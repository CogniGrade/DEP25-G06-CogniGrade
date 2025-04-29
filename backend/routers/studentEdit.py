import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from backend.utils.security import get_current_user_required
from backend.models.tables import QuestionResponse, Question
from backend.database import get_db
from backend.models.users import User

import os
import uuid
import base64
import json

# Constants for upload directories. Adjust these paths as needed.
UPLOAD_DIRECTORY_TEXT_ANS = "uploads/text_images/ans"
UPLOAD_DIRECTORY_TABLE_ANS = "uploads/table_images/ans"
UPLOAD_DIRECTORY_DIAGRAM_ANS = "uploads/diagram_images/ans"

UPLOAD_DIRECTORY_TEXT_MS = "uploads/text_images/ms"
UPLOAD_DIRECTORY_TABLE_MS = "uploads/table_images/ms"
UPLOAD_DIRECTORY_DIAGRAM_MS = "uploads/diagram_images/ms"


# Ensure that the directories exist.
for directory in [UPLOAD_DIRECTORY_TEXT_ANS, UPLOAD_DIRECTORY_TABLE_ANS, UPLOAD_DIRECTORY_DIAGRAM_ANS, UPLOAD_DIRECTORY_TEXT_MS, UPLOAD_DIRECTORY_TABLE_MS, UPLOAD_DIRECTORY_DIAGRAM_MS]:
    os.makedirs(directory, exist_ok=True)
    
router = APIRouter()

# Pydantic model for the payload. (Optionally add exam_id if needed.)
class QuestionResponsePayload(BaseModel):
    question_id: int
    question_number: int
    original_index: int
    text_images: Optional[List[str]] = []      # Expect concatenated text image (or list with one image) as a data URI.
    table_images: Optional[List[str]] = []       # List of table images as data URIs.
    diagram_images: Optional[List[str]] = []     # List of diagram images as data URIs.

def save_image_file(data_uri: str, upload_dir: str, exam_id: str, question_num: str) -> str:
    """
    Convert a data URI (e.g., data:image/png;base64,...) to a binary file,
    save it under the specified directory with a unique filename that includes
    exam number and question number, and return the file path.
    """
    # Data URI format: "data:image/png;base64,...."
    try:
        header, encoded = data_uri.split(",", 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image format in data URI.")
    
    # Determine file extension from header (optional)
    if "image/png" in header:
        ext = "png"
    elif "image/jpeg" in header:
        ext = "jpg"
    else:
        ext = "png"  # default

    # Decode base64 string.
    try:
        image_data = base64.b64decode(encoded)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 data in image.")
    
    file_id = str(uuid.uuid4())
    # Use question_num as a string; if not available from payload, you might query the question.
    file_name = f"{file_id}_{exam_id}_{question_num}.{ext}"
    file_location = os.path.join(upload_dir, file_name)
    
    with open(file_location, "wb") as f:
        f.write(image_data)
    return file_location

@router.post("/exam/{exam_id}/question_response/{document_type}")
async def submit_question_response(
    exam_id: int,
    document_type: str,
    payload: QuestionResponsePayload,
    db: Session = Depends(get_db),                          # Import your get_db dependency
    current_user: User = Depends(get_current_user_required)  # Import your get_current_user_required dependency
):
    document_type = document_type.lower()
    # Optionally retrieve the question from DB to get question number.
    question = db.query(Question).filter(Question.id == payload.question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    question_num = str(question.question_number)

    # Process each list of images:
    def process_images(image_list: List[str], upload_dir: str) -> List[str]:
        file_paths = []
        for data_uri in image_list:
            path = save_image_file(data_uri, upload_dir, exam_id, question_num)
            file_paths.append(path)
        return file_paths

    if document_type == "answer_script":
        print("Question Number: ", question.question_number, "Text Images: ", len(payload.text_images))
        processed_text_images = process_images(payload.text_images, UPLOAD_DIRECTORY_TEXT_ANS)
        processed_table_images = process_images(payload.table_images, UPLOAD_DIRECTORY_TABLE_ANS)
        processed_diagram_images = process_images(payload.diagram_images, UPLOAD_DIRECTORY_DIAGRAM_ANS)
        # Look for an existing QuestionResponse for the student & question.
        qr = db.query(QuestionResponse).filter(
            QuestionResponse.question_id == payload.question_id,
            QuestionResponse.student_id == current_user.id
        ).first()

        if not qr:
            qr = QuestionResponse(question_id=payload.question_id, student_id=current_user.id)
            db.add(qr)

        # Now store the processed file paths as JSON strings.
        qr.ans_text_images = json.dumps(processed_text_images)                    ### LATER CHANGE TO ANSWER_TEXT_IMAGES
        qr.ans_table_images = json.dumps(processed_table_images)                   ### LATER CHANGE TO ANSWER_TABLE_IMAGES
        qr.ans_diagram_images = json.dumps(processed_diagram_images)                ### LATER CHANGE TO ANSWER_DIAGRAM_IMAGES
        db.commit()
        db.refresh(qr)
    elif document_type == "marking_scheme":
        print(len(payload.diagram_images))
        processed_text_images = process_images(payload.text_images, UPLOAD_DIRECTORY_TEXT_MS)
        processed_table_images = process_images(payload.table_images, UPLOAD_DIRECTORY_TABLE_MS)
        processed_diagram_images = process_images(payload.diagram_images, UPLOAD_DIRECTORY_DIAGRAM_MS)
        question.ms_text_images = json.dumps(processed_text_images)                    ### LATER CHANGE TO MARKING_TEXT_IMAGES
        question.ms_table_images = json.dumps(processed_table_images)                   ### LATER CHANGE TO MARKING_TABLE_IMAGES
        question.ms_diagram_images = json.dumps(processed_diagram_images)                ### LATER CHANGE TO MARKING_DIAGRAM_IMAGES
        db.commit()
        db.refresh(question)

    return JSONResponse(status_code=200, content={"message": "Images added to QuestionResponse table successfully."})
