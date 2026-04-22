from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from db.session import engine, Base
from db.models import User, APIKey, ALPlayer, NLPlayer, UnmatchedPlayer  # noqa: F401
from routers import auth, admin

load_dotenv()


# ── Lifespan ──────────────────────────────────────────────────────────────────
# Replaces the deprecated @app.on_event("startup") / ("shutdown") pattern.
# On startup: create DB tables + start the daily update scheduler.
# On shutdown: gracefully stop the scheduler.

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)

    from data.daily_update import start_scheduler
    scheduler = start_scheduler()

    yield

    # Shutdown
    if scheduler and scheduler.running:
        scheduler.shutdown()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="PPA-DUN Backend", lifespan=lifespan)

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Allow all origins so the dashboard frontend (ppa-dun.site) and local dev
# environments can call the backend without CORS errors.
# The backend is only reachable through nginx, which limits exposure
# to the public internet.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
# Register the auth router, which handles all /api/auth/* endpoints:
#   POST   /api/auth/google          — Google OAuth login, user creation
#   POST   /api/auth/api-key         — Issue a new API key for the user
#   GET    /api/auth/api-keys        — List all API keys for the user
#   DELETE /api/auth/api-key/{key}   — Delete a specific API key

app.include_router(auth.router)
app.include_router(admin.router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Public endpoint to verify the backend server is running."""
    return {"status": "ok"}