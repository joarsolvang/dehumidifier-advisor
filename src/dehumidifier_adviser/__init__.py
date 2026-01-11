"""Dehumidifier Adviser - Humidity forecasting and analysis."""

from dehumidifier_adviser.geocoding import (
    Geocoder,
    GeocodingError,
    GeocodingServiceError,
    LocationNotFoundError,
)
from dehumidifier_adviser.models import DailyHumidityData, HourlyHumidityData, HumidityForecast, Location
from dehumidifier_adviser.weather import OpenMeteoClient

__version__ = "0.1.0"

__all__ = [
    "DailyHumidityData",
    "Geocoder",
    "GeocodingError",
    "GeocodingServiceError",
    "HourlyHumidityData",
    "HumidityForecast",
    "Location",
    "LocationNotFoundError",
    "OpenMeteoClient",
]
