# backend/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# note the asyncpgù in the URL
engine = create_async_engine(settings.DATABASE_URL, echo=True)

# use AsyncSession for async ORM
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
Base = declarative_base()

# async dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
