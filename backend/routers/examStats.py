from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import TIMESTAMP
from backend.database import get_db
from backend.models.tables import Exam, ExamResult, Enrollment, Question, QuestionResponse
from backend.models.files import AnswerScript
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.routers.geminiAPI import grade_question, grade_question_with_diagram, extract_single_answer_text
import re

router = APIRouter(tags=["exam-stats"])

@router.get("/exams/{exam_id}/stats")
async def get_exam_stats(exam_id: int,
                        db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(get_current_user_required)):
    if not current_user.is_professor:
        raise HTTPException(status_code=403, detail="Access denied")
    
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalars().first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    result = await db.execute(select(Enrollment)
        .options(selectinload(Enrollment.student))
        .where(
            Enrollment.classroom_id == exam.classroom_id,
            Enrollment.status == "accepted",
            Enrollment.role == "student"
        )
    )
    enrollments = result.scalars().all()
    
    students = []
    total_answer_scripts = 0
    graded_scripts = 0
    for enrollment in enrollments:
        student = enrollment.student
        result = await db.execute(select(ExamResult).where(
            ExamResult.exam_id == exam_id,
            ExamResult.student_id == student.id
        ))
        result = result.scalars().first()
        total_marks = result.marks_obtained if result and result.marks_obtained is not None else 0
        percentage = round((total_marks / exam.points_possible) * 100, 2) if exam.points_possible else 0
        students.append({
            "id": student.id,
            "email": student.email,
            "name": student.full_name,
            "roll": getattr(student, "entry_number", None),
            "total_marks": total_marks,
            "percentage": percentage
        })
        if result and result.marks_obtained is not None:
            graded_scripts += 1
        total_answer_scripts += 1

    buckets = [0] * (exam.points_possible*2 + 1)
    for s in students:
        bucket = int(s["total_marks"]*2)
        buckets[bucket] += 1
    distribution = {
        "labels": [f"{i/2}" for i in range(exam.points_possible*2 + 1)],
        "data": buckets
    }
    grading_progress = graded_scripts / total_answer_scripts if total_answer_scripts else 0
    return JSONResponse({
        "students": students,
        "grading_progress": grading_progress,
        "marks_distribution": distribution
    })

# ---------------------------------------------------------------------------
# 2. Students Performance (Calculated from the ExamResult table)
# ---------------------------------------------------------------------------
# @router.get("/exam/{exam_id}/students-performance")
# async def get_students_performance(
#     exam_id: int,
#     db: AsyncSession = Depends(get_db),
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
#         result = db.query(ExamResult).filter(
#             ExamResult.exam_id == exam_id,
#             ExamResult.student_id == student.id
#         ).first()
#         total_marks = result.marks_obtained if result and result.marks_obtained is not None else 0
#         percentage = (total_marks / exam.points_possible * 100) if exam.points_possible else 0
#         performance.append({
#             "student_id": student.id,
#             "name": student.full_name,
#             "roll_number": getattr(student, "entry_number", None),
#             "total_marks": total_marks,
#             "percentage": percentage
#         })
#     return JSONResponse(performance)

@router.patch("/exams/{exam_id}/student/{student_id}/question/{question_id}/update")
async def edit_marks(
    exam_id: int,
    question_id: int,
    student_id: int,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """
    Endpoint to manually edit the marks for a student's response to a question.
    Receives the new marks and optional reasoning from form data. After updating,
    it calls the internal function to update the overall exam result.
    """
    grade = payload["grade"]
    # Ensure the professor is making the request
    if not current_user.is_professor:
        raise HTTPException(status_code=403, detail="Access denied")

    result = await db.execute(select(QuestionResponse).where(
        QuestionResponse.question_id == question_id,
        QuestionResponse.student_id == student_id
    ))
    response = result.scalars().first()
    
    if not response:
        raise HTTPException(status_code=404, detail="Response not found for this student and question.")
    
    response.marks_obtained = payload["grade"]
    await db.commit()
    
    await add_exam_result_internal(exam_id, student_id, db, current_user)
    
    return {"message": "Marks updated successfully"}

# ---------------------------------------------------------------------------

# 3. Detailed Student Evaluation (Question-wise breakdown)

# ---------------------------------------------------------------------------

@router.get("/exam/{exam_id}/student-evaluation/{student_id}")
async def get_student_evaluation(
    exam_id: int,
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Question).where(Question.exam_id == exam_id))
    questions = result.scalars().all()
    evaluation = []
    for q in questions:
        result = await db.execute(select(QuestionResponse).where(
            QuestionResponse.question_id == q.id,
            QuestionResponse.student_id == student_id
        ))
        response = result.scalars().first()
        evaluation.append({
            "question_id": q.id,
            "question_number": q.question_number,
            "text": q.text[:50] + "..." if len(q.text) > 50 else q.text,
            "full_question_text": q.text,
            "student_response": response.answer_text if response else None,
            "reasoning": response.reasoning if response else None,
            "ideal_answer": q.ideal_answer,
            "marking_scheme": q.ideal_marking_scheme,
            "marks_obtained": response.marks_obtained if response else None,
            "max_marks": q.max_marks
        })
    return JSONResponse(evaluation)

# ---------------------------------------------------------------------------
# 4. Update Question or Student Response (Manual Edit)
# ---------------------------------------------------------------------------

@router.patch("/exams/{exam_id}/questions/{question_id}")
async def update_question(
    exam_id: int,
    question_id: int,
    update_data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Question).where(
        Question.id == question_id,
        Question.exam_id == exam_id
    ))
    question = result.scalars().first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found.")
    if "text" in update_data:
        question.text = update_data["text"]
    if "ideal_answer" in update_data:
        question.ideal_answer = update_data["ideal_answer"]
    if "ideal_marking_scheme" in update_data:
        question.ideal_marking_scheme = update_data["ideal_marking_scheme"]
    await db.commit()
    await db.refresh(question)
    return JSONResponse({
        "success": True,
        "question": {
            "id": question.id,
            "text": question.text,
            "ideal_answer": question.ideal_answer,
            "ideal_marking_scheme": question.ideal_marking_scheme
        }
    })

@router.patch("/exam/{exam_id}/question/{question_id}/student/{student_id}/update")
async def update_student_response(
    exam_id: int,
    question_id: int,
    student_id: int,
    update_data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(QuestionResponse).where(
        QuestionResponse.question_id == question_id,
        QuestionResponse.student_id == student_id
    ))
    response = result.scalars().first()
    if not response:
        response = QuestionResponse(
            question_id=question_id,
            student_id=student_id,
            answer_text=update_data.get("response", ""),
            marks_obtained=update_data.get("marks_obtained"),
            reasoning=update_data.get("reasoning", "")
        )
        db.add(response)
    else:
        response.answer_text = update_data.get("response", response.answer_text)
        response.marks_obtained = update_data.get("marks_obtained", response.marks_obtained)
        response.reasoning = update_data.get("reasoning", response.reasoning)
    await db.commit()
    await add_exam_result_internal(exam_id, student_id, db, current_user)
    return {"message": "Updated successfully"}

# ---------------------------------------------------------------------------
# 5. Send for Re-evaluation (Reset marks, re-grade, and update ExamResult)
# ---------------------------------------------------------------------------
@router.post("/exam/{exam_id}/question/{question_id}/student/{student_id}/reevaluate")
async def send_for_reevaluation(
    exam_id: int,
    question_id: int,
    student_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):  
    print("CALLED")
    result = await db.execute(select(QuestionResponse).where(
        QuestionResponse.question_id == question_id,
        QuestionResponse.student_id == student_id
    ))
    response = result.scalars().first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")
    response.marks_obtained = None
    response.reasoning = "Sent for re-evaluation"
    await db.commit()
    result = await db.execute(select(Question).where(Question.id == question_id))
    question = result.scalars().first()
    await extract_single_answer_text({
        "exam_id": exam_id,
        "student_id": student_id,
        "question_id": question_id,
    }, db, current_user)
    result = await grade_question_with_diagram({
        "exam_id": exam_id,
        "student_id": student_id,
        "question_id": question_id,
        "ideal_answer": question.ideal_answer,
        "marking_scheme": question.ideal_marking_scheme
    }, db, current_user)
    response.marks_obtained = result.get("grade")
    response.reasoning = result.get("reasoning")
    await db.commit()
    await add_exam_result_internal(exam_id, student_id, db, current_user)
    return {"message": "Sent for re-evaluation and exam result updated"}

@router.get("/exam/{exam_id}/question-metrics")
async def get_question_metrics(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Question).where(Question.exam_id == exam_id))
    questions = result.scalars().all()
    metrics = []
    for q in questions:
        result = await db.execute(select(QuestionResponse).where(QuestionResponse.question_id == q.id))
        responses = result.scalars().all()
        marks = [r.marks_obtained for r in responses if r.marks_obtained is not None]
        metrics.append({
            "question_id": q.id,
            "question_number": q.question_number,
            "text": q.text,
            "ideal_answer": q.ideal_answer,
            "max_marks": q.max_marks,
            "marks_distribution": marks
        })
    return JSONResponse(metrics)

# ---------------------------------------------------------------------------
# 7. Drop Question (Assign Zero Marks)
# ---------------------------------------------------------------------------
@router.post("/exam/{exam_id}/question/{question_id}/drop")
async def drop_question(
    exam_id: int,
    question_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(QuestionResponse).where(QuestionResponse.question_id == question_id))
    responses = result.scalars().all()
    for r in responses:
        r.marks_obtained = 0
        await add_exam_result_internal(exam_id, r.student_id, db, current_user)
        r.reasoning = "Question Dropped by professor"
    await db.commit()
    return {"message": "Question dropped"}

# ---------------------------------------------------------------------------
# 8. Award Full Marks (For Entire Class on a Question)
# ---------------------------------------------------------------------------
@router.post("/exam/{exam_id}/question/{question_id}/full-marks")
async def give_full_marks(
    exam_id: int,
    question_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Question).where(Question.id == question_id))
    question = result.scalars().first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    result = await db.execute(select(QuestionResponse).where(QuestionResponse.question_id == question_id))
    responses = result.scalars().all()
    for r in responses:
        r.marks_obtained = question.max_marks
        await add_exam_result_internal(exam_id, r.student_id, db, current_user)
        r.reasoning = "Full marks awarded by professor"
    await db.commit()
    return {"message": "Full marks awarded"}

# ---------------------------------------------------------------------------
# 9. Get Grading Status (Based on Answer Scripts vs. Graded Responses)
# ---------------------------------------------------------------------------
@router.get("/exam/{exam_id}/grading-status")
async def get_grading_status(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    from sqlalchemy import func
    result = await db.execute(select(func.count()).select_from(AnswerScript).where(AnswerScript.exam_id == exam_id))
    total = result.scalar()
    result = await db.execute(select(Question.id).where(Question.exam_id == exam_id))
    question_ids = [row[0] for row in result.fetchall()]
    result = await db.execute(select(func.count()).select_from(QuestionResponse).where(
        QuestionResponse.question_id.in_(question_ids),
        QuestionResponse.marks_obtained.isnot(None)
    ).distinct(QuestionResponse.student_id))
    graded = result.scalar()
    return {"total": total, "graded": graded}

# ---------------------------------------------------------------------------
# 10. Add Exam Result (Called after each answer script is graded)
# ---------------------------------------------------------------------------
@router.post("/exam/{exam_id}/add-result")
async def add_exam_result(
    exam_id: int,
    student_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    student_id = student_id or current_user.id
    return await add_exam_result_internal(exam_id, student_id, db, current_user)

async def add_exam_result_internal(exam_id: int, student_id: int, db: AsyncSession, current_user: User):
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalars().first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    result = await db.execute(select(Question.id).where(Question.exam_id == exam_id))
    question_ids = [row[0] for row in result.fetchall()]
    result = await db.execute(select(QuestionResponse).where(
        QuestionResponse.student_id == student_id,
        QuestionResponse.question_id.in_(question_ids)
    ))
    responses = result.scalars().all()
    total_marks = sum(r.marks_obtained for r in responses if r.marks_obtained is not None)
    print(f"Total Marks for Student {student_id}: {total_marks}")
    result = await db.execute(select(ExamResult).where(
        ExamResult.exam_id == exam_id,
        ExamResult.student_id == student_id
    ))
    exam_result = result.scalars().first()
    
    if exam_result:
        exam_result.marks_obtained = total_marks
        exam_result.graded_by = current_user.id
        exam_result.graded_at = datetime.now(timezone.utc)
    else:
        exam_result = ExamResult(
            exam_id=exam_id,
            student_id=student_id,
            marks_obtained=total_marks,
            graded_by=current_user.id,
            graded_at=datetime.now(timezone.utc)
        )
        db.add(exam_result)
    
    await db.commit()
    await db.refresh(exam_result)
    return JSONResponse({
        "success": True,
        "result": {
            "student_id": student_id,
            "marks_obtained": total_marks,
            "graded_at": exam_result.graded_at.isoformat()
        }
    })

@router.get("/exams/{exam_id}/student/{student_id}/question/{question_id}/details")
async def get_student_question_details(
    exam_id: int,
    student_id: int,
    question_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalars().first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    result = await db.execute(select(Question).where(
        Question.id == question_id,
        Question.exam_id == exam_id
    ))
    question = result.scalars().first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found in this exam.")

    result = await db.execute(select(QuestionResponse).where(
        QuestionResponse.student_id == student_id,
        QuestionResponse.question_id == question_id
    ))
    response = result.scalars().first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found for this student and question.")

    return {
        "grade": response.marks_obtained,
        "response": response.answer_text
    }