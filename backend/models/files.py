import enum
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from backend.database import Base

class FileTypeEnum(enum.Enum):
    question_paper = "question_paper"
    solution_script = "solution_script"
    marking_scheme = "marking_scheme"
    answer_sheet = "answer_sheet"
    announcement = "announcement"
    assignment_material = "assignment_material"

class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    file_path = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    link_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Add ondelete="CASCADE" where appropriate.
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=True)
    related_assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=True)
    related_announcement_id = Column(Integer, ForeignKey("announcements.id", ondelete="CASCADE"), nullable=True)
    related_exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=True)

    author_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    extracted_text = Column(Text, nullable=True)
    
    # Discriminator column for file type.
    file_type = Column(Enum(FileTypeEnum), nullable=False)

    # Relationships (child side – no passive_deletes needed here)
    classroom = relationship("Classroom", back_populates="materials")
    assignment = relationship("Assignment", back_populates="materials")
    announcement = relationship("Announcement", back_populates="materials")
    exam = relationship("Exam", back_populates="materials")
    author = relationship("User")


class AnswerScript(Base):
    __tablename__ = "answer_scripts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    file_path = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    extracted_text = Column(Text, nullable=True)

    # Relationships
    exam = relationship("Exam", back_populates="answer_scripts")
    student = relationship("User", back_populates="answer_scripts")
