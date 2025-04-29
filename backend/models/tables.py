from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import shortuuid
import enum
from backend.database import Base

class AssignmentStatus(str, enum.Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    GRADED = "graded"
    LATE = "late"

class EnrollmentStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

class Role(str, enum.Enum):
    STUDENT = "student"
    TA = "ta"
    PROFESSOR = "professor"

class Classroom(Base):
    __tablename__ = "classrooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    class_code = Column(String, unique=True, index=True, default=lambda: shortuuid.ShortUUID().random(length=6).upper())
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    is_archived = Column(Boolean, default=False)

    # Relationships with passive_deletes for efficient cascade operations
    owner = relationship("User", back_populates="owned_classes")
    enrollments = relationship("Enrollment", back_populates="classroom", cascade="all, delete-orphan", passive_deletes=True)
    assignments = relationship("Assignment", back_populates="classroom", cascade="all, delete-orphan", passive_deletes=True)
    announcements = relationship("Announcement", back_populates="classroom", cascade="all, delete-orphan", passive_deletes=True)
    exams = relationship("Exam", back_populates="classroom", cascade="all, delete-orphan", passive_deletes=True)
    materials = relationship("Material", back_populates="classroom", cascade="all, delete-orphan", passive_deletes=True)
    queries = relationship("Query", back_populates="classroom", cascade="all, delete-orphan", passive_deletes=True)

class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"))
    status = Column(Enum(EnrollmentStatus), default=EnrollmentStatus.PENDING)
    role = Column(Enum(Role), default=Role.STUDENT)
    joined_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_accessed = Column(DateTime, nullable=True)

    # Relationships
    student = relationship("User", back_populates="enrollments")
    classroom = relationship("Classroom", back_populates="enrollments")

class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    due_date = Column(DateTime, nullable=True)
    points_possible = Column(Integer, default=100)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"))
    author_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    attachment_path = Column(String, nullable=True)

    # Relationships
    classroom = relationship("Classroom", back_populates="assignments")
    author = relationship("User")
    submissions = relationship("Submission", back_populates="assignment", cascade="all, delete-orphan", passive_deletes=True)
    materials = relationship("Material", back_populates="assignment", cascade="all, delete-orphan", passive_deletes=True)
    queries = relationship("Query", back_populates="assignment", cascade="all, delete-orphan", passive_deletes=True)
    

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=True)
    file_path = Column(String, nullable=True)
    submitted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    grade = Column(Integer, nullable=True)
    feedback = Column(Text, nullable=True)
    status = Column(Enum(AssignmentStatus), default=AssignmentStatus.PENDING)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"))
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    graded_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    graded_at = Column(DateTime, nullable=True)

    # Relationships
    assignment = relationship("Assignment", back_populates="submissions")
    student = relationship("User", foreign_keys=[student_id])
    grader = relationship("User", foreign_keys=[graded_by])

class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, onupdate=lambda: datetime.now(timezone.utc))
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"))
    author_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    attachment_path = Column(String, nullable=True)

    classroom = relationship("Classroom", back_populates="announcements")
    author = relationship("User")
    
    materials = relationship("Material", back_populates="announcement", cascade="all, delete-orphan", passive_deletes=True)
    queries = relationship("Query", back_populates="announcement", cascade="all, delete-orphan", passive_deletes=True)

class Exam(Base):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    exam_date = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    points_possible = Column(Integer, default=100)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"))
    author_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    exam_stage = Column(Integer, default=0)  # e.g., "Question Upload", "Label Extract", "Solution Upload", "Marking Annotate", Answer Script Upload", "Answer Script Annotate", "Grading", "Graded"

    classroom = relationship("Classroom", back_populates="exams")
    author = relationship("User")
    results = relationship("ExamResult", back_populates="exam", cascade="all, delete-orphan", passive_deletes=True)
    materials = relationship("Material", back_populates="exam", cascade="all, delete-orphan", passive_deletes=True)
    queries = relationship("Query", back_populates="exam", cascade="all, delete-orphan", passive_deletes=True)
    answer_scripts = relationship("AnswerScript", back_populates="exam", cascade="all, delete-orphan", passive_deletes=True)
    questions = relationship("Question", back_populates="exam", cascade="all, delete-orphan", passive_deletes=True)

class ExamResult(Base):
    __tablename__ = "exam_results"

    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"))
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    marks_obtained = Column(Integer, nullable=True)
    feedback = Column(Text, nullable=True)
    graded_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    graded_at = Column(DateTime, nullable=True)

    exam = relationship("Exam", back_populates="results")
    student = relationship("User", foreign_keys=[student_id])
    grader = relationship("User", foreign_keys=[graded_by])

class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True, index=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    question_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)        # The question's text or prompt.
    ideal_answer = Column(Text, nullable=True)   # The ideal answer for the question
    ideal_marking_scheme = Column(Text, nullable=True)  # Marking scheme for the ideal answer
    max_marks = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    part_labels = Column(Text, nullable=True) 

    ms_text_images = Column(Text, nullable=True)
    ms_table_images = Column(Text, nullable=True)
    ms_diagram_images = Column(Text, nullable=True)
    
    exam = relationship("Exam", back_populates="questions")
    responses = relationship("QuestionResponse", back_populates="question", cascade="all, delete-orphan", passive_deletes=True)

class QuestionResponse(Base):
    __tablename__ = "question_responses"
    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    answer_text = Column(Text, nullable=True)
    marks_obtained = Column(Integer, nullable=True)
    query = Column(Text, nullable=True)
    reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # New columns to store extracted regions JSON data (as a JSON string)
    ans_text_images = Column(Text, nullable=True)
    ans_table_images = Column(Text, nullable=True)
    ans_diagram_images = Column(Text, nullable=True)
    
    question = relationship("Question", back_populates="responses")
    student = relationship("User", back_populates="question_responses")

class Query(Base):
    __tablename__ = "queries"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    is_public = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"))
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    
    # Multiple foreign keys to support different parent types:
    related_assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=True)
    related_announcement_id = Column(Integer, ForeignKey("announcements.id", ondelete="CASCADE"), nullable=True)
    related_exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=True)
    
    # Self-referential foreign key for responses to another query:
    parent_query_id = Column(Integer, ForeignKey("queries.id", ondelete="CASCADE"), nullable=True)
    
    # Relationships
    classroom = relationship("Classroom", back_populates="queries")
    student = relationship("User")
    assignment = relationship("Assignment", back_populates="queries")
    announcement = relationship("Announcement", back_populates="queries")
    exam = relationship("Exam", back_populates="queries")
    parent_query = relationship("Query", remote_side=[id], back_populates="responses")
    responses = relationship("Query", back_populates="parent_query", cascade="all, delete-orphan", passive_deletes=True)
