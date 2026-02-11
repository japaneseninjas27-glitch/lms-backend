from fastapi import APIRouter, HTTPException, status, UploadFile, File
from lms_models import BlogPost, BlogPostCreate, BlogComment, BlogReaction
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import datetime
import uuid
import shutil
from pathlib import Path
from typing import List, Optional

router = APIRouter()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Upload directory for blog media
BLOG_UPLOAD_DIR = Path("/app/backend/uploads/blog")
BLOG_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def serialize_doc(doc):
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if k != '_id'}
    return doc

# ============= BLOG POSTS =============

@router.get("/posts")
async def get_all_posts(limit: int = 20, skip: int = 0):
    """Get all published blog posts (public)"""
    posts = await db.blog_posts.find({"is_published": True}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    total = await db.blog_posts.count_documents({"is_published": True})
    return {"posts": serialize_doc(posts), "total": total}

@router.get("/posts/{post_id}")
async def get_post(post_id: str):
    """Get a single blog post with comments"""
    post = await db.blog_posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    comments = await db.blog_comments.find({"post_id": post_id}).sort("created_at", -1).to_list(100)
    reactions = await db.blog_reactions.find({"post_id": post_id}).to_list(500)
    
    return {
        "post": serialize_doc(post),
        "comments": serialize_doc(comments),
        "reactions": serialize_doc(reactions)
    }

@router.post("/posts")
async def create_post(post_data: BlogPostCreate, author_id: str, author_name: str, author_role: str):
    """Create a new blog post (Admin/Teacher only)"""
    if author_role not in ["admin", "teacher"]:
        raise HTTPException(status_code=403, detail="Only admins and teachers can create posts")
    
    post = BlogPost(
        author_id=author_id,
        author_name=author_name,
        author_role=author_role,
        **post_data.dict()
    )
    await db.blog_posts.insert_one(post.dict())
    return {"message": "Post created successfully", "post_id": post.id}

@router.post("/posts/upload-media")
async def upload_blog_media(file: UploadFile = File(...)):
    """Upload media (image/video) for blog post"""
    allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'video/mp4', 'video/webm']
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="File type not allowed")
    
    # Check file size (max 50MB for videos, 10MB for images)
    max_size = 50 * 1024 * 1024 if file.content_type.startswith('video') else 10 * 1024 * 1024
    
    file_extension = file.filename.split('.')[-1]
    unique_filename = f"blog_{uuid.uuid4().hex[:12]}.{file_extension}"
    file_path = BLOG_UPLOAD_DIR / unique_filename
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    media_type = "video" if file.content_type.startswith('video') else "image"
    
    return {
        "url": f"/uploads/blog/{unique_filename}",
        "media_type": media_type
    }

@router.put("/posts/{post_id}")
async def update_post(post_id: str, updates: dict, user_id: str):
    """Update a blog post"""
    post = await db.blog_posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post["author_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    updates["updated_at"] = datetime.utcnow()
    await db.blog_posts.update_one({"id": post_id}, {"$set": updates})
    return {"message": "Post updated"}

@router.delete("/posts/{post_id}")
async def delete_post(post_id: str, user_id: str, user_role: str):
    """Delete a blog post"""
    post = await db.blog_posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post["author_id"] != user_id and user_role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.blog_posts.delete_one({"id": post_id})
    await db.blog_comments.delete_many({"post_id": post_id})
    await db.blog_reactions.delete_many({"post_id": post_id})
    return {"message": "Post deleted"}

# ============= COMMENTS =============

@router.post("/posts/{post_id}/comments")
async def add_comment(post_id: str, content: str, user_id: str, user_name: str):
    """Add a comment to a post"""
    post = await db.blog_posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    comment = BlogComment(
        post_id=post_id,
        user_id=user_id,
        user_name=user_name,
        content=content
    )
    await db.blog_comments.insert_one(comment.dict())
    
    # Update comment count
    await db.blog_posts.update_one({"id": post_id}, {"$inc": {"comments_count": 1}})
    
    return {"message": "Comment added", "comment_id": comment.id}

@router.delete("/comments/{comment_id}")
async def delete_comment(comment_id: str, user_id: str, user_role: str):
    """Delete a comment"""
    comment = await db.blog_comments.find_one({"id": comment_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment["user_id"] != user_id and user_role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    await db.blog_comments.delete_one({"id": comment_id})
    await db.blog_posts.update_one({"id": comment["post_id"]}, {"$inc": {"comments_count": -1}})
    return {"message": "Comment deleted"}

# ============= REACTIONS =============

@router.post("/posts/{post_id}/react")
async def toggle_reaction(post_id: str, user_id: str, reaction_type: str = "like"):
    """Toggle reaction on a post"""
    existing = await db.blog_reactions.find_one({"post_id": post_id, "user_id": user_id})
    
    if existing:
        # Remove reaction
        await db.blog_reactions.delete_one({"id": existing["id"]})
        await db.blog_posts.update_one({"id": post_id}, {"$inc": {"likes_count": -1}})
        return {"message": "Reaction removed", "reacted": False}
    else:
        # Add reaction
        reaction = BlogReaction(
            post_id=post_id,
            user_id=user_id,
            reaction_type=reaction_type
        )
        await db.blog_reactions.insert_one(reaction.dict())
        await db.blog_posts.update_one({"id": post_id}, {"$inc": {"likes_count": 1}})
        return {"message": "Reaction added", "reacted": True}

@router.get("/posts/{post_id}/user-reaction")
async def get_user_reaction(post_id: str, user_id: str):
    """Check if user has reacted to a post"""
    reaction = await db.blog_reactions.find_one({"post_id": post_id, "user_id": user_id})
    return {"reacted": reaction is not None, "reaction_type": reaction["reaction_type"] if reaction else None}
