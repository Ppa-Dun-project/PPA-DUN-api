from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
from api.routers import player
from dotenv import load_dotenv

load_dotenv()   # read .env file and set environment variables

app = FastAPI(title="PPA-DUN API")

API_KEY = os.getenv("API_KEY")

@app.middleware("http")   # middleware to check API for all http requests
async def verify_api_key(request: Request, call_next):  # call_next: included in api request call (/player || /health)
    if request.url.path == "/health":
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