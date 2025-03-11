from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import os

from backend.database import get_db
from backend.models.notifications import Notification
from backend.models.users import User
from backend.utils.security import get_current_user_required

router = APIRouter(tags=["notifications"])

@router.get("/notifications")
async def get_notifications(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    notifications = (
        db.query(Notification)
        .filter(Notification.recipient_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    notif_list = [
        {
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "message": n.message,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "read": n.read,
            "action_url": n.action_url
        }
        for n in notifications
    ]
    return JSONResponse({"success": True, "notifications": notif_list})

@router.get("/notifications/count")
async def get_unread_count(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    count = db.query(Notification).filter(Notification.recipient_id == current_user.id, Notification.read == False).count()
    return JSONResponse({"success": True, "count": count})

@router.post("/notifications/{notification_id}/read")
async def mark_as_read(notification_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification or notification.recipient_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read = True
    db.commit()
    return JSONResponse({"success": True, "message": "Notification marked as read", "redirect": notification.action_url or "/notifications"})

@router.post("/notifications/read-all")
async def mark_all_as_read(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    db.query(Notification).filter(Notification.recipient_id == current_user.id, Notification.read == False).update({"read": True})
    db.commit()
    return JSONResponse({"success": True, "message": "All notifications marked as read"})

@router.post("/invite-student")
async def invite_student(class_id: int, email: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    from backend.models.classes import Classroom, Enrollment
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    student = db.query(User).filter(User.email == email, User.is_professor == False).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    existing_enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == student.id,
        Enrollment.classroom_id == classroom.id
    ).first()
    if existing_enrollment:
        if existing_enrollment.status == "accepted":
            raise HTTPException(status_code=400, detail="Student already enrolled")
        elif existing_enrollment.status == "pending":
            raise HTTPException(status_code=400, detail="Invitation already pending")
        else:
            existing_enrollment.status = "pending"
            db.commit()
    else:
        new_enrollment = Enrollment(
            student_id=student.id,
            classroom_id=classroom.id,
            status="pending"
        )
        db.add(new_enrollment)
        db.commit()
    from datetime import datetime
    notification = Notification(
        type="class_invitation",
        title="Class Invitation",
        message=f"{current_user.full_name} has invited you to join {classroom.name}",
        sender_id=current_user.id,
        recipient_id=student.id,
        classroom_id=classroom.id,
        action_url=f"/enrollments/respond/{classroom.id}",
        created_at=datetime.now(timezone.utc)
    )
    db.add(notification)
    db.commit()
    return JSONResponse({"success": True, "message": "Invitation sent"})
