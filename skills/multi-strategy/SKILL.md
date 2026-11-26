---
name: multi-strategy
display_name: A股多策略库 (Multi-Strategy Library)
title: A股多策略交易分析工具
description: 实现6大类18种经典交易策略的自动化执行和对比分析，支持趋势跟踪、均值回归、动量、龙头战法、低吸蓝筹、网格交易。
homepage: https://github.com/nousresearch/hermes-agent
author: Hermes Agent
version: 1.0.0
---

# A股多策略库 (Multi-Strategy Library)

实现 **6大类、18种** 经典交易策略的自动化执行和对比分析。每个策略独立函数，可单独调用也可组合使用，支持批量扫描全市场股票并输出信号强度评分。

## 六大策略体系概览

| # | 策略类别 | 包含策略数 | 核心思路 |
|---|---------|-----------|---------|
| 1 | **趋势跟踪** (Trend Following) | 4 | 跟随价格趋势，顺势而为 |
| 2 | **均值回归** (Mean Reversion) | 3 | 价格偏离均值后回归 |
| 3 | **动量策略** (Momentum) | 3 | 强者恒强，追涨杀跌 |
| 4 | **龙头战法** (Dragon Head) | 3 | 捕捉涨停板龙头股 |
| 5 | **低吸蓝筹** (Blue Chip Dip) | 3 | 低估值+高质量+回调买入 |
| 6 | **网格交易** (Grid Trading) | 2 | 区间震荡中自动买卖 |

## 依赖安装

```bash
pip install pandas numpy requests openpyxl
```

> 数据来自腾讯 / 东方财富公开行情接口，免费且无需任何 API Key。

## 快速开始

### 命令行调用

```bash
# 执行单个策略
python multi_strategy.py --strategy dual_ma_crossover 600519

# 对单只股票运行所有策略
python multi_strategy.py --all 贵州茅台

# 批量扫描多只股票（从文件读取）
python multi_strategy.py --strategy rsi_reversal --stocks stocks.txt

# 查看策略对比表
python multi_strategy.py --comparison

# 自定义参数
python multi_strategy.py --strategy breakout_n_day 000001 --n_days 60
```

### 作为模块导入

```python
from multi_strategy import (
    strategy_dual_ma_crossover,
    strategy_rsi_reversal,
    run_all_strategies,
    scan_stocks,
    generate_strategy_comparison
)

# 单策略分析
result = strategy_dual_ma_crossover("600519", ma_fast=5, ma_slow=20)
print(result["signal_strength"])  # 信号强度评分

# 全策略分析
results = run_all_strategies("贵州茅台")

# 批量扫描
scan_result = scan_stocks("rsi_reversal", ["600519", "000001", "300750"])
```

---

## 一、趋势跟踪策略 (Trend Following)

### 1. 双均线金叉/死叉 (`dual_ma_crossover`)

**逻辑说明：**
- MA5（短期均线）上穿MA20（中期均线）→ **金叉买入信号**
- MA5下穿MA20 → **死叉卖出信号**
- 信号强度基于均线偏离度计算，偏离越大信号越强

**适用市场环境：** 趋势行情（单边上涨或下跌），震荡市中易产生假信号。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ma_fast` | 5 | 短期均线周期 |
| `ma_slow` | 20 | 中期均线周期 |
| `period` | "近一年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy dual_ma_crossover 600519
# 自定义参数：MA10/MA30交叉
python multi_strategy.py --strategy dual_ma_crossover 贵州茅台 --ma_fast 10 --ma_slow 30
```

### 2. 三均线多头/空头排列 (`triple_ma_alignment`)

**逻辑说明：**
- MA5 > MA10 > MA20 → **多头排列**（上升趋势，买入/持有）
- MA5 < MA10 < MA20 → **空头排列**（下降趋势，卖出/观望）
- 均线纠缠 → **交叉状态**（方向不明，观望）

**适用市场环境：** 单边趋势行情效果最佳。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `period` | "近一年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy triple_ma_alignment 000001
```

### 3. MACD零轴上方金叉 (`macd_above_zero`)

**逻辑说明：**
- DIF和DEA均在零轴上方 + DIF上穿DEA → **强势买入信号**（最可靠）
- DIF在零轴下方金叉 → **弱势买入信号**（可靠性较低）
- 死叉 → **卖出信号**

**适用市场环境：** 上升趋势中零轴上方金叉最为可靠。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `period` | "近一年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy macd_above_zero 宁德时代
```

### 4. 突破N日新高/新低 (`breakout_n_day`)

**逻辑说明：**
- 股价突破过去N日内最高价 → **买入信号**（趋势加速）
- 股价跌破过去N日内最低价 → **卖出/止损信号**
- 区间内运行 → **观望**，计算当前位置百分比

**适用市场环境：** 强势行情中的突破确认。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `n_days` | 20 | 回看天数 |
| `period` | "近一年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy breakout_n_day 600519 --n_days 60
```

---

## 二、均值回归策略 (Mean Reversion)

### 5. RSI超卖反弹 (`rsi_reversal`)

**逻辑说明：**
- RSI < 30 → **超卖区域**，股价可能反弹（买入）
- RSI > 70 → **超买区域**，股价可能回调（卖出）
- 信号强度基于偏离极端值的程度计算

**适用市场环境：** 震荡市效果最佳；强趋势中RSI可能长期处于极端值。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `rsi_period` | 14 | RSI计算周期 |
| `oversold` | 30 | 超卖阈值 |
| `overbought` | 70 | 超买阈值 |
| `period` | "近一年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy rsi_reversal 600519
# 激进参数：RSI<20买入，>80卖出
python multi_strategy.py --strategy rsi_reversal 贵州茅台 --oversold 20 --overbought 80
```

### 6. BOLL下轨支撑/上轨压力 (`boll_band`)

**逻辑说明：**
- 股价跌破布林带下轨 → **超卖机会**（买入）
- 股价突破布林带上轨 → **超买风险**（卖出）
- 中轨上方运行 → **偏强持有**；中轨下方 → **偏弱观望**

**适用市场环境：** 区间震荡行情。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `period_param` | 20 | 布林带周期 |
| `num_std` | 2.0 | 标准差倍数 |
| `period` | "近一年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy boll_band 000001
```

### 7. 布林带收窄突破 (`boll_squeeze`)

**逻辑说明：**
- 带宽（BandWidth）收缩至阈值以下 → **变盘前兆**
- 收窄后股价向上突破中轨 → **买入信号**
- 收窄后股价向下跌破中轨 → **卖出信号**
- 非收窄状态下的突破可靠性较低

**适用市场环境：** 变盘期，窄幅震荡后的方向选择。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `period_param` | 20 | 布林带周期 |
| `num_std` | 2.0 | 标准差倍数 |
| `squeeze_threshold` | 5.0 | 收窄阈值（带宽%） |
| `lookback` | 10 | 回看天数计算平均带宽 |

**使用示例：**
```bash
python multi_strategy.py --strategy boll_squeeze 600519
```

---

## 三、动量策略 (Momentum)

### 8. N日涨幅排名选股 (`n_day_momentum`)

**逻辑说明：**
- 计算过去N日的涨跌幅，涨幅越大信号越强
- 结合波动率计算类夏普比率评估风险调整后收益
- 涨幅>10%为强势上涨，3%-10%为温和上涨

**适用市场环境：** 牛市或结构性行情。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `n_days` | 20 | 回看天数（常用20/60） |
| `period` | "近一年" | K线数据时间范围 |

**使用示例：**
```bash
# 20日涨幅
python multi_strategy.py --strategy n_day_momentum 300750 --n_days 20
# 60日涨幅
python multi_strategy.py --strategy n_day_momentum 宁德时代 --n_days 60
```

### 9. 相对强度RS策略 (`relative_strength`)

**逻辑说明：**
- 计算个股vs沪深300的累计收益率比率（RS Ratio）
- RS评分>80 → **强势股**（重点关注/买入）
- RS评分<40 → **弱势股**（回避）

**适用市场环境：** 任何市场，选股工具。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `period` | "近一年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy relative_strength 600519
```

### 10. 加速上涨策略 (`acceleration`)

**逻辑说明：**
- 比较近5日涨幅与前5日涨幅
- 近期涨幅 > 前期涨幅且为正 → **加速上涨**（买入/持有）
- 近期正涨、前期下跌 → **止跌反弹**（关注反转）
- 动能减弱 → **减仓/观望**

**适用市场环境：** 强势行情中的追涨确认。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `recent_days` | 5 | 近期天数 |
| `prior_days` | 5 | 前期天数 |
| `period` | "近一年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy acceleration 000001
```

---

## 四、龙头战法策略 (Dragon Head)

### 11. 连板梯队选股 (`consecutive_limit_up`)

**逻辑说明：**
- 统计连续涨停天数，≥2天为连板股（龙头候选）
- 近20日累计涨停次数≥2次为活跃股
- 信号强度随连板天数递增

**适用市场环境：** 热点题材行情，资金活跃期。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_boards` | 2 | 最低连板天数要求 |
| `period` | "近半年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy consecutive_limit_up 300750
```

### 12. 首板打板策略 (`first_limit_up`)

**逻辑说明：**
- 当日首次涨停（前一日未涨停）→ **首板信号**
- 流通市值<100亿为优选条件（需通过财务API确认）
- 连板涨停不符合首板条件

**适用市场环境：** 活跃市，题材启动初期。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_market_cap` | 100 | 最大流通市值（亿） |
| `period` | "近半年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy first_limit_up 300750
```

### 13. 换手板策略 (`turnover_limit_up`)

**逻辑说明：**
- 涨停 + 成交量放大>5% → **换手板**（资金活跃确认，买入）
- 涨停但缩量 → **缩量板**（谨慎关注）
- 高换手涨停可能为出货信号，需结合封单量判断

**适用市场环境：** 资金活跃期。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_turnover_pct` | 5.0 | 最低换手率要求（%） |
| `period` | "近半年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy turnover_limit_up 300750
```

---

## 五、低吸蓝筹策略 (Blue Chip Dip)

### 14. PE/PB低于行业均值 (`undervalued_pe_pb`)

**逻辑说明：**
- PE或PB低于历史均值20%以上 → **低估信号**
- PE和PB双低估 → **深度价值**（买入）
- 单指标低估 → **部分低估**（关注）

**适用市场环境：** 任何市场，长期价值投资。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `discount_threshold` | 20.0 | 折价阈值（%） |
| `period` | "近三年" | 财务数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy undervalued_pe_pb 600519
```

### 15. ROE稳定优质策略 (`roe_stable`)

**逻辑说明：**
- ROE > 15%且连续3年以上 → **ROE达标**
- ROE标准差 < 5 → **稳定性好**（买入/长期持有）
- 高ROE但波动大 → **需观察稳定性**

**适用市场环境：** 价值投资，长期持有。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_roe` | 15.0 | ROE最低要求（%） |
| `min_years` | 3 | 连续达标年数 |
| `period` | "近三年" | 财务数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy roe_stable 贵州茅台
```

### 16. 高股息回调策略 (`dividend_dip`)

**逻辑说明：**
- 股息率 > 3% → **高股息标的**
- 近6个月股价回调 > 10% → **安全边际充足**
- 双条件满足 → **买入（深度价值+低估值）**

**适用市场环境：** 熊市/震荡市，防御性配置。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `min_dividend_yield` | 3.0 | 最低股息率（%） |
| `min_pullback_pct` | 10.0 | 最低回调幅度（%） |
| `period` | "近两年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy dividend_dip 600519
```

---

## 六、网格交易策略 (Grid Trading)

### 17. 等差网格交易 (`grid_arithmetic`)

**逻辑说明：**
- 以基准价为中点，按固定百分比间距上下设置买卖档位
- 价格下跌到买入档 → **自动买入**；上涨到卖出档 → **自动卖出**
- 输出完整的网格交易计划表和历史触碰统计

**适用市场环境：** 区间震荡行情。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `base_price` | None（最新价） | 基准价格 |
| `grid_spacing` | 0.02 | 网格间距（2%） |
| `num_grids_up` | 5 | 上方网格数 |
| `num_grids_down` | 5 | 下方网格数 |
| `period` | "近半年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy grid_arithmetic 600519
# 自定义基准价和间距
python multi_strategy.py --strategy grid_arithmetic 贵州茅台 --base_price 1800 --grid_spacing 0.03
```

### 18. 等比网格交易 (`grid_geometric`)

**逻辑说明：**
- 以基准价为中点，按固定比例（复利）设置买卖档位
- 低价区密集、高价区稀疏 → **适合波动率较高的标的**
- 输出完整的网格交易计划表和分析建议

**适用市场环境：** 宽幅震荡行情。

**参数设置：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `base_price` | None（最新价） | 基准价格 |
| `grid_ratio` | 0.02 | 网格比例（2%） |
| `num_grids_up` | 5 | 上方网格数 |
| `num_grids_down` | 5 | 下方网格数 |
| `period` | "近半年" | K线数据时间范围 |

**使用示例：**
```bash
python multi_strategy.py --strategy grid_geometric 000001
```

---

## 策略对比表

| 策略 | 类别 | 胜率(参考) | 盈亏比(参考) | 适用周期 | 市场环境 |
|------|------|-----------|-------------|---------|---------|
| 双均线交叉 | 趋势跟踪 | ~55% | ~1.5:1 | 日线/周线 | 趋势行情 |
| 三均线排列 | 趋势跟踪 | ~60% | ~2:1 | 日线/周线 | 单边趋势 |
| MACD零轴金叉 | 趋势跟踪 | ~58% | ~1.8:1 | 日线 | 上升趋势 |
| 突破N日新高 | 趋势跟踪 | ~45% | ~2.5:1 | 日线/周线 | 强势行情 |
| RSI超卖反弹 | 均值回归 | ~60% | ~1.3:1 | 日线 | 震荡市 |
| BOLL支撑压力 | 均值回归 | ~55% | ~1.2:1 | 日线/60分钟 | 区间震荡 |
| 布林带收窄突破 | 均值回归 | ~50% | ~2:1 | 日线/周线 | 变盘期 |
| N日涨幅排名 | 动量 | ~45% | ~2.5:1 | 周线/月线 | 牛市/结构性行情 |
| 相对强度RS | 动量 | ~55% | ~2:1 | 周线 | 任何市场 |
| 加速上涨 | 动量 | ~40% | ~3:1 | 日线/60分钟 | 强势行情 |
| 连板梯队 | 龙头战法 | ~35% | ~3:1 | 日线(T+1) | 热点题材 |
| 首板打板 | 龙头战法 | ~40% | ~2.5:1 | 日线(盘中) | 活跃市 |
| 换手板 | 龙头战法 | ~45% | ~2:1 | 日线(T+1) | 资金活跃期 |
| PE/PB低估 | 低吸蓝筹 | ~65% | ~1.5:1 | 月线/季线 | 任何市场(长期) |
| ROE稳定优质 | 低吸蓝筹 | ~70% | ~2:1 | 季线/年线 | 价值投资 |
| 高股息回调 | 低吸蓝筹 | ~65% | ~1.8:1 | 月线 | 熊市/震荡市 |
| 等差网格 | 网格交易 | ~70% | ~1:1 | 分钟/日线 | 区间震荡 |
| 等比网格 | 网格交易 | ~65% | ~1.2:1 | 分钟/日线 | 宽幅震荡 |

> ⚠️ **注意：** 胜率和盈亏比为历史回测参考值，实际表现因市场环境和执行质量而异。数据仅供参考，不构成投资建议。

---

## 输出格式说明

### 终端输出

每个策略独立展示：
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 策略: 双均线交叉(MA5/MA20)
   标的: 600519
   最新价: ¥1856.00

   📋 信号详情:
      • 均线交叉: 金叉 → 买入
      • MA5: 1870.50
      • MA20: 1840.30

   🟢 信号强度: 85.0/100

   ⚠️ 风险提示:
      • 均线策略在震荡市中易产生假信号
      • 建议配合成交量确认

   📅 数据范围: 2024-01-01 ~ 2024-12-31
```

### JSON结果文件

自动保存到 `output/` 目录，结构示例：
```json
[
  {
    "strategy": "双均线交叉(MA5/MA20)",
    "stock": "600519",
    "latest_close": 1856.00,
    "signals": [
      {"type": "均线交叉", "value": "金叉", "action": "买入"},
      {"type": "MA5", "value": 1870.50},
      {"type": "MA20", "value": 1840.30}
    ],
    "signal_strength": 85.0,
    "risk_warning": ["均线策略在震荡市中易产生假信号"],
    "data_range": "2024-01-01 ~ 2024-12-31"
  }
]
```

---

## 批量扫描示例

创建 `stocks.txt` 文件（每行一个股票代码）：
```
600519
000001
300750
贵州茅台
平安银行
宁德时代
```

执行批量扫描：
```bash
python multi_strategy.py --strategy rsi_reversal --stocks stocks.txt
```

结果按信号强度降序排列，输出Top 10。

---

## API参考

### 核心函数

| 函数 | 说明 |
|------|------|
| `run_strategy(name, code, **kwargs)` | 运行指定策略 |
| `run_all_strategies(code)` | 对单只股票运行所有策略 |
| `scan_stocks(name, codes, **kwargs)` | 批量扫描多只股票 |
| `format_strategy_result(result)` | 格式化结果为可读字符串 |
| `save_results(results, path)` | 保存结果到JSON文件 |
| `generate_strategy_comparison()` | 生成策略对比表 |

### 策略函数列表

```python
# 趋势跟踪
strategy_dual_ma_crossover(stock_code, ma_fast=5, ma_slow=20)
strategy_triple_ma_alignment(stock_code)
strategy_macd_above_zero(stock_code)
strategy_breakout_n_day(stock_code, n_days=20)

# 均值回归
strategy_rsi_reversal(stock_code, rsi_period=14, oversold=30, overbought=70)
strategy_boll_band(stock_code, period_param=20, num_std=2.0)
strategy_boll_squeeze(stock_code, squeeze_threshold=5.0)

# 动量策略
strategy_n_day_momentum(stock_code, n_days=20)
strategy_relative_strength(stock_code)
strategy_acceleration(stock_code, recent_days=5, prior_days=5)

# 龙头战法
strategy_consecutive_limit_up(stock_code, min_boards=2)
strategy_first_limit_up(stock_code, max_market_cap=100)
strategy_turnover_limit_up(stock_code, min_turnover_pct=5.0)

# 低吸蓝筹
strategy_undervalued_pe_pb(stock_code, discount_threshold=20.0)
strategy_roe_stable(stock_code, min_roe=15.0, min_years=3)
strategy_dividend_dip(stock_code, min_dividend_yield=3.0, min_pullback_pct=10.0)

# 网格交易
strategy_grid_arithmetic(stock_code, base_price=None, grid_spacing=0.02)
strategy_grid_geometric(stock_code, base_price=None, grid_ratio=0.02)
```

---

## 注意事项

1. **技术指标仅供参考**，不构成投资建议。实际交易应结合基本面、市场环境综合判断。
2. 公开行情接口有调用频率限制，批量分析时注意间隔。
3. 龙头战法策略需要盘中实时数据支持最佳效果，日线级别为近似模拟。
4. 网格交易输出的是计划表，实际执行需配合自动交易系统。
5. 财务数据（PE/PB/ROE/股息率）通过东方财富数据中心公开报表获取，字段口径可能随接口调整而变化。
