from fastapi import APIRouter, HTTPException, status
from lms_models import (
    Course, CourseCreate, Batch, BatchCreate, FeeStructure, FeePayment,
    TeacherSalary, SalaryPayment, Alert, AlertCreate, UserRole
)
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import datetime, date, timedelta
import uuid
from typing import List, Optional

router = APIRouter()

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

def serialize_doc(doc):
    """Convert MongoDB document to JSON serializable format"""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if k != '_id'}
    return doc

# ============= DASHBOARD STATS =============

@router.get("/dashboard/stats")
async def get_admin_dashboard_stats():
    """Get comprehensive dashboard statistics"""
    # User counts
    total_students = await db.users.count_documents({"role": "student"})
    total_teachers = await db.users.count_documents({"role": "teacher"})
    active_students = await db.student_profiles.count_documents({"status": "active"})
    
    # Batch stats
    total_batches = await db.batches.count_documents({})
    active_batches = await db.batches.count_documents({"status": "ongoing"})
    
    # Revenue calculations
    total_revenue_result = await db.fee_payments.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)
    total_revenue = total_revenue_result[0]["total"] if total_revenue_result else 0
    
    # Pending fees
    pending_fees_result = await db.fee_structures.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$pending_amount"}}}
    ]).to_list(1)
    pending_fees = pending_fees_result[0]["total"] if pending_fees_result else 0
    
    # This month's revenue
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_revenue_result = await db.fee_payments.aggregate([
        {"$match": {"payment_date": {"$gte": start_of_month}}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
    ]).to_list(1)
    monthly_revenue = monthly_revenue_result[0]["total"] if monthly_revenue_result else 0
    
    # Recent enrollments (last 30 days)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    new_students = await db.users.count_documents({
        "role": "student",
        "created_at": {"$gte": thirty_days_ago}
    })
    
    return {
        "total_students": total_students,
        "total_teachers": total_teachers,
        "active_students": active_students,
        "total_batches": total_batches,
        "active_batches": active_batches,
        "total_revenue": total_revenue,
        "pending_fees": pending_fees,
        "monthly_revenue": monthly_revenue,
        "new_students_this_month": new_students
    }

# ============= USER MANAGEMENT =============

@router.get("/users")
async def get_all_users(role: str = None, skip: int = 0, limit: int = 50):
    """Get all users with optional role filter"""
    query = {}
    if role:
        query["role"] = role
    
    users = await db.users.find(query).skip(skip).limit(limit).to_list(limit)
    
    # Get profiles for each user
    for user in users:
        user_role = user.get("role", "unknown")
        if user_role == "student":
            profile = await db.student_profiles.find_one({"user_id": user["id"]})
            # Get fee info
            fee_info = await db.fee_structures.find_one({"student_id": user["id"]})
            user["profile"] = serialize_doc(profile)
            user["fee_info"] = serialize_doc(fee_info)
        elif user_role == "teacher":
            profile = await db.teacher_profiles.find_one({"user_id": user["id"]})
            salary_info = await db.teacher_salaries.find_one({"teacher_id": user["id"], "status": "active"})
            user["profile"] = serialize_doc(profile)
            user["salary_info"] = serialize_doc(salary_info)
    
    total = await db.users.count_documents(query)
    
    return {
        "users": serialize_doc(users),
        "total": total,
        "skip": skip,
        "limit": limit
    }

@router.post("/users/add")
async def add_user(user_data: dict):
    """Admin adds a new user (student/teacher)"""
    from auth import get_password_hash
    from lms_models import StudentProfile, TeacherProfile
    
    # Check if email exists
    existing = await db.users.find_one({"email": user_data["email"]})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    user_id = str(uuid.uuid4())
    user = {
        "id": user_id,
        "name": user_data["name"],
        "email": user_data["email"],
        "phone": user_data["phone"],
        "role": user_data["role"],
        "password": get_password_hash(user_data.get("password", "ninja123")),  # Default password
        "is_active": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    await db.users.insert_one(user)
    
    # Create role-specific profile
    if user_data["role"] == "student":
        enrollment_number = f"JN{datetime.now().year}{str(uuid.uuid4())[:6].upper()}"
        profile = StudentProfile(
            user_id=user_id,
            enrollment_number=enrollment_number,
            city=user_data.get("city", ""),
            state=user_data.get("state", "")
        )
        await db.student_profiles.insert_one(profile.dict())
    elif user_data["role"] == "teacher":
        profile = TeacherProfile(
            user_id=user_id,
            qualification=user_data.get("qualification", ""),
            experience_years=user_data.get("experience_years", 0)
        )
        await db.teacher_profiles.insert_one(profile.dict())
    
    return {"message": "User created successfully", "user_id": user_id}

@router.put("/users/{user_id}")
async def update_user(user_id: str, updates: dict):
    """Update user details"""
    # Update main user
    user_updates = {}
    for field in ["name", "phone", "email", "is_active"]:
        if field in updates:
            user_updates[field] = updates[field]
    
    if user_updates:
        user_updates["updated_at"] = datetime.utcnow()
        await db.users.update_one({"id": user_id}, {"$set": user_updates})
    
    # Update profile based on role
    user = await db.users.find_one({"id": user_id})
    if user["role"] == "student":
        profile_updates = {}
        for field in ["city", "state", "current_level", "status"]:
            if field in updates:
                profile_updates[field] = updates[field]
        if profile_updates:
            await db.student_profiles.update_one({"user_id": user_id}, {"$set": profile_updates})
    elif user["role"] == "teacher":
        profile_updates = {}
        for field in ["qualification", "experience_years", "specialization", "bio"]:
            if field in updates:
                profile_updates[field] = updates[field]
        if profile_updates:
            await db.teacher_profiles.update_one({"user_id": user_id}, {"$set": profile_updates})
    
    return {"message": "User updated successfully"}

@router.delete("/users/{user_id}")
async def delete_user(user_id: str):
    """Delete/deactivate a user"""
    # Soft delete - just mark as inactive
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"is_active": False, "updated_at": datetime.utcnow()}}
    )
    
    # Update profile status
    await db.student_profiles.update_one({"user_id": user_id}, {"$set": {"status": "inactive"}})
    
    return {"message": "User deactivated"}

# ============= COURSE MANAGEMENT =============

@router.post("/courses")
async def create_course(course_data: CourseCreate):
    """Create a new course"""
    course = Course(**course_data.dict())
    await db.courses.insert_one(course.dict())
    return {"message": "Course created", "id": course.id}

@router.get("/courses")
async def get_all_courses():
    """Get all courses"""
    courses = await db.courses.find().to_list(100)
    return {"courses": serialize_doc(courses)}

@router.put("/courses/{course_id}")
async def update_course(course_id: str, updates: dict):
    """Update a course"""
    await db.courses.update_one({"id": course_id}, {"$set": updates})
    return {"message": "Course updated"}

@router.delete("/courses/{course_id}")
async def delete_course(course_id: str):
    """Deactivate a course"""
    await db.courses.update_one({"id": course_id}, {"$set": {"is_active": False}})
    return {"message": "Course deactivated"}

# ============= BATCH MANAGEMENT =============

@router.post("/batch")
async def create_batch_simple(batch_data: dict):
    """Create a new batch from JSON body"""
    start_date = datetime.strptime(batch_data["start_date"], "%Y-%m-%d") if batch_data.get("start_date") else datetime.now()
    # Default end date to 6 months after start
    end_date = start_date + timedelta(days=180)
    # Build schedule from timings string
    schedule = {"days": ["Mon", "Wed", "Fri"], "time": batch_data.get("timings", "09:00-11:00")}
    
    batch = Batch(
        batch_name=batch_data.get("batch_name"),
        course_id=batch_data.get("course_id"),
        teacher_id=batch_data.get("teacher_id"),
        start_date=start_date.date() if isinstance(start_date, datetime) else start_date,
        end_date=end_date.date() if isinstance(end_date, datetime) else end_date,
        schedule=schedule,
        max_students=batch_data.get("max_students", 30),
        status="upcoming"
    )
    
    # Convert dates for MongoDB storage
    batch_dict = batch.dict()
    batch_dict["start_date"] = datetime.combine(batch_dict["start_date"], datetime.min.time())
    batch_dict["end_date"] = datetime.combine(batch_dict["end_date"], datetime.min.time())
    
    await db.batches.insert_one(batch_dict)
    
    # Update teacher's assigned batches
    await db.teacher_profiles.update_one(
        {"user_id": batch_data.get("teacher_id")},
        {"$addToSet": {"assigned_batches": batch.id}}
    )
    
    return {"message": "Batch created", "id": batch.id}

@router.post("/batches")
async def create_batch(batch_data: BatchCreate):
    """Create a new batch"""
    batch = Batch(**batch_data.dict())
    await db.batches.insert_one(batch.dict())
    
    # Update teacher's assigned batches
    await db.teacher_profiles.update_one(
        {"user_id": batch_data.teacher_id},
        {"$addToSet": {"assigned_batches": batch.id}}
    )
    
    return {"message": "Batch created", "id": batch.id}

@router.get("/batches")
async def get_all_batches(batch_status: str = None):
    """Get all batches with details"""
    query = {}
    if batch_status:
        query["status"] = batch_status
    
    batches = await db.batches.find(query).to_list(100)
    
    for batch in batches:
        # Get course details
        course = await db.courses.find_one({"id": batch["course_id"]})
        batch["course"] = serialize_doc(course)
        
        # Get teacher details
        teacher = await db.users.find_one({"id": batch["teacher_id"]})
        batch["teacher"] = {"id": teacher["id"], "name": teacher["name"]} if teacher else None
        
        batch["student_count"] = len(batch.get("enrolled_students", []))
        
        # Get enrolled student details
        student_details = []
        for student_id in batch.get("enrolled_students", [])[:10]:  # Limit to first 10
            student = await db.users.find_one({"id": student_id})
            if student:
                student_details.append({"id": student["id"], "name": student["name"], "email": student.get("email")})
        batch["student_details"] = student_details
    
    return {"batches": serialize_doc(batches)}

@router.put("/batches/{batch_id}")
async def update_batch(batch_id: str, updates: dict):
    """Update a batch"""
    await db.batches.update_one({"id": batch_id}, {"$set": updates})
    return {"message": "Batch updated"}

@router.post("/batches/{batch_id}/enroll")
async def enroll_student(batch_id: str, student_id: str):
    """Enroll a student in a batch"""
    batch = await db.batches.find_one({"id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    if len(batch.get("enrolled_students", [])) >= batch.get("max_students", 30):
        raise HTTPException(status_code=400, detail="Batch is full")
    
    # Add to batch
    await db.batches.update_one(
        {"id": batch_id},
        {"$addToSet": {"enrolled_students": student_id}}
    )
    
    # Update student profile
    await db.student_profiles.update_one(
        {"user_id": student_id},
        {
            "$set": {"batch_id": batch_id},
            "$addToSet": {"enrolled_courses": batch["course_id"]}
        }
    )
    
    return {"message": "Student enrolled successfully"}

@router.post("/batches/{batch_id}/remove-student")
async def remove_student_from_batch(batch_id: str, student_id: str):
    """Remove a student from a batch"""
    await db.batches.update_one(
        {"id": batch_id},
        {"$pull": {"enrolled_students": student_id}}
    )
    
    await db.student_profiles.update_one(
        {"user_id": student_id},
        {"$set": {"batch_id": None}}
    )
    
    return {"message": "Student removed from batch"}

@router.post("/enroll-student")
async def enroll_student_with_fees(batch_id: str, student_id: str, total_fee: float = 0, discount: float = 0, installments: int = 2):
    """Enroll a student in a batch and create fee structure"""
    batch = await db.batches.find_one({"id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    if len(batch.get("enrolled_students", [])) >= batch.get("max_students", 30):
        raise HTTPException(status_code=400, detail="Batch is full")
    
    # Check if already enrolled
    if student_id in batch.get("enrolled_students", []):
        raise HTTPException(status_code=400, detail="Student already enrolled in this batch")
    
    # Add to batch
    await db.batches.update_one(
        {"id": batch_id},
        {"$addToSet": {"enrolled_students": student_id}}
    )
    
    # Update student profile
    await db.student_profiles.update_one(
        {"user_id": student_id},
        {
            "$set": {"batch_id": batch_id, "status": "active"},
            "$addToSet": {"enrolled_courses": batch.get("course_id")}
        },
        upsert=True
    )
    
    # Create fee structure if fee is provided
    if total_fee > 0:
        pending = total_fee - discount
        
        # Calculate installment dates
        installment_list = []
        per_installment = pending / installments
        for i in range(installments):
            due_date = datetime.utcnow() + timedelta(days=30 * (i + 1))
            installment_list.append({
                "installment_number": i + 1,
                "amount": per_installment,
                "due_date": due_date,
                "status": "pending"
            })
        
        fee = FeeStructure(
            student_id=student_id,
            course_id=batch.get("course_id"),
            batch_id=batch_id,
            total_fee=total_fee,
            pending_amount=pending,
            installments=installment_list,
            discount_applied=discount
        )
        await db.fee_structures.insert_one(fee.dict())
    
    return {"message": "Student enrolled successfully", "batch_id": batch_id}

# ============= FEE MANAGEMENT =============

@router.post("/fees/structure")
async def create_fee_structure(student_id: str, course_id: str, batch_id: str, total_fee: float, installments: List[dict], discount: float = 0):
    """Create fee structure for a student"""
    pending = total_fee - discount
    
    fee = FeeStructure(
        student_id=student_id,
        course_id=course_id,
        batch_id=batch_id,
        total_fee=total_fee,
        pending_amount=pending,
        installments=installments,
        discount_applied=discount
    )
    await db.fee_structures.insert_one(fee.dict())
    return {"message": "Fee structure created", "id": fee.id}

@router.get("/fees/pending")
async def get_pending_fees():
    """Get all students with pending fees"""
    fees = await db.fee_structures.find({"pending_amount": {"$gt": 0}}).to_list(500)
    
    result = []
    for fee in fees:
        student = await db.users.find_one({"id": fee["student_id"]})
        if student:
            result.append({
                "student_id": fee["student_id"],
                "student_name": student["name"],
                "student_email": student["email"],
                "student_phone": student["phone"],
                "total_fee": fee["total_fee"],
                "paid_amount": fee["paid_amount"],
                "pending_amount": fee["pending_amount"],
                "installments": fee["installments"]
            })
    
    return {"pending_fees": result}

@router.post("/fees/payment")
async def record_fee_payment(fee_structure_id: str, amount: float, payment_method: str, transaction_id: str = None, notes: str = None):
    """Record a fee payment"""
    fee = await db.fee_structures.find_one({"id": fee_structure_id})
    if not fee:
        raise HTTPException(status_code=404, detail="Fee structure not found")
    
    # Create payment record
    receipt_number = f"RCP{datetime.now().strftime('%Y%m%d')}{str(uuid.uuid4())[:6].upper()}"
    
    payment = FeePayment(
        fee_structure_id=fee_structure_id,
        student_id=fee["student_id"],
        amount=amount,
        payment_method=payment_method,
        transaction_id=transaction_id,
        installment_number=len([i for i in fee["installments"] if i.get("status") == "paid"]) + 1,
        receipt_number=receipt_number,
        notes=notes
    )
    await db.fee_payments.insert_one(payment.dict())
    
    # Update fee structure
    new_paid = fee["paid_amount"] + amount
    new_pending = fee["pending_amount"] - amount
    
    await db.fee_structures.update_one(
        {"id": fee_structure_id},
        {"$set": {
            "paid_amount": new_paid,
            "pending_amount": max(0, new_pending)
        }}
    )
    
    return {"message": "Payment recorded", "receipt_number": receipt_number}

@router.get("/fees/student/{student_id}")
async def get_student_fees(student_id: str):
    """Get fee details for a student"""
    fee = await db.fee_structures.find_one({"student_id": student_id})
    payments = await db.fee_payments.find({"student_id": student_id}).sort("payment_date", -1).to_list(50)
    
    return {
        "fee_structure": serialize_doc(fee),
        "payments": serialize_doc(payments)
    }

# ============= TEACHER SALARY MANAGEMENT =============

@router.post("/salary/structure")
async def set_teacher_salary(teacher_id: str, salary_type: str, base_amount: float = 0, percentage: float = 0):
    """Set salary structure for a teacher"""
    # Deactivate existing salary structure
    await db.teacher_salaries.update_many(
        {"teacher_id": teacher_id, "status": "active"},
        {"$set": {"status": "inactive"}}
    )
    
    salary = TeacherSalary(
        teacher_id=teacher_id,
        salary_type=salary_type,
        base_amount=base_amount,
        percentage=percentage,
        effective_from=date.today()
    )
    # Convert to dict and fix date serialization for MongoDB
    salary_dict = salary.dict()
    salary_dict["effective_from"] = datetime.combine(salary_dict["effective_from"], datetime.min.time())
    await db.teacher_salaries.insert_one(salary_dict)
    return {"message": "Salary structure set", "id": salary.id}

@router.get("/salary/teachers")
async def get_all_teacher_salaries():
    """Get salary info for all teachers"""
    teachers = await db.users.find({"role": "teacher"}).to_list(100)
    
    result = []
    for teacher in teachers:
        salary = await db.teacher_salaries.find_one({"teacher_id": teacher["id"], "status": "active"})
        # Get recent payments
        recent_payments = await db.salary_payments.find({
            "teacher_id": teacher["id"]
        }).sort("created_at", -1).limit(3).to_list(3)
        
        result.append({
            "teacher_id": teacher["id"],
            "name": teacher["name"],
            "email": teacher["email"],
            "salary_structure": serialize_doc(salary),
            "recent_payments": serialize_doc(recent_payments)
        })
    
    return {"teachers": result}

@router.post("/salary/pay")
async def process_salary_payment(teacher_id: str, month: str, base_salary: float, bonus: float = 0, deductions: float = 0, notes: str = None):
    """Process salary payment for a teacher"""
    total = base_salary + bonus - deductions
    
    payment = SalaryPayment(
        teacher_id=teacher_id,
        month=month,
        base_salary=base_salary,
        bonus=bonus,
        deductions=deductions,
        total_amount=total,
        payment_date=datetime.utcnow(),
        status="paid",
        notes=notes
    )
    await db.salary_payments.insert_one(payment.dict())
    return {"message": "Salary paid", "id": payment.id, "amount": total}

@router.get("/salary/history/{teacher_id}")
async def get_teacher_salary_history(teacher_id: str):
    """Get salary payment history for a teacher"""
    payments = await db.salary_payments.find({"teacher_id": teacher_id}).sort("created_at", -1).to_list(24)
    return {"payments": serialize_doc(payments)}

# ============= ALERTS & REMINDERS =============

@router.post("/alerts")
async def create_alert(alert_data: AlertCreate, admin_id: str):
    """Create an alert/reminder"""
    alert = Alert(
        **alert_data.dict(),
        created_by=admin_id
    )
    await db.alerts.insert_one(alert.dict())
    return {"message": "Alert created", "id": alert.id}

@router.get("/alerts")
async def get_all_alerts(alert_status: str = None):
    """Get all alerts"""
    query = {}
    if alert_status == "pending":
        query["sent"] = False
    elif alert_status == "sent":
        query["sent"] = True
    
    alerts = await db.alerts.find(query).sort("created_at", -1).to_list(100)
    return {"alerts": serialize_doc(alerts)}

@router.post("/alerts/{alert_id}/send")
async def send_alert(alert_id: str):
    """Mark alert as sent (actual sending would need integration)"""
    await db.alerts.update_one(
        {"id": alert_id},
        {"$set": {"sent": True, "sent_at": datetime.utcnow()}}
    )
    return {"message": "Alert marked as sent"}

@router.post("/alerts/fee-reminders")
async def send_fee_reminders(admin_id: str):
    """Auto-create fee reminder alerts for students with pending fees"""
    pending = await db.fee_structures.find({"pending_amount": {"$gt": 0}}).to_list(500)
    
    created = 0
    for fee in pending:
        alert = Alert(
            created_by=admin_id,
            alert_type="fee_reminder",
            title="Fee Payment Reminder",
            message=f"You have a pending fee of ₹{fee['pending_amount']}. Please clear your dues at the earliest.",
            target_type="individual",
            target_ids=[fee["student_id"]]
        )
        await db.alerts.insert_one(alert.dict())
        created += 1
    
    return {"message": f"Created {created} fee reminder alerts"}

@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str):
    """Delete an alert"""
    await db.alerts.delete_one({"id": alert_id})
    return {"message": "Alert deleted"}

# ============= NOTIFICATION SERVICE =============

@router.post("/notifications/send-sms")
async def send_sms_notification(phone: str, message: str):
    """Send SMS notification (mock - logs to DB for actual integration)"""
    notification = {
        "id": str(uuid.uuid4()),
        "type": "sms",
        "recipient": phone,
        "message": message,
        "status": "queued",
        "created_at": datetime.utcnow()
    }
    await db.notifications.insert_one(notification)
    return {"message": "SMS queued", "id": notification["id"]}

@router.post("/notifications/send-email")
async def send_email_notification(email: str, subject: str, body: str):
    """Send email notification (mock - logs to DB for actual integration)"""
    notification = {
        "id": str(uuid.uuid4()),
        "type": "email",
        "recipient": email,
        "subject": subject,
        "body": body,
        "status": "queued",
        "created_at": datetime.utcnow()
    }
    await db.notifications.insert_one(notification)
    return {"message": "Email queued", "id": notification["id"]}

@router.post("/notifications/bulk-fee-reminder")
async def send_bulk_fee_reminders():
    """Send fee reminders to all students with pending fees"""
    pending_fees = await db.fee_structures.find({"pending_amount": {"$gt": 0}}).to_list(500)
    
    notifications_sent = 0
    for fee in pending_fees:
        student = await db.users.find_one({"id": fee["student_id"]})
        if student:
            # Create notification record
            notification = {
                "id": str(uuid.uuid4()),
                "type": "fee_reminder",
                "student_id": fee["student_id"],
                "recipient_email": student.get("email"),
                "recipient_phone": student.get("phone"),
                "message": f"Dear {student.get('name', 'Student')}, your pending fee is ₹{fee['pending_amount']}. Please make the payment at your earliest convenience.",
                "amount": fee["pending_amount"],
                "status": "sent",
                "created_at": datetime.utcnow()
            }
            await db.notifications.insert_one(notification)
            notifications_sent += 1
    
    return {"message": f"Fee reminders sent to {notifications_sent} students", "count": notifications_sent}

@router.get("/notifications/history")
async def get_notification_history(notification_type: str = None, limit: int = 50):
    """Get notification history"""
    query = {}
    if notification_type:
        query["type"] = notification_type
    
    notifications = await db.notifications.find(query).sort("created_at", -1).limit(limit).to_list(limit)
    return {"notifications": serialize_doc(notifications)}

# ============= AUTOMATED PROGRESS REPORTS =============

@router.post("/progress-reports/schedule")
async def schedule_automated_reports(batch_id: str, frequency: str = "monthly", day_of_month: int = 1):
    """Schedule automated progress report generation for a batch"""
    schedule = {
        "id": str(uuid.uuid4()),
        "batch_id": batch_id,
        "frequency": frequency,  # weekly, monthly, quarterly
        "day_of_month": day_of_month,
        "is_active": True,
        "last_generated": None,
        "next_scheduled": datetime.utcnow() + timedelta(days=30 if frequency == "monthly" else 7),
        "created_at": datetime.utcnow()
    }
    await db.report_schedules.insert_one(schedule)
    return {"message": "Report schedule created", "id": schedule["id"]}

@router.get("/progress-reports/schedules")
async def get_report_schedules():
    """Get all automated report schedules"""
    schedules = await db.report_schedules.find({"is_active": True}).to_list(100)
    
    for schedule in schedules:
        batch = await db.batches.find_one({"id": schedule["batch_id"]})
        schedule["batch_name"] = batch.get("batch_name") if batch else "Unknown"
    
    return {"schedules": serialize_doc(schedules)}

@router.post("/progress-reports/generate-batch/{batch_id}")
async def generate_batch_reports(batch_id: str, report_period: str):
    """Generate progress reports for all students in a batch"""
    batch = await db.batches.find_one({"id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    reports_generated = 0
    for student_id in batch.get("enrolled_students", []):
        # Get attendance data
        attendance = await db.attendance.find({
            "batch_id": batch_id,
            "student_id": student_id
        }).to_list(100)
        
        total_classes = len(attendance)
        present = sum(1 for a in attendance if a.get("status") == "present")
        absent = sum(1 for a in attendance if a.get("status") == "absent")
        late = sum(1 for a in attendance if a.get("status") == "late")
        percentage = round((present / total_classes * 100), 1) if total_classes > 0 else 0
        
        # Get assignment data
        assignments = await db.assignments.find({"batch_id": batch_id}).to_list(50)
        total_assignments = len(assignments)
        submissions = await db.submissions.find({
            "student_id": student_id,
            "assignment_id": {"$in": [a["id"] for a in assignments]}
        }).to_list(50)
        
        submitted = len(submissions)
        graded = sum(1 for s in submissions if s.get("marks") is not None)
        avg_score = round(sum(s.get("marks", 0) for s in submissions if s.get("marks")) / graded, 1) if graded > 0 else 0
        
        # Calculate grade
        overall_score = (percentage * 0.3) + (avg_score * 0.7)
        if overall_score >= 90:
            grade = "A+"
        elif overall_score >= 80:
            grade = "A"
        elif overall_score >= 70:
            grade = "B+"
        elif overall_score >= 60:
            grade = "B"
        elif overall_score >= 50:
            grade = "C"
        else:
            grade = "D"
        
        report = {
            "id": str(uuid.uuid4()),
            "student_id": student_id,
            "batch_id": batch_id,
            "teacher_id": batch.get("teacher_id"),
            "report_period": report_period,
            "attendance_summary": {
                "total_classes": total_classes,
                "present": present,
                "absent": absent,
                "late": late,
                "percentage": percentage
            },
            "assignment_summary": {
                "total": total_assignments,
                "submitted": submitted,
                "graded": graded,
                "average_score": avg_score
            },
            "overall_grade": grade,
            "created_at": datetime.utcnow()
        }
        await db.progress_reports.insert_one(report)
        reports_generated += 1
    
    # Update schedule if exists
    await db.report_schedules.update_one(
        {"batch_id": batch_id, "is_active": True},
        {"$set": {"last_generated": datetime.utcnow()}}
    )
    
    return {"message": f"Generated {reports_generated} progress reports", "count": reports_generated}

# ============= ATTENDANCE REPORTS EXPORT =============

@router.get("/reports/attendance/{batch_id}")
async def export_attendance_report(batch_id: str, start_date: str = None, end_date: str = None):
    """Export attendance report for a batch"""
    batch = await db.batches.find_one({"id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    query = {"batch_id": batch_id}
    if start_date:
        query["date"] = {"$gte": datetime.strptime(start_date, "%Y-%m-%d")}
    if end_date:
        if "date" in query:
            query["date"]["$lte"] = datetime.strptime(end_date, "%Y-%m-%d")
        else:
            query["date"] = {"$lte": datetime.strptime(end_date, "%Y-%m-%d")}
    
    attendance_records = await db.attendance.find(query).sort("date", 1).to_list(1000)
    
    # Get student details
    student_map = {}
    for student_id in batch.get("enrolled_students", []):
        student = await db.users.find_one({"id": student_id})
        if student:
            student_map[student_id] = student.get("name", "Unknown")
    
    # Format for export
    export_data = []
    for record in attendance_records:
        export_data.append({
            "date": record["date"].strftime("%Y-%m-%d") if isinstance(record["date"], datetime) else record["date"],
            "student_name": student_map.get(record["student_id"], "Unknown"),
            "student_id": record["student_id"],
            "status": record["status"],
            "remarks": record.get("remarks", "")
        })
    
    # Summary
    summary = {}
    for student_id, name in student_map.items():
        student_records = [r for r in attendance_records if r["student_id"] == student_id]
        total = len(student_records)
        present = sum(1 for r in student_records if r["status"] == "present")
        summary[name] = {
            "total_classes": total,
            "present": present,
            "absent": total - present,
            "percentage": round((present / total * 100), 1) if total > 0 else 0
        }
    
    return {
        "batch_name": batch.get("batch_name"),
        "records": export_data,
        "summary": summary,
        "total_records": len(export_data)
    }

@router.get("/reports/attendance/csv/{batch_id}")
async def export_attendance_csv(batch_id: str):
    """Export attendance as CSV format string"""
    report = await export_attendance_report(batch_id)
    
    # Generate CSV string
    csv_lines = ["Date,Student Name,Student ID,Status,Remarks"]
    for record in report["records"]:
        csv_lines.append(f"{record['date']},{record['student_name']},{record['student_id']},{record['status']},{record['remarks']}")
    
    return {"csv_data": "\n".join(csv_lines), "filename": f"attendance_{batch_id}.csv"}

# ============= BULK STUDENT ENROLLMENT =============

@router.post("/enroll-bulk")
async def bulk_enroll_students(batch_id: str, students: List[dict]):
    """Bulk enroll multiple students from CSV data
    
    Expected format:
    students = [
        {"name": "Student Name", "email": "email@example.com", "phone": "1234567890", "total_fee": 17999, "discount": 0},
        ...
    ]
    """
    batch = await db.batches.find_one({"id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    enrolled_count = 0
    errors = []
    
    for idx, student_data in enumerate(students):
        try:
            # Check if user exists
            existing = await db.users.find_one({"email": student_data.get("email")})
            
            if existing:
                student_id = existing["id"]
            else:
                # Create new user
                new_user = {
                    "id": str(uuid.uuid4()),
                    "name": student_data.get("name"),
                    "email": student_data.get("email"),
                    "phone": student_data.get("phone", ""),
                    "role": "student",
                    "hashed_password": "temp_password_change_required",
                    "created_at": datetime.utcnow()
                }
                await db.users.insert_one(new_user)
                student_id = new_user["id"]
            
            # Check if already enrolled
            if student_id in batch.get("enrolled_students", []):
                errors.append({"row": idx + 1, "email": student_data.get("email"), "error": "Already enrolled"})
                continue
            
            # Add to batch
            await db.batches.update_one(
                {"id": batch_id},
                {"$addToSet": {"enrolled_students": student_id}}
            )
            
            # Create fee structure
            total_fee = student_data.get("total_fee", 0)
            discount = student_data.get("discount", 0)
            pending = total_fee - discount
            
            if total_fee > 0:
                installment_list = []
                per_installment = pending / 2
                for i in range(2):
                    due_date = datetime.utcnow() + timedelta(days=30 * (i + 1))
                    installment_list.append({
                        "installment_number": i + 1,
                        "amount": per_installment,
                        "due_date": due_date,
                        "status": "pending"
                    })
                
                fee = FeeStructure(
                    student_id=student_id,
                    course_id=batch.get("course_id"),
                    batch_id=batch_id,
                    total_fee=total_fee,
                    pending_amount=pending,
                    installments=installment_list,
                    discount_applied=discount
                )
                await db.fee_structures.insert_one(fee.dict())
            
            enrolled_count += 1
            
        except Exception as e:
            errors.append({"row": idx + 1, "email": student_data.get("email", "N/A"), "error": str(e)})
    
    return {
        "message": f"Enrolled {enrolled_count} students",
        "enrolled": enrolled_count,
        "errors": errors
    }

@router.post("/enroll-bulk/parse-csv")
async def parse_csv_for_enrollment(body: dict):
    """Parse CSV data and return structured student list for preview"""
    import csv
    from io import StringIO
    
    csv_data = body.get("csv_data", "")
    reader = csv.DictReader(StringIO(csv_data))
    students = []
    
    for row in reader:
        students.append({
            "name": row.get("name", row.get("Name", "")),
            "email": row.get("email", row.get("Email", "")),
            "phone": row.get("phone", row.get("Phone", "")),
            "total_fee": float(row.get("total_fee", row.get("Fee", 0)) or 0),
            "discount": float(row.get("discount", row.get("Discount", 0)) or 0)
        })
    
    return {"students": students, "count": len(students)}

