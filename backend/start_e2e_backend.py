import os

import uvicorn

from e2e_seed_data import seed_e2e_data


os.environ.setdefault("ENABLE_PRIORITY_URGENCY_ML", "true")
os.environ.setdefault("ENABLE_MUTUAL_AID", "true")
os.environ.setdefault("APP_SKIP_RUNTIME_MIGRATIONS", "true")
os.environ.setdefault("APP_DISABLE_PROJECTOR", "true")


if __name__ == "__main__":
    seed_e2e_data()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
