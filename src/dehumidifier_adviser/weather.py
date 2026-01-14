"""Open-Meteo API client for humidity forecasting."""

from typing import Any, ClassVar

import httpx

from dehumidifier_adviser.models import HumidityForecast


class OpenMeteoClient:
    """Client for accessing Open-Meteo weather forecasting API.

    This client focuses on retrieving humidity-related weather parameters
    including relative humidity, dew point, vapour pressure deficit, and
    soil moisture data.
    """

    BASE_URL: ClassVar[str] = "https://api.open-meteo.com/v1/forecast"

    # All available hourly humidity-related parameters
    HOURLY_HUMIDITY_PARAMS: ClassVar[list[str]] = [
        "relative_humidity_2m",
        "dew_point_2m",
        "vapour_pressure_deficit",
    ]

    # All available daily humidity-related parameters
    DAILY_HUMIDITY_PARAMS: ClassVar[list[str]] = [
        "relative_humidity_2m_mean",
        "relative_humidity_2m_max",
        "relative_humidity_2m_min",
        "dew_point_2m_mean",
        "dew_point_2m_max",
        "dew_point_2m_min",
    ]

    # Current weather parameters (temperature, humidity, weather code)
    CURRENT_WEATHER_PARAMS: ClassVar[list[str]] = [
        "temperature_2m",
        "relative_humidity_2m",
        "weather_code",
    ]

    def __init__(self, timeout: float = 10.0) -> None:
        """Initialize the Open-Meteo client.

        Args:
            timeout: Request timeout in seconds (default: 10.0)
        """
        self.timeout = timeout

    def get_humidity_forecast(
        self,
        latitude: float,
        longitude: float,
        *,
        hourly: list[str] | None = None,
        daily: list[str] | None = None,
        past_days: int = 0,
        forecast_days: int = 7,
        timezone: str = "auto",
    ) -> HumidityForecast:
        """Fetch humidity forecast for a specific location.

        Args:
            latitude: Location latitude (-90 to 90)
            longitude: Location longitude (-180 to 180)
            hourly: List of hourly parameters to fetch. If None, fetches all humidity parameters.
            daily: List of daily parameters to fetch. If None, fetches all humidity parameters.
            past_days: Number of past days to include (0-92, default: 0)
            forecast_days: Number of forecast days (1-16, default: 7)
            timezone: Timezone for timestamps (default: "auto")

        Returns:
            HumidityForecast object containing the requested data

        Raises:
            httpx.HTTPError: If the API request fails
            ValueError: If latitude/longitude are out of valid ranges
        """
        if not -90 <= latitude <= 90:
            raise ValueError(f"Latitude must be between -90 and 90, got {latitude}")
        if not -180 <= longitude <= 180:
            raise ValueError(f"Longitude must be between -180 and 180, got {longitude}")

        # Use all humidity parameters if none specified
        hourly_params = hourly if hourly is not None else self.HOURLY_HUMIDITY_PARAMS
        daily_params = daily if daily is not None else self.DAILY_HUMIDITY_PARAMS

        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": timezone,
            "past_days": past_days,
            "forecast_days": forecast_days,
        }

        if hourly_params:
            params["hourly"] = ",".join(hourly_params)
        if daily_params:
            params["daily"] = ",".join(daily_params)

        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        return HumidityForecast.model_validate(data)

    def get_current_humidity(
        self, latitude: float, longitude: float, *, timezone: str = "auto"
    ) -> dict[str, float | None]:
        """Get current humidity conditions for a location.

        Fetches the most recent hourly humidity data.

        Args:
            latitude: Location latitude (-90 to 90)
            longitude: Location longitude (-180 to 180)
            timezone: Timezone for timestamps (default: "auto")

        Returns:
            Dictionary with current humidity measurements

        Raises:
            httpx.HTTPError: If the API request fails
            ValueError: If latitude/longitude are out of valid ranges
        """
        forecast = self.get_humidity_forecast(
            latitude=latitude,
            longitude=longitude,
            hourly=self.HOURLY_HUMIDITY_PARAMS,
            daily=None,
            past_days=1,
            forecast_days=1,
            timezone=timezone,
        )

        if forecast.hourly is None or not forecast.hourly.time:
            return {}

        # Get the most recent (last) data point
        current: dict[str, float | None] = {}
        last_index = -1

        if forecast.hourly.relative_humidity_2m:
            current["relative_humidity_2m"] = forecast.hourly.relative_humidity_2m[last_index]
        if forecast.hourly.dew_point_2m:
            current["dew_point_2m"] = forecast.hourly.dew_point_2m[last_index]
        if forecast.hourly.vapour_pressure_deficit:
            current["vapour_pressure_deficit"] = forecast.hourly.vapour_pressure_deficit[last_index]

        return current

    def get_current_conditions(
        self, latitude: float, longitude: float, *, timezone: str = "auto"
    ) -> dict[str, float | int | None]:
        """Get current weather conditions including temperature, humidity, and weather code.

        Uses the Open-Meteo 'current' parameter for efficient real-time data retrieval.

        Args:
            latitude: Location latitude (-90 to 90)
            longitude: Location longitude (-180 to 180)
            timezone: Timezone for timestamps (default: "auto")

        Returns:
            Dictionary with current conditions:
            - temperature_2m: Temperature in °C
            - relative_humidity_2m: Humidity in %
            - weather_code: WMO weather interpretation code (0-99)
            - time: Timestamp of measurement

        Raises:
            httpx.HTTPError: If the API request fails
            ValueError: If latitude/longitude are out of valid ranges
        """
        if not -90 <= latitude <= 90:
            raise ValueError(f"Latitude must be between -90 and 90, got {latitude}")
        if not -180 <= longitude <= 180:
            raise ValueError(f"Longitude must be between -180 and 180, got {longitude}")

        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "current": ",".join(self.CURRENT_WEATHER_PARAMS),
            "timezone": timezone,
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        # Extract current weather data from response
        current_data = data.get("current", {})

        result: dict[str, float | int | None] = {
            "temperature_2m": current_data.get("temperature_2m"),
            "relative_humidity_2m": current_data.get("relative_humidity_2m"),
            "weather_code": current_data.get("weather_code"),
            "time": current_data.get("time"),
        }

        return result
