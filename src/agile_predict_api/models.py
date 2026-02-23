"""Data models for the Agile Predict energy price forecast API."""

import logging
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PricePoint(BaseModel):
    """A single forecast price data point."""

    date_time: datetime
    agile_pred: float = Field(description="Predicted Agile electricity price (p/kWh)")
    agile_pred_low: float | None = Field(default=None, description="Lower bound of price estimate (p/kWh)")
    agile_pred_high: float | None = Field(default=None, description="Upper bound of price estimate (p/kWh)")


class EnergyForecastTimeSeries(BaseModel):
    """Agile energy price forecast as a flat, JSON-serialisable timeseries."""

    timestamps: list[str]
    timestamp_format: str
    timezone: str
    values: list[float]
    values_unit: Literal["p/kWh"]


class EnergyForecast(BaseModel):
    """A single energy price forecast from the Agile Predict API."""

    name: str = Field(description="Forecast identifier")
    created_at: datetime = Field(description="When this forecast was generated")
    prices: list[PricePoint] = Field(description="Ordered list of half-hourly price points")

    def to_timeseries(self) -> EnergyForecastTimeSeries:
        """Convert this forecast to a flat timeseries ready for JSON serialisation."""
        timestamps = [price_point.date_time for price_point in self.prices]
        values = [price_point.agile_pred for price_point in self.prices]
        if timestamps[0].tzinfo is None:
            logger.warning("Timestamp %s is naive (no timezone info); defaulting timezone to 'UTC'", timestamps[0])
        timezone = timestamps[0].tzname() or "UTC"
        iso_timestamps = [timestamp.isoformat() for timestamp in timestamps]
        return EnergyForecastTimeSeries(
            timestamps=iso_timestamps,
            timestamp_format="ISO 8601",
            timezone=timezone,
            values=values,
            values_unit="p/kWh",
        )
