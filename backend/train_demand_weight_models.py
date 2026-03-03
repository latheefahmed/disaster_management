from app.database import SessionLocal
from app.services.demand_learning_service import train_demand_weight_models


def main():
    db = SessionLocal()
    try:
        result = train_demand_weight_models(db)
        db.commit()
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
