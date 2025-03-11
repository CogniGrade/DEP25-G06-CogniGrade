from backend.database import Base
from backend.models.users import User, UserSettings, LoginHistory
from backend.models.tables import (
    Classroom, Enrollment, Assignment, Submission, 
    Announcement, Exam, ExamResult,
    Query,
    AssignmentStatus, EnrollmentStatus, Role
)
from backend.models.files import Material, AnswerScript
from backend.models.notifications import Notification, NotificationType