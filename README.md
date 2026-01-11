# Dehumidifier Advisor

A Python library and web dashboard for fetching and analyzing humidity forecast data worldwide. Get detailed humidity forecasts for any location using the Open-Meteo weather API.

## Features

- **Geocoding**: Convert city names to coordinates using OpenStreetMap Nominatim
- **Humidity Forecasts**: Get hourly and daily humidity forecasts (1-16 days)
- **Current Conditions**: Real-time humidity data for any location
- **Interactive Dashboard**: Web-based Streamlit dashboard for visualizing forecasts
- **Data Export**: Convert forecast data to Polars/Pandas DataFrames

## Usage

### Web Dashboard

The easiest way to use Dehumidifier Advisor is through the interactive Streamlit dashboard:

```bash
uv sync
uv run streamlit run streamlit_app.py
```

The dashboard will open in your browser at `http://localhost:8501`. Features include:

- 🔍 Location search (city, country, optional state/region)
- 📍 Interactive map showing selected location
- 💧 Current humidity conditions display
- 📊 Toggle between hourly and daily forecast views
- 🎯 Customizable forecast duration (1-16 days)
- ⚡ Intelligent caching for performance

### Python API

You can also use the library programmatically:

```python
from dehumidifier_adviser import Geocoder, OpenMeteoClient

# Get location coordinates
geocoder = Geocoder()
location = geocoder.forward_geocode(city="London", country="United Kingdom")

# Get humidity forecast
client = OpenMeteoClient()
forecast = client.get_humidity_forecast(
    latitude=location.latitude,
    longitude=location.longitude,
    forecast_days=7
)

# Get current conditions
current = client.get_current_humidity(
    latitude=location.latitude,
    longitude=location.longitude
)

print(f"Current humidity in {location.city}: {current['relative_humidity_2m']}%")
```

See `main.py` for more detailed examples.


## Development
The development environment should be created and managed using [uv](https://docs.astral.sh/uv/). To create the environment:
```commandline
uv sync
```
To run the formatting, linting and testing:
```commandline
uv run poe all
```
Or simply
```commandline
poe all
```
if you have activated the virtual environment (VSCode will do this automatically for you). For example, to activate the environment from a PowerShell prompt:
```powershell
. ".venv\Scripts\activate.ps1"
```

## Contact
Put your contact details here.
