import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from api.routers import player
from api.services.player import compute_player_value, compute_recommended_bid
from api.models.player import PlayerValueRequest, PlayerBidRequest

load_dotenv()

# ── Database ─────────────────────────────────────────────────────────────────

DATABASE_URL = "mysql+pymysql://root:{password}@db:3306/{db}".format(
    password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
    db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="PPA-DUN API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",       # local development
        "http://dev.ppa-dun.site",     # dev
        "https://ppa-dun.site",        # prod
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Middleware ────────────────────────────────────────────────────────────────

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    # /health, /demo/*, and OPTIONS are always exempt
    if request.url.path == "/health" or request.url.path.startswith("/demo") or request.method == "OPTIONS":
        return await call_next(request)

    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing API key"}
        )

    # Look up the key in the database
    try:
        db = SessionLocal()
        result = db.execute(
            text("SELECT id FROM api_keys WHERE `key` = :key"),
            {"key": api_key}
        ).fetchone()
        db.close()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"detail": "Service unavailable"}
        )

    if result is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid API key"}
        )

    return await call_next(request)

# ── Exception Handlers ────────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    missing_fields = [".".join(str(loc) for loc in err["loc"] if loc != "body") for err in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={"detail": f"Missing fields: {', '.join(missing_fields)}"},
    )

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(player.router)

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok"}

# ── Demo Endpoints ────────────────────────────────────────────────────────────
# No API key required. Calls the same service functions as /player/value and
# /player/bid, but exposed without authentication so the key is never sent
# to the browser.

@app.post("/demo/value")
def demo_value(request: PlayerValueRequest):
    return compute_player_value(request)


@app.post("/demo/bid")
def demo_bid(request: PlayerBidRequest):
    return compute_recommended_bid(request)