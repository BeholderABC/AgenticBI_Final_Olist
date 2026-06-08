# 预聚合视图设计

## 1. 设计动机

Olist 数据集包含 9 张业务表，Agent 在回答「月度 GMV」「各州销售排名」「配送准时率」等高频问题时，若每次都从原始表执行多表 JOIN + GROUP BY，将产生巨大的中间结果集和查询延迟。在 Agent 频繁调用数据的 Agentic BI 场景下，这会导致 Web 端响应超时（>60s）。

为此，本项目在 MySQL 中构建 **Pre-Aggregation 预聚合加速层**：将高频分析维度预先计算并物化为物理表（Materialized Table），Agent 查询时优先命中视图，仅在视图无法覆盖时才回退原始表。

---

## 2. 视图清单

项目实现 **6 个核心预聚合视图**（满足规范要求的至少 4 个）及 **2 个地理辅助表**：

| 视图名 | 粒度 | 核心字段 | 典型用途 |
|--------|------|----------|----------|
| mv_monthly_sales | 年-月 | year_month, total_gmv, total_orders, avg_basket, total_freight | 月度趋势、GMV 环比、预测输入 |
| mv_state_sales | 年-月-州 | year_month, customer_state, total_gmv, total_orders, unique_customers | 各州销售排名、区域对比 |
| mv_category_sales | 年-月-品类 | year_month, product_category_english, total_gmv, total_orders, avg_price | 品类表现、下降品类诊断 |
| mv_delivery_perf | 年-月-州 | year_month, customer_state, avg_delivery_days, on_time_rate, delayed_orders | 配送延迟、准时率分析 |
| mv_seller_perf | 年-月-卖家 | year_month, seller_id, seller_state, total_gmv, total_orders, avg_review_score | 卖家绩效、差评卖家定位 |
| mv_payment_dist | 年-月-支付 | year_month, payment_type, total_transactions, avg_installments, total_value | 支付偏好、分期率 |
| mv_zip_geo | 邮编前缀 | zip, lat, lng | 地理 JOIN 辅助（避免运行时大 JOIN） |
| mv_state_geo | 州 | state, lat, lng, total_gmv, total_orders | 州级地理气泡图 |

---

## 3. SQL 定义摘录

以下 SQL 均定义于 `utils/refresh_views.py`，刷新时以 `CREATE TABLE ... AS SELECT` 方式物化。

### 3.1 mv_monthly_sales（月度销售）

```sql
SELECT
  CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS year_month,
  SUM(oi.price) AS total_gmv,
  COUNT(DISTINCT o.order_id) AS total_orders,
  (SUM(oi.price) / NULLIF(COUNT(DISTINCT o.order_id), 0)) AS avg_basket,
  SUM(oi.freight_value) AS total_freight
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
GROUP BY year_month
```

### 3.2 mv_state_sales（州级销售）

```sql
SELECT
  CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS year_month,
  c.customer_state,
  SUM(oi.price) AS total_gmv,
  COUNT(DISTINCT o.order_id) AS total_orders,
  COUNT(DISTINCT c.customer_unique_id) AS unique_customers
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
GROUP BY year_month, c.customer_state
```

### 3.3 mv_category_sales（品类销售，含葡→英翻译）

```sql
SELECT
  CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS year_month,
  COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS product_category_english,
  SUM(oi.price) AS total_gmv,
  COUNT(DISTINCT o.order_id) AS total_orders,
  AVG(oi.price) AS avg_price
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
LEFT JOIN product_category_name_translation t
  ON t.product_category_name = p.product_category_name
WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
GROUP BY year_month, product_category_english
```

### 3.4 mv_delivery_perf（配送绩效）

```sql
SELECT
  CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS year_month,
  c.customer_state,
  AVG(DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp)) AS avg_delivery_days,
  AVG(CASE WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN 1 ELSE 0 END) AS on_time_rate,
  SUM(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1 ELSE 0 END) AS delayed_orders
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_estimated_delivery_date IS NOT NULL
GROUP BY year_month, c.customer_state
```

### 3.5 mv_seller_perf（卖家绩效）

```sql
SELECT
  CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS year_month,
  oi.seller_id,
  s.seller_state,
  SUM(oi.price) AS total_gmv,
  COUNT(DISTINCT o.order_id) AS total_orders,
  AVG(r.review_score) AS avg_review_score
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN sellers s ON s.seller_id = oi.seller_id
LEFT JOIN order_reviews r ON r.order_id = o.order_id
WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
GROUP BY year_month, oi.seller_id, s.seller_state
```

### 3.6 mv_payment_dist（支付分布）

```sql
SELECT
  CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS year_month,
  p.payment_type,
  COUNT(*) AS total_transactions,
  AVG(p.payment_installments) AS avg_installments,
  SUM(p.payment_value) AS total_value
FROM orders o
JOIN payments p ON p.order_id = o.order_id
WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
GROUP BY year_month, p.payment_type
```

---

## 4. 刷新与索引

### 4.1 一键刷新

```bash
python -m utils.refresh_views
```

脚本对每个视图：DROP → CREATE TABLE AS SELECT → 创建复合索引。各视图在独立事务中刷新，单个失败不阻塞其余视图。

### 4.2 启动自检（自动刷新）

`utils/startup_check.py` 在 Streamlit 仪表板启动时自动执行：

1. 检查 9 张基础表是否存在；
2. 检查 8 张物化视图是否存在；
3. 缺失视图时自动调用 `refresh_all_views()` 补建。

### 4.3 索引策略

刷新完成后自动创建索引，例如：

- `mv_monthly_sales(year_month)`
- `mv_state_sales(year_month, customer_state)`
- `mv_category_sales(year_month, product_category_english)`
- `mv_delivery_perf(year_month, customer_state)`
- `mv_seller_perf(year_month, seller_id)`
- `mv_payment_dist(year_month, payment_type)`

---

## 5. Agent 查询策略

数据分析 Agent（`agents/sql_agent.py`）的 Prompt 中列出了全部视图及其字段。当用户问题匹配预计算维度时，Agent 应优先查询视图：

| 用户问题示例 | 应命中视图 |
|-------------|-----------|
| 去年每个月销售额是多少？ | mv_monthly_sales |
| 2017 年哪个州销售额最高？ | mv_state_sales |
| 平台准时交付率？哪些州延迟严重？ | mv_delivery_perf |
| 哪种支付方式最受欢迎？ | mv_payment_dist |
| 哪些卖家差评率最高？ | mv_seller_perf |
| 哪些品类在下降？ | mv_category_sales |

**回退机制**：当问题涉及视图未覆盖的维度（如某个具体 order_id 的详情、商品重量 vs 运费散点分析）时，Agent 回退到 `orders`、`order_items`、`products` 等基础表查询。

---

## 6. 性能对比

运行 `python -m utils.perf_compare` 可对比同一分析问题（月度 GMV）在两种路径下的耗时：

| 查询路径 | 说明 |
|----------|------|
| 原始表聚合 | `orders JOIN order_items GROUP BY year_month` |
| 预聚合视图 | `SELECT FROM mv_monthly_sales` |

测试结果保存于 `data/artifacts/perf/`：

- `perf_compare_chart.png` — 耗时对比柱状图
- `perf_compare_*.md` — Markdown 报告
- `perf_compare_*.csv` — 各次运行明细

实测表明，预聚合视图可将月度 GMV 类查询加速 **数倍至数十倍**（具体数值取决于硬件与数据量），有效保障 Agent 在 Web 端的交互响应速度。

---

## 7. 小结

预聚合层是本项目的核心性能工程：6 个业务视图 + 2 个地理辅助表覆盖了描述性、诊断性、预测性分析的高频维度，配合 Agent 的视图优先策略和启动自检机制，实现了「离线重计算、在线轻查询」的 Agentic BI 加速范式。成员 B 可在此基础上进一步实现 `mv_seller_perf` 的运行时预加载与视图命中日志强化。
