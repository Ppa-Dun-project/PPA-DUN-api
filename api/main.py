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
# Build the MySQL connection URL from environment variables.
# Using pymysql as the driver (mysql+pymysql://...).
# pool_pre_ping=True: SQLAlchemy tests each connection before use to detect
# stale/dropped connections and automatically reconnect.
# The cryptography package is required for pymysql to handle MySQL 8.0's
# default authentication plugin (caching_sha2_password).

DATABASE_URL = "mysql+pymysql://root:{password}@{host}:3306/{db}".format(
    password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "db"),        # "db" is the Docker Compose service name
    db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# SessionLocal is a factory for creating DB sessions.
# autocommit=False: transactions must be committed explicitly.
# autoflush=False: changes are not flushed to DB until commit or explicit flush.
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="PPA-DUN API")

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Allow all origins globally so external API consumers (licensed clients) can
# call /player/* from any domain without CORS errors.
# /demo/* origin restriction is enforced separately in check_demo_origin()
# because CORS headers alone cannot block server-side requests (e.g., curl).

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
# slowapi provides per-IP rate limiting, applied only to /demo/* endpoints.
# /player/* endpoints are protected by API key auth instead of rate limiting.
#
# get_real_ip() extracts the actual client IP from the X-Forwarded-For header,
# which nginx sets when proxying requests. Without this, all requests would
# appear to come from the nginx container IP (127.0.0.1), making per-IP
# limiting ineffective.

def get_real_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For may contain a comma-separated chain of IPs
        # (e.g., "client_ip, proxy1_ip, proxy2_ip"). The first one is the
        # original client IP.
        return forwarded_for.split(",")[0].strip()
    # Fall back to the direct connection IP if the header is absent
    return request.client.host

limiter = Limiter(key_func=get_real_ip)
app.state.limiter = limiter         # slowapi reads the limiter from app.state
app.add_middleware(SlowAPIMiddleware)

# Custom handler for rate limit exceeded errors.
# Returns 429 with a human-readable message instead of slowapi's default response.
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait a moment and try again."},
    )

app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# ── Demo Origin Restriction ───────────────────────────────────────────────────
# /demo/* endpoints require no API key, so they must be restricted to requests
# coming from the official dashboard domain only.
# This prevents unauthorized third parties from using the demo endpoints as a
# free alternative to the authenticated /player/* endpoints.
#
# Note: The Origin header is only set by browsers (CORS requests). Direct
# requests without an Origin header (e.g., curl) are not blocked here.
# Rate limiting handles abuse from such requests.

DEMO_ALLOWED_ORIGINS = {
    "https://api.ppa-dun.site",
}

# Allow an additional local origin during development if LOCAL_API_SERVER_URL
# is set in the .env file (e.g., "http://localhost:5173").
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
        or request.method == "OPTIONS"
    ):
        return await call_next(request)

    # Reject requests that are missing the X-API-Key header entirely
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing API key"}
        )

    # Look up the API key in the database.
    # If the DB is unreachable (e.g., container restart), return 503 rather than
    # crashing. This distinguishes infrastructure errors from auth failures.
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

    # If no matching key was found in the DB, reject the request
    if result is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid API key"}
        )

    # Key is valid — pass the request to the actual route handler
    return await call_next(request)

# ── Exception Handlers ────────────────────────────────────────────────────────
# Override FastAPI's default 422 Unprocessable Entity response for Pydantic
# validation errors. The default response includes verbose internal field paths;
# this handler returns a cleaner message listing only the missing field names.

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
# Register the player router, which handles POST /player/value and
# POST /player/bid. These endpoints require a valid X-API-Key header
# (enforced by the middleware above).

app.include_router(player.router)

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Public endpoint to verify the server is running. No authentication required."""
    return {"status": "ok"}

# ── Demo Endpoints ────────────────────────────────────────────────────────────
# These endpoints call the same service functions as /player/value and
# /player/bid, but are exposed without API key authentication.
# This allows the dashboard frontend to demonstrate the API in the browser
# without embedding a secret API key in client-side JavaScript.
#
# Security measures applied instead of API key auth:
#   - Origin header check (check_demo_origin): only the official dashboard domain
#   - Rate limiting (10 requests/minute per IP): prevents scripted abuse

@app.post("/demo/value")
@limiter.limit("10/minute")
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