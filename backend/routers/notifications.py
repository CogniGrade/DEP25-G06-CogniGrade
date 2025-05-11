from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import TIMESTAMP
import os

from backend.database import get_db
from backend.models.notifications import Notification
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.models.tables import Classroom, Enrollment

router = APIRouter(tags=["notifications"])

@router.get("/notifications")
async def get_notifications(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    result = await db.execute(
        select(Notification)
        .where(Notification.recipient_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )
    notifications = result.scalars().all()
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
async def get_unread_count(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    from sqlalchemy import func
    result = await db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_id == current_user.id, Notification.read == False)
    )
    count = result.scalar()
    return JSONResponse({"success": True, "count": count})

@router.post("/notifications/{notification_id}/read")
async def mark_as_read(notification_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    notification = result.scalars().first()
    if not notification or notification.recipient_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read = True
    await db.commit()
    return JSONResponse({"success": True, "message": "Notification marked as read", "redirect": notification.action_url or "/notifications"})

@router.post("/notifications/read-all")
async def mark_all_as_read(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    await db.execute(
        update(Notification)
        .where(Notification.recipient_id == current_user.id, Notification.read == False)
        .values(read=True)
    )
    await db.commit()
    return JSONResponse({"success": True, "message": "All notifications marked as read"})

@router.post("/invite-student")
async def invite_student(class_id: int, email: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    result = await db.execute(select(Classroom).where(Classroom.id == class_id))
    classroom = result.scalars().first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    result = await db.execute(select(User).where(User.email == email, User.is_professor == False))
    student = result.scalars().first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    result = await db.execute(select(Enrollment).where(
        Enrollment.student_id == student.id,
        Enrollment.classroom_id == classroom.id
    ))
    existing_enrollment = result.scalars().first()
    if existing_enrollment:
        if existing_enrollment.status == "accepted":
            raise HTTPException(status_code=400, detail="Student already enrolled")
        elif existing_enrollment.status == "pending":
            raise HTTPException(status_code=400, detail="Invitation already pending")
        else:
            existing_enrollment.status = "pending"
            await db.commit()
    else:
        new_enrollment = Enrollment(
            student_id=student.id,
            classroom_id=classroom.id,
            status="pending"
        )
        db.add(new_enrollment)
        await db.commit()
    
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
    await db.commit()
    return JSONResponse({"success": True, "message": "Invitation sent"})