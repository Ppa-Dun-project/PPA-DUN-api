from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from db.session import Base  # Base is defined in db/session.py via declarative_base()


# ── User ──────────────────────────────────────────────────────────────────────
# Represents a registered user who authenticated via Google OAuth.
# Created automatically on first login via POST /api/auth/google.

class User(Base):
    __tablename__ = "users"

    id        = Column(Integer, primary_key=True, index=True)
    google_id = Column(String(255), unique=True, nullable=False)  # Google's stable unique user ID ("sub" field in ID token)
    email     = Column(String(255), unique=True, nullable=False)  # User's Google account email
    name      = Column(String(255), nullable=False)               # User's display name from Google profile
    created_at = Column(DateTime, default=datetime.utcnow)        # Timestamp of first login (UTC)

    # One-to-many relationship with APIKey.
    # Accessing user.api_keys returns a list of all APIKey records for this user.
    # back_populates="user" links this side to APIKey.user on the other side.
    api_keys = relationship("APIKey", back_populates="user")


# ── APIKey ────────────────────────────────────────────────────────────────────
# Represents an API key issued to a user for authenticating requests to the
# API server (api.ppa-dun.site). The key is verified by api/main.py middleware
# on every /player/* request.

class APIKey(Base):
    __tablename__ = "api_keys"

    id      = Column(Integer, primary_key=True, index=True)
    key     = Column(String(64), unique=True, nullable=False, index=True)  # 64-char hex string (secrets.token_hex(32))
    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        unique=True,   # unique=True enforces one-key-per-user at the DB level,
                       # in addition to the application-level check in auth.py
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    # Many-to-one relationship back to User.
    # Accessing api_key.user returns the User object that owns this key.
    user = relationship("User", back_populates="api_keys")