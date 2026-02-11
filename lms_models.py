from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime, date
from enum import Enum
import uuid

# Enums
class UserRole(str, Enum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"
    PARENT = "parent"

class CourseLevel(str, Enum):
    N5 = "N5"
    N4 = "N4"
    N3 = "N3"
    N2 = "N2"
    N1 = "N1"

class BatchStatus(str, Enum):
    UPCOMING = "upcoming"
    ONGOING = "ongoing"
    COMPLETED = "completed"

class AttendanceStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"

class PaymentStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"

# Enhanced User Models
class UserBase(BaseModel):
    email: EmailStr
    name: str
    phone: str
    role: UserRole

class UserCreate(UserBase):
    password: str

class UserInDB(UserBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    password: str  # hashed
    profile_image: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

# Student Models
class StudentProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    enrollment_number: str
    date_of_birth: Optional[date] = None
    city: str
    state: str
    current_level: Optional[CourseLevel] = None
    target_exam_date: Optional[date] = None
    parent_phone: Optional[str] = None
    parent_email: Optional[EmailStr] = None
    enrolled_courses: List[str] = []
    batch_id: Optional[str] = None
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Teacher Models
class TeacherProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    qualification: str
    specialization: List[CourseLevel] = []
    experience_years: int
    assigned_batches: List[str] = []
    bio: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Course Models
class Course(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    level: CourseLevel
    description: str
    duration_months: int
    fee: float
    installment_plan: dict  # {installments: 2, amounts: [9000, 9000]}
    syllabus: Optional[str] = None
    learning_outcomes: List[str] = []
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class CourseCreate(BaseModel):
    name: str
    level: CourseLevel
    description: str
    duration_months: int
    fee: float
    installment_plan: dict

# Batch Models
class Batch(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    course_id: str
    batch_name: str
    teacher_id: str
    start_date: date
    end_date: date
    schedule: dict  # {days: ["Mon", "Wed", "Fri"], time: "18:00"}
    max_students: int = 30
    enrolled_students: List[str] = []
    status: BatchStatus = BatchStatus.UPCOMING
    created_at: datetime = Field(default_factory=datetime.utcnow)

class BatchCreate(BaseModel):
    course_id: str
    batch_name: str
    teacher_id: str
    start_date: date
    end_date: date
    schedule: dict
    max_students: int = 30

# Module & Lesson Models
class Lesson(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    module_id: str
    lesson_number: int
    title: str
    content: Optional[str] = None
    video_url: Optional[str] = None
    duration_minutes: int
    resources: List[dict] = []  # [{name: "file.pdf", url: "..."}]
    order: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Module(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    course_id: str
    module_number: int
    title: str
    description: str
    learning_objectives: List[str] = []
    duration_hours: int
    lessons: List[Lesson] = []
    order: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Assignment Models
class Assignment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str
    teacher_id: str
    title: str
    description: str
    due_date: datetime
    total_marks: int
    attachments: List[str] = []
    assignment_type: str = "homework"  # homework, practice, project
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AssignmentCreate(BaseModel):
    batch_id: str
    title: str
    description: str
    due_date: datetime
    total_marks: int
    attachments: List[str] = []
    assignment_type: str = "homework"

class AssignmentSubmission(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    assignment_id: str
    student_id: str
    submission_date: datetime = Field(default_factory=datetime.utcnow)
    attachments: List[str] = []
    marks_obtained: Optional[int] = None
    feedback: Optional[str] = None
    status: str = "pending"  # pending, graded

# Test Models
class TestQuestion(BaseModel):
    question: str
    options: List[str]  # For MCQ
    correct_answer: str
    marks: int
    explanation: Optional[str] = None

class Test(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str
    teacher_id: str
    title: str
    test_type: str  # mock_jlpt, module_test, quiz
    duration_minutes: int
    total_marks: int
    passing_marks: int
    scheduled_date: datetime
    questions: List[TestQuestion] = []
    status: str = "draft"  # draft, published, completed
    created_at: datetime = Field(default_factory=datetime.utcnow)

class TestSubmission(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    test_id: str
    student_id: str
    answers: dict  # {question_id: answer}
    marks_obtained: int
    percentage: float
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    time_taken_minutes: int
    result: str  # pass, fail

# Attendance Model
class Attendance(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str
    student_id: str
    date: date
    status: AttendanceStatus
    marked_by: str  # teacher_id
    remarks: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AttendanceCreate(BaseModel):
    batch_id: str
    student_id: str
    date: date
    status: AttendanceStatus
    remarks: Optional[str] = None

# Live Class Model
class LiveClass(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str
    teacher_id: str
    title: str
    scheduled_date: datetime
    duration_minutes: int
    meeting_link: str
    recording_link: Optional[str] = None
    status: str = "scheduled"  # scheduled, ongoing, completed, cancelled
    created_at: datetime = Field(default_factory=datetime.utcnow)

class LiveClassCreate(BaseModel):
    batch_id: str
    title: str
    scheduled_date: datetime
    duration_minutes: int
    meeting_link: str

# Payment Model
class Payment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    student_id: str
    course_id: str
    amount: float
    payment_date: datetime = Field(default_factory=datetime.utcnow)
    payment_method: str  # online, cash, bank_transfer
    transaction_id: Optional[str] = None
    installment_number: int
    status: PaymentStatus = PaymentStatus.PENDING
    receipt_url: Optional[str] = None

# Certificate Model
class Certificate(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    student_id: str
    course_id: str
    certificate_number: str
    issue_date: date
    completion_percentage: float
    final_grade: str
    certificate_url: str
    verification_code: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Announcement Model
class Announcement(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_by: str  # admin/teacher_id
    title: str
    content: str
    target_audience: str  # all, batch_id, specific student_ids
    priority: str = "medium"  # low, medium, high
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None

class AnnouncementCreate(BaseModel):
    title: str
    content: str
    target_audience: str
    priority: str = "medium"
    expires_at: Optional[datetime] = None

# Message Model
class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_user_id: str
    to_user_id: str
    subject: str
    message: str
    attachments: List[str] = []
    is_read: bool = False
    sent_at: datetime = Field(default_factory=datetime.utcnow)

# Progress Tracking Model
class Progress(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    student_id: str
    course_id: str
    module_id: str
    lesson_id: str
    completed: bool = False
    time_spent_minutes: int = 0
    completed_at: Optional[datetime] = None



# Fee Structure Model
class FeeStructure(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    student_id: str
    course_id: str
    batch_id: str
    total_fee: float
    paid_amount: float = 0
    pending_amount: float
    installments: List[dict] = []  # [{amount: 9000, due_date: date, status: "paid/pending", paid_date: None}]
    discount_applied: float = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

class FeePayment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    fee_structure_id: str
    student_id: str
    amount: float
    payment_date: datetime = Field(default_factory=datetime.utcnow)
    payment_method: str  # online, cash, bank_transfer, upi
    transaction_id: Optional[str] = None
    installment_number: int
    receipt_number: str
    notes: Optional[str] = None

# Daily Session Status Model
class DailySessionStatus(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str
    teacher_id: str
    date: date
    topics_covered: List[str] = []
    homework_given: Optional[str] = None
    notes: Optional[str] = None
    duration_minutes: int
    students_present: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

class DailySessionStatusCreate(BaseModel):
    batch_id: str
    date: date
    topics_covered: List[str]
    homework_given: Optional[str] = None
    notes: Optional[str] = None
    duration_minutes: int
    students_present: int

# Study Notes Model
class StudyNote(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    batch_id: str
    teacher_id: str
    title: str
    description: Optional[str] = None
    file_url: str
    file_type: str  # pdf, doc, image, video
    topic: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class StudyNoteCreate(BaseModel):
    batch_id: str
    title: str
    description: Optional[str] = None
    topic: Optional[str] = None

# Teacher Salary Model
class TeacherSalary(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    teacher_id: str
    salary_type: str  # fixed, percentage
    base_amount: float = 0  # For fixed salary
    percentage: float = 0  # For percentage-based (of batch revenue)
    effective_from: date
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)

class SalaryPayment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    teacher_id: str
    month: str  # "2026-01"
    base_salary: float
    bonus: float = 0
    deductions: float = 0
    total_amount: float
    payment_date: Optional[datetime] = None
    status: str = "pending"  # pending, paid
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Alert/Reminder Model
class Alert(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_by: str  # admin_id
    alert_type: str  # fee_reminder, event, announcement, custom
    title: str
    message: str


# Blog/Post Model
class BlogPost(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    author_id: str
    author_name: str
    author_role: str  # admin, teacher
    title: str
    content: str
    media_url: Optional[str] = None  # video or image URL
    media_type: Optional[str] = None  # video, image
    tags: List[str] = []
    is_published: bool = True
    likes_count: int = 0
    comments_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class BlogPostCreate(BaseModel):
    title: str
    content: str
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    tags: List[str] = []

class BlogComment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    post_id: str
    user_id: str
    user_name: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class BlogReaction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    post_id: str
    user_id: str
    reaction_type: str = "like"  # like, love, celebrate
    created_at: datetime = Field(default_factory=datetime.utcnow)

# Student Progress Report Model
class ProgressReport(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    student_id: str
    batch_id: str
    generated_by: str  # teacher_id
    report_period: str  # "2024-01 to 2024-03"
    attendance_summary: dict = {}
    assignment_summary: dict = {}


# Job Application Model
class JobApplication(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    full_name: str
    email: str
    phone: str
    city: str
    experience_years: int = 0
    current_position: Optional[str] = None
    japanese_level: str  # N5, N4, N3, N2, N1, Native
    qualification: str
    resume_url: Optional[str] = None
    cover_letter: Optional[str] = None
    status: str = "pending"  # pending, reviewed, shortlisted, rejected, hired
    admin_notes: Optional[str] = None
    applied_at: datetime = Field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None

class JobApplicationCreate(BaseModel):
    full_name: str
    email: str
    phone: str
    city: str
    experience_years: int = 0
    current_position: Optional[str] = None
    japanese_level: str
    qualification: str
    cover_letter: Optional[str] = None

    test_scores: List[dict] = []
    overall_grade: str = ""
    teacher_remarks: str = ""
    areas_of_improvement: List[str] = []
    strengths: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

    target_type: str  # all_students, batch, individual, all_teachers
    target_ids: List[str] = []  # student_ids or batch_ids
    scheduled_date: Optional[datetime] = None
    sent: bool = False
    sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AlertCreate(BaseModel):
    alert_type: str
    title: str
    message: str
    target_type: str
    target_ids: List[str] = []
    scheduled_date: Optional[datetime] = None
