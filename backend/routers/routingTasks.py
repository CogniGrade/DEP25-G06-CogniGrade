from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from backend.database import get_db
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.tasks import process_and_grade_exam

router = APIRouter(tags=["routing-tasks"])

@router.post("/exam/{exam_id}/enqueue-processing")
async def enqueue_processing(
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    """
    Enqueue the processing and grading task for the given exam and student.
    """
    process_and_grade_exam.delay(exam_id, current_user.id)
    return {"message": "Processing and grading enqueued"}