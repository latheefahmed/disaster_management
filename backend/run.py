from app.database import Base, engine, apply_runtime_migrations

from app.models.state import State
from app.models.district import District
from app.models.resource import Resource
from app.models.user import User
from app.models.audit_log import AuditLog
from app.models.request import ResourceRequest
from app.models.allocation import Allocation
from app.models.scenario import Scenario
from app.models.scenario_request import ScenarioRequest
from app.models.scenario_state_stock import ScenarioStateStock
from app.models.scenario_national_stock import ScenarioNationalStock
from app.models.solver_run import SolverRun
from app.models.scenario_explanation import ScenarioExplanation
from app.models.agent_recommendation import AgentRecommendation
from app.models.pool_transaction import PoolTransaction
from app.models.priority_urgency_model import PriorityUrgencyModel
from app.models.priority_urgency_event import PriorityUrgencyEvent
from app.models.request_prediction import RequestPrediction


def init_db():
    Base.metadata.create_all(bind=engine)
    apply_runtime_migrations()


if __name__ == "__main__":
    init_db()
    print("Database tables created successfully.")
