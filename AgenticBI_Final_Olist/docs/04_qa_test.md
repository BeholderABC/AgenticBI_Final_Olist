# 附录验证问题全覆盖测试报告

> 成员C编写 | 生成日期：2026-06-12
>
> 本文件逐条验证商案.txt 第九节附录中的10+个标准问题，
> 记录系统应答策略、数据命中路径与已知限制。

---

## 测试环境

| 项目 | 说明 |
|------|------|
| 数据库 | MySQL 8.x, Olist 9表 + 6预聚合视图 |
| LLM | DeepSeek-V4-Pro |
| Agent 编排 | LangGraph StateGraph + MemorySaver |
| Web 界面 | Streamlit 双栏布局 |

---

## 问题清单与验证结果

### Q1：「2017年 GMV 是多少？按月和各州排名的趋势怎样？」

| 维度 | 详情 |
|------|------|
| **命中视图** | mv_monthly_sales（时间趋势）+ mv_state_sales（州排名） |
| **Agent 路径** | coordinator → analysis → viz → decision |
| **自动图表** | ts_gmv_forecast（月度折线图）、bar_state_gmv（州GMV柱状图） |
| **预期结果** | 返回2017年月度GMV序列及Top 5州排名 |
| **状态** | ✅ 可正确回答 |

### Q2：「平台整体准时交付率是多少？哪些州延迟最严重？」

| 维度 | 详情 |
|------|------|
| **命中视图** | mv_delivery_perf |
| **Agent 路径** | coordinator → analysis → viz → decision |
| **自动图表** | bar_delivery_days（延迟天数柱状图） |
| **预期结果** | 输出全国准时率 + 延迟最严重的Top 5州 |
| **状态** | ✅ 可正确回答 |

### Q3：「哪种支付方式最受欢迎？平均分期数是多少？」

| 维度 | 详情 |
|------|------|
| **命中视图** | mv_payment_dist |
| **Agent 路径** | coordinator → analysis → viz → decision |
| **自动图表** | heatmap_payment_installments（支付×分期矩阵） |
| **预期结果** | 返回信用卡占比最高，分期数约3~5期 |
| **状态** | ✅ 可正确回答 |

### Q4：「产品的重量、尺寸与运费之间有什么关系？」

| 维度 | 详情 |
|------|------|
| **命中表** | order_items + orders + products + product_category_name_translation（基础表JOIN） |
| **Agent 路径** | coordinator → analysis → viz → decision |
| **自动图表** | scatter_weight_freight + scatter_weight_dims_freight（C5扩展散点） |
| **数据说明** | 散点SQL已扩展product_length_cm/height_cm/width_cm三列，展示多维度关系 |
| **预期结果** | 重量与运费呈正相关，大件商品运费显著偏高 |
| **状态** | ✅ 可正确回答 |

### Q5：「Top 10 差评品类及其主要差评原因是什么？」

| 维度 | 详情 |
|------|------|
| **命中表** | diagnostic_bad_review_categories（品类差评聚合） |
| **Agent 路径** | coordinator → analysis → nlp → viz → decision |
| **自动图表** | heatmap_category_rating（C1品类×评分矩阵）+ wordcloud_dual（C2好评/差评对比词云） |
| **辅助数据** | NLP Agent提取差评TF-IDF高频词、TextBlob情感极性 |
| **预期结果** | 列出差评率最高的10个品类，附带差评关键词 |
| **状态** | ✅ 可正确回答 |

### Q6：「根据历史订单趋势，预测未来6周的销售额，并给出趋势解读。」

| 维度 | 详情 |
|------|------|
| **命中视图** | mv_monthly_sales |
| **Agent 路径** | coordinator → analysis → forecast → viz → decision |
| **预测模型** | SARIMAX (models/forecast.py) |
| **自动图表** | ts_gmv_forecast（含预测区间） |
| **预期结果** | 返回6周预测值（含80%置信区间）+ 趋势解读 |
| **状态** | ✅ 可正确回答（需足够历史数据，约20+个月） |

### Q7：「基于全部分析结果，给出平台3个月内的三大优先改进策略。」

| 维度 | 详情 |
|------|------|
| **Agent 路径** | coordinator → analysis → (forecast) → (nlp) → viz → decision |
| **决策逻辑** | Decision Agent综合descriptive + diagnostic + forecast + NLP结果，输出3~5条优先级策略 |
| **预期结果** | 输出包含物流、品类、卖家三大维度的改进建议 |
| **状态** | ✅ 可正确回答（依赖LLM推理质量） |

### Q8：「2017年哪个州的销售额最高？交付准时率是多少？哪种支付方式最受欢迎？」

| 维度 | 详情 |
|------|------|
| **命中视图** | mv_state_sales + mv_delivery_perf + mv_payment_dist |
| **Agent 路径** | coordinator → analysis → viz → decision |
| **多问合成** | SQL Agent 按顺序响应三个子问题，Decision Agent 整合回答 |
| **预期结果** | SP州销售额最高；准时率约80~85%；信用卡最受欢迎 |
| **状态** | ✅ 可正确回答 |

### Q9：「为什么某些州的平均配送时长显著高于全国均值？哪些卖家的差评率最高？」

| 维度 | 详情 |
|------|------|
| **命中表** | diagnostic_delivery_vs_national（配送对比）+ diagnostic_bad_review_sellers（差评卖家） |
| **Agent 路径** | coordinator → analysis → nlp → viz → decision |
| **分析逻辑** | 比较州级配送天数与全国均值差值，按差评率倒排卖家 |
| **预期结果** | 东北部各州（MA、PI等）配送延迟最严重；特定卖家差评率极高 |
| **状态** | ✅ 可正确回答 |

### Q10：「如何降低巴西东北部地区的高退货率？请给出具体的运营改进方案。」

| 维度 | 详情 |
|------|------|
| **Agent 路径** | coordinator → analysis → (nlp) → viz → decision |
| **决策输入** | mv_delivery_perf配送数据 + NLP差评关键词 + 品类差评率 |
| **注意** | Olist数据集无退货表，返回值基于review_score≤2做代理指标（已在回答中注明口径） |
| **预期结果** | 输出物流改善、卖家筛选、客服响应三方面策略 |
| **状态** | ✅ 可正确回答（注明口径） |

### 加分项 Q：「如果将 Top 20 高差评卖家的商品统一下架，平台整体评分预估提升多少？」

| 维度 | 详情 |
|------|------|
| **Agent 路径** | coordinator → analysis → whatif → decision |
| **核心模块** | models/whatif.py（C8 What-if模拟） |
| **模拟逻辑** | 从mv_seller_perf取Top 20低分卖家 → 计算加权评分移除前后的平台均值变化 |
| **预期结果** | 输出评分提升幅度（约0.05~0.15分）及受影响的订单数量 |
| **状态** | ✅ 可正确回答 |

### 加分项 Q：「最近哪些州出现了订单量骤降或差评率突升的异常？」

| 维度 | 详情 |
|------|------|
| **Agent 路径** | coordinator → analysis → anomaly → decision |
| **核心模块** | agents/anomaly_agent.py（C9异常检测） |
| **检测逻辑** | MoM订单量下降>30%标记为高风险；州级准时率低于平台均值2x标记为中风险 |
| **预期结果** | 输出异常州列表+风险等级+建议动作 |
| **状态** | ✅ 可正确回答（需要有连续月份数据） |

---

## 汇总统计

| 指标 | 数值 |
|------|------|
| 附录问题总数 | 12（含2个加分项） |
| 可正确回答 | 12 / 12 |
| 覆盖率 | **100%** |
| 需注明口径说明的 | 1（Q10：退货率由review_score代理） |
| 注意要点 | Q10 无真实的退货数据，以 review_score <= 2 为代理指标 |

---

## 已知限制与改进方向

1. **退货率**：无 olist_order_returns 表，使用 review_score ≤ 2 做近似（已在回答中注明）。
2. **预测精度**：SARIMAX要求至少20个月历史数据，2016年9月~2018年10月的数据仅25个月左右。如数据不足可能回退简单移动平均。
3. **TextBlob 语言适应**：葡萄牙语评论对 TextBlob 极性判断准确度低于英语，建议后续引入多语言模型或葡萄牙语专用词典。
4. **实时性**：What-if 和异常检测依赖 mv_seller_perf 和 mv_state_sales 视图，需确保视图已刷新。