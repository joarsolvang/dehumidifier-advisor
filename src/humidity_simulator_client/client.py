"""Humidity simulator API client."""

from typing import ClassVar

import httpx

from humidity_simulator_client.models import SimulationRequest, SimulationResult


class SimulatorError(Exception):
    """Base exception for simulator API errors."""


class SimulatorConnectionError(SimulatorError):
    """Raised when unable to connect to the simulator API."""


class HumiditySimulatorClient:
    """Client for the humidity-simulator API."""

    DEFAULT_BASE_URL: ClassVar[str] = "http://localhost:8000"

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def simulate(self, request: SimulationRequest) -> SimulationResult:
        """Run a humidity simulation via the API."""
        url = f"{self.base_url}/simulate"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, json=request.model_dump())
                response.raise_for_status()
                return SimulationResult.model_validate(response.json())
        except httpx.ConnectError as e:
            msg = f"Cannot connect to simulator API at {self.base_url}. Is the container running?"
            raise SimulatorConnectionError(msg) from e
        except httpx.HTTPStatusError as e:
            msg = f"Simulator API error: {e.response.status_code} - {e.response.text}"
            raise SimulatorError(msg) from e
        except httpx.HTTPError as e:
            msg = f"HTTP error communicating with simulator: {e}"
            raise SimulatorError(msg) from e
