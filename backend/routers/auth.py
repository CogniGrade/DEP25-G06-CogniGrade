from datetime import timedelta, datetime, timezone
import secrets
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status, Response, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from jose import JWTError, jwt
import smtplib
from email.message import EmailMessage

# Existing imports
from backend.config import settings
from backend.database import get_db
from backend.models.users import User
from backend.utils.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user_from_cookie,
)
from backend.utils.validators import validate_email, validate_password

# NEW: Import Authlib’s OAuth tools
from authlib.integrations.starlette_client import OAuth, OAuthError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

# Set up the OAuth instance and register Google OAuth.
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,  # add in your config
    client_secret=settings.GOOGLE_CLIENT_SECRET,  # add in your config
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

@router.post("/login")
async def login(data: dict, response: Response, db: Session = Depends(get_db)):
    try:
        print("HEYYYYY")
        email = data.get("email")
        password = data.get("password")
        remember = data.get("remember", False)
        
        if not email or not password:
            return JSONResponse(status_code=400, content={"success": False, "error": "Please fill in all fields"})
        
        email = email.lower().strip()
        user = db.query(User).filter(User.email == email).first()
        if not user or not verify_password(password, user.hashed_password):
            logger.warning(f"Login attempt failed for email {email}")
            return JSONResponse(status_code=401, content={"success": False, "error": "Incorrect email or password"})
        
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        
        access_token_expires = timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 7 if remember else settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
        access_token = create_access_token(
            data={"sub": str(user.id)},
            expires_delta=access_token_expires
        )
        # Create a JSONResponse, then set the cookie on that response:
        resp = JSONResponse({"success": True, "message": "Login successful", "redirect": "/static/dashboard.htm"})
        resp.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=60*60*24*7 if remember else settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path="/",
            secure=settings.COOKIE_SECURE,
            domain=settings.COOKIE_DOMAIN,
            samesite=settings.COOKIE_SAMESITE
        )
        logger.info(f"User {user.email} logged in successfully")
        return resp
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": "An unexpected error occurred"})

@router.post("/signup")
async def signup(data: dict, response: Response, db: Session = Depends(get_db)):
    print("HEYYYYYYYYYY")
    try:
        full_name = data.get("full_name")
        email = data.get("email")
        password = data.get("password")
        confirm_password = data.get("confirm_password")
        is_professor = data.get("is_professor", False)
        
        if not all([full_name, email, password, confirm_password]):
            return JSONResponse(status_code=400, content={"success": False, "error": "Please fill in all fields"})
        
        email = email.lower().strip()
        full_name = full_name.strip()
        
        if not validate_email(email):
            return JSONResponse(status_code=400, content={"success": False, "error": "Invalid email format"})
        
        print(password, confirm_password)
        if password != confirm_password:
            return JSONResponse(status_code=400, content={"success": False, "error": "Passwords do not match"})
        
        is_valid, error_msg = validate_password(password)
        print(error_msg)
        if not is_valid:
            return JSONResponse(status_code=400, content={"success": False, "error": error_msg})
        
        if db.query(User).filter(User.email == email).first():
            return JSONResponse(status_code=400, content={"success": False, "error": "Email already registered"})
        
        hashed_password = get_password_hash(password)
        user = User(
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            is_professor=is_professor
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        access_token = create_access_token(
            data={"sub": str(user.id)},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        resp = JSONResponse({"success": True, "message": "Signup successful", "redirect": "/static/dashboard.htm"})
        resp.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path="/",
            secure=settings.COOKIE_SECURE,
            domain=settings.COOKIE_DOMAIN,
            samesite=settings.COOKIE_SAMESITE
        )
        logger.info(f"New user registered successfully: {user.email}")
        return resp
        
    except Exception as e:
        logger.error(f"Signup error: {str(e)}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": "An unexpected error occurred"})

@router.get("/check-session")
async def check_session(request: Request, db: Session = Depends(get_db)):
    """Check if the current session is valid"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired")
    return {"status": "ok"}

@router.get("/logout")
async def logout(request: Request):
    """Handle user logout by deleting the access token cookie and clearing session"""
    logger.info("Processing logout request")
    response = RedirectResponse(url="/static/login.htm", status_code=303)
    response.delete_cookie(key="access_token", path="/")
    response.set_cookie(
        key="access_token",
        value="",
        max_age=0,
        path="/",
        expires="Thu, 01 Jan 1970 00:00:00 GMT"
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ========= Google OAuth Endpoints =========

@router.get("/login/google")
async def login_google(request: Request):
    """
    Initiate Google OAuth login.
    Both the login.htm and signup.htm buttons call this endpoint.
    """
    redirect_uri = request.url_for("auth_via_google")
    print("Redirect URI:", redirect_uri)
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/auth/google", name="auth_via_google")
async def auth_via_google(request: Request, db: Session = Depends(get_db)):
    """
    Handle the callback from Google. If the user is logging in with Google, fetch their profile.
    If a user with the given email does not exist, create one (using a dummy password).
    Then create an access token, set the cookie, and redirect to the dashboard.
    """
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token['userinfo']
        email = user_info.get("email")
        full_name = user_info.get("name") or "Google User"
        
        # Look up the user by email. If not found, create a new user.
        user = db.query(User).filter(User.email == email).first()
        if not user:
            dummy_password = secrets.token_hex(16)
            hashed_dummy = get_password_hash(dummy_password)
            user = User(email=email, full_name=full_name, hashed_password=hashed_dummy)
            db.add(user)
            db.commit()
            db.refresh(user)
        
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user.id)},
            expires_delta=access_token_expires
        )
        response = RedirectResponse(url="/static/dashboard.htm", status_code=303)
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path="/",
            secure=settings.COOKIE_SECURE,
            domain=settings.COOKIE_DOMAIN,
            samesite=settings.COOKIE_SAMESITE
        )
        return response
    except Exception as e:
        logger.error(f"Google OAuth error: {str(e)}", exc_info=True)
        return JSONResponse(status_code=400, content={"success": False, "error": "Google OAuth failed"})


def send_reset_email(email: str, reset_link: str):
    """Utility function to send a password reset email."""
    msg = EmailMessage()
    msg.set_content(
        f"Hi,\n\nPlease click the following link to reset your password:\n{reset_link}\n\n"
        "If you did not request this, please ignore this email."
    )
    msg["Subject"] = "Password Reset Request"
    msg["From"] = settings.SMTP_USERNAME
    msg["To"] = email
    
    print("Reached Checkpoint")
    with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("Email sent successfully")

@router.post("/forgot-password")
async def forgot_password(data: dict, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Accepts an email address. If the email is registered, sends a reset link via email.
    If not, returns an error: "Email Not Registered".
    """
    try:
        email = data.get("email")
        if not email:
            return JSONResponse(status_code=400, content={"success": False, "error": "Email is required"})
        
        email = email.lower().strip()
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return JSONResponse(status_code=400, content={"success": False, "error": "Email Not Registered"})
        
        # Generate a reset token that expires in 15 minutes, with an "action" claim.
        reset_token = create_access_token(
            data={"sub": email, "action": "reset"},
            expires_delta=timedelta(minutes=15)
        )
        # Construct the reset link pointing to the frontend reset-password page.
        reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password.htm?token={reset_token}"
        
        print("Reset Link created")

        # Send the reset email asynchronously in the background.
        background_tasks.add_task(send_reset_email, email, reset_link)
        
        return JSONResponse(content={"success": True, "message": "Reset code sent to your email."})
    except Exception as e:
        # Log the error in your logs for debugging if needed.
        return JSONResponse(status_code=500, content={"success": False, "error": "An error occurred while processing your request."})

@router.post("/reset-password")
async def reset_password(data: dict, db: Session = Depends(get_db)):
    """
    Resets the user’s password.
    Expects a JSON body with:
      - token: the reset token (JWT) with payload {"sub": email, "action": "reset"}
      - new_password: the new password
      - confirm_password: confirmation of the new password
    If the email extracted from the token is not registered, returns "Email Not Registered".
    """
    token = data.get("token")
    new_password = data.get("new_password")
    confirm_password = data.get("confirm_password")
    
    if not token or not new_password or not confirm_password:
        return JSONResponse(status_code=400, content={"success": False, "error": "Missing required fields"})
    
    if new_password != confirm_password:
        return JSONResponse(status_code=400, content={"success": False, "error": "Passwords do not match"})
    
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("action") != "reset":
            return JSONResponse(status_code=400, content={"success": False, "error": "Invalid token action"})
    except JWTError:
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid or expired token"})
    
    email = payload.get("sub")
    if not email:
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid token payload"})
    
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user:
        return JSONResponse(status_code=400, content={"success": False, "error": "Email Not Registered"})
    
    # Update the user's password
    hashed_password = get_password_hash(new_password)
    user.hashed_password = hashed_password
    db.commit()
    
    return JSONResponse(content={"success": True, "message": "Password reset successful"})
