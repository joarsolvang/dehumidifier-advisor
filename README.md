# Dehumidifier Advisor

Work in progress - The aim of this repositiory is to provide guidance on how best to manage your indoor environment. The tool will use a combination of preset housing scenarios and weather forecast data to simulate your indoor environment. The simulation timeseries will be used as a basis for optimisation work, the output (eventually) being when your best bet is to get the laundry done etc. 


### Web Dashboard

The app is currently local-only/in-development. To run it pull the repo and run:

```bash
uv sync
uv run streamlit run streamlit_app.py
```

The dashboard will open in your browser at `http://localhost:8501`.

Deployed on [Streamlit Community Cloud](https://streamlit.io/cloud), talking
to the `humidity-simulator` API on Azure Functions. Set `SIMULATOR_API_URL`
and `SIMULATOR_API_KEY` as Streamlit Cloud secrets.


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
