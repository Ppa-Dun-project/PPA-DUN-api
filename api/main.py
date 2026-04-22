import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from api.routers import player
from api.services.player import compute_player_value, compute_recommended_bid
from api.models.player import PlayerValueRequest, PlayerBidRequest

# Load environment variables from .env file (MYSQL_ROOT_PASSWORD, MYSQL_HOST, etc.)
load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
# Build the database URL from env variables.

DATABASE_URL = "mysql+pymysql://root:{password}@{host}:3306/{db}".format(
    password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "db"),        # "db" is the Docker Compose service name
    db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# autocommit=False: transactions must be committed explicitly.
# autoflush=False: changes are not flushed to DB until commit or explicit flush.
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="PPA-DUN API") # the app object

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Browser basically blocks frontend JavaScript from making requests to a different origin.
# Allow all origins so the dashboard frontend

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
# this limiter is used for the /demo/* endpoints later in this file

# get_real_ip() extracts the actual client IP from the X-Forwarded-For header,
# which nginx sets when proxying requests. Without this, it seems every requests are from nginx container

def get_real_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For may contain a comma-separated chain of IPs
        # (e.g., "client_ip, proxy1_ip, proxy2_ip"). The first one is the
        # original client IP.
        return forwarded_for.split(",")[0].strip()
    # Fall back to the direct connection IP if the header is absent
    return request.client.host

limiter = Limiter(key_func=get_real_ip)   # setting criteria for rate limiting (by client IP)
app.state.limiter = limiter         # slowapi reads the limiter from app.state
app.add_middleware(SlowAPIMiddleware)  # adds the rate limiting middleware to the app

# Custom handler for rate limit exceeded errors.
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait a moment and try again."},
    )

app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# ── Demo Origin Restriction ───────────────────────────────────────────────────
# demo can be used with curl. To prevent abuse, restrict the allowed origins to the official dashboard domain.

DEMO_ALLOWED_ORIGINS = {
    "https://api.ppa-dun.site",
}

# Allow an additional local origin during development if LOCAL_API_SERVER_URL
_local_url = os.getenv("LOCAL_API_SERVER_URL")
if _local_url:
    DEMO_ALLOWED_ORIGINS.add(_local_url)


def check_demo_origin(request: Request):
    """Raise 403 if the request's Origin header is not in the allowed set."""
    origin = request.headers.get("origin")
    if origin and origin not in DEMO_ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=403,
            detail="Origin not allowed for demo endpoints"
        )

# ── Auth Middleware ───────────────────────────────────────────────────────────
# This middleware runs on every incoming HTTP request before it reaches any
# route handler. It enforces API key authentication for all endpoints except:
#   - GET /health      : public health check
#   - /demo/*          : demo endpoints (auth-exempt by design)
#   - OPTIONS requests : CORS preflight requests must pass through

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    # Skip auth for exempt paths
    if (
        request.url.path == "/health"
        or request.url.path.startswith("/demo")
        or request.url.path == "/player/recalculate" # must be deleted after "FEAT-12" is done
        or request.method == "OPTIONS"
    ):
        return await call_next(request)

    # missing API key
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing API key"}
        )

   # DB connection error or other unexpected error during key verification
    try:
        db = SessionLocal()
        result = db.execute(
            text("SELECT id FROM api_keys WHERE `key` = :key"),  # :key is a parameter placeholder to prevent SQL injection
            {"key": api_key}
        ).fetchone()
        db.close()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"detail": "Service unavailable"}
        )

    # Invalid key (not found in DB)
    if result is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid API key"}
        )

    # Key is valid
    return await call_next(request)

# ── Exception Handlers ────────────────────────────────────────────────────────
# Simple handler to return a cleaner error message instead of default FastAPI 422 error response
# when required fields are missing in the request body.

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    missing_fields = [
        ".".join(str(loc) for loc in err["loc"] if loc != "body")
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": f"Missing fields: {', '.join(missing_fields)}"},
    )

# ── Routers ───────────────────────────────────────────────────────────────────
# routers from api/routers/player.py
# which defines the /player/value and /player/bid endpoints.

app.include_router(player.router)

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Public endpoint to verify the server is running. No authentication required."""
    return {"status": "ok"}

# ── Demo Endpoints ────────────────────────────────────────────────────────────
# demo can be used without an API key
# to prevent abuse, rate limit is applied and allowed origins are restricted.

@app.post("/demo/value")
@limiter.limit("10/minute")   # limit to 10 requests per minute per client IP
def demo_value(request: Request, body: PlayerValueRequest):
    """
    Demo version of POST /player/value.
    Returns player_value (0.0 ~ 100.0) without requiring an API key.
    Origin is restricted to the official dashboard domain.
    """
    check_demo_origin(request)
    return compute_player_value(body)


@app.post("/demo/bid")
@limiter.limit("10/minute")
def demo_bid(request: Request, body: PlayerBidRequest):
    """
    Demo version of POST /player/bid.
    Returns player_value + recommended_bid without requiring an API key.
    Origin is restricted to the official dashboard domain.
    """
    check_demo_origin(request)
    return compute_recommended_bid(body)