from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import os
import shortuuid
import logging

from backend.database import get_db
from backend.models.tables import Classroom, Enrollment, Assignment, Submission, Announcement
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.models.tables import Exam  # Added for exam queries

logger = logging.getLogger(__name__)
router = APIRouter(tags=["classes"])

class EnrollmentCreate(BaseModel):
    role: str = "student"  # "student" or "ta"

class AssignmentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None  # as ISO string
    max_marks: Optional[int] = None

class SubmissionCreate(BaseModel):
    content: str

class GradeSubmission(BaseModel):
    grade: int
    feedback: Optional[str] = None

class AnnouncementCreate(BaseModel):
    title: str
    content: str

def parse_datetime(dt_str: str) -> datetime:
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid datetime format: {dt_str}") from e

@router.get("/dashboard")
async def dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    print(current_user.is_professor)
    if current_user.is_professor:
        teaching_courses = db.query(Classroom).filter(Classroom.owner_id == current_user.id).all()
        enrolled_courses = []
    else:
        enrolled_courses = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted",
            Enrollment.role == "student"
        ).all()
        ta_enrollments = db.query(Enrollment).filter(
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted",
            Enrollment.role == "ta"
        ).all()
        teaching_courses = [enrollment.classroom for enrollment in ta_enrollments]
    
    def course_to_dict(course):
        return {
            "id": course.id,
            "name": course.name,
            "subject": course.subject,
            "description": course.description,
            "class_code": course.class_code,
            "owner_name": getattr(course.owner, "full_name", "Unknown") if hasattr(course, "owner") else "Unknown",
            "owner_email": getattr(course.owner, "email", "Unknown") if hasattr(course, "owner") else "Unknown"
        }
    return JSONResponse({
        "user": {
            "full_name": current_user.full_name,
            "is_professor": current_user.is_professor
        },
        "teaching_courses": [course_to_dict(course) for course in teaching_courses],
        "enrolled_courses": [course_to_dict(enrollment.classroom) for enrollment in enrolled_courses]
    })

@router.post("/classes/create")
async def create_class(request: Request, name: str = Form(...), subject: str = Form(...), description: Optional[str] = Form(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    try:
        if not current_user.is_professor:
            raise HTTPException(status_code=403, detail="Only professors can create classes")
        new_class = Classroom(
            name=name,
            subject=subject,
            description=description,
            class_code=shortuuid.ShortUUID().random(length=6).upper(),
            owner_id=current_user.id,
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_class)
        db.commit()
        db.refresh(new_class)
        logger.info(f"Class created: {new_class.name} by {current_user.email}")
        return JSONResponse({"success": True, "class": {
            "id": new_class.id,
            "name": new_class.name,
            "subject": new_class.subject,
            "description": new_class.description,
            "class_code": new_class.class_code
        }})
    except Exception as e:
        logger.error(f"Error creating class: {str(e)}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": "An error occurred while creating the class"})

@router.post("/classes/join-class")
async def join_class(class_code: str = Form(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    try:
        class_code = class_code.strip().upper()
        classroom = db.query(Classroom).filter(Classroom.class_code == class_code).first()
        if not classroom:
            return JSONResponse(status_code=400, content={"success": False, "error": "Invalid class code"})
        
        existing_enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == classroom.id,
            Enrollment.student_id == current_user.id
        ).first()
        if existing_enrollment:
            if existing_enrollment.status == "accepted":
                return JSONResponse({"success": True, "message": "Already enrolled", "redirect": f"/classes/{classroom.id}"})
            # elif existing_enrollment.status == "pending":                                           ##  FOR NOW ALL ACCEPTED ON JOINING,  UNCOMMENT LATER
            #     return JSONResponse({"success": True, "message": "Request already pending"})        ##  FOR NOW ALL ACCEPTED ON JOINING,  UNCOMMENT LATER
            else:
                existing_enrollment.status = "accepted"                                  ##  FOR NOW ALL ACCEPTED ON JOINING
                db.commit()
        else:
            new_enrollment = Enrollment(
                student_id=current_user.id,
                classroom_id=classroom.id,
                status="accepted"                                                        ##  FOR NOW ALL ACCEPTED ON JOINING
            )
            db.add(new_enrollment)
            db.commit()
        return JSONResponse({"success": True, "message": "Enrollment request submitted"})
    except Exception as e:
        logger.error(f"Error joining class: {str(e)}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": "An error occurred while joining the class"})

@router.post("/classes/{class_id}/assignments")
async def create_assignment(class_id: int, assignment: AssignmentCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    try:
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ).first()
        if not enrollment or (enrollment.role != "ta" and not current_user.is_professor):
            raise HTTPException(status_code=403, detail="Only professors and TAs can create assignments")
        
        parsed_due_date = None
        if assignment.due_date:
            try:
                parsed_due_date = parse_datetime(assignment.due_date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid due date format")
        
        new_assignment = Assignment(
            title=assignment.title,
            description=assignment.description,
            due_date=parsed_due_date,
            max_marks=assignment.max_marks,
            classroom_id=class_id,
            created_by_id=current_user.id,
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_assignment)
        db.commit()
        db.refresh(new_assignment)
        return JSONResponse({"success": True, "assignment": {
            "id": new_assignment.id,
            "title": new_assignment.title,
            "description": new_assignment.description,
            "due_date": new_assignment.due_date.isoformat() if new_assignment.due_date else None,
            "max_marks": new_assignment.max_marks
        }})
    except Exception as e:
        logger.error(f"Error creating assignment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while creating the assignment")

@router.post("/assignments/{assignment_id}/submissions")
async def submit_assignment(assignment_id: int, submission: SubmissionCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    try:
        assignment_obj = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment_obj:
            raise HTTPException(status_code=404, detail="Assignment not found")
        
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == assignment_obj.classroom_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted",
            Enrollment.role == "student"
        ).first()
        if not enrollment:
            raise HTTPException(status_code=403, detail="Only enrolled students can submit assignments")
        
        new_submission = Submission(
            content=submission.content,
            assignment_id=assignment_id,
            student_id=current_user.id,
            submitted_at=datetime.now(timezone.utc)
        )
        db.add(new_submission)
        db.commit()
        db.refresh(new_submission)
        return JSONResponse({"success": True, "submission": {
            "id": new_submission.id,
            "content": new_submission.content,
            "submitted_at": new_submission.submitted_at.isoformat()
        }})
    except Exception as e:
        logger.error(f"Error submitting assignment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while submitting the assignment")

@router.post("/submissions/{submission_id}/grade")
async def grade_submission(submission_id: int, grade_data: GradeSubmission, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    try:
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")
        
        assignment_obj = db.query(Assignment).filter(Assignment.id == submission.assignment_id).first()
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == assignment_obj.classroom_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ).first()
        if not enrollment or (enrollment.role != "ta" and not current_user.is_professor):
            raise HTTPException(status_code=403, detail="Only professors and TAs can grade submissions")
        
        if assignment_obj.max_marks and grade_data.grade > assignment_obj.max_marks:
            raise HTTPException(status_code=400, detail=f"Grade cannot exceed maximum marks: {assignment_obj.max_marks}")
        
        submission.grade = grade_data.grade
        submission.feedback = grade_data.feedback
        submission.graded_by_id = current_user.id
        submission.graded_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(submission)
        return JSONResponse({"success": True, "submission": {
            "id": submission.id,
            "grade": submission.grade,
            "feedback": submission.feedback
        }})
    except Exception as e:
        logger.error(f"Error grading submission: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while grading the submission")

@router.post("/classes/{class_id}/announcements")
async def create_announcement(class_id: int, announcement: AnnouncementCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    try:
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Classroom not found")
        
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ).first()
        if not enrollment:
            raise HTTPException(status_code=403, detail="You are not enrolled in this class")
        if enrollment.role != "ta" and not current_user.is_professor:
            raise HTTPException(status_code=403, detail="Only professors and TAs can create announcements")
        
        new_announcement = Announcement(
            title=announcement.title,
            content=announcement.content,
            classroom_id=class_id,
            author_id=current_user.id,
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_announcement)
        db.commit()
        db.refresh(new_announcement)
        return JSONResponse({"success": True, "announcement": {
            "id": new_announcement.id,
            "title": new_announcement.title,
            "content": new_announcement.content
        }})
    except Exception as e:
        logger.error(f"Error creating announcement: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while creating the announcement")

@router.get("/classes/{class_id}")
async def view_class(class_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    try:
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Class not found")
        
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ).first()
        is_owner = classroom.owner_id == current_user.id
        if not enrollment and not is_owner:
            raise HTTPException(status_code=403, detail="Access denied")
        
        announcements = db.query(Announcement).filter(Announcement.classroom_id == class_id).order_by(Announcement.created_at.desc()).all()
        assignments = db.query(Assignment).filter(Assignment.classroom_id == class_id).order_by(Assignment.created_at.desc()).all()
        ta_enrollments = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.status == "accepted",
            Enrollment.role == "ta"
        ).all()
        student_enrollments = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.status == "accepted",
            Enrollment.role == "student"
        ).all()
        exams = db.query(Exam).filter(Exam.classroom_id == class_id).order_by(Exam.created_at.desc()).all()
        
        def announcement_to_dict(ann):
            return {"id": ann.id, "title": ann.title, "content": ann.content, "created_at": ann.created_at.isoformat() if ann.created_at else None}
        def assignment_to_dict(asmt):
            return {"id": asmt.id, "title": asmt.title, "description": asmt.description, "created_at": asmt.created_at.isoformat() if asmt.created_at else None}
        def exam_to_dict(exam):
            return {"id": exam.id, "title": exam.title, "exam_date": exam.exam_date.isoformat() if exam.exam_date else None, "points_possible": exam.points_possible}
        
        return JSONResponse({
            "user": {
                "full_name": current_user.full_name,
                "is_professor": current_user.is_professor
            },
            "id": classroom.id,
            "name": classroom.name,
            "subject": classroom.subject,
            "description": classroom.description,
            "announcements": [announcement_to_dict(ann) for ann in announcements],
            "assignments": [assignment_to_dict(asmt) for asmt in assignments],
            "exams": [exam_to_dict(exam) for exam in exams],
            "ta_enrollments": [e.id for e in ta_enrollments],
            "student_enrollments": [e.id for e in student_enrollments]
        })
    except Exception as e:
        logger.error(f"Error loading class data: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while loading the class data")
