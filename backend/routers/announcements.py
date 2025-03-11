from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import os

from backend.database import get_db
from backend.models.tables import Classroom, Announcement, Enrollment
from backend.models.users import User
from backend.utils.security import get_current_user_required

router = APIRouter(tags=["announcements"])

@router.get("/classes/{class_id}/announcements")
async def view_announcements(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    announcements = db.query(Announcement).filter(
        Announcement.classroom_id == class_id
    ).order_by(Announcement.created_at.desc()).all()
    ann_list = [
        {
            "id": ann.id,
            "title": ann.title,
            "content": ann.content,
            "created_at": ann.created_at.isoformat() if ann.created_at else None
        }
        for ann in announcements
    ]
    return JSONResponse({"success": True, "announcements": ann_list})

@router.post("/classes/{class_id}/announcements")
async def post_announcement(class_id: int, request: Request, content: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    enrollment = db.query(Enrollment).filter(
        Enrollment.classroom_id == class_id,
        Enrollment.student_id == current_user.id,
        Enrollment.status == "accepted",
        Enrollment.role == "ta"
    ).first()
    if classroom.owner_id != current_user.id and not enrollment:
        raise HTTPException(status_code=403, detail="Not authorized to post announcements")
    announcement = Announcement(
        content=content,
        classroom_id=class_id,
        author_id=current_user.id,
        created_at=datetime.now(timezone.utc)
    )
    db.add(announcement)
    db.commit()
    return JSONResponse({"success": True, "message": "Announcement posted"})
