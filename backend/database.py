import sqlite3
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.config import DATABASE_URL

# Cấu hình engine kết nối
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

# Cấu hình PRAGMA và Immediate Locking cho SQLite theo thiết kế Phase 1
if DATABASE_URL.startswith("sqlite"):
    @sa.event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, connection_record):
        if isinstance(dbapi_connection, sqlite3.Connection):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute("PRAGMA busy_timeout = 30000;")
            cursor.close()

    @sa.event.listens_for(engine, "begin")
    def do_sqlite_begin_immediate(conn):
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """Dependency cung cấp db session cho FastAPI endpoints"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
