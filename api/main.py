from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
from api.routers import player
from api.services.player import get_player_value
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="PPA-DUN API")
API_KEY = os.getenv("API_KEY")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if request.url.path == "/health" or request.url.path.startswith("/demo") or request.method == "OPTIONS":
        return await call_next(request)
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return JSONResponse(status_code=401, content={"detail": "Missing API key"})
    if api_key != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Invalid API key"})
    return await call_next(request)

app.include_router(player.router)

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/demo/{player_name}")
def demo(player_name: str):
    return get_player_value(player_name)