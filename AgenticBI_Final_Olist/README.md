## Agentic BI (Olist) — 多智能体电商运营分析系统

本项目实现一个 **Agentic BI** 多智能体系统，基于 Olist 巴西电商多表数据集，在 **MySQL** 中落库并构建 **Pre-Aggregation 预聚合视图**，支持自然语言提问、跨表分析、预测、NLP 评论洞察、自动可视化，并输出可执行的决策建议。

### 1. 功能概览

- **多智能体协作（LangGraph）**：协调器（Planner）+ 数据分析 Agent + 可视化 Agent + NLP/评论洞察 Agent + 决策智能 Agent
- **MySQL 多表查询**：支持跨表 JOIN 与 KPI 聚合
- **预聚合加速层（至少 4 个）**：系统启动可一键刷新
- **预测**：基于月度 GMV 序列预测未来 6 周（默认用 `statsmodels`，可选接入 `prophet`）
- **可视化（≥6 种）**：折线（含预测区间）、柱状、热力矩阵、散点/气泡、地理州级分布、词云
- **Web 双栏仪表板**：左侧对话/结果，右侧图表展示；支持多轮对话上下文

### 2. 运行环境

- Python 3.10+（建议 3.11）
- MySQL 8.0+

### 3. 配置

项目已将 DeepSeek API Key 直接嵌入到默认设置中，下载后可直接使用 agent 功能。

如果你想覆盖默认配置，可继续使用 `.env` 文件：

```bash
copy .env.example .env
```

推荐在 `.env` 中显式配置（尤其是希望看到你自己账号的 token 消耗时）：

- `DEEPSEEK_API_KEY`: DeepSeek API Key（会覆盖项目默认 key）
- `DEEPSEEK_BASE_URL`: 默认 `https://api.deepseek.com/v1`
- `DEEPSEEK_MODEL`: 默认 `deepseek-v4-pro`

### 4. 安装依赖

```bash
pip install -r requirements.txt
```

### 5. 数据准备

将 Kaggle 的 Olist 数据集 CSV 文件放到 `data/raw/`（文件名保持原始命名，例如 `olist_orders_dataset.csv` 等）。

### 6. 初始化数据库 + 刷新预聚合视图

```bash
python -m utils.db_init
python -m utils.refresh_views
```

性能说明（保证 Web 端不“卡死”）：

- `utils.refresh_views` 现在会构建额外的物化表 `mv_zip_geo`、`mv_state_geo`，避免在每次提问时做地理相关的大 JOIN。
- Web 提问默认使用 **快速模式**（目标 <60s），会跳过最慢的图表；右侧按钮“重新生成图表”会生成完整图表集（满足 ≥6 类可视化要求）。

### 7. 启动 Web 仪表板

```bash
streamlit run dashboard/app.py
```

### 8. 目录结构

```text
AgenticBI_Final_Olist/
├── agents/                  # 多 Agent 定义 & LangGraph 编排
├── config/                  # 数据字典、Prompt 模板
├── dashboard/               # Streamlit Web UI
├── data/
│   ├── raw/                 # 原始CSV（自行放置）
│   └── artifacts/           # 生成的图表、缓存等
├── models/                  # 预测/NLP 模块
├── utils/                   # MySQL 初始化、加载、预聚合 SQL、性能计时
├── app.py                   # CLI 入口（可选）
├── requirements.txt
├── .env.example
└── .gitignore
```

