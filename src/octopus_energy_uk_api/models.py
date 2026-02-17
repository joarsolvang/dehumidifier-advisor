"""Data models for the Octopus Energy UK API."""

from datetime import datetime

from pydantic import BaseModel


class UnitRate(BaseModel):
    """A single half-hourly price point."""

    value_exc_vat: float
    value_inc_vat: float
    valid_from: datetime
    valid_to: datetime | None


class StandingCharge(BaseModel):
    """Daily fixed charge."""

    value_exc_vat: float
    value_inc_vat: float
    valid_from: datetime
    valid_to: datetime | None


class AgileRates(BaseModel):
    """Collection result for agile tariff rates."""

    tariff_code: str
    product_code: str
    unit_rates: list[UnitRate]
    standing_charges: list[StandingCharge]


class AgileRatesTimeSeries(BaseModel):
    """A source of Agile Rate timeseries."""

    name: str
    desciption: str
    timestamps: list[str]
    timestamp_format: str
    timezone: str
    values: list[float]
    values_unit: str
