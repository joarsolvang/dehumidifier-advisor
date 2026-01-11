"""Geocoding functionality using OpenStreetMap Nominatim service."""

from typing import ClassVar

from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim

from dehumidifier_adviser.models import Location


class GeocodingError(Exception):
    """Base exception for geocoding errors."""


class LocationNotFoundError(GeocodingError):
    """Raised when a location cannot be found."""


class GeocodingServiceError(GeocodingError):
    """Raised when the geocoding service is unavailable or times out."""


class Geocoder:
    """Geocoder for converting between addresses and coordinates.

    Uses OpenStreetMap's Nominatim service for geocoding. This is a free
    service with a usage limit of 1 request per second. For production use
    with higher volume, consider using a commercial geocoding service.

    Usage policy: https://operations.osmfoundation.org/policies/nominatim/
    """

    DEFAULT_USER_AGENT: ClassVar[str] = "dehumidifier-adviser"

    def __init__(
        self,
        user_agent: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the geocoder.

        Args:
            user_agent: User agent string for Nominatim requests. Should identify
                       your application. Defaults to "dehumidifier-adviser".
            timeout: Request timeout in seconds (default: 10.0)
        """
        self.timeout = timeout
        self._geocoder = Nominatim(
            user_agent=user_agent or self.DEFAULT_USER_AGENT,
            timeout=timeout,
        )

    def _validate_address_parameters(self, *, city: str, country: str) -> None:
        """Validate address parameters for forward geocoding.

        Args:
            city: City name to validate
            country: Country name to validate

        Raises:
            ValueError: If city or country is empty or contains only whitespace
        """
        if not city or not city.strip():
            raise ValueError("city cannot be empty")
        if not country or not country.strip():
            raise ValueError("country cannot be empty")

    def _validate_coordinates(self, *, latitude: float, longitude: float) -> None:
        """Validate coordinate values.

        Args:
            latitude: Latitude value to validate
            longitude: Longitude value to validate

        Raises:
            ValueError: If latitude is not in [-90, 90] or longitude is not in [-180, 180]
        """
        if not -90 <= latitude <= 90:
            raise ValueError(f"Latitude must be between -90 and 90, got {latitude}")
        if not -180 <= longitude <= 180:
            raise ValueError(f"Longitude must be between -180 and 180, got {longitude}")

    def forward_geocode(
        self,
        city: str,
        country: str,
        state: str | None = None,
    ) -> Location:
        """Convert address to coordinates (forward geocoding).

        Constructs a structured query and returns the first/best match from
        Nominatim. If multiple matches exist, the most relevant one (as
        determined by Nominatim's ranking) is returned.

        Args:
            city: City name (e.g., "London", "New York")
            country: Country name or ISO code (e.g., "United Kingdom", "GB")
            state: Optional state/province/region (e.g., "California", "NSW")

        Returns:
            Location object with coordinates and address details

        Raises:
            LocationNotFoundError: If the location cannot be found
            GeocodingServiceError: If the service is unavailable or times out
            ValueError: If required parameters are empty strings

        Example:
            >>> geocoder = Geocoder()
            >>> location = geocoder.forward_geocode(
            ...     city="London",
            ...     country="United Kingdom"
            ... )
            >>> print(f"{location.city}: {location.latitude}, {location.longitude}")
            London: 51.5074, -0.1278
        """
        # Validate inputs
        self._validate_address_parameters(city=city, country=country)

        # Build structured query
        query_parts = [city.strip(), country.strip()]
        if state and state.strip():
            query_parts.insert(1, state.strip())

        query = ", ".join(query_parts)

        try:
            # Perform geocoding
            result = self._geocoder.geocode(
                query,
                exactly_one=True,  # Return only the best match
                addressdetails=True,  # Get detailed address components
            )

            if result is None:
                raise LocationNotFoundError(
                    f"Location not found: {query}. Try different spellings or more specific details."
                )

            # Extract address components
            address = result.raw.get("address", {})
            extracted_city = address.get("city") or address.get("town") or address.get("village") or city  # Fallback
            extracted_country = address.get("country", country)
            extracted_state = address.get("state") or address.get("region") or state

            return Location(
                city=extracted_city,
                country=extracted_country,
                state=extracted_state,
                latitude=result.latitude,
                longitude=result.longitude,
                display_name=result.address,
            )

        except GeocoderTimedOut as e:
            raise GeocodingServiceError(f"Geocoding request timed out after {self.timeout}s: {e}") from e
        except GeocoderUnavailable as e:
            raise GeocodingServiceError(f"Geocoding service unavailable: {e}") from e

    def reverse_geocode(
        self,
        latitude: float,
        longitude: float,
    ) -> Location:
        """Convert coordinates to address (reverse geocoding).

        Args:
            latitude: Latitude coordinate (-90 to 90)
            longitude: Longitude coordinate (-180 to 180)

        Returns:
            Location object with address details and coordinates

        Raises:
            LocationNotFoundError: If no address found at coordinates
            GeocodingServiceError: If the service is unavailable or times out
            ValueError: If latitude/longitude are out of valid ranges

        Example:
            >>> geocoder = Geocoder()
            >>> location = geocoder.reverse_geocode(
            ...     latitude=51.5074,
            ...     longitude=-0.1278
            ... )
            >>> print(f"{location.city}, {location.country}")
            London, United Kingdom
        """
        # Validate coordinates
        self._validate_coordinates(latitude=latitude, longitude=longitude)

        try:
            result = self._geocoder.reverse(
                (latitude, longitude),
                exactly_one=True,
                addressdetails=True,
            )

            if result is None:
                raise LocationNotFoundError(f"No address found at coordinates: {latitude}, {longitude}")

            # Extract address components
            address = result.raw.get("address", {})
            city = (
                address.get("city")
                or address.get("town")
                or address.get("village")
                or address.get("municipality")
                or "Unknown"
            )
            country = address.get("country", "Unknown")
            state = address.get("state") or address.get("region")

            return Location(
                city=city,
                country=country,
                state=state,
                latitude=latitude,
                longitude=longitude,
                display_name=result.address,
            )

        except GeocoderTimedOut as e:
            raise GeocodingServiceError(f"Reverse geocoding request timed out after {self.timeout}s: {e}") from e
        except GeocoderUnavailable as e:
            raise GeocodingServiceError(f"Geocoding service unavailable: {e}") from e
