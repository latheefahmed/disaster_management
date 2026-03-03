from app.agents.base import BaseAgent
from app.models.audit_log import AuditLog


class AuditAgent(BaseAgent):

    def list_logs(self):
        return self.db.query(AuditLog).order_by(AuditLog.id.desc()).all()
