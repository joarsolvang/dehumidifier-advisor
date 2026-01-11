"""Tests for geocoding functionality."""

from unittest.mock import Mock, patch

import pytest
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

from dehumidifier_adviser import (
    Geocoder,
    GeocodingServiceError,
    Location,
    LocationNotFoundError,
)


class TestLocation:
    """Tests for Location model."""

    def test_valid_location(self) -> None:
        """Test creating a valid Location."""
        location = Location(
            city="London",
            country="United Kingdom",
            latitude=51.5074,
            longitude=-0.1278,
        )
        assert location.city == "London"
        assert location.country == "United Kingdom"
        assert location.state is None
        assert location.latitude == 51.5074
        assert location.longitude == -0.1278

    def test_location_with_state(self) -> None:
        """Test creating a Location with state."""
        location = Location(
            city="New York",
            country="United States",
            state="New York",
            latitude=40.7128,
            longitude=-74.0060,
        )
        assert location.state == "New York"

    def test_latitude_validation_too_high(self) -> None:
        """Test latitude validation rejects values > 90."""
        with pytest.raises(ValueError, match="Latitude must be between"):
            Location(
                city="Test",
                country="Test",
                latitude=91.0,
                longitude=0.0,
            )

    def test_latitude_validation_too_low(self) -> None:
        """Test latitude validation rejects values < -90."""
        with pytest.raises(ValueError, match="Latitude must be between"):
            Location(
                city="Test",
                country="Test",
                latitude=-91.0,
                longitude=0.0,
            )

    def test_longitude_validation_too_high(self) -> None:
        """Test longitude validation rejects values > 180."""
        with pytest.raises(ValueError, match="Longitude must be between"):
            Location(
                city="Test",
                country="Test",
                latitude=0.0,
                longitude=181.0,
            )

    def test_longitude_validation_too_low(self) -> None:
        """Test longitude validation rejects values < -180."""
        with pytest.raises(ValueError, match="Longitude must be between"):
            Location(
                city="Test",
                country="Test",
                latitude=0.0,
                longitude=-181.0,
            )

    def test_location_with_display_name(self) -> None:
        """Test creating a Location with display_name."""
        location = Location(
            city="London",
            country="United Kingdom",
            latitude=51.5074,
            longitude=-0.1278,
            display_name="London, Greater London, England, United Kingdom",
        )
        assert location.display_name == "London, Greater London, England, United Kingdom"


class TestGeocoderValidation:
    """Tests for Geocoder validation methods."""

    def test_validate_address_parameters_valid(self) -> None:
        """Test that valid address parameters pass validation."""
        geocoder = Geocoder()
        # Should not raise any exception
        geocoder._validate_address_parameters(city="London", country="UK")

    def test_validate_address_parameters_empty_city(self) -> None:
        """Test validation rejects empty city."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="city cannot be empty"):
            geocoder._validate_address_parameters(city="", country="UK")

    def test_validate_address_parameters_whitespace_city(self) -> None:
        """Test validation rejects whitespace-only city."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="city cannot be empty"):
            geocoder._validate_address_parameters(city="   ", country="UK")

    def test_validate_address_parameters_empty_country(self) -> None:
        """Test validation rejects empty country."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="country cannot be empty"):
            geocoder._validate_address_parameters(city="London", country="")

    def test_validate_address_parameters_whitespace_country(self) -> None:
        """Test validation rejects whitespace-only country."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="country cannot be empty"):
            geocoder._validate_address_parameters(city="London", country="   ")

    def test_validate_coordinates_valid(self) -> None:
        """Test that valid coordinates pass validation."""
        geocoder = Geocoder()
        # Should not raise any exception
        geocoder._validate_coordinates(latitude=51.5074, longitude=-0.1278)

    def test_validate_coordinates_boundary_values(self) -> None:
        """Test that boundary coordinate values pass validation."""
        geocoder = Geocoder()
        # Test extreme valid values
        geocoder._validate_coordinates(latitude=90.0, longitude=180.0)
        geocoder._validate_coordinates(latitude=-90.0, longitude=-180.0)
        geocoder._validate_coordinates(latitude=0.0, longitude=0.0)

    def test_validate_coordinates_latitude_too_high(self) -> None:
        """Test validation rejects latitude > 90."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match=r"Latitude must be between -90 and 90, got 91\.0"):
            geocoder._validate_coordinates(latitude=91.0, longitude=0.0)

    def test_validate_coordinates_latitude_too_low(self) -> None:
        """Test validation rejects latitude < -90."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match=r"Latitude must be between -90 and 90, got -91\.0"):
            geocoder._validate_coordinates(latitude=-91.0, longitude=0.0)

    def test_validate_coordinates_longitude_too_high(self) -> None:
        """Test validation rejects longitude > 180."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match=r"Longitude must be between -180 and 180, got 181\.0"):
            geocoder._validate_coordinates(latitude=0.0, longitude=181.0)

    def test_validate_coordinates_longitude_too_low(self) -> None:
        """Test validation rejects longitude < -180."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match=r"Longitude must be between -180 and 180, got -181\.0"):
            geocoder._validate_coordinates(latitude=0.0, longitude=-181.0)

    def test_validate_coordinates_with_extreme_precision(self) -> None:
        """Test validation handles coordinates with high precision."""
        geocoder = Geocoder()
        # Should handle high-precision coordinates without issues
        geocoder._validate_coordinates(latitude=51.50740123456789, longitude=-0.12780987654321)


class TestGeocoder:
    """Tests for Geocoder class."""

    def test_initialization_default(self) -> None:
        """Test Geocoder initialization with defaults."""
        geocoder = Geocoder()
        assert geocoder.timeout == 10.0

    def test_initialization_custom_timeout(self) -> None:
        """Test Geocoder initialization with custom timeout."""
        geocoder = Geocoder(timeout=20.0)
        assert geocoder.timeout == 20.0

    def test_initialization_custom_user_agent(self) -> None:
        """Test Geocoder initialization with custom user agent."""
        geocoder = Geocoder(user_agent="test-app/1.0")
        assert geocoder.timeout == 10.0

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_forward_geocode_success(self, mock_nominatim: Mock) -> None:
        """Test successful forward geocoding."""
        # Setup mock
        mock_result = Mock()
        mock_result.latitude = 51.5074
        mock_result.longitude = -0.1278
        mock_result.address = "London, Greater London, England, United Kingdom"
        mock_result.raw = {"address": {"city": "London", "country": "United Kingdom"}}
        mock_nominatim.return_value.geocode.return_value = mock_result

        # Test
        geocoder = Geocoder()
        location = geocoder.forward_geocode(city="London", country="UK")

        assert location.city == "London"
        assert location.country == "United Kingdom"
        assert location.latitude == 51.5074
        assert location.longitude == -0.1278
        assert location.display_name == "London, Greater London, England, United Kingdom"

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_forward_geocode_with_state(self, mock_nominatim: Mock) -> None:
        """Test forward geocoding with state parameter."""
        # Setup mock
        mock_result = Mock()
        mock_result.latitude = 40.7128
        mock_result.longitude = -74.0060
        mock_result.address = "New York, NY, USA"
        mock_result.raw = {"address": {"city": "New York", "state": "New York", "country": "United States"}}
        mock_nominatim.return_value.geocode.return_value = mock_result

        # Test
        geocoder = Geocoder()
        location = geocoder.forward_geocode(city="New York", country="United States", state="New York")

        assert location.city == "New York"
        assert location.state == "New York"
        assert location.country == "United States"

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_forward_geocode_fallback_to_town(self, mock_nominatim: Mock) -> None:
        """Test forward geocoding falls back to 'town' when 'city' not available."""
        # Setup mock
        mock_result = Mock()
        mock_result.latitude = 50.0
        mock_result.longitude = 0.0
        mock_result.address = "Small Town, Country"
        mock_result.raw = {"address": {"town": "Small Town", "country": "Country"}}
        mock_nominatim.return_value.geocode.return_value = mock_result

        # Test
        geocoder = Geocoder()
        location = geocoder.forward_geocode(city="Small Town", country="Country")

        assert location.city == "Small Town"

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_forward_geocode_not_found(self, mock_nominatim: Mock) -> None:
        """Test forward geocoding when location not found."""
        mock_nominatim.return_value.geocode.return_value = None

        geocoder = Geocoder()
        with pytest.raises(LocationNotFoundError, match="Location not found"):
            geocoder.forward_geocode(city="NonexistentCity", country="Nowhere")

    def test_forward_geocode_empty_city(self) -> None:
        """Test forward geocoding with empty city."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="city cannot be empty"):
            geocoder.forward_geocode(city="", country="UK")

    def test_forward_geocode_whitespace_city(self) -> None:
        """Test forward geocoding with whitespace-only city."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="city cannot be empty"):
            geocoder.forward_geocode(city="   ", country="UK")

    def test_forward_geocode_empty_country(self) -> None:
        """Test forward geocoding with empty country."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="country cannot be empty"):
            geocoder.forward_geocode(city="London", country="")

    def test_forward_geocode_whitespace_country(self) -> None:
        """Test forward geocoding with whitespace-only country."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="country cannot be empty"):
            geocoder.forward_geocode(city="London", country="   ")

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_forward_geocode_timeout(self, mock_nominatim: Mock) -> None:
        """Test forward geocoding timeout."""
        mock_nominatim.return_value.geocode.side_effect = GeocoderTimedOut()

        geocoder = Geocoder()
        with pytest.raises(GeocodingServiceError, match="timed out"):
            geocoder.forward_geocode(city="London", country="UK")

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_forward_geocode_service_unavailable(self, mock_nominatim: Mock) -> None:
        """Test forward geocoding when service unavailable."""
        mock_nominatim.return_value.geocode.side_effect = GeocoderUnavailable()

        geocoder = Geocoder()
        with pytest.raises(GeocodingServiceError, match="service unavailable"):
            geocoder.forward_geocode(city="London", country="UK")

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_reverse_geocode_success(self, mock_nominatim: Mock) -> None:
        """Test successful reverse geocoding."""
        # Setup mock
        mock_result = Mock()
        mock_result.address = "London, Greater London, England, United Kingdom"
        mock_result.raw = {"address": {"city": "London", "country": "United Kingdom", "state": "England"}}
        mock_nominatim.return_value.reverse.return_value = mock_result

        # Test
        geocoder = Geocoder()
        location = geocoder.reverse_geocode(latitude=51.5074, longitude=-0.1278)

        assert location.city == "London"
        assert location.country == "United Kingdom"
        assert location.state == "England"
        assert location.latitude == 51.5074
        assert location.longitude == -0.1278

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_reverse_geocode_fallback_to_town(self, mock_nominatim: Mock) -> None:
        """Test reverse geocoding falls back to town/village when city not available."""
        # Setup mock
        mock_result = Mock()
        mock_result.address = "Small Village, Country"
        mock_result.raw = {"address": {"village": "Small Village", "country": "Country"}}
        mock_nominatim.return_value.reverse.return_value = mock_result

        # Test
        geocoder = Geocoder()
        location = geocoder.reverse_geocode(latitude=50.0, longitude=0.0)

        assert location.city == "Small Village"

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_reverse_geocode_unknown_fallback(self, mock_nominatim: Mock) -> None:
        """Test reverse geocoding falls back to 'Unknown' when no city-like field available."""
        # Setup mock
        mock_result = Mock()
        mock_result.address = "Some Address"
        mock_result.raw = {"address": {"road": "Some Road"}}
        mock_nominatim.return_value.reverse.return_value = mock_result

        # Test
        geocoder = Geocoder()
        location = geocoder.reverse_geocode(latitude=50.0, longitude=0.0)

        assert location.city == "Unknown"
        assert location.country == "Unknown"

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_reverse_geocode_not_found(self, mock_nominatim: Mock) -> None:
        """Test reverse geocoding when no address found."""
        mock_nominatim.return_value.reverse.return_value = None

        geocoder = Geocoder()
        with pytest.raises(LocationNotFoundError, match="No address found at coordinates"):
            geocoder.reverse_geocode(latitude=0.0, longitude=0.0)

    def test_reverse_geocode_invalid_latitude_too_high(self) -> None:
        """Test reverse geocoding with invalid latitude (too high)."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="Latitude must be between"):
            geocoder.reverse_geocode(latitude=91.0, longitude=0.0)

    def test_reverse_geocode_invalid_latitude_too_low(self) -> None:
        """Test reverse geocoding with invalid latitude (too low)."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="Latitude must be between"):
            geocoder.reverse_geocode(latitude=-91.0, longitude=0.0)

    def test_reverse_geocode_invalid_longitude_too_high(self) -> None:
        """Test reverse geocoding with invalid longitude (too high)."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="Longitude must be between"):
            geocoder.reverse_geocode(latitude=0.0, longitude=181.0)

    def test_reverse_geocode_invalid_longitude_too_low(self) -> None:
        """Test reverse geocoding with invalid longitude (too low)."""
        geocoder = Geocoder()
        with pytest.raises(ValueError, match="Longitude must be between"):
            geocoder.reverse_geocode(latitude=0.0, longitude=-181.0)

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_reverse_geocode_timeout(self, mock_nominatim: Mock) -> None:
        """Test reverse geocoding timeout."""
        mock_nominatim.return_value.reverse.side_effect = GeocoderTimedOut()

        geocoder = Geocoder()
        with pytest.raises(GeocodingServiceError, match="timed out"):
            geocoder.reverse_geocode(latitude=51.5074, longitude=-0.1278)

    @patch("dehumidifier_adviser.geocoding.Nominatim")
    def test_reverse_geocode_service_unavailable(self, mock_nominatim: Mock) -> None:
        """Test reverse geocoding when service unavailable."""
        mock_nominatim.return_value.reverse.side_effect = GeocoderUnavailable()

        geocoder = Geocoder()
        with pytest.raises(GeocodingServiceError, match="service unavailable"):
            geocoder.reverse_geocode(latitude=51.5074, longitude=-0.1278)
