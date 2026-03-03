from app.agents.base import BaseAgent
from app.services.request_service import create_request


class DistrictAgent(BaseAgent):

    def submit_request(self, data):
        return create_request(self.db, self.actor, data)

    def propose_adjustment(self, demand_row: dict) -> dict:
        """
        District may slightly boost its own critical needs.
        """
        demand_row["demand"] = demand_row["demand"] * 1.0
        return demand_row
