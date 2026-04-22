from fastapi import APIRouter
from data.daily_update import run_daily_update
import threading

router = APIRouter(prefix="/admin")


@router.post("/update")
def trigger_update():
    """
    POST /admin/update

    Immediately triggers the full daily update pipeline
    (injury → depth charts → player_value recalculation)
    in a background thread so the HTTP response returns instantly.
    """
    thread = threading.Thread(target=run_daily_update, daemon=True)
    thread.start()

    return {"status": "update started"}