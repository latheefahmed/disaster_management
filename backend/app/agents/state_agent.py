from app.agents.base import BaseAgent
from app.models.request import ResourceRequest


class StateAgent(BaseAgent):

    def list_requests(self):
        return self.db.query(ResourceRequest).filter(
            ResourceRequest.state_code == self.actor["state_code"]
        ).all()

    def approve_request(self, request_id: int):
        req = self.db.get(ResourceRequest, request_id)
        if not req:
            return None

        req.status = "approved"
        self.db.commit()

        self.audit(
            "REQUEST_APPROVED",
            {
                "request_id": req.id,
                "district_code": req.district_code
            }
        )
        return req

    def reject_request(self, request_id: int, reason: str):
        req = self.db.get(ResourceRequest, request_id)
        if not req:
            return None

        req.status = "rejected"
        self.db.commit()

        self.audit(
            "REQUEST_REJECTED",
            {
                "request_id": req.id,
                "reason": reason
            }
        )
        return req

    def escalate_request(self, request_id: int):
        req = self.db.get(ResourceRequest, request_id)
        if not req:
            return None

        req.status = "escalated"
        self.db.commit()

        self.audit(
            "REQUEST_ESCALATED",
            {
                "request_id": req.id,
                "state_code": self.actor["state_code"]
            }
        )
        return req

    def propose_adjustment(self, demand_row: dict) -> dict:
        """
        State smooths spikes.
        """
        demand_row["demand"] = min(demand_row["demand"], 1.2 * demand_row["demand"])
        return demand_row
