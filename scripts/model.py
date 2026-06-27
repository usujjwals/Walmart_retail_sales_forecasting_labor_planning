# scripts/01_train_forecast.py

import json
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


from xgboost import XGBRegressor

# ---------------------------------------------------------
# 1. Define project paths
# ---------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent

for _candidate in (SCRIPT_DIR, *SCRIPT_DIR.parents):
    if (_candidate / "data" / "raw").is_dir():
        BASE_DIR = _candidate
        break
else:
    raise FileNotFoundError(
        f"Could not find data/raw directory starting from {SCRIPT_DIR}"
    )

RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# 2. Load raw Walmart files
# ---------------------------------------------------------
def load_data():
    """
    Loads the Walmart sales forecasting dataset.

    train.csv:
        Weekly sales by Store, Dept, Date.

    features.csv:
        Store-level weekly features such as temperature, fuel price,
        markdowns, CPI, unemployment, and holiday flag.

    stores.csv:
        Store type and size.
    """

    train = pd.read_csv(RAW_DIR / "train.csv", parse_dates=["Date"])
    features = pd.read_csv(RAW_DIR / "features.csv", parse_dates=["Date"])
    stores = pd.read_csv(RAW_DIR / "stores.csv")

    return train, features, stores


# ---------------------------------------------------------
# 3. Clean and merge data
# ---------------------------------------------------------
def prepare_modeling_data(train, features, stores):
    """
    Creates one clean modeling table at this grain:

        Store + Dept + Date

    This table combines:
        - Weekly sales
        - Store type
        - Store size
        - Holiday flag
        - Economic features
        - Markdown features
    """

    # Merge sales with store information
    df = train.merge(stores, on="Store", how="left")

    # Merge with features using Store, Date, and IsHoliday
    df = df.merge(
        features,
        on=["Store", "Date", "IsHoliday"],
        how="left"
    )

    # Keep original sales for audit purposes
    df["Weekly_Sales_Original"] = df["Weekly_Sales"]

    # Negative sales can represent returns/corrections.
    # For labor planning, negative demand is not meaningful,
    # so we cap it at zero.
    df["Weekly_Sales"] = df["Weekly_Sales"].clip(lower=0)

    # Missing markdown values usually mean no markdown was active.
    markdown_cols = [
        "MarkDown1",
        "MarkDown2",
        "MarkDown3",
        "MarkDown4",
        "MarkDown5"
    ]

    for col in markdown_cols:
        df[col] = df[col].fillna(0)

    # Fill missing economic/weather values by store.
    # This keeps the trend stable without using future sales.
    df = df.sort_values(["Store", "Dept", "Date"])

    for col in ["Temperature", "Fuel_Price", "CPI", "Unemployment"]:
        df[col] = df.groupby("Store")[col].ffill().bfill()

    return df


# ---------------------------------------------------------
# 4. Create forecasting features
# ---------------------------------------------------------
def create_features(df):
    """
    Adds calendar, lag, and rolling sales features.

    Calendar features help the model understand seasonality.

    Lag features tell the model what sales were in previous weeks.

    Rolling features tell the model recent demand trends.
    """

    df = df.sort_values(["Store", "Dept", "Date"]).copy()

    # Calendar features
    df["year"] = df["Date"].dt.year
    df["month"] = df["Date"].dt.month
    df["weekofyear"] = df["Date"].dt.isocalendar().week.astype(int)
    df["quarter"] = df["Date"].dt.quarter
    df["is_december"] = (df["month"] == 12).astype(int)

    group_cols = ["Store", "Dept"]

    # Lag features
    for lag in [1, 2, 4, 13, 52]:
        df[f"lag_{lag}"] = (
            df.groupby(group_cols)["Weekly_Sales"]
            .shift(lag)
        )

    # Rolling averages based only on past values
    df["rolling_4_mean"] = (
        df.groupby(group_cols)["Weekly_Sales"]
        .transform(lambda s: s.shift(1).rolling(window=4, min_periods=1).mean())
    )

    df["rolling_13_mean"] = (
        df.groupby(group_cols)["Weekly_Sales"]
        .transform(lambda s: s.shift(1).rolling(window=13, min_periods=1).mean())
    )

    return df


# ---------------------------------------------------------
# 5. Create preprocessing pipeline
# ---------------------------------------------------------
def make_one_hot_encoder():
    """
    Handles sklearn version differences.

    Newer sklearn versions use sparse_output.
    Older sklearn versions use sparse.
    """

    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=True)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=True)


def build_preprocessor(numeric_features, categorical_features):
    """
    Builds preprocessing steps for numeric and categorical columns.
    """

    preprocessor = ColumnTransformer(
        transformers=[
            (
                "numeric",
                SimpleImputer(strategy="median"),
                numeric_features
            ),
            (
                "categorical",
                make_one_hot_encoder(),
                categorical_features
            )
        ]
    )

    return preprocessor


# ---------------------------------------------------------
# 6. Train Ridge and XGBoost models
# ---------------------------------------------------------
def train_models(df):
    """
    Trains two forecasting models:

        1. Ridge Regression
            - Fast
            - Easy to explain
            - Strong baseline model

        2. XGBoost Regressor
            - More powerful nonlinear model
            - Can capture complex patterns and feature interactions
            - Often strong for tabular data

    Holdout strategy:
        The last 13 weeks are used as a test set.
        This simulates forecasting future weeks.
    """

    max_date = df["Date"].max()
    holdout_start = max_date - pd.Timedelta(weeks=12)

    required_model_cols = [
        "lag_1",
        "lag_2",
        "lag_4",
        "lag_13",
        "lag_52",
        "rolling_4_mean",
        "rolling_13_mean"
    ]

    model_df = df.dropna(subset=required_model_cols).copy()

    train_df = model_df[model_df["Date"] < holdout_start].copy()
    holdout_df = model_df[model_df["Date"] >= holdout_start].copy()

    numeric_features = [
        "Size",
        "Temperature",
        "Fuel_Price",
        "CPI",
        "Unemployment",
        "MarkDown1",
        "MarkDown2",
        "MarkDown3",
        "MarkDown4",
        "MarkDown5",
        "year",
        "month",
        "weekofyear",
        "quarter",
        "is_december",
        "lag_1",
        "lag_2",
        "lag_4",
        "lag_13",
        "lag_52",
        "rolling_4_mean",
        "rolling_13_mean"
    ]

    categorical_features = [
        "Store",
        "Dept",
        "Type",
        "IsHoliday"
    ]

    features = numeric_features + categorical_features

    models = {
        "Ridge Regression": Ridge(alpha=1.0),

        "XGBoost Regressor": XGBRegressor(
            objective="reg:squarederror",
            n_estimators=2000,
            learning_rate=0.01,
            max_depth=6,
            min_child_weight=5,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
            tree_method="hist",
            eval_metric="mae"
        )
    }

    results = {}
    metrics_list = []

    for model_name, model in models.items():
        print(f"\nTraining model: {model_name}")

        preprocessor = build_preprocessor(
            numeric_features=numeric_features,
            categorical_features=categorical_features
        )

        pipeline = Pipeline(
            steps=[
                ("preprocess", preprocessor),
                ("model", model)
            ]
        )

        pipeline.fit(
            train_df[features],
            train_df["Weekly_Sales"]
        )

        model_holdout = holdout_df.copy()

        model_holdout["model_name"] = model_name

        model_holdout["forecast_weekly_sales"] = pipeline.predict(
            model_holdout[features]
        )

        # Forecasted sales cannot be negative for demand planning.
        model_holdout["forecast_weekly_sales"] = (
            model_holdout["forecast_weekly_sales"]
            .clip(lower=0)
        )

        model_holdout["forecast_error"] = (
            model_holdout["Weekly_Sales"]
            - model_holdout["forecast_weekly_sales"]
        )

        model_holdout["abs_forecast_error"] = (
            model_holdout["forecast_error"].abs()
        )

        model_holdout["forecast_variance_pct"] = np.where(
            model_holdout["forecast_weekly_sales"] > 0,
            model_holdout["forecast_error"] / model_holdout["forecast_weekly_sales"],
            np.nan
        )

        mae = mean_absolute_error(
            model_holdout["Weekly_Sales"],
            model_holdout["forecast_weekly_sales"]
        )

        wape = (
            model_holdout["abs_forecast_error"].sum()
            / model_holdout["Weekly_Sales"].sum()
        )

        metrics = {
            "model_name": model_name,
            "holdout_start": str(holdout_start.date()),
            "holdout_end": str(model_holdout["Date"].max().date()),
            "holdout_rows": int(len(model_holdout)),
            "mae": float(mae),
            "wape": float(wape)
        }

        metrics_list.append(metrics)

        results[model_name] = {
            "pipeline": pipeline,
            "holdout_df": model_holdout,
            "metrics": metrics
        }

        print(f"MAE:  {mae:.2f}")
        print(f"WAPE: {wape:.4f}")

    metrics_df = pd.DataFrame(metrics_list)

    best_model_name = (
        metrics_df
        .sort_values("wape", ascending=True)
        .iloc[0]["model_name"]
    )

    print("\nBest model based on lowest WAPE:")
    print(best_model_name)

    return results, metrics_df, best_model_name, holdout_start, features


# ---------------------------------------------------------
# 7. Export forecast outputs
# ---------------------------------------------------------
def clean_forecast_output(holdout_df):
    """
    Creates a database-friendly forecast output table.
    """

    forecast_output = holdout_df[
        [
            "model_name",
            "Store",
            "Dept",
            "Date",
            "Type",
            "Size",
            "IsHoliday",
            "Weekly_Sales",
            "forecast_weekly_sales",
            "forecast_error",
            "abs_forecast_error",
            "forecast_variance_pct",
            "Temperature",
            "Fuel_Price",
            "CPI",
            "Unemployment",
            "MarkDown1",
            "MarkDown2",
            "MarkDown3",
            "MarkDown4",
            "MarkDown5",
            "rolling_4_mean",
            "rolling_13_mean"
        ]
    ].copy()

    forecast_output = forecast_output.rename(
        columns={
            "Store": "store",
            "Dept": "dept",
            "Date": "date",
            "Type": "store_type",
            "Size": "store_size",
            "IsHoliday": "is_holiday",
            "Weekly_Sales": "actual_weekly_sales",
            "Temperature": "temperature",
            "Fuel_Price": "fuel_price",
            "CPI": "cpi",
            "Unemployment": "unemployment",
            "MarkDown1": "markdown1",
            "MarkDown2": "markdown2",
            "MarkDown3": "markdown3",
            "MarkDown4": "markdown4",
            "MarkDown5": "markdown5"
        }
    )

    return forecast_output


def export_forecast_output(results, metrics_df, best_model_name):
    """
    Exports:

        - Forecast output for Ridge
        - Forecast output for XGBoost
        - Combined forecast output
        - Best model forecast output
        - Model comparison metrics
        - Metrics JSON file
    """

    all_forecasts = []

    for model_name, result in results.items():
        holdout_df = result["holdout_df"]
        forecast_output = clean_forecast_output(holdout_df)

        safe_model_name = (
            model_name
            .lower()
            .replace(" ", "_")
            .replace("-", "_")
        )

        forecast_output.to_csv(
            PROCESSED_DIR / f"forecast_output_{safe_model_name}.csv",
            index=False
        )

        all_forecasts.append(forecast_output)

    combined_forecasts = pd.concat(all_forecasts, ignore_index=True)

    combined_forecasts.to_csv(
        PROCESSED_DIR / "forecast_output_all_models.csv",
        index=False
    )

    best_forecast_output = clean_forecast_output(
        results[best_model_name]["holdout_df"]
    )

    # This keeps your old downstream file name working.
    # It now contains the best model's forecast.
    best_forecast_output.to_csv(
        PROCESSED_DIR / "forecast_output.csv",
        index=False
    )

    metrics_df = metrics_df.sort_values("wape", ascending=True)

    metrics_df.to_csv(
        PROCESSED_DIR / "model_comparison.csv",
        index=False
    )

    metrics_df.to_csv(
        PROCESSED_DIR / "model_metrics.csv",
        index=False
    )

    metrics_json = {
        "best_model": best_model_name,
        "models": metrics_df.to_dict(orient="records")
    }

    with open(PROCESSED_DIR / "model_metrics.json", "w") as f:
        json.dump(metrics_json, f, indent=4)

    print("\nModel Comparison")
    print("----------------")
    print(metrics_df.to_string(index=False))

    print("\nExported:")
    print("data/processed/forecast_output.csv")
    print("data/processed/forecast_output_ridge_regression.csv")
    print("data/processed/forecast_output_xgboost_regressor.csv")
    print("data/processed/forecast_output_all_models.csv")
    print("data/processed/model_comparison.csv")
    print("data/processed/model_metrics.csv")
    print("data/processed/model_metrics.json")


# ---------------------------------------------------------
# 8. Main function
# ---------------------------------------------------------
def main():
    train, features, stores = load_data()

    df = prepare_modeling_data(
        train=train,
        features=features,
        stores=stores
    )

    df = create_features(df)

    results, metrics_df, best_model_name, holdout_start, model_features = train_models(df)

    export_forecast_output(
        results=results,
        metrics_df=metrics_df,
        best_model_name=best_model_name
    )


if __name__ == "__main__":
    main()