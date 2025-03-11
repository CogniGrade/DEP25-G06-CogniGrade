import os
import secrets
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME = "Institute Classroom Portal"
    PROJECT_VERSION = "1.0.0"
    
    # Environment
    ENV = os.getenv("ENV", "development")
    DEBUG = ENV == "development"
    
    # Security settings
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
    ALGORITHM = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24))  # 24 hours
    
    # Cookie settings
    COOKIE_SECURE = ENV != "development"  # Use secure cookies in production
    COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)
    COOKIE_SAMESITE = "lax"
    
    # Database settings
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./classroom.db")
    DATABASE_POOL_SIZE = int(os.getenv("DATABASE_POOL_SIZE", 20))
    DATABASE_MAX_OVERFLOW = int(os.getenv("DATABASE_MAX_OVERFLOW", 10))
    DATABASE_POOL_TIMEOUT = int(os.getenv("DATABASE_POOL_TIMEOUT", 30))
    
    # Email settings (for future use)
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_SERVER = os.getenv("SMTP_SERVER", "")
    SMTP_PORT = os.getenv("SMTP_PORT", "")

    # Google Sign In
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")


    FRONTEND_BASE_URL = "http://127.0.0.1:8000/static"

settings = Settings()