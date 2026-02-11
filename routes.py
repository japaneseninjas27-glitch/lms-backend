from fastapi import APIRouter, HTTPException, status
from models import (
    UserCreate, UserLogin, User, UserResponse,
    StudentInquiryCreate, StudentInquiry,
    ContactFormCreate, ContactForm,
    NewsletterSubscriptionCreate, NewsletterSubscription
)
from auth import get_password_hash, verify_password, create_access_token
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import timedelta

def serialize_doc(doc):
    """Convert MongoDB document to JSON serializable format"""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        # Remove MongoDB ObjectId and convert to dict
        serialized = {k: v for k, v in doc.items() if k != '_id'}
        return serialized
    return doc

router = APIRouter()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Note: Authentication routes are in auth_routes.py

# Student Inquiry Routes
@router.post("/inquiries", status_code=status.HTTP_201_CREATED)
async def create_inquiry(inquiry_data: StudentInquiryCreate):
    """Submit student inquiry from welcome modal"""
    inquiry = StudentInquiry(**inquiry_data.dict())
    await db.inquiries.insert_one(inquiry.dict())
    
    return {
        "message": "Inquiry submitted successfully",
        "inquiry_id": inquiry.id
    }

@router.get("/inquiries")
async def get_inquiries(skip: int = 0, limit: int = 100):
    """Get all student inquiries (Admin endpoint - add auth later)"""
    inquiries = await db.inquiries.find().sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"inquiries": serialize_doc(inquiries)}

@router.get("/inquiries/{inquiry_id}")
async def get_inquiry(inquiry_id: str):
    """Get a specific inquiry by ID"""
    inquiry = await db.inquiries.find_one({"id": inquiry_id})
    if not inquiry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inquiry not found"
        )
    return serialize_doc(inquiry)

# Contact Form Routes
@router.post("/contact", status_code=status.HTTP_201_CREATED)
async def submit_contact_form(contact_data: ContactFormCreate):
    """Submit contact form"""
    contact = ContactForm(**contact_data.dict())
    await db.contacts.insert_one(contact.dict())
    
    return {
        "message": "Message sent successfully",
        "contact_id": contact.id
    }

@router.get("/contacts")
async def get_contacts(skip: int = 0, limit: int = 100):
    """Get all contact form submissions (Admin endpoint)"""
    contacts = await db.contacts.find().sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"contacts": serialize_doc(contacts)}

# Newsletter Routes
@router.post("/newsletter/subscribe", status_code=status.HTTP_201_CREATED)
async def subscribe_newsletter(subscription_data: NewsletterSubscriptionCreate):
    """Subscribe to newsletter"""
    # Check if already subscribed
    existing = await db.newsletter_subscriptions.find_one({"email": subscription_data.email})
    if existing:
        if existing.get("subscribed"):
            return {"message": "Email already subscribed"}
        else:
            # Resubscribe
            await db.newsletter_subscriptions.update_one(
                {"email": subscription_data.email},
                {"$set": {"subscribed": True}}
            )
            return {"message": "Subscribed successfully"}
    
    # Create new subscription
    subscription = NewsletterSubscription(email=subscription_data.email)
    await db.newsletter_subscriptions.insert_one(subscription.dict())
    
    return {"message": "Subscribed successfully"}

@router.get("/newsletter/subscriptions")
async def get_subscriptions(skip: int = 0, limit: int = 100):
    """Get all newsletter subscriptions (Admin endpoint)"""
    subscriptions = await db.newsletter_subscriptions.find(
        {"subscribed": True}
    ).skip(skip).limit(limit).to_list(limit)
    return {"subscriptions": serialize_doc(subscriptions)}