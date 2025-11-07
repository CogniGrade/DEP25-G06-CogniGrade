import os
import uuid
import io
from typing import List, Optional, Dict
import logging
import asyncio
import threading
import json
import re
import aiofiles  # Added for async file operations

import google.generativeai as genai
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException, Form
from fastapi.responses import JSONResponse, RedirectResponse
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.database import get_db
from backend.models.files import AnswerScript, Material, FileTypeEnum
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.models.tables import QuestionResponse, Question

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

model_name = "gemini-2.0-flash"
models = []
for key in api_keys:
    genai.configure(api_key=key)
    models.append(genai.GenerativeModel(model_name))

call_count = 0
call_lock = threading.Lock()
async_call_lock = asyncio.Lock()
calls_per_key = 15

def get_model():
    """Return the appropriate model instance based on a global call counter.
    
    The models are rotated every 'calls_per_key' calls.
    Thread-safe and asyncio-safe.
    """
    global call_count
    with call_lock:
        call_count += 1
        index = ((call_count - 1) // calls_per_key) % len(models)
        print(f"Number of calls: {call_count}")
        if (call_count - 1) % calls_per_key == 0:
            print(f"Switching to model {index}")
        return models[index]

async def get_model_async():
    async with async_call_lock:
        return get_model()

UPLOAD_DIRECTORY = "./uploads"
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["gemini-api"])

def extract_leaves(labels: List[str]) -> List[str]:
    """
    Given a flat list of hierarchical labels (e.g. ["1", "1.1", "1.1.a", ...]),
    return only those labels without children in the list.
    """
    leaves = []
    for lbl in labels:
        if '.' not in lbl or not any(other != lbl and other.startswith(lbl + '.') for other in labels):
            leaves.append(lbl)
    return leaves

@router.post("/extract-text")
async def upload_and_extract(
    files: List[UploadFile] = File(...),
    exam_id: int = Form(...),
    file_type: str = Form(...),
    student_id: Optional[int] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    results = []
    try:
        file_type_enum = FileTypeEnum(file_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file type provided.")
    for file in files:
        try:
            if file_type_enum in [FileTypeEnum.question_paper, FileTypeEnum.solution_script, FileTypeEnum.marking_scheme]:
                result = await db.execute(select(Material).where(
                    Material.title == file.filename,
                    Material.related_exam_id == exam_id,
                    Material.file_type == file_type_enum
                ))
                existing = result.scalars().first()
            elif file_type_enum == FileTypeEnum.answer_sheet:
                if not student_id:
                    raise HTTPException(status_code=400, detail="student_id is required for answer_sheet.")
                result = await db.execute(select(AnswerScript).where(
                    AnswerScript.title == file.filename,
                    AnswerScript.exam_id == exam_id,
                    AnswerScript.student_id == student_id
                ))
                existing = result.scalars().first()
            else:
                existing = None

            # if existing and existing.extracted_text:
            #     results.append({"filename": file.filename, "text": existing.extracted_text})
            #     continue

            result = await db.execute(select(Question).where(Question.exam_id == exam_id))
            questions = result.scalars().all()
            if not questions:
                raise HTTPException(status_code=404, detail="Exam not found or has no questions")

            all_labels: List[str] = []
            for q in questions:
                raw = q.part_labels or ""
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        labels = [str(item).strip() for item in parsed]
                    else:
                        raise ValueError
                except (ValueError, json.JSONDecodeError):
                    labels = [item.strip() for item in raw.split(',') if item.strip()]
                all_labels.append(str(q.question_number))
                all_labels.extend(labels)

            leaf_labels = extract_leaves(all_labels)
            leaf_labels.sort(key=lambda x: [int(part) if part.isdigit() else part.lower() for part in x.split('.')])

            file_id = str(uuid.uuid4())
            file_location = os.path.join(UPLOAD_DIRECTORY, f"{file_id}_{file.filename}")
            async with aiofiles.open(file_location, "wb") as f:
                content = await file.read()
                await f.write(content)

            logger.info(f"Uploading {file.filename} to Gemini...")

            print(leaf_labels)
            sample_file = await asyncio.to_thread(genai.upload_file, path=file_location, display_name=file.filename)

            if file_type_enum == FileTypeEnum.question_paper:
                logger.info("Question Paper detected.")
#                 prompt = """
# Task: Extract the printed questions from the provided document. Also, label each extracted question with its maximum marks if mentioned.

# Instructions:
# 1. Ensure that every complete printed question present in the document is extracted.
# 2. Question Labeling:
#     - Question Labeling: Label as "Question Number - X Max Marks - Y" (visible) or "Question Number - [X] Max Marks - Y" (unclear/absent/expected), where X is the Question Number, and Y is the marks for that question. For subparts, label as "Question Number - X(subpart)". Extract all answers even with duplicate question numbers.
#     Example - "Question Number - 1(a) Max Marks - 10" if a question is labelled as 1 and has a subpart (a), and maximum marks of 10.
    
#     - Two or more questions can have the same Question Number, extract as is, do not skip any question.
#     (a) Part 1...
#     (b) Part 2..." and so on.

# 3. Max marks for any question can be inferred by looking up the marks distribution scheme in the instructions section of the question paper, or if explicitly mentioned beside the question)
# 4. After the Question Labels, the actual question text should be extracted.
# 5. If the document contains both printed questions and handwritten answers, focus solely on extracting the printed questions.
# 6. Do not extract any printed text that is not part of any question (e.g., instructions, headings, page numbers).
# """
                prompt = f"""You are given a document containing printed exam questions and a list of reference labels
{leaf_labels}
- each in the form Question.Part.Subpart. Your job is to extract every question (and its sub-parts) matching these labels, preserving all formatting, layout cues, and any mark allocations.

Extraction Task

1) Locate each question (and sub-part) in the document by matching against the given labels as closely as possible.
2) Preserve verbatim: spacing, bullets, numbering style, arrows, algebraic notation, code blocks, annotations, and any explicit mark numbers.
3) Skip any strikethrough or scribbled-out text. Ignore non-question text (headings, page numbers, general instructions).
4) If the document contains both printed questions and handwritten answers, focus solely on extracting the printed questions.
5) Give output in Markdown Format, do not use JSON formatting.

Output Structure
---
For each top-level question Q:
    Question Number - Q

If Q has parts, nest them under Q:
    Part Q.a  (Add Partial Marks - m if available)
    <exact text of sub-question a>
    Part Q.b  (Add Partial Marks - n if available)
    <exact text of sub-question b>
    ...
---
"""
            elif file_type_enum == FileTypeEnum.answer_sheet:
                prompt = """
Task: Your only job is to extract the handwritten answer sections(messy handwriting, handwritten code possible) written by a student, preserving formatting, layout, code spacing, arrows, bullet points, and linking annotations.
Do not correct student's answer. Don't change the student's answer at all. Do not answer the question yourself.
Instructions:
1. **Extract All Answers:** Ensure every complete handwritten answer is extracted. Very importantly, do not yourself correct any question.
2. Question Labeling: Label as "Question Number - X" (visible) or "Question Number - [X]" (unclear/absent/expected), where X is the Question Number. For subparts, label as "Question Number - X(subpart)". Extract all answers even with duplicate question numbers.
Example - "Question Number - 1(a)" if a question is labelled as 1 and has a subpart (a).
3. **Completion Questions:**
    - **Identify Initial Part:** For completion questions ("Complete...", "Fill in..."), find the provided initial answer. Look for three dots "...", blanks "___" or other visual cues.
    - **Concatenate:** Combine the initial part with the student's completion, preserving formatting.
4. **Differentiate Answers:** Use cues like "Answer :" etc, spatial separation, or box regions to identify answer sections.
5. **Formatting:** You may rearrange, reformat the response if the question explicitly states so. But do not correct any incorrect content in the answer. Otherwise preserve the structure as present in the student's answer.
6. **Ignore Struck-Out/Scribbled Content:** omit any word or line that is strikethrough or scribbled out from the extracted answer.
7. **Ignore Irrelevant Text:** Extract only student answers, not instructions, headings, etc.
8. Recheck the extracted answer to ensure it is the exact same as the student's answer, and that it is not missing any part of the answer. If you find any missing part, add it to the extracted answer.
9. In case of any objective question, look for ticks or circles marking the selected option, which should be then extracted.
10. Pay attention to boxes, lines, etc while formatting handwritten answer.
11. Give output in Markdown Format, do not use JSON formatting.
"""
            elif file_type_enum in [FileTypeEnum.solution_script, FileTypeEnum.marking_scheme]:
#                 prompt = """
# Task: Extract solution/marking scheme sections with associated marks, preserving formatting, layout, code spacing, arrows, bullet points, and linking annotations.

# Context: Analyze solution scripts or marking schemes (handwritten possible). Sections may include question numbers, or full question texts also, along with mark allocations. Extract all solutions/marking points and their marks, handling non-sequential links and specific format instructions.

# Instructions:

# 1. **Extract All with Marks:** Extract every complete solution/marking point. If marks are explicitly mentioned for any part, extract that mark information and associate it. Review layout to ensure all sections and their marks are captured and correctly labeled.

# 2. **Understand Question Context:** Read the question number or full question alongside each solution. Understand the context and any format instructions within the question to guide extraction.

# 3. **Labeling (Including Marks):**
#     - Label with "Question Number - X" if clear, where X is the Question Number.
#     - Label with "Question Number - [X]" if unclear or absent, where X is the Question Number.
#     - Two or more questions can have the same Question Number, extract as is, do not skip any question's answer.
# 4. **Differentiate and Associate Marks:** Use spatial cues and markers to identify distinct solution sections and their corresponding marks.

# 5. **Formatting:** Preserve original structure and formatting, including mark placements. Do not correct content.

# 6. **Ignore Struck-Out Content:** omit any strikethrough or scribbled content, including marks.

# 7. **Ignore Irrelevant Text:** Extract only solution content and associated marks directly related to questions.
# """
                prompt = f"""You are given a marking scheme/solution script from which you have to extract text.
                The structure of the marking scheme should roughly follow the following questions and parts hierarchy:
{leaf_labels}

The labels are given in the format Question.Part.Subpart, that is, the parent questions are separated from their children by points '.'. 

Task:
  Using these given labels as reference, locate and extract the solution or marking-scheme section—complete with its mark allocation, as well as possile. Preserve:
  - original formatting (spacing, bullets, arrows, code blocks, annotations)
  - layout and spatial cues
  - any explicit mark numbers

Extraction Instructions:
1. Group Question.parts under a single Question
2. If marks are mentioned, capture them and associate them with the exact text.
3. Retain any question number you see (e.g. “Question Number - X”).
4. Do not alter content—no corrections, just copy formatting verbatim.
5. Skip any strikethrough or scribbled-out text (and their marks).
6. Ignore any extraneous text not directly part of a solution or its marks.
7. Focus solely on extracting the marking-scheme/solutions. Do not extract any question text even if it is present in the document.
8. Give output in Markdown Format, do not use JSON formatting.

Output format for each extracted question:
---
For each top-level question Q:
    Question Number - Q  Max Marks - M
If Q has parts, nest them under Q:
    Part Q.a  (Add Partial Marks - m if available)
    <exact text of sub-question a>
    Part Q.b  (Add Partial Marks - n if available)
    <exact text of sub-question b>
    ...
---

"""
            model = get_model()
            response = await asyncio.to_thread(model.generate_content, (sample_file, prompt))
            extracted_text = response.text if response.text else "No text extracted."
            
            if existing:
                existing.extracted_text = extracted_text
                await db.commit()
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
                    await db.commit()
                    await db.refresh(new_material)
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
                    await db.commit()
                    await db.refresh(new_answer)
                    results.append({"filename": file.filename, "text": extracted_text})
        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {str(e)}", exc_info=True)
            results.append({"filename": file.filename, "error": str(e)})
    
    return JSONResponse({"results": results})

@router.post("/extract-question-labels")
async def extract_question_labels(
    files: List[UploadFile] = File(...),
    exam_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Extract hierarchical question labels from uploaded question papers,
    build full prefix hierarchy, and insert into Questions.part_labels.
    """
    results = []
    for file in files:
        fid = str(uuid.uuid4())
        file_path = os.path.join(UPLOAD_DIRECTORY, f"{fid}_{file.filename}")
        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        ai_file = await asyncio.to_thread(genai.upload_file, path=file_path, display_name=file.filename)

        prompt = """
Extract every question label from the paper in the form Question_Number.Part.Subpart (any depth), 
that is, parent questions are separated from their children by points '.'. There may be multiple levels of hierarchy.
For each top-level question (no dots), also extract its maximum marks as 'Max Marks - X'.
Do not attach marks to any sub-parts. Extract only numeric value of the Question Number, for example Q1 should be extracted as 1.

Example output:
1 - Max Marks - 6
1.1
1.1.a
1.2
2 - Max Marks - 5
2.1
2.1.a
2.1.b
"""
        model = get_model()
        resp = await asyncio.to_thread(model.generate_content, (ai_file, prompt))
        text = resp.text.strip() or ""

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        raw_labels = []
        marks_dict = {}

        for ln in lines:
            if "Max Marks - " in ln:
                label_part, marks_part = ln.split("Max Marks -", 1)
                label = label_part.strip().rstrip("-").strip()
                try:
                    marks = int(marks_part.strip())
                except ValueError:
                    marks = 0
                # only store marks for truly top-level (no dot in label)
                if "." not in label:
                    marks_dict[label] = marks
                raw_labels.append(label)
            else:
                raw_labels.append(ln)

        full_labels = set()
        top_questions = set()

        for lbl in raw_labels:
            parts = lbl.split(".")
            if parts and len(parts[0]) < 3:
                top_questions.add(parts[0])
                for i in range(1, len(parts)):
                    prefix = ".".join(parts[: i + 1])
                    full_labels.add(prefix)

        def sort_key(s):
            return [int(p) if p.isdigit() else p for p in s.split(".")]

        ordered = sorted(full_labels, key=sort_key)
        top_questions = sorted(top_questions, key=lambda x: int(x))

        for qnum in top_questions:
            q_labels = [lbl for lbl in ordered if lbl.split(".")[0] == qnum]
            part_labels_json = json.dumps(q_labels)
            max_marks = marks_dict.get(qnum, 0)

            q = Question(
                exam_id=exam_id,
                question_number=int(qnum),
                text="",
                ideal_answer=None,
                ideal_marking_scheme=None,
                max_marks=max_marks,
                part_labels=part_labels_json,
            )
            db.add(q)
            await db.commit()
            await db.refresh(q)

            results.append({
                "question_number": q.question_number,
                "max_marks": q.max_marks,
                "part_labels": q.part_labels
            })

    return {"results": results}

# @router.post("/extract-question-labels")
# async def extract_question_labels(
#     files: List[UploadFile] = File(...),
#     exam_id: int = Form(...),
#     db: AsyncSession = Depends(get_db),
#     current_user: User = Depends(get_current_user_required),
# ):
#     """
#     Extract hierarchical question labels from uploaded question papers,
#     build full prefix hierarchy, and insert into Questions.part_labels.
#     """
#     results = []
#     for file in files:
#         # 2. Save upload locally
#         fid = str(uuid.uuid4())
#         file_path = os.path.join(UPLOAD_DIRECTORY, f"{fid}_{file.filename}")
#         with open(file_path, "wb") as f:
#             f.write(await file.read())

#         # 3. Upload to Gemini
#         ai_file = genai.upload_file(file_path, display_name=file.filename)

#         # 4. Send extraction prompt
#         prompt = """
# Extract the question labels from the given question paper in the form Question_Number.Part.Subpart, 
# that is, the parent questions are separated from their children by points '.'. 
# There may be multiple levels of hierarchy also.
# """
#         resp = get_model().generate_content((ai_file, prompt))
#         text = resp.text.strip() or ""
#         # Expect each label on its own line; split and clean
#         raw_labels = [line.strip() for line in text.splitlines() if line.strip()]

#         # 5. Build full-hierarchy list
#         full_labels = set()
#         top_questions = set()
#         for lbl in raw_labels:
#             if lbl[-1] == '.':
#                 lbl = lbl[:-1]
#             parts = lbl.split(".")
#             if len(parts[0]) < 3:
#                 top_questions.add(parts[0])
#                 # accumulate prefixes: e.g. ["4","1","a"] → "4.1", "4.1.a"
#                 for i in range(1, len(parts)):
#                     prefix = ".".join(parts[: i + 1])
#                     full_labels.add(prefix)
#         # sort by numerical ordering
#         def sort_key(s):
#             return [int(p) if p.isdigit() else p for p in s.split(".")]
#         ordered = sorted(full_labels, key=sort_key)
#         # print(ordered)
#         # 6. Determine top-level question numbers (e.g. 4 from "4.1.a")
#         top_questions = sorted(top_questions)

#         for qnum in top_questions:
#             # 7. Filter only labels under this question
#             q_labels = [lbl for lbl in ordered if lbl.split(".")[0] == qnum]

#             part_labels_json = json.dumps(q_labels)

#             # 8. Insert Question row
#             q = Question(
#                 exam_id=exam_id,
#                 question_number=qnum,
#                 text="",               # you may wish to fill this separately
#                 ideal_answer=None,
#                 ideal_marking_scheme=None,
#                 max_marks=0,           # default; adjust as needed
#                 part_labels=part_labels_json,
#             )
#             db.add(q)
#             await db.commit()
#             await db.refresh(q)
#             results.append({
#                 "question_number": q.question_number,
#                 "part_labels": q.part_labels
#             })

#     return {"results": results}

@router.post("/grade-question")
async def grade_question(
    request: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    try:
        student_answer = request.get("student_answer")
        ideal_answer = request.get("ideal_answer")
        marking_scheme = request.get("marking_scheme")
        exam_id = request.get("exam_id")
        student_id = request.get("student_id")
        question_id = request.get("question_id")
        
        if not student_answer or (not ideal_answer and not marking_scheme):
            raise HTTPException(status_code=400, detail="Missing required parameters. Provide student_answer and at least one of ideal_answer or marking_scheme.")
        
        result = await db.execute(select(Question).where(
            Question.id == question_id,
            Question.exam_id == exam_id
        ))
        question = result.scalars().first()
        if not question:
            raise HTTPException(status_code=404, detail="Question not found.")
        
        if marking_scheme and ideal_answer:
            prompt = f"""Question: {question.text}

This is the correct marking scheme: {marking_scheme}

Ideal Answer: {ideal_answer}

Based on these, grade the following student answer: {student_answer}

If the marking scheme doesn't specify mark distribution, grade proportionally based on the level of correctness—giving higher marks for more accurate and complete answers, and lower marks for partially correct or incomplete ones. Don't be too strict, nor too lenient.

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X
Reason: Some Text"""
        elif marking_scheme:
            prompt = f"""Question: {question.text}

This is the correct marking scheme: {marking_scheme}

Grade the following student answer: {student_answer}

If the marking scheme doesn't specify mark distribution, grade proportionally based on the level of correctness—giving higher marks for more accurate and complete answers, and lower marks for partially correct or incomplete ones. Don't be too strict, nor too lenient.

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X
Reason: Some Text"""
        elif ideal_answer:
            prompt = f"""Question: {question.text}

Ideal Answer: {ideal_answer}

Grade the following student answer: {student_answer}

Grade proportionally based on the level of correctness—giving higher marks for more accurate and complete answers, and lower marks for partially correct or incomplete ones. Don't be too strict, nor too lenient.

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X/{question.max_marks}, where X is the marks secured.
Reason: Some Text"""
        
        model = get_model()
        response = await asyncio.to_thread(model.generate_content, prompt)
        result_text = response.text
        
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
        
        if question_id and student_id and exam_id and grade is not None:
            result = await db.execute(select(QuestionResponse).where(
                QuestionResponse.question_id == question_id,
                QuestionResponse.student_id == student_id
            ))
            existing_response = result.scalars().first()
            if existing_response:
                existing_response.marks_obtained = grade
                existing_response.reasoning = reason
                await db.commit()
        
        return {"grade": grade, "reasoning": reason, "raw_response": result_text}
        
    except Exception as e:
        logger.error(f"Error in grade_question: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error grading question: {str(e)}")

@router.post("/grade-question-with-diagram")
async def grade_question_with_diagram(
    request: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    print("diagram grade")
    try:
        ideal_answer = request.get("ideal_answer")
        marking_scheme = request.get("marking_scheme")
        exam_id = request.get("exam_id")
        student_id = request.get("student_id")
        question_id = request.get("question_id")
        
        result = await db.execute(select(QuestionResponse).where(
            QuestionResponse.question_id == question_id,
            QuestionResponse.student_id == student_id
        ))
        qr = result.scalars().first()
        student_answer = qr.answer_text if qr else None
        ans_table_images = json.loads(qr.ans_table_images) if (qr and qr.ans_table_images) else None
        ans_diagram_images = json.loads(qr.ans_diagram_images) if (qr and qr.ans_diagram_images) else None
        
        if (not student_answer and len(ans_table_images) == 0 and len(ans_diagram_images) == 0):
            raise HTTPException(status_code=400, detail="Missing required parameters. Provide student_answer and at least one of ideal_answer or marking_scheme.")
        
        async def upload_file(entry):
            try:
                uploaded_file = await asyncio.to_thread(
                    genai.upload_file,
                    path=entry,
                    display_name=os.path.basename(entry)
                )
                print(f"Successfully uploaded: {entry} -> {uploaded_file.name}")
                return entry, uploaded_file
            except Exception as e:
                logger.error(f"Error uploading file {entry['img_path']}: {str(e)}", exc_info=True)
                return None

        tasks = [upload_file(table) for table in ans_table_images] + [upload_file(diagram) for diagram in ans_diagram_images]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        uploaded_files = [(entry, uploaded_file) for entry, uploaded_file in results if entry is not None]
        
        result = await db.execute(select(Question).where(
            Question.id == question_id,
            Question.exam_id == exam_id
        ))
        question = result.scalars().first()
        ms_table_images = json.loads(question.ms_table_images) if (question and question.ms_table_images) else None
        ms_diagram_images = json.loads(question.ms_diagram_images) if (question and question.ms_diagram_images) else None
        
        if not question:
            print("\n\n\nOH NOOOOOOO ERROR \n\n\n")
            raise HTTPException(status_code=404, detail="Question not found.")
        
        def check_image_presence(diagram_images, table_images):
            image_present = True
            table_present = False
            diagram_present = False
            if diagram_images and table_images and (len(diagram_images) * len(table_images)) != 0:
                diagram_present = True
                table_present = True
            elif diagram_images and (len(diagram_images) != 0):
                diagram_present = True
            elif table_images and (len(table_images) != 0):
                table_present = True
            else:
                image_present = False
            return image_present, table_present, diagram_present

        ans_image_present, ans_table_present, ans_diagram_present = check_image_presence(ans_diagram_images, ans_table_images)
        ms_image_present, ms_table_present, ms_diagram_present = check_image_presence(ms_diagram_images, ms_table_images)

        if (marking_scheme or ms_image_present) and ideal_answer:
            prompt_content = [f"""Question: {question.text}

This is the correct marking scheme: {f'{marking_scheme}, with' if marking_scheme else "look at"} {f" the attached {'diagrams and tables' if ms_diagram_present and ms_table_present else 'diagrams' if ms_diagram_present else 'table' if ms_table_present else ''}" if ms_image_present else ""}"""] + [f for (_, f) in uploaded_files] + [f"""

Ideal Answer: {ideal_answer}

Grade the following student answer: {f'{student_answer}, with' if student_answer else "look at"} {f" the attached {'diagrams and tables' if ans_diagram_present and ans_table_present else 'diagrams' if ans_diagram_present else 'table' if ans_table_present else ''}" if ans_image_present else ""}"""] + [f for (_, f) in uploaded_files] + [f"""

If the marking scheme doesn't specify mark distribution, grade proportionally based on the level of correctness—giving higher marks for more accurate and complete answers, and lower marks for partially correct or incomplete ones. Don't be too strict, nor too lenient.

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X
Reason: Some Text

Make sure this output format is exactly followed, that is, the overall Grade: for the question should be exactly be in the first line of your response, and then the Reason can be from second line onwards.
"""]
        elif (marking_scheme or ms_image_present):
            prompt_content = [f"""Question: {question.text}

This is the correct marking scheme: {f'{marking_scheme}, with' if marking_scheme else "look at"} {f" the attached {'diagrams and tables' if ms_diagram_present and ms_table_present else 'diagrams' if ms_diagram_present else 'table' if ms_table_present else ''}" if ms_image_present else ""}"""] + [f for (_, f) in uploaded_files] + [f"""

Grade the following student answer: {f'{student_answer}, with' if student_answer else "look at"} {f" the attached {'diagrams and tables' if ans_diagram_present and ans_table_present else 'diagrams' if ans_diagram_present else 'table' if ans_table_present else ''}" if ans_image_present else ""}"""] + [f for (_, f) in uploaded_files] + [f"""

If the marking scheme doesn't specify mark distribution, grade proportionally based on the level of correctness—giving higher marks for more accurate and complete answers, and lower marks for partially correct or incomplete ones. Don't be too strict, nor too lenient.
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      
Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X
Reason: Some Text

Make sure this output format is exactly followed, that is, the overall Grade: for the question should be exactly be in the first line of your response, and then the Reason can be from second line onwards.
"""]
        elif ideal_answer:
            prompt_content = [f"""Question: {question.text}

Ideal Answer: {ideal_answer}

Grade the following student answer: {f'{student_answer}, with' if student_answer else "look at"} {f" the attached {'diagrams and tables' if ans_diagram_present and ans_table_present else 'diagrams' if ans_diagram_present else 'table' if ans_table_present else ''}" if ans_image_present else ""}"""] + [f for (_, f) in uploaded_files] + [f"""

Give marks proportionally based on the level of correctness—giving higher marks for more accurate and complete answers, and lower marks for partially correct or incomplete ones. Don't be too strict, nor too lenient.

Maximum Marks Possible: {question.max_marks}.
Output Format:
Grade: X/{question.max_marks}, where X is the marks secured.
Reason: Some Text

Make sure this output format is exactly followed, that is, the overall Grade: for the question should be exactly be in the first line of your response, and then the Reason can be from second line onwards.
"""]
        else:
            prompt_content = [f"""Question: {question.text}

Grade the following student answer: {f'{student_answer}, with' if student_answer else "look at"} {f" the attached {'diagrams and tables' if ans_diagram_present and ans_table_present else 'diagrams' if ans_diagram_present else 'table' if ans_table_present else ''}" if ans_image_present else ""}"""] + [f for (_, f) in uploaded_files] + [f"""

Give marks proportionally based on the level of correctness—giving higher marks for more accurate and complete answers, and lower marks for partially correct or incomplete ones. Don't be too strict, nor too lenient.
                                                                                                                                                                                                                                                                                                                                                 
Maximum Marks Possible: {question.max_marks}.

Output Format:
Grade: X/{question.max_marks}, where X is the marks secured.
Reason: Some Text

Make sure this output format is exactly followed, that is, the overall Grade: for the question should be exactly be in the first line of your response, and then the Reason can be from second line onwards.
"""]

        model = get_model()
        response = await asyncio.to_thread(model.generate_content, prompt_content)
        result_text = response.text
        
        print("Question Num: ", question.question_number, "\nAns: ", result_text)
        
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
        
        if question_id and student_id and exam_id and grade is not None:
            result = await db.execute(select(QuestionResponse).where(
                QuestionResponse.question_id == question_id,
                QuestionResponse.student_id == student_id
            ))
            existing_response = result.scalars().first()
            if existing_response:
                existing_response.marks_obtained = grade
                existing_response.reasoning = reason
                await db.commit()
        
        return {"grade": grade, "reasoning": reason, "raw_response": result_text}
        
    except Exception as e:
        logger.error(f"Error in grade_question: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error grading question: {str(e)}")

async def extract_single_answer_text(
    request: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    exam_id = request.get("exam_id")
    student_id = request.get("student_id")
    question_id = request.get("question_id")
    result = await db.execute(
        select(QuestionResponse)
        .join(Question, Question.id == QuestionResponse.question_id)
        .where(
            Question.exam_id == exam_id,
            QuestionResponse.question_id == question_id,
            QuestionResponse.student_id == student_id
        )
    )
    qr = result.scalars().one_or_none()
    if not qr:
        raise HTTPException(404, "No answer found for this question/exam/user")

    try:
        img_paths = json.loads(qr.ans_text_images) or []
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid image-list format")
    
    if not img_paths or img_paths == []:
        return JSONResponse(
            status_code=200,
            content={"message": "Text extraction skipped"}
        )
    
    uploads = []
    for path in img_paths:
        if os.path.exists(path):
            try:
                up = await asyncio.to_thread(
                    genai.upload_file, path=path, display_name=os.path.basename(path)
                )
                uploads.append(up)
            except Exception as e:
                logger.warning(f"Upload failed for {path}: {e}")
    if not uploads:
        raise HTTPException(500, "Failed to upload any image")

    prompt = """
Task: The given image shows a student's handwritten answer with its Question Number at the top ”). 
1) Read and extract that Question Number.
2) Extract the full answer text, breaking out any sub-parts.
3) Carefully consider the context of each answer to avoid extraction errors that may result from poor handwriting. For eg, simple spelling errors or subscript/superscript errors can be corrected, but do not correct calculation errors or the final answer.
4) Return:

Question Number [question_number]
Answer: [text]          ← if no sub-parts

—or—

Question Number [question_number]
Part: [part_label] - Answer: [text]
"""
    try:
        model = await get_model_async()
        response = await asyncio.to_thread(model.generate_content, [*uploads, prompt])
    except Exception as e:
        logger.error(f"LLM call failed: {e}", exc_info=True)
        raise HTTPException(502, "Text-extraction service error")

    extracted_text = response.text.strip()
    if not extracted_text:
        raise HTTPException(204, "No text extracted")

    qr.answer_text = extracted_text
    db.add(qr)
    await db.commit()

    return JSONResponse(
        status_code=200,
        content={"message": "Text extracted successfully again"}
    )

async def process_answer_text_images_logic(exam_id: int, student_id: int, db: AsyncSession):
    # print("\n\n\n\nEXTRACTING answer_text IMAGES\n\n\n\n")
    result = await db.execute(select(Question).where(Question.exam_id == exam_id))
    questions = result.scalars().all()
    question_number_map = {
        q.id: str(q.question_number)
        for q in questions
    }

    result = await db.execute(select(QuestionResponse).where(
        QuestionResponse.question_id.in_(question_number_map.keys()),
        QuestionResponse.student_id == student_id
    ))
    responses = result.scalars().all()

    # print("\n\n\n\nfetch_all_responses: ", responses, end="\n\n\n\n")
    batch_entries = []
    for qr in responses:
        try:
            image_list = json.loads(qr.ans_text_images)
            print("image_list: ", image_list, end="\n\n\n\n")
        except Exception as e:
            logger.error(f"Failed to parse image list for {qr.id}: {e}")
            continue
        for img_idx, img_path in enumerate(image_list or []):
            print("img_path: ", img_path, end="\n\n")
            if os.path.exists(img_path):
                batch_entries.append({
                    "qr_id": qr.id,
                    "question_number": question_number_map[qr.question_id],
                    "img_path": img_path
                })

    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

    # print("batch_entries: ", batch_entries, end="\n\n\n\n")
    batches = list(chunks(batch_entries, 5))

    extraction_mapping = {}

    async def process_batch(batch):
        print("\n\n\n\nProcessing batch", end="\n\n\n\n")
        async def upload(entry):
            try:
                up = await asyncio.to_thread(
                    genai.upload_file,
                    path=entry["img_path"],
                    display_name=os.path.basename(entry["img_path"])
                )
                return entry, up
            except Exception as e:
                logger.error(f"Upload failed {entry['img_path']}: {e}")
                return None

        uploads = await asyncio.gather(*(upload(e) for e in batch), return_exceptions=True)
        uploaded = [(e, f) for e, f in uploads if e and f]

        # print("Uploaded files: ", uploaded)
        if not uploaded:
            return {}

        prompt = """
Task: Each image shows a student’s handwritten answer with its Question Number at the top ”). 
1) Read extract that Question Number.
2) Extract the full answer text, breaking out any sub-parts.
3) Carefully consider the context of each answer to avoid extraction errors that may result from poor handwriting.
4) Return:

Question Number [question_number]
Answer: [text]          ← if no sub-parts

—or—

Question Number [question_number]
Part: [part_label] - Answer: [text]
...

Separate each question with a blank line.
"""

        try:
            model = await get_model_async()
            response = await asyncio.to_thread(
                model.generate_content,
                [f for (_, f) in uploaded] + [prompt]
            )
            # print("Response: ", response.text)
        except Exception as e:
            logger.error(f"LLM call failed: {e}", exc_info=True)
            return {}

        text = response.text or ""
        def parse_sections(txt):
            data = {}
            parts = re.split(r'Question Number\s*([^\r\n]+)', txt)
            for i in range(1, len(parts), 2):
                qnum = parts[i].strip()
                body = parts[i+1].strip()
                data[qnum] = body
            return data

        extracted = parse_sections(text)

        base_to_qr = {
            entry["question_number"]: entry["qr_id"]
            for entry in batch
        }

        batch_result = {}
        for qnum_str, body in extracted.items():
            m = re.match(r'(\d+)', qnum_str)
            if not m:
                continue
            base = m.group(1)
            if base in base_to_qr:
                qr_id = base_to_qr[base]
                batch_result.setdefault(qr_id, []).append(body)

        return batch_result

    # print("\n\n\n\nProcessing batches: ", batches, end="\n\n\n\n")
    results = await asyncio.gather(*(process_batch(b) for b in batches), return_exceptions=True)
    print("Results: ", results, end="\n\n\n\n")
    for r in results:
        if isinstance(r, dict):
            for qr_id, answers in r.items():
                extraction_mapping.setdefault(qr_id, []).extend(answers)

    updated = 0
    try:
        for qr in responses:
            if qr.id in extraction_mapping:
                qr.answer_text = "\n\n".join(extraction_mapping[qr.id])
                db.add(qr)
                updated += 1
        await db.commit()
    except Exception as e:
        logger.error(f"DB write failed: {e}", exc_info=True)
        raise HTTPException(500, "Failed to update answers")

    return JSONResponse(
        {"message": f"Processed {updated} question responses successfully."},
        status_code=200
    )



@router.post("/{exam_id}/process-text-images/answer_script")
async def process_answer_text_image(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    await process_answer_text_images_logic(exam_id, current_user.id, db)
    return JSONResponse({"message": "Processed successfully"})


### DUPLICATION DONE TO SOME EXTENT, IMPROVE LATER ###
@router.post("/{exam_id}/process-text-images/marking_scheme")
async def process_marking_scheme_text_image(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """
    For an exam, fetch all questions that have marking scheme images provided.
    For each Question that contains image paths (stored in the ms_text_images field), we:
      - Build a list of entries containing a unique key, associated Question id, and the image file path.
      - Group these entries into batches (e.g., 5 images per batch).
      - Upload all images in the batch concurrently.
      - Construct a composite prompt that includes each image’s unique key.
      - Send all images at once to the Gemini API and extract the marking scheme text.
      - Parse the API response (expected format: "Key: <unique_key> \n <extracted text>"). 
      - Map and store each extracted text into the corresponding Question's ideal_marking_scheme field.
    """
    # Retrieve all exam questions.
    questions = db.query(Question).filter(Question.exam_id == exam_id).all()
   
    questions_with_images = [q for q in questions if q.ms_text_images]

    batch_entries = []
    for question in questions_with_images:
        try:
            image_list = json.loads(question.ms_text_images)
        except Exception:
            continue
        if not image_list or len(image_list) == 0:
            continue
        for idx, img_path in enumerate(image_list):
            if os.path.exists(img_path):
                key = f"{question.id}_{idx}"
                batch_entries.append({
                    'key': key,
                    'question_id': question.id,
                    'img_path': img_path
                })
    
    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

    batches = list(chunks(batch_entries, 5))
    
    extraction_mapping = {}

    async def process_batch(batch):
        batch_extraction_mapping = {}

        async def upload_file(entry):
            try:
                uploaded_file = await asyncio.to_thread(
                    genai.upload_file,
                    path=entry['img_path'],
                    display_name=os.path.basename(entry['img_path'])
                )
                logger.info(f"Uploaded: {entry['img_path']} -> {uploaded_file.name}")
                return entry, uploaded_file
            except Exception as e:
                logger.error(f"Error uploading file {entry['img_path']}: {str(e)}", exc_info=True)
                return None

        upload_tasks = [upload_file(entry) for entry in batch]
        results = await asyncio.gather(*upload_tasks, return_exceptions=True)
        uploaded_files = [(entry, uploaded_file) for result in results if result is not None for entry, uploaded_file in [result]]
        
        if not uploaded_files:
            return batch_extraction_mapping

        prompt = f"""Task: You are provided with multiple images, each containing marking scheme information for an exam question.
Each image has a unique key.

Your task is to extract and clearly structure the marking scheme details from each image.
For each image, follow this format strictly:
Key: <key>
[Extracted marking scheme details here]

If the marking scheme includes multiple criteria or parts, list each one on a new line using the format:
Key: <key>
Question Number [Question Number] - [extracted text]
Part: [part number] - Details: [extracted text]
Part: [part number] - Details: [extracted text]
...

If the image contains a single cohesive marking scheme, simply output the full details under the key.

Ensure the extracted details are accurate and maintain the original logical structure.

Images provided with keys: {", ".join(entry['key'] for entry, _ in uploaded_files)}
"""

        logger.info(prompt)
        try:
            model = await get_model_async()
            response = await asyncio.to_thread(
                model.generate_content,
                ([f for (_, f) in uploaded_files] + [prompt])
            )
        except Exception as e:
            logger.error(f"Error processing batch: {str(e)}", exc_info=True)
            return batch_extraction_mapping
        
        if response.text:
            def parse_text(sample_text):
                extracted_data = {}
                # Example split assuming format "Key: <unique_key>" is used
                sections = re.split(r'Key:\s*(\w+_\d+)', sample_text)
                for i in range(1, len(sections), 2):
                    key = sections[i].strip()
                    content = sections[i+1].strip()
                    extracted_data[key] = content
                return extracted_data

            extracted_data = parse_text(response.text)
            
            for entry, _ in uploaded_files:
                key_str = entry['key']
                if key_str in extracted_data:
                    question_id = entry['question_id']
                    extracted_text = extracted_data[key_str]
                    batch_extraction_mapping.setdefault(question_id, []).append(extracted_text)
        
        return batch_extraction_mapping

    batch_tasks = [process_batch(batch) for batch in batches]
    batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

    for batch_result in batch_results:
        if isinstance(batch_result, dict):
            for question_id, texts in batch_result.items():
                extraction_mapping.setdefault(question_id, []).extend(texts)
        else:
            logger.error(f"Batch processing failed: {str(batch_result)}")

    processed_count = 0
    try:
        for question in questions_with_images:
            if question.id in extraction_mapping:
                question.ideal_marking_scheme = "\n".join(extraction_mapping[question.id])
                db.add(question)
                processed_count += 1
    except Exception as e:
        logger.error(f"Error updating Question: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error updating Question records.")

    await db.commit()

    return JSONResponse(
        status_code=200,
        content={"message": f"Processed marking scheme images for {processed_count} questions."}
    )


async def grade_exam_logic(exam_id: int, student_id: int, db: AsyncSession):
    result = await db.execute(select(Question).where(Question.exam_id == exam_id))
    questions = result.scalars().all()
    if not questions:
        raise HTTPException(status_code=404, detail="No questions found for this exam.")

    results = []
    for question in questions:
        req = {
            "ideal_answer": question.ideal_answer,
            "marking_scheme": question.ideal_marking_scheme,
            "exam_id": exam_id,
            "student_id": student_id,
            "question_id": question.id
        }
        grade_res = await grade_question_with_diagram(req, db, None)  # No current_user needed
        results.append({
            "question_number": question.question_number,
            "grade": grade_res["grade"],
            "reasoning": grade_res["reasoning"],
            "raw": grade_res["raw_response"]
        })
    return {
        "exam_id": exam_id,
        "student_id": student_id,
        "results": results
    }

@router.post("/{exam_id}/grade-exam")
async def grade_exam(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    result = await grade_exam_logic(exam_id, current_user.id, db)
    return result

