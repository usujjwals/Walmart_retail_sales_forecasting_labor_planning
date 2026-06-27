SELECT COUNT(*) FROM raw_train_sales;
SELECT COUNT(*) FROM raw_features;
SELECT COUNT(*) FROM raw_stores;
SELECT COUNT(*) FROM raw_test_sales;

SELECT COUNT(*) FROM analytics_forecast_output;
SELECT COUNT(*) FROM analytics_model_comparison;
SELECT COUNT(*) FROM analytics_model_metrics;
SELECT COUNT(*) FROM analytics_labor_standards;
SELECT COUNT(*) FROM analytics_simulated_schedule;

SELECT COUNT(*) 
FROM mart_workforce_dashboard;

SELECT *
FROM mart_workforce_dashboard
LIMIT 20;