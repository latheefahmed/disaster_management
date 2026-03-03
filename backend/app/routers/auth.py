from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.auth import LoginRequest
from app.services.auth_service import authenticate_user

router = APIRouter()


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    result = authenticate_user(db, data.username, data.password)

    if not result:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # authenticate_user returns (token, payload)
    token, payload = result

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": payload["role"],
        "state_code": payload.get("state_code"),
        "district_code": payload.get("district_code"),
    }
