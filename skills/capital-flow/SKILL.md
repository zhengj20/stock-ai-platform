---
name: capital-flow
display_name: 资金流向选股 (Capital Flow Selection)
title: Capital Flow Based Stock Selection
description: 基于主力资金流向、订单大小分类和量价关系进行智能选股，检测连续流入、量价背离等信号。
homepage: ""
author: Hermes Agent
version: 1.0.0
dependencies:
  - pandas
  - numpy
  - requests
---

# 资金流向选股策略

基于东方财富公开资金流向接口（免费、无需 API Key）与腾讯/东财日K线数据，通过多维度分析识别资金动向，辅助选股决策。

## 核心功能

### 1. 主力净流入筛选 (`scan`)

批量扫描股票池，计算每只股票的资金强度综合评分：

```bash
python capital_flow.py scan --stocks "贵州茅台,宁德时代,比亚迪" --top_n 10
```

**评分维度：**
- 主力净流入占比 (40%) - 净流入天数/总天数
- 连续流入天数 (30%) - 最近连续净流入天数
- 超大单占比 (20%) - 机构/大户参与度
- 量价配合度 (10%) - 价格与资金方向是否一致

**评级标准：**
| 分数 | 等级 | 含义 |
|------|------|------|
| ≥70 | A | 强势，重点关注 |
| ≥55 | B | 偏强，可以关注 |
| ≥40 | C | 中性，观望为主 |
| ≥25 | D | 偏弱，谨慎参与 |
| <25 | E | 弱势，回避 |

### 2. 连续资金流入检测 (`continuous`)

检测股票是否出现持续的资金净流入：

```bash
python capital_flow.py continuous --stock 贵州茅台 --days 5
```

**信号含义：**
- 连续≥5日净流入：强势信号，主力建仓可能性大
- 连续3-4日净流入：偏强信号，需要配合其他指标确认
- 连续1-2日净流入：一般信号，可能是短期波动

### 3. 量价背离分析 (`divergence`)

识别价格与资金流向的背离关系：

```bash
python capital_flow.py divergence --stock 贵州茅台
```

**四种状态：**

| 类型 | 价格趋势 | 资金方向 | 操作建议 |
|------|---------|---------|---------|
| 健康上涨 | ↑ | 流入 | 持有/买入 |
| 顶背离 | ↑ | 流出 | 减仓/观望 |
| 底背离 | ↓ | 流入 | 关注/逢低买入 |
| 健康下跌 | ↓ | 流出 | 回避 |

### 4. 综合评分 (`score`)

对单只股票进行全面的资金强度评估：

```bash
python capital_flow.py score --stock 贵州茅台
```

## Python API调用

```python
from capital_flow import CapitalFlowSelector, CapitalFlowAnalyzer

# 初始化
selector = CapitalFlowSelector()

# 批量扫描
result_df = selector.scan_stocks(
    stock_names=["贵州茅台", "宁德时代", "比亚迪"],
    top_n=10,
    min_score=40.0
)

# 单只股票分析
analyzer = CapitalFlowAnalyzer(selector.mx)

# 连续流入检测
continuous = analyzer.calc_continuous_inflow("贵州茅台", days=5)

# 量价背离
divergence = analyzer.calc_price_flow_divergence("贵州茅台", days=20)

# 综合评分
score = analyzer.calc_capital_strength_score("贵州茅台")
```

## 与其他策略配合使用

资金流向策略适合与以下策略组合：

1. **多因子选股**: 将资金强度作为额外因子加入合成
2. **技术面确认**: 资金流入+技术指标金叉=增强信号
3. **基本面过滤**: 资金流入+低估值=安全边际更高

## 注意事项

- 盘中数据为实时快照，收盘后更准确
- 单日资金流向可能受大单干扰，建议看连续趋势
- 小市值股票的资金流向波动较大，需要更多确认信号
