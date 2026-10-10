"""Tests for GSP region lookup."""

import json
from pathlib import Path

import pytest

from dehumidifier_adviser.gsp import LocationOutsideGridSupplyAreaError, find_gsp, require_gsp

GSP_REGIONS = json.loads((Path(__file__).parent.parent / "data" / "gsp_regions.geojson").read_text())


@pytest.mark.parametrize(
    ("place", "latitude", "longitude", "expected"),
    [
        ("Norwich", 52.6309, 1.2974, "A"),
        ("Nottingham", 52.9548, -1.1581, "B"),
        ("London", 51.5074, -0.1278, "C"),
        ("Liverpool", 53.4084, -2.9916, "D"),
        ("Birmingham", 52.4862, -1.8904, "E"),
        ("Newcastle", 54.9783, -1.6178, "F"),
        ("Manchester", 53.4808, -2.2426, "G"),
        ("Southampton", 50.9097, -1.4044, "H"),
        ("Brighton", 50.8225, -0.1372, "J"),
        ("Cardiff", 51.4816, -3.1791, "K"),
        ("Plymouth", 50.3755, -4.1427, "L"),
        ("Leeds", 53.8008, -1.5491, "M"),
        ("Glasgow", 55.8642, -4.2518, "N"),
        ("Inverness", 57.4778, -4.2247, "P"),
    ],
)
def test_find_gsp_for_uk_cities(place: str, latitude: float, longitude: float, expected: str) -> None:
    """Each region letter is found for a city inside it."""
    assert find_gsp(latitude, longitude, GSP_REGIONS) == expected, place


@pytest.mark.parametrize(
    ("place", "latitude", "longitude"),
    [
        ("Paris", 48.8566, 2.3522),
        ("Belfast", 54.5973, -5.9301),
        ("Oslo", 59.9139, 10.7522),
    ],
)
def test_find_gsp_outside_regions(place: str, latitude: float, longitude: float) -> None:
    """Locations outside Great Britain have no GSP region."""
    assert find_gsp(latitude, longitude, GSP_REGIONS) is None, place


def test_require_gsp_returns_region_inside_gb() -> None:
    """require_gsp returns the region letter for a location in Great Britain."""
    assert require_gsp(51.5074, -0.1278, GSP_REGIONS) == "C"


def test_require_gsp_raises_outside_gb() -> None:
    """require_gsp raises for a location outside Great Britain."""
    with pytest.raises(LocationOutsideGridSupplyAreaError, match="England, Scotland and Wales"):
        require_gsp(59.9139, 10.7522, GSP_REGIONS)
