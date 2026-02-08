"""
DeviceLink - Database Models
SQLAlchemy models for device tracking and clipboard sync.
"""

from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timezone
import uuid
import enum


DATABASE_URL = "sqlite:///./devicelink.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class DeviceType(str, enum.Enum):
    MAC = "mac"
    PHONE = "phone"
    TABLET = "tablet"
    OTHER = "other"


class Device(Base):
    __tablename__ = "devices"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    device_type = Column(String, nullable=False, default=DeviceType.OTHER)
    os = Column(String, nullable=True)
    ip = Column(String, nullable=True)
    battery = Column(Integer, nullable=True)  # 0-100
    storage_total = Column(Float, nullable=True)  # GB
    storage_free = Column(Float, nullable=True)  # GB
    last_seen = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ClipboardEntry(Base):
    __tablename__ = "clipboard"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = Column(String, nullable=False)
    device_name = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    content_type = Column(String, default="text")  # text, image_url
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI - yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
