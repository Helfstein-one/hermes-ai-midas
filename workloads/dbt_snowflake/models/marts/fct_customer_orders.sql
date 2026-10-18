-- dbt Model: fct_customer_orders
-- Materialization: incremental
-- Target Platform: Snowflake Virtual Warehouse (Baseline 2X-Large -> Optimized Medium)

{{
    config(
        materialized='table',
        tags=['finance', 'daily_marts']
    )
}}

WITH raw_orders AS (
    SELECT *
    FROM raw_vault.orders
),

raw_customers AS (
    SELECT *
    FROM raw_vault.customers
),

joined AS (
    SELECT
        raw_orders.order_id,
        raw_customers.customer_id,
        raw_orders.order_total,
        raw_customers.customer_segment
    FROM raw_orders, raw_customers
)

SELECT *
FROM joined
