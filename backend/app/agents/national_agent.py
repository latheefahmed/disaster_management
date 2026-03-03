from app.agents.base import BaseAgent
from app.models.request import ResourceRequest


class NationalAgent(BaseAgent):

    def list_escalated(self):
        return self.db.query(ResourceRequest).filter(
            ResourceRequest.status == "escalated"
        ).all()

    def mark_fulfilled(self, request_id: int):
        req = self.db.get(ResourceRequest, request_id)
        if not req:
            return None

        req.status = "fulfilled"
        self.db.commit()

        self.audit(
            "REQUEST_FULFILLED",
            {
                "request_id": req.id
            }
        )
        return req

    def mark_unfulfilled(self, request_id: int, reason: str):
        req = self.db.get(ResourceRequest, request_id)
        if not req:
            return None

        req.status = "unmet"
        self.db.commit()

        self.audit(
            "REQUEST_UNMET",
            {
                "request_id": req.id,
                "reason": reason
            }
        )
        return req

    def propose_adjustment(self, demand_row: dict) -> dict:
        """
        National ensures macro stability.
        """
        demand_row["demand"] = demand_row["demand"]
        return demand_row
