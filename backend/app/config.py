from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_URL = f"sqlite:///{BASE_DIR / 'backend.db'}"

# Core-engine frozen data root (READ-ONLY)
CORE_ENGINE_ROOT = BASE_DIR.parent / "core_engine"

DATA_PROCESSED_PATH = CORE_ENGINE_ROOT / "data" / "processed" / "new_data"
PHASE3_OUTPUT_PATH = CORE_ENGINE_ROOT / "phase3" / "output"
PHASE4_RESOURCE_SCHEMA = CORE_ENGINE_ROOT / "phase4" / "resources" / "schema"
PHASE4_RESOURCE_DATA = CORE_ENGINE_ROOT / "phase4" / "resources" / "synthetic_data"


ENABLE_DEMAND_LEARNING = os.getenv("ENABLE_DEMAND_LEARNING", "false").strip().lower() in {"1", "true", "yes", "on"}
DEMAND_LEARNING_LAMBDA = float(os.getenv("DEMAND_LEARNING_LAMBDA", "0.3"))
DEMAND_LEARNING_RIDGE_ALPHA = float(os.getenv("DEMAND_LEARNING_RIDGE_ALPHA", "1.0"))
DEMAND_LEARNING_MIN_SAMPLES = int(os.getenv("DEMAND_LEARNING_MIN_SAMPLES", "20"))
DEMAND_LEARNING_SMOOTHING = float(os.getenv("DEMAND_LEARNING_SMOOTHING", "0.35"))

ENABLE_PRIORITY_URGENCY_ML = os.getenv("ENABLE_PRIORITY_URGENCY_ML", "false").strip().lower() in {"1", "true", "yes", "on"}
PRIORITY_URGENCY_CONFIDENCE_THRESHOLD = float(os.getenv("PRIORITY_URGENCY_CONFIDENCE_THRESHOLD", "0.55"))
PRIORITY_URGENCY_MIN_SAMPLES = int(os.getenv("PRIORITY_URGENCY_MIN_SAMPLES", "50"))
PRIORITY_URGENCY_L2 = float(os.getenv("PRIORITY_URGENCY_L2", "0.05"))
PRIORITY_URGENCY_LEARNING_RATE = float(os.getenv("PRIORITY_URGENCY_LEARNING_RATE", "0.05"))
PRIORITY_URGENCY_EPOCHS = int(os.getenv("PRIORITY_URGENCY_EPOCHS", "300"))

PHASE8_HORIZON = int(os.getenv("PHASE8_HORIZON", "30"))
PHASE8_ENABLE_ROLLING = os.getenv("PHASE8_ENABLE_ROLLING", "false").strip().lower() in {"1", "true", "yes", "on"}
PHASE8_WEIGHT_UNMET = float(os.getenv("PHASE8_WEIGHT_UNMET", "1000000"))
PHASE8_WEIGHT_HOLD = float(os.getenv("PHASE8_WEIGHT_HOLD", "1"))
PHASE8_WEIGHT_SHIP = float(os.getenv("PHASE8_WEIGHT_SHIP", "2"))
PHASE8_SOLVER_TIMEOUT_SEC = int(os.getenv("PHASE8_SOLVER_TIMEOUT_SEC", "300"))

ENABLE_MUTUAL_AID = os.getenv("ENABLE_MUTUAL_AID", "true").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_AGENT_ENGINE = os.getenv("ENABLE_AGENT_ENGINE", "false").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_RECEIPT_CONFIRMATION = os.getenv("ENABLE_RECEIPT_CONFIRMATION", "false").strip().lower() in {"1", "true", "yes", "on"}
AVG_SPEED_KMPH = float(os.getenv("AVG_SPEED_KMPH", "50"))
ENABLE_NN_META_CONTROLLER = os.getenv("ENABLE_NN_META_CONTROLLER", "false").strip().lower() in {"1", "true", "yes", "on"}
NN_ROLLING_WINDOW = int(os.getenv("NN_ROLLING_WINDOW", "30"))