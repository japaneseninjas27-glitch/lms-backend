from fastapi import APIRouter, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from models import UserCreate, UserLogin, UserResponse
from lms_models import UserRole, StudentProfile, TeacherProfile
from auth import get_password_hash, verify_password, create_access_token
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import timedelta, datetime
import uuid
import shutil
from pathlib import Path

router = APIRouter()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Upload directory
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

# Enhanced Signup with Role
@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(user_data: UserCreate, role: str = "student"):
    """Create a new user account with role"""
    # Check if user already exists
    existing_user = await db.users.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Validate role
    if role not in ["student", "teacher", "admin"]:
        role = "student"
    
    # Create user object
    from lms_models import UserInDB
    user = UserInDB(
        name=user_data.name,
        email=user_data.email,
        phone=user_data.phone,
        role=role,
        password=get_password_hash(user_data.password)
    )
    
    # Insert into database
    await db.users.insert_one(user.dict())
    
    # Create role-specific profile
    if role == "student":
        # Generate enrollment number
        enrollment_number = f"JN{datetime.now().year}{str(uuid.uuid4())[:6].upper()}"
        student_profile = StudentProfile(
            user_id=user.id,
            enrollment_number=enrollment_number,
            city=user_data.city if hasattr(user_data, 'city') else "",
            state=user_data.state if hasattr(user_data, 'state') else ""
        )
        await db.student_profiles.insert_one(student_profile.dict())
    elif role == "teacher":
        teacher_profile = TeacherProfile(
            user_id=user.id,
            qualification="",
            experience_years=0
        )
        await db.teacher_profiles.insert_one(teacher_profile.dict())
    
    return {
        "message": "User created successfully",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role
        }
    }

# Enhanced Login with Role
@router.post("/auth/login")
async def login(credentials: UserLogin):
    """Login user and return JWT token with role"""
    # Find user
    user = await db.users.find_one({"email": credentials.email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Verify password
    if not verify_password(credentials.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # Create access token
    access_token = create_access_token(
        data={"sub": user["email"], "user_id": user["id"], "role": user["role"]},
        expires_delta=timedelta(days=7)
    )
    
    return {
        "message": "Login successful",
        "token": access_token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "profile_image": user.get("profile_image")
        }
    }

# Upload Profile Photo
@router.post("/upload/profile-photo")
async def upload_profile_photo(user_id: str, file: UploadFile = File(...)):
    """Upload profile photo"""
    # Validate file type
    if not file.content_type.startswith('image/'):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    # Create unique filename
    file_extension = file.filename.split('.')[-1]
    unique_filename = f"profile_{user_id}_{uuid.uuid4().hex[:8]}.{file_extension}"
    file_path = UPLOAD_DIR / unique_filename
    
    # Save file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Update user profile image URL
    file_url = f"/uploads/{unique_filename}"
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"profile_image": file_url}}
    )
    
    return {"message": "Profile photo uploaded", "url": file_url}

# Get uploaded file
@router.get("/uploads/{filename}")
async def get_uploaded_file(filename: str):
    """Serve uploaded files"""
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)

def serialize_doc(doc):
    """Convert MongoDB document to JSON serializable format, excluding _id"""
    if doc is None:
        return None
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if k != '_id'}
    return doc

# Get User Profile
@router.get("/profile/{user_id}")
async def get_user_profile(user_id: str):
    """Get complete user profile with role-specific data"""
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    profile_data = {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "phone": user["phone"],
        "role": user["role"],
        "profile_image": user.get("profile_image"),
        "created_at": user["created_at"]
    }
    
    # Get role-specific profile
    if user["role"] == "student":
        student_profile = await db.student_profiles.find_one({"user_id": user_id})
        profile_data["student_profile"] = serialize_doc(student_profile)
    elif user["role"] == "teacher":
        teacher_profile = await db.teacher_profiles.find_one({"user_id": user_id})
        profile_data["teacher_profile"] = serialize_doc(teacher_profile)
    
    return profile_data

# Update Profile
@router.put("/profile/{user_id}")
async def update_user_profile(user_id: str, updates: dict):
    """Update user profile"""
    # Update main user data
    user_updates = {}
    if "name" in updates:
        user_updates["name"] = updates["name"]
    if "phone" in updates:
        user_updates["phone"] = updates["phone"]
    
    if user_updates:
        await db.users.update_one(
            {"id": user_id},
            {"$set": user_updates}
        )
    
    # Update role-specific profile
    user = await db.users.find_one({"id": user_id})
    if user["role"] == "student":
        student_updates = {}
        if "city" in updates:
            student_updates["city"] = updates["city"]
        if "state" in updates:
            student_updates["state"] = updates["state"]
        if "current_level" in updates:
            student_updates["current_level"] = updates["current_level"]
        
        if student_updates:
            await db.student_profiles.update_one(
                {"user_id": user_id},
                {"$set": student_updates}
            )
    
    return {"message": "Profile updated successfully"}
