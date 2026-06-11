"""Database connection.

DATABASE_URL is read from an environment variable (set in docker-compose.yml)
and points at the postgres service defined in docker-compose.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://careplan:careplan@db:5432/careplan",
)

# engine = the database connection pool. Shared across the whole application.
engine = create_engine(DATABASE_URL)

# SessionLocal = opens a session per request, used to read and write data.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base class for all tables (models)."""


def get_db():
    """FastAPI dependency: open a db session per request and close it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
