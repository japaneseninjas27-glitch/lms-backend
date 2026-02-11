from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
import uuid

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str
    city: str
    state: str
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: EmailStr
    phone: str
    city: str
    state: str
    password: str  # This will be hashed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class UserResponse(BaseModel):
    id: str
    name: str
    email: str

class StudentInquiryCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str
    city: str
    state: str
    current_level: str  # none/n5/n4/n3/n2/n1
    reason: str

class StudentInquiry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: EmailStr
    phone: str
    city: str
    state: str
    current_level: str
    reason: str
    status: str = "new"  # new/contacted/enrolled/not_interested
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class ContactFormCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str
    course: Optional[str] = None
    message: str

class ContactForm(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    email: EmailStr
    phone: str
    course: Optional[str] = None
    message: str
    status: str = "new"  # new/replied
    created_at: datetime = Field(default_factory=datetime.utcnow)

class NewsletterSubscriptionCreate(BaseModel):
    email: EmailStr

class NewsletterSubscription(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: EmailStr
    subscribed: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)