import os
import uuid
import io
from typing import List, Optional

import google.generativeai as genai
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException, Form
from fastapi.responses import JSONResponse, RedirectResponse
from PIL import Image
import logging
from sqlalchemy.orm import Session


from backend.database import get_db
from backend.models.files import AnswerScript, Material, FileTypeEnum
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.models.tables import QuestionResponse, Question

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")



# Create uploads folder.
UPLOAD_DIRECTORY = "./uploads"
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["gemini-api"])

@router.post("/extract-text")
async def upload_and_extract(
    files: List[UploadFile] = File(...),
    exam_id: int = Form(...),
    file_type: str = Form(...),   # expected: "question_paper", "solution_script", "marking_scheme", "answer_sheet"
    student_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    results = []
    try:
        file_type_enum = FileTypeEnum(file_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file type provided.")
    for file in files:
        try:
            # Check if a record already exists based on filename, exam_id and file_type.
            if file_type_enum in [FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme]:
                existing = db.query(Material).filter(
                    Material.title == file.filename,
                    Material.related_exam_id == exam_id,
                    Material.file_type == file_type_enum
                ).first()
                
            elif file_type_enum == FileTypeEnum.answer_sheet:
                if not student_id:
                    raise HTTPException(status_code=400, detail="student_id is required for answer_sheet.")
                existing = db.query(AnswerScript).filter(
                    AnswerScript.title == file.filename,
                    AnswerScript.exam_id == exam_id,
                    AnswerScript.student_id == student_id,
                    # In a real application, consider a more reliable uniqueness check (e.g. hash of the file)
                    # Here we assume that if the same file is re-uploaded, the filename will match.
                    # Note: AnswerScript does not store filename, so we compare file_path after saving.
                ).first()
            else:
                existing = None

            # If a record exists and extracted_text is not empty, use it.
            if existing and existing.extracted_text:
                results.append({"filename": file.filename, "text": existing.extracted_text})
                continue

            # Read the file bytes and save a copy on disk
            file_id = str(uuid.uuid4())
            file_location = os.path.join(UPLOAD_DIRECTORY, f"{file_id}_{file.filename}")
            
            with open(file_location, "wb") as f:
                f.write(await file.read())

            print(f"Uploading {file.filename} to Gemini...")  # Debug log

            # Upload file to Gemini AI
            sample_file = genai.upload_file(path=file_location, display_name=file.filename)

            if file_type_enum in [FileTypeEnum.question_paper]:
                # Use uploaded file in Gemini API request
                prompt = """Extract text from the image, preserving all formatting (tables, bullet points, etc.). Remove any "Instructions" section at the beginning. Before each answer, mention: 
Question Number - X
Max Marks - Y
where X is the question number and Y is the allocated marks to that question (mentioned along with the question, or inferred from "Instructions" section if available). Ignore any text that is not a part of the questions.""" 
            elif file_type_enum in [FileTypeEnum.answer_sheet, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme]:
                # Use uploaded file in Gemini API request
                prompt = """The pdfs and images may contain text portions linked by complex arrows, creating a loosely structured flow between different text elements. Extract the text accurately along with its connections. Keep the correct formatting as in image, maintaining the tables, bulletting etc. Before each answer, always mention: 
Question Number - X
Ignore any text that is irrelevent to the question answers."""
            response = model.generate_content((sample_file, prompt))
            #"between different text elements. Extract the text accurately along with its connections.""])
            extracted_text = response.text if response.text else "No text extracted."

            # If a record exists but text is empty, update it.
            if existing:
                if file_type_enum in [FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme]:
                    existing.extracted_text = extracted_text
                    db.commit()
                    results.append({"filename": file.filename, "text": extracted_text})
                elif file_type_enum == FileTypeEnum.answer_sheet:
                    existing.extracted_text = extracted_text
                    db.commit()
                    results.append({"filename": file.filename, "text": extracted_text})
            else:
                # No existing record; create a new one.
                if file_type_enum in [FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme]:
                    new_material = Material(
                        title=file.filename,
                        description="",
                        file_path=file_location,
                        file_size=int(round(file.size, 0)),
                        link_url=None,
                        related_exam_id=exam_id,
                        author_id=current_user.id,
                        extracted_text=extracted_text,
                        file_type=file_type_enum
                    )
                    db.add(new_material)
                    db.commit()
                    db.refresh(new_material)
                    results.append({"filename": file.filename, "text": extracted_text})
                elif file_type_enum == FileTypeEnum.answer_sheet:
                    new_answer = AnswerScript(
                        title=file.filename,
                        file_path=file_location,
                        file_size=int(round(file.size, 0)),
                        exam_id=exam_id,
                        student_id=student_id,
                        extracted_text=extracted_text
                    )
                    db.add(new_answer)
                    db.commit()
                    db.refresh(new_answer)
                    results.append({"filename": file.filename, "text": extracted_text})
        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {str(e)}", exc_info=True)
            results.append({"filename": file.filename, "error": str(e)})
    
    return JSONResponse({"results": results})

@router.post("/grade-question")
async def grade_question(
    request: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    try:
        # Extract data from the request payload
        student_answer = request.get("student_answer")
        ideal_answer = request.get("ideal_answer")
        marking_scheme = request.get("marking_scheme")
        exam_id = request.get("exam_id")
        student_id = request.get("student_id")
        question_id = request.get("question_id")
        
        # Ensure required parameters exist:
        if not student_answer or (not ideal_answer and not marking_scheme):
            raise HTTPException(status_code=400, detail="Missing required parameters. Provide student_answer and at least one of ideal_answer or marking_scheme.")
        
        # Fetch the particular question from the database
        question = db.query(Question).filter(
            Question.id == question_id,
            Question.exam_id == exam_id
        ).first()
        if not question:
            raise HTTPException(status_code=404, detail="Question not found.")
        
        # Build the prompt based on available data
        if marking_scheme and ideal_answer:
            # Both marking scheme and ideal answer exist
            prompt = f"""Question: {question.text}

This is the correct marking scheme: {marking_scheme}

Ideal Answer: {ideal_answer}

Based on these, grade the following student answer: {student_answer}

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X
Reason: Some Text"""
        elif marking_scheme:
            # Only marking scheme provided
            prompt = f"""Question: {question.text}

This is the correct marking scheme: {marking_scheme}

Grade the following student answer: {student_answer}

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X
Reason: Some Text"""
        elif ideal_answer:
            # Only ideal answer provided
            prompt = f"""Question: {question.text}

Ideal Answer: {ideal_answer}

Grade the following student answer: {student_answer}

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X
Reason: Some Text"""
        
        # Call the Gemini API to generate content based on the prompt
        response = model.generate_content(prompt)
        result_text = response.text
        
        # Parse the API response to extract grade and reasoning
        grade = None
        reason = ""
        if "Grade:" in result_text:
            grade_line = [line for line in result_text.split('\n') if "Grade:" in line][0]
            grade_str = grade_line.split("Grade:")[1].strip()
            try:
                grade = int(grade_str.split()[0])
            except ValueError:
                pass
        if "Reason:" in result_text:
            reason_parts = result_text.split("Reason:")
            if len(reason_parts) > 1:
                reason = reason_parts[1].strip()
        
        # Update or create the corresponding QuestionResponse record in the database
        if question_id and student_id and exam_id and grade is not None:
            existing_response = db.query(QuestionResponse).filter(
                QuestionResponse.question_id == question_id,
                QuestionResponse.student_id == student_id
            ).first()
            if existing_response:
                existing_response.marks_obtained = grade
                existing_response.reasoning = reason
                db.commit()
            # Optionally, create a new response record if one does not exist.
        
        return {"grade": grade, "reasoning": reason, "raw_response": result_text}
        
    except Exception as e:
        logger.error(f"Error in grade_question: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error grading question: {str(e)}")
