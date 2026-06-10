# 成员 B 自测与验收记录

测试日期：2026-06-10

## 1. 静态测试

命令：

```bash
python -m py_compile agents/state.py agents/coordinator.py agents/sql_agent.py agents/graph.py dashboard/app.py app.py
```

结果：通过，无语法错误。

命令：

```bash
python -c "from agents.graph import build_graph; print(type(build_graph()).__name__)"
```

结果：输出 `CompiledStateGraph`，说明 LangGraph 编译成功，`MemorySaver` checkpointer 可正常接入。

## 2. 上下文与视图策略测试

命令：

```bash
python -c "from agents.coordinator import plan_question; p=plan_question('那准时率呢？',[{'role':'user','content':'2017年哪个州销售额最高？'}]); print(p['route']); print(p['context_rewrite'])"
```

结果：

```text
{'analysis': True, 'forecast': False, 'nlp': False, 'viz': True, 'decision': True}
2017年哪个州销售额最高？。追问：那准时率呢？
```

结论：追问可结合历史问题改写，且未触发 forecast/NLP。

命令：

```bash
python -c "from agents.sql_agent import _preferred_views; print(_preferred_views('2017年哪个州销售额最高？。追问：那准时率呢？')); print(_preferred_views('哪些卖家差评率最高'))"
```

结果：

```text
['mv_delivery_perf', 'mv_state_sales', 'mv_monthly_sales']
['mv_seller_perf']
```

结论：准时率追问优先命中 `mv_delivery_perf`；卖家差评问题命中 `mv_seller_perf`。

## 3. 条件路由测试

通过 monkeypatch 将数据库、LLM、预测、NLP、可视化替换为轻量 stub，验证图路由。

描述性问题：

```text
2017年哪个州销售额最高？
```

结果：直接执行 `analysis -> decision`，未触发 `forecast`、`nlp`、`viz`。

预测问题：

```text
预测未来6周销售额
```

结果：执行 `analysis -> forecast -> decision`，确认预测类问题会触发 forecast 节点。

## 4. 人工验收建议

启动 Web：

```bash
streamlit run dashboard/app.py
```

推荐连续输入：

1. `2017年哪个州销售额最高？`
2. `那准时率呢？`
3. `哪些卖家差评率最高？`
4. `为什么某些州的平均配送时长显著高于全国均值？哪些卖家的差评率最高？`
5. `根据历史订单趋势，预测未来6周的销售额。`

验收点：

- 第 2 个问题能承接第 1 个问题的州级上下文；
- 第 1、2、3、4 个非预测问题不触发 SARIMAX；
- 卖家差评问题的数据表或 `_question_meta` 中出现 `mv_seller_perf`；
- 配送诊断问题出现 `diagnostic_delivery_vs_national`；
- 预测问题才触发 forecast 节点并生成未来 6 周结果。
