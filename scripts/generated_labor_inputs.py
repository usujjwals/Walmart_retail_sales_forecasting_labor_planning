# scripts/02_generate_labor_inputs_from_best_forecast.py

from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------
# Purpose:
# This script uses the best forecast output, which should be
# your XGBoost forecast file, and creates two workforce inputs:
#
# 1. labor_standards.csv
#    - target sales per labor hour by department
#
# 2. simulated_schedule.csv
#    - simulated scheduled labor hours by store, department, week
#
# These are simulated because the Walmart Kaggle dataset does
# not include real employee schedules or labor hours.
# ---------------------------------------------------------


BASE_DIR = Path(__file__).resolve().parents[1]

RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
SIMULATED_DIR = BASE_DIR / "data" / "simulated"

SIMULATED_DIR.mkdir(parents=True, exist_ok=True)


def standardize_columns(df):
    """
    Converts column names into clean lowercase snake_case names.
    This helps avoid errors if one model output used slightly different names.
    """

    df.columns = (
        df.columns
        .str.strip()
        .str.replace(" ", "_")
        .str.replace("-", "_")
        .str.lower()
    )

    return df


def create_labor_standards():
    """
    Creates department-level labor productivity assumptions.

    Since the public Walmart dataset does not include labor-hour data,
    we create simulated productivity standards based on department sales volume.

    Logic:
        High-volume departments get higher sales-per-labor-hour targets.
        Low-volume departments get lower sales-per-labor-hour targets.

    Output:
        data/simulated/labor_standards.csv
    """

    train = pd.read_csv(RAW_DIR / "train.csv")
    train = standardize_columns(train)

    # For labor planning, negative sales are not meaningful demand.
    train["weekly_sales"] = train["weekly_sales"].clip(lower=0)

    dept_stats = (
        train.groupby("dept", as_index=False)
        .agg(
            median_weekly_sales=("weekly_sales", "median"),
            avg_weekly_sales=("weekly_sales", "mean")
        )
    )

    low_cutoff = dept_stats["median_weekly_sales"].quantile(0.33)
    high_cutoff = dept_stats["median_weekly_sales"].quantile(0.66)

    def assign_volume_tier(median_sales):
        if median_sales >= high_cutoff:
            return "High Volume"
        elif median_sales >= low_cutoff:
            return "Medium Volume"
        else:
            return "Low Volume"

    dept_stats["volume_tier"] = (
        dept_stats["median_weekly_sales"]
        .apply(assign_volume_tier)
    )

    def assign_target_sales_per_labor_hour(volume_tier):
        if volume_tier == "High Volume":
            return 1250.00
        elif volume_tier == "Medium Volume":
            return 950.00
        else:
            return 700.00

    dept_stats["target_sales_per_labor_hour"] = (
        dept_stats["volume_tier"]
        .apply(assign_target_sales_per_labor_hour)
    )

    labor_standards = dept_stats[
        [
            "dept",
            "volume_tier",
            "target_sales_per_labor_hour"
        ]
    ]

    output_path = SIMULATED_DIR / "labor_standards.csv"
    labor_standards.to_csv(output_path, index=False)

    print(f"Created {output_path}")


def create_simulated_schedule():
    """
    Creates a simulated schedule table using the best forecast output.

    Grain:
        store + dept + date

    Schedule logic:
        Scheduled labor is based on recent rolling sales trend,
        store type, holiday flag, and department labor standard.

    Output:
        data/simulated/simulated_schedule.csv
    """

    forecast_path = PROCESSED_DIR / "forecast_output_best.csv"

    forecast = pd.read_csv(forecast_path, parse_dates=["date"])
    forecast = standardize_columns(forecast)

    labor_standards = pd.read_csv(SIMULATED_DIR / "labor_standards.csv")
    labor_standards = standardize_columns(labor_standards)

    df = forecast.merge(
        labor_standards,
        on="dept",
        how="left"
    )

    # Average weekly hours per associate.
    avg_weekly_hours_per_associate = 32

    # Larger Type A stores are planned closer to expected demand.
    coverage_factor_by_store_type = {
        "A": 0.98,
        "B": 0.95,
        "C": 0.92
    }

    # Simulated hourly wage assumptions.
    wage_by_store_type = {
        "A": 18.50,
        "B": 17.50,
        "C": 16.75
    }

    df["planning_coverage_factor"] = (
        df["store_type"]
        .map(coverage_factor_by_store_type)
        .fillna(0.95)
    )

    df["holiday_schedule_factor"] = np.where(
        df["is_holiday"].astype(str).str.lower().isin(["true", "1"]),
        1.06,
        1.00
    )

    # Use rolling 4-week sales trend as the schedule planning baseline.
    # If rolling_4_mean is missing, fall back to forecast_weekly_sales.
    df["schedule_baseline_sales"] = (
        df["rolling_4_mean"]
        .fillna(df["forecast_weekly_sales"])
    )

    df["scheduled_labor_hours"] = (
        df["schedule_baseline_sales"]
        / df["target_sales_per_labor_hour"]
        * df["planning_coverage_factor"]
        * df["holiday_schedule_factor"]
    )

    df["scheduled_labor_hours"] = df["scheduled_labor_hours"].clip(lower=0)

    df["scheduled_associates"] = np.ceil(
        df["scheduled_labor_hours"]
        / avg_weekly_hours_per_associate
    ).astype(int)

    df["callout_rate"] = np.where(
        df["is_holiday"].astype(str).str.lower().isin(["true", "1"]),
        0.075,
        0.045
    )

    df["flex_pool_hours"] = df["scheduled_labor_hours"] * 0.05

    df["avg_hourly_rate"] = (
        df["store_type"]
        .map(wage_by_store_type)
        .fillna(17.50)
    )

    df["avg_weekly_hours_per_associate"] = avg_weekly_hours_per_associate

    schedule = df[
        [
            "store",
            "dept",
            "date",
            "scheduled_labor_hours",
            "scheduled_associates",
            "callout_rate",
            "flex_pool_hours",
            "avg_hourly_rate",
            "avg_weekly_hours_per_associate"
        ]
    ]

    output_path = SIMULATED_DIR / "simulated_schedule.csv"
    schedule.to_csv(output_path, index=False)

    print(f"Created {output_path}")


def main():
    create_labor_standards()
    create_simulated_schedule()


if __name__ == "__main__":
    main()