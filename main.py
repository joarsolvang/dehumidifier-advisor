"""Usage examples for dehumidifier-adviser with geocoding."""

import matplotlib.pyplot as plt

from dehumidifier_adviser import Geocoder, GeocodingError, OpenMeteoClient

# Example 1: Forward geocoding + weather forecast
print("=" * 70)
print("Example 1: Forward Geocoding + Weather Forecast")
print("=" * 70)

geocoder = Geocoder()
client = OpenMeteoClient()

try:
    # Convert city name to coordinates
    location = geocoder.forward_geocode(city="London", country="United Kingdom")
    print(f"\nFound: {location.city}, {location.country}")
    print(f"Coordinates: {location.latitude:.4f}, {location.longitude:.4f}")
    print(f"Full address: {location.display_name}")

    # Get weather forecast for that location
    forecast = client.get_humidity_forecast(latitude=location.latitude, longitude=location.longitude, forecast_days=7)

    print(f"\nWeather forecast for {location.city}:")
    print(f"Timezone: {forecast.timezone}")
    print(f"Elevation: {forecast.elevation}m")

    # Get current conditions
    current = client.get_current_humidity(latitude=location.latitude, longitude=location.longitude)
    if current.get("relative_humidity_2m") is not None:
        print(f"Current humidity: {current['relative_humidity_2m']}%")

except GeocodingError as e:
    print(f"Geocoding error: {e}")

# Example 2: Reverse geocoding
print("\n" + "=" * 70)
print("Example 2: Reverse Geocoding")
print("=" * 70)

try:
    # Convert coordinates to city name
    location = geocoder.reverse_geocode(latitude=40.7128, longitude=-74.0060)
    print(f"\nLocation: {location.city}, {location.country}")
    if location.state:
        print(f"State: {location.state}")
    print(f"Full address: {location.display_name}")

except GeocodingError as e:
    print(f"Geocoding error: {e}")

# Example 3: Multiple cities comparison
print("\n" + "=" * 70)
print("Example 3: Multiple Cities Humidity Comparison")
print("=" * 70)

cities = [
    ("London", "United Kingdom"),
    ("New York", "United States", "New York"),
    ("Tokyo", "Japan"),
    ("Sydney", "Australia"),
]

print("\nCurrent humidity levels:")
for city_data in cities:
    try:
        if len(city_data) == 3:
            location = geocoder.forward_geocode(city=city_data[0], country=city_data[1], state=city_data[2])
        else:
            location = geocoder.forward_geocode(city=city_data[0], country=city_data[1])

        current = client.get_current_humidity(latitude=location.latitude, longitude=location.longitude)

        humidity = current.get("relative_humidity_2m", "N/A")
        print(f"  {location.city}: {humidity}%")

    except GeocodingError as e:
        print(f"  {city_data[0]}: Error - {e}")

# Example 4: Visualization with geocoding
print("\n" + "=" * 70)
print("Example 4: Creating Visualization for London")
print("=" * 70)

try:
    location = geocoder.forward_geocode(city="London", country="UK")
    forecast = client.get_humidity_forecast(latitude=location.latitude, longitude=location.longitude, forecast_days=7)

    # Convert to DataFrames
    if forecast.hourly:
        hourly_df = forecast.hourly.to_dataframe()
        print(f"\nHourly forecast: {len(hourly_df)} hours")

    if forecast.daily:
        daily_df = forecast.daily.to_dataframe()
        print(f"Daily forecast: {len(daily_df)} days")

    # Create plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle(f"Humidity Forecast - {location.city}, {location.country}", fontsize=14, fontweight="bold")

    # Plot 1: Hourly relative humidity and dew point
    if forecast.hourly:
        ax1.plot(
            hourly_df["time"],
            hourly_df["relative_humidity_2m"],
            label="Relative Humidity",
            color="blue",
            linewidth=2,
        )
        ax1_twin = ax1.twinx()
        ax1_twin.plot(hourly_df["time"], hourly_df["dew_point_2m"], label="Dew Point", color="orange", linewidth=2)

        ax1.set_xlabel("Time")
        ax1.set_ylabel("Relative Humidity (%)", color="blue")
        ax1_twin.set_ylabel("Dew Point (°C)", color="orange")
        ax1.tick_params(axis="y", labelcolor="blue")
        ax1_twin.tick_params(axis="y", labelcolor="orange")
        ax1.grid(visible=True, alpha=0.3)
        ax1.set_title("Hourly Forecast")

        # Add legends
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax1_twin.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    # Plot 2: Daily humidity ranges
    if forecast.daily:
        days = daily_df["time"]
        mean_humidity = daily_df["relative_humidity_2m_mean"]
        min_humidity = daily_df["relative_humidity_2m_min"]
        max_humidity = daily_df["relative_humidity_2m_max"]

        ax2.plot(days, mean_humidity, label="Mean", color="green", linewidth=2, marker="o")
        ax2.fill_between(days, min_humidity, max_humidity, alpha=0.3, color="green", label="Min-Max Range")

        ax2.set_xlabel("Date")
        ax2.set_ylabel("Relative Humidity (%)")
        ax2.set_title("Daily Humidity Range")
        ax2.legend(loc="upper left")
        ax2.grid(visible=True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("humidity_forecast.png", dpi=150, bbox_inches="tight")
    print("\nPlot saved as 'humidity_forecast.png'")
    plt.show()

except GeocodingError as e:
    print(f"Geocoding error: {e}")
