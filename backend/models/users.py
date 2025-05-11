from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Table, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import TIMESTAMP
from backend.database import Base



class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(100), unique=True, index=True)
    hashed_password = Column(Text, nullable=False)
    full_name = Column(String(100), nullable=False)
    profile_picture = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    is_professor = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_login = Column(TIMESTAMP(timezone=True), nullable=True)
    
    # Relationships with passive_deletes where cascade deletion is applied
    owned_classes = relationship("Classroom", back_populates="owner", cascade="all, delete-orphan", passive_deletes=True)
    enrollments = relationship("Enrollment", back_populates="student")
    sent_notifications = relationship("Notification", foreign_keys="Notification.sender_id", back_populates="sender")
    received_notifications = relationship("Notification", foreign_keys="Notification.recipient_id", back_populates="recipient")
    answer_scripts = relationship("AnswerScript", back_populates="student")
    question_responses = relationship("QuestionResponse", back_populates="student")

class UserSettings(Base):
    __tablename__ = "user_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    email_notifications = Column(Boolean, default=True)
    display_theme = Column(String(100), default="light")
    language_preference = Column(String(100), default="en")
    
    user = relationship("User")

class LoginHistory(Base):
    __tablename__ = "login_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    login_time = Column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(Text, nullable=True)
    
    user = relationship("User")
