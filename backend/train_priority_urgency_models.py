from app.database import SessionLocal
from app.services.priority_urgency_ml_service import train_priority_urgency_models


def main():
    db = SessionLocal()
    try:
        result = train_priority_urgency_models(db)
        db.commit()
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
