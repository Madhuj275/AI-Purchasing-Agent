from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import Budget


class BudgetService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, node_id: str, category: str, period: str = "2026-Q4") -> Budget | None:
        return self.session.query(Budget).filter_by(node_id=node_id, category=category, period=period).one_or_none()

    def list_budgets(self) -> list[Budget]:
        return self.session.query(Budget).order_by(Budget.node_id, Budget.category).all()

    def can_commit(self, node_id: str, category: str, amount: float) -> bool:
        row = self.get(node_id, category)
        if row is None:
            return False
        return amount <= row.remaining + 1e-9

    def commit(self, node_id: str, category: str, amount: float) -> Budget:
        row = self.get(node_id, category)
        if row is None:
            raise ValueError("Budget not found")
        if amount > row.remaining + 1e-9:
            raise ValueError("Insufficient budget")
        row.committed += amount
        row.remaining -= amount
        self.session.flush()
        return row

    def release(self, node_id: str, category: str, amount: float) -> Budget:
        row = self.get(node_id, category)
        if row is None:
            raise ValueError("Budget not found")
        row.committed = max(0.0, row.committed - amount)
        row.remaining += amount
        self.session.flush()
        return row
