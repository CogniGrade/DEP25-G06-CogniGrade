from typing import List, Optional
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import logging
import os
import uuid
import json

from pydantic import BaseModel

from backend.database import get_db
from backend.models.tables import Exam, Classroom, Enrollment, Question, QuestionResponse, Announcement
from backend.models.files import AnswerScript, Material, FileTypeEnum
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.models.notifications import Notification, NotificationType


UPLOAD_DIRECTORY = "./uploads"
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["exams"])

@router.get("/exams/{exam_id}/stage")
def get_exam_stage(exam_id: int, db: Session = Depends(get_db)):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return {"exam_stage": exam.exam_stage}

class UpdateExamStageRequest(BaseModel):
    exam_stage: int  # the new stage to set

@router.post("/exams/{exam_id}/stage")
def update_exam_stage(exam_id: int, request: UpdateExamStageRequest, db: Session = Depends(get_db)):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    exam.exam_stage = request.exam_stage
    db.commit()
    db.refresh(exam)

    return {"message": "Exam stage updated successfully", "exam_stage": exam.exam_stage}


@router.patch("/exam/update-extracted-text")
async def update_extracted_text(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Expect payload to have: file_id, file_type, extracted_text
    file_id = payload.get("file_id")
    file_type = payload.get("file_type")
    new_text = payload.get("extracted_text")
    if not all([file_id, file_type, new_text is not None]):
        raise HTTPException(status_code=400, detail="Missing required parameters.")

    # Determine which table to update based on the file_type.
    if file_type == "answer_sheet":
        file_record = db.query(AnswerScript).filter(AnswerScript.id == file_id).first()
    elif file_type in ["question_paper", "solution_script", "marking_scheme"]:
        file_record = db.query(Material).filter(Material.id == file_id).first()
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    if not file_record:
        raise HTTPException(status_code=404, detail="File record not found.")

    try:
        file_record.extracted_text = new_text
        db.commit()
        return JSONResponse({"success": True, "message": "Extracted text updated"})
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/exams/{exam_id}/students")
async def get_exam_students(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Find the exam record
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    print("FETCHING STUDENTS FOR EXAM")
    # Query enrollments for the classroom associated with the exam.
    enrollments = db.query(Enrollment).filter(
        Enrollment.classroom_id == exam.classroom_id,
        Enrollment.status == "accepted",
        Enrollment.role == "student"
    ).all()
    print("FETCHED ENROLLMENTS")
    
    # Build a list of student objects.
    # Assumes each User (via enrollment.student) has full_name and (optionally) an entry_number.
    students = []
    for enrollment in enrollments:
        student = enrollment.student
        students.append({
            "id": student.id,
            "name": student.full_name,
            "email": getattr(student, "email", "N/A")
        })
    print(students)
    return JSONResponse({"students": students})

def parse_datetime(dt_str: str) -> datetime:
    """
    Parse an ISO datetime string to a datetime object with timezone info.
    """
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {dt_str}")

@router.get("/exams/{exam_id}/files")
async def get_exam_files(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Get Materials for static sections
    materials = db.query(Material).filter(
        Material.related_exam_id == exam_id,
        Material.file_type.in_([FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme])
    ).all()
    # Get Answer Scripts (for student answer sheets)
    answer_scripts = db.query(AnswerScript).filter(
        AnswerScript.exam_id == exam_id
    ).all()
    mat_list = [{
        "id": m.id,
        "filename": m.title,
        "file_path": m.file_path,
        "file_size": m.file_size,
        "file_type": m.file_type.value,
        "extracted_text": m.extracted_text or ""
    } for m in materials]
    ans_list = [{
        "id": a.id,
        "filename": a.title,
        "file_path": a.file_path,
        "file_size": a.file_size,
        "file_type": "answer_sheet",
        "extracted_text": a.extracted_text or "",
        "student_id": a.student_id
    } for a in answer_scripts]
    return JSONResponse({"materials": mat_list, "answer_scripts": ans_list})


@router.post("/classes/{class_id}/exams")
async def create_exam(
    class_id: int, 
    title: str = Form(...),
    exam_date: Optional[str] = Form(None),
    points_possible: Optional[int] = Form(100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):  
    try:
        # Check if class exists
        classroom = db.query(Classroom).filter(Classroom.id == class_id).first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Class not found")

        # Check if user is the class owner
        is_owner = (classroom.owner_id == current_user.id)
        
        enrollment = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ).all()
        
        # Check if user has permission to create exam
        if not (is_owner or current_user.is_professor or (enrollment and enrollment.role == "ta")): 
            raise HTTPException(status_code=403, detail="Only professors and TAs can create exams")
            
        # Continue with exam creation
        # Parse exam date from form data
        parsed_exam_date = parse_datetime(exam_date) if exam_date else datetime.now(timezone.utc)
        
        # Create the exam record
        new_exam = Exam(
            title=title,
            exam_date=parsed_exam_date,
            points_possible=points_possible,
            classroom_id=class_id,
            author_id=current_user.id,
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_exam)
        db.commit()
        db.refresh(new_exam)
        
        # Get all student enrollments for this class
        enrollments = db.query(Enrollment).filter(
            Enrollment.classroom_id == class_id,
            Enrollment.status == "accepted"
        ).all()

        # Create a notification for each enrolled student
        for enrollment in enrollments:
            notification = Notification(
                type=NotificationType.EXAM,
                title=f"New Exam: {title}",
                message=f"{current_user.full_name} has created a new exam '{title}' for {classroom.name}. Exam date: {parsed_exam_date.strftime('%d %b %Y')}",
                sender_id=current_user.id,
                recipient_id=enrollment.student_id,
                classroom_id=class_id,
                exam_id=new_exam.id,
                action_url=f"/courses.htm?class_id={class_id}",
                created_at=datetime.now(timezone.utc)
            )
            db.add(notification)
        
        announcement = Announcement(
            classroom_id=class_id,
            author_id=current_user.id,
            title=f"New Exam: {title}",
            content=f"{current_user.full_name} has created a new exam '{title}' for {classroom.name}. Exam date: {parsed_exam_date.strftime('%d %b %Y')}",
            created_at=datetime.now(timezone.utc)
        )
        db.add(announcement)
        db.commit()
        db.refresh(announcement)
        # Now that we have both the exam and announcement created, link them using a Query
        # from backend.models.tables import Query
        
        # query = Query(
        #     title=f"New Exam: {title}",
        #     content=f"This announcement is linked to the exam '{title}'",
        #     is_public=True,
        #     classroom_id=class_id,
        #     student_id=current_user.id,
        #     related_announcement_id=announcement.id,
        #     related_exam_id=new_exam.id,
        #     created_at=datetime.now(timezone.utc)
        # )
        # db.add(query)
        # db.commit()
        
        logger.info(f"Exam '{new_exam.title}' created for class ID {class_id} by user {current_user.email}")

        return JSONResponse({
            "success": True,
            "exam": {
                "id": new_exam.id,
                "title": new_exam.title,
                "exam_date": new_exam.exam_date.isoformat(),
                "points_possible": new_exam.points_possible
            }
        })
    except Exception as e:
        # print("Error in enrollment query:", str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/exam/save-files")
async def save_files(
    exam_id: int = Form(...),
    file_type: str = Form(...),  # expected values: question_paper, solution_script, marking_scheme, answer_sheet
    student_id: Optional[int] = Form(None),  # required if file_type is answer_sheet
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    print("YOO")
    try:
        file_type_enum = FileTypeEnum(file_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file type provided.")

    # For non-student files
    if file_type_enum in [FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme]:
        saved_files = []
        for file in files:
            file_id = str(uuid.uuid4())
            file_location = os.path.join(UPLOAD_DIRECTORY, f"{file_id}_{file.filename}")
            contents = await file.read()
            with open(file_location, "wb") as f:
                f.write(contents)
            # Check for an existing record to avoid duplicates
            existing = db.query(Material).filter(
                Material.title == file.filename,
                Material.related_exam_id == exam_id,
                Material.file_type == file_type_enum
            ).first()
            if not existing:
                material = Material(
                    title=file.filename,
                    description="",
                    file_path=file_location,
                    file_size=int(round(file.size, 0)),
                    link_url=None,
                    related_exam_id=exam_id,
                    author_id=current_user.id,
                    extracted_text="",  # Not extracted yet
                    file_type=file_type_enum
                )
                db.add(material)
                db.commit()
                db.refresh(material)
                saved_files.append({"id": material.id, "title": material.title})
        return JSONResponse({"success": True, "saved_files": saved_files})
    
    # For answer sheets
    elif file_type_enum == FileTypeEnum.answer_sheet:
        if not student_id:
            raise HTTPException(status_code=400, detail="student_id is required for answer_sheet.")
        saved_files = []
        for file in files:
            file_id = str(uuid.uuid4())
            file_location = os.path.join(UPLOAD_DIRECTORY, f"{file_id}_{file.filename}")
            contents = await file.read()
            with open(file_location, "wb") as f:
                f.write(contents)
            # Check if an answer script record already exists (using file_path as unique identifier)
            existing = db.query(AnswerScript).filter(
                AnswerScript.title == file.filename,
                AnswerScript.exam_id == exam_id,
                AnswerScript.student_id == student_id,
            ).first()
            if not existing:
                answer_script = AnswerScript(
                    title=file.filename,
                    file_path=file_location,
                    file_size=int(round(file.size, 0)),
                    exam_id=exam_id,
                    student_id=student_id,
                    extracted_text=""
                )
                db.add(answer_script)
                db.commit()
                db.refresh(answer_script)
                saved_files.append({"id": answer_script.id})
        return JSONResponse({"success": True, "saved_files": saved_files})
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type.")
    

@router.delete("/exams/{exam_id}/files")
async def reset_exam_files(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Delete Materials (static exam files)
    materials = db.query(Material).filter(
        Material.related_exam_id == exam_id,
        Material.file_type.in_([FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme])
    ).all()
    for m in materials:
        if m.file_path and os.path.exists(m.file_path):
            os.remove(m.file_path)
        db.delete(m)
    
    # Delete AnswerScripts (student answer sheets)
    answer_scripts = db.query(AnswerScript).filter(
        AnswerScript.exam_id == exam_id
    ).all()
    for a in answer_scripts:
        if a.file_path and os.path.exists(a.file_path):
            os.remove(a.file_path)
        db.delete(a)
    
    db.commit()
    return JSONResponse({"success": True, "message": "All files deleted for this exam."})

@router.delete("/exams/{exam_id}/student_files")
async def reset_exam_files(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Delete AnswerScripts (student answer sheets)
    answer_scripts = db.query(AnswerScript).filter(
        AnswerScript.exam_id == exam_id
    ).all()
    for a in answer_scripts:
        if a.file_path and os.path.exists(a.file_path):
            os.remove(a.file_path)
        db.delete(a)
    
    db.commit()
    return JSONResponse({"success": True, "message": "All Student Answer Scripts deleted for this exam."})


@router.delete("/exams/{exam_id}/files/{file_id}")
async def delete_exam_file(
    exam_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Try to delete from Materials first
    material = db.query(Material).filter(
        Material.id == file_id,
        Material.related_exam_id == exam_id
    ).first()
    if material:
        if material.file_path and os.path.exists(material.file_path):
            os.remove(material.file_path)
        db.delete(material)
        db.commit()
        return JSONResponse({"success": True, "message": "Material file deleted."})
    
    # Try to delete from AnswerScripts
    answer_script = db.query(AnswerScript).filter(
        AnswerScript.id == file_id,
        AnswerScript.exam_id == exam_id
    ).first()
    if answer_script:
        if answer_script.file_path and os.path.exists(answer_script.file_path):
            os.remove(answer_script.file_path)
        db.delete(answer_script)
        db.commit()
        return JSONResponse({"success": True, "message": "Answer script deleted."})
    
    raise HTTPException(status_code=404, detail="File not found for this exam.")

@router.delete("/exams/{exam_id}/questions")
def delete_exam_questions(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Delete all questions for an exam to start fresh"""
    questions = db.query(Question).filter(
        Question.exam_id == exam_id
    ).all()
    
    for question in questions:
        db.delete(question)
    
    db.commit()
    return {"success": True, "message": "All questions deleted for this exam"}

@router.post("/exams/{exam_id}/questions")
def create_exam_question(
    exam_id: int,
    question: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Create a new question for the exam"""
    new_question = Question(
        exam_id=exam_id,
        question_number=question.get("question_number"),
        text=question.get("text"),
        max_marks=question.get("max_marks", 10)
    )
    db.add(new_question)
    db.commit()
    db.refresh(new_question)
    return {
        "id": new_question.id,
        "question_number": new_question.question_number,
        "text": new_question.text,
        "max_marks": new_question.max_marks
    }

@router.get("/exams/{exam_id}/questions/all")
async def get_exam_questions(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    questions = db.query(Question).filter(Question.exam_id == exam_id).order_by(Question.question_number).all()
    
    q_list = [{
         "id": q.id,
         "question_number": q.question_number,
         "text": q.text,
         "ideal_answer": q.ideal_answer,
         "ideal_marking_scheme": q.ideal_marking_scheme,
         "max_marks": q.max_marks
    } for q in questions]
    return JSONResponse(q_list)



@router.get("/exams/{exam_id}/questions/parts")
async def get_exam_questions(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    questions = db.query(Question).filter(Question.exam_id == exam_id).order_by(Question.question_number).all()
    
    q_list = [{
         "id": q.id,
         "question_number": q.question_number,
         "part_labels": q.part_labels,
         "max_marks": q.max_marks
    } for q in questions]
    print("Questions", q_list)
    return JSONResponse(q_list)


class UpdatePartLabels(BaseModel):
    questionId: int
    partLabels: List[str]
    maxMarks: Optional[int]  # New field for updated marks

class UpdatesPayload(BaseModel):
    updates: List[UpdatePartLabels]

@router.post("/exams/{exam_id}/questions/parts")
async def update_question_parts(
    exam_id: int,
    payload: UpdatesPayload,
    db: Session = Depends(get_db)
):
    for update in payload.updates:
        question = (
            db.query(Question)
            .filter(Question.id == update.questionId, Question.exam_id == exam_id)
            .first()
        )
        if not question:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Question with id {update.questionId} not found for exam {exam_id}"
            )
        # Update part_labels column (stored as JSON text)
        question.part_labels = json.dumps(update.partLabels)
        # Update max_marks if provided
        if update.maxMarks is not None:
            question.max_marks = update.maxMarks

    db.commit()
    return {"message": "Part labels and marks updated successfully"}



@router.get("/exams/{exam_id}/document/answer_script")
async def get_answer_scripts(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    answer_scripts = db.query(AnswerScript).filter(
        AnswerScript.exam_id == exam_id
    ).all()
    ans_list = [{
        "id": a.id,
        "filename": a.title,
        "file_path": a.file_path,
        "file_size": a.file_size,
        "extracted_text": a.extracted_text or "",
        "student_id": a.student_id
    } for a in answer_scripts]
    return JSONResponse(ans_list)


@router.post("/exams/{exam_id}/student-responses")
async def post_student_response(
    exam_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    student_id = payload.get("student_id")
    question_id = payload.get("question_id")
    answer_text = payload.get("answer_text")
    if not all([student_id, question_id, answer_text]):
        raise HTTPException(status_code=400, detail="Missing required parameters.")

    new_response = QuestionResponse(
        question_id=question_id,
        student_id=student_id,
        answer_text=answer_text,
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_response)
    db.commit()
    db.refresh(new_response)
    return JSONResponse({"success": True, "id": new_response.id})



# @router.patch("/exams/{exam_id}/questions/{question_id}")
# async def update_question(
#     exam_id: int,
#     question_id: int,
#     update_data: dict,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     question = db.query(Question).filter(
#         Question.id == question_id,
#         Question.exam_id == exam_id
#     ).first()
#     if not question:
#         raise HTTPException(status_code=404, detail="Question not found.")
#     if "text" in update_data:
#         question.text = update_data["text"]
#     if "ideal_answer" in update_data:
#         question.ideal_answer = update_data["ideal_answer"]
#     if "ideal_marking_scheme" in update_data:
#         question.ideal_marking_scheme = update_data["ideal_marking_scheme"]
#     db.commit()
#     db.refresh(question)
#     return JSONResponse({
#         "success": True,
#         "question": {
#             "id": question.id,
#             "text": question.text,
#             "ideal_answer": question.ideal_answer,
#             "ideal_marking_scheme": question.ideal_marking_scheme
#         }
#     })


# @router.get("/exam/{exam_id}/students-performance")
# async def get_students_performance(
#     exam_id: int,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     exam = db.query(Exam).filter(Exam.id == exam_id).first()
#     if not exam:
#         raise HTTPException(status_code=404, detail="Exam not found")
#     enrollments = db.query(Enrollment).filter(
#         Enrollment.classroom_id == exam.classroom_id,
#         Enrollment.status == "accepted",
#         Enrollment.role == "student"
#     ).all()
#     performance = []
#     for enrollment in enrollments:
#         student = enrollment.student
#         responses = db.query(QuestionResponse).filter(
#             QuestionResponse.student_id == student.id,
#             QuestionResponse.question_id.in_(
#                 db.query(Question.id).filter(Question.exam_id == exam_id)
#             )
#         ).all()
#         total_marks = sum(r.marks_obtained for r in responses if r.marks_obtained is not None) if responses else None
#         percentage = (total_marks / exam.points_possible * 100) if total_marks is not None else None
#         performance.append({
#             "student_id": student.id,
#             "name": student.full_name,
#             "roll_number": getattr(student, "entry_number", None),
#             "total_marks": total_marks,
#             "percentage": percentage
#         })
#     return JSONResponse(performance)

# @router.get("/exam/{exam_id}/student-evaluation/{student_id}")
# async def get_student_evaluation(
#     exam_id: int,
#     student_id: int,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     questions = db.query(Question).filter(Question.exam_id == exam_id).all()
#     evaluation = []
#     for q in questions:
#         response = db.query(QuestionResponse).filter(
#             QuestionResponse.question_id == q.id,
#             QuestionResponse.student_id == student_id
#         ).first()
#         evaluation.append({
#             "question_id": q.id,
#             "text": q.text[:50] + "..." if len(q.text) > 50 else q.text,
#             "full_question_text": q.text,
#             "student_response": response.answer_text if response else None,
#             "reasoning": response.reasoning if response else None,
#             "marks_obtained": response.marks_obtained if response else None,
#             "max_marks": q.max_marks
#         })
#     return JSONResponse(evaluation)

# @router.patch("/exam/{exam_id}/question/{question_id}/student/{student_id}/update")
# async def update_student_response(
#     exam_id: int,
#     question_id: int,
#     student_id: int,
#     update_data: dict,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     response = db.query(QuestionResponse).filter(
#         QuestionResponse.question_id == question_id,
#         QuestionResponse.student_id == student_id
#     ).first()
#     if not response:
#         response = QuestionResponse(
#             question_id=question_id,
#             student_id=student_id,
#             answer_text=update_data.get("response", ""),
#             marks_obtained=update_data.get("marks_obtained"),
#             reasoning=update_data.get("reasoning", "")
#         )
#         db.add(response)
#     else:
#         response.answer_text = update_data.get("response", response.answer_text)
#         response.marks_obtained = update_data.get("marks_obtained", response.marks_obtained)
#         response.reasoning = update_data.get("reasoning", response.reasoning)
#     db.commit()
#     return {"message": "Updated successfully"}

# @router.post("/exam/{exam_id}/question/{question_id}/student/{student_id}/reevaluate")
# async def send_for_reevaluation(
#     exam_id: int,
#     question_id: int,
#     student_id: int,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     response = db.query(QuestionResponse).filter(
#         QuestionResponse.question_id == question_id,
#         QuestionResponse.student_id == student_id
#     ).first()
#     if not response:
#         raise HTTPException(status_code=404, detail="Response not found")
#     response.marks_obtained = None  # Reset for re-evaluation
#     response.reasoning = "Sent for re-evaluation"
#     db.commit()
#     # Trigger re-evaluation logic (e.g., call /grade-question)
#     question = db.query(Question).filter(Question.id == question_id).first()
#     await grade_student_response(exam_id, student_id, question_id, response.answer_text, question.ideal_answer, question.ideal_marking_scheme, db)
#     return {"message": "Sent for re-evaluation"}

# @router.get("/exam/{exam_id}/question-metrics")
# async def get_question_metrics(
#     exam_id: int,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     questions = db.query(Question).filter(Question.exam_id == exam_id).all()
#     metrics = []
#     for q in questions:
#         responses = db.query(QuestionResponse).filter(QuestionResponse.question_id == q.id).all()
#         marks = [r.marks_obtained for r in responses if r.marks_obtained is not None]
#         metrics.append({
#             "question_id": q.id,
#             "text": q.text,
#             "ideal_answer": q.ideal_answer,
#             "max_marks": q.max_marks,
#             "marks_distribution": marks
#         })
#     return JSONResponse(metrics)

# @router.post("/exam/{exam_id}/question/{question_id}/drop")
# async def drop_question(
#     exam_id: int,
#     question_id: int,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     responses = db.query(QuestionResponse).filter(QuestionResponse.question_id == question_id).all()
#     for r in responses:
#         r.marks_obtained = 0
#     db.commit()
#     return {"message": "Question dropped"}

# @router.post("/exam/{exam_id}/question/{question_id}/full-marks")
# async def give_full_marks(
#     exam_id: int,
#     question_id: int,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     question = db.query(Question).filter(Question.id == question_id).first()
#     responses = db.query(QuestionResponse).filter(QuestionResponse.question_id == question_id).all()
#     for r in responses:
#         r.marks_obtained = question.max_marks
#         r.reasoning = "Full marks awarded by professor"
#     db.commit()
#     return {"message": "Full marks awarded"}

# @router.get("/exam/{exam_id}/grading-status")
# async def get_grading_status(
#     exam_id: int,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     total = db.query(AnswerScript).filter(AnswerScript.exam_id == exam_id).count()
#     graded = db.query(QuestionResponse).filter(
#         QuestionResponse.question_id.in_(
#             db.query(Question.id).filter(Question.exam_id == exam_id)
#         ),
#         QuestionResponse.marks_obtained.isnot(None)
#     ).distinct(QuestionResponse.student_id).count()
#     return {"total": total, "graded": graded}

# async def grade_student_response(exam_id, student_id, question_id, student_answer, ideal_answer, marking_scheme, db):
#     # Call existing /grade-question endpoint internally (simplified for brevity)
#     from .geminiAPI import grade_question
#     result = await grade_question({
#         "exam_id": exam_id,
#         "student_id": student_id,
#         "question_id": question_id,
#         "student_answer": student_answer,
#         "ideal_answer": ideal_answer,
#         "marking_scheme": marking_scheme
#     }, db, current_user=Depends(get_current_user_required)())
#     response = db.query(QuestionResponse).filter(
#         QuestionResponse.question_id == question_id,
#         QuestionResponse.student_id == student_id
#     ).first()
#     if response:
#         response.marks_obtained = result["grade"]
#         response.reasoning = result["reasoning"]
#         db.commit()