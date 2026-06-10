# 智能体设计与多智能体调度

## 1. 设计目标

成员 B 阶段重点解决 Agentic BI 的核心编排能力：让系统不仅能单轮回答问题，还能在连续对话中理解追问、按问题类型选择必要 Agent、优先命中预聚合视图，并为诊断性分析提供可复用的下钻 SQL 模板。

本阶段完成的核心文件包括：

| 模块 | 文件 | 作用 |
|------|------|------|
| 状态对象 | `agents/state.py` | 增加对话历史、结构化计划、路由结果 |
| 协调器 Agent | `agents/coordinator.py` | LLM 任务分解 + 规则兜底，输出 plan 和 route |
| LangGraph 编排 | `agents/graph.py` | MemorySaver、条件路由、诊断分析预加载 |
| SQL Agent | `agents/sql_agent.py` | 视图命中策略、回退查询、运行时校验日志 |
| Web/CLI 对话入口 | `dashboard/app.py`, `app.py` | 将历史消息传入 Agent state，thread_id 生效 |
| 诊断 SQL 模板 | `config/diagnostic_queries.sql` | 配送、卖家、品类差评等下钻模板 |

---

## 2. Agent 角色与职责

系统采用 LangGraph `StateGraph` 编排多 Agent 协作，所有节点共享 `AgenticState`。

| Agent | 节点/文件 | 职责 |
|-------|-----------|------|
| 协调器 Agent | `_coordinator_node`, `agents/coordinator.py` | 解析用户问题，结合历史上下文生成结构化子任务，决定是否调用预测、NLP、可视化与决策节点 |
| SQL 分析 Agent | `_analysis_node`, `agents/sql_agent.py` | 将自然语言问题转换为安全 SELECT，优先查询预聚合视图，必要时回退基础表 |
| 预测 Agent | `_forecast_node`, `models/forecast.py` | 基于 `mv_monthly_sales` 预测未来 6 周 GMV |
| NLP Agent | `_nlp_node`, `agents/nlp_agent.py` | 对评论文本抽取负面关键词与主题，支持差评原因分析 |
| 可视化 Agent | `_viz_node`, `agents/viz_agent.py` | 根据问题和可用表选择图表并生成图片 |
| 决策 Agent | `_decision_node`, `agents/decision_agent.py` | 综合 SQL、预测、NLP 与图表结果生成业务建议 |

---

## 3. MemorySaver 与多轮上下文

图编译时启用 LangGraph MemorySaver：

```python
return g.compile(checkpointer=MemorySaver())
```

Web 端和 CLI 均使用稳定的 `thread_id` 调用图：

```python
config = {"configurable": {"thread_id": st.session_state.thread_id}}
```

同时，前端会把历史问答显式传入 `AgenticState.conversation_history`。这样系统具备两层上下文能力：

1. **LangGraph checkpointer**：同一 `thread_id` 下保存图状态快照；
2. **显式 conversation_history**：协调器和 SQL Agent 可直接读取最近问答，用于补全「那准时率呢？」这类追问。

协调器会在检测到追问词时生成 `context_rewrite`，例如：

```text
上轮问题：2017年哪个州销售额最高？
当前追问：那准时率呢？
改写后：2017年哪个州销售额最高？追问：那准时率呢？
```

该改写问题会传入后续 SQL、NLP、可视化与决策节点，降低上下文丢失风险。

---

## 4. LLM 协调器与结构化计划

`agents/coordinator.py` 采用 “LLM 优先、规则兜底” 策略。LLM 正常可用时输出如下 JSON：

```json
{
  "intent": "diagnostic",
  "subtasks": [
    {"agent": "sql", "task": "查询配送与卖家绩效视图", "reason": "定位延迟和低评分来源"},
    {"agent": "nlp", "task": "提取差评主题", "reason": "解释差评原因"},
    {"agent": "decision", "task": "生成运营建议", "reason": "输出可执行策略"}
  ],
  "route": {
    "analysis": true,
    "forecast": false,
    "nlp": true,
    "viz": true,
    "decision": true
  },
  "context_rewrite": "为什么某些州配送时间高于全国均值？哪些卖家差评率最高？"
}
```

如果 LLM API 缺失、超时或返回非 JSON，协调器会自动使用关键词规则兜底，保证本地测试和课堂演示不会因外部模型失败而中断。

---

## 5. 条件分支路由

原系统为线性链路：

```text
coordinator -> analysis -> forecast -> nlp -> viz -> decision
```

B 阶段改为条件路由：

```text
coordinator -> analysis
analysis -> forecast | nlp | viz | decision
forecast -> nlp | viz | decision
nlp -> viz | decision
viz -> decision -> END
```

路由规则由 `state.route` 控制：

| 问题类型 | forecast | nlp | viz | 效果 |
|----------|----------|-----|-----|------|
| 描述性问题 | false | false | true | 跳过 SARIMAX 与 NLP，仅做视图查询、图表和结论 |
| 预测问题 | true | false | true | 触发 `forecast_6_weeks` |
| 评论/差评问题 | false | true | true | 触发 NLP 评论洞察 |
| 诊断/策略问题 | 按需 | true | true | 加载诊断表并输出建议 |

这满足「非预测类问题不触发 SARIMAX」的验收要求，也减少 Web 端等待时间。

---

## 6. SQL Agent 视图命中策略

SQL Agent 的 Prompt 明确要求：

- 能用预聚合视图回答的 KPI 必须使用视图；
- 只有商品尺寸、原始评论文本、订单明细等视图无法覆盖的维度才回退基础表；
- 输出 JSON 元数据，包括 `use_view`、`view_name`、`sql` 和 `kpi_explanation`。

B 阶段新增运行时校验：

1. 根据问题关键词计算 `preferred_views`；
2. 如果 LLM 声称 `use_view=true` 但 SQL 未引用对应视图，则替换为内置安全视图查询；
3. 如果问题明显命中视图但 LLM 生成基础表 JOIN，则强制改写为视图查询；
4. 将策略写入 `_question_meta.view_strategy`，便于验收和调试。

典型策略值：

| view_strategy | 含义 |
|---------------|------|
| `llm_sql_accepted` | LLM SQL 通过校验 |
| `forced_fallback_llm_view_mismatch` | LLM 元数据与 SQL 不一致，强制使用声明视图 |
| `forced_preagg_view_by_runtime_policy` | 问题命中视图但 LLM 未使用，运行时强制改写 |

---

## 7. 诊断性分析增强

为满足商案中「为什么某些州配送时长高于全国均值」「哪些卖家差评率最高」「Top 10 差评品类及原因」等诊断问题，B 阶段补充三类诊断数据：

| 输出表 | 来源 | 用途 |
|--------|------|------|
| `diagnostic_delivery_vs_national` | `mv_delivery_perf` | 州级配送时长、准时率与全国均值差异 |
| `diagnostic_bad_review_sellers` | `mv_seller_perf` | 低评分、高订单量卖家定位 |
| `diagnostic_bad_review_categories` | 原始 reviews/items/products | 品类差评率 Top 10 下钻 |

SQL 模板集中保存于 `config/diagnostic_queries.sql`，报告和答辩可直接引用。

---

## 8. 验收问题覆盖

B 阶段自测重点覆盖商案第九节中的描述性与诊断性问题：

| 验收问题 | 预期行为 |
|----------|----------|
| “2017年哪个州销售额最高？” | 命中 `mv_state_sales`，返回州级 GMV 排名 |
| “那准时率呢？” | 通过历史上下文理解追问，命中 `mv_delivery_perf` |
| “平台整体准时交付率是多少？哪些州延迟最严重？” | 加载 `diagnostic_delivery_vs_national` |
| “哪种支付方式最受欢迎？平均分期数是多少？” | 命中 `mv_payment_dist` |
| “为什么某些州的平均配送时长显著高于全国均值？哪些卖家的差评率最高？” | 加载配送诊断和 `mv_seller_perf` |

静态验收命令：

```bash
python -m py_compile agents/state.py agents/coordinator.py agents/sql_agent.py agents/graph.py dashboard/app.py app.py
python -c "from agents.graph import build_graph; g=build_graph(); print(type(g).__name__)"
```

动态验收建议：

```bash
streamlit run dashboard/app.py
```

然后连续提问：

```text
2017年哪个州销售额最高？
那准时率呢？
哪些卖家差评率最高？
根据历史订单趋势，预测未来6周的销售额。
```

在第二轮回答中检查上下文不丢失；在非预测问题中检查日志或响应时间，确认未触发 SARIMAX；在卖家问题中检查数据表区域是否出现 `diagnostic_bad_review_sellers` 或 `_question_meta` 中的 `mv_seller_perf`。
