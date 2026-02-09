"""Predefined scenarios for humidity simulation."""

import pandas as pd

from humidity_simulator_client.models import HumiditySource

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"
TIMEZONE = "UTC"
DEFAULT_SIMULATION_DAYS = 7
DEFAULT_TIME_RESOLUTION = "15min"


def _build_scenario_df(start_date: pd.Timestamp, days: int, time_resolution: str) -> pd.DataFrame:
    """Build a DataFrame with a datetime index and calendar metadata columns.

    Args:
        start_date: First day of the simulation.
        days: Number of days to simulate.
        time_resolution: Frequency string for the datetime index (e.g. "15min", "30min").

    Returns:
        DataFrame indexed by datetime with columns: is_weekday, hour, minute.
    """
    end = start_date + pd.Timedelta(days=days) - pd.Timedelta(time_resolution)
    index = pd.date_range(start=start_date, end=end, freq=time_resolution)

    df = pd.DataFrame(index=index)
    df["is_weekday"] = df.index.dayofweek < 5  # type: ignore[union-attr]
    df["hour"] = df.index.hour  # type: ignore[union-attr]
    df["minute"] = df.index.minute  # type: ignore[union-attr]
    return df


def _series_to_source(series: pd.Series, name: str) -> HumiditySource:  # type: ignore[type-arg]
    """Convert a non-null pandas Series into a HumiditySource."""
    non_null = series.dropna()
    return HumiditySource(
        name=name,
        max_emissions_rate_unit="g/h",
        timestamps=[ts.strftime(TIMESTAMP_FORMAT) for ts in non_null.index],
        timestamp_format=TIMESTAMP_FORMAT,
        timezone=TIMEZONE,
        values=non_null.tolist(),
        values_unit="g/h",
    )


def scenario_one_bed_flat(
    start_date: pd.Timestamp,
    days: int = DEFAULT_SIMULATION_DAYS,
    time_resolution: str = DEFAULT_TIME_RESOLUTION,
) -> list[HumiditySource]:
    """1 Bed Flat: single occupant over the given number of days.

    Weekdays (Mon-Fri): shower at 07:00, work from home, cook dinner.
    Weekends (Sat-Sun): shower at 09:00, no cooking.
    Breathing is constant throughout.
    """
    df = _build_scenario_df(start_date, days, time_resolution)

    # Breathing: constant 80 g/h at all times
    flat_occupation = df["is_weekday"] | ((df["hour"] < 12) & ~df["is_weekday"])
    df["breathing"] = 0
    df.loc[flat_occupation, "breathing"] = 80.0

    # Shower: 15-min burst (weekday 07:00-07:15, weekend 09:00-09:15)
    weekday_shower = df["is_weekday"] & (df["hour"] == 7) & (df["minute"].isin([0, 15]))
    weekend_shower = ~df["is_weekday"] & (df["hour"] == 9) & (df["minute"].isin([0, 15]))
    df["shower"] = pd.NA
    df.loc[weekday_shower | weekend_shower, "shower"] = 1200.0

    # Cooking: weekday evenings 18:00-19:00
    weekday_cooking = df["is_weekday"] & (df["hour"] >= 18) & (df["hour"] < 19)
    df["cooking"] = pd.NA
    df.loc[weekday_cooking, "cooking"] = 600.0

    return [
        _series_to_source(df["breathing"], "Breathing (1 person)"),
        _series_to_source(df["shower"], "Shower"),
        _series_to_source(df["cooking"], "Cooking (Dinner)"),
    ]


SCENARIO_FACTORIES = {
    "1 Bed Flat": scenario_one_bed_flat,
}
