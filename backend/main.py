from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from db.session import engine, Base
from db.models import User, APIKey, ALPlayer, NLPlayer  # noqa: F401 — imported to register models with SQLAlchemy metadata
from routers import auth

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="PPA-DUN Backend") # the server

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Browser basically blocks frontend JavaScript from making requests to a different origin.
# Allow all origins so the dashboard frontend

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup Event ─────────────────────────────────────────────────────────────
# Runs once when the server starts.
# create_all() checks the DB and creates any tables that do not yet exist,
# based on the SQLAlchemy model definitions in db/models.py.

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

# ── Routers ───────────────────────────────────────────────────────────────────
# Register the auth router, which handles all /api/auth/* endpoints:
#   POST   /api/auth/google          — Google OAuth login, user creation
#   POST   /api/auth/api-key         — Issue a new API key for the user
#   GET    /api/auth/api-keys        — List all API keys for the user
#   DELETE /api/auth/api-key/{key}   — Delete a specific API key

app.include_router(auth.router)

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Public endpoint to verify the backend server is running."""
    return {"status": "ok"}