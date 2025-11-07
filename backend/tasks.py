from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession
from asyncio import get_event_loop
from backend.database import AsyncSessionLocal
from backend.models.users import User
from backend.routers.geminiAPI import process_answer_text_images_logic, grade_exam_logic
from backend.routers.examStats import add_exam_result_internal
from backend.routers.exams import update_exam_stage
import os
from dotenv import load_dotenv
load_dotenv()

# Use environment variable for broker URL, with a fallback for non-Docker local dev
broker_url = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//")
celery_app = Celery(
    "tasks",
    broker=broker_url,
    backend="rpc://"  # Result backend, adjust if using a different one like Redis
)

@celery_app.task
def process_and_grade_exam(exam_id: int, student_id: int):
    """
    Celery task to process text images and grade the exam for a specific student.
    Runs asynchronously in the background.
    """
    loop = get_event_loop()
    loop.run_until_complete(_process_and_grade(exam_id, student_id))

async def _process_and_grade(exam_id: int, student_id: int):
    async with AsyncSessionLocal() as db:
        print("\n\n\n\n\n\nProcessing and grading exam...:\t\t", exam_id, " ", student_id, end = "\n\n\n\n\n")
        await process_answer_text_images_logic(exam_id, student_id, db)
        await grade_exam_logic(exam_id, student_id, db)
        await add_exam_result_internal(exam_id, student_id, db)
        await update_exam_stage(exam_id, 7, db)