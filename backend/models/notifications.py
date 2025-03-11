from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum
from backend.database import Base

class NotificationType(str, enum.Enum):
    INVITE = "invite"
    ANNOUNCEMENT = "announcement"
    ASSIGNMENT = "assignment"
    ASSIGNMENT_GRADED = "assignment_graded"
    ENROLLMENT = "enrollment"
    ENROLLMENT_REQUEST = "enrollment_request"
    ENROLLMENT_ACCEPTED = "enrollment_accepted"
    ENROLLMENT_REJECTED = "enrollment_rejected"
    ENROLLMENT_REMOVED = "enrollment_removed"
    EXAM = "exam"
    EXAM_RESULT = "exam_result"
    QUERY = "query"
    QUERY_RESPONSE = "query_response"
    COMMENT = "comment"

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(Enum(NotificationType), nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    read = Column(Boolean, default=False)
    action_url = Column(String, nullable=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    recipient_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=True)
    
    # Optional reference IDs for specific notifications
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id", ondelete="CASCADE"), nullable=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=True)
    query_id = Column(Integer, ForeignKey("queries.id", ondelete="CASCADE"), nullable=True)

    # Relationships
    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_notifications")
    recipient = relationship("User", foreign_keys=[recipient_id], back_populates="received_notifications")
    classroom = relationship("Classroom")
