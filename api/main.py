import os
from fastapi import FastAPI, Request, HTTPException
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

DATABASE_URL = "mysql+pymysql://root:{password}@{host}:3306/{db}".format(
    password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "db"),
    db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="PPA-DUN API")

# Allow all origins globally so external API consumers can call /player/* from
# any domain. /demo/* origin restriction is enforced per-handler below.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Demo Origin Restriction ───────────────────────────────────────────────────
# /demo/* endpoints have no API key authentication, so we restrict them to
# requests originating from the official dashboard domain only.
# Requests with no Origin header (curl, server-to-server) are not blocked here
# and are handled separately by SEC-06 (rate limiting).

DEMO_ALLOWED_ORIGINS = {
    os.getenv("LOCAL_API_SERVER_URL"),
    "https://api.ppa-dun.site/demo",
}

def check_demo_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and origin not in DEMO_ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Origin not allowed for demo endpoints"
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
# to the browser. Origin is restricted to the official dashboard domain.

@app.post("/demo/value")
def demo_value(request: Request, body: PlayerValueRequest):
    check_demo_origin(request)
    return compute_player_value(body)


@app.post("/demo/bid")
def demo_bid(request: Request, body: PlayerBidRequest):
    check_demo_origin(request)
    return compute_recommended_bid(body)