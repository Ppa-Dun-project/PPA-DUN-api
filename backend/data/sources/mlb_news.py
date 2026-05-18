"""MLB news RSS poller — feeds the Draft Kit notification system.

Every poll cycle:
  1. Fetch the Yahoo Sports MLB RSS feed.
  2. Parse out (guid, title, link) for each <item>.
  3. Compare against the `mlb_news_seen` ledger; anything not in the ledger
     is a new story.
  4. Record new guids in the ledger and return them so the caller can push
     a notification per item.
  5. On the very first call (ledger empty) we still record everything but
     return no items — this prevents a backlog-flood of toasts when the
     scheduler is freshly deployed.

Old ledger rows are pruned to a bounded count so the table does not grow
forever; the cap is generous enough that no Yahoo MLB story should be
re-notified once it has been seen.

We parse the RSS with stdlib (xml.etree) rather than pulling in feedparser
because we only need three fields and the feed is well-formed.
"""

from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional

import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import MLBNewsSeen

logger = logging.getLogger(__name__)

# Yahoo Sports MLB feed — same source the homepage already polls via rss2json,
# but here we hit it directly server-side and parse the XML ourselves.
RSS_URL = "https://sports.yahoo.com/mlb/rss/"

# How many rows we keep in `mlb_news_seen` before pruning. Yahoo's feed has
# ~20 items at a time, so 500 covers comfortably more than a week of churn.
MAX_LEDGER_ROWS = 500

# Same DB connection settings as other backend pipeline modules.
DATABASE_URL = "mysql+pymysql://root:{password}@{host}:3306/{db}".format(
    password=os.getenv("MYSQL_ROOT_PASSWORD", ""),
    host=os.getenv("MYSQL_HOST", "db"),
    db=os.getenv("MYSQL_DATABASE", "ppa_dun_api"),
)
_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
_SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


@dataclass(frozen=True)
class NewsItem:
    guid: str
    title: str
    link: Optional[str]


def _fetch_rss_items() -> List[NewsItem]:
    """Fetch the Yahoo MLB RSS feed and return items as (guid, title, link).

    Items without a `guid` (or with empty title) are skipped — without a stable
    id we have no way to dedup, and an empty title would render an empty toast.
    """
    try:
        resp = requests.get(RSS_URL, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"[mlb_news] RSS fetch failed: {e}")
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.warning(f"[mlb_news] RSS parse failed: {e}")
        return []

    items: List[NewsItem] = []
    for it in root.iter("item"):
        guid_el = it.find("guid")
        title_el = it.find("title")
        link_el = it.find("link")
        guid = (guid_el.text or "").strip() if guid_el is not None else ""
        title = (title_el.text or "").strip() if title_el is not None else ""
        if not guid or not title:
            continue
        link = (link_el.text or "").strip() if link_el is not None else None
        items.append(NewsItem(guid=guid, title=title, link=link))
    return items


def _prune_old(session, keep: int = MAX_LEDGER_ROWS) -> None:
    """Keep only the `keep` most-recent rows in `mlb_news_seen`."""
    total = session.query(MLBNewsSeen).count()
    if total <= keep:
        return
    # Delete the oldest (total - keep) rows.
    oldest_ids_subq = (
        session.query(MLBNewsSeen.id)
        .order_by(MLBNewsSeen.seen_at.asc())
        .limit(total - keep)
        .all()
    )
    ids_to_delete = [row.id for row in oldest_ids_subq]
    if ids_to_delete:
        session.query(MLBNewsSeen).filter(MLBNewsSeen.id.in_(ids_to_delete)).delete(
            synchronize_session=False
        )


def find_new_items() -> List[NewsItem]:
    """Poll the RSS feed and return only items we have not yet seen.

    Side effect: every fetched item's guid is written to the ledger so future
    polls will treat it as "seen". On the very first call (empty ledger) we
    still write everything but return an empty list — no backlog spam.
    """
    items = _fetch_rss_items()
    if not items:
        return []

    session = _SessionLocal()
    try:
        bootstrap = session.query(MLBNewsSeen).first() is None

        existing_guids = {
            row.guid
            for row in session.query(MLBNewsSeen.guid)
            .filter(MLBNewsSeen.guid.in_([it.guid for it in items]))
            .all()
        }
        new_items = [it for it in items if it.guid not in existing_guids]
        if not new_items:
            return []

        for it in new_items:
            session.add(MLBNewsSeen(guid=it.guid, title=it.title[:500]))

        _prune_old(session)
        session.commit()

        if bootstrap:
            logger.info(
                f"[mlb_news] bootstrap — recorded {len(new_items)} items, "
                "skipping notifications for this cycle"
            )
            return []

        logger.info(f"[mlb_news] {len(new_items)} new items to notify")
        return new_items
    except Exception as e:
        session.rollback()
        logger.warning(f"[mlb_news] ledger update failed: {e}")
        return []
    finally:
        session.close()
