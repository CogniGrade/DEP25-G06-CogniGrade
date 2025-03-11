from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from backend.database import get_db
from backend.models.tables import Classroom, Enrollment
from backend.models.users import User
from backend.models.notifications import Notification, NotificationType
from backend.utils.security import get_current_user_required

router = APIRouter(tags=["enrollments"])

@router.post("/classes/join-class")
async def join_class(class_code: str = Form(...), role: str = Form("student"), db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if current_user.is_professor:
        raise HTTPException(status_code=403, detail="Professors cannot join classes")
    
    classroom = db.query(Classroom).filter(Classroom.class_code == class_code.strip().upper()).first()
    if not classroom:
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid class code"})
    
    existing_enrollment = db.query(Enrollment).filter(
        Enrollment.student_id == current_user.id,
        Enrollment.classroom_id == classroom.id
    ).first()
    
    if existing_enrollment:
        if existing_enrollment.status == "accepted":
            return JSONResponse({"success": True, "message": "Already enrolled", "redirect": f"/classes/{classroom.id}"})
        elif existing_enrollment.status == "pending":
            return JSONResponse({"success": True, "message": "Request already pending"})
        else:
            existing_enrollment.status = "pending"
            db.commit()
    else:
        new_enrollment = Enrollment(
            student_id=current_user.id,
            classroom_id=classroom.id,
            status="pending"
        )
        db.add(new_enrollment)
        db.commit()
    
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
    db.commit()
    
    return JSONResponse({"success": True, "message": "Enrollment request submitted"})

@router.get("/enrollments/manage/{class_id}")
async def manage_enrollments(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    pending_enrollments = db.query(Enrollment).filter(
        Enrollment.classroom_id == class_id,
        Enrollment.status == "pending"
    ).all()
    pending_students = []
    for enrollment in pending_enrollments:
        student = db.query(User).get(enrollment.student_id)
        if student:
            pending_students.append({"student_id": student.id, "full_name": student.full_name, "enrollment_id": enrollment.id})
    
    accepted_enrollments = db.query(Enrollment).filter(
        Enrollment.classroom_id == class_id,
        Enrollment.status == "accepted"
    ).all()
    enrolled_students = []
    for enrollment in accepted_enrollments:
        student = db.query(User).get(enrollment.student_id)
        if student:
            enrolled_students.append({"student_id": student.id, "full_name": student.full_name, "enrollment_id": enrollment.id})
    
    return JSONResponse({
        "success": True,
        "classroom": {"id": classroom.id, "name": classroom.name},
        "pending_students": pending_students,
        "enrolled_students": enrolled_students
    })

@router.post("/enrollments/{enrollment_id}/accept")
async def accept_enrollment(enrollment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    classroom = db.query(Classroom).filter(Classroom.id == enrollment.classroom_id).first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    enrollment.status = "accepted"
    db.commit()
    
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
    db.commit()
    
    return JSONResponse({"success": True, "message": "Enrollment accepted"})

@router.post("/enrollments/{enrollment_id}/reject")
async def reject_enrollment(enrollment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    classroom = db.query(Classroom).filter(Classroom.id == enrollment.classroom_id).first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    enrollment.status = "rejected"
    db.commit()
    
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
    db.commit()
    
    return JSONResponse({"success": True, "message": "Enrollment rejected"})

@router.post("/enrollments/{enrollment_id}/remove")
async def remove_student(enrollment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    classroom = db.query(Classroom).filter(Classroom.id == enrollment.classroom_id).first()
    if not classroom or classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    student_id = enrollment.student_id
    db.delete(enrollment)
    db.commit()
    
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
    db.commit()
    
    return JSONResponse({"success": True, "message": "Student removed from class"})
