from fastapi import APIRouter, HTTPException, status, UploadFile, File
from lms_models import JobApplication, JobApplicationCreate
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import datetime
import uuid
import shutil
from pathlib import Path

router = APIRouter()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Upload directory for resumes

UPLOAD_DIR = Path("/tmp/uploads")
RESUME_UPLOAD_DIR = UPLOAD_DIR / "resumes"

RESUME_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def serialize_doc(doc):
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if k != '_id'}
    return doc

# ============= JOB APPLICATIONS =============

@router.post("/apply")
async def submit_job_application(application_data: JobApplicationCreate):
    """Submit a new job application"""
    # Check if email already applied
    existing = await db.job_applications.find_one({"email": application_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="You have already applied. We will contact you soon!")
    
    application = JobApplication(**application_data.dict())
    await db.job_applications.insert_one(application.dict())
    
    return {
        "message": "Application submitted successfully! We will review and contact you soon.",
        "application_id": application.id
    }

@router.post("/apply/upload-resume")
async def upload_resume(application_id: str, file: UploadFile = File(...)):
    """Upload resume for job application"""
    allowed_types = ['application/pdf', 'application/msword', 
                     'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only PDF and DOC/DOCX files are allowed")
    
    # Check file size (max 5MB)
    if file.size and file.size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be less than 5MB")
    
    file_extension = file.filename.split('.')[-1]
    unique_filename = f"resume_{application_id}_{uuid.uuid4().hex[:8]}.{file_extension}"
    file_path = RESUME_UPLOAD_DIR / unique_filename
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Update application with resume URL
    resume_url = f"/uploads/resumes/{unique_filename}"
    await db.job_applications.update_one(
        {"id": application_id},
        {"$set": {"resume_url": resume_url}}
    )
    
    return {"message": "Resume uploaded successfully", "url": resume_url}

@router.get("/applications")
async def get_all_applications(status_filter: str = None):
    """Get all job applications (Admin only)"""
    query = {}
    if status_filter and status_filter != "all":
        query["status"] = status_filter
    
    applications = await db.job_applications.find(query).sort("applied_at", -1).to_list(500)
    
    # Count by status
    total = await db.job_applications.count_documents({})
    pending = await db.job_applications.count_documents({"status": "pending"})
    reviewed = await db.job_applications.count_documents({"status": "reviewed"})
    shortlisted = await db.job_applications.count_documents({"status": "shortlisted"})
    
    return {
        "applications": serialize_doc(applications),
        "stats": {
            "total": total,
            "pending": pending,
            "reviewed": reviewed,
            "shortlisted": shortlisted
        }
    }

@router.get("/applications/{application_id}")
async def get_application(application_id: str):
    """Get a specific job application"""
    application = await db.job_applications.find_one({"id": application_id})
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return serialize_doc(application)

@router.put("/applications/{application_id}/status")
async def update_application_status(application_id: str, new_status: str, admin_notes: str = None):
    """Update job application status (Admin only)"""
    valid_statuses = ["pending", "reviewed", "shortlisted", "rejected", "hired"]
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    update_data = {
        "status": new_status,
        "reviewed_at": datetime.utcnow()
    }
    if admin_notes:
        update_data["admin_notes"] = admin_notes
    
    await db.job_applications.update_one(
        {"id": application_id},
        {"$set": update_data}
    )
    
    return {"message": f"Application status updated to {new_status}"}

UPLOAD_DIR = Path("/tmp/uploads")

@router.delete("/applications/{application_id}")
async def delete_application(application_id: str):
    """Delete a job application (Admin only)"""
    
    application = await db.job_applications.find_one({"id": application_id})
    
    if application and application.get("resume_url"):
        # Build correct file path
        file_relative_path = application["resume_url"].lstrip("/")
        file_path = UPLOAD_DIR / file_relative_path

        if file_path.exists():
            file_path.unlink()

    await db.job_applications.delete_one({"id": application_id})
    
    return {"message": "Application deleted"}
