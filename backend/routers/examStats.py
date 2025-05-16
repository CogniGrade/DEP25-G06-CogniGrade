from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from backend.database import get_db
from backend.models.tables import Exam, ExamResult, Enrollment, Question, QuestionResponse
from backend.models.files import AnswerScript
from backend.models.users import User
from backend.utils.security import get_current_user_required

# Import the external grading function from your geminiAPI module.
from backend.routers.geminiAPI import grade_question, extract_single_answer_text

import re

router = APIRouter(tags=["exam-stats"])

# ---------------------------------------------------------------------------
# 1. Overall Exam Statistics (Using the ExamResults table)
# ---------------------------------------------------------------------------
@router.get("/exams/{exam_id}/stats")
def get_exam_stats(exam_id: int,
                   db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user_required)):
    if not current_user.is_professor:
        raise HTTPException(status_code=403, detail="Access denied")
    
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    enrollments = db.query(Enrollment).filter(
        Enrollment.classroom_id == exam.classroom_id,
        Enrollment.status == "accepted",
        Enrollment.role == "student"
    ).all()
    
    students = []
    total_answer_scripts = 0
    graded_scripts = 0
    for enrollment in enrollments:
        student = enrollment.student
        # Since our workflow updates ExamResult immediately, we can look it up.
        result = db.query(ExamResult).filter(
            ExamResult.exam_id == exam_id,
            ExamResult.student_id == student.id
        ).first()
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

    # Create marks distribution buckets (0-9%, 10-19%, etc.)
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
    db: Session = Depends(get_db),
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

    # Retrieve the student's response for the given question
    response = db.query(QuestionResponse).filter(
        QuestionResponse.question_id == question_id,
        QuestionResponse.student_id == student_id
    ).first()
    
    if not response:
        raise HTTPException(status_code=404, detail="Response not found for this student and question.")
    
    # Update the marks and optional reasoning
    response.marks_obtained = grade
    # if reasoning:
    #     response.reasoning = reasoning
    
    db.commit()
    
    # Immediately update the overall ExamResult after marks edit.
    add_exam_result_internal(exam_id, student_id, db, current_user)
    
    return {"message": "Marks updated successfully"}


# ---------------------------------------------------------------------------
# 3. Detailed Student Evaluation (Question-wise breakdown)
# ---------------------------------------------------------------------------
@router.get("/exam/{exam_id}/student-evaluation/{student_id}")
async def get_student_evaluation(
    exam_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    questions = db.query(Question).filter(Question.exam_id == exam_id).all()
    evaluation = []
    for q in questions:
        response = db.query(QuestionResponse).filter(
            QuestionResponse.question_id == q.id,
            QuestionResponse.student_id == student_id
        ).first()
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    question = db.query(Question).filter(
        Question.id == question_id,
        Question.exam_id == exam_id
    ).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found.")
    if "text" in update_data:
        question.text = update_data["text"]
    if "ideal_answer" in update_data:
        question.ideal_answer = update_data["ideal_answer"]
    if "ideal_marking_scheme" in update_data:
        question.ideal_marking_scheme = update_data["ideal_marking_scheme"]
    db.commit()
    db.refresh(question)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    response = db.query(QuestionResponse).filter(
        QuestionResponse.question_id == question_id,
        QuestionResponse.student_id == student_id
    ).first()
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
    db.commit()
    # Immediately update ExamResult after response edit.
    add_exam_result_internal(exam_id, student_id, db, current_user)
    return {"message": "Updated successfully"}

# ---------------------------------------------------------------------------
# 5. Send for Re-evaluation (Reset marks, re-grade, and update ExamResult)
# ---------------------------------------------------------------------------
@router.post("/exam/{exam_id}/question/{question_id}/student/{student_id}/reevaluate")
async def send_for_reevaluation(
    exam_id: int,
    question_id: int,
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):  
    print("CALLED")
    response = db.query(QuestionResponse).filter(
        QuestionResponse.question_id == question_id,
        QuestionResponse.student_id == student_id
    ).first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")
    # Reset marks and update reasoning for re-evaluation.
    response.marks_obtained = None
    response.reasoning = "Sent for re-evaluation"
    db.commit()
    # Retrieve question details.
    question = db.query(Question).filter(Question.id == question_id).first()
    await extract_single_answer_text({
        "exam_id": exam_id,
        "student_id": student_id,
        "question_id": question_id,
    }, db, current_user)
    # Call grade_question directly.
    result = await grade_question({
        "exam_id": exam_id,
        "student_id": student_id,
        "question_id": question_id,
        # "student_answer": response.answer_text,
        "ideal_answer": question.ideal_answer,
        "marking_scheme": question.ideal_marking_scheme
    }, db, current_user)
    # Update the response with the new grade.
    response.marks_obtained = result.get("grade")
    response.reasoning = result.get("reasoning")
    db.commit()
    # After re-grading, update the overall exam result.
    add_exam_result_internal(exam_id, student_id, db, current_user)
    return {"message": "Sent for re-evaluation and exam result updated"}

# ---------------------------------------------------------------------------
# 6. Get Question Metrics (Per-question statistics)
# ---------------------------------------------------------------------------
@router.get("/exam/{exam_id}/question-metrics")
async def get_question_metrics(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    questions = db.query(Question).filter(Question.exam_id == exam_id).all()
    metrics = []
    for q in questions:
        responses = db.query(QuestionResponse).filter(QuestionResponse.question_id == q.id).all()
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    responses = db.query(QuestionResponse).filter(QuestionResponse.question_id == question_id).all()
    for r in responses:
        r.marks_obtained = 0
        add_exam_result_internal(exam_id, r.student_id, db, current_user)
        r.reasoning = "Question Dropped by professor"
    db.commit()
    return {"message": "Question dropped"}

# ---------------------------------------------------------------------------
# 8. Award Full Marks (For Entire Class on a Question)
# ---------------------------------------------------------------------------
@router.post("/exam/{exam_id}/question/{question_id}/full-marks")
async def give_full_marks(
    exam_id: int,
    question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    responses = db.query(QuestionResponse).filter(QuestionResponse.question_id == question_id).all()
    for r in responses:
        r.marks_obtained = question.max_marks
        add_exam_result_internal(exam_id, r.student_id, db, current_user)
        r.reasoning = "Full marks awarded by professor"
    db.commit()
    return {"message": "Full marks awarded"}

# ---------------------------------------------------------------------------
# 9. Get Grading Status (Based on Answer Scripts vs. Graded Responses)
# ---------------------------------------------------------------------------
@router.get("/exam/{exam_id}/grading-status")
async def get_grading_status(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    total = db.query(AnswerScript).filter(AnswerScript.exam_id == exam_id).count()
    graded = db.query(QuestionResponse).filter(
        QuestionResponse.question_id.in_(
            db.query(Question.id).filter(Question.exam_id == exam_id)
        ),
        QuestionResponse.marks_obtained.isnot(None)
    ).distinct(QuestionResponse.student_id).count()
    return {"total": total, "graded": graded}

# ---------------------------------------------------------------------------
# 10. Add Exam Result (Called after each answer script is graded)
# ---------------------------------------------------------------------------
@router.post("/exam/{exam_id}/add-result")
async def add_exam_result(
    exam_id: int,
    student_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # if not current_user.is_professor:
    #     raise HTTPException(status_code=403, detail="Access denied")
    
    student_id = student_id or current_user.id
    
    return add_exam_result_internal(exam_id, student_id, db, current_user)

# Internal function to update or create the ExamResult record.
def add_exam_result_internal(exam_id: int, student_id: int, db: Session, current_user: User):
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    
    # Instead of summing individual responses, we rely on the updated ExamResult.
    # In this workflow, every time a student's answer script is graded,
    # we update their ExamResult with the current total marks.
    # For safety, however, we can calculate the sum from QuestionResponse.
    question_ids = [q[0] for q in db.query(Question.id).filter(Question.exam_id == exam_id).all()]
    responses = db.query(QuestionResponse).filter(
        QuestionResponse.student_id == student_id,
        QuestionResponse.question_id.in_(question_ids)
    ).all()
    total_marks = sum(r.marks_obtained for r in responses if r.marks_obtained is not None)
    print(f"Total Marks for Student {student_id}: {total_marks}")
    exam_result = db.query(ExamResult).filter(
        ExamResult.exam_id == exam_id,
        ExamResult.student_id == student_id
    ).first()
    
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
    
    db.commit()
    db.refresh(exam_result)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Fetch the exam to ensure it exists
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found.")

    # Verify the question belongs to the exam
    question = db.query(Question).filter(
        Question.id == question_id,
        Question.exam_id == exam_id
    ).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found in this exam.")

    # Fetch the student’s response for the question
    response = db.query(QuestionResponse).filter(
        QuestionResponse.student_id == student_id,
        QuestionResponse.question_id == question_id
    ).first()
    if not response:
        raise HTTPException(status_code=404, detail="Response not found for this student and question.")

    # Return the response details
    return {
        "grade": response.marks_obtained,
        "response": response.answer_text
    }

# @router.get("/exams/{exam_id}/student/{student_id}/details")
# async def get_student_exam_details(
#     exam_id: int,
#     student_id: int,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user_required)
# ):
#     # Fetch the exam
#     exam = db.query(Exam).filter(Exam.id == exam_id).first()
#     if not exam:
#         raise HTTPException(status_code=404, detail="Exam not found.")

#     pattern = re.compile(r"Max(?:imum)?\s*Marks\s*(?:[:\-]\s*)?\d+", re.IGNORECASE)
#     questions = db.query(Question).filter(Question.exam_id == exam_id).order_by(Question.question_number).all()
#     evaluation = []
#     for q in questions:
#         response = db.query(QuestionResponse).filter(
#             QuestionResponse.question_id == q.id,
#             QuestionResponse.student_id == current_user.id
#         ).first()
#         marks_obtained = response.marks_obtained if response and response.marks_obtained is not None else ""
#         query_text = response.query if response and response.query else ""
#         # Remove "Max(imum) Marks" substring
#         clean_text = re.sub(pattern, "", q.text).strip()
#         reasoning_text = response.reasoning if response and response.reasoning else ""
        
#         evaluation.append({
#             "question_id": q.id,
#             "question_number": q.question_number,
#             "full_question_text": q.text, # Add the full question text
#             "max_marks": q.max_marks,
#             "marks_obtained": marks_obtained,
#             "reasoning": reasoning_text, # Add the reasoning text
#             "query": query_text
#         })
#     # Construct the answer sheet HTML (simplified example)
#     # answer_sheet_html = "<p>Student's complete answer sheet goes here.</p>"  # Replace with actual rendering logic if needed

#     # Prepare question-wise details
#     questions = [
#         {
#             "id": response.question_id,
#             "grade": response.marks_obtained,
#             "response": response.answer_text,
#             "reasoning": response.reasoning or "Not provided"  # Assuming a reasoning field exists
#         }
#         for response in responses
#     ]

#     return {
#         # "answer_sheet_html": answer_sheet_html,
#         "questions": questions
#     }