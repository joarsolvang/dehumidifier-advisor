"""Humidity simulator API client package."""

from dehumidifier_adviser.scenarios import PRESET_FACTORIES
from humidity_simulator_client.client import (
    HumiditySimulatorClient,
    SimulatorConnectionError,
    SimulatorError,
)
from humidity_simulator_client.models import (
    HumiditySource,
    SimulationRequest,
    SimulationResult,
)

__all__ = [
    "PRESET_FACTORIES",
    "HumiditySimulatorClient",
    "HumiditySource",
    "SimulationRequest",
    "SimulationResult",
    "SimulatorConnectionError",
    "SimulatorError",
]
