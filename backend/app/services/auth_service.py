from sqlalchemy.orm import Session
from app.models.user import User
from app.utils.hashing import hash_password
from app.utils.security import generate_token, store_token


def authenticate_user(db: Session, username: str, password: str):
    user = db.get(User, username)
    if not user:
        return None

    if user.password_hash != hash_password(password):
        return None

    token = generate_token()

    payload = {
        "username": user.username,
        "role": user.role,
        "state_code": user.state_code,
        "district_code": user.district_code,
    }

    store_token(token, payload)
    return token, payload
