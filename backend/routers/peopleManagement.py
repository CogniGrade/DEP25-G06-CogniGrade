from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession     # ASYNC
from sqlalchemy.future import select

from typing import Optional
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import TIMESTAMP
from pydantic import BaseModel

import logging

from backend.database import get_db
from backend.models.tables import Classroom, Enrollment
from backend.models.users import User
from backend.utils.security import get_current_user_required

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pplManagement"])

@router.get("/classes/{class_id}/people")
async def get_class_people(class_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    result = await db.execute(select(Classroom).where(Classroom.id == class_id))
    classroom = result.scalars().first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Prepare professor info
    professor = {
        "user_id": classroom.owner_id,
        "full_name": classroom.owner.full_name,
        "role": "professor"
    }
    
    # Fetch TA enrollments
    result = await db.execute(select(Enrollment).where(
        Enrollment.classroom_id == class_id,
        Enrollment.status == "accepted",
        Enrollment.role == "ta"
    ))
    ta_enrollments = result.scalars().all()
    
    # Fetch student enrollments
    result = await db.execute(select(Enrollment).where(
        Enrollment.classroom_id == class_id,
        Enrollment.status == "accepted",
        Enrollment.role == "student"
    ))
    student_enrollments = result.scalars().all()
    
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
async def remove_student(enrollment_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    result = await db.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    enrollment = result.scalars().first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    result = await db.execute(select(Classroom).where(Classroom.id == enrollment.classroom_id))
    classroom = result.scalars().first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Authorization: Professors can remove any student.
    # TAs can only remove enrollments where the role is "student".
    if current_user.is_professor:
        authorized = True
    else:
        result = await db.execute(select(Enrollment).where(
            Enrollment.classroom_id == classroom.id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted",
            Enrollment.role == "ta"
        ))
        ta_enrollment = result.scalars().first()
        authorized = bool(ta_enrollment and enrollment.role == "student")
    
    if not authorized:
        raise HTTPException(status_code=403, detail="Not authorized to remove this student")
    
    student_id = enrollment.student_id
    db.delete(enrollment)
    await db.commit()
    
    # (Optional) Send a notification if needed...
    
    return JSONResponse({"success": True, "message": "Student removed from class"})

@router.post("/enrollments/{enrollment_id}/make-ta")
async def make_ta(enrollment_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if not current_user.is_professor:
        raise HTTPException(status_code=403, detail="Only professors can promote students to TA")
    
    result = await db.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    enrollment = result.scalars().first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    if enrollment.role != "student":
        raise HTTPException(status_code=400, detail="Enrollment is not a student")
    
    enrollment.role = "ta"
    await db.commit()
    return JSONResponse({"success": True, "message": "Student promoted to TA"})

@router.post("/enrollments/{enrollment_id}/make-student")
async def make_student(enrollment_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    if not current_user.is_professor:
        raise HTTPException(status_code=403, detail="Only professors can demote TAs to student")
    
    result = await db.execute(select(Enrollment).where(Enrollment.id == enrollment_id))
    enrollment = result.scalars().first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    
    if enrollment.role != "ta":
        raise HTTPException(status_code=400, detail="Enrollment is not a TA")
    
    enrollment.role = "student"
    await db.commit()
    return JSONResponse({"success": True, "message": "TA demoted to Student"})