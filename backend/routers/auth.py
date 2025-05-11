from datetime import timedelta, datetime, timezone
import secrets
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status, Response, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from jose import JWTError, jwt
import smtplib
from email.message import EmailMessage

# Existing imports
from backend.config import settings
from backend.database import get_db      # ← changed
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
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


@router.post("/login")
async def login(
    data: dict,
    response: Response,
    db: AsyncSession = Depends(get_db),      # ← changed
):
    email = (data.get("email") or "").lower().strip()
    password = data.get("password")
    remember = data.get("remember", False)

    if not email or not password:
        return JSONResponse(status_code=400, content={"success": False, "error": "Please fill in all fields"})

    # 1) build and run select
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if not user or not verify_password(password, user.hashed_password):
        logger.warning(f"Login attempt failed for email {email}")
        return JSONResponse(status_code=401, content={"success": False, "error": "Incorrect email or password"})

    user.last_login = datetime.now(timezone.utc)
    await db.commit()

    access_token_expires = timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 7 if remember else settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires
    )

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


@router.post("/signup")
async def signup(
    data: dict,
    response: Response,
    db: AsyncSession = Depends(get_db),      # ← changed
):
    full_name = data.get("full_name", "").strip()
    email = (data.get("email") or "").lower().strip()
    password = data.get("password")
    confirm_password = data.get("confirm_password")
    is_professor = data.get("is_professor", False)

    if not all([full_name, email, password, confirm_password]):
        return JSONResponse(status_code=400, content={"success": False, "error": "Please fill in all fields"})

    if not validate_email(email):
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid email format"})

    if password != confirm_password:
        return JSONResponse(status_code=400, content={"success": False, "error": "Passwords do not match"})

    valid, err = validate_password(password)
    if not valid:
        return JSONResponse(status_code=400, content={"success": False, "error": err})

    # check for existing user
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    if result.scalars().first():
        return JSONResponse(status_code=400, content={"success": False, "error": "Email already registered"})

    # create
    hashed_password = get_password_hash(password)
    user = User(
        email=email,
        hashed_password=hashed_password,
        full_name=full_name,
        is_professor=is_professor
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

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


@router.get("/check-session")
async def check_session(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired")
    return {"status": "ok"}


@router.get("/logout")
async def logout(request: Request):
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
    response.headers.update({
        "Cache-Control": "no-cache, no-store, must-revalidate, private",
        "Pragma": "no-cache",
        "Expires": "0"
    })
    return response


# ========= Google OAuth Endpoints =========

@router.get("/login/google")
async def login_google(request: Request):
    redirect_uri = request.url_for("auth_via_google")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google", name="auth_via_google")
async def auth_via_google(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token["userinfo"]
        email = user_info["email"]
        full_name = user_info.get("name", "Google User")

        # lookup or create
        stmt = select(User).where(User.email == email)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            dummy_password = secrets.token_hex(16)
            user = User(
                email=email,
                full_name=full_name,
                hashed_password=get_password_hash(dummy_password)
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        access_token = create_access_token(
            data={"sub": str(user.id)},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        resp = RedirectResponse(url="/static/dashboard.htm", status_code=303)
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
        return resp

    except OAuthError as e:
        logger.error(f"Google OAuth error: {e.error}", exc_info=True)
        return JSONResponse(status_code=400, content={"success": False, "error": "Google OAuth failed"})


def send_reset_email(email: str, reset_link: str):
    msg = EmailMessage()
    msg.set_content(
        f"Hi,\n\nPlease click the following link to reset your password:\n{reset_link}\n\n"
        "If you did not request this, please ignore this email."
    )
    msg["Subject"] = "Password Reset Request"
    msg["From"] = settings.SMTP_USERNAME
    msg["To"] = email

    with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()


@router.post("/forgot-password")
async def forgot_password(
    data: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = (data.get("email") or "").lower().strip()
    if not email:
        return JSONResponse(status_code=400, content={"success": False, "error": "Email is required"})

    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        return JSONResponse(status_code=400, content={"success": False, "error": "Email Not Registered"})

    reset_token = create_access_token(
        data={"sub": email, "action": "reset"},
        expires_delta=timedelta(minutes=15)
    )
    reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password.htm?token={reset_token}"

    background_tasks.add_task(send_reset_email, email, reset_link)
    return JSONResponse(content={"success": True, "message": "Reset code sent to your email."})


@router.post("/reset-password")
async def reset_password(data: dict, db: AsyncSession = Depends(get_db)):
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
            raise JWTError("Invalid action")
    except JWTError:
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid or expired token"})

    email = payload.get("sub", "").lower()
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalars().first()
    if not user:
        return JSONResponse(status_code=400, content={"success": False, "error": "Email Not Registered"})

    user.hashed_password = get_password_hash(new_password)
    await db.commit()
    return JSONResponse(content={"success": True, "message": "Password reset successful"})
