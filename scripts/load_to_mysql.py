# scripts/03_load_to_mysql.py

from pathlib import Path
import os

import pandas as pd

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


BASE_DIR = Path(__file__).resolve().parents[1]

RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
SIMULATED_DIR = BASE_DIR / "data" / "simulated"
SQL_DIR = BASE_DIR / "sql"


def get_engine():
    """
    Connects to MySQL using the .env file.
    """

    load_dotenv(BASE_DIR / ".env",override=True)

    url = URL.create(
        drivername="mysql+pymysql",
        username=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD") or None,
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.getenv("MYSQL_DATABASE")
    )

    return create_engine(url)


def run_sql_file(engine, sql_file):
    """
    Runs a SQL file statement by statement.

    This is safer for MySQL because MySQL can have issues
    executing multiple statements in one call.
    """

    sql_path = SQL_DIR / sql_file

    with open(sql_path, "r") as file:
        sql = file.read()

    statements = [
        statement.strip()
        for statement in sql.split(";")
        if statement.strip()
    ]

    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))

    print(f"Executed {sql_file}")


def clean_column_names(df):
    """
    Makes column names database-friendly.
    """

    df.columns = (
        df.columns
        .str.strip()
        .str.replace(" ", "_")
        .str.replace("-", "_")
        .str.replace("/", "_")
        .str.lower()
    )

    return df


def normalize_bool_columns(df):
    """
    Converts boolean columns into 1/0 for MySQL compatibility.
    """

    for col in df.columns:
        if df[col].dtype == "bool":
            df[col] = df[col].astype(int)

    if "is_holiday" in df.columns:
        df["is_holiday"] = (
            df["is_holiday"]
            .astype(str)
            .str.lower()
            .map(
                {
                    "true": 1,
                    "false": 0,
                    "1": 1,
                    "0": 0
                }
            )
            .fillna(0)
            .astype(int)
        )

    return df


def load_csv_to_mysql(engine, csv_path, table_name, parse_dates=None):
    """
    Loads a CSV file into a MySQL table.
    """

    print(f"Loading {csv_path} into {table_name}")

    df = pd.read_csv(csv_path, parse_dates=parse_dates)
    df = clean_column_names(df)
    df = normalize_bool_columns(df)

    df.to_sql(
        name=table_name,
        con=engine,
        if_exists="replace",
        index=False,
        chunksize=50000
    )

    print(f"Loaded {len(df):,} rows into {table_name}")


def main():
    engine = get_engine()

    # Drop existing MySQL views and tables.
    run_sql_file(engine, "01_drop_existing_mysql.sql")

    # Load raw Walmart data.
    load_csv_to_mysql(
        engine=engine,
        csv_path=RAW_DIR / "train.csv",
        table_name="raw_train_sales",
        parse_dates=["Date"]
    )

    load_csv_to_mysql(
        engine=engine,
        csv_path=RAW_DIR / "features.csv",
        table_name="raw_features",
        parse_dates=["Date"]
    )

    load_csv_to_mysql(
        engine=engine,
        csv_path=RAW_DIR / "stores.csv",
        table_name="raw_stores"
    )

    load_csv_to_mysql(
        engine=engine,
        csv_path=RAW_DIR / "test.csv",
        table_name="raw_test_sales",
        parse_dates=["Date"]
    )

    # Load the official best forecast.
    # This should be your XGBoost forecast output.
    load_csv_to_mysql(
        engine=engine,
        csv_path=PROCESSED_DIR / "forecast_output_best.csv",
        table_name="analytics_forecast_output",
        parse_dates=["date"]
    )

    # Load model comparison so you can prove XGBoost was selected.
    load_csv_to_mysql(
        engine=engine,
        csv_path=PROCESSED_DIR / "model_comparison.csv",
        table_name="analytics_model_comparison"
    )

    # Load model metrics if available.
    load_csv_to_mysql(
        engine=engine,
        csv_path=PROCESSED_DIR / "model_metrics.csv",
        table_name="analytics_model_metrics"
    )

    # Load simulated workforce inputs.
    load_csv_to_mysql(
        engine=engine,
        csv_path=SIMULATED_DIR / "labor_standards.csv",
        table_name="analytics_labor_standards"
    )

    load_csv_to_mysql(
        engine=engine,
        csv_path=SIMULATED_DIR / "simulated_schedule.csv",
        table_name="analytics_simulated_schedule",
        parse_dates=["date"]
    )

    # Create indexes and mart views.
    run_sql_file(engine, "03_create_indexes_mysql.sql")
    run_sql_file(engine, "02_create_mart_views_mysql.sql")

    print("\nMySQL build complete.")
    print("Main Tableau view: mart_workforce_dashboard")


if __name__ == "__main__":
    main()