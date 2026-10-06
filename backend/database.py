import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

# SQLite keeps the demo one-command runnable; set POSTGRES_URL to use PostgreSQL.
DATABASE_URL = os.getenv("POSTGRES_URL", "sqlite+aiosqlite:///./attendsure.db")
engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase): pass

async def get_db():
    async with SessionLocal() as session:
        yield session
