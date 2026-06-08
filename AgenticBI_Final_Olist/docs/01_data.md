# 数据集描述与预处理

## 1. 数据集概述

本项目采用 Kaggle 公开的 **Brazilian E-Commerce Public Dataset by Olist**（巴西 Olist 电商数据集）。该数据集记录了 2016 年 9 月至 2018 年 10 月期间巴西电商平台 Olist 的真实交易行为，规模约 **99,441 笔订单**、**112,650 个订单行项目**，覆盖客户、卖家、商品、支付、评论、地理信息等多维业务实体。

与单表销售数据不同，Olist 采用 **9 张独立业务表、通过外键关联** 的多表结构，能够支撑跨表 JOIN 分析、全订单链路追踪（下单→支付→发货→送达→评价）以及基于评论文本的 NLP 洞察，是构建 Agentic BI 系统的理想实战数据。

### 1.1 九张核心表

| 表名 | 文件名 | 业务含义 | 关键字段 |
|------|--------|----------|----------|
| orders | olist_orders_dataset.csv | 订单主表 | order_id, customer_id, order_status, 各阶段时间戳 |
| order_items | olist_order_items_dataset.csv | 订单行项目 | order_id, product_id, seller_id, price, freight_value |
| products | olist_products_dataset.csv | 商品属性 | product_id, product_category_name, 重量/尺寸 |
| customers | olist_customers_dataset.csv | 客户信息 | customer_id, customer_unique_id, zip, city, state |
| sellers | olist_sellers_dataset.csv | 卖家信息 | seller_id, zip, city, state |
| payments | olist_order_payments_dataset.csv | 支付记录 | order_id, payment_type, installments, payment_value |
| order_reviews | olist_order_reviews_dataset.csv | 订单评价 | order_id, review_score, 评论标题与正文 |
| geolocation | olist_geolocation_dataset.csv | 邮编地理坐标 | zip_prefix, lat, lng, city, state |
| product_category_name_translation | product_category_name_translation.csv | 品类葡→英翻译 | product_category_name, product_category_name_english |

### 1.2 数据特点与挑战

- **多表关联复杂**：分析 GMV、区域销售、配送绩效等 KPI 需 JOIN 3~5 张表，实时聚合开销大。
- **葡萄牙语文本**：商品分类名、评论内容为葡萄牙语，需借助翻译表或 NLP 处理。
- **地理数据膨胀**：geolocation 表同一邮编前缀存在大量重复行，直接 JOIN 会产生巨大中间结果集。
- **时间字段异构**：订单各阶段时间戳格式需统一解析，部分未送达订单的交付时间为空。
- **评价数据稀疏**：部分订单无评论，评论文本存在空值。

---

## 2. 数据加载流程

原始 CSV 文件放置于 `data/raw/`，通过一键脚本完成「读取 → 清洗 → 落库 → 建索引」：

```bash
python -m utils.db_init
```

加载流程由 `utils/db_init.py` 编排，核心步骤：

1. 检查 `data/raw/` 下 9 个 CSV 是否齐全；
2. 调用 `utils/data_clean.py` 对每张表执行清洗；
3. 通过 SQLAlchemy `to_sql` 写入 MySQL（`if_exists='replace'`）；
4. 在关键 JOIN 字段上创建索引，加速后续查询与视图刷新。

数据库默认名：`olist_agentic_bi`，字符集 `utf8mb4`（支持葡萄牙语及评论文本）。

---

## 3. 预处理规则详解

清洗逻辑集中在 `utils/data_clean.py`，按表提供可复用函数，并输出 `CleanReport`（记录清洗前后行数与操作明细）。

### 3.1 orders（订单表）

- 解析 5 个时间戳字段为 `datetime`（无法解析的置为 NaT）；
- 去除 `order_id` 重复行（保留首条）；
- 丢弃 `order_status` 为空的无效记录。

### 3.2 order_items（订单行）

- 去除 `(order_id, order_item_id)` 重复；
- `price`、`freight_value` 强制数值化，丢弃空值行；
- 解析 `shipping_limit_date`。

### 3.3 products（商品表）

- 去除 `product_id` 重复；
- `product_category_name` 空值填充为 `unknown`；
- 重量、尺寸等数值字段统一 `to_numeric`。

### 3.4 customers / sellers（客户与卖家）

- 去除主键重复；
- `customer_state` / `seller_state` 统一为大写缩写；
- 邮编前缀转为整数类型。

### 3.5 payments（支付表）

- `payment_value`、`payment_installments` 数值化；
- 丢弃 `payment_value` 为空记录；
- `payment_type` 统一小写。

### 3.6 order_reviews（评价表）

- 每个 `order_id` 仅保留一条评价；
- `review_score` 限定在 1~5 分有效区间；
- 评论标题与正文空值填充为空字符串；
- 解析评价创建与回复时间戳。

### 3.7 geolocation（地理表）

- 丢弃经纬度无效行；
- **按 `geolocation_zip_code_prefix` 聚合**：对同一邮编的 lat/lng 取均值、city/state 取首条，将约 100 万行压缩至数万行，避免后续 JOIN 性能灾难。

### 3.8 product_category_name_translation（品类翻译）

- 去除葡语品类名重复；
- 英文名缺失时回退使用葡语原名，保证 JOIN 后不产生空品类。

---

## 4. 预处理效果

清洗在加载阶段自动执行，终端会打印每张表的行数变化，例如：

```
loaded orders: 99,441 rows
  cleaned orders: 99,441 -> 99,441 rows (no changes)
loaded geolocation: 1,000,163 -> 19,015 rows
  - aggregated geolocation from 1,000,163 to 19,015 rows by zip prefix
```

地理表聚合是本项目预处理的关键优化之一，直接降低了预聚合视图刷新和运行时 JOIN 的耗时。

---

## 5. 配置与环境

数据库与 API 连接通过 `.env` 配置，模板见 `.env.example`：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| MYSQL_HOST | MySQL 主机 | 127.0.0.1 |
| MYSQL_PORT | 端口 | 3306 |
| MYSQL_USER | 用户名 | root |
| MYSQL_PASSWORD | 密码 | （空） |
| MYSQL_DATABASE | 库名 | olist_agentic_bi |

---

## 6. 小结

本项目的数据预处理遵循「**加载即清洗、清洗即可用**」原则：在 `db_init` 阶段完成空值处理、重复消除、时间标准化、品类翻译补全和地理数据聚合，为上层预聚合视图和 Agent SQL 查询提供干净、可 JOIN、可索引的数据基础。完整的字段说明见 `config/data_dictionary.md`。
