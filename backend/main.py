from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
import os
import logging

from backend.database import engine, get_db, Base
from backend.routers import auth, classes, enrollments, notifications, announcements, exams, geminiAPI, studentBackend
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
app.include_router(studentBackend.router)  # <-- Added new student endpoints

@app.get("/")
async def root(request: Request):
    return JSONResponse({"message": "Welcome to the Institute Classroom Portal API. Please login."})

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
