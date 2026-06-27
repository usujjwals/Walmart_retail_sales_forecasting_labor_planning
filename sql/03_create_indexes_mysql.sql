CREATE INDEX idx_forecast_store_dept_date
ON analytics_forecast_output (store, dept, date);

CREATE INDEX idx_labor_standards_dept
ON analytics_labor_standards (dept);

CREATE INDEX idx_schedule_store_dept_date
ON analytics_simulated_schedule (store, dept, date);