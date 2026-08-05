"""Streamlit dashboard for dehumidifier humidity forecasting."""

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from agile_predict_api import AgilePredictClient, AgilePredictError, EnergyForecast, EnergyForecastTimeSeries
from dehumidifier_adviser import (
    Geocoder,
    GeocodingServiceError,
    HumidityForecast,
    Location,
    LocationNotFoundError,
    OpenMeteoClient,
)
from dehumidifier_adviser.models import MergedEnergyForecast
from dehumidifier_adviser.scenarios import SCENARIO_FACTORIES
from humidity_simulator_client import (
    AmbientConditions,
    DehumidifierSpec,
    GreedyStep,
    HumiditySimulatorClient,
    HumiditySource,
    OptimisationRequest,
    SimulationRequest,
    SimulationResult,
    SimulatorConnectionError,
    SimulatorError,
    StepsResponse,
)
from humidity_simulator_client import (
    EnergyForecastTimeSeries as OptimisationEnergyForecast,
)
from octopus_energy_uk_api import AgileRatesTimeSeries, OctopusEnergyClient, OctopusEnergyError

# Page configuration
st.set_page_config(
    page_title="Tørk",
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
    """Fetch and cache weather forecast data including humidity and temperature.

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
        hourly=["relative_humidity_2m", "temperature_2m"],
        daily=[
            "relative_humidity_2m_mean",
            "relative_humidity_2m_max",
            "relative_humidity_2m_min",
            "temperature_2m_mean",
            "temperature_2m_max",
            "temperature_2m_min",
        ],
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


_GSP_REGIONS: dict[str, str] = {
    "A": "A - South East England",
    "B": "B - East Midlands",
    "C": "C - East England",
    "D": "D - Merseyside & North Wales",
    "E": "E - West Midlands",
    "F": "F - North East England",
    "G": "G - North West England",
    "H": "H - Southern England",
    "J": "J - South East England (second zone)",
    "K": "K - South Wales",
    "L": "L - South West England",
    "M": "M - Yorkshire",
    "N": "N - South Scotland",
    "P": "P - North Scotland",
}


AGILE_PRODUCT_CODE = "AGILE-24-10-01"


@st.cache_data(ttl=1800)  # Cache for 30 minutes
def get_agile_predict_cached(gsp: str, forecast_days: int) -> EnergyForecast:
    """Fetch and cache Agile Predict electricity price forecast.

    Args:
        gsp: Grid Supply Point region letter (A-P)
        forecast_days: Number of days to fetch

    Returns:
        EnergyForecast with half-hourly predicted prices and p10/p90 bands
    """
    client = AgilePredictClient(timeout=30.0)
    return client.get_forecast(gsp, days=forecast_days)[0]


@st.cache_data(ttl=1800)  # Cache for 30 minutes
def get_octopus_agile_cached(gsp: str) -> AgileRatesTimeSeries:
    """Fetch and cache actual Agile unit rates from Octopus Energy for today onwards.

    Args:
        gsp: Grid Supply Point region letter (A-P)

    Returns:
        AgileRatesTimeSeries with half-hourly actual electricity prices

    Raises:
        OctopusEnergyError: If the API request fails
    """
    client = OctopusEnergyClient()
    return client.get_agile_rates_timeseries(
        AGILE_PRODUCT_CODE,
        gsp=gsp,
        period_from=datetime.now(tz=timezone.utc),
    )


def build_merged_energy_forecast(gsp: str, forecast_days: int) -> MergedEnergyForecast:
    """Merge Octopus actual prices with Agile Predict forecast prices.

    Octopus actual prices are used where available (roughly today + tomorrow after
    4pm publication).  Agile Predict forecast fills the remainder of the window.

    Args:
        gsp: Grid Supply Point region letter (A-P)
        forecast_days: Number of days to cover

    Returns:
        MergedEnergyForecast with combined series and separate actual/forecast slices
    """
    agile_forecast = get_agile_predict_cached(gsp=gsp, forecast_days=forecast_days)
    agile_datetimes: pd.DatetimeIndex = pd.to_datetime(
        [p.date_time for p in agile_forecast.prices], utc=True
    ).tz_convert(None)
    agile_ts_list = agile_datetimes.tolist()
    agile_dict: dict[pd.Timestamp, float] = {ts: p.agile_pred for ts, p in zip(agile_ts_list, agile_forecast.prices)}
    agile_low_dict: dict[pd.Timestamp, float | None] = {
        ts: p.agile_low for ts, p in zip(agile_ts_list, agile_forecast.prices)
    }
    agile_high_dict: dict[pd.Timestamp, float | None] = {
        ts: p.agile_high for ts, p in zip(agile_ts_list, agile_forecast.prices)
    }

    octopus_dict: dict[pd.Timestamp, float] = {}
    try:
        octopus_ts = get_octopus_agile_cached(gsp=gsp)
        oct_datetimes: pd.DatetimeIndex = pd.to_datetime(octopus_ts.timestamps, utc=True).tz_convert(None)
        octopus_dict = dict(zip(oct_datetimes.tolist(), octopus_ts.values))
    except OctopusEnergyError:
        pass  # Fall back to pure forecast if Octopus is unavailable

    now_utc = pd.Timestamp(datetime.now(tz=timezone.utc)).tz_convert(None)
    all_timestamps: list[pd.Timestamp] = sorted(
        ts for ts in (set(agile_ts_list) | set(octopus_dict.keys())) if ts >= now_utc
    )

    actual_ts: list[pd.Timestamp] = []
    actual_vals: list[float] = []
    forecast_ts: list[pd.Timestamp] = []
    forecast_vals: list[float] = []
    forecast_vals_low: list[float] = []
    forecast_vals_high: list[float] = []
    combined_ts_strs: list[str] = []
    combined_vals: list[float] = []

    for ts in all_timestamps:
        if ts in octopus_dict:
            actual_ts.append(ts)
            actual_vals.append(octopus_dict[ts])
            combined_ts_strs.append(ts.isoformat())
            combined_vals.append(octopus_dict[ts])
        elif ts in agile_dict:
            central = agile_dict[ts]
            forecast_ts.append(ts)
            forecast_vals.append(central)
            forecast_vals_low.append(agile_low_dict.get(ts) or central)
            forecast_vals_high.append(agile_high_dict.get(ts) or central)
            combined_ts_strs.append(ts.isoformat())
            combined_vals.append(central)

    combined = OptimisationEnergyForecast(
        timestamps=combined_ts_strs,
        timestamp_format="ISO 8601",
        timezone="UTC",
        values=combined_vals,
        values_unit="p/kWh",
    )

    return MergedEnergyForecast(
        combined=combined,
        actual_timestamps=actual_ts,
        actual_values=actual_vals,
        forecast_timestamps=forecast_ts,
        forecast_values=forecast_vals,
        forecast_values_low=forecast_vals_low,
        forecast_values_high=forecast_vals_high,
    )


def plot_electricity_prices(timeseries: EnergyForecastTimeSeries) -> None:
    """Create and display a half-hourly electricity price line chart.

    Args:
        timeseries: AgileRatesTimeSeries with timestamps and prices
    """
    df = pd.DataFrame({"time": pd.to_datetime(timeseries.timestamps), "price": timeseries.values})

    fig = px.line(
        df,
        x="time",
        y="price",
        title="Agile Electricity Price Forecast",
        labels={"time": "Time", "price": "Price (p/kWh inc VAT)"},
        markers=True,
    )

    fig.update_layout(
        hovermode="x unified",
        template="plotly_white",
    )

    st.plotly_chart(fig, use_container_width=True)


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


def plot_hourly_temperature(forecast: HumidityForecast) -> None:
    """Create and display hourly temperature line chart.

    Args:
        forecast: HumidityForecast object containing hourly data
    """
    if forecast.hourly is None:
        st.warning("⚠️ No hourly data available")
        return

    # Convert polars DataFrame to pandas for Plotly compatibility
    df = forecast.hourly.to_dataframe().to_pandas()

    if "temperature_2m" not in df.columns:
        st.warning("⚠️ No temperature data available")
        return

    # Create interactive line chart
    fig = px.line(
        df,
        x="time",
        y="temperature_2m",
        title="Hourly Temperature Forecast",
        labels={"time": "Time", "temperature_2m": "Temperature (°C)"},
        markers=True,
    )

    # Customize layout
    fig.update_layout(
        hovermode="x unified",
        template="plotly_white",
    )

    st.plotly_chart(fig, use_container_width=True)


def plot_daily_temperature(forecast: HumidityForecast) -> None:
    """Create and display daily temperature chart with min/max error bars.

    Args:
        forecast: HumidityForecast object containing daily data
    """
    if forecast.daily is None:
        st.warning("⚠️ No daily data available")
        return

    # Convert polars DataFrame to pandas for Plotly compatibility
    df = forecast.daily.to_dataframe().to_pandas()

    if "temperature_2m_mean" not in df.columns:
        st.warning("⚠️ No temperature data available")
        return

    # Calculate error bars (distance from mean to min/max)
    df["error_minus"] = df["temperature_2m_mean"] - df["temperature_2m_min"]
    df["error_plus"] = df["temperature_2m_max"] - df["temperature_2m_mean"]

    # Create line chart with error bars
    fig = px.line(
        df,
        x="time",
        y="temperature_2m_mean",
        title="Daily Temperature Forecast",
        labels={"time": "Date", "temperature_2m_mean": "Mean Temperature (°C)"},
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
        template="plotly_white",
    )

    st.plotly_chart(fig, use_container_width=True)


def plot_simulation_results(result: SimulationResult) -> None:
    """Create and display simulation results as a dual-axis line chart.

    Args:
        result: SimulationResult containing timeseries data.
    """
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=result.timestamps,
            y=result.relative_humidity,
            name="Relative Humidity (%)",
            yaxis="y",
            mode="lines+markers",
            marker={"size": 4},
        )
    )

    fig.add_trace(
        go.Scatter(
            x=result.timestamps,
            y=result.absolute_humidity,
            name="Absolute Humidity (g/m\u00b3)",
            yaxis="y2",
            mode="lines+markers",
            marker={"size": 4},
        )
    )

    fig.update_layout(
        title="Humidity Simulation Results",
        xaxis_title="Time",
        yaxis={
            "title": "Relative Humidity (%)",
            "range": [0, 100],
        },
        yaxis2={
            "title": "Absolute Humidity (g/m\u00b3)",
            "overlaying": "y",
            "side": "right",
        },
        hovermode="x unified",
        template="plotly_white",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
    )

    st.plotly_chart(fig, use_container_width=True)


def _build_optimisation_plot(
    step: GreedyStep,
    baseline_rh: list[float] | None = None,
    merged_forecast: MergedEnergyForecast | None = None,
) -> go.Figure:
    """Build a multi-panel Plotly figure showing RH, dehumidifier schedule and (optionally) electricity price."""
    timestamps = pd.to_datetime(step.simulation_result.timestamps)
    rh = step.simulation_result.relative_humidity
    schedule = step.schedule
    delta = timestamps[1] - timestamps[0] if len(timestamps) > 1 else pd.Timedelta("30min")

    n_rows = 3 if merged_forecast is not None else 2
    row_heights = [0.5, 0.2, 0.3] if n_rows == 3 else [0.7, 0.3]
    subplot_titles = (
        ["", "Dehumidifier Schedule", "Electricity Price (p/kWh)"] if n_rows == 3 else ["", "Dehumidifier Schedule"]
    )

    fig = make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.06,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    # Unoptimised baseline (no dehumidifier)
    if baseline_rh is not None:
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=baseline_rh,
                name="Unoptimised RH (%)",
                line={"color": "lightcoral", "dash": "dash", "width": 1.5},
                opacity=0.8,
            ),
            row=1,
            col=1,
        )

    # Optimised RH line
    fig.add_trace(
        go.Scatter(x=timestamps, y=rh, name="Optimised RH (%)", line={"color": "steelblue", "width": 2}),
        row=1,
        col=1,
    )

    # 60% / 40% reference lines (as traces so they appear in the legend cleanly)
    fig.add_trace(
        go.Scatter(
            x=[timestamps.min(), timestamps.max()],
            y=[60, 60],
            name="60% recommended max",
            line={"color": "orange", "dash": "dash", "width": 1},
            opacity=0.8,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=[timestamps.min(), timestamps.max()],
            y=[40, 40],
            name="40% recommended min",
            line={"color": "green", "dash": "dash", "width": 1},
            opacity=0.8,
        ),
        row=1,
        col=1,
    )

    # Green shading on the RH panel for each contiguous ON block
    i, n = 0, len(schedule)
    while i < n:
        if schedule[i] == 1:
            j = i
            while j < n and schedule[j] == 1:
                j += 1
            fig.add_vrect(
                x0=timestamps[i],
                x1=timestamps[j - 1] + delta,
                fillcolor="green",
                opacity=0.15,
                line_width=0,
                row=1,
                col=1,
            )
            i = j
        else:
            i += 1

    # Dehumidifier schedule step chart
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=schedule,
            name="Dehumidifier on",
            line={"color": "green", "width": 1.5, "shape": "hv"},
            fill="tozeroy",
            fillcolor="rgba(0,128,0,0.3)",
        ),
        row=2,
        col=1,
    )

    # Electricity price panel (row 3) — split into actual (Octopus) and forecast (Agile Predict) traces
    if merged_forecast is not None:
        if merged_forecast.actual_timestamps:
            fig.add_trace(
                go.Scatter(
                    x=merged_forecast.actual_timestamps,
                    y=merged_forecast.actual_values,
                    name="Octopus Agile Pricing",
                    line={"color": "steelblue", "width": 1.5},
                ),
                row=3,
                col=1,
            )

        if merged_forecast.forecast_timestamps:
            # P10/P90 shaded band rendered as a closed polygon
            if merged_forecast.forecast_values_low and merged_forecast.forecast_values_high:
                band_x = (
                    list(merged_forecast.forecast_timestamps)
                    + list(reversed(merged_forecast.forecast_timestamps))
                )
                band_y = (
                    list(merged_forecast.forecast_values_high)
                    + list(reversed(merged_forecast.forecast_values_low))
                )
                fig.add_trace(
                    go.Scatter(
                        x=band_x,
                        y=band_y,
                        fill="toself",
                        fillcolor="rgba(70, 130, 180, 0.15)",
                        line={"width": 0},
                        mode="lines",
                        showlegend=False,
                        hoverinfo="skip",
                    ),
                    row=3,
                    col=1,
                )

            fig.add_trace(
                go.Scatter(
                    x=merged_forecast.forecast_timestamps,
                    y=merged_forecast.forecast_values,
                    name="Agile Predict",
                    line={"color": "steelblue", "width": 1.5, "dash": "dash"},
                ),
                row=3,
                col=1,
            )

        # Highlight dehumidifier-on windows on the price panel
        i, n = 0, len(schedule)
        while i < n:
            if schedule[i] == 1:
                j = i
                while j < n and schedule[j] == 1:
                    j += 1
                fig.add_vrect(
                    x0=timestamps[i],
                    x1=timestamps[j - 1] + delta,
                    fillcolor="green",
                    opacity=0.15,
                    line_width=0,
                    row=3,
                    col=1,
                )
                i = j
            else:
                i += 1

    yaxis3_layout = {"title": "Price (p/kWh)"} if merged_forecast is not None else {}

    fig.update_layout(
        height=350 * n_rows,
        yaxis={"range": [0, 105], "title": "Relative Humidity (%)"},
        yaxis2={"tickvals": [0, 1], "ticktext": ["Off", "On"], "range": [-0.1, 1.4], "title": "Schedule"},
        yaxis3=yaxis3_layout,
        hovermode="x unified",
        template="plotly_white",
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )

    return fig


def _build_price_plot(step: GreedyStep, energy_forecast: OptimisationEnergyForecast) -> go.Figure:
    """Build an electricity price chart with the dehumidifier schedule highlighted."""
    price_fmt = energy_forecast.timestamp_format
    if price_fmt.replace(" ", "") == "ISO8601":
        price_ts = pd.to_datetime(energy_forecast.timestamps, utc=True).tz_convert(None)
    else:
        price_ts = pd.to_datetime(energy_forecast.timestamps, format=price_fmt)
        if price_ts.tz is not None:
            price_ts = price_ts.tz_convert(None)

    sim_timestamps = pd.to_datetime(step.simulation_result.timestamps)
    schedule = step.schedule
    delta = sim_timestamps[1] - sim_timestamps[0] if len(sim_timestamps) > 1 else pd.Timedelta("30min")

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=price_ts,
            y=energy_forecast.values,
            name="Price (p/kWh)",
            line={"color": "darkorange", "width": 1.5},
        )
    )

    i, n = 0, len(schedule)
    while i < n:
        if schedule[i] == 1:
            j = i
            while j < n and schedule[j] == 1:
                j += 1
            fig.add_vrect(
                x0=sim_timestamps[i],
                x1=sim_timestamps[j - 1] + delta,
                fillcolor="green",
                opacity=0.15,
                line_width=0,
            )
            i = j
        else:
            i += 1

    fig.update_layout(
        yaxis={"title": "Price (p/kWh)"},
        hovermode="x unified",
        template="plotly_white",
        showlegend=True,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )

    return fig


def _baseline_simulation_request(request: OptimisationRequest) -> SimulationRequest:
    """Build a plain SimulationRequest from an OptimisationRequest (strips dehumidifier/energy fields)."""
    return SimulationRequest(
        surface_area=request.surface_area,
        surface_area_unit=request.surface_area_unit,
        ceiling_height=request.ceiling_height,
        ceiling_height_unit=request.ceiling_height_unit,
        internal_temperature=request.internal_temperature,
        internal_temperature_unit=request.internal_temperature_unit,
        air_changes_per_hour=request.air_changes_per_hour,
        starting_relative_humidity=request.starting_relative_humidity,
        sources=request.sources,
        external_ambient_conditions=request.external_ambient_conditions,
    )


def _submit_optimisation_job(client: HumiditySimulatorClient, request: OptimisationRequest) -> str | None:
    """Submit an optimisation job; displays any error and returns None on failure."""
    try:
        with st.spinner("Submitting optimisation job..."):
            return client.submit_optimisation(request)
    except SimulatorConnectionError as e:
        st.error(f"❌ {e}")
    except SimulatorError as e:
        st.error(f"Optimisation error: {e}")
    return None


def _run_optimisation(
    client: HumiditySimulatorClient, request: OptimisationRequest, merged_forecast: MergedEnergyForecast
) -> None:
    """Run baseline simulation then submit optimisation job, live-updating the UI with each step."""
    baseline_rh: list[float] | None = None
    try:
        with st.spinner("Running baseline simulation..."):
            baseline_rh = client.simulate(_baseline_simulation_request(request)).relative_humidity
    except SimulatorConnectionError as e:
        st.error(f"❌ {e}")
        return
    except SimulatorError as e:
        st.warning(f"Baseline simulation failed — chart will not show unoptimised line: {e}")

    job_id = _submit_optimisation_job(client, request)
    if job_id is None:
        return

    status_placeholder = st.empty()
    metric_placeholder = st.empty()
    plot_placeholder = st.empty()

    status_placeholder.info("Waiting for first result...")

    steps_seen = 0
    latest_step: GreedyStep | None = None

    try:
        while True:
            response: StepsResponse = client.get_optimisation_steps(job_id, from_index=steps_seen)

            for step in response.steps:
                latest_step = step
                steps_seen += 1

            if latest_step is not None:
                n_total = latest_step.n_total
                pct = steps_seen / n_total
                label = (
                    f"Complete — {steps_seen} / {n_total} steps"
                    if response.complete
                    else f"Step {steps_seen} / {n_total} ({pct:.0%})"
                )
                status_placeholder.progress(pct, text=label)
                metric_placeholder.metric("Best Objective", f"£{latest_step.objective / 100:.2f}")
                plot_placeholder.plotly_chart(
                    _build_optimisation_plot(latest_step, baseline_rh, merged_forecast),
                    use_container_width=True,
                    key=f"opt_plot_{steps_seen}",
                )

            if response.complete:
                if response.error:
                    st.error(f"Optimisation failed: {response.error}")
                break

            time.sleep(0.5)

    except SimulatorError as e:
        st.error(f"Optimisation error: {e}")


def display_optimisation_tab(forecast: HumidityForecast, forecast_days: int, gsp: str) -> None:
    """Display the optimisation tab — reads configuration from session state set in Configuration tab."""
    if st.button("Run Optimisation", use_container_width=True, type="primary"):
        if (
            forecast.hourly is None
            or forecast.hourly.relative_humidity_2m is None
            or forecast.hourly.temperature_2m is None
        ):
            st.error("❌ Forecast data is missing hourly humidity or temperature — cannot run optimisation.")
            return

        try:
            with st.spinner("Loading electricity prices..."):
                merged_forecast = build_merged_energy_forecast(gsp=gsp, forecast_days=forecast_days)
        except AgilePredictError as e:
            st.error(f"❌ Could not load electricity prices: {e}")
            return

        if merged_forecast.actual_timestamps:
            st.caption(
                f"Using {len(merged_forecast.actual_timestamps)} actual price slots from Octopus Energy "
                f"and {len(merged_forecast.forecast_timestamps)} forecast slots from Agile Predict."
            )
        else:
            st.caption(
                f"Using {len(merged_forecast.forecast_timestamps)} forecast slots from Agile Predict "
                "(Octopus actual prices unavailable)."
            )

        ambient_conditions = AmbientConditions(
            name="External Conditions",
            timestamps=[t.strftime("%Y-%m-%d %H:%M") for t in hourly_times],
            timestamp_format="%Y-%m-%d %H:%M",
            timezone=forecast.timezone,
            relative_humidity=hourly_rh,
            ambient_temperature=hourly_temp,
            ambient_temperature_unit="Celcius",
        )

        scenario_name = st.session_state.get("cfg_scenario", next(iter(SCENARIO_FACTORIES.keys())))
        sources = [
            _trim_source_to_future(s)
            for s in SCENARIO_FACTORIES[scenario_name](pd.Timestamp.now().normalize(), forecast_days)
        ]

        request = OptimisationRequest(
            surface_area=st.session_state.get("cfg_surface_area", 20.0),
            surface_area_unit="m2",
            ceiling_height=st.session_state.get("cfg_ceiling_height", 2.5),
            ceiling_height_unit="m",
            internal_temperature=st.session_state.get("cfg_temperature", 20.0),
            internal_temperature_unit="c",
            air_changes_per_hour=st.session_state.get("cfg_ach", 0.5),
            starting_relative_humidity=float(st.session_state.get("cfg_starting_rh", 50)),
            sources=sources,
            external_ambient_conditions=ambient_conditions,
            energy_forecast=merged_forecast.combined,
            dehumidifier=DehumidifierSpec(
                name=st.session_state.get("cfg_dh_name", "Dehumidifier"),
                wattage=st.session_state.get("cfg_dh_wattage", 250.0),
                extraction_rate=st.session_state.get("cfg_dh_extraction_rate", 400.0),
                extraction_rate_unit="g/h",
            ),
        )

        simulator_url = st.session_state.get("simulator_api_url", HumiditySimulatorClient.DEFAULT_BASE_URL)
        _run_optimisation(HumiditySimulatorClient(base_url=simulator_url), request, merged_forecast)


_SCENARIO_DESCRIPTIONS: dict[str, str] = {
    "1 Bed Flat": (
        "Single occupant flat.\n\n"
        "- **Breathing** (80 g/h) continuously on weekdays and weekend mornings until noon\n"
        "- **Shower** (1,200 g/h, 30 min) at 07:00 on weekdays and 09:00 on weekends\n"
        "- **Cooking** (600 g/h, 1 hr) on weekday evenings 18:00\u201319:00"
    ),
}


def display_configuration_tab() -> None:
    """Display the configuration tab \u2014 room, scenario and dehumidifier settings."""
    cfg_tab_room, cfg_tab_scenario, cfg_tab_dh = st.tabs(["Room", "Scenario", "Dehumidifier"])

    with cfg_tab_room:
        st.number_input(
            "Surface Area (m\u00b2)",
            min_value=1.0,
            max_value=500.0,
            value=65.0,
            step=1.0,
            key="cfg_surface_area",
        )
        st.number_input(
            "Ceiling Height (m)",
            min_value=1.0,
            max_value=10.0,
            value=2.5,
            step=0.1,
            key="cfg_ceiling_height",
        )
        st.number_input(
            "Room Temperature (\u00b0C)",
            min_value=-10.0,
            max_value=50.0,
            value=22.0,
            step=0.5,
            key="cfg_temperature",
        )
        st.slider(
            "Starting Relative Humidity (%)",
            min_value=0,
            max_value=100,
            value=50,
            key="cfg_starting_rh",
        )
        st.number_input(
            "Air Changes per Hour (ACH)",
            min_value=0.1,
            max_value=10.0,
            value=0.5,
            step=0.1,
            key="cfg_ach",
        )
        st.caption(
            "ACH measures how many times per hour the entire room's air volume is replaced by outside air. "
            "Typical values: 0.2 (very well sealed), 0.5 (average UK home), 1.0+ (draughty or well-ventilated)."
        )

    with cfg_tab_scenario:
        scenario_name = st.selectbox(
            "Choose a scenario",
            options=list(SCENARIO_FACTORIES.keys()),
            key="cfg_scenario",
        )
        description = _SCENARIO_DESCRIPTIONS.get(scenario_name, "")
        if description:
            st.markdown(description)

    with cfg_tab_dh:
        st.text_input("Name", value="Dehumidifier", key="cfg_dh_name")
        st.number_input(
            "Wattage (W)",
            min_value=1.0,
            max_value=5000.0,
            value=250.0,
            step=10.0,
            key="cfg_dh_wattage",
        )
        st.number_input(
            "Extraction Rate (g/h)",
            min_value=1.0,
            max_value=5000.0,
            value=400.0,
            step=10.0,
            key="cfg_dh_extraction_rate",
        )


def _run_simulation(
    sources: list[HumiditySource],
    surface_area: float,
    ceiling_height: float,
    temperature: float,
    starting_rh: int,
    *,
    air_changes_per_hour: float,
    ambient_conditions: AmbientConditions,
    is_metric: bool,
) -> None:
    """Build and execute a simulation request, then display results."""
    request = SimulationRequest(
        surface_area=surface_area,
        surface_area_unit="m2" if is_metric else "ft2",
        ceiling_height=ceiling_height,
        ceiling_height_unit="m" if is_metric else "ft",
        internal_temperature=temperature,
        internal_temperature_unit="c" if is_metric else "f",
        air_changes_per_hour=air_changes_per_hour,
        starting_relative_humidity=float(starting_rh),
        sources=sources,
        external_ambient_conditions=ambient_conditions,
    )

    simulator_url = st.session_state.get("simulator_api_url", HumiditySimulatorClient.DEFAULT_BASE_URL)
    client = HumiditySimulatorClient(base_url=simulator_url)

    try:
        with st.spinner("Running simulation..."):
            result = client.simulate(request)
        plot_simulation_results(result)

        with st.expander("Simulation Summary"):
            st.markdown(
                f"- **Peak relative humidity:** {max(result.relative_humidity):.1f}%\n"
                f"- **Min relative humidity:** {min(result.relative_humidity):.1f}%\n"
                f"- **Peak absolute humidity:** {max(result.absolute_humidity):.2f} g/m\u00b3\n"
                f"- **Data points:** {len(result.timestamps)}"
            )

    except SimulatorConnectionError:
        st.error(
            f"Cannot connect to the humidity simulator API at **{simulator_url}**.\n\n"
            "Make sure the simulator container is running:\n"
            "```\ncd humidity-simulator && docker compose up -d --build\n```"
        )
    except SimulatorError as e:
        st.error(f"Simulation error: {e}")


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


def display_weather_data(location: Location, forecast_days: int, gsp: str) -> None:
    """Display weather data for the given location.

    Args:
        location: Location object with coordinates and address
        forecast_days: Number of days to forecast
        gsp: Grid Supply Point region letter used for electricity price forecasts
    """
    # Fetch current conditions and forecast data upfront
    try:
        with st.spinner("Loading current conditions..."):
            current = get_current_conditions_cached(location.latitude, location.longitude)

        with st.spinner(f"Loading {forecast_days}-day forecast..."):
            forecast = get_forecast_cached(location.latitude, location.longitude, forecast_days)
    except Exception as e:  # noqa: BLE001
        st.error(f"❌ **Weather data error:** {e}")
        return

    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Current Conditions", "Forecast", "Configuration", "Optimisation"])

    # Tab 1: Current Conditions
    with tab1:
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

            # Add vertical spacing to match horizontal column gap
            st.markdown("<div style='margin: 0.5rem 0;'></div>", unsafe_allow_html=True)

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

    # Tab 2: Forecast
    with tab2:
        forecast_type = st.selectbox(
            "Forecast Type",
            options=["Humidity", "Temperature", "Electricity Price"],
            index=0,
            help="Select which metric to display in the forecast",
            key="forecast_type_select",
        )

        st.divider()

        # Display appropriate chart based on forecast type
        if forecast_type == "Humidity":
            plot_hourly_humidity(forecast)
        elif forecast_type == "Temperature":
            plot_hourly_temperature(forecast)
        else:  # Electricity Price
            try:
                agile_ts = get_agile_predict_cached(gsp=gsp, forecast_days=forecast_days).to_timeseries()
                plot_electricity_prices(agile_ts)
            except AgilePredictError as e:
                st.warning(f"Could not load electricity prices: {e}")

    # Tab 3: Configuration
    with tab3:
        display_configuration_tab()

    # Tab 4: Optimisation
    with tab4:
        display_optimisation_tab(forecast, forecast_days, gsp)


def main() -> None:
    """Main Streamlit application."""
    # Header
    st.title("Tørk")
    st.markdown("Optimise your bills, optimise your drying, optimise your dehumidifier!")

    # Sidebar with location input and settings
    with st.sidebar:
        # Location input form
        with st.form("location_form"):
            st.subheader("🔍 Enter Location")

            city = st.text_input("City", placeholder="e.g., London")
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

        st.divider()

        # Forecast settings
        st.header("⚙️ Forecast Settings")

        forecast_days = st.slider(
            "Forecast Duration (days)",
            min_value=1,
            max_value=16,
            value=7,
            help="Number of days to forecast (API limit: 1-16)",
        )

        gsp = st.selectbox(
            "Electricity Region (GSP)",
            options=list(_GSP_REGIONS.keys()),
            format_func=lambda k: _GSP_REGIONS[k],
            index=6,  # Default: G - North West England
            help="UK Grid Supply Point region for Agile electricity price forecasts",
        )

        st.divider()

        st.header("🔬 Simulator Settings")
        st.text_input(
            "Simulator API URL",
            value=HumiditySimulatorClient.DEFAULT_BASE_URL,
            key="simulator_api_url",
            help="URL of the humidity-simulator API (default: http://localhost:8000)",
        )

        st.divider()
        st.markdown("### About")
        st.markdown(
            """
            This dashboard uses:
            - **OpenStreetMap Nominatim** for geocoding
            - **Open-Meteo API** for weather forecasts
            - **Humidity Simulator API** for room simulation
            - **[Agile Predict](https://agilepredict.com)** for electricity price forecasts
            - **Relative Humidity (%)** as the primary metric

            Data is cached to improve performance and respect API rate limits.
            """
        )

    # Get location to display (default or user-specified)
    location = get_location_to_display()

    # Display weather data if location is available
    if location:
        display_weather_data(location, forecast_days, gsp)


if __name__ == "__main__":
    main()
