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
def get_current_humidity_cached(latitude: float, longitude: float) -> dict[str, float | None]:
    """Fetch and cache current humidity conditions.

    Args:
        latitude: Location latitude coordinate
        longitude: Location longitude coordinate

    Returns:
        Dictionary with current humidity data

    Raises:
        httpx.HTTPError: If API request fails
    """
    client = OpenMeteoClient()
    return client.get_current_humidity(latitude=latitude, longitude=longitude)


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


def main() -> None:
    """Main Streamlit application."""
    # Add custom CSS for sticky header
    st.markdown(
        """
        <style>
        /* Make title sticky */
        [data-testid="stHeader"] {
            position: sticky;
            top: 0;
            z-index: 999;
            background-color: white;
        }
        /* Add slight shadow to sticky header */
        [data-testid="stHeader"]::after {
            content: "";
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 1px;
            background: linear-gradient(to bottom, rgba(0,0,0,0.1), transparent);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Header
    st.title("🌧️ Dehumidifier Advisor Dashboard")
    st.markdown("Get humidity forecasts for any location worldwide")

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

    # Display results if location has been submitted
    if "location_input" in st.session_state:
        loc_input = st.session_state.location_input

        try:
            # Get location with spinner
            with st.spinner("🌍 Finding location..."):
                location = get_location_cached(loc_input["city"], loc_input["country"], loc_input["state"])

            # Display map and current conditions side by side
            map_col, conditions_col = st.columns(2)

            with map_col:
                st.subheader("📍 Location")
                map_data = pd.DataFrame({"lat": [location.latitude], "lon": [location.longitude]})
                st.map(map_data, zoom=10)

            with conditions_col:
                st.subheader("💧 Current Conditions")

                with st.spinner("Loading current conditions..."):
                    current = get_current_humidity_cached(location.latitude, location.longitude)
                humidity = current.get("relative_humidity_2m", "N/A")

                # Display humidity metric prominently
                st.metric("Relative Humidity", f"{humidity}%" if humidity != "N/A" else "N/A")

                # Location details
                st.write(f"**Location:** {location.city}, {location.country}")
                if location.state:
                    st.write(f"**Region:** {location.state}")

                # Coordinates
                st.write(f"**Coordinates:** {location.latitude:.4f}, {location.longitude:.4f}")

            # Forecast section with settings
            st.subheader("📊 Humidity Forecast")

            # Forecast settings (moved from sidebar)
            settings_col1, settings_col2 = st.columns([2, 1])

            with settings_col1:
                forecast_days = st.slider(
                    "Forecast Duration (days)",
                    min_value=1,
                    max_value=16,
                    value=7,
                    help="Number of days to forecast (API limit: 1-16)",
                )

            with settings_col2:
                view_mode = st.radio(
                    "View Mode",
                    options=["Hourly", "Daily"],
                    index=0,
                    help="Toggle between hourly and daily forecast views",
                    horizontal=True,
                )

            # Load and display forecast
            with st.spinner(f"Loading {forecast_days}-day forecast..."):
                forecast = get_forecast_cached(location.latitude, location.longitude, forecast_days)

            # Display appropriate chart based on view mode
            if view_mode == "Hourly":
                plot_hourly_humidity(forecast)
            else:
                plot_daily_humidity(forecast)

        except LocationNotFoundError:
            st.error(
                f"🔍 **Location not found:** '{loc_input['city']}, {loc_input['country']}'\n\n"
                "**Suggestions:**\n"
                "- Check spelling of city and country names\n"
                "- Try using full country name (e.g., 'United Kingdom' not 'UK')\n"
                "- Add state/region for disambiguation (e.g., 'New York' state for 'New York' city)"
            )

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

        except Exception as e:  # noqa: BLE001
            st.error(f"❌ **Unexpected error:** {e}\n\nPlease try again or contact support if the issue persists.")

    # Footer
    st.divider()
    st.markdown(
        """
        <div style='text-align: center; padding: 2rem 0 1rem 0; color: #666;'>
            <h4>About This Dashboard</h4>
            <p>
                This dashboard uses <strong>OpenStreetMap Nominatim</strong> for geocoding and
                <strong>Open-Meteo API</strong> for weather forecasts.
                All humidity data represents <strong>Relative Humidity (%)</strong>.
            </p>
            <p style='font-size: 0.9em; margin-top: 1rem;'>
                Data is cached to improve performance and respect API rate limits.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
