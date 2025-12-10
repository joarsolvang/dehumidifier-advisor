from dehumidifier_adviser import OpenMeteoClient


def main() -> None:
    """Simple example of using the OpenMeteoClient."""
    client = OpenMeteoClient()

    # Get full humidity forecast
    forecast = client.get_humidity_forecast(latitude=51.5074, longitude=-0.1278, forecast_days=7)
    print(f"Forecast for {forecast.latitude}, {forecast.longitude}")
    print(f"Timezone: {forecast.timezone}")

    # Get current conditions
    current = client.get_current_humidity(latitude=51.5074, longitude=-0.1278)
    print(f"\nCurrent conditions: {current}")


if __name__ == "__main__":
    main()
