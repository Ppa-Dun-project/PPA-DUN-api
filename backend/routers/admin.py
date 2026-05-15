import os
import threading
from typing import Optional

import requests
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from data.pipeline.daily_update import run_daily_update

router = APIRouter(prefix="/admin")


class PlayerEventPayload(BaseModel):
    """Fake notification payload — admin manually triggers a notification-worthy
    event. No player data is mutated; this just relays the event to the Draft
    Kit Backend so a toast appears in connected browsers."""
    player_id: str
    message: str
    event_type: str = "INJURY"
    player_name: Optional[str] = None


@router.post("/update")
def trigger_update(request: Request):
    """
    POST /admin/update

    Immediately triggers the full daily update pipeline
    (injury → depth charts → player_value recalculation)
    in a background thread so the HTTP response returns instantly.
    """
    admin_secret = os.getenv("ADMIN_SECRET")
    if not admin_secret:
        raise HTTPException(status_code=503, detail="ADMIN_SECRET not configured")

    x_admin_key = request.headers.get("X-Admin-Key")
    if not x_admin_key or x_admin_key != admin_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key")

    thread = threading.Thread(target=run_daily_update, daemon=True)
    thread.start()

    return {"status": "update started"}


@router.post("/player-event")
def force_player_event(payload: PlayerEventPayload, request: Request):
    """
    POST /admin/player-event

    Force-push a notification-worthy event to the Draft Kit (fake demo input).
    No player data is mutated — this just relays the event to the Draft Kit
    Backend webhook so a toast appears in connected browsers.

    Body: { player_id, message, event_type?, player_name? }
    Auth: X-Admin-Key header (must match ADMIN_SECRET env)
    """
    admin_secret = os.getenv("ADMIN_SECRET")
    if not admin_secret:
        raise HTTPException(status_code=503, detail="ADMIN_SECRET not configured")

    x_admin_key = request.headers.get("X-Admin-Key")
    if not x_admin_key or x_admin_key != admin_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key")

    be_webhook_url = os.getenv("BE_WEBHOOK_URL")
    internal_key = os.getenv("INTERNAL_WEBHOOK_KEY")
    if not be_webhook_url or not internal_key:
        raise HTTPException(status_code=503, detail="BE webhook not configured")

    try:
        resp = requests.post(
            be_webhook_url,
            json=payload.model_dump(),
            headers={"X-Internal-Key": internal_key},
            timeout=5,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to notify backend: {e}")

    return {"status": "notified", "event": payload.model_dump()}