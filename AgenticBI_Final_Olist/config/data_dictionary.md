## 数据字典（Olist 基础表 + 预聚合视图）

### 基础表（落库后）

- `orders`
  - `order_id` (PK), `customer_id`, `order_status`
  - `order_purchase_timestamp`, `order_approved_at`
  - `order_delivered_carrier_date`, `order_delivered_customer_date`
  - `order_estimated_delivery_date`

- `order_items`
  - `order_id`, `order_item_id`, `product_id`, `seller_id`
  - `shipping_limit_date`, `price`, `freight_value`

- `products`
  - `product_id`, `product_category_name`, `product_name_length`
  - `product_description_length`, `product_photos_qty`
  - `product_weight_g`, `product_length_cm`, `product_height_cm`, `product_width_cm`

- `customers`
  - `customer_id`, `customer_unique_id`, `customer_zip_code_prefix`
  - `customer_city`, `customer_state`

- `sellers`
  - `seller_id`, `seller_zip_code_prefix`, `seller_city`, `seller_state`

- `payments`
  - `order_id`, `payment_sequential`, `payment_type`
  - `payment_installments`, `payment_value`

- `order_reviews`
  - `order_id`, `review_score`, `review_comment_title`, `review_comment_message`
  - `review_creation_date`, `review_answer_timestamp`

- `geolocation`
  - `geolocation_zip_code_prefix`, `geolocation_lat`, `geolocation_lng`
  - `geolocation_city`, `geolocation_state`

- `product_category_name_translation`
  - `product_category_name`, `product_category_name_english`

### 预聚合视图（物化为表，推荐每次启动可刷新）

#### `mv_monthly_sales`（年-月）
- 字段：`year_month`, `total_gmv`, `total_orders`, `avg_basket`, `total_freight`
- 用途：月度趋势、环比、预测输入

#### `mv_state_sales`（年-月-州）
- 字段：`year_month`, `customer_state`, `total_gmv`, `total_orders`, `unique_customers`
- 用途：区域对比、州排名、地理分布

#### `mv_category_sales`（年-月-品类）
- 字段：`year_month`, `product_category_english`, `total_gmv`, `total_orders`, `avg_price`
- 用途：品类表现、趋势诊断

#### `mv_delivery_perf`（年-月-州）
- 字段：`year_month`, `customer_state`, `avg_delivery_days`, `on_time_rate`, `delayed_orders`
- 用途：配送延迟诊断、准时率

#### `mv_seller_perf`（推荐，年-月-卖家）
- 字段：`year_month`, `seller_id`, `seller_state`, `total_gmv`, `total_orders`, `avg_review_score`
- 用途：卖家绩效、差评卖家定位

#### `mv_payment_dist`（推荐，年-月-支付类型）
- 字段：`year_month`, `payment_type`, `total_transactions`, `avg_installments`, `total_value`
- 用途：支付偏好、分期对比、矩阵图

