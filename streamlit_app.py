"""Streamlit dashboard for dehumidifier humidity forecasting."""

import pandas as pd
import plotly.express as px
import streamlit as st

from dehumidifier_adviser import (
    Geocoder,
    GeocodingServiceError,
    HumidityForecast,
    Location,
    LocationNotFoundError,
    OpenMeteoClient,
)

# Page configuration
st.set_page_config(
    page_title="Dehumidifier Advisor",
    page_icon="🌧️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Default location (London, United Kingdom)
# Pre-cached to avoid unnecessary Nominatim API calls on initial page load
DEFAULT_LOCATION = Location(
    city="London",
    country="United Kingdom",
    state="England",
    latitude=51.5074,
    longitude=-0.1278,
    display_name="London, Greater London, England, United Kingdom",
)


def get_weather_icon_and_description(weather_code: int) -> tuple[str, str]:
    """Map Open-Meteo WMO weather code to emoji icon and description.

    Args:
        weather_code: WMO weather interpretation code (0-99)

    Returns:
        Tuple of (emoji_icon, description_text)

    WMO weather codes reference: https://open-meteo.com/en/docs
    """
    weather_mapping = {
        0: ("☀️", "Clear sky"),
        1: ("🌤️", "Mainly clear"),
        2: ("⛅", "Partly cloudy"),
        3: ("☁️", "Overcast"),
        45: ("🌫️", "Fog"),
        48: ("🌫️", "Depositing rime fog"),
        51: ("🌦️", "Light drizzle"),
        53: ("🌦️", "Moderate drizzle"),
        55: ("🌧️", "Dense drizzle"),
        56: ("🌧️", "Freezing drizzle (light)"),
        57: ("🌧️", "Freezing drizzle (dense)"),
        61: ("🌧️", "Slight rain"),
        63: ("🌧️", "Moderate rain"),
        65: ("🌧️", "Heavy rain"),
        66: ("🌧️", "Freezing rain (light)"),
        67: ("🌧️", "Freezing rain (heavy)"),
        71: ("🌨️", "Slight snow"),
        73: ("🌨️", "Moderate snow"),
        75: ("❄️", "Heavy snow"),
        77: ("🌨️", "Snow grains"),
        80: ("🌦️", "Slight rain showers"),
        81: ("🌧️", "Moderate rain showers"),
        82: ("🌧️", "Violent rain showers"),
        85: ("🌨️", "Slight snow showers"),
        86: ("🌨️", "Heavy snow showers"),
        95: ("⛈️", "Thunderstorm"),
        96: ("⛈️", "Thunderstorm with slight hail"),
        99: ("⛈️", "Thunderstorm with heavy hail"),
    }

    return weather_mapping.get(weather_code, ("❓", f"Unknown (code {weather_code})"))


@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_location_cached(city: str, country: str, state: str | None) -> Location:
    """Fetch and cache location data from geocoding API.

    Args:
        city: City name
        country: Country name
        state: Optional state/region name

    Returns:
        Location object with coordinates and address details

    Raises:
        LocationNotFoundError: If location cannot be found
        GeocodingServiceError: If service is unavailable
    """
    geocoder = Geocoder()
    return geocoder.forward_geocode(city=city, country=country, state=state)


@st.cache_data(ttl=1800)  # Cache for 30 minutes
def get_forecast_cached(latitude: float, longitude: float, forecast_days: int) -> HumidityForecast:
    """Fetch and cache humidity forecast data.

    Args:
        latitude: Location latitude coordinate
        longitude: Location longitude coordinate
        forecast_days: Number of forecast days (1-16)

    Returns:
        HumidityForecast object with hourly and daily data

    Raises:
        httpx.HTTPError: If API request fails
    """
    client = OpenMeteoClient()
    return client.get_humidity_forecast(
        latitude=latitude,
        longitude=longitude,
        forecast_days=forecast_days,
        hourly=["relative_humidity_2m"],
        daily=["relative_humidity_2m_mean", "relative_humidity_2m_max", "relative_humidity_2m_min"],
    )


@st.cache_data(ttl=600)  # Cache for 10 minutes
def get_current_conditions_cached(latitude: float, longitude: float) -> dict[str, float | int | None]:
    """Fetch and cache current weather conditions including temperature and weather code.

    Args:
        latitude: Location latitude coordinate
        longitude: Location longitude coordinate

    Returns:
        Dictionary with current conditions: temperature_2m, relative_humidity_2m, weather_code, time

    Raises:
        httpx.HTTPError: If API request fails
    """
    client = OpenMeteoClient()
    return client.get_current_conditions(latitude=latitude, longitude=longitude)


def plot_hourly_humidity(forecast: HumidityForecast) -> None:
    """Create and display hourly humidity line chart.

    Args:
        forecast: HumidityForecast object containing hourly data
    """
    if forecast.hourly is None:
        st.warning("⚠️ No hourly data available")
        return

    # Convert polars DataFrame to pandas for Plotly compatibility
    df = forecast.hourly.to_dataframe().to_pandas()

    # Create interactive line chart
    fig = px.line(
        df,
        x="time",
        y="relative_humidity_2m",
        title="Hourly Relative Humidity Forecast",
        labels={"time": "Time", "relative_humidity_2m": "Relative Humidity (%)"},
        markers=True,
    )

    # Customize layout
    fig.update_layout(
        hovermode="x unified",
        yaxis_range=[0, 100],  # Humidity is 0-100%
        template="plotly_white",
    )

    st.plotly_chart(fig, use_container_width=True)


def plot_daily_humidity(forecast: HumidityForecast) -> None:
    """Create and display daily humidity chart with min/max error bars.

    Args:
        forecast: HumidityForecast object containing daily data
    """
    if forecast.daily is None:
        st.warning("⚠️ No daily data available")
        return

    # Convert polars DataFrame to pandas for Plotly compatibility
    df = forecast.daily.to_dataframe().to_pandas()

    # Calculate error bars (distance from mean to min/max)
    df["error_minus"] = df["relative_humidity_2m_mean"] - df["relative_humidity_2m_min"]
    df["error_plus"] = df["relative_humidity_2m_max"] - df["relative_humidity_2m_mean"]

    # Create line chart with error bars
    fig = px.line(
        df,
        x="time",
        y="relative_humidity_2m_mean",
        title="Daily Relative Humidity Forecast",
        labels={"time": "Date", "relative_humidity_2m_mean": "Mean Relative Humidity (%)"},
        markers=True,
    )

    # Add error bars showing min/max range
    fig.update_traces(
        error_y={
            "type": "data",
            "symmetric": False,
            "array": df["error_plus"],
            "arrayminus": df["error_minus"],
        }
    )

    # Customize layout
    fig.update_layout(
        hovermode="x unified",
        yaxis_range=[0, 100],  # Humidity is 0-100%
        template="plotly_white",
    )

    st.plotly_chart(fig, use_container_width=True)


def get_location_to_display() -> Location | None:
    """Determine which location to display based on user input or default.

    Returns:
        Location object, or None if geocoding failed
    """
    if "location_input" in st.session_state:
        loc_input = st.session_state.location_input

        try:
            with st.spinner("🌍 Finding location..."):
                return get_location_cached(loc_input["city"], loc_input["country"], loc_input["state"])

        except LocationNotFoundError:
            st.error(
                f"🔍 **Location not found:** '{loc_input['city']}, {loc_input['country']}'\n\n"
                "**Suggestions:**\n"
                "- Check spelling of city and country names\n"
                "- Try using full country name (e.g., 'United Kingdom' not 'UK')\n"
                "- Add state/region for disambiguation (e.g., 'New York' state for 'New York' city)"
            )
            return None

        except GeocodingServiceError as e:
            st.error(
                f"🌐 **Geocoding service error:** {e}\n\n"
                "**Possible causes:**\n"
                "- Network connectivity issues\n"
                "- Service temporarily unavailable\n"
                "- Rate limit exceeded (1 request/second limit)\n\n"
                "**Try:** Wait a few seconds and try again."
            )

            if st.button("Clear Cache & Retry"):
                st.cache_data.clear()
                st.rerun()
            return None

        except Exception as e:  # noqa: BLE001
            st.error(f"❌ **Unexpected error:** {e}\n\nPlease try again or contact support if the issue persists.")
            return None

    # Use default location on initial page load
    return DEFAULT_LOCATION


def display_weather_data(location: Location, forecast_days: int, view_mode: str) -> None:
    """Display weather data for the given location.

    Args:
        location: Location object with coordinates and address
        forecast_days: Number of days to forecast
        view_mode: Display mode ("Hourly" or "Daily")
    """
    # Fetch current conditions once
    with st.spinner("Loading current conditions..."):
        current = get_current_conditions_cached(location.latitude, location.longitude)

    # Single header spanning both panels, centered
    st.markdown("<h3 style='text-align: center;'>Current Conditions</h3>", unsafe_allow_html=True)

    # Main layout: Map (50%) | Metrics Grid (50%)
    col_left, col_right = st.columns([1, 1])

    # Left column: Map with fixed height to match 2x2 grid
    with col_left:
        map_data = pd.DataFrame({"lat": [location.latitude], "lon": [location.longitude]})
        # Wrap map in a container with height matching the 2x2 grid (2 * 150px panels + spacing)
        st.markdown(
            """
            <style>
            .map-container iframe {
                height: 320px !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.map(map_data, zoom=10, height=320)

    # Right column: 2x2 Grid of metrics with borders
    with col_right:
        # Top row: Location and Humidity
        row1_col1, row1_col2 = st.columns([1, 1])

        with row1_col1:
            # Location box with border
            state_html = (
                f'<p style="font-size: 0.9em; font-style: italic; margin: 5px 0;">{location.state}</p>'
                if location.state
                else ""
            )
            st.markdown(
                f"""
                <div style="border: 2px solid #e0e0e0; border-radius: 8px; padding: 20px;
                            text-align: center; height: 150px; display: flex;
                            flex-direction: column; justify-content: center;">
                    <p style="font-size: 1.2em; font-weight: bold; margin: 5px 0;">{location.city}</p>
                    <p style="font-size: 1em; margin: 5px 0;">{location.country}</p>
                    {state_html}
                    <p style="font-size: 0.8em; color: #666; margin: 5px 0;">
                        {location.latitude:.4f}, {location.longitude:.4f}
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with row1_col2:
            # Humidity box with border
            humidity = current.get("relative_humidity_2m", "N/A")
            humidity_value = f"{humidity}%" if humidity != "N/A" else "N/A"
            st.markdown(
                f"""
                <div style="border: 2px solid #e0e0e0; border-radius: 8px; padding: 20px;
                            text-align: center; height: 150px; display: flex;
                            flex-direction: column; justify-content: center;">
                    <p style="font-size: 0.9em; color: #666; margin: 5px 0;">💧 Humidity</p>
                    <p style="font-size: 2em; font-weight: bold; margin: 5px 0;">{humidity_value}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Bottom row: Temperature and Weather
        row2_col1, row2_col2 = st.columns([1, 1])

        with row2_col1:
            # Temperature box with border
            temperature = current.get("temperature_2m", "N/A")
            temp_value = f"{temperature}°C" if temperature != "N/A" else "N/A"
            st.markdown(
                f"""
                <div style="border: 2px solid #e0e0e0; border-radius: 8px; padding: 20px;
                            text-align: center; height: 150px; display: flex;
                            flex-direction: column; justify-content: center;">
                    <p style="font-size: 0.9em; color: #666; margin: 5px 0;">🌡️ Temperature</p>
                    <p style="font-size: 2em; font-weight: bold; margin: 5px 0;">{temp_value}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with row2_col2:
            # Weather icon and description box with border
            weather_code = current.get("weather_code")
            if weather_code is not None:
                icon, description = get_weather_icon_and_description(int(weather_code))
                st.markdown(
                    f"""
                    <div style="border: 2px solid #e0e0e0; border-radius: 8px; padding: 20px;
                                text-align: center; height: 150px; display: flex;
                                flex-direction: column; justify-content: center;">
                        <p style="font-size: 3em; margin: 5px 0;">{icon}</p>
                        <p style="font-size: 1em; font-weight: bold; margin: 5px 0;">{description}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    """
                    <div style="border: 2px solid #e0e0e0; border-radius: 8px; padding: 20px;
                                text-align: center; height: 150px; display: flex;
                                flex-direction: column; justify-content: center;">
                        <p style="font-size: 0.9em; color: #666; margin: 5px 0;">☁️ Weather</p>
                        <p style="font-size: 2em; font-weight: bold; margin: 5px 0;">N/A</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Forecast section (full width below)
    st.divider()
    st.subheader("📊 Humidity Forecast")

    try:
        with st.spinner(f"Loading {forecast_days}-day forecast..."):
            forecast = get_forecast_cached(location.latitude, location.longitude, forecast_days)

        # Display appropriate chart based on view mode
        if view_mode == "Hourly":
            plot_hourly_humidity(forecast)
        else:
            plot_daily_humidity(forecast)

    except Exception as e:  # noqa: BLE001
        st.error(f"❌ **Weather data error:** {e}")


def main() -> None:
    """Main Streamlit application."""
    # Header
    st.title("Dehumidifier Advisor Dashboard")
    st.markdown("Get humidity forecasts for any location worldwide")

    # Sidebar settings
    with st.sidebar:
        st.header("⚙️ Forecast Settings")

        forecast_days = st.slider(
            "Forecast Duration (days)",
            min_value=1,
            max_value=16,
            value=7,
            help="Number of days to forecast (API limit: 1-16)",
        )

        view_mode = st.radio(
            "View Mode",
            options=["Hourly", "Daily"],
            index=0,
            help="Toggle between hourly and daily forecast views",
        )

        st.divider()
        st.markdown("### About")
        st.markdown(
            """
            This dashboard uses:
            - **OpenStreetMap Nominatim** for geocoding
            - **Open-Meteo API** for weather forecasts
            - **Relative Humidity (%)** as the primary metric

            Data is cached to improve performance and respect API rate limits.
            """
        )

    # Location input form
    with st.form("location_form"):
        st.subheader("🔍 Enter Location")

        col1, col2 = st.columns(2)
        with col1:
            city = st.text_input("City", placeholder="e.g., London")
        with col2:
            country = st.text_input("Country", placeholder="e.g., United Kingdom")

        state = st.text_input("State/Region (Optional)", placeholder="e.g., England")

        submit = st.form_submit_button("Get Forecast", use_container_width=True)

        if submit:
            if not city or not country:
                st.error("❌ Please enter both city and country")
            else:
                st.session_state.location_input = {
                    "city": city.strip(),
                    "country": country.strip(),
                    "state": state.strip() if state else None,
                }

    # Get location to display (default or user-specified)
    location = get_location_to_display()

    # Display weather data if location is available
    if location:
        display_weather_data(location, forecast_days, view_mode)


if __name__ == "__main__":
    main()
