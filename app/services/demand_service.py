from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.entities import ActualSale, DemandForecast
from app.utils.ids import utcnow


class DemandService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.settings = get_settings()

    def get_forecast(self, sku: str, node_id: str) -> DemandForecast | None:
        return (
            self.session.query(DemandForecast)
            .filter_by(sku=sku, node_id=node_id)
            .order_by(DemandForecast.forecast_timestamp.desc())
            .first()
        )

    def list_forecasts(self) -> list[DemandForecast]:
        return self.session.query(DemandForecast).order_by(DemandForecast.sku).all()

    def get_sales(self, sku: str, node_id: str) -> list[ActualSale]:
        return (
            self.session.query(ActualSale)
            .filter_by(sku=sku, node_id=node_id)
            .order_by(ActualSale.period_start)
            .all()
        )

    def list_sales(self) -> list[ActualSale]:
        return self.session.query(ActualSale).order_by(ActualSale.sku).all()

    def is_stale(self, forecast: DemandForecast | None) -> bool:
        if forecast is None:
            return True
        ts = forecast.forecast_timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = utcnow() - ts
        return age > timedelta(hours=self.settings.stale_forecast_hours)

    def demand_change(self, sku: str, node_id: str) -> dict:
        forecast = self.get_forecast(sku, node_id)
        sales = self.get_sales(sku, node_id)
        if not sales:
            return {"status": "missing_sales", "material": False}
        recent = sales[-1]
        window_hours = (recent.period_end - recent.period_start).total_seconds() / 3600
        unreliable_window = window_hours < 24
        if forecast is None:
            return {
                "status": "missing_forecast",
                "material": False,
                "unreliable_window": unreliable_window,
                "recent_qty": recent.quantity_sold,
                "window_hours": window_hours,
            }
        expected_in_window = forecast.daily_demand * max(window_hours / 24.0, 1 / 24)
        if expected_in_window <= 0:
            return {"status": "invalid_forecast", "material": False}
        ratio = recent.quantity_sold / expected_in_window
        material = (ratio - 1) >= self.settings.demand_spike_threshold and not unreliable_window
        return {
            "status": "compared",
            "material": material,
            "ratio": ratio,
            "recent_qty": recent.quantity_sold,
            "expected_in_window": expected_in_window,
            "window_hours": window_hours,
            "unreliable_window": unreliable_window,
            "stale_forecast": self.is_stale(forecast),
            "daily_demand": forecast.daily_demand,
        }
