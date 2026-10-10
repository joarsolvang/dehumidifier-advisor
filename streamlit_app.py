"""Streamlit dashboard for dehumidifier humidity forecasting."""

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from agile_predict_api import AgilePredictClient, AgilePredictError, EnergyForecast
from dehumidifier_adviser import (
    Geocoder,
    GeocodingServiceError,
    HumidityForecast,
    Location,
    LocationNotFoundError,
    OpenMeteoClient,
)
from dehumidifier_adviser.gsp import find_gsp
from dehumidifier_adviser.models import MergedEnergyForecast
from dehumidifier_adviser.scenarios import SCENARIO_FACTORIES
from humidity_simulator_client import (
    AmbientConditions,
    DehumidifierSpec,
    HumiditySimulatorClient,
    HumiditySource,
    OptimisationRequest,
    OptimisationResult,
    SimulationRequest,
    SimulationResult,
    SimulatorConnectionError,
    SimulatorError,
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

# Simulator API base URL. Server-side config only (env var), never a user-editable UI
# field — the value is used to make outbound HTTP requests from the Streamlit server,
# so accepting it from visitor input would allow SSRF (e.g. probing internal services
# or cloud metadata endpoints).
SIMULATOR_API_URL = os.environ.get("SIMULATOR_API_URL", HumiditySimulatorClient.DEFAULT_BASE_URL)
SIMULATOR_API_KEY = os.environ.get("SIMULATOR_API_KEY")


@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_location_cached(city: str, country: str) -> Location:
    """Fetch and cache location data from geocoding API.

    Args:
        city: City name
        country: Country name

    Returns:
        Location object with coordinates and address details

    Raises:
        LocationNotFoundError: If location cannot be found
        GeocodingServiceError: If service is unavailable
    """
    geocoder = Geocoder()
    return geocoder.forward_geocode(city=city, country=country)


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


GSP_REGIONS_GEOJSON = Path(__file__).parent / "data" / "gsp_regions.geojson"

UK_MAP_HEIGHT = 450
# Approximate rendered width of the map column, used to pick a zoom level that fits the selected region
UK_MAP_ASSUMED_WIDTH = 650
MAP_TILE_SIZE = 512
MAP_ZOOM_PADDING = 0.3


@st.cache_data
def load_gsp_regions() -> dict:
    """Load the GSP group boundaries (one feature per region letter) as GeoJSON."""
    return json.loads(GSP_REGIONS_GEOJSON.read_text())


def _feature_bounds(feature: dict) -> tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) of a Polygon or MultiPolygon feature."""
    polygons = feature["geometry"]["coordinates"]
    if feature["geometry"]["type"] == "Polygon":
        polygons = [polygons]
    points = [point for polygon in polygons for ring in polygon for point in ring]
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    return min(lons), min(lats), max(lons), max(lats)


def _map_view_for_bounds(bounds: tuple[float, float, float, float]) -> tuple[dict[str, float], float]:
    """Compute a map centre and zoom level that fit the given (min_lon, min_lat, max_lon, max_lat) box."""
    min_lon, min_lat, max_lon, max_lat = bounds

    def mercator_y(lat: float) -> float:
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    x_fraction = (max_lon - min_lon) / 360
    y_fraction = (mercator_y(max_lat) - mercator_y(min_lat)) / (2 * math.pi)
    zoom = min(
        math.log2(UK_MAP_ASSUMED_WIDTH / (MAP_TILE_SIZE * x_fraction)),
        math.log2(UK_MAP_HEIGHT / (MAP_TILE_SIZE * y_fraction)),
    )
    centre_y = (mercator_y(max_lat) + mercator_y(min_lat)) / 2
    centre_lat = math.degrees(2 * math.atan(math.exp(centre_y)) - math.pi / 2)
    return {"lat": centre_lat, "lon": (min_lon + max_lon) / 2}, zoom - MAP_ZOOM_PADDING


def build_location_map(location: Location, gsp: str) -> go.Figure:
    """Build a map of GSP region boundaries, zoomed to and highlighting the selected region, with a location marker."""
    gsp_regions = load_gsp_regions()
    gsp_letters = [feature["properties"]["gsp"] for feature in gsp_regions["features"]]
    selected_feature = next(feature for feature in gsp_regions["features"] if feature["properties"]["gsp"] == gsp)
    centre, zoom = _map_view_for_bounds(_feature_bounds(selected_feature))

    fig = go.Figure()
    fig.add_trace(
        go.Choroplethmap(
            geojson=gsp_regions,
            featureidkey="properties.gsp",
            locations=gsp_letters,
            z=[0] * len(gsp_letters),
            colorscale=[[0, "rgba(70, 130, 180, 0.15)"], [1, "rgba(70, 130, 180, 0.15)"]],
            showscale=False,
            marker={"line": {"color": "steelblue", "width": 1}},
            text=[_GSP_REGIONS[letter] for letter in gsp_letters],
            hovertemplate="%{text}<extra></extra>",
            name="Grid Supply Points",
        )
    )
    # Selected region drawn on top with a stronger fill and outline
    fig.add_trace(
        go.Choroplethmap(
            geojson={"type": "FeatureCollection", "features": [selected_feature]},
            featureidkey="properties.gsp",
            locations=[gsp],
            z=[0],
            colorscale=[[0, "rgba(70, 130, 180, 0.35)"], [1, "rgba(70, 130, 180, 0.35)"]],
            showscale=False,
            marker={"line": {"color": "navy", "width": 3}},
            text=[_GSP_REGIONS[gsp]],
            hovertemplate="%{text}<extra></extra>",
            name="Selected Grid Supply Point",
        )
    )
    fig.add_trace(
        go.Scattermap(
            lat=[location.latitude],
            lon=[location.longitude],
            mode="markers",
            marker={"size": 12, "color": "crimson"},
            text=[location.city],
            hovertemplate="%{text}<extra></extra>",
            name="Location",
        )
    )
    fig.update_layout(
        map={"style": "carto-positron", "center": centre, "zoom": zoom},
        height=UK_MAP_HEIGHT,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        showlegend=False,
    )
    return fig


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
        period_from=datetime.now(tz=UTC),
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
    agile_dict: dict[pd.Timestamp, float] = {
        ts: p.agile_pred for ts, p in zip(agile_ts_list, agile_forecast.prices, strict=True)
    }
    agile_low_dict: dict[pd.Timestamp, float | None] = {
        ts: p.agile_low for ts, p in zip(agile_ts_list, agile_forecast.prices, strict=True)
    }
    agile_high_dict: dict[pd.Timestamp, float | None] = {
        ts: p.agile_high for ts, p in zip(agile_ts_list, agile_forecast.prices, strict=True)
    }

    octopus_dict: dict[pd.Timestamp, float] = {}
    try:
        octopus_ts = get_octopus_agile_cached(gsp=gsp)
        oct_datetimes: pd.DatetimeIndex = pd.to_datetime(octopus_ts.timestamps, utc=True).tz_convert(None)
        octopus_dict = dict(zip(oct_datetimes.tolist(), octopus_ts.values, strict=True))
    except OctopusEnergyError:
        pass  # Fall back to pure forecast if Octopus is unavailable

    now_utc = pd.Timestamp(datetime.now(tz=UTC)).tz_convert(None)
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


def _build_optimisation_plot(  # noqa: C901
    step: OptimisationResult,
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
                band_x = list(merged_forecast.forecast_timestamps) + list(reversed(merged_forecast.forecast_timestamps))
                band_y = list(merged_forecast.forecast_values_high) + list(
                    reversed(merged_forecast.forecast_values_low)
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


def _run_optimisation(
    client: HumiditySimulatorClient, request: OptimisationRequest, merged_forecast: MergedEnergyForecast
) -> None:
    """Run a baseline simulation, then run the optimiser and display the final result."""
    baseline_rh: list[float] | None = None
    try:
        with st.spinner("Running baseline simulation..."):
            baseline_rh = client.simulate(_baseline_simulation_request(request)).relative_humidity
    except SimulatorConnectionError as e:
        st.error(f"❌ {e}")
        return
    except SimulatorError as e:
        st.warning(f"Baseline simulation failed — chart will not show unoptimised line: {e}")

    try:
        with st.spinner("Running optimisation..."):
            result = client.optimise(request)
    except SimulatorConnectionError as e:
        st.error(f"❌ {e}")
        return
    except SimulatorError as e:
        st.error(f"Optimisation error: {e}")
        return

    running_cost_pence = sum(result.simulation_result.dehumidifier_running_cost_pence or [])
    st.metric("Running Cost", f"£{running_cost_pence / 100:.2f}")
    st.plotly_chart(
        _build_optimisation_plot(result, baseline_rh, merged_forecast),
        use_container_width=True,
    )


def _trim_ambient_to_future(
    times: list[datetime],
    rh: list[float],
    temp: list[float],
    forecast_timezone: str,
) -> tuple[list[datetime], list[float], list[float]]:
    """Drop any hourly slots whose timestamp is before the current moment."""
    try:
        tz = ZoneInfo(forecast_timezone)
        now_local = datetime.now(tz=tz).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        now_local = datetime.now()

    triples = [(t, r, te) for t, r, te in zip(times, rh, temp, strict=True) if t >= now_local]
    if not triples:
        return [], [], []
    ft, fr, fte = zip(*triples, strict=True)
    return list(ft), list(fr), list(fte)


def _trim_source_to_future(source: HumiditySource) -> HumiditySource:
    """Drop any source emissions slots whose timestamp is before the current UTC moment."""
    now_utc = datetime.now(tz=UTC).replace(tzinfo=None)
    fmt = source.timestamp_format
    future = [
        (ts, v) for ts, v in zip(source.timestamps, source.values, strict=True) if datetime.strptime(ts, fmt) >= now_utc
    ]
    ts_list = [ts for ts, _ in future]
    val_list = [v for _, v in future]
    return HumiditySource(
        name=source.name,
        max_emissions_rate_unit=source.max_emissions_rate_unit,
        timestamps=ts_list,
        timestamp_format=source.timestamp_format,
        timezone=source.timezone,
        values=val_list,
        values_unit=source.values_unit,
    )


# Defaults for the Configuration tab widgets; also used before that tab has rendered on first load
_ROOM_DEFAULTS: dict[str, float] = {
    "cfg_surface_area": 65.0,
    "cfg_ceiling_height": 2.5,
    "cfg_temperature": 22.0,
    "cfg_starting_rh": 50,
    "cfg_ach": 0.5,
}


def _room_setting(key: str) -> float:
    return st.session_state.get(key, _ROOM_DEFAULTS[key])


def _build_room_simulation_request(forecast: HumidityForecast, forecast_days: int) -> SimulationRequest | None:
    """Build a no-dehumidifier simulation request from the forecast and the Configuration tab settings.

    Returns:
        The request, or None if the forecast is missing hourly humidity or temperature
    """
    if (
        forecast.hourly is None
        or forecast.hourly.relative_humidity_2m is None
        or forecast.hourly.temperature_2m is None
    ):
        return None

    hourly_times, hourly_rh, hourly_temp = _trim_ambient_to_future(
        forecast.hourly.time,
        forecast.hourly.relative_humidity_2m,
        forecast.hourly.temperature_2m,
        forecast.timezone,
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

    return SimulationRequest(
        surface_area=_room_setting("cfg_surface_area"),
        surface_area_unit="m2",
        ceiling_height=_room_setting("cfg_ceiling_height"),
        ceiling_height_unit="m",
        internal_temperature=_room_setting("cfg_temperature"),
        internal_temperature_unit="c",
        air_changes_per_hour=_room_setting("cfg_ach"),
        starting_relative_humidity=float(_room_setting("cfg_starting_rh")),
        sources=sources,
        external_ambient_conditions=ambient_conditions,
    )


@st.cache_data(ttl=1800)  # Cache for 30 minutes
def simulate_room_cached(request_json: str) -> SimulationResult:
    """Run (and cache) a no-dehumidifier simulation for a JSON-serialised SimulationRequest."""
    client = HumiditySimulatorClient(base_url=SIMULATOR_API_URL, api_key=SIMULATOR_API_KEY)
    return client.simulate(SimulationRequest.model_validate_json(request_json))


HUMIDITY_CHART_HEIGHT = 400


def build_humidity_forecast_plot(ambient: AmbientConditions, internal: SimulationResult | None) -> go.Figure:
    """Plot the external humidity forecast alongside the simulated internal humidity (no dehumidifier)."""
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=pd.to_datetime(ambient.timestamps, format=ambient.timestamp_format),
            y=ambient.relative_humidity,
            name="External",
            line={"color": "gray", "width": 1.5},
        )
    )
    if internal is not None:
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(internal.timestamps),
                y=internal.relative_humidity,
                name="Internal",
                line={"color": "steelblue", "width": 2},
            )
        )
    fig.update_layout(
        title="Relative Humidity Forecast",
        xaxis_title="Time",
        yaxis_title="Relative Humidity (%)",
        yaxis_range=[0, 100],
        hovermode="x unified",
        template="plotly_white",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0},
        height=HUMIDITY_CHART_HEIGHT,
    )
    return fig


def display_humidity_forecast(forecast: HumidityForecast, forecast_days: int) -> None:
    """Display external and simulated internal humidity for the configured room, excluding humidity sources."""
    request = _build_room_simulation_request(forecast, forecast_days)
    if request is None:
        st.warning("⚠️ Forecast data is missing hourly humidity or temperature")
        return

    # Zero the source emissions rather than dropping the sources: the simulator returns an empty
    # result when given no sources, and the sources' timestamps define the simulated period.
    request = request.model_copy(
        update={"sources": [s.model_copy(update={"values": [0.0] * len(s.values)}) for s in request.sources]}
    )

    internal: SimulationResult | None = None
    try:
        with st.spinner("Simulating internal humidity..."):
            internal = simulate_room_cached(request.model_dump_json())
    except SimulatorError as e:
        st.warning(f"Could not simulate internal humidity: {e}")

    st.plotly_chart(
        build_humidity_forecast_plot(request.external_ambient_conditions, internal), use_container_width=True
    )
    st.caption('Internal humidity is representative of the room defined in "Configuration" without any interference.')


def display_optimisation_tab(forecast: HumidityForecast, forecast_days: int, gsp: str) -> None:
    """Display the optimisation tab — reads configuration from session state set in Configuration tab."""
    if st.button("Run Optimisation", use_container_width=True, type="primary"):
        simulation_request = _build_room_simulation_request(forecast, forecast_days)
        if simulation_request is None:
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

        request = OptimisationRequest(
            **simulation_request.model_dump(),
            energy_forecast=merged_forecast.combined,
            dehumidifier=DehumidifierSpec(
                name=st.session_state.get("cfg_dh_name", "Dehumidifier"),
                wattage=st.session_state.get("cfg_dh_wattage", 250.0),
                extraction_rate=st.session_state.get("cfg_dh_extraction_rate", 400.0),
                extraction_rate_unit="g/h",
            ),
        )

        client = HumiditySimulatorClient(base_url=SIMULATOR_API_URL, api_key=SIMULATOR_API_KEY)
        _run_optimisation(client, request, merged_forecast)


_SCENARIO_DESCRIPTIONS: dict[str, str] = {
    "1 Bed Flat": (
        "Single occupant flat.\n\n"
        "- **Occupancy** (80 g/h) continuously on weekdays and weekend mornings until noon\n"
        "- **Showering** (1,200 g/h, 30 min) at 07:00 on weekdays and 09:00 on weekends\n"
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
            value=_ROOM_DEFAULTS["cfg_surface_area"],
            step=1.0,
            key="cfg_surface_area",
        )
        st.number_input(
            "Ceiling Height (m)",
            min_value=1.0,
            max_value=10.0,
            value=_ROOM_DEFAULTS["cfg_ceiling_height"],
            step=0.1,
            key="cfg_ceiling_height",
        )
        st.number_input(
            "Room Temperature (\u00b0C)",
            min_value=-10.0,
            max_value=50.0,
            value=_ROOM_DEFAULTS["cfg_temperature"],
            step=0.5,
            key="cfg_temperature",
        )
        st.slider(
            "Starting Relative Humidity (%)",
            min_value=0,
            max_value=100,
            value=_ROOM_DEFAULTS["cfg_starting_rh"],
            key="cfg_starting_rh",
        )
        st.number_input(
            "Air Changes per Hour (ACH)",
            min_value=0.1,
            max_value=10.0,
            value=_ROOM_DEFAULTS["cfg_ach"],
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

    client = HumiditySimulatorClient(base_url=SIMULATOR_API_URL, api_key=SIMULATOR_API_KEY)

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
            f"Cannot connect to the humidity simulator API at **{SIMULATOR_API_URL}**.\n\n"
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
                return get_location_cached(loc_input["city"], loc_input["country"])

        except LocationNotFoundError:
            st.error(
                f"🔍 **Location not found:** '{loc_input['city']}, {loc_input['country']}'\n\n"
                "**Suggestions:**\n"
                "- Check spelling of city and country names\n"
                "- Try using full country name (e.g., 'United Kingdom' not 'UK')"
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


def display_location_box(location: Location) -> None:
    """Display the selected location's city and country in a bordered box."""
    st.markdown(
        f"""
        <div style="border: 2px solid #e0e0e0; border-radius: 8px; padding: 12px; text-align: center;">
            <p style="font-size: 1.2em; font-weight: bold; margin: 5px 0;">{location.city}</p>
            <p style="font-size: 1em; margin: 5px 0;">{location.country}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def display_weather_data(location: Location, forecast_days: int, gsp: str) -> None:
    """Display weather data for the given location.

    Args:
        location: Location object with coordinates and address
        forecast_days: Number of days to forecast
        gsp: Grid Supply Point region letter used for electricity price forecasts
    """
    # Fetch forecast data upfront
    try:
        with st.spinner(f"Loading {forecast_days}-day forecast..."):
            forecast = get_forecast_cached(location.latitude, location.longitude, forecast_days)
    except Exception as e:  # noqa: BLE001
        st.error(f"❌ **Weather data error:** {e}")
        return

    tab_optimisation, tab_configuration = st.tabs(["Optimisation", "Configuration"])

    with tab_optimisation:
        # Humidity forecast on the left, map on the right
        col_forecasts, col_map = st.columns([3, 2])

        # Each chart sits in its own bordered box
        with col_forecasts, st.container(border=True):
            display_humidity_forecast(forecast, forecast_days)

        with col_map, st.container(border=True):
            st.plotly_chart(build_location_map(location, gsp), use_container_width=True)

        with st.container(border=True):
            display_optimisation_tab(forecast, forecast_days, gsp)

    with tab_configuration:
        display_configuration_tab()


def select_gsp_manually() -> str:
    """Show a Grid Supply Point selector for locations outside every GSP region."""
    st.subheader("⚙️ Grid Supply Point")
    st.warning("This location is outside the Grid Supply Point regions. Choose one for electricity prices.")
    gsp = st.selectbox(
        "Grid Supply Point",
        options=list(_GSP_REGIONS.keys()),
        format_func=lambda k: _GSP_REGIONS[k],
        index=6,  # Default: G - North West England
        help="UK Grid Supply Point region for Agile electricity price forecasts",
        label_visibility="collapsed",
    )
    st.divider()
    return gsp


def main() -> None:
    """Main Streamlit application."""
    # Header
    st.title("Tørk")
    st.markdown("Optimise your bills, optimise your drying, optimise your dehumidifier!")

    # Sidebar with location input and settings
    with st.sidebar:
        # Location input form
        with st.form("location_form"):
            st.subheader("🔍 Location Input")

            city = st.text_input("City", placeholder="e.g., London")
            country = st.text_input("Country", placeholder="e.g., United Kingdom")

            submit = st.form_submit_button("Get Forecast", use_container_width=True)

            if submit:
                if not city or not country:
                    st.error("❌ Please enter both city and country")
                else:
                    st.session_state.location_input = {
                        "city": city.strip(),
                        "country": country.strip(),
                    }

        st.divider()

        # Filled in below once the location has been resolved
        location_container = st.container()

        # Filled in below only if the GSP cannot be found from the location
        gsp_fallback_container = st.container()

        st.subheader("⚙️ Forecast Duration")

        forecast_days = st.slider(
            "Forecast Duration (days)",
            min_value=1,
            max_value=16,
            value=7,
            help="Number of days to forecast (API limit: 1-16)",
            label_visibility="collapsed",
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
        gsp = find_gsp(location.latitude, location.longitude, load_gsp_regions())
        if gsp is None:
            with gsp_fallback_container:
                gsp = select_gsp_manually()
        with location_container:
            st.subheader("📍 Current Location")
            display_location_box(location)
            st.divider()
        display_weather_data(location, forecast_days, gsp)


if __name__ == "__main__":
    main()
