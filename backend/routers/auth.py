import os
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from google.oauth2 import id_token
from google.auth.transport import requests
from pydantic import BaseModel
from backend.db.session import get_db
from backend.db.models import User, APIKey

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")


class GoogleLoginRequest(BaseModel):
    token: str


class UserResponse(BaseModel):
    id: int
    email: str
    name: str

    class Config:
        from_attributes = True


class APIKeyResponse(BaseModel):
    key: str
    created_at: str


@router.post("/google", response_model=UserResponse)
def google_login(req: GoogleLoginRequest, db: Session = Depends(get_db)):
    try:
        idinfo = id_token.verify_oauth2_token(
            req.token, requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    google_id = idinfo["sub"]
    email = idinfo["email"]
    name = idinfo.get("name", "")

    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        user = User(google_id=google_id, email=email, name=name)
        db.add(user)
        db.commit()
        db.refresh(user)

    return user


@router.post("/api-key", response_model=APIKeyResponse)
def create_api_key(google_token: GoogleLoginRequest, db: Session = Depends(get_db)):
    try:
        idinfo = id_token.verify_oauth2_token(
            google_token.token, requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    user = db.query(User).filter(User.google_id == idinfo["sub"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    key = secrets.token_hex(32)
    api_key = APIKey(key=key, user_id=user.id)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return APIKeyResponse(key=api_key.key, created_at=str(api_key.created_at))


@router.get("/api-keys")
def get_api_keys(google_token: str, db: Session = Depends(get_db)):
    try:
        idinfo = id_token.verify_oauth2_token(
            google_token, requests.Request(), GOOGLE_CLIENT_ID
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    user = db.query(User).filter(User.google_id == idinfo["sub"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    keys = db.query(APIKey).filter(APIKey.user_id == user.id).all()
    return [APIKeyResponse(key=k.key, created_at=str(k.created_at)) for k in keys]
