from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import TIMESTAMP
from backend.database import get_db
from backend.models.tables import Classroom, Enrollment
from backend.models.users import User
from backend.models.notifications import Notification, NotificationType
from backend.utils.security import get_current_user_required

router = APIRouter(tags=["enrollments"])

@router.post("/classes/join-class")
async def join_class(class_code: str = Form(...), role: str = Form("student"), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if current_user.is_professor:
        raise HTTPException(status_code=403, detail="Professors cannot join classes")
    
    result = await db.execute(select(Classroom).where(Classroom.class_code == class_code.strip().upper()))
    classroom = result.scalars().first()
    if not classroom:
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid class code"})
    
    result = await db.execute(select(Enrollment).where(
        Enrollment.student_id == current_user.id,
        Enrollment.classroom_id == classroom.id
    ))
    existing_enrollment = result.scalars().first()
    
    if existing_enrollment:
        if existing_enrollment.status == "accepted":
            return JSONResponse({"success": True, "message": "Already enrolled", "redirect": f"/classes/{classroom.id}"})
        elif existing_enrollment.status == "pending":
            return JSONResponse({"success": True, "message": "Request already pending"})
        else:
            existing_enrollment.status = "pending"
            await db.commit()
    else:
        new_enrollment = Enrollment(
            student_id=current_user.id,
            classroom_id=classroom.id,
            status="pending"
        )
        db.add(new_enrollment)
        await db.commit()
    
    notification = Notification(
        type=NotificationType.ENROLLMENT_REQUEST,
        title="New Enrollment Request",
        message=f"{current_user.full_name} wants to join your {classroom.name} class",
        sender_id=current_user.id,
        recipient_id=classroom.owner_id,
        classroom_id=classroom.id,
        action_url=f"/enrollments/manage/{classroom.id}",
        created_at=datetime.now(timezone.utc)
    )
    db.add(notification)
    await db.commit()
    
    return JSONResponse({"success": True, "message": "Enrollment request submitted"})

@router.get("/enrollments/manage/{class_id}")
async def manage_enrollments(class_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    result = await db.execute(select(Classroom).where(Classroom.id == class_id))
    classroom = result.scalars().first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await db.execute(select(Enrollment).where(
        Enrollment.classroom_id == class_id,
        Enrollment.status == "pending"
    ))
    pending_enrollments = result.scalars().all()
    pending_students = []
    for enrollment in pending_enrollments:
        result = await db.execute(select(User).where(User.id == enrollment.student_id))
        student = result.scalars().first()
        if student:
            pending_students.append({"student_id": student.id, "full_name": student.full_name, "enrollment_id": enrollment.id})
    
    result = await db.execute(select(Enrollment).where(
        Enrollment.classroom_id == class_id,
        Enrollment.status == "accepted"
    ))
    accepted_enrollments = result.scalars().all()
    enrolled_students = []
    for enrollment in accepted_enrollments:
        result = await db.execute(select(User).where(User.id == enrollment.student_id))
        student = result.scalars().first()
        if student:
            enrolled_students.append({"student_id": student.id, "full_name": student.full_name, "enrollment_id": enrollment.id})
    
    return JSONResponse({
        "success": True,
        "classroom": {"id": classroom.id, "name": classroom.name},
        "pending_students": pending_students,
        "enrolled_students": enrolled_students
    })

@router.post("/enrollments/{enrollment_id}/accept")
async def accept_enrollment(enrollment_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    result = await db.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    enrollment = result.scalars().first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    result = await db.execute(select(Classroom).where(Classroom.id == enrollment.classroom_id))
    classroom = result.scalars().first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    enrollment.status = "accepted"
    await db.commit()
    
    notification = Notification(
        type=NotificationType.ENROLLMENT_ACCEPTED,
        title="Enrollment Accepted",
        message=f"Your request to join {classroom.name} has been accepted",
        sender_id=current_user.id,
        recipient_id=enrollment.student_id,
        classroom_id=classroom.id,
        action_url=f"/classes/{classroom.id}",
        created_at=datetime.now(timezone.utc)
    )
    db.add(notification)
    await db.commit()
    
    return JSONResponse({"success": True, "message": "Enrollment accepted"})

@router.post("/enrollments/{enrollment_id}/reject")
async def reject_enrollment(enrollment_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    result = await db.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    enrollment = result.scalars().first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    result = await db.execute(select(Classroom).where(Classroom.id == enrollment.classroom_id))
    classroom = result.scalars().first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    enrollment.status = "rejected"
    await db.commit()
    
    notification = Notification(
        type=NotificationType.ENROLLMENT_REJECTED,
        title="Enrollment Rejected",
        message=f"Your request to join {classroom.name} has been rejected",
        sender_id=current_user.id,
        recipient_id=enrollment.student_id,
        classroom_id=classroom.id,
        created_at=datetime.now(timezone.utc)
    )
    db.add(notification)
    await db.commit()
    
    return JSONResponse({"success": True, "message": "Enrollment rejected"})

@router.post("/enrollments/{enrollment_id}/remove")
async def remove_student(enrollment_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    result = await db.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    enrollment = result.scalars().first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    result = await db.execute(select(Classroom).where(Classroom.id == enrollment.classroom_id))
    classroom = result.scalars().first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    student_id = enrollment.student_id
    await db.delete(enrollment)
    await db.commit()
    
    notification = Notification(
        type=NotificationType.ENROLLMENT_REMOVED,
        title="Removed from Class",
        message=f"You have been removed from the class {classroom.name}",
        sender_id=current_user.id,
        recipient_id=student_id,
        classroom_id=classroom.id,
        action_url=f"/classes/{classroom.id}",
        created_at=datetime.now(timezone.utc)
    )
    db.add(notification)
    await db.commit()
    
    return JSONResponse({"success": True, "message": "Student removed from class"})