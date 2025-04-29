from fastapi import Form, APIRouter, HTTPException, Depends, UploadFile, File, Body, status
from backend.database import get_db
from backend.models.users import User, UserSettings
from sqlalchemy.orm import Session
from backend.utils.security import get_current_user_required, get_password_hash, verify_password
from typing import Optional
import os
from io import BytesIO
from PIL import Image

router = APIRouter(tags=["profile-settings"])
PROFILE_PICTURE_DIR = "./profile_pictures"

# Ensure the profile pictures directory exists
os.makedirs(PROFILE_PICTURE_DIR, exist_ok=True)

@router.get("/get-info")
async def get_info(current_user: User = Depends(get_current_user_required)):
    return {
        "user": {
            "full_name": current_user.full_name,
            "is_professor": current_user.is_professor,
            "email": current_user.email,
            "bio": current_user.bio if current_user.bio else "",
            "profile_picture": current_user.profile_picture  # Return the file path if the picture exists
        }
    }

@router.post("/update-profile")
async def update_profile(
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    profile_picture: UploadFile = File(None),
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    """Updates the user's profile information and profile picture."""
    
    # Check if a profile picture is uploaded
    if profile_picture:
        file_location = f"./profile_pictures/{current_user.id}.jpg"
        try:
            # Process image to maintain quality
            img_contents = await profile_picture.read()
            img = Image.open(BytesIO(img_contents))
            
            # Convert to RGB if in RGBA mode
            if img.mode == 'RGBA':
                img = img.convert('RGB')
                
            # Save with high quality
            img.save(file_location, "JPEG", quality=95)
            current_user.profile_picture = file_location
            db.commit()
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error processing profile image: {str(e)}"
            )

    # Update the user's profile in the database
    if full_name:
        current_user.full_name = full_name
    if email:
        current_user.email = email
    if bio:
        current_user.bio = bio
    db.commit()
    
    return {"message": "Profile updated successfully"}

@router.post("/change-password")
async def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    """Changes the user's password."""
    
    # Verify current password
    if not verify_password(current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    # Verify new password matches confirmation
    if new_password != confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password and confirmation do not match"
        )
    
    # Validate password strength (can add more rules as needed)
    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long"
        )
    
    # Update password
    current_user.hashed_password = get_password_hash(new_password)
    db.commit()
    
    return {"message": "Password changed successfully"}

@router.get("/notification-settings")
async def get_notification_settings(
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    """Gets the user's notification settings."""
    
    # Get or create user settings
    user_settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    
    if not user_settings:
        user_settings = UserSettings(
            user_id=current_user.id,
            email_notifications=True,
            display_theme="light",
            language_preference="en"
        )
        db.add(user_settings)
        db.commit()
        db.refresh(user_settings)
    
    return {
        "email_notifications": user_settings.email_notifications,
        "display_theme": user_settings.display_theme,
        "language_preference": user_settings.language_preference
    }

@router.post("/notification-settings")
async def update_notification_settings(
    email_notifications: bool = Form(...),
    display_theme: str = Form(...),
    language_preference: str = Form(...),
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    """Updates the user's notification settings."""
    
    # Get or create user settings
    user_settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
    
    if not user_settings:
        user_settings = UserSettings(
            user_id=current_user.id,
            email_notifications=email_notifications,
            display_theme=display_theme,
            language_preference=language_preference
        )
        db.add(user_settings)
    else:
        user_settings.email_notifications = email_notifications
        user_settings.display_theme = display_theme
        user_settings.language_preference = language_preference
    
    db.commit()
    
    return {"message": "Notification settings updated successfully"}

@router.get("/privacy-settings")
async def get_privacy_settings(
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    """Gets the user's privacy settings."""
    
    # For now, return basic privacy settings
    # This could be extended with a dedicated PrivacySettings model in the future
    return {
        "profile_visibility": "public",  # Example field
        "activity_visibility": "followers"  # Example field
    }

@router.post("/privacy-settings")
async def update_privacy_settings(
    profile_visibility: str = Form(...),
    activity_visibility: str = Form(...),
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    """Updates the user's privacy settings."""
    
    # Placeholder for future privacy settings implementation
    # This could save to a dedicated PrivacySettings model
    
    return {"message": "Privacy settings updated successfully"}

@router.post("/delete-account")
async def delete_account(
    password: str = Form(...),
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db)
):
    """Permanently deletes the user's account."""
    
    # Verify password for security
    if not verify_password(password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is incorrect"
        )
    
    # Remove profile picture if exists
    file_name = f"{current_user.id}.jpg"
    file_path = os.path.join(PROFILE_PICTURE_DIR, file_name)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    try:
        # Handle related records manually by clearing relationships
        # First, handle answer scripts
        if current_user.answer_scripts:
            for script in current_user.answer_scripts:
                db.delete(script)
        
        # Handle question responses
        if current_user.question_responses:
            for response in current_user.question_responses:
                db.delete(response)
        
        # Clear enrollment relationships
        if current_user.enrollments:
            for enrollment in current_user.enrollments:
                db.delete(enrollment)
        
        # Clear notification relationships
        if current_user.sent_notifications:
            for notification in current_user.sent_notifications:
                notification.sender_id = None
                db.add(notification)
        
        if current_user.received_notifications:
            for notification in current_user.received_notifications:
                db.delete(notification)
        
        # Delete user settings if any
        user_settings = db.query(UserSettings).filter(UserSettings.user_id == current_user.id).first()
        if user_settings:
            db.delete(user_settings)
            
        # Now delete the user
        db.delete(current_user)
        db.commit()
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting account: {str(e)}"
        )
    
    return {"message": "Account deleted successfully"} 