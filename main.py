import matplotlib.pyplot as plt

from dehumidifier_adviser import OpenMeteoClient

# Initialize client and get forecast
client = OpenMeteoClient()
forecast = client.get_humidity_forecast(latitude=51.5074, longitude=-0.1278, forecast_days=7)

print(f"Forecast for {forecast.latitude}, {forecast.longitude}")
print(f"Timezone: {forecast.timezone}")

# Get current conditions
current = client.get_current_humidity(latitude=51.5074, longitude=-0.1278)
print(f"\nCurrent conditions: {current}")

# Convert forecast data to DataFrames
if forecast.hourly:
    hourly_df = forecast.hourly.to_dataframe()
    print(f"\nHourly forecast: {len(hourly_df)} hours")

if forecast.daily:
    daily_df = forecast.daily.to_dataframe()
    print(f"Daily forecast: {len(daily_df)} days")

# Create plots
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
fig.suptitle(f"Humidity Forecast - {forecast.latitude}, {forecast.longitude}", fontsize=14, fontweight="bold")

# Plot 1: Hourly relative humidity and dew point
if forecast.hourly:
    ax1.plot(hourly_df["time"], hourly_df["relative_humidity_2m"], label="Relative Humidity", color="blue", linewidth=2)
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
