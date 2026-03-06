from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from backend.db.session import engine, Base
from backend.db.models import User, APIKey
from backend.routers import auth

load_dotenv()

app = FastAPI(title="PPA-DUN Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


app.include_router(auth.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
