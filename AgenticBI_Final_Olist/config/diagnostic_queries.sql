-- Diagnostic SQL templates for Member B.
-- These queries are intended for the SQL/analysis agent to support drill-down answers.

-- 1) Delivery delay vs national baseline by customer state.
SELECT
  d.customer_state,
  AVG(d.avg_delivery_days) AS avg_delivery_days,
  AVG(d.on_time_rate) AS on_time_rate,
  SUM(d.delayed_orders) AS delayed_orders,
  n.national_avg_delivery_days,
  n.national_on_time_rate,
  AVG(d.avg_delivery_days) - n.national_avg_delivery_days AS delivery_days_vs_national
FROM mv_delivery_perf d
CROSS JOIN (
  SELECT
    AVG(avg_delivery_days) AS national_avg_delivery_days,
    AVG(on_time_rate) AS national_on_time_rate
  FROM mv_delivery_perf
) n
GROUP BY d.customer_state, n.national_avg_delivery_days, n.national_on_time_rate
ORDER BY delivery_days_vs_national DESC, on_time_rate ASC
LIMIT 20;

-- 2) Lowest-rated sellers using the pre-aggregated seller performance view.
SELECT
  seller_id,
  seller_state,
  SUM(total_orders) AS total_orders,
  SUM(total_gmv) AS total_gmv,
  AVG(avg_review_score) AS avg_review_score,
  AVG(CASE WHEN avg_review_score <= 2 THEN 1 ELSE 0 END) AS low_score_month_ratio
FROM mv_seller_perf
GROUP BY seller_id, seller_state
HAVING total_orders >= 5
ORDER BY avg_review_score ASC, total_orders DESC
LIMIT 20;

-- 3) Top bad-review categories for category-level diagnostic drill-down.
SELECT
  COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS product_category_english,
  COUNT(DISTINCT o.order_id) AS reviewed_orders,
  AVG(r.review_score) AS avg_review_score,
  AVG(CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END) AS bad_review_rate,
  SUM(CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END) AS bad_review_orders
FROM order_reviews r
JOIN orders o ON o.order_id = r.order_id
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN product_category_name_translation t
  ON t.product_category_name = p.product_category_name
WHERE r.review_score IS NOT NULL
GROUP BY 1
HAVING reviewed_orders >= 30
ORDER BY bad_review_rate DESC, bad_review_orders DESC
LIMIT 10;

-- 4) Delivery geography drill-down: customer state x seller state.
SELECT
  c.customer_state,
  s.seller_state,
  COUNT(DISTINCT o.order_id) AS total_orders,
  AVG(DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp)) AS avg_delivery_days,
  AVG(CASE WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN 1 ELSE 0 END) AS on_time_rate
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
JOIN sellers s ON s.seller_id = oi.seller_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_estimated_delivery_date IS NOT NULL
GROUP BY c.customer_state, s.seller_state
HAVING total_orders >= 20
ORDER BY avg_delivery_days DESC, total_orders DESC
LIMIT 50;
