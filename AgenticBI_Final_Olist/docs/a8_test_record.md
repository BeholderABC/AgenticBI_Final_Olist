# A8 自测记录 — 成员 A

测试时间：2026-06-08  
测试环境：Windows 10，Python 3.x，MySQL 8.0（本地 127.0.0.1）  
测试人：成员 A

---

## 1. 测试目标

验证分工清单 A 阶段验收标准：

- [x] `python -m utils.db_init && python -m utils.refresh_views` 无报错
- [x] 9 表加载 + 6 核心视图刷新全流程 < 5 分钟
- [x] `data/artifacts/perf/` 下有性能对比截图
- [x] `docs/01_data.md` 与 `docs/02_views.md` 已撰写

---

## 2. 全流程耗时测试

| 步骤 | 命令 | 耗时 | 结果 |
|------|------|------|------|
| 数据加载+清洗 | `python -m utils.db_init` | 44.5 s | PASS |
| 预聚合视图刷新 | `python -m utils.refresh_views` | 20.2 s | PASS |
| **合计** | — | **64.6 s** | PASS（< 300 s） |

### 2.1 db_init 清洗明细

| 表名 | 清洗前 | 清洗后 | 关键操作 |
|------|--------|--------|----------|
| customers | 99,441 | 99,441 | 无变化 |
| geolocation | 1,000,163 | 19,015 | 按邮编前缀聚合 |
| order_items | 112,650 | 112,650 | 无变化 |
| payments | 103,886 | 103,886 | 无变化 |
| order_reviews | 99,224 | 98,673 | 去除 551 条重复评价 |
| orders | 99,441 | 99,441 | 无变化 |
| products | 32,951 | 32,951 | 填充 610 条空品类 |
| sellers | 3,095 | 3,095 | 无变化 |
| translation | 71 | 71 | 无变化 |

### 2.2 refresh_views 各视图耗时

| 视图 | 耗时 |
|------|------|
| mv_monthly_sales | 1.64 s |
| mv_state_sales | 3.63 s |
| mv_category_sales | 4.71 s |
| mv_delivery_perf | 1.77 s |
| mv_seller_perf | 5.50 s |
| mv_payment_dist | 1.33 s |
| mv_zip_geo | 0.12 s |
| mv_state_geo | 0.76 s |

---

## 3. 启动自检测试

| 测试项 | 命令 | 结果 |
|--------|------|------|
| 视图就绪检查 | `python -m utils.startup_check` | PASS，输出「数据库与预聚合视图已就绪」 |
| Dashboard 集成 | `dashboard/app.py` 启动时调用 `ensure_views_ready()` | 已集成（代码审查确认） |

---

## 4. 性能对比测试

| 测试项 | 命令 | 结果 |
|--------|------|------|
| Benchmark 脚本 | `python -m utils.perf_compare` | PASS |
| 原始表聚合耗时 | orders JOIN order_items GROUP BY month | 0.896 s（3 次平均） |
| 预聚合视图耗时 | SELECT FROM mv_monthly_sales | 0.001 s（3 次平均） |
| 加速比 | — | **602x** |

### 产出文件

- `data/artifacts/perf/perf_compare_chart.png` — 对比柱状图
- `data/artifacts/perf/perf_compare_20260608_122416.md` — Markdown 报告
- `data/artifacts/perf/perf_compare_20260608_122416.csv` — 原始计时数据

---

## 5. 文档交付检查

| 文件 | 路径 | 状态 |
|------|------|------|
| 数据集与预处理报告 | docs/01_data.md | 已交付 |
| 预聚合视图设计报告 | docs/02_views.md | 已交付 |
| 环境配置模板 | .env.example | 已交付 |

---

## 6. 结论

成员 A 全部 8 项任务（A1~A8）已完成，满足分工清单验收标准。可交接给成员 B：

- 干净的数据库（9 表 + 8 物化视图）
- 性能对比截图与报告（`data/artifacts/perf/`）
- 报告素材（`docs/01_data.md`、`docs/02_views.md`）
