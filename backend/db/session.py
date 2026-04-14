import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ── Database URL ──────────────────────────────────────────────────────────────
# Reads DATABASE_URL from the environment first.
# If not set, falls back to a constructed pymysql URL using individual
# MYSQL_* environment variables (set in Docker Compose or .env).
# "db" in the hostname refers to the MySQL container's Docker Compose service name.

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:{password}@db:3306/{db}".format(
        password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
        db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
    ),
)

# ── Engine ────────────────────────────────────────────────────────────────────
# The engine manages the connection pool to the database.
# pool_pre_ping=True: before each connection is used, SQLAlchemy sends a
# lightweight "ping" query to verify the connection is still alive.
# This prevents errors caused by stale connections after DB restarts.

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# ── Session Factory ───────────────────────────────────────────────────────────
# SessionLocal is a factory for creating individual DB sessions.
# autocommit=False: all changes must be explicitly committed with db.commit().
# autoflush=False:  changes are not automatically synced to DB before queries.
# Each request gets its own session via the get_db() dependency below.

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# ── Base ──────────────────────────────────────────────────────────────────────
# declarative_base() returns a base class that all ORM models inherit from.
# SQLAlchemy uses this base to track all model classes and their table mappings.
# Base.metadata.create_all(engine) in backend/main.py uses this to create tables
# on startup.

Base = declarative_base()


# ── Dependency ────────────────────────────────────────────────────────────────
# get_db() is a FastAPI dependency used via Depends(get_db) in route handlers.
# It yields a DB session for the duration of a single request, then closes it
# in the finally block — ensuring the connection is always returned to the pool
# even if an exception is raised during request handling.

def get_db():
    db = SessionLocal()
    try:
        yield db       # The route handler receives this session as its db parameter
    finally:
        db.close()     # Always runs after the request completes or fails