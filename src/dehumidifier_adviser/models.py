"""Data models for Open-Meteo API responses."""

from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, Field


class HourlyHumidityData(BaseModel):
    """Hourly humidity-related weather data."""

    time: list[datetime] = Field(description="Hourly timestamps")
    relative_humidity_2m: list[float] | None = Field(None, description="Relative humidity at 2m above ground (%)")
    dew_point_2m: list[float] | None = Field(None, description="Dew point temperature at 2m (°C)")
    vapour_pressure_deficit: list[float] | None = Field(None, description="Vapour Pressure Deficit (VPD) in kPa")


class DailyHumidityData(BaseModel):
    """Daily humidity-related weather data."""

    time: list[datetime] = Field(description="Daily dates")
    relative_humidity_2m_mean: list[float] | None = Field(None, description="Mean daily relative humidity at 2m (%)")
    relative_humidity_2m_max: list[float] | None = Field(None, description="Maximum daily relative humidity at 2m (%)")
    relative_humidity_2m_min: list[float] | None = Field(None, description="Minimum daily relative humidity at 2m (%)")
    dew_point_2m_mean: list[float] | None = Field(None, description="Mean daily dew point at 2m (°C)")
    dew_point_2m_max: list[float] | None = Field(None, description="Maximum daily dew point at 2m (°C)")
    dew_point_2m_min: list[float] | None = Field(None, description="Minimum daily dew point at 2m (°C)")


class HumidityForecast(BaseModel):
    """Complete humidity forecast response from Open-Meteo API."""

    latitude: float = Field(description="Location latitude")
    longitude: float = Field(description="Location longitude")
    timezone: str = Field(description="Timezone identifier")
    timezone_abbreviation: str = Field(description="Timezone abbreviation")
    elevation: float = Field(description="Location elevation in meters")
    hourly: HourlyHumidityData | None = Field(None, description="Hourly humidity data")
    daily: DailyHumidityData | None = Field(None, description="Daily humidity data")
    hourly_units: dict[str, str] | None = Field(None, description="Units for hourly parameters")
    daily_units: dict[str, str] | None = Field(None, description="Units for daily parameters")

    class Config:
        """Pydantic model configuration."""

        json_encoders: ClassVar[dict] = {datetime: lambda v: v.isoformat()}
