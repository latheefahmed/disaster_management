from sqlalchemy import Column, String
from app.database import Base


class District(Base):
    __tablename__ = "districts"

    district_code = Column(String, primary_key=True)
    district_name = Column(String)
    state_code = Column(String)

    # ----------------------------------
    # Phase 5B – Demand Governance
    # ----------------------------------
    # baseline_plus_human | human_only
    demand_mode = Column(
        String,
        nullable=False,
        server_default="baseline_plus_human"
    )
