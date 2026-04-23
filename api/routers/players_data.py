import os
import unicodedata
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

DATABASE_URL = "mysql+pymysql://root:{password}@{host}:3306/{db}".format(
    password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "db"),
    db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
)
engine       = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# ── Column whitelist ──────────────────────────────────────────────────────────
# Only columns in this set may be requested via the columns query param.
# This prevents SQL injection through column name manipulation and limits
# exposure of internal DB fields (e.g. player_id, first_name, team_id).

ALLOWED_COLUMNS = {
    "name", "position", "team",
    "ab", "r", "h", "single", "double", "triple",
    "hr", "rbi", "bb", "k", "sb", "cs", "avg", "obp", "slg",
    "injury_status", "depth_order", "player_value",
}

# Returned when the columns param is omitted
DEFAULT_COLUMNS = ["name", "position", "team", "player_value"]

# All queryable columns returned by GET /players/{player_name}
FULL_COLUMNS = [
    "name", "position", "team",
    "ab", "r", "h", "single", "double", "triple",
    "hr", "rbi", "bb", "k", "sb", "cs", "avg", "obp", "slg",
    "injury_status", "depth_order", "player_value",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """
    Normalize a player name for DB matching.
    Mirrors the logic in backend/data/utils.py normalize_name().
    Defined here to keep api/ self-contained — no cross-service imports.

    Steps:
      1. Remove periods (C.J. -> CJ)
      2. Strip diacritics via NFD decomposition (Acuna -> Acuna)
      3. Lowercase and strip whitespace
    """
    name = name.replace(".", "")
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _row_to_dict(row, columns: list[str]) -> dict:
    """Convert a SQLAlchemy Row to a dict using the given column names as keys."""
    return {col: getattr(row, col, None) for col in columns}


# ── GET /players ──────────────────────────────────────────────────────────────

@router.get("/players")
def get_players(
    league:  str        = Query(...,  description="AL or NL (required)"),
    columns: str | None = Query(None, description="Comma-separated column names to include"),
):
    """
    GET /players?league=AL
    GET /players?league=AL&columns=hr,rbi,avg,player_value

    Returns all players in the specified league.
    - league is required. Returns 400 if missing or not AL/NL.
    - columns is optional. Returns 400 if any column is not in ALLOWED_COLUMNS.
    - If columns is omitted, returns name, position, team, player_value only.
    - name is always included in the response regardless of columns param.
    - Requires a valid X-API-Key header (enforced by middleware in api/main.py).
    """
    # Validate league
    league = league.upper()
    if league not in ("AL", "NL"):
        raise HTTPException(
            status_code=400,
            detail="league must be AL or NL",
        )

    # Resolve and validate requested columns
    if columns:
        requested = [c.strip().lower() for c in columns.split(",") if c.strip()]
        invalid   = [c for c in requested if c not in ALLOWED_COLUMNS]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid column(s): {', '.join(invalid)}. "
                    f"Allowed columns: {', '.join(sorted(ALLOWED_COLUMNS))}"
                ),
            )
        # Ensure name is always first, deduplicate while preserving order
        select_cols = list(dict.fromkeys(["name"] + requested))
    else:
        select_cols = DEFAULT_COLUMNS

    table      = "players_al" if league == "AL" else "players_nl"
    col_clause = ", ".join(f"`{c}`" for c in select_cols)

    db = SessionLocal()
    try:
        rows = db.execute(text(f"SELECT {col_clause} FROM {table}")).fetchall()
    except Exception as e:
        raise HTTPException(status_code=503, detail="Database unavailable")
    finally:
        db.close()

    return {
        "league":  league,
        "count":   len(rows),
        "players": [_row_to_dict(row, select_cols) for row in rows],
    }


# ── GET /players/{player_name} ────────────────────────────────────────────────

@router.get("/players/{player_name}")
def get_player(player_name: str):
    """
    GET /players/{player_name}

    Returns the full record for a single player (all columns in FULL_COLUMNS).
    - Searches players_al first, then players_nl as fallback.
    - Name matching uses normalize_name() on both sides to handle
      punctuation and diacritic differences (e.g. C.J. -> CJ, Acuna -> Acuna).
    - Returns 404 if the player is not found in either table.
    - Spaces in names must be URL-encoded: /players/Juan%20Soto
    - Requires a valid X-API-Key header (enforced by middleware in api/main.py).
    """
    norm       = _normalize_name(player_name)
    col_clause = ", ".join(f"`{c}`" for c in FULL_COLUMNS)

    db = SessionLocal()
    try:
        for table in ("players_al", "players_nl"):
            row = db.execute(
                text(f"""
                    SELECT {col_clause}
                    FROM {table}
                    WHERE LOWER(REPLACE(REPLACE(name, '.', ''), '\\'', '')) = :norm
                    LIMIT 1
                """),
                {"norm": norm},
            ).fetchone()

            if row:
                return {
                    "league": "AL" if table == "players_al" else "NL",
                    "player": _row_to_dict(row, FULL_COLUMNS),
                }
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")
    finally:
        db.close()

    raise HTTPException(
        status_code=404,
        detail=f"Player '{player_name}' not found",
    )