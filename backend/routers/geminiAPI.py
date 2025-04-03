import os
import uuid
import io
from typing import List, Optional
import logging
from threading import Lock

import google.generativeai as genai
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException, Form
from fastapi.responses import JSONResponse, RedirectResponse
from PIL import Image
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.files import AnswerScript, Material, FileTypeEnum
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.models.tables import QuestionResponse, Question

# Dynamically load API keys from environment variables.
api_keys = []
i = 1
while True:
    key = os.getenv(f"GEMINI_API_KEY_{i}")
    if not key:
        break
    api_keys.append(key)
    i += 1

if not api_keys:
    raise RuntimeError("No GEMINI_API_KEY_X environment variables found.")

# Create model instances for each API key using the same model.
model_name = "gemini-1.5-flash"
models = []
for key in api_keys:
    genai.configure(api_key=key)
    models.append(genai.GenerativeModel(model_name))

# Global call counter and lock for thread safety.
call_count = 0
call_lock = Lock()
calls_per_key = 15  # Switch API key after this many calls.

def get_model():
    """Return the appropriate model instance based on a global call counter.
    
    The models are rotated every 'calls_per_key' calls.
    """
    global call_count
    with call_lock:
        call_count += 1
        index = ((call_count - 1) // calls_per_key) % len(models)
        print(f"Number of calls: {call_count}")
        # If a switch is happening, print which model is now being used.
        if (call_count - 1) % calls_per_key == 0:
            print(f"Switching to model {index}")
        return models[index]


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
                ).first()
            else:
                existing = None

            # If a record exists and extracted_text is not empty, use it.
            if existing and existing.extracted_text:
                results.append({"filename": file.filename, "text": existing.extracted_text})
                continue

            # Read the file bytes and save a copy on disk.
            file_id = str(uuid.uuid4())
            file_location = os.path.join(UPLOAD_DIRECTORY, f"{file_id}_{file.filename}")
            with open(file_location, "wb") as f:
                f.write(await file.read())

            logger.info(f"Uploading {file.filename} to Gemini...")

            # Upload file to Gemini AI.
            sample_file = genai.upload_file(path=file_location, display_name=file.filename)

            # Build prompt based on file type.
            if file_type_enum == FileTypeEnum.question_paper:
                logger.info("Question Paper detected.")
                prompt = """
Task: Extract the printed questions from the provided document. Also, label each extracted question with its maximum marks if mentioned.

Instructions:
1. Ensure that every complete printed question present in the document is extracted.
2. Question Labeling:
    - Question Labeling: Label as "Question Number - X Max Marks - Y" (visible) or "Question Number - [X] Max Marks - Y" (unclear/absent/expected), where X is the Question Number, and Y is the marks for that question. For subparts, label as "Question Number - X(subpart)". Extract all answers even with duplicate question numbers.
    Example - "Question Number - 1(a) Max Marks - 10" if a question is labelled as 1 and has a subpart (a), and maximum marks of 10.
    
    - Two or more questions can have the same Question Number, extract as is, do not skip any question.
(a) Part 1...
(b) Part 2..." and so on.

3. Max marks for any question can be inferred by looking up the marks distribution scheme in the instructions section of the question paper, or if explicitly mentioned beside the question)
4. If the document contains both printed questions and handwritten answers, focus solely on extracting the printed questions.
5. Do not extract any printed text that is not part of any question (e.g., instructions, headings, page numbers).
"""
            elif file_type_enum == FileTypeEnum.answer_sheet:
                prompt = """
Task: Extract handwritten answer sections(messy handwriting, handwritten code possible), preserving formatting, layout, code spacing, arrows, bullet points, and linking annotations.
Do not correct student's answer. Don't change the student's answer at all.
Instructions:
1. **Extract All Answers:** Ensure every complete handwritten answer is extracted. Very importantly, do not yourself correct any question.
2. Question Labeling: Label as "Question Number - X" (visible) or "Question Number - [X]" (unclear/absent/expected), where X is the Question Number. For subparts, label as "Question Number - X(subpart)". Extract all answers even with duplicate question numbers.
Example - "Question Number - 1(a)" if a question is labelled as 1 and has a subpart (a).
3. **Completion Questions:**
    - **Identify Initial Part:** For completion questions ("Complete...", "Fill in..."), find the provided initial answer. Look for three dots "...", blanks "___" or other visual cues.
    - **Concatenate:** Combine the initial part with the student's completion, preserving formatting.
4. **Differentiate Answers:** Use cues like "Answer :" etc, spatial separation, or box regions to identify answer sections.
5. **Formatting:** You may rearrange, reformat the response if the question explicitly states so. But do not correct any incorrect content in the answer. Otherwise preserve the structure as present in the student's answer.
6. **Ignore Struck-Out/Scribbled Content:** Omit any word or line that is strikethrough or scribbled out from the extracted answer.
7. **Ignore Irrelevant Text:** Extract only student answers, not instructions, headings, etc.
8. Recheck the extracted answer to ensure it is the exact same as the student's answer, and that it is not missing any part of the answer. If you find any missing part, add it to the extracted answer.

"""
            elif file_type_enum in [FileTypeEnum.solution_script, FileTypeEnum.marking_scheme]:
                prompt = """
Task: Extract solution/marking scheme sections with associated marks, preserving formatting, layout, code spacing, arrows, bullet points, and linking annotations.

Context: Analyze solution scripts or marking schemes (handwritten possible). Sections may include question numbers, or full question texts also, along with mark allocations. Extract all solutions/marking points and their marks, handling non-sequential links and specific format instructions.

Instructions:

1. **Extract All with Marks:** Extract every complete solution/marking point. If marks are explicitly mentioned for any part, extract that mark information and associate it. Review layout to ensure all sections and their marks are captured and correctly labeled.

2. **Understand Question Context:** Read the question number or full question alongside each solution. Understand the context and any format instructions within the question to guide extraction.

3. **Labeling (Including Marks):**
    - Label with "Question Number - X" if clear, where X is the Question Number.
    - Label with "Question Number - [X]" if unclear or absent, where X is the Question Number.
    - Two or more questions can have the same Question Number, extract as is, do not skip any question's answer.
4. **Differentiate and Associate Marks:** Use spatial cues and markers to identify distinct solution sections and their corresponding marks.

5. **Formatting:** Preserve original structure and formatting, including mark placements. Do not correct content.

6. **Ignore Struck-Out Content:** Omit any strikethrough or scribbled content, including marks.

7. **Ignore Irrelevant Text:** Extract only solution content and associated marks directly related to questions.
"""

            # Use the selected model (and corresponding API key) to generate content.
            response = get_model().generate_content((sample_file, prompt))
            extracted_text = response.text if response.text else "No text extracted."

            # Update existing record or create a new one.
            if existing:
                existing.extracted_text = extracted_text
                db.commit()
                results.append({"filename": file.filename, "text": extracted_text})
            else:
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
        # Extract data from the request payload.
        student_answer = request.get("student_answer")
        ideal_answer = request.get("ideal_answer")
        marking_scheme = request.get("marking_scheme")
        exam_id = request.get("exam_id")
        student_id = request.get("student_id")
        question_id = request.get("question_id")
        
        if not student_answer or (not ideal_answer and not marking_scheme):
            raise HTTPException(status_code=400, detail="Missing required parameters. Provide student_answer and at least one of ideal_answer or marking_scheme.")
        
        # Fetch the particular question from the database.
        question = db.query(Question).filter(
            Question.id == question_id,
            Question.exam_id == exam_id
        ).first()
        if not question:
            raise HTTPException(status_code=404, detail="Question not found.")
        
        # Build the prompt based on available data.
        if marking_scheme and ideal_answer:
            prompt = f"""Question: {question.text}

This is the correct marking scheme: {marking_scheme}

Ideal Answer: {ideal_answer}

Based on these, grade the following student answer: {student_answer}

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X
Reason: Some Text"""
        elif marking_scheme:
            prompt = f"""Question: {question.text}

This is the correct marking scheme: {marking_scheme}

Grade the following student answer: {student_answer}

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X
Reason: Some Text"""
        elif ideal_answer:
            prompt = f"""Question: {question.text}

Ideal Answer: {ideal_answer}

Grade the following student answer: {student_answer}

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X/{question.max_marks}, where X is the marks secured.
Reason: Some Text"""
        
        # Use the selected model (and corresponding API key) to generate content.
        response = get_model().generate_content(prompt)
        result_text = response.text
        
        # Parse the API response.
        grade = None
        reason = ""
        if "Grade:" in result_text:
            grade_line = [line for line in result_text.split('\n') if "Grade:" in line][0]
            grade_str = grade_line.split("Grade:")[1].strip()
            try:
                fraction = grade_str.split()[0]
                numerator = fraction.split('/')[0]
                grade = float(numerator)
            except ValueError:
                pass

        if "Reason:" in result_text:
            reason_parts = result_text.split("Reason:")
            if len(reason_parts) > 1:
                reason = reason_parts[1].strip()
        if grade is not None and (grade < 0 or grade > question.max_marks):
            grade = None
        
        # Update or create the corresponding QuestionResponse record.
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
