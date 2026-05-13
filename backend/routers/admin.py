import os
from fastapi import APIRouter, Request, HTTPException
from data.pipeline.daily_update import run_daily_update
import threading

router = APIRouter(prefix="/admin")


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