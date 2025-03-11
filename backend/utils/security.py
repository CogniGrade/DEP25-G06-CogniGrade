from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import logging

from backend.config import settings
from backend.database import get_db
from backend.models.users import User

# Configure logging
logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

def verify_password(plain_password, hashed_password):
    """Verify a password against its hash"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Error verifying password: {str(e)}", exc_info=True)
        return False

def get_password_hash(password):
    """Hash a password"""
    try:
        return pwd_context.hash(password)
    except Exception as e:
        logger.error(f"Error hashing password: {str(e)}", exc_info=True)
        raise

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create a new access token"""
    try:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"Error creating access token: {str(e)}", exc_info=True)
        raise

def get_user(db: Session, user_id: int):
    """Get a user by ID"""
    try:
        return db.query(User).filter(User.id == user_id).first()
    except Exception as e:
        logger.error(f"Error getting user by ID: {str(e)}", exc_info=True)
        return None

def get_user_by_email(db: Session, email: str):
    """Get a user by email"""
    try:
        return db.query(User).filter(User.email == email.lower()).first()
    except Exception as e:
        logger.error(f"Error getting user by email: {str(e)}", exc_info=True)
        return None

async def get_current_user_from_cookie(request: Request, db: Session = Depends(get_db)):
    """Get the current user from the session cookie"""
    try:
        token = request.cookies.get("access_token")
        if not token:
            logger.debug("No access token found in cookies")
            return None
            
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id: str = payload.get("sub")
            if not user_id:
                logger.warning("Token payload does not contain user ID")
                return None
        except JWTError as e:
            logger.warning(f"Invalid token: {str(e)}")
            return None
        
        user = get_user(db, int(user_id))
        if not user:
            logger.warning(f"User not found for ID: {user_id}")
            return None
            
        return user
    except Exception as e:
        logger.error(f"Error in get_current_user_from_cookie: {str(e)}", exc_info=True)
        return None

async def get_current_user_required(request: Request, db: Session = Depends(get_db)):
    """Get the current user and raise an error if not authenticated"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        logger.warning("Authentication required but no valid user found")

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user