from typing import List, Optional
from fastapi import APIRouter, Depends, File, UploadFile, Form, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import TIMESTAMP
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
async def get_exam_stage(exam_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalars().first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return {"exam_stage": exam.exam_stage}

@router.post("/exams/{exam_id}/stage")
async def update_exam_stage(exam_id: int, exam_stage: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalars().first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    exam.exam_stage = exam_stage
    await db.commit()
    await db.refresh(exam)

    return {"message": "Exam stage updated successfully", "exam_stage": exam.exam_stage}

@router.patch("/exam/update-extracted-text")
async def update_extracted_text(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    file_id = payload.get("file_id")
    file_type = payload.get("file_type")
    new_text = payload.get("extracted_text")
    if not all([file_id, file_type, new_text is not None]):
        raise HTTPException(status_code=400, detail="Missing required parameters.")

    if file_type == "answer_sheet":
        result = await db.execute(select(AnswerScript).where(AnswerScript.id == file_id))
        file_record = result.scalars().first()
    elif file_type in ["question_paper", "solution_script", "marking_scheme"]:
        result = await db.execute(select(Material).where(Material.id == file_id))
        file_record = result.scalars().first()
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

    if not file_record:
        raise HTTPException(status_code=404, detail="File record not found.")

    try:
        file_record.extracted_text = new_text
        await db.commit()
        return JSONResponse({"success": True, "message": "Extracted text updated"})
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exams/{exam_id}/students")
async def get_exam_students(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalars().first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    print("FETCHING STUDENTS FOR EXAM")
    result = await db.execute(select(Enrollment).options(selectinload(Enrollment.student))    # ← load student in one go
        .where(
            Enrollment.classroom_id == exam.classroom_id,
            Enrollment.status == "accepted",
            Enrollment.role == "student"
        )
    )
    enrollments = result.scalars().all()
    print("FETCHED ENROLLMENTS")
    
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

async def parse_datetime(dt_str: str) -> datetime:
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Material).where(
        Material.related_exam_id == exam_id,
        Material.file_type.in_([FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme])
    ))
    materials = result.scalars().all()
    
    result = await db.execute(select(AnswerScript).where(AnswerScript.exam_id == exam_id))
    answer_scripts = result.scalars().all()
    
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):  
    try:
        result = await db.execute(select(Classroom).where(Classroom.id == class_id))
        classroom = result.scalars().first()
        if not classroom:
            raise HTTPException(status_code=404, detail="Class not found")

        is_owner = (classroom.owner_id == current_user.id)
        
        result = await db.execute(select(Enrollment).where(
            Enrollment.classroom_id == class_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ))
        enrollment = result.scalars().first()
        
        if not (is_owner or current_user.is_professor or (enrollment and enrollment.role == "ta")): 
            raise HTTPException(status_code=403, detail="Only professors and TAs can create exams")
            
        parsed_exam_date = await parse_datetime(exam_date) if exam_date else datetime.now(timezone.utc)
        
        new_exam = Exam(
            title=title,
            exam_date=parsed_exam_date,
            points_possible=points_possible,
            classroom_id=class_id,
            author_id=current_user.id,
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_exam)
        await db.commit()
        await db.refresh(new_exam)
        
        result = await db.execute(select(Enrollment).where(
            Enrollment.classroom_id == class_id,
            Enrollment.status == "accepted"
        ))
        enrollments = result.scalars().all()

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
        await db.commit()
        await db.refresh(announcement)
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
        # await db.commit()
        
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
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/exam/save-files")
async def save_files(
    exam_id: int = Form(...),
    file_type: str = Form(...),  # expected values: question_paper, solution_script, marking_scheme, answer_sheet
    student_id: Optional[int] = Form(None),  # required if file_type is answer_sheet
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    print("YOO")
    try:
        file_type_enum = FileTypeEnum(file_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file type provided.")

    if file_type_enum in [FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme]:
        saved_files = []
        for file in files:
            file_id = str(uuid.uuid4())
            file_location = os.path.join(UPLOAD_DIRECTORY, f"{file_id}_{file.filename}")
            contents = await file.read()
            with open(file_location, "wb") as f:
                f.write(contents)
            result = await db.execute(select(Material).where(
                Material.title == file.filename,
                Material.related_exam_id == exam_id,
                Material.file_type == file_type_enum
            ))
            existing = result.scalars().first()
            if not existing:
                material = Material(
                    title=file.filename,
                    description="",
                    file_path=file_location,
                    file_size=int(round(file.size, 0)),
                    link_url=None,
                    related_exam_id=exam_id,
                    author_id=current_user.id,
                    extracted_text="",
                    file_type=file_type_enum
                )
                db.add(material)
                await db.commit()
                await db.refresh(material)
                saved_files.append({"id": material.id, "title": material.title})
        return JSONResponse({"success": True, "saved_files": saved_files})
    
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
            result = await db.execute(select(AnswerScript).where(
                AnswerScript.title == file.filename,
                AnswerScript.exam_id == exam_id,
                AnswerScript.student_id == student_id
            ))
            existing = result.scalars().first()
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
                await db.commit()
                await db.refresh(answer_script)
                saved_files.append({"id": answer_script.id})
        return JSONResponse({"success": True, "saved_files": saved_files})
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type.")

@router.delete("/exams/{exam_id}/files")
async def reset_exam_files(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Material).where(
        Material.related_exam_id == exam_id,
        Material.file_type.in_([FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme])
    ))
    materials = result.scalars().all()
    for m in materials:
        if m.file_path and os.path.exists(m.file_path):
            os.remove(m.file_path)
        await db.delete(m)
    
    result = await db.execute(select(AnswerScript).where(AnswerScript.exam_id == exam_id))
    answer_scripts = result.scalars().all()
    for a in answer_scripts:
        if a.file_path and os.path.exists(a.file_path):
            os.remove(a.file_path)
        await db.delete(a)
    
    await db.commit()
    return JSONResponse({"success": True, "message": "All files deleted for this exam."})

@router.delete("/exams/{exam_id}/student_files")
async def reset_exam_files(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(AnswerScript).where(AnswerScript.exam_id == exam_id))
    answer_scripts = result.scalars().all()
    for a in answer_scripts:
        if a.file_path and os.path.exists(a.file_path):
            os.remove(a.file_path)
        await db.delete(a)
    
    await db.commit()
    return JSONResponse({"success": True, "message": "All Student Answer Scripts deleted for this exam."})

@router.delete("/exams/{exam_id}/files/{file_id}")
async def delete_exam_file(
    exam_id: int,
    file_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Material).where(
        Material.id == file_id,
        Material.related_exam_id == exam_id
    ))
    material = result.scalars().first()
    if material:
        if material.file_path and os.path.exists(material.file_path):
            os.remove(material.file_path)
        await db.delete(material)
        await db.commit()
        return JSONResponse({"success": True, "message": "Material file deleted."})
    
    result = await db.execute(select(AnswerScript).where(
        AnswerScript.id == file_id,
        AnswerScript.exam_id == exam_id
    ))
    answer_script = result.scalars().first()
    if answer_script:
        if answer_script.file_path and os.path.exists(answer_script.file_path):
            os.remove(answer_script.file_path)
        await db.delete(answer_script)
        await db.commit()
        return JSONResponse({"success": True, "message": "Answer script deleted."})
    
    raise HTTPException(status_code=404, detail="File not found for this exam.")

@router.delete("/exams/{exam_id}/questions")
async def delete_exam_questions(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Question).where(Question.exam_id == exam_id))
    questions = result.scalars().all()
    
    for question in questions:
        await db.delete(question)
    
    await db.commit()
    return {"success": True, "message": "All questions deleted for this exam"}

@router.post("/exams/{exam_id}/questions")
async def create_exam_question(
    exam_id: int,
    question: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    new_question = Question(
        exam_id=exam_id,
        question_number=question.get("question_number"),
        text=question.get("text"),
        max_marks=question.get("max_marks", 10)
    )
    db.add(new_question)
    await db.commit()
    await db.refresh(new_question)
    return {
        "id": new_question.id,
        "question_number": new_question.question_number,
        "text": new_question.text,
        "max_marks": new_question.max_marks
    }

@router.get("/exams/{exam_id}/questions/all")
async def get_exam_questions(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Question).where(Question.exam_id == exam_id).order_by(Question.question_number))
    questions = result.scalars().all()
    
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Question).where(Question.exam_id == exam_id).order_by(Question.question_number))
    questions = result.scalars().all()
    
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
    maxMarks: Optional[int]

class UpdatesPayload(BaseModel):
    updates: List[UpdatePartLabels]

@router.post("/exams/{exam_id}/questions/parts")
async def update_question_parts(
    exam_id: int,
    payload: UpdatesPayload,
    db: AsyncSession = Depends(get_db)
):
    for update in payload.updates:
        result = await db.execute(select(Question).where(
            Question.id == update.questionId,
            Question.exam_id == exam_id
        ))
        question = result.scalars().first()
        if not question:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Question with id {update.questionId} not found for exam {exam_id}"
            )
        question.part_labels = json.dumps(update.partLabels)
        if update.maxMarks is not None:
            question.max_marks = update.maxMarks

    await db.commit()
    return {"message": "Part labels and marks updated successfully"}

@router.get("/exams/{exam_id}/document/answer_script")
async def get_answer_scripts(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(AnswerScript).where(AnswerScript.exam_id == exam_id))
    answer_scripts = result.scalars().all()
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
    db: AsyncSession = Depends(get_db),
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
    await db.commit()
    await db.refresh(new_response)
    return JSONResponse({"success": True, "id": new_response.id})