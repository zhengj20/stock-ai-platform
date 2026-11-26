---
name: strategy-combo
display_name: 策略组合引擎 (Strategy Combination)
title: Multi-Strategy Signal Fusion Engine
description: 多策略信号融合系统，支持投票融合、加权融合和冲突检测，将不同选股策略的结果综合评估。
homepage: ""
author: Hermes Agent
version: 1.0.0
dependencies:
  - pandas
  - numpy
env: {}
---

# 策略组合引擎

将多个选股策略的结果进行智能融合，输出综合排名和置信度评估。

## 核心功能

### 1. 投票融合 (`vote`)

多数表决机制：统计每只股票被多少个策略选中为Top N。

```bash
python strategy_combo.py vote \
  --results ml_result.json factor_result.json flow_result.json \
  --top_n 20 --min_votes 2
```

**输出：**
- 票数：被多少策略选中
- 平均得分：各策略得分的平均值
- 置信度：票数/总策略数×100%
- 完全共识股票：所有策略共同选中的股票

### 2. 加权融合 (`weight`)

按策略历史表现分配权重，计算综合评分。

```bash
python strategy_combo.py weight \
  --results ml_result.json factor_result.json flow_result.json \
  --weights '{"ml_output":0.4,"选股结果":0.3,"capital_flow":0.3}'
```

**流程：**
1. 各策略得分标准化到0-100范围
2. 按权重计算加权平均分
3. 参与策略数越多，置信度越高

### 3. 冲突检测 (`conflict`)

识别不同策略对同一股票给出相反信号的情况。

```bash
python strategy_combo.py conflict --results *.json
```

**输出：**
- 看多策略 vs 看空策略列表
- 高分歧股票（标准差>30）
- 高共识股票（标准差<10）

### 4. 完整分析 (`full`)

一次性执行投票+加权+冲突检测。

```bash
python strategy_combo.py full --results *.json
```

## Python API调用

```python
from strategy_combo import StrategyComboEngine

engine = StrategyComboEngine()

# 加载多个策略结果
all_results = engine.load_results([
    "ml_output/prediction_20240101.json",
    "output/选股结果_20240101.json",
    "capital_flow_result.csv"
])

# 投票融合
vote_df, consensus = engine.vote_fuse(all_results, top_n=20, min_votes=2)

# 加权融合
weight_df = engine.weight_fuse(
    all_results, 
    weights={"ml": 0.4, "factor": 0.3, "flow": 0.3}
)

# 冲突检测
conflicts, divergence = engine.detect_conflicts(all_results)
```

## 支持的输入格式

| 来源 | JSON字段 | CSV列名 |
|------|---------|---------|
| ML选股 | `top_stocks[].stock_name` + `combined_score` | `股票` + `得分` |
| 多因子 | `results[].股票` + `综合得分` | `股票` + `得分` |
| 资金流向 | `stock` + `total_score` | `股票` + `得分` |

## 实战建议

### 权重分配参考

基于策略特性推荐的基础权重：

| 策略类型 | 推荐权重 | 适用场景 |
|---------|---------|---------|
| ML选股 | 0.35-0.40 | 趋势行情 |
| 多因子 | 0.25-0.30 | 任何市场 |
| 资金流向 | 0.20-0.25 | 活跃市 |
| 技术策略 | 0.10-0.15 | 短线交易 |

### 置信度解读

| 置信度 | 含义 | 操作建议 |
|--------|------|---------|
| ≥80% | 高共识，多策略确认 | 重仓参与 |
| 60-80% | 中等共识 | 正常仓位 |
| 40-60% | 分歧较大 | 轻仓试探 |
| <40% | 低共识 | 观望 |
