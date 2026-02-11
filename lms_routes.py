from fastapi import APIRouter, HTTPException, status, Depends
from lms_models import *
from auth import get_password_hash, verify_password, create_access_token, decode_token
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import timedelta, datetime
from typing import List, Optional

router = APIRouter()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

def serialize_doc(doc):
    """Convert MongoDB document to JSON serializable format, excluding _id"""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if k != '_id'}
    return doc

# Helper function to get current user from token
async def get_current_user(token: str):
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"email": payload.get("sub")})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

# ============= ADMIN ROUTES =============

@router.get("/admin/dashboard/stats")
async def get_admin_dashboard_stats():
    """Get dashboard statistics for admin"""
    total_students = await db.users.count_documents({"role": "student"})
    total_teachers = await db.users.count_documents({"role": "teacher"})
    total_batches = await db.batches.count_documents({})
    total_revenue = await db.payments.aggregate([
        {"$match": {"status": "completed"}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)
    
    revenue = total_revenue[0]["total"] if total_revenue else 0
    
    # Active students count
    active_students = await db.student_profiles.count_documents({"status": "active"})
    
    return {
        "total_students": total_students,
        "total_teachers": total_teachers,
        "total_batches": total_batches,
        "total_revenue": revenue,
        "active_students": active_students
    }

@router.get("/admin/students")
async def get_all_students(skip: int = 0, limit: int = 50):
    """Get all students with their profiles"""
    students = await db.users.find({"role": "student"}).skip(skip).limit(limit).to_list(limit)
    
    # Get student profiles
    for student in students:
        profile = await db.student_profiles.find_one({"user_id": student["id"]})
        student["profile"] = profile
    
    return {"students": serialize_doc(students)}

@router.get("/admin/teachers")
async def get_all_teachers(skip: int = 0, limit: int = 50):
    """Get all teachers with their profiles"""
    teachers = await db.users.find({"role": "teacher"}).skip(skip).limit(limit).to_list(limit)
    
    # Get teacher profiles
    for teacher in teachers:
        profile = await db.teacher_profiles.find_one({"user_id": teacher["id"]})
        teacher["profile"] = profile
    
    return {"teachers": serialize_doc(teachers)}

@router.post("/admin/courses", status_code=status.HTTP_201_CREATED)
async def create_course(course_data: CourseCreate):
    """Create a new course"""
    course = Course(**course_data.dict())
    await db.courses.insert_one(course.dict())
    return {"message": "Course created successfully", "course_id": course.id}

@router.get("/admin/courses")
async def get_all_courses():
    """Get all courses"""
    courses = await db.courses.find().to_list(100)
    return {"courses": serialize_doc(courses)}

@router.post("/admin/batches", status_code=status.HTTP_201_CREATED)
async def create_batch(batch_data: BatchCreate):
    """Create a new batch"""
    batch = Batch(**batch_data.dict())
    await db.batches.insert_one(batch.dict())
    return {"message": "Batch created successfully", "batch_id": batch.id}

@router.post("/admin/batches/{batch_id}/enroll")
async def enroll_student_in_batch(batch_id: str, student_id: str):
    """Enroll a student in a batch"""
    # Check if batch exists and has capacity
    batch = await db.batches.find_one({"id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    if len(batch.get("enrolled_students", [])) >= batch.get("max_students", 30):
        raise HTTPException(status_code=400, detail="Batch is full")
    
    # Add student to batch
    await db.batches.update_one(
        {"id": batch_id},
        {"$addToSet": {"enrolled_students": student_id}}
    )
    
    # Update student profile
    await db.student_profiles.update_one(
        {"user_id": student_id},
        {"$set": {"batch_id": batch_id}, "$addToSet": {"enrolled_courses": batch["course_id"]}}
    )
    
    return {"message": "Student enrolled successfully"}

# ============= TEACHER ROUTES =============

@router.get("/teacher/dashboard/{teacher_id}")
async def get_teacher_dashboard(teacher_id: str):
    """Get teacher dashboard data"""
    # Get teacher profile
    teacher_profile = await db.teacher_profiles.find_one({"user_id": teacher_id})
    if not teacher_profile:
        raise HTTPException(status_code=404, detail="Teacher profile not found")
    
    # Get assigned batches
    batches = await db.batches.find({"teacher_id": teacher_id}).to_list(50)
    
    # Get total students
    total_students = 0
    for batch in batches:
        total_students += len(batch.get("enrolled_students", []))
    
    # Get upcoming classes
    upcoming_classes = await db.live_classes.find({
        "teacher_id": teacher_id,
        "scheduled_date": {"$gte": datetime.utcnow()},
        "status": "scheduled"
    }).sort("scheduled_date", 1).limit(5).to_list(5)
    
    return {
        "profile": serialize_doc(teacher_profile),
        "total_batches": len(batches),
        "total_students": total_students,
        "batches": serialize_doc(batches),
        "upcoming_classes": serialize_doc(upcoming_classes)
    }

@router.get("/teacher/batches/{teacher_id}")
async def get_teacher_batches(teacher_id: str):
    """Get all batches assigned to teacher"""
    batches = await db.batches.find({"teacher_id": teacher_id}).to_list(100)
    
    # Get course details for each batch
    for batch in batches:
        course = await db.courses.find_one({"id": batch["course_id"]})
        batch["course"] = serialize_doc(course)
    
    return {"batches": serialize_doc(batches)}

@router.post("/teacher/attendance", status_code=status.HTTP_201_CREATED)
async def mark_attendance(attendance_data: AttendanceCreate, teacher_id: str):
    """Mark attendance for a student"""
    attendance = Attendance(**attendance_data.dict(), marked_by=teacher_id)
    await db.attendance.insert_one(attendance.dict())
    return {"message": "Attendance marked successfully"}

@router.post("/teacher/assignments", status_code=status.HTTP_201_CREATED)
async def create_assignment(assignment_data: AssignmentCreate, teacher_id: str):
    """Create a new assignment"""
    assignment = Assignment(**assignment_data.dict(), teacher_id=teacher_id)
    await db.assignments.insert_one(assignment.dict())
    return {"message": "Assignment created successfully", "assignment_id": assignment.id}

@router.get("/teacher/assignments/{assignment_id}/submissions")
async def get_assignment_submissions(assignment_id: str):
    """Get all submissions for an assignment"""
    submissions = await db.assignment_submissions.find({"assignment_id": assignment_id}).to_list(100)
    
    # Get student details for each submission
    for submission in submissions:
        student = await db.users.find_one({"id": submission["student_id"]})
        submission["student"] = {"name": student["name"], "email": student["email"]}
    
    return {"submissions": serialize_doc(submissions)}

@router.put("/teacher/assignments/{submission_id}/grade")
async def grade_assignment(submission_id: str, marks: int, feedback: str):
    """Grade a student's assignment submission"""
    await db.assignment_submissions.update_one(
        {"id": submission_id},
        {"$set": {"marks_obtained": marks, "feedback": feedback, "status": "graded"}}
    )
    return {"message": "Assignment graded successfully"}

@router.post("/teacher/live-class", status_code=status.HTTP_201_CREATED)
async def create_live_class(class_data: LiveClassCreate, teacher_id: str):
    """Create a live class session"""
    live_class = LiveClass(**class_data.dict(), teacher_id=teacher_id)
    await db.live_classes.insert_one(live_class.dict())
    return {"message": "Live class scheduled successfully", "class_id": live_class.id}

# ============= STUDENT ROUTES =============

@router.get("/student/dashboard/{student_id}")
async def get_student_dashboard(student_id: str):
    """Get student dashboard data"""
    # Get student profile
    student_profile = await db.student_profiles.find_one({"user_id": student_id})
    if not student_profile:
        raise HTTPException(status_code=404, detail="Student profile not found")
    
    # Get enrolled courses
    courses = []
    for course_id in student_profile.get("enrolled_courses", []):
        course = await db.courses.find_one({"id": course_id})
        if course:
            courses.append(course)
    
    # Get pending assignments
    batch_id = student_profile.get("batch_id")
    pending_assignments = []
    if batch_id:
        assignments = await db.assignments.find({"batch_id": batch_id, "status": "active"}).to_list(50)
        for assignment in assignments:
            submission = await db.assignment_submissions.find_one({
                "assignment_id": assignment["id"],
                "student_id": student_id
            })
            if not submission:
                pending_assignments.append(assignment)
    
    # Get upcoming classes
    upcoming_classes = []
    if batch_id:
        upcoming_classes = await db.live_classes.find({
            "batch_id": batch_id,
            "scheduled_date": {"$gte": datetime.utcnow()},
            "status": "scheduled"
        }).sort("scheduled_date", 1).limit(5).to_list(5)
    
    # Get attendance percentage
    total_classes = await db.attendance.count_documents({"student_id": student_id})
    present_classes = await db.attendance.count_documents({
        "student_id": student_id,
        "status": "present"
    })
    attendance_percentage = (present_classes / total_classes * 100) if total_classes > 0 else 0
    
    return {
        "profile": serialize_doc(student_profile),
        "courses": serialize_doc(courses),
        "pending_assignments": serialize_doc(pending_assignments),
        "upcoming_classes": serialize_doc(upcoming_classes),
        "attendance_percentage": round(attendance_percentage, 2)
    }

@router.get("/student/assignments/{student_id}")
async def get_student_assignments(student_id: str):
    """Get all assignments for a student"""
    student_profile = await db.student_profiles.find_one({"user_id": student_id})
    if not student_profile or not student_profile.get("batch_id"):
        return {"assignments": []}
    
    assignments = await db.assignments.find({"batch_id": student_profile["batch_id"]}).to_list(100)
    
    # Check submission status for each assignment
    for assignment in assignments:
        submission = await db.assignment_submissions.find_one({
            "assignment_id": assignment["id"],
            "student_id": student_id
        })
        assignment["submission"] = submission
    
    return {"assignments": serialize_doc(assignments), "submissions": serialize_doc([a.get("submission") for a in assignments if a.get("submission")])}

@router.post("/student/assignments/{assignment_id}/submit", status_code=status.HTTP_201_CREATED)
async def submit_assignment(assignment_id: str, submission_data: dict):
    """Submit an assignment"""
    student_id = submission_data.get("student_id")
    content = submission_data.get("content", "")
    attachments = submission_data.get("attachments", [])
    
    # Check if already submitted
    existing = await db.assignment_submissions.find_one({
        "assignment_id": assignment_id,
        "student_id": student_id
    })
    if existing:
        raise HTTPException(status_code=400, detail="Assignment already submitted")
    
    submission = AssignmentSubmission(
        assignment_id=assignment_id,
        student_id=student_id,
        content=content,
        attachments=attachments
    )
    await db.assignment_submissions.insert_one(submission.dict())
    return {"message": "Assignment submitted successfully"}

@router.get("/student/attendance/{student_id}")
async def get_student_attendance(student_id: str):
    """Get attendance records for a student"""
    attendance = await db.attendance.find({"student_id": student_id}).sort("date", -1).to_list(100)
    
    # Calculate statistics
    total = len(attendance)
    present = len([a for a in attendance if a["status"] == "present"])
    absent = len([a for a in attendance if a["status"] == "absent"])
    late = len([a for a in attendance if a["status"] == "late"])
    
    return {
        "attendance_records": serialize_doc(attendance),
        "statistics": {
            "total": total,
            "present": present,
            "absent": absent,
            "late": late,
            "percentage": round((present / total * 100), 2) if total > 0 else 0
        }
    }

@router.get("/student/progress/{student_id}")
async def get_student_progress(student_id: str):
    """Get learning progress for a student"""
    progress_records = await db.progress.find({"student_id": student_id}).to_list(500)
    
    # Group by course
    course_progress = {}
    for record in progress_records:
        course_id = record["course_id"]
        if course_id not in course_progress:
            course_progress[course_id] = {
                "completed_lessons": 0,
                "total_time_minutes": 0
            }
        if record["completed"]:
            course_progress[course_id]["completed_lessons"] += 1
        course_progress[course_id]["total_time_minutes"] += record["time_spent_minutes"]
    
    return {"progress": course_progress}

@router.get("/student/progress-reports/{student_id}")
async def get_student_progress_reports(student_id: str):
    """Get all progress reports for a student"""
    reports = await db.progress_reports.find({"student_id": student_id}).sort("created_at", -1).to_list(50)
    return {"reports": serialize_doc(reports)}

# ============= COMMON ROUTES =============

@router.get("/courses")
async def get_active_courses():
    """Get all active courses"""
    courses = await db.courses.find({"is_active": True}).to_list(100)
    return {"courses": serialize_doc(courses)}

@router.get("/announcements")
async def get_announcements(user_id: str, batch_id: Optional[str] = None):
    """Get announcements for a user"""
    query = {
        "$or": [
            {"target_audience": "all"},
            {"target_audience": batch_id} if batch_id else {}
        ],
        "$or": [
            {"expires_at": None},
            {"expires_at": {"$gte": datetime.utcnow()}}
        ]
    }
    announcements = await db.announcements.find(query).sort("created_at", -1).limit(20).to_list(20)
    return {"announcements": serialize_doc(announcements)}

@router.post("/announcements", status_code=status.HTTP_201_CREATED)
async def create_announcement(announcement_data: AnnouncementCreate, user_id: str):
    """Create an announcement (admin/teacher only)"""
    announcement = Announcement(**announcement_data.dict(), created_by=user_id)
    await db.announcements.insert_one(announcement.dict())
    return {"message": "Announcement created successfully"}
