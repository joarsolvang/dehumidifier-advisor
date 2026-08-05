"""Humidity simulator API client."""

import time
from typing import ClassVar

import httpx

from humidity_simulator_client.models import (
    OptimisationRequest,
    SimulationRequest,
    SimulationResult,
    StepsResponse,
)

_POLL_INTERVAL = 0.5


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
        """Submit a simulation job and poll until complete, then return the result."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                job_id = self._submit_job(client, request)
                return self._poll_result(client, job_id)
        except httpx.ConnectError as e:
            msg = f"Cannot connect to simulator API at {self.base_url}. Is the container running?"
            raise SimulatorConnectionError(msg) from e
        except httpx.HTTPStatusError as e:
            msg = f"Simulator API error: {e.response.status_code} - {e.response.text}"
            raise SimulatorError(msg) from e
        except httpx.HTTPError as e:
            msg = f"HTTP error communicating with simulator: {e}"
            raise SimulatorError(msg) from e

    def _submit_job(self, client: httpx.Client, request: SimulationRequest) -> str:
        response = client.post(
            f"{self.base_url}/simulate/jobs",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return response.json()["job_id"]  # type: ignore[no-any-return]

    def submit_optimisation(self, request: OptimisationRequest) -> str:
        """Submit an optimisation job and return the job ID."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/optimisation/jobs",
                    json=request.model_dump(),
                )
                response.raise_for_status()
                return response.json()["job_id"]  # type: ignore[no-any-return]
        except httpx.ConnectError as e:
            msg = f"Cannot connect to simulator API at {self.base_url}. Is the container running?"
            raise SimulatorConnectionError(msg) from e
        except httpx.HTTPStatusError as e:
            msg = f"Simulator API error: {e.response.status_code} - {e.response.text}"
            raise SimulatorError(msg) from e
        except httpx.HTTPError as e:
            msg = f"HTTP error communicating with simulator: {e}"
            raise SimulatorError(msg) from e

    def get_optimisation_steps(self, job_id: str, from_index: int = 0) -> StepsResponse:
        """Fetch optimisation steps from a given index."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    f"{self.base_url}/optimisation/jobs/{job_id}/steps",
                    params={"from_index": from_index},
                )
                response.raise_for_status()
                return StepsResponse.model_validate(response.json())
        except httpx.ConnectError as e:
            msg = f"Cannot connect to simulator API at {self.base_url}. Is the container running?"
            raise SimulatorConnectionError(msg) from e
        except httpx.HTTPStatusError as e:
            msg = f"Simulator API error: {e.response.status_code} - {e.response.text}"
            raise SimulatorError(msg) from e
        except httpx.HTTPError as e:
            msg = f"HTTP error communicating with simulator: {e}"
            raise SimulatorError(msg) from e

    def _poll_result(self, client: httpx.Client, job_id: str) -> SimulationResult:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            response = client.get(f"{self.base_url}/simulate/jobs/{job_id}/result")
            if response.status_code == 404:
                # Worker hasn't picked up the job yet — retry
                time.sleep(_POLL_INTERVAL)
                continue
            response.raise_for_status()
            data = response.json()

            if data["status"] == "complete":
                return SimulationResult.model_validate(data["result"])
            if data["status"] == "error":
                raise SimulatorError(f"Simulation job failed: {data.get('error', 'Unknown error')}")

            time.sleep(_POLL_INTERVAL)

        raise SimulatorError(f"Simulation job {job_id!r} timed out after {self.timeout}s")
