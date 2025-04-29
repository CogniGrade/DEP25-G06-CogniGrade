from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, UploadFile, File
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import os
import shortuuid
import logging

from backend.database import get_db
from backend.models.tables import Classroom, Enrollment, Assignment, Submission, Announcement
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.models.tables import Exam, ExamResult, Query  # Added ExamResult for classwork endpoint

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

class QueryCreate(BaseModel):
    title: str
    content: str
    is_public: bool = True
    related_assignment_id: Optional[int] = None
    related_announcement_id: Optional[int] = None
    related_exam_id: Optional[int] = None
    parent_query_id: Optional[int] = None

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
    # if current_user.is_professor:
    teaching_courses_prof = db.query(Classroom).filter(Classroom.owner_id == current_user.id).all()
    # enrolled_courses = []
    # else:
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
    teaching_courses = [enrollment.classroom for enrollment in ta_enrollments] + teaching_courses_prof   
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
        # Check if class exists
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Class not found")
            
        # Check if user is the class owner (professor)
        is_owner = classroom.owner_id == current_user.id
        
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ).first()
        
        # Allow if user is class owner, professor, or TA
        if not (is_owner or current_user.is_professor or (enrollment and enrollment.role == "ta")):
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
            points_possible=assignment.max_marks,
            classroom_id=class_id,
            author_id=current_user.id,
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
            "points_possible": new_assignment.points_possible
        }})
    except Exception as e:
        logger.error(f"Error creating assignment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while creating the assignment")

@router.get("/assignments/{assignment_id}/submissions")
async def get_assignment_submissions(
    assignment_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user_required)
):
    """Get all submissions for an assignment (professor/TA only)"""
    try:
        # Fetch the assignment
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        # Check if user is professor or TA
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == assignment.classroom_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ).first()
        
        is_owner = assignment.classroom.owner_id == current_user.id
        if not is_owner and (not enrollment or enrollment.role != "ta"):
            raise HTTPException(status_code=403, detail="Only professors and TAs can view all submissions")

        # Get all submissions
        submissions = db.query(Submission).filter(
            Submission.assignment_id == assignment_id
        ).order_by(Submission.submitted_at.desc()).all()

        # Format submissions with student names
        formatted_submissions = []
        for submission in submissions:
            student = db.query(User).filter(User.id == submission.student_id).first()
            student_name = student.full_name if student else "Unknown"
            
            # Check if there are any files in the student's upload directory
            file_paths = []
            directory = f"uploads/assignments/{assignment_id}/{submission.student_id}"
            if submission.file_path and os.path.exists(submission.file_path):
                file_paths.append(submission.file_path)
            elif os.path.exists(directory):
                # Get all files in the directory
                for file_name in os.listdir(directory):
                    file_paths.append(f"{directory}/{file_name}")
            
            formatted_submissions.append({
                "id": submission.id,
                "student_id": submission.student_id,
                "student_name": student_name,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
                "grade": submission.grade,
                "feedback": submission.feedback,
                "file_path": submission.file_path,
                "file_paths": file_paths,
                "has_files": len(file_paths) > 0
            })

        return {"submissions": formatted_submissions}
    except Exception as e:
        logger.error(f"Error fetching submissions: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching submissions")

@router.get("/assignments/{assignment_id}/my-submission")
async def get_my_submission(
    assignment_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user_required)
):
    """Get current user's submission for an assignment"""
    try:
        # Fetch the assignment
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        # Check if user is enrolled
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == assignment.classroom_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted",
            Enrollment.role == "student"
        ).first()
        
        if not enrollment:
            raise HTTPException(status_code=403, detail="Only enrolled students can view their submissions")

        # Get user's submission
        submission = db.query(Submission).filter(
            Submission.assignment_id == assignment_id,
            Submission.student_id == current_user.id
        ).order_by(Submission.submitted_at.desc()).first()

        if not submission:
            # Return empty submission object instead of error
            return {"submission": None, "status": "not_submitted"}

        # Get all files in the student's upload directory
        file_paths = []
        directory = f"uploads/assignments/{assignment_id}/{current_user.id}"
        if submission.file_path and os.path.exists(submission.file_path):
            file_paths.append(submission.file_path)
        elif os.path.exists(directory):
            # Get all files in the directory
            for file_name in os.listdir(directory):
                file_paths.append(f"{directory}/{file_name}")
        
        # Format submission data
        formatted_submission = {
            "id": submission.id,
            "content": submission.content,
            "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None,
            "grade": submission.grade,
            "feedback": submission.feedback,
            "file_path": submission.file_path,
            "file_paths": file_paths,
            "has_files": len(file_paths) > 0
        }

        return {"submission": formatted_submission, "status": "submitted"}
    except Exception as e:
        logger.error(f"Error fetching submission: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching the submission")

@router.get("/assignments/{assignment_id}")
async def get_assignment(
    assignment_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user_required)
):
    """Get assignment details by ID with classroom and user information"""
    try:
        # Fetch the assignment
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        # Get classroom details
        classroom = db.query(Classroom).filter(Classroom.id == assignment.classroom_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Classroom not found")

        # Check if user has access (enrolled or owner)
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == assignment.classroom_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ).first()
        
        is_owner = classroom.owner_id == current_user.id
        if not enrollment and not is_owner:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get author information
        author = db.query(User).filter(User.id == assignment.author_id).first()
        author_name = author.full_name if author else "Unknown"

        # Get user's submission for students
        user_submission = None
        if enrollment and enrollment.role == "student":
            user_submission = db.query(Submission).filter(
                Submission.assignment_id == assignment_id,
                Submission.student_id == current_user.id
            ).order_by(Submission.submitted_at.desc()).first()

        # Format user submission data if exists
        formatted_submission = None
        if user_submission:
            # Get all files in the student's upload directory
            file_paths = []
            directory = f"uploads/assignments/{assignment_id}/{current_user.id}"
            if user_submission.file_path and os.path.exists(user_submission.file_path):
                file_paths.append(user_submission.file_path)
            elif os.path.exists(directory):
                # Get all files in the directory
                for file_name in os.listdir(directory):
                    file_paths.append(f"{directory}/{file_name}")
            
            formatted_submission = {
                "id": user_submission.id,
                "content": user_submission.content,
                "submitted_at": user_submission.submitted_at.isoformat() if user_submission.submitted_at else None,
                "grade": user_submission.grade,
                "feedback": user_submission.feedback,
                "file_path": user_submission.file_path,
                "file_paths": file_paths,
                "has_files": len(file_paths) > 0
            }

        # Get role from enrollment
        user_role = enrollment.role if enrollment else None
        
        # Format assignment data
        assignment_data = {
            "id": assignment.id,
            "title": assignment.title,
            "description": assignment.description,
            "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
            "points_possible": assignment.points_possible,
            "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
            "classroom_id": assignment.classroom_id,
            "author_id": assignment.author_id,
            "author_name": author_name,
            "attachment_path": assignment.attachment_path
        }

        # Return formatted response
        return {
            "assignment": assignment_data,
            "classroom": {
                "id": classroom.id,
                "name": classroom.name
            },
            "user": {
                "id": current_user.id,
                "is_professor": current_user.is_professor
            },
            "user_role": user_role,
            "user_submission": formatted_submission
        }
    except Exception as e:
        logger.error(f"Error fetching assignment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching the assignment")

@router.get("/assignments/{assignment_id}/comments")
async def get_assignment_comments(
    assignment_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Get comments/queries for an assignment"""
    try:
        # Fetch the assignment
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        # Check if user has access
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == assignment.classroom_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ).first()
        
        is_owner = assignment.classroom.owner_id == current_user.id
        if not enrollment and not is_owner:
            raise HTTPException(status_code=403, detail="Access denied")

        # Get queries related to this assignment
        queries = db.query(Query).filter(
            Query.related_assignment_id == assignment_id,
            Query.is_public == True
        ).order_by(Query.created_at).all()

        # Format queries with author names
        formatted_comments = []
        for query in queries:
            author = db.query(User).filter(User.id == query.student_id).first()
            author_name = author.full_name if author else "Unknown"
            
            formatted_comments.append({
                "id": query.id,
                "content": query.content,
                "created_at": query.created_at.isoformat() if query.created_at else None,
                "author_id": query.student_id,
                "author_name": author_name
            })

        return {"comments": formatted_comments}
    except Exception as e:
        logger.error(f"Error fetching comments: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while fetching comments")

@router.post("/assignments/{assignment_id}/submit")
async def submit_assignment_file(
    assignment_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Submit an assignment with a file attachment"""
    try:
        # Check if assignment exists
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")

        # Check if user is enrolled as student
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == assignment.classroom_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted",
            Enrollment.role == "student"
        ).first()
        
        if not enrollment:
            raise HTTPException(status_code=403, detail="Only enrolled students can submit assignments")

        # Create directory if not exists
        upload_dir = f"uploads/assignments/{assignment_id}/{current_user.id}"
        os.makedirs(upload_dir, exist_ok=True)
        
        # Save file
        file_path = f"{upload_dir}/{file.filename}"
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        # Create or update submission
        existing_submission = db.query(Submission).filter(
            Submission.assignment_id == assignment_id,
            Submission.student_id == current_user.id
        ).first()
        
        if existing_submission:
            # Update existing submission
            # Do not overwrite file_path, as it could contain a previous file
            # We'll retrieve all files from the directory when needed
            existing_submission.submitted_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing_submission)
            submission = existing_submission
        else:
            # Create new submission
            new_submission = Submission(
                assignment_id=assignment_id,
                student_id=current_user.id,
                submitted_at=datetime.now(timezone.utc)
            )
            db.add(new_submission)
            db.commit()
            db.refresh(new_submission)
            submission = new_submission
        
        # Get all files in directory
        file_paths = []
        if os.path.exists(upload_dir):
            for file_name in os.listdir(upload_dir):
                file_paths.append(f"{upload_dir}/{file_name}")
        
        return {
            "success": True,
            "submission": {
                "id": submission.id,
                "file_path": submission.file_path,
                "file_paths": file_paths,
                "has_files": len(file_paths) > 0,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else None
            }
        }
    except Exception as e:
        logger.error(f"Error submitting assignment file: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while submitting the assignment file")

@router.post("/assignments/{assignment_id}/unsubmit")
async def unsubmit_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    try:
        # Find the assignment
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
        
        # Check if user is enrolled as a student
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == assignment.classroom_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted",
            Enrollment.role == "student"
        ).first()
        
        if not enrollment:
            raise HTTPException(status_code=403, detail="Only enrolled students can unsubmit assignments")
        
        # Find the student's submission
        submission = db.query(Submission).filter(
            Submission.assignment_id == assignment_id,
            Submission.student_id == current_user.id
        ).first()
        
        if not submission:
            raise HTTPException(status_code=404, detail="No submission found to unsubmit")
        
        # Cannot unsubmit if already graded
        if submission.grade is not None:
            raise HTTPException(status_code=400, detail="Cannot unsubmit a graded assignment")
        
        # Instead of deleting, mark as unsubmitted
        # We'll keep the file paths but clear the submitted_at to indicate it's not submitted
        submission.submitted_at = None
        
        # Save the changes
        db.commit()
        
        # Get all files in directory for the response
        file_paths = []
        directory = f"uploads/assignments/{assignment_id}/{current_user.id}"
        if os.path.exists(directory):
            for file_name in os.listdir(directory):
                file_paths.append(f"{directory}/{file_name}")
        
        return JSONResponse({
            "success": True, 
            "message": "Assignment unsubmitted successfully",
            "files": file_paths,
            "has_files": len(file_paths) > 0
        })
    except Exception as e:
        logger.error(f"Error unsubmitting assignment: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while unsubmitting the assignment")

@router.post("/submissions/{submission_id}/grade")
async def grade_submission(
    submission_id: int,
    grade_data: GradeSubmission,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Grade a submission"""
    try:
        submission = db.query(Submission).filter(Submission.id == submission_id).first()
        if not submission:
            raise HTTPException(status_code=404, detail="Submission not found")

        # Get the assignment
        assignment = db.query(Assignment).filter(Assignment.id == submission.assignment_id).first()
        if not assignment:
            raise HTTPException(status_code=404, detail="Assignment not found")
            
        # Check if user is professor or TA for this classroom
        is_owner = assignment.classroom.owner_id == current_user.id
        
        if not is_owner and not current_user.is_professor:
            enrollment = db.query(Enrollment).filter(
                Enrollment.classroom_id == assignment.classroom_id,
                Enrollment.student_id == current_user.id,
                Enrollment.status == "accepted",
                Enrollment.role == "ta"
            ).first()
            
            if not enrollment:
                raise HTTPException(status_code=403, detail="Only professors and TAs can grade submissions")

        # Validate grade
        if assignment.points_possible and grade_data.grade > assignment.points_possible:
            raise HTTPException(status_code=400, detail=f"Grade cannot exceed maximum points: {assignment.points_possible}")

        # Update submission with grade
        submission.grade = grade_data.grade
        submission.feedback = grade_data.feedback
        submission.graded_by = current_user.id
        submission.graded_at = datetime.now(timezone.utc)
        
        # Save to database
        db.commit()
        db.refresh(submission)
        
        return {
            "success": True,
            "submission": {
                "id": submission.id,
                "grade": submission.grade,
                "feedback": submission.feedback,
                "graded_at": submission.graded_at.isoformat() if submission.graded_at else None
            }
        }
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise e
    except Exception as e:
        logger.error(f"Error grading submission: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while grading the submission")

@router.post("/classes/{class_id}/announcements")
async def create_announcement(class_id: int, announcement: AnnouncementCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_required)):
    try:
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Classroom not found")
        
        # Check if user is the owner of the class
        is_owner = classroom.owner_id == current_user.id
        
        if not is_owner:
            # Check if user is enrolled
            enrollment = db.query(Enrollment).filter(
                Enrollment.classroom_id == class_id,
                Enrollment.student_id == current_user.id,
                Enrollment.status == "accepted"
            ).first()
            
            if not enrollment:
                raise HTTPException(status_code=403, detail="You are not enrolled in this class")
            
            # Allow all enrolled users (students, TAs) to create announcements
        
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

@router.put("/classes/{class_id}/announcements/{announcement_id}")
async def update_announcement(
    class_id: int, 
    announcement_id: int, 
    announcement: AnnouncementCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user_required)
):
    try:
        # Check if class exists
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Class not found")
        
        # Check if announcement exists
        existing_announcement = db.query(Announcement).filter(
            Announcement.id == announcement_id,
            Announcement.classroom_id == class_id
        ).first()
        
        if not existing_announcement:
            raise HTTPException(status_code=404, detail="Announcement not found")
        
        # Check if user is authorized to edit
        is_owner = classroom.owner_id == current_user.id
        is_author = existing_announcement.author_id == current_user.id
        
        if not (is_owner or is_author):
            enrollment = db.query(Enrollment).filter(
                Enrollment.classroom_id == class_id,
                Enrollment.student_id == current_user.id,
                Enrollment.status == "accepted",
                Enrollment.role == "ta"
            ).first()
            
            if not enrollment:
                raise HTTPException(status_code=403, detail="You do not have permission to edit this announcement")
        
        # Update the announcement
        existing_announcement.title = announcement.title
        existing_announcement.content = announcement.content
        
        db.commit()
        db.refresh(existing_announcement)
        
        return JSONResponse({
            "success": True, 
            "announcement": {
                "id": existing_announcement.id,
                "title": existing_announcement.title,
                "content": existing_announcement.content
            }
        })
    except Exception as e:
        logger.error(f"Error updating announcement: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while updating the announcement")

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
            # Get author information
            author = db.query(User).filter(User.id == ann.author_id).first()
            author_name = author.full_name if author else "Unknown"
            
            # Check if current user can edit this announcement
            can_edit = (ann.author_id == current_user.id) or (classroom.owner_id == current_user.id)
            
            # Check for a query that links this announcement to an exam or assignment
            from backend.models.tables import Query
            
            # Get related exam ID
            related_exam_id = None
            related_query = db.query(Query).filter(
                Query.related_announcement_id == ann.id,
                Query.related_exam_id != None
            ).first()
            
            if related_query:
                related_exam_id = related_query.related_exam_id
            # If no direct link is found, use the time-based heuristic as fallback
            elif "Exam" in ann.title:
                # Find the most recent exam
                latest_exam = db.query(Exam).filter(
                    Exam.classroom_id == class_id,
                    Exam.created_at <= ann.created_at + timedelta(minutes=1),
                    Exam.created_at >= ann.created_at - timedelta(minutes=1)
                ).order_by(Exam.created_at.desc()).first()
                
                if latest_exam:
                    related_exam_id = latest_exam.id
            
            # Get related assignment ID
            related_assignment_id = None
            related_query = db.query(Query).filter(
                Query.related_announcement_id == ann.id,
                Query.related_assignment_id != None
            ).first()
            
            if related_query:
                related_assignment_id = related_query.related_assignment_id
            # If no direct link is found, use the time-based heuristic as fallback
            elif "Assignment" in ann.title:
                # Find the most recent assignment
                latest_assignment = db.query(Assignment).filter(
                    Assignment.classroom_id == class_id,
                    Assignment.created_at <= ann.created_at + timedelta(minutes=1),
                    Assignment.created_at >= ann.created_at - timedelta(minutes=1)
                ).order_by(Assignment.created_at.desc()).first()
                
                if latest_assignment:
                    related_assignment_id = latest_assignment.id
            
            return {
                "id": ann.id, 
                "title": ann.title, 
                "content": ann.content, 
                "created_at": ann.created_at.isoformat() if ann.created_at else None,
                "author_id": ann.author_id,
                "author_name": author_name,
                "can_edit": can_edit,
                "exam_id": related_exam_id,
                "assignment_id": related_assignment_id
            }
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
            "class_code": classroom.class_code,
            "announcements": [announcement_to_dict(ann) for ann in announcements],
            "assignments": [assignment_to_dict(asmt) for asmt in assignments],
            "exams": [exam_to_dict(exam) for exam in exams],
            "ta_enrollments": [e.id for e in ta_enrollments],
            "student_enrollments": [e.id for e in student_enrollments]
        })
    except Exception as e:
        logger.error(f"Error loading class data: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while loading the class data")

@router.get("/classes/{class_id}/members")
async def get_class_members(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Get all members (teachers and students) of a class"""
    try:
        # Check if class exists
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Class not found")

        # Check if user is enrolled or is the owner
        if classroom.owner_id != current_user.id:
            enrollment = db.query(Enrollment).filter(
                Enrollment.classroom_id == class_id,
                Enrollment.student_id == current_user.id,
                Enrollment.status == "accepted"
            ).first()
            if not enrollment:
                raise HTTPException(status_code=403, detail="You are not enrolled in this class")

        # Get the class owner/teacher
        teacher = db.query(User).filter(User.id == classroom.owner_id).first()
        teachers = []
        if teacher:
            teachers.append({
                "id": teacher.id,
                "full_name": teacher.full_name,
                "email": teacher.email,
                "role": "owner"
            })

        # Get TAs (teaching assistants)
        ta_enrollments = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.status == "accepted",
            Enrollment.role == "ta"
        ).all()
        
        for enrollment in ta_enrollments:
            ta = db.query(User).filter(User.id == enrollment.student_id).first()
            if ta:
                teachers.append({
                    "id": ta.id,
                    "full_name": ta.full_name,
                    "email": ta.email,
                    "role": "ta"
                })

        # Get students
        student_enrollments = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.status == "accepted",
            Enrollment.role == "student"
        ).all()
        
        students = []
        for enrollment in student_enrollments:
            student = db.query(User).filter(User.id == enrollment.student_id).first()
            if student:
                students.append({
                    "id": student.id,
                    "full_name": student.full_name,
                    "email": student.email
                })

        return JSONResponse({
            "success": True,
            "teachers": teachers,
            "students": students
        })
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting class members: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving class members")

@router.get("/classes/{class_id}/announcements/{announcement_id}/queries")
async def get_announcement_queries(
    class_id: int,
    announcement_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Get queries (comments) for a specific announcement"""
    try:
        # Check if class exists
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Class not found")
        
        # Check if announcement exists
        announcement = db.query(Announcement).filter(
            Announcement.id == announcement_id,
            Announcement.classroom_id == class_id
        ).first()
        if not announcement:
            raise HTTPException(status_code=404, detail="Announcement not found")
        
        # Check if user is enrolled or is the owner
        if classroom.owner_id != current_user.id:
            enrollment = db.query(Enrollment).filter(
                Enrollment.classroom_id == class_id,
                Enrollment.student_id == current_user.id,
                Enrollment.status == "accepted"
            ).first()
            if not enrollment:
                raise HTTPException(status_code=403, detail="You are not enrolled in this class")
        
        # Get queries for this announcement
        from backend.models.tables import Query
        queries = db.query(Query).filter(
            Query.classroom_id == class_id,
            Query.related_announcement_id == announcement_id,
            Query.parent_query_id == None  # Only top-level queries, not replies
        ).order_by(Query.created_at.asc()).all()
        
        # Format queries
        queries_list = []
        for query in queries:
            # Get author information
            author = db.query(User).filter(User.id == query.student_id).first()
            author_name = author.full_name if author else "Unknown"
            
            # Get replies to this query
            replies = db.query(Query).filter(
                Query.parent_query_id == query.id
            ).order_by(Query.created_at.asc()).all()
            
            # Format replies
            replies_list = []
            for reply in replies:
                reply_author = db.query(User).filter(User.id == reply.student_id).first()
                reply_author_name = reply_author.full_name if reply_author else "Unknown"
                
                replies_list.append({
                    "id": reply.id,
                    "content": reply.content,
                    "created_at": reply.created_at.isoformat() if reply.created_at else None,
                    "author_id": reply.student_id,
                    "author_name": reply_author_name
                })
            
            queries_list.append({
                "id": query.id,
                "title": query.title,
                "content": query.content,
                "created_at": query.created_at.isoformat() if query.created_at else None,
                "author_id": query.student_id,
                "author_name": author_name,
                "replies": replies_list
            })
        
        return JSONResponse({
            "success": True,
            "queries": queries_list
        })
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting announcement queries: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while retrieving queries")

@router.post("/classes/{class_id}/queries")
async def create_query(
    class_id: int,
    query: QueryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Create a new query (comment) for a class"""
    try:
        # Check if class exists
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Class not found")
        
        # Check if user is enrolled or is the owner
        if classroom.owner_id != current_user.id:
            enrollment = db.query(Enrollment).filter(
                Enrollment.classroom_id == class_id,
                Enrollment.student_id == current_user.id,
                Enrollment.status == "accepted"
            ).first()
            if not enrollment:
                raise HTTPException(status_code=403, detail="You are not enrolled in this class")
        
        # Validate related items if any
        if query.related_announcement_id:
            announcement = db.query(Announcement).filter(
                Announcement.id == query.related_announcement_id,
                Announcement.classroom_id == class_id
            ).first()
            if not announcement:
                raise HTTPException(status_code=404, detail="Related announcement not found")
        
        if query.related_assignment_id:
            assignment = db.query(Assignment).filter(
                Assignment.id == query.related_assignment_id,
                Assignment.classroom_id == class_id
            ).first()
            if not assignment:
                raise HTTPException(status_code=404, detail="Related assignment not found")
        
        if query.related_exam_id:
            exam = db.query(Exam).filter(
                Exam.id == query.related_exam_id,
                Exam.classroom_id == class_id
            ).first()
            if not exam:
                raise HTTPException(status_code=404, detail="Related exam not found")
        
        if query.parent_query_id:
            parent_query = db.query(Query).filter(
                Query.id == query.parent_query_id,
                Query.classroom_id == class_id
            ).first()
            if not parent_query:
                raise HTTPException(status_code=404, detail="Parent query not found")
        
        # Create query
        from backend.models.tables import Query
        new_query = Query(
            title=query.title,
            content=query.content,
            is_public=query.is_public,
            classroom_id=class_id,
            student_id=current_user.id,
            related_announcement_id=query.related_announcement_id,
            related_assignment_id=query.related_assignment_id,
            related_exam_id=query.related_exam_id,
            parent_query_id=query.parent_query_id,
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_query)
        db.commit()
        db.refresh(new_query)
        
        # Get author name
        author = db.query(User).filter(User.id == current_user.id).first()
        author_name = author.full_name if author else "Unknown"
        
        return JSONResponse({
            "success": True,
            "query": {
                "id": new_query.id,
                "title": new_query.title,
                "content": new_query.content,
                "created_at": new_query.created_at.isoformat() if new_query.created_at else None,
                "author_id": new_query.student_id,
                "author_name": author_name
            }
        })
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error creating query: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred while creating the query")

@router.get("/classes/{class_id}/classwork")
async def get_class_classwork(
    class_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Get all classwork (assignments and exams) for a class"""
    try:
        # Check if the class exists
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Class not found")
        
        # Check if user is enrolled or is the owner
        is_owner = classroom.owner_id == current_user.id
        enrollment = None
        
        if not is_owner:
            enrollment = db.query(Enrollment).filter(
                Enrollment.classroom_id == class_id,
                Enrollment.student_id == current_user.id,
                Enrollment.status == "accepted"
            ).first()
            
            if not enrollment:
                raise HTTPException(status_code=403, detail="Access denied")
        
        # Get user role
        user_role = None
        if enrollment:
            user_role = enrollment.role
        elif is_owner:
            user_role = "owner"
        
        # Retrieve all assignments for the class
        assignments = db.query(Assignment).filter(Assignment.classroom_id == class_id).all()
        
        # Retrieve all exams for the class
        exams = db.query(Exam).filter(Exam.classroom_id == class_id).all()
        
        # Format assignments
        formatted_assignments = []
        for assignment in assignments:
            # Get creator info
            creator = db.query(User).filter(User.id == assignment.author_id).first()
            creator_name = creator.full_name if creator else "Unknown"
            
            # Get submission count
            submission_count = db.query(Submission).filter(Submission.assignment_id == assignment.id).count()
            
            # Get student count
            student_count = db.query(Enrollment).filter(
                Enrollment.classroom_id == class_id,
                Enrollment.role == "student",
                Enrollment.status == "accepted"
            ).count()
            
            # Get user's submission if student
            user_submission = None
            if user_role == "student":
                user_submission_obj = db.query(Submission).filter(
                    Submission.assignment_id == assignment.id,
                    Submission.student_id == current_user.id
                ).first()
                
                if user_submission_obj:
                    user_submission = {
                        "id": user_submission_obj.id,
                        "submitted_at": user_submission_obj.submitted_at.isoformat() if user_submission_obj.submitted_at else None,
                        "grade": user_submission_obj.grade,
                        "feedback": user_submission_obj.feedback,
                        "file_path": user_submission_obj.file_path
                    }
            
            # Format assignment
            formatted_assignment = {
                "id": assignment.id,
                "title": assignment.title,
                "description": assignment.description,
                "due_date": assignment.due_date.isoformat() if assignment.due_date else None,
                "points_possible": assignment.points_possible,
                "created_at": assignment.created_at.isoformat() if assignment.created_at else None,
                "author_id": assignment.author_id,
                "author_name": creator_name,
                "submission_count": submission_count,
                "student_count": student_count,
                "type": "assignment",
                "user_submission": user_submission
            }
            
            formatted_assignments.append(formatted_assignment)
        
        # Format exams
        formatted_exams = []
        for exam in exams:
            # Get creator info
            creator = db.query(User).filter(User.id == exam.author_id).first()
            creator_name = creator.full_name if creator else "Unknown"
            
            # Get user's result if student
            user_result = None
            if user_role == "student":
                user_result_obj = db.query(ExamResult).filter(
                    ExamResult.exam_id == exam.id,
                    ExamResult.student_id == current_user.id
                ).first()
                
                if user_result_obj:
                    user_result = {
                        "id": user_result_obj.id,
                        "score": user_result_obj.marks_obtained,
                        "feedback": user_result_obj.feedback,
                        "graded_at": user_result_obj.graded_at.isoformat() if user_result_obj.graded_at else None
                    }
            
            # Format exam
            formatted_exam = {
                "id": exam.id,
                "title": exam.title,
                "description": exam.description,
                "exam_date": exam.exam_date.isoformat() if exam.exam_date else None,
                "points_possible": exam.points_possible,
                "created_at": exam.created_at.isoformat() if exam.created_at else None,
                "author_id": exam.author_id,
                "author_name": creator_name,
                "type": "exam",
                "user_result": user_result
            }
            
            formatted_exams.append(formatted_exam)
        
        # Combine and sort by date
        all_classwork = formatted_assignments + formatted_exams
        all_classwork.sort(key=lambda x: 
            datetime.fromisoformat(x.get('due_date', x.get('exam_date', x.get('created_at', '2000-01-01')))) 
            if x.get('due_date') or x.get('exam_date') or x.get('created_at') else datetime.min, 
            reverse=True
        )
        
        return {
            "classwork": all_classwork,
            "classroom": {
                "id": classroom.id,
                "name": classroom.name,
                "description": classroom.description,
                "owner_id": classroom.owner_id
            },
            "user": {
                "id": current_user.id,
                "is_professor": current_user.is_professor
            },
            "user_role": user_role
        }
        
    except Exception as e:
        logger.error(f"Error retrieving classwork: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An error occurred while retrieving classwork: {str(e)}")
