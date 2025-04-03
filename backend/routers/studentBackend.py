from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models.users import User
from backend.models.files import Material, AnswerScript, FileTypeEnum
from backend.utils.security import get_current_user_required
from backend.models.tables import QuestionResponse, Question  # Ensure Question is imported
import re
router = APIRouter(prefix="/student", tags=["studentBackend"])

@router.get("/exam/{exam_id}/available-documents")
def available_documents(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """
    Returns a dictionary indicating the availability of each document type for the given exam.
    For Answer-Script, the query uses the current student (current_user.id).
    For the other types (Question-Paper, Solution-Script, Marking-Scheme),
    the query is made against the Materials table using the exam_id.
    """
    available = {}

    # Check for Answer-Script availability (stored in AnswerScript table)
    answer_script = db.query(AnswerScript).filter(
        AnswerScript.exam_id == exam_id,
        AnswerScript.student_id == current_user.id
    ).first()
    available["Answer-Script"] = bool(answer_script)

    # Mapping for the three document types stored in the Materials table.
    mapping = {
        "Question-Paper": FileTypeEnum.question_paper,
        "Solution-Script": FileTypeEnum.solution_script,
        "Marking-Scheme": FileTypeEnum.marking_scheme,
    }
    for option, file_enum in mapping.items():
        material = db.query(Material).filter(
            Material.related_exam_id == exam_id,
            Material.file_type == file_enum
        ).first()
        available[option] = bool(material)

    return available


@router.get("/exam/{exam_id}/document/{doc_type}")
def get_document(
    exam_id: int,
    doc_type: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """
    Returns the document details (file_path and extracted_text) for the given exam and doc_type.
    If doc_type is "Answer-Script", the AnswerScript table is used (with the current student's id);
    Otherwise, for "Question-Paper", "Solution-Script", or "Marking-Scheme", the Materials table is used.
    """
    doc_type_norm = doc_type.lower()

    if doc_type_norm == "answer-script":
        document = db.query(AnswerScript).filter(
            AnswerScript.exam_id == exam_id,
            AnswerScript.student_id == current_user.id
        ).first()
        if not document:
            raise HTTPException(status_code=404, detail="Answer Script not found.")
    elif doc_type_norm in ["question-paper", "solution-script", "marking-scheme"]:
        mapping = {
            "question-paper": FileTypeEnum.question_paper,
            "solution-script": FileTypeEnum.solution_script,
            "marking-scheme": FileTypeEnum.marking_scheme
        }
        file_enum = mapping.get(doc_type_norm)
        document = db.query(Material).filter(
            Material.related_exam_id == exam_id,
            Material.file_type == file_enum
        ).first()
        if not document:
            raise HTTPException(status_code=404, detail=f"{doc_type.title()} not found.")
    else:
        raise HTTPException(status_code=400, detail="Invalid document type requested.")

    return {
        "file_path": document.file_path,
        "extracted_text": document.extracted_text
    }

@router.post("/exam/{exam_id}/student-responses")
def create_student_response(
    exam_id: int,
    response_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """Create or update a student's response to a question"""
    existing_response = db.query(QuestionResponse).filter(
        QuestionResponse.question_id == response_data.get("question_id"),
        QuestionResponse.student_id == response_data.get("student_id")
    ).first()
    
    if existing_response:
        existing_response.answer_text = response_data.get("answer_text")
        db.commit()
        db.refresh(existing_response)
        return {
            "id": existing_response.id,
            "message": "Response updated successfully"
        }
    else:
        new_response = QuestionResponse(
            question_id=response_data.get("question_id"),
            student_id=response_data.get("student_id"),
            answer_text=response_data.get("answer_text")
        )
        db.add(new_response)
        db.commit()
        db.refresh(new_response)
        return {
            "id": new_response.id,
            "message": "Response created successfully"
        }

# --- New Endpoints for Evaluation Table and Posting Query ---

def strip_markdown(text: str) -> str:
    # Remove inline code formatting
    text = re.sub(r'`(.+?)`', r'\1', text)
    # Remove bold and italic formatting
    text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)
    text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)
    # Remove strikethrough formatting
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    # Remove any leftover markdown characters (like headers, blockquotes, lists)
    text = re.sub(r'[>#\-\+]', '', text)
    return text.strip()

@router.get("/exam/{exam_id}/evaluation")
def get_exam_evaluation(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """
    Returns a list of questions for the exam along with the student's responses.
    For each question:
      - Any substring matching the regex /Max(?:imum)?\s*Marks\s*(?:[:\-]\s*)?(\d+)/i is removed.
      - Markdown formatting is stripped.
      - The question number is prepended in the format "QX) " (where X is the question number).
      - The resulting text is truncated to 50 characters (with "..." appended if needed).
    Also returns the marks obtained (if any) and any query raised.
    """
    pattern = re.compile(r"Max(?:imum)?\s*Marks\s*(?:[:\-]\s*)?\d+", re.IGNORECASE)
    questions = db.query(Question).filter(Question.exam_id == exam_id).order_by(Question.question_number).all()
    evaluation = []
    for q in questions:
        response = db.query(QuestionResponse).filter(
            QuestionResponse.question_id == q.id,
            QuestionResponse.student_id == current_user.id
        ).first()
        marks_obtained = response.marks_obtained if response and response.marks_obtained is not None else ""
        query_text = response.query if response and response.query else ""
        # Remove "Max(imum) Marks" substring
        clean_text = re.sub(pattern, "", q.text).strip()
        # Remove markdown formatting
        clean_text = strip_markdown(clean_text)
        # Prepend the question number in the format "QX) "
        full_text = f"Q{q.question_number}) " + clean_text
        # Truncate to 50 characters if needed
        truncated_text = full_text if len(full_text) <= 50 else full_text[:50] + "..."
        reasoning_text = response.reasoning if response and response.reasoning else ""
        
        evaluation.append({
            "question_id": q.id,
            "question_number": q.question_number,
            "text": truncated_text, # Keep truncated text for the main display
            "full_question_text": q.text, # Add the full question text
            "max_marks": q.max_marks,
            "marks_obtained": marks_obtained,
            "reasoning": reasoning_text, # Add the reasoning text
            "query": query_text
        })
    return evaluation


@router.post("/exam/{exam_id}/post-query")
def post_query(
    exam_id: int,
    query_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """
    Updates (or creates) the student's query for a particular question.
    Expects a JSON payload with 'question_id' and 'query' keys.
    """
    question_id = query_data.get("question_id")
    query_text = query_data.get("query")
    if not question_id or query_text is None:
        raise HTTPException(status_code=400, detail="Missing question_id or query")
    
    response = db.query(QuestionResponse).filter(
        QuestionResponse.question_id == question_id,
        QuestionResponse.student_id == current_user.id
    ).first()
    
    if response:
        response.query = query_text
        db.commit()
        db.refresh(response)
        return {"id": response.id, "message": "Query updated successfully", "query": response.query}
    else:
        new_response = QuestionResponse(
            question_id=question_id,
            student_id=current_user.id,
            answer_text="",
            query=query_text
        )
        db.add(new_response)
        db.commit()
        db.refresh(new_response)
        return {"id": new_response.id, "message": "Query created successfully", "query": new_response.query}
