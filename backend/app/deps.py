from fastapi import Header, HTTPException, Depends
import re
from app.database import SessionLocal
from app.utils.security import get_token_payload, require_roles


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(authorization: str = Header(...)):
    header = str(authorization or "").strip()
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = header[len("Bearer "):].strip()
    if not token or not re.fullmatch(r"[0-9a-fA-F]+", token):
        raise HTTPException(status_code=401, detail="Invalid token format.")

    payload = get_token_payload(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


def require_role(roles):
    def dependency(user=Depends(get_current_user)):
        return require_roles(roles)(user)
    return dependency
