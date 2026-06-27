-- nodel comparison
SELECT *
FROM analytics_model_comparison
ORDER BY wape ASC;

-- Find top overtime-risk stores, Which stores create the highest labor risk?
SELECT
    store,
    store_type,
    SUM(overtime_risk_hours) AS total_overtime_risk_hours,
    SUM(estimated_overtime_cost) AS total_estimated_overtime_cost,
    AVG(site_readiness_score) AS avg_site_readiness_score
FROM mart_workforce_dashboard
GROUP BY
    store,
    store_type
ORDER BY total_estimated_overtime_cost DESC
LIMIT 10;

-- Find top at-risk store-department weeks

SELECT
    week_date,
    store,
    dept,
    store_type,
    forecast_weekly_sales,
    required_labor_hours,
    available_labor_hours,
    labor_gap_hours,
    overtime_risk_hours,
    estimated_overtime_cost,
    site_readiness_score,
    recommendation
FROM mart_workforce_dashboard
WHERE overtime_risk_hours > 0
ORDER BY estimated_overtime_cost DESC
LIMIT 20;

-- Forecast accuracy by department
SELECT
    dept,
    SUM(actual_weekly_sales) AS actual_weekly_sales,
    SUM(forecast_weekly_sales) AS forecast_weekly_sales,
    SUM(abs_forecast_error) AS abs_forecast_error,
    SUM(abs_forecast_error) / NULLIF(SUM(actual_weekly_sales), 0) AS wape
FROM mart_workforce_dashboard
GROUP BY dept
ORDER BY wape DESC
LIMIT 15;

-- Weekly labor trend
SELECT
    week_date,
    SUM(required_labor_hours) AS required_labor_hours,
    SUM(available_labor_hours) AS available_labor_hours,
    SUM(labor_gap_hours) AS labor_gap_hours,
    SUM(overtime_risk_hours) AS overtime_risk_hours,
    SUM(estimated_overtime_cost) AS estimated_overtime_cost
FROM mart_workforce_dashboard
GROUP BY week_date
ORDER BY week_date;








