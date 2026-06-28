"""Data models for the humidity simulator API."""

from typing import Literal

from pydantic import BaseModel, Field


class HumiditySource(BaseModel):
    """A source of humidity emissions with associated timeseries data."""

    name: str
    max_emissions_rate_unit: Literal["g/h", "kg/h", "lb/h"]
    timestamps: list[str]
    timestamp_format: str
    timezone: str
    values: list[float]
    values_unit: Literal["g/h", "kg/h", "lb/h"]


class AmbientConditions(BaseModel):
    """External ambient conditions timeseries for the simulation."""

    name: str
    timestamps: list[str]
    timestamp_format: str
    timezone: str
    relative_humidity: list[float]
    ambient_temperature: list[float]
    ambient_temperature_unit: Literal["Celcius"]


class SimulationRequest(BaseModel):
    """Request body for the humidity simulator /simulate endpoint."""

    surface_area: float = Field(gt=0, description="Floor area of the room")
    surface_area_unit: Literal["m2", "ft2"] = Field(description="Unit for surface area")
    ceiling_height: float = Field(gt=0, description="Height of the ceiling")
    ceiling_height_unit: Literal["m", "ft"] = Field(description="Unit for ceiling height")
    internal_temperature: float = Field(description="Room temperature")
    internal_temperature_unit: Literal["c", "k", "f"] = Field(description="Unit for temperature")
    air_changes_per_hour: float = Field(gt=0, description="Air Changes per Hour (ACH)")
    starting_relative_humidity: float = Field(ge=0, le=100, description="Initial relative humidity (0-100%)")
    time_resolution_minutes: int = Field(default=30, gt=0, description="Time step for simulation in minutes")
    sources: list[HumiditySource] = Field(description="List of humidity sources to simulate")
    external_ambient_conditions: AmbientConditions = Field(description="Forecast ambient conditions")


class SimulationResult(BaseModel):
    """Results from a humidity simulation."""

    timestamps: list[str]
    relative_humidity: list[float]
    absolute_humidity: list[float]
    dehumidifier_running_cost_pence: list[float] | None = None
