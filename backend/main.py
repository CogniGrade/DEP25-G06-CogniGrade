from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import os
import logging

from backend.database import engine, get_db, Base
from backend.routers import auth, classes, enrollments, notifications, announcements, exams, geminiAPI, studentBackend, peopleManagement, examStats, user_routes, studentEdit
from backend.config import settings

from fastapi.staticfiles import StaticFiles

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.PROJECT_NAME, version=settings.PROJECT_VERSION)

# Serve static files with HTML support (so index.html is served as the default)
app.mount("/static", StaticFiles(directory="frontend", html=True), name="static")

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Mount profile pictures directory
app.mount("/profile_pictures", StaticFiles(directory="profile_pictures"), name="profile_pictures")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

# Include routers
app.include_router(auth.router)
app.include_router(classes.router)
app.include_router(enrollments.router)
app.include_router(notifications.router)
app.include_router(announcements.router)
app.include_router(exams.router)
app.include_router(geminiAPI.router)
app.include_router(peopleManagement.router)
app.include_router(studentBackend.router)  # <-- Added new student endpoints
app.include_router(examStats.router)  # <-- Added new exam endpoints
app.include_router(studentEdit.router)  # <-- Added new studentEdit endpoints
app.include_router(user_routes.router)  # <-- Added new user endpoints
@app.get("/")
async def root(request: Request):
    return RedirectResponse(url="/static/login.htm")

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.PROJECT_VERSION}

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        logger.error(f"Error in middleware: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", reload=True)
