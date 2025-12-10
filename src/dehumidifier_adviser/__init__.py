"""Dehumidifier Adviser - Humidity forecasting and analysis."""

from dehumidifier_adviser.models import DailyHumidityData, HourlyHumidityData, HumidityForecast
from dehumidifier_adviser.weather import OpenMeteoClient

__version__ = "0.1.0"

__all__ = [
    "DailyHumidityData",
    "HourlyHumidityData",
    "HumidityForecast",
    "OpenMeteoClient",
]
