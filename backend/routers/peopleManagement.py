from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel

import logging

from backend.database import get_db
from backend.models.tables import Classroom, Enrollment
from backend.models.users import User
from backend.utils.security import get_current_user_required

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pplManagement"])

@router.get("/classes/{class_id}/people")
async def get_class_people(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Prepare professor info
    professor = {
        "user_id": classroom.owner_id,
        "full_name": classroom.owner.full_name,
        "role": "professor"
    }
    
    # Fetch TA enrollments
    ta_enrollments = db.query(Enrollment).filter(
        Enrollment.classroom_id == class_id,
        Enrollment.status == "accepted",
        Enrollment.role == "ta"
    ).all()
    
    # Fetch student enrollments
    student_enrollments = db.query(Enrollment).filter(
        Enrollment.classroom_id == class_id,
        Enrollment.status == "accepted",
        Enrollment.role == "student"
    ).all()
    
    teachers = [professor] + [{
        "enrollment_id": e.id,
        "user_id": e.student_id,
        "full_name": e.student.full_name,
        "role": e.role.value if hasattr(e.role, 'value') else e.role
    } for e in ta_enrollments]
    
    students = [{
        "enrollment_id": e.id,
        "user_id": e.student_id,
        "full_name": e.student.full_name,
        "role": e.role.value if hasattr(e.role, 'value') else e.role
    } for e in student_enrollments]
    
    return JSONResponse({"success": True, "teachers": teachers, "students": students})




@router.post("/enrollments/{enrollment_id}/remove")
async def remove_student(enrollment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    classroom = db.query(Classroom).filter(Classroom.id == enrollment.classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Authorization: Professors can remove any student.
    # TAs can only remove enrollments where the role is "student".
    if current_user.is_professor:
        authorized = True
    else:
        ta_enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == classroom.id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted",
            Enrollment.role == "ta"
        ).first()
        authorized = bool(ta_enrollment and enrollment.role == "student")
    
    if not authorized:
        raise HTTPException(status_code=403, detail="Not authorized to remove this student")
    
    student_id = enrollment.student_id
    db.delete(enrollment)
    db.commit()
    
    # (Optional) Send a notification if needed...
    
    return JSONResponse({"success": True, "message": "Student removed from class"})


@router.post("/enrollments/{enrollment_id}/make-ta")
async def make_ta(enrollment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if not current_user.is_professor:
        raise HTTPException(status_code=403, detail="Only professors can promote students to TA")
    
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    if enrollment.role != "student":
        raise HTTPException(status_code=400, detail="Enrollment is not a student")
    
    enrollment.role = "ta"
    db.commit()
    return JSONResponse({"success": True, "message": "Student promoted to TA"})


@router.post("/enrollments/{enrollment_id}/make-student")
async def make_student(enrollment_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if not current_user.is_professor:
        raise HTTPException(status_code=403, detail="Only professors can demote TAs to student")
    
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    if enrollment.role != "ta":
        raise HTTPException(status_code=400, detail="Enrollment is not a TA")
    
    enrollment.role = "student"
    db.commit()
    return JSONResponse({"success": True, "message": "TA demoted to Student"})
