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

# ── PlayerBase ────────────────────────────────────────────────────────────────
# Abstract mixin that defines the shared schema for ALPlayer and NLPlayer.
#
# __abstract__ = True tells SQLAlchemy not to create a table for this class
# itself. Only its concrete subclasses (ALPlayer, NLPlayer) get tables.
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
 
class PlayerBase:
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
 
 
# ── ALPlayer ──────────────────────────────────────────────────────────────────
# American League batters. Populated from players_stats_al_2025.sql.
# Queried when API requests specify league="AL".
 
class ALPlayer(PlayerBase, Base):
    __tablename__ = "players_al"
 
 
# ── NLPlayer ──────────────────────────────────────────────────────────────────
# National League batters. Populated from players_stats_nl_2025.sql.
# Queried when API requests specify league="NL".
 
class NLPlayer(PlayerBase, Base):
    __tablename__ = "players_nl"


# ── Unmatched ──────────────────────────────────────────────────────────────────
# players that are not in MLB stat api
class UnmatchedPlayer(Base):
    __tablename__ = "unmatched_players"

    id         = Column(Integer, primary_key=True, index=True)
    league     = Column(String(2),   nullable=False)          # "AL" or "NL"
    name       = Column(String(255), nullable=False)          # raw name from SQL dump
    team       = Column(String(10),  nullable=False)
    position   = Column(String(20),  nullable=False)
    ab         = Column(Integer,     nullable=True)
    r          = Column(Integer,     nullable=True)
    h          = Column(Integer,     nullable=True)
    hr         = Column(Integer,     nullable=True)
    rbi        = Column(Integer,     nullable=True)
    sb         = Column(Integer,     nullable=True)
    avg        = Column(Float,       nullable=True)
    created_at = Column(DateTime,    default=datetime.utcnow)


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
# mean / std  : computed from non-NULL rows in players_al + players_nl
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