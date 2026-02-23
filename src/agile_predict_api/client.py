"""Agile Predict energy price forecast API client."""

import logging
from typing import ClassVar

import httpx

from agile_predict_api.models import EnergyForecast

logger = logging.getLogger(__name__)

_VALID_REGIONS: frozenset[str] = frozenset("ABCDEFGHJKLMNP")


class AgilePredictError(Exception):
    """Base exception for Agile Predict API errors."""


class AgilePredictClient:
    """Client for the Agile Predict energy price forecast API.

    Fetches forecasted Agile electricity prices by UK Grid Supply Point (GSP) region.

    Region codes:
        A = South East England
        B = East Midlands
        C = East England
        D = Merseyside & North Wales
        E = West Midlands
        F = North East England
        G = North West England
        H = Southern England
        J = South East England (second zone)
        K = South Wales
        L = South West England
        M = Yorkshire
        N = South Scotland
        P = North Scotland
    """

    BASE_URL: ClassVar[str] = "https://agilepredict.com/api"

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def get_forecast(
        self,
        region: str,
        *,
        days: int = 14,
        forecast_count: int = 1,
        high_low: bool = True,
    ) -> list[EnergyForecast]:
        """Fetch energy price forecasts for a GSP region.

        Args:
            region: Single-letter GSP region code (e.g. ``"G"`` for North West England).
            days: Number of days of data to retrieve (default: 14).
            forecast_count: Number of recent forecasts to fetch (default: 1).
            high_low: Whether to include high/low price estimates (default: True).

        Returns:
            List of :class:`EnergyForecast` objects, one per requested forecast.

        Raises:
            ValueError: If ``region`` is not a valid single-letter GSP code.
            AgilePredictError: If the API request fails due to a network or HTTP error.
        """
        region = region.upper()
        if region not in _VALID_REGIONS:
            msg = f"Invalid region '{region}'. Must be one of: {sorted(_VALID_REGIONS)}"
            raise ValueError(msg)

        url = f"{self.BASE_URL}/{region}"
        params: dict[str, str] = {
            "days": str(days),
            "forecast_count": str(forecast_count),
            "high_low": str(high_low),
        }

        logger.info(
            "Fetching Agile Predict forecast for region=%s days=%d forecast_count=%d", region, days, forecast_count
        )

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data: list[dict[str, object]] = response.json()
                logger.debug("Received %d forecast(s) for region %s", len(data), region)
                return [EnergyForecast.model_validate(f) for f in data]
        except httpx.ConnectError as e:
            msg = f"Cannot connect to Agile Predict API: {e}"
            logger.error(msg)
            raise AgilePredictError(msg) from e
        except httpx.HTTPStatusError as e:
            msg = f"Agile Predict API error: {e.response.status_code} - {e.response.text}"
            logger.error(msg)
            raise AgilePredictError(msg) from e
        except httpx.HTTPError as e:
            msg = f"HTTP error communicating with Agile Predict API: {e}"
            logger.error(msg)
            raise AgilePredictError(msg) from e
