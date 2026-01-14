"""Data models for Open-Meteo API responses."""

from datetime import datetime

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, field_validator


class HourlyHumidityData(BaseModel):
    """Hourly humidity-related weather data."""

    time: list[datetime] = Field(description="Hourly timestamps")
    relative_humidity_2m: list[float] | None = Field(None, description="Relative humidity at 2m above ground (%)")
    dew_point_2m: list[float] | None = Field(None, description="Dew point temperature at 2m (°C)")
    vapour_pressure_deficit: list[float] | None = Field(None, description="Vapour Pressure Deficit (VPD) in kPa")

    def to_dataframe(self) -> pl.DataFrame:
        """Convert hourly data to a Polars DataFrame.

        Returns:
            Polars DataFrame with hourly humidity data
        """
        data: dict[str, list[datetime] | list[float] | None] = {"time": self.time}

        if self.relative_humidity_2m is not None:
            data["relative_humidity_2m"] = self.relative_humidity_2m
        if self.dew_point_2m is not None:
            data["dew_point_2m"] = self.dew_point_2m
        if self.vapour_pressure_deficit is not None:
            data["vapour_pressure_deficit"] = self.vapour_pressure_deficit

        return pl.DataFrame(data)


class DailyHumidityData(BaseModel):
    """Daily humidity-related weather data."""

    time: list[datetime] = Field(description="Daily dates")
    relative_humidity_2m_mean: list[float] | None = Field(None, description="Mean daily relative humidity at 2m (%)")
    relative_humidity_2m_max: list[float] | None = Field(None, description="Maximum daily relative humidity at 2m (%)")
    relative_humidity_2m_min: list[float] | None = Field(None, description="Minimum daily relative humidity at 2m (%)")
    dew_point_2m_mean: list[float] | None = Field(None, description="Mean daily dew point at 2m (°C)")
    dew_point_2m_max: list[float] | None = Field(None, description="Maximum daily dew point at 2m (°C)")
    dew_point_2m_min: list[float] | None = Field(None, description="Minimum daily dew point at 2m (°C)")

    def to_dataframe(self) -> pl.DataFrame:
        """Convert daily data to a Polars DataFrame.

        Returns:
            Polars DataFrame with daily humidity data
        """
        data: dict[str, list[datetime] | list[float] | None] = {"time": self.time}

        if self.relative_humidity_2m_mean is not None:
            data["relative_humidity_2m_mean"] = self.relative_humidity_2m_mean
        if self.relative_humidity_2m_max is not None:
            data["relative_humidity_2m_max"] = self.relative_humidity_2m_max
        if self.relative_humidity_2m_min is not None:
            data["relative_humidity_2m_min"] = self.relative_humidity_2m_min
        if self.dew_point_2m_mean is not None:
            data["dew_point_2m_mean"] = self.dew_point_2m_mean
        if self.dew_point_2m_max is not None:
            data["dew_point_2m_max"] = self.dew_point_2m_max
        if self.dew_point_2m_min is not None:
            data["dew_point_2m_min"] = self.dew_point_2m_min

        return pl.DataFrame(data)


class CurrentWeather(BaseModel):
    """Current weather conditions from Open-Meteo API."""

    model_config = ConfigDict(frozen=True)

    time: datetime = Field(description="Timestamp of current conditions")
    temperature_2m: float = Field(description="Temperature at 2m above ground (°C)")
    relative_humidity_2m: float = Field(description="Relative humidity at 2m (%)")
    weather_code: int = Field(ge=0, le=99, description="WMO weather interpretation code")


class HumidityForecast(BaseModel):
    """Complete humidity forecast response from Open-Meteo API."""

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})

    latitude: float = Field(description="Location latitude")
    longitude: float = Field(description="Location longitude")
    timezone: str = Field(description="Timezone identifier")
    timezone_abbreviation: str = Field(description="Timezone abbreviation")
    elevation: float = Field(description="Location elevation in meters")
    hourly: HourlyHumidityData | None = Field(None, description="Hourly humidity data")
    daily: DailyHumidityData | None = Field(None, description="Daily humidity data")
    hourly_units: dict[str, str] | None = Field(None, description="Units for hourly parameters")
    daily_units: dict[str, str] | None = Field(None, description="Units for daily parameters")


class Location(BaseModel):
    """Location information with coordinates and address details.

    This model represents a geographic location with both coordinates
    and human-readable address components.
    """

    city: str = Field(description="City name")
    country: str = Field(description="Country name")
    state: str | None = Field(None, description="State/province/region (optional)")
    latitude: float = Field(description="Latitude (-90 to 90)")
    longitude: float = Field(description="Longitude (-180 to 180)")
    display_name: str | None = Field(None, description="Full formatted address from geocoder")

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        """Validate latitude is within valid range."""
        if not -90 <= v <= 90:
            raise ValueError(f"Latitude must be between -90 and 90, got {v}")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        """Validate longitude is within valid range."""
        if not -180 <= v <= 180:
            raise ValueError(f"Longitude must be between -180 and 180, got {v}")
        return v
