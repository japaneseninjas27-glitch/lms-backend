from fastapi import APIRouter, HTTPException, status, UploadFile, File
from lms_models import (
    DailySessionStatus, DailySessionStatusCreate, StudyNote, StudyNoteCreate,
    Assignment, AssignmentCreate, Attendance, AttendanceCreate, LiveClass, LiveClassCreate
)
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import datetime, date
import uuid
import shutil
from pathlib import Path
from typing import List

router = APIRouter()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Upload directory for notes
NOTES_UPLOAD_DIR = Path("/app/backend/uploads/notes")
NOTES_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

def serialize_doc(doc):
    """Convert MongoDB document to JSON serializable format"""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if k != '_id'}
    return doc

# ============= TEACHER DASHBOARD =============

@router.get("/dashboard/{teacher_id}")
async def get_teacher_dashboard(teacher_id: str):
    """Get comprehensive teacher dashboard data"""
    # Get teacher profile
    teacher = await db.users.find_one({"id": teacher_id, "role": "teacher"})
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")
    
    teacher_profile = await db.teacher_profiles.find_one({"user_id": teacher_id})
    
    # Get assigned batches
    batches = await db.batches.find({"teacher_id": teacher_id}).to_list(50)
    
    # Get total students across all batches
    total_students = 0
    for batch in batches:
        total_students += len(batch.get("enrolled_students", []))
    
    # Get upcoming classes
    upcoming_classes = await db.live_classes.find({
        "teacher_id": teacher_id,
        "scheduled_date": {"$gte": datetime.utcnow()},
        "status": "scheduled"
    }).sort("scheduled_date", 1).limit(5).to_list(5)
    
    # Get pending assignments to grade
    pending_submissions = await db.assignment_submissions.find({
        "status": "pending"
    }).to_list(100)
    
    # Filter for teacher's batches
    teacher_batch_ids = [b["id"] for b in batches]
    assignments = await db.assignments.find({
        "batch_id": {"$in": teacher_batch_ids}
    }).to_list(100)
    assignment_ids = [a["id"] for a in assignments]
    
    pending_to_grade = [s for s in pending_submissions if s.get("assignment_id") in assignment_ids]
    
    # Get recent session statuses
    recent_sessions = await db.daily_session_status.find({
        "teacher_id": teacher_id
    }).sort("date", -1).limit(5).to_list(5)
    
    return {
        "profile": serialize_doc(teacher_profile),
        "total_batches": len(batches),
        "total_students": total_students,
        "batches": serialize_doc(batches),
        "upcoming_classes": serialize_doc(upcoming_classes),
        "pending_to_grade": len(pending_to_grade),
        "recent_sessions": serialize_doc(recent_sessions)
    }

# ============= BATCH & STUDENTS =============

@router.get("/batches/{teacher_id}")
async def get_teacher_batches(teacher_id: str):
    """Get all batches assigned to teacher with details"""
    batches = await db.batches.find({"teacher_id": teacher_id}).to_list(100)
    
    for batch in batches:
        # Get course details
        course = await db.courses.find_one({"id": batch["course_id"]})
        batch["course"] = serialize_doc(course)
        
        # Get student count and details
        student_ids = batch.get("enrolled_students", [])
        students = await db.users.find({"id": {"$in": student_ids}}).to_list(100)
        batch["students"] = serialize_doc(students)
        batch["student_count"] = len(students)
    
    return {"batches": serialize_doc(batches)}

@router.get("/batch/{batch_id}/students")
async def get_batch_students(batch_id: str):
    """Get all students in a batch with their details"""
    batch = await db.batches.find_one({"id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    student_ids = batch.get("enrolled_students", [])
    students = []
    
    for sid in student_ids:
        user = await db.users.find_one({"id": sid})
        if user:
            profile = await db.student_profiles.find_one({"user_id": sid})
            # Get attendance stats
            total_attendance = await db.attendance.count_documents({"student_id": sid, "batch_id": batch_id})
            present = await db.attendance.count_documents({"student_id": sid, "batch_id": batch_id, "status": "present"})
            
            students.append({
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "phone": user["phone"],
                "profile": serialize_doc(profile),
                "attendance_percentage": round((present / total_attendance * 100), 2) if total_attendance > 0 else 0
            })
    
    return {"students": students}

# ============= ATTENDANCE =============

@router.post("/attendance")
async def mark_attendance(attendance_data: AttendanceCreate, teacher_id: str):
    """Mark attendance for a student"""
    attendance = Attendance(
        **attendance_data.dict(),
        marked_by=teacher_id
    )
    await db.attendance.insert_one(attendance.dict())
    return {"message": "Attendance marked successfully", "id": attendance.id}

@router.post("/attendance/bulk")
async def mark_bulk_attendance(batch_id: str, attendance_date: str, attendance_list: List[dict], teacher_id: str):
    """Mark attendance for multiple students at once"""
    attendance_records = []
    for item in attendance_list:
        attendance = Attendance(
            batch_id=batch_id,
            student_id=item["student_id"],
            date=attendance_date,
            status=item["status"],
            remarks=item.get("remarks"),
            marked_by=teacher_id
        )
        attendance_records.append(attendance.dict())
    
    if attendance_records:
        await db.attendance.insert_many(attendance_records)
    
    return {"message": f"Attendance marked for {len(attendance_records)} students"}

@router.get("/attendance/{batch_id}")
async def get_batch_attendance(batch_id: str, attendance_date: str = None):
    """Get attendance records for a batch"""
    query = {"batch_id": batch_id}
    if attendance_date:
        query["date"] = attendance_date
    
    attendance = await db.attendance.find(query).sort("date", -1).to_list(500)
    return {"attendance": serialize_doc(attendance)}

# ============= DAILY SESSION STATUS =============

@router.post("/session-status")
async def create_session_status(status_data: DailySessionStatusCreate, teacher_id: str):
    """Create daily session status - what was taught"""
    session_status = DailySessionStatus(
        **status_data.dict(),
        teacher_id=teacher_id
    )
    await db.daily_session_status.insert_one(session_status.dict())
    return {"message": "Session status recorded", "id": session_status.id}

@router.get("/session-status/{batch_id}")
async def get_session_statuses(batch_id: str, limit: int = 30):
    """Get session status history for a batch"""
    statuses = await db.daily_session_status.find({
        "batch_id": batch_id
    }).sort("date", -1).limit(limit).to_list(limit)
    return {"sessions": serialize_doc(statuses)}

@router.put("/session-status/{status_id}")
async def update_session_status(status_id: str, updates: dict):
    """Update a session status"""
    await db.daily_session_status.update_one(
        {"id": status_id},
        {"$set": updates}
    )
    return {"message": "Session status updated"}

# ============= STUDY NOTES =============

@router.post("/notes/upload")
async def upload_study_note(
    batch_id: str,
    title: str,
    teacher_id: str,
    file: UploadFile = File(...),
    description: str = None,
    topic: str = None
):
    """Upload study notes for a batch"""
    # Validate file type
    allowed_types = ['application/pdf', 'image/jpeg', 'image/png', 'application/msword',
                     'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="File type not allowed")
    
    # Create unique filename
    file_extension = file.filename.split('.')[-1]
    unique_filename = f"note_{batch_id}_{uuid.uuid4().hex[:8]}.{file_extension}"
    file_path = NOTES_UPLOAD_DIR / unique_filename
    
    # Save file
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Create note record
    note = StudyNote(
        batch_id=batch_id,
        teacher_id=teacher_id,
        title=title,
        description=description,
        file_url=f"/uploads/notes/{unique_filename}",
        file_type=file_extension,
        topic=topic
    )
    await db.study_notes.insert_one(note.dict())
    
    return {"message": "Note uploaded successfully", "id": note.id, "url": note.file_url}

@router.get("/notes/{batch_id}")
async def get_batch_notes(batch_id: str):
    """Get all study notes for a batch"""
    notes = await db.study_notes.find({"batch_id": batch_id}).sort("created_at", -1).to_list(100)
    return {"notes": serialize_doc(notes)}

@router.delete("/notes/{note_id}")
async def delete_note(note_id: str):
    """Delete a study note"""
    note = await db.study_notes.find_one({"id": note_id})
    if note:
        # Delete file
        file_path = Path("/app/backend") / note["file_url"].lstrip("/")
        if file_path.exists():
            file_path.unlink()
        await db.study_notes.delete_one({"id": note_id})
    return {"message": "Note deleted"}

# ============= ASSIGNMENTS & TESTS =============

@router.post("/assignments")
async def create_assignment(assignment_data: AssignmentCreate, teacher_id: str):
    """Create a new assignment or test"""
    assignment = Assignment(
        **assignment_data.dict(),
        teacher_id=teacher_id
    )
    await db.assignments.insert_one(assignment.dict())
    return {"message": "Assignment created", "id": assignment.id}

@router.get("/assignments/{batch_id}")
async def get_batch_assignments(batch_id: str):
    """Get all assignments for a batch"""
    assignments = await db.assignments.find({"batch_id": batch_id}).sort("created_at", -1).to_list(100)
    
    # Get submission counts for each
    for assignment in assignments:
        submissions = await db.assignment_submissions.count_documents({"assignment_id": assignment["id"]})
        graded = await db.assignment_submissions.count_documents({
            "assignment_id": assignment["id"],
            "status": "graded"
        })
        assignment["total_submissions"] = submissions
        assignment["graded_count"] = graded
    
    return {"assignments": serialize_doc(assignments)}

@router.get("/assignments/{assignment_id}/submissions")
async def get_assignment_submissions(assignment_id: str):
    """Get all submissions for an assignment"""
    submissions = await db.assignment_submissions.find({"assignment_id": assignment_id}).to_list(100)
    
    # Get student details
    for submission in submissions:
        student = await db.users.find_one({"id": submission["student_id"]})
        if student:
            submission["student"] = {
                "id": student["id"],
                "name": student["name"],
                "email": student["email"]
            }
    
    return {"submissions": serialize_doc(submissions)}

@router.put("/submissions/{submission_id}/grade")
async def grade_submission(submission_id: str, marks: int, feedback: str = None):
    """Grade a student's submission"""
    await db.assignment_submissions.update_one(
        {"id": submission_id},
        {"$set": {
            "marks_obtained": marks,
            "feedback": feedback,
            "status": "graded",
            "graded_at": datetime.utcnow()
        }}
    )
    return {"message": "Submission graded"}

# ============= LIVE CLASSES =============

@router.post("/live-class")
async def create_live_class(class_data: LiveClassCreate, teacher_id: str):
    """Schedule a live class"""
    live_class = LiveClass(
        **class_data.dict(),
        teacher_id=teacher_id
    )
    await db.live_classes.insert_one(live_class.dict())
    return {"message": "Live class scheduled", "id": live_class.id}

@router.get("/live-classes/{teacher_id}")
async def get_teacher_live_classes(teacher_id: str, class_status: str = None):
    """Get live classes for a teacher"""
    query = {"teacher_id": teacher_id}
    if class_status:
        query["status"] = class_status
    
    classes = await db.live_classes.find(query).sort("scheduled_date", 1).to_list(50)
    return {"classes": serialize_doc(classes)}

@router.put("/live-class/{class_id}")
async def update_live_class(class_id: str, updates: dict):
    """Update a live class (link, status, recording)"""
    await db.live_classes.update_one(
        {"id": class_id},
        {"$set": updates}
    )
    return {"message": "Live class updated"}

@router.delete("/live-class/{class_id}")
async def cancel_live_class(class_id: str):
    """Cancel a live class"""
    await db.live_classes.update_one(
        {"id": class_id},
        {"$set": {"status": "cancelled"}}
    )
    return {"message": "Live class cancelled"}


# ============= PROGRESS REPORTS =============

@router.post("/progress-report")
async def generate_progress_report(student_id: str, batch_id: str, teacher_id: str, report_period: str, teacher_remarks: str = "", areas_of_improvement: list = None, strengths: list = None):
    """Generate progress report for a student"""
    from lms_models import ProgressReport
    
    # Get student info
    student = await db.users.find_one({"id": student_id})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    # Calculate attendance summary
    total_attendance = await db.attendance.count_documents({"student_id": student_id, "batch_id": batch_id})
    present = await db.attendance.count_documents({"student_id": student_id, "batch_id": batch_id, "status": "present"})
    absent = await db.attendance.count_documents({"student_id": student_id, "batch_id": batch_id, "status": "absent"})
    late = await db.attendance.count_documents({"student_id": student_id, "batch_id": batch_id, "status": "late"})
    
    attendance_summary = {
        "total_classes": total_attendance,
        "present": present,
        "absent": absent,
        "late": late,
        "percentage": round((present / total_attendance * 100), 2) if total_attendance > 0 else 0
    }
    
    # Calculate assignment summary
    assignments = await db.assignments.find({"batch_id": batch_id}).to_list(100)
    assignment_ids = [a["id"] for a in assignments]
    submissions = await db.assignment_submissions.find({
        "student_id": student_id,
        "assignment_id": {"$in": assignment_ids}
    }).to_list(100)
    
    total_assignments = len(assignments)
    submitted = len(submissions)
    graded = [s for s in submissions if s.get("status") == "graded"]
    total_marks = sum([s.get("marks_obtained", 0) for s in graded])
    max_marks = sum([a.get("total_marks", 100) for a in assignments if a["id"] in [s["assignment_id"] for s in graded]])
    
    assignment_summary = {
        "total": total_assignments,
        "submitted": submitted,
        "graded": len(graded),
        "average_score": round((total_marks / max_marks * 100), 2) if max_marks > 0 else 0
    }
    
    # Test scores
    test_scores = []
    for submission in graded:
        assignment = next((a for a in assignments if a["id"] == submission["assignment_id"]), None)
        if assignment:
            test_scores.append({
                "name": assignment["title"],
                "marks_obtained": submission.get("marks_obtained", 0),
                "total_marks": assignment.get("total_marks", 100),
                "percentage": round((submission.get("marks_obtained", 0) / assignment.get("total_marks", 100) * 100), 2)
            })
    
    # Calculate overall grade
    avg_attendance = attendance_summary["percentage"]
    avg_assignment = assignment_summary["average_score"]
    overall_score = (avg_attendance * 0.3) + (avg_assignment * 0.7)
    
    if overall_score >= 90:
        overall_grade = "A+"
    elif overall_score >= 80:
        overall_grade = "A"
    elif overall_score >= 70:
        overall_grade = "B+"
    elif overall_score >= 60:
        overall_grade = "B"
    elif overall_score >= 50:
        overall_grade = "C"
    else:
        overall_grade = "D"
    
    report = ProgressReport(
        student_id=student_id,
        batch_id=batch_id,
        generated_by=teacher_id,
        report_period=report_period,
        attendance_summary=attendance_summary,
        assignment_summary=assignment_summary,
        test_scores=test_scores,
        overall_grade=overall_grade,
        teacher_remarks=teacher_remarks,
        areas_of_improvement=areas_of_improvement or [],
        strengths=strengths or []
    )
    
    await db.progress_reports.insert_one(report.dict())
    
    return {
        "message": "Progress report generated",
        "report_id": report.id,
        "report": serialize_doc(report.dict())
    }

@router.get("/progress-reports/{batch_id}")
async def get_batch_progress_reports(batch_id: str):
    """Get all progress reports for a batch"""
    reports = await db.progress_reports.find({"batch_id": batch_id}).sort("created_at", -1).to_list(100)
    
    # Add student names
    for report in reports:
        student = await db.users.find_one({"id": report["student_id"]})
        if student:
            report["student_name"] = student["name"]
    
    return {"reports": serialize_doc(reports)}

@router.get("/progress-report/{report_id}")
async def get_progress_report(report_id: str):
    """Get a specific progress report"""
    report = await db.progress_reports.find_one({"id": report_id})
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    student = await db.users.find_one({"id": report["student_id"]})
    batch = await db.batches.find_one({"id": report["batch_id"]})
    
    return {
        "report": serialize_doc(report),
        "student": {"name": student["name"], "email": student["email"]} if student else None,
        "batch": serialize_doc(batch)
    }

