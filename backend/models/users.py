from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Table, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from backend.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    profile_picture = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    is_professor = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime, nullable=True)
    
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
    display_theme = Column(String, default="light")
    language_preference = Column(String, default="en")
    
    user = relationship("User")

class LoginHistory(Base):
    __tablename__ = "login_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    login_time = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    
    user = relationship("User")
