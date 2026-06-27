CREATE OR REPLACE VIEW mart_workforce_dashboard AS
WITH base AS (
    SELECT
        f.store,
        f.dept,
        DATE(f.date) AS week_date,
        f.store_type,
        f.store_size,
        f.is_holiday,

        f.actual_weekly_sales,
        f.forecast_weekly_sales,
        f.forecast_error,
        f.abs_forecast_error,
        f.forecast_variance_pct,

        f.temperature,
        f.fuel_price,
        f.cpi,
        f.unemployment,
        f.markdown1,
        f.markdown2,
        f.markdown3,
        f.markdown4,
        f.markdown5,

        ls.volume_tier,
        ls.target_sales_per_labor_hour,

        sch.scheduled_labor_hours,
        sch.scheduled_associates,
        sch.callout_rate,
        sch.flex_pool_hours,
        sch.avg_hourly_rate,
        sch.avg_weekly_hours_per_associate

    FROM analytics_forecast_output f

    LEFT JOIN analytics_labor_standards ls
        ON f.dept = ls.dept

    LEFT JOIN analytics_simulated_schedule sch
        ON f.store = sch.store
       AND f.dept = sch.dept
       AND DATE(f.date) = DATE(sch.date)
),

labor_metrics AS (
    SELECT
        base.*,

        forecast_weekly_sales / NULLIF(target_sales_per_labor_hour, 0)
            AS required_labor_hours,

        CEIL(
            (
                forecast_weekly_sales / NULLIF(target_sales_per_labor_hour, 0)
            )
            / NULLIF(avg_weekly_hours_per_associate, 0)
        ) AS required_associates,

        scheduled_labor_hours * (1 - callout_rate)
            AS available_labor_hours

    FROM base
),

gap_metrics AS (
    SELECT
        labor_metrics.*,

        required_labor_hours - available_labor_hours
            AS labor_gap_hours,

        CEIL(
            (required_labor_hours - available_labor_hours)
            / NULLIF(avg_weekly_hours_per_associate, 0)
        ) AS labor_gap_associates,

        available_labor_hours / NULLIF(required_labor_hours, 0)
            AS coverage_pct,

        GREATEST(
            required_labor_hours - available_labor_hours - flex_pool_hours,
            0
        ) AS overtime_risk_hours,

        GREATEST(
            required_labor_hours - available_labor_hours - flex_pool_hours,
            0
        ) * avg_hourly_rate * 1.5
            AS estimated_overtime_cost,

        actual_weekly_sales / NULLIF(available_labor_hours, 0)
            AS productivity_sales_per_labor_hour,

        (
            actual_weekly_sales / NULLIF(available_labor_hours, 0)
        )
        / NULLIF(target_sales_per_labor_hour, 0)
            AS productivity_to_target_pct

    FROM labor_metrics
),

scored AS (
    SELECT
        gap_metrics.*,

        LEAST(COALESCE(coverage_pct, 0), 1.10) / 1.10 * 40
            AS coverage_score,

        GREATEST(
            0,
            1 - LEAST(
                COALESCE(abs_forecast_error / NULLIF(actual_weekly_sales, 0), 1),
                1
            )
        ) * 25
            AS forecast_accuracy_score,

        LEAST(COALESCE(productivity_to_target_pct, 0), 1.10) / 1.10 * 25
            AS productivity_score,

        CASE
            WHEN is_holiday = 1 THEN 5
            ELSE 10
        END AS holiday_risk_score

    FROM gap_metrics
)

SELECT
    store,
    dept,
    week_date,
    store_type,
    store_size,
    is_holiday,

    actual_weekly_sales,
    forecast_weekly_sales,
    forecast_error,
    abs_forecast_error,
    forecast_variance_pct,

    temperature,
    fuel_price,
    cpi,
    unemployment,
    markdown1,
    markdown2,
    markdown3,
    markdown4,
    markdown5,

    volume_tier,
    target_sales_per_labor_hour,

    required_labor_hours,
    required_associates,

    scheduled_labor_hours,
    scheduled_associates,
    callout_rate,
    available_labor_hours,
    flex_pool_hours,

    labor_gap_hours,
    labor_gap_associates,
    coverage_pct,

    overtime_risk_hours,

    CASE
        WHEN overtime_risk_hours > 0 THEN 'At Risk'
        ELSE 'Covered'
    END AS overtime_risk_flag,

    avg_hourly_rate,
    estimated_overtime_cost,

    productivity_sales_per_labor_hour,
    productivity_to_target_pct,

    ROUND(
        LEAST(
            100,
            GREATEST(
                0,
                coverage_score
                + forecast_accuracy_score
                + productivity_score
                + holiday_risk_score
            )
        ),
        1
    ) AS site_readiness_score,

    CASE
        WHEN
            LEAST(
                100,
                GREATEST(
                    0,
                    coverage_score
                    + forecast_accuracy_score
                    + productivity_score
                    + holiday_risk_score
                )
            ) >= 85
        THEN 'Ready'

        WHEN
            LEAST(
                100,
                GREATEST(
                    0,
                    coverage_score
                    + forecast_accuracy_score
                    + productivity_score
                    + holiday_risk_score
                )
            ) >= 70
        THEN 'Watch'

        ELSE 'At Risk'
    END AS site_readiness_status,

CASE
    WHEN labor_gap_hours >= 24
        THEN 'Add associates or approve overtime'

    WHEN labor_gap_hours >= 8
        THEN 'Use flex pool / monitor schedule'

    WHEN labor_gap_hours <= -24
        THEN 'Potential overstaffing - review schedule'

    ELSE 'Staffing balanced'
END AS recommendation

FROM scored;


CREATE OR REPLACE VIEW mart_store_week_summary AS
SELECT
    week_date,
    store,
    store_type,

    SUM(actual_weekly_sales) AS actual_weekly_sales,
    SUM(forecast_weekly_sales) AS forecast_weekly_sales,

    SUM(required_labor_hours) AS required_labor_hours,
    SUM(scheduled_labor_hours) AS scheduled_labor_hours,
    SUM(available_labor_hours) AS available_labor_hours,

    SUM(labor_gap_hours) AS labor_gap_hours,
    SUM(overtime_risk_hours) AS overtime_risk_hours,
    SUM(estimated_overtime_cost) AS estimated_overtime_cost,

    AVG(coverage_pct) AS avg_coverage_pct,
    AVG(site_readiness_score) AS avg_site_readiness_score,

    SUM(
        CASE
            WHEN overtime_risk_flag = 'At Risk' THEN 1
            ELSE 0
        END
    ) AS at_risk_dept_count

FROM mart_workforce_dashboard
GROUP BY
    week_date,
    store,
    store_type;


CREATE OR REPLACE VIEW mart_forecast_accuracy_summary AS
SELECT
    store,
    dept,
    store_type,

    SUM(actual_weekly_sales) AS actual_weekly_sales,
    SUM(forecast_weekly_sales) AS forecast_weekly_sales,

    SUM(abs_forecast_error) AS abs_forecast_error,

    SUM(abs_forecast_error)
        / NULLIF(SUM(actual_weekly_sales), 0)
        AS wape,

    SUM(forecast_error)
        / NULLIF(SUM(actual_weekly_sales), 0)
        AS forecast_bias_pct

FROM mart_workforce_dashboard
GROUP BY
    store,
    dept,
    store_type;


CREATE OR REPLACE VIEW mart_top_at_risk_store_depts AS
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
ORDER BY
    estimated_overtime_cost DESC;