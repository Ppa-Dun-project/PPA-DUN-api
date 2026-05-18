from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, UniqueConstraint
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

    # One-to-one relationship with UserAllowedIP.
    # Each user may register at most one allowed IP address for API access.
    allowed_ip = relationship("UserAllowedIP", back_populates="user", uselist=False)


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


# ── UserAllowedIP ─────────────────────────────────────────────────────────────
# Stores the single allowed IP address registered per user account.
# When a user registers an IP, all API requests using their key must originate
# from that address. If no record exists, all IPs are permitted.
#
# user_id is unique — one row per user, enforced at both DB and application level.
# ip_address uses String(45) to accommodate both IPv4 and IPv6 addresses.
# updated_at is set manually on every insert or update.

class UserAllowedIP(Base):
    __tablename__ = "user_allowed_ips"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        unique=True,    # Enforces one IP registration per user at the DB level
    )
    ip_address = Column(String(45), nullable=False)   # String(45) covers IPv4 and IPv6
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Many-to-one relationship back to User.
    user = relationship("User", back_populates="allowed_ip")


# ── BatterBase ────────────────────────────────────────────────────────────────
# Abstract mixin that defines the shared schema for ALBatter and NLBatter.
#
# __abstract__ = True tells SQLAlchemy not to create a table for this class
# itself. Only its concrete subclasses (ALBatter, NLBatter) get tables.
# declared_attr is required for columns that reference relationships or need
# per-class customization; regular Column() definitions are inherited as-is.
#
# Column groups:
#   Identity (from SQL dumps)       : name, position, team
#   Identity (from statsapi.mlb.com): player_id (PK), first_name, last_name,
#                                     and other biographical fields. Populated
#                                     once at init. Never modified at runtime.
#   Stats (from SQL dumps)          : ab, r, h, single, double, triple, hr,
#                                     rbi, bb, k, sb, cs, avg, obp, slg.
#                                     single = h - double - triple - hr
#                                     (derived at import time for AL dump which
#                                     lacks a 1B column).
#   Status (daily scheduler)        : injury_status, depth_order, player_value.
#                                     All three must be updated together —
#                                     partial updates are not permitted,
#                                     enforced at the application layer.
#   Timestamp                       : updated_at. Set manually only when all
#                                     three status fields are updated together.
#                                     No SQLAlchemy onupdate — intentionally
#                                     manual so stats writes do not affect
#                                     this timestamp.
 
class BatterBase:
    __abstract__ = True
 
    # ── Identity: from SQL dumps ──────────────────────────────────────────────
    # name uses MLB API's full name (Unicode, e.g. "Julio Rodríguez").
    # team uses MLB API's abbreviation (SQL dump abbreviations are remapped
    # via TEAM_ABBR_MAP in init_players.py before insert).
    name     = Column(String(255), nullable=False, index=True)
    position = Column(String(20),  nullable=False)
    team     = Column(String(10),  nullable=False)
 
    # ── Identity: from statsapi.mlb.com (init only) ───────────────────────────
    # player_id is MLB's stable integer player ID. Used as the primary key.
    # Matched against SQL dump rows using (normalized_name, team) at init time.
    player_id      = Column(Integer, primary_key=True, index=True)
    first_name     = Column(String(100), nullable=True)
    last_name      = Column(String(100), nullable=True)
    primary_number = Column(String(10),  nullable=True)
    birth_date     = Column(String(20),  nullable=True)
    birth_city     = Column(String(100), nullable=True)
    birth_country  = Column(String(100), nullable=True)
    height         = Column(String(10),  nullable=True)
    weight         = Column(Integer,     nullable=True)
    current_age    = Column(Integer,     nullable=True)
    position_name  = Column(String(50),  nullable=True)
    team_id        = Column(Integer,     nullable=True)
    bat_side       = Column(String(5),   nullable=True)
    pitch_hand     = Column(String(5),   nullable=True)
    mlb_debut_date = Column(String(20),  nullable=True)
    active         = Column(Integer,     nullable=True)   # 1 = active, 0 = inactive
 
    # ── Season stats (init only, from SQL dumps) ──────────────────────────────
    ab     = Column(Integer, nullable=True)
    r      = Column(Integer, nullable=True)
    h      = Column(Integer, nullable=True)
    single = Column(Integer, nullable=True)   # AL: derived as h - double - triple - hr
    double = Column(Integer, nullable=True)
    triple = Column(Integer, nullable=True)
    hr     = Column(Integer, nullable=True)
    rbi    = Column(Integer, nullable=True)
    bb     = Column(Integer, nullable=True)
    k      = Column(Integer, nullable=True)
    sb     = Column(Integer, nullable=True)
    cs     = Column(Integer, nullable=True)
    avg    = Column(Float,   nullable=True)
    obp    = Column(Float,   nullable=True)
    slg    = Column(Float,   nullable=True)
 
    # ── Daily-updated status ──────────────────────────────────────────────────
    injury_status = Column(String(50), nullable=True)
    depth_order   = Column(Integer,    nullable=True)
    player_value  = Column(Float,      nullable=True)
 
    # ── Timestamp (manual only) ───────────────────────────────────────────────
    # Null until the first daily update runs.
    # Never set by SQLAlchemy automatically — only written when all three
    # status fields (injury_status, depth_order, player_value) are updated.
    updated_at = Column(DateTime, nullable=True)
 
 
# ── ALBatter ──────────────────────────────────────────────────────────────────
# American League batters. Populated from players_stats_al_2025.sql.
# Queried when API requests specify league="AL".

class ALBatter(BatterBase, Base):
    __tablename__ = "batters_al"
 
 
# ── NLBatter ──────────────────────────────────────────────────────────────────
# National League batters. Populated from players_stats_nl_2025.sql.
# Queried when API requests specify league="NL".
 
class NLBatter(BatterBase, Base):
    __tablename__ = "batters_nl"


# ── PitcherBase ───────────────────────────────────────────────────────────────
# Abstract mixin that defines the shared schema for ALPitcher and NLPitcher.
#
# Column groups:
#   Identity (from SQL dumps)       : name, position, team
#   Identity (from statsapi.mlb.com): player_id (PK) and biographical fields.
#                                     Populated once at init. Never modified.
#   Stats — FVARz (from SQL dumps)  : w, sv, so, era, whip, ip.
#                                     Used directly in pitcher valuation.
#   Stats — reference only          : l, g, gs, war, fip, h, r, er, hr, bb,
#                                     hbp, bf, era_plus, h9, hr9, bb9, so9,
#                                     so_bb. Stored for API access only.
#   Status (daily scheduler)        : injury_status, depth_order, player_value.
#   Timestamp                       : updated_at. Manual only.

class PitcherBase:
    __abstract__ = True

    # ── Identity: from SQL dumps ──────────────────────────────────────────────
    # position defaults to "P" at init; overwritten by ESPN depth chart updates
    # with "SP", "RP", or "CL" as the season progresses.
    name     = Column(String(255), nullable=False, index=True)
    position = Column(String(20),  nullable=False)
    team     = Column(String(10),  nullable=False)

    # ── Identity: from statsapi.mlb.com (init only) ───────────────────────────
    player_id      = Column(Integer, primary_key=True, index=True)
    first_name     = Column(String(100), nullable=True)
    last_name      = Column(String(100), nullable=True)
    primary_number = Column(String(10),  nullable=True)
    birth_date     = Column(String(20),  nullable=True)
    birth_city     = Column(String(100), nullable=True)
    birth_country  = Column(String(100), nullable=True)
    height         = Column(String(10),  nullable=True)
    weight         = Column(Integer,     nullable=True)
    current_age    = Column(Integer,     nullable=True)
    position_name  = Column(String(50),  nullable=True)
    team_id        = Column(Integer,     nullable=True)
    bat_side       = Column(String(5),   nullable=True)
    pitch_hand     = Column(String(5),   nullable=True)
    mlb_debut_date = Column(String(20),  nullable=True)
    active         = Column(Integer,     nullable=True)   # 1 = active, 0 = inactive

    # ── Season stats — FVARz inputs (from SQL dumps) ──────────────────────────
    w    = Column(Integer, nullable=True)   # wins
    sv   = Column(Integer, nullable=True)   # saves
    so   = Column(Integer, nullable=True)   # strikeouts (SO in Baseball Reference)
    era  = Column(Float,   nullable=True)   # earned run average
    whip = Column(Float,   nullable=True)   # walks + hits per inning pitched
    ip   = Column(Float,   nullable=True)   # innings pitched

    # ── Season stats — reference only (from SQL dumps) ────────────────────────
    l       = Column(Integer, nullable=True)   # losses
    g       = Column(Integer, nullable=True)   # games pitched
    gs      = Column(Integer, nullable=True)   # games started
    war     = Column(Float,   nullable=True)   # wins above replacement
    fip     = Column(Float,   nullable=True)   # fielding independent pitching
    h       = Column(Integer, nullable=True)   # hits allowed
    r       = Column(Integer, nullable=True)   # runs allowed
    er      = Column(Integer, nullable=True)   # earned runs
    hr      = Column(Integer, nullable=True)   # home runs allowed
    bb      = Column(Float,   nullable=True)   # walks (stored as Float; source has .0 values)
    hbp     = Column(Integer, nullable=True)   # hit by pitch
    bf      = Column(Integer, nullable=True)   # batters faced
    era_plus = Column(Float,  nullable=True)   # ERA+ (park/league adjusted; NULL when undefined)
    h9      = Column(Float,   nullable=True)   # hits per 9 innings
    hr9     = Column(Float,   nullable=True)   # home runs per 9 innings
    bb9     = Column(Float,   nullable=True)   # walks per 9 innings
    so9     = Column(Float,   nullable=True)   # strikeouts per 9 innings
    so_bb   = Column(Float,   nullable=True)   # SO/BB ratio (NULL when BB = 0)

    # ── Daily-updated status ──────────────────────────────────────────────────
    injury_status = Column(String(50), nullable=True)
    depth_order   = Column(Integer,    nullable=True)
    player_value  = Column(Float,      nullable=True)

    # ── Timestamp (manual only) ───────────────────────────────────────────────
    updated_at = Column(DateTime, nullable=True)


# ── ALPitcher ─────────────────────────────────────────────────────────────────
# American League pitchers. Populated from pitchers_stats_al_2025.sql.
# Queried when API requests specify league="AL".

class ALPitcher(PitcherBase, Base):
    __tablename__ = "pitchers_al"


# ── NLPitcher ─────────────────────────────────────────────────────────────────
# National League pitchers. Populated from pitchers_stats_nl_2025.sql.
# Queried when API requests specify league="NL".

class NLPitcher(PitcherBase, Base):
    __tablename__ = "pitchers_nl"


# ── LeagueBaseline ────────────────────────────────────────────────────────────
# Stores per-category mean and std computed from the actual player pool.
# Used by api/services/player.py as the baseline for z-score calculation.
#
# Rows are identified by (player_type, category) — this pair acts as a
# logical unique key and is the target for upsert operations in
# compute_baselines.py.
#
# player_type : "batter" or "pitcher"
# category    : stat name — batter: R, HR, RBI, SB, AVG
#                           pitcher: W, SV, K, ERA, WHIP
# mean / std  : computed from non-NULL rows in batters_al + batters_nl
#               or pitchers_al + pitchers_nl depending on player_type
# computed_at : UTC timestamp of the last successful computation

class LeagueBaseline(Base):
    __tablename__ = "league_baselines"
    __table_args__ = (
        UniqueConstraint("player_type", "category", name="uq_baseline_type_category"),
    )

    id          = Column(Integer,  primary_key=True, index=True)
    player_type = Column(String(10),  nullable=False)   # "batter" or "pitcher"
    category    = Column(String(10),  nullable=False)   # e.g. "HR", "ERA"
    mean        = Column(Float,       nullable=False)
    std         = Column(Float,       nullable=False)
    computed_at = Column(DateTime,    nullable=False)


# ── APIRequestLog ─────────────────────────────────────────────────────────────
# Logs each authenticated API request for per-user usage tracking.
# Inserted by api/main.py middleware after each request from a user-issued key.
# Queried by Grafana (per-user dashboard) via MySQL data source.
# INTERNAL_API_KEY traffic is excluded (no logging).

class APIRequestLog(Base):
    __tablename__ = "api_request_logs"

    id          = Column(Integer, primary_key=True, index=True)
    api_key     = Column(String(64),  nullable=False)              # which key issued the call (audit)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    path        = Column(String(255), nullable=True)               # e.g. /player/bid
    status      = Column(Integer,     nullable=True)               # HTTP response code
    duration_ms = Column(Float,       nullable=True)               # request processing time
    ts          = Column(DateTime,    nullable=False, default=datetime.utcnow, index=True)


# ── MLBNewsSeen ───────────────────────────────────────────────────────────────
# Dedup ledger for the MLB news RSS poller. Each row is one feed item we have
# already observed and pushed to the BE webhook. Indexed by guid so the 30-min
# poller can quickly check "have we seen this?" before notifying again.
# Old rows are pruned by the poller itself (cap at MAX_ROWS) to bound growth.

class MLBNewsSeen(Base):
    __tablename__ = "mlb_news_seen"

    id          = Column(Integer, primary_key=True, index=True)
    guid        = Column(String(512), unique=True, nullable=False, index=True)
    title       = Column(String(512), nullable=True)
    seen_at     = Column(DateTime,    nullable=False, default=datetime.utcnow)