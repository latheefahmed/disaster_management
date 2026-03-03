from app.analytics.fairness_metrics import compute_fairness
from app.analytics.risk_metrics import compute_unmet_risk


def build_explanation():
    return {
        "fairness": compute_fairness(),
        "risk": compute_unmet_risk()
    }
