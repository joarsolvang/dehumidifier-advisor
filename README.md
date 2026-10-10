# Tørk — Dehumidifier Advisor

Parked for now. This project looked to explore how the indoor environment and dehumidifiers could be managed to provide demand-side flexibility. Rather than an on-off controller, this project pulled price and weather forecasts to offer the controller foresight and an opportunity to act pre-emptively under advantageous pricing. A future goal of the project was also to pull some "drying-weather" heuristic from the forecast to advise people on when to run their laundry. 

**Try it: [dehumidifier-advisor.streamlit.app](https://dehumidifier-advisor.streamlit.app/)**


## How it works

1. **Weather**: an hourly humidity and temperature forecast is fetched from [Open-Meteo](https://open-meteo.com/).
2. **Room simulation**: the accompanying [humidity-simulator](https://github.com/joarsolvang/humidity-simulator) API simulates the
   internal humidity of the room defined in the *Configuration* tab (size, temperature, ventilation, occupancy scenario).
3. **Electricity prices**: Octopus Agile prices for the Grid Supply Point region, using published prices where available and
   [Agile Predict](https://agilepredict.com) forecasts beyond that. Kudos to Agile Predict for the open service.
4. **Optimisation**: The optimisation algorithm is simpler than initially intended. Implementing MILP became difficult due to the non-linearities and formulating the rate of change, which is intrinsically linked to the changing delta between the internal and external humidity. The current optimisation iterates over the simulation and does a reasonable job of balancing costs with penalties for exceeding maximum recommended humidity levels. 

## Running locally

```bash
uv sync
uv run streamlit run streamlit_app.py
```

The dashboard opens at `http://localhost:8501`. The room simulation and optimisation need a running humidity-simulator
API; point the app at it with environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `SIMULATOR_API_URL` | `http://localhost:8000` | Base URL of the humidity-simulator API |
| `SIMULATOR_API_KEY` | _(none)_ | API key, if the API requires one |

## Deployment

The app is hosted on [Streamlit Community Cloud](https://streamlit.io/cloud) from the `main` branch, and talks to the
humidity-simulator API on Azure Functions.

## Development

The development environment should be created and managed using [uv](https://docs.astral.sh/uv/). To create the
environment:
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
if you have activated the virtual environment (VSCode will do this automatically for you). For example, to activate the
environment from a PowerShell prompt:
```powershell
. ".venv\Scripts\activate.ps1"
```
