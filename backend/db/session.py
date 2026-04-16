import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ── Database URL ──────────────────────────────────────────────────────────────
# Build the database URL from env variables.

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:{password}@db:3306/{db}".format(
        password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
        db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
    ),
)

# ── Engine ────────────────────────────────────────────────────────────────────
# Create object that actually connects to the database.
# pool_pre_ping=True: checks connections before use.
# Also manages "connection pool" of reusable connections for efficiency.

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# ── Session Factory ───────────────────────────────────────────────────────────
# Session = basic unit for DB operations.
# SessionLocal call will make new session.
# autocommit=False: changes are not auto-committed
# autoflush=False: changes are not auto-flushed

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# ── Base ──────────────────────────────────────────────────────────────────────
# Parent class for all DB tables creating.

Base = declarative_base()


# ── Dependency ────────────────────────────────────────────────────────────────
# offers a session to each API call and closes the session.

def get_db():
    db = SessionLocal()
    try:
        yield db       # The route handler receives this session as its db parameter
    finally:
        db.close()     # Always runs after the request completes or fails