from sqlalchemy import Column, String, Boolean
from app.database import Base

class User(Base):
    __tablename__ = "users"

    username = Column(String, primary_key=True)
    password_hash = Column(String)

    role = Column(String)  # district / state / national / admin

    state_code = Column(String, nullable=True)
    district_code = Column(String, nullable=True)

    is_active = Column(Boolean, default=True)