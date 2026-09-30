"""Humidity simulator API client."""

from typing import ClassVar

import httpx

from humidity_simulator_client.models import (
    OptimisationRequest,
    OptimisationResult,
    SimulationRequest,
    SimulationResult,
)


class SimulatorError(Exception):
    """Base exception for simulator API errors."""


class SimulatorConnectionError(SimulatorError):
    """Raised when unable to connect to the simulator API."""


class HumiditySimulatorClient:
    """Client for the humidity-simulator API."""

    DEFAULT_BASE_URL: ClassVar[str] = "http://localhost:8000"

    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"x-functions-key": self.api_key} if self.api_key else {}

    def _post(self, path: str, json: dict) -> httpx.Response:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}{path}", json=json, headers=self._headers())
            response.raise_for_status()
            return response
        except httpx.ConnectError as e:
            msg = f"Cannot connect to simulator API at {self.base_url}."
            raise SimulatorConnectionError(msg) from e
        except httpx.HTTPStatusError as e:
            msg = f"Simulator API error: {e.response.status_code} - {e.response.text}"
            raise SimulatorError(msg) from e
        except httpx.HTTPError as e:
            msg = f"HTTP error communicating with simulator: {e}"
            raise SimulatorError(msg) from e

    def simulate(self, request: SimulationRequest) -> SimulationResult:
        """Run a simulation and return the result."""
        response = self._post("/simulate", request.model_dump())
        return SimulationResult.model_validate(response.json())

    def optimise(self, request: OptimisationRequest) -> OptimisationResult:
        """Run the optimiser and return the final accepted schedule."""
        response = self._post("/optimisation", request.model_dump())
        return OptimisationResult.model_validate(response.json())
