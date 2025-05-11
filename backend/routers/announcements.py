from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession     # ASYNC
from sqlalchemy.future import select

from sqlalchemy import desc
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import TIMESTAMP
import logging

from backend.database import get_db
from backend.models.tables import Announcement, Classroom, Enrollment, Query
from backend.models.users import User
from backend.utils.security import get_current_user_required
from backend.models.notifications import Notification, NotificationType
    
router = APIRouter(tags=["announcements"])
logger = logging.getLogger(__name__)

@router.get("/classes/{class_id}/announcements")
async def get_class_announcements(
    class_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Verify class exists and user has access
    result = await db.execute(select(Classroom).where(Classroom.id == class_id))
    classroom = result.scalars().first()    
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Check if user is enrolled or is the owner
    if classroom.owner_id != current_user.id:
        result = await db.execute(select(Enrollment).where(
            Enrollment.classroom_id == class_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ))
        enrollment = result.scalars().first()
        if not enrollment:
            raise HTTPException(status_code=403, detail="You are not enrolled in this class")
    
    # Get announcements for the class
    announcements_query = db.query(Announcement).filter(
        Announcement.classroom_id == class_id
    ).order_by(desc(Announcement.created_at)).all()
    
    # Format announcements
    announcements_list = []
    for announcement in announcements_query:
        # Get author name
        author = db.query(User).filter(User.id == announcement.author_id).first()
        author_name = author.full_name if author else "Unknown"
        
        # Check if user can edit (author or class owner)
        can_edit = announcement.author_id == current_user.id or classroom.owner_id == current_user.id
        
        announcements_list.append({
            "id": announcement.id,
            "title": announcement.title,
            "content": announcement.content,
            "created_at": announcement.created_at.isoformat() if announcement.created_at else None,
            "author_id": announcement.author_id,
            "author_name": author_name,
            "can_edit": can_edit
        })
    
    return JSONResponse({"success": True, "announcements": announcements_list})

@router.post("/classes/{class_id}/announcements")
async def create_announcement(
    class_id: int,
    title: str = Form(...),
    content: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Verify class exists and user has access
    result = await db.execute(select(Classroom).where(Classroom.id == class_id))
    classroom = result.scalars().first()    
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Check if user is enrolled or is the owner
    if classroom.owner_id != current_user.id:
        result = await db.execute(select(Enrollment).where(
            Enrollment.classroom_id == class_id,
            Enrollment.student_id == current_user.id,
            Enrollment.status == "accepted"
        ))
        enrollment = result.scalars().first()    
        if not enrollment:
            raise HTTPException(status_code=403, detail="You are not enrolled in this class")
    
    # Create announcement
    new_announcement = Announcement(
        classroom_id=class_id,
        author_id=current_user.id,
        title=title,
        content=content,
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_announcement)
    await db.commit()
    await db.refresh(new_announcement)
    
    # Create notifications for all students in the class
    
    # Get all student enrollments for this class
    result = await db.execute(select(Enrollment).where(
        Enrollment.classroom_id == class_id,
        Enrollment.status == "accepted",
        Enrollment.role == "student"
    ))
    enrollments = result.scalars().all()
    
    # Create a notification for each enrolled student
    for enrollment in enrollments:
        if enrollment.student_id != current_user.id:  # Don't notify the creator
            notification = Notification(
                type=NotificationType.ANNOUNCEMENT,
                title=title,
                message=content,
                sender_id=current_user.id,
                recipient_id=enrollment.student_id,
                classroom_id=class_id,
                announcement_id=new_announcement.id,
                action_url=f"/courses.htm?class_id={class_id}",
                created_at=datetime.now(timezone.utc)
            )
            db.add(notification)
    await db.commit()
    
    logger.info(f"Announcement created for class ID {class_id} by user {current_user.email}")
    
    return JSONResponse({
        "success": True,
        "announcement": {
            "id": new_announcement.id,
            "title": new_announcement.title,
            "content": new_announcement.content,
            "created_at": new_announcement.created_at.isoformat()
        }
    })

@router.put("/classes/{class_id}/announcements/{announcement_id}")
async def update_announcement(
    class_id: int,
    announcement_id: int,
    content: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Verify class exists
    result = await db.execute(select(Classroom).where(Classroom.id == class_id))
    classroom = result.scalars().first()    
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Get announcement    
    result = await db.execute(select(Announcement).where(
        Announcement.id == announcement_id,
        Announcement.classroom_id == class_id
    ))
    announcement = result.scalars().first()    
    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    
    # Check permissions (only author or class owner can edit)
    if announcement.author_id != current_user.id and classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You don't have permission to edit this announcement")
    
    # Update announcement
    announcement.content = content
    await db.commit()
    
    return JSONResponse({
        "success": True,
        "message": "Announcement updated"
    })

@router.delete("/classes/{class_id}/announcements/{announcement_id}")
async def delete_announcement(
    class_id: int,
    announcement_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_required)
):
    # Verify class exists
    result = await db.execute(select(Classroom).where(Classroom.id == class_id))
    classroom = result.scalars().first()    
    if not classroom:
        raise HTTPException(status_code=404, detail="Class not found")
    
    # Get announcement
    result = await db.execute(select(Announcement).where(
        Announcement.id == announcement_id,
        Announcement.classroom_id == class_id
    ))
    announcement = result.scalars().first()  
    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    
    # Check permissions (only author or class owner can delete)
    if announcement.author_id != current_user.id and classroom.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="You don't have permission to delete this announcement")
    
    # Get all queries related to this announcement
    queries = db.query(Query).filter(
        Query.related_announcement_id == announcement_id
    ).all()
    
    query_count = len(queries)
    
    try:
        # Explicitly delete all related queries first
        for query in queries:
            db.delete(query)
        
        # Delete the announcement
        db.delete(announcement)
        await db.commit()
        
        return JSONResponse({
            "success": True,
            "message": "Announcement deleted",
            "deleted_queries_count": query_count
        })
    except Exception as e:
        db.rollback()
        logging.error(f"Error deleting announcement: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting announcement: {str(e)}")
