"""Tests for the dehumidifier_adviser package."""

from dehumidifier_adviser import (
    DailyHumidityData,
    HourlyHumidityData,
    HumidityForecast,
    OpenMeteoClient,
)


def test_imports() -> None:
    """Test that all main exports are importable."""
    assert OpenMeteoClient is not None
    assert HumidityForecast is not None
    assert HourlyHumidityData is not None
    assert DailyHumidityData is not None


def test_client_initialization() -> None:
    """Test that OpenMeteoClient can be initialized."""
    client = OpenMeteoClient()
    assert client.timeout == 10.0

    client_with_timeout = OpenMeteoClient(timeout=20.0)
    assert client_with_timeout.timeout == 20.0
