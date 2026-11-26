---
name: a-share-architecture
display_name: A股分析系统架构指南 (A-Share System Architecture)
title: A股量化分析体系 v2.1 架构总览、数据流与模块依赖关系
description: 定义A股分析系统的整体架构：14个Skills的分层设计、四级数据调度链（pytdx→东财直连→新浪→腾讯）、模块间调用约定和集成规范。
version: 2.1.0
---

# A股量化分析体系 v2.1 — 架构指南

## 系统概览

```
🏗️ Hermes fenxi profile (14 Skills)
│
├── 🔍 数据层 (1个)
│   └── a-share-data-cache → pytdx/东财直连/新浪/腾讯 四级调度（无缓存）
│
├── 📈 分析层 (9个)
│   ├── tech-indicators → MACD/KDJ/RSI/BOLL/MA等10项指标
│   ├── kline-patterns → 21种K线形态识别（需DataFrame输入）
│   ├── multi-factor → 27因子量化选股
│   ├── market-sentiment → 情绪评分+恐惧贪婪指数
│   ├── nlp-analyzer → 自然语言意图识别→智能路由
│   ├── ml-stock-picker → LightGBM/XGBoost机器学习选股
│   ├── sector-rotation → 板块资金流向/强度排名
│   ├── dragon-list → 龙虎榜+游资席位分析
│   └── multi-strategy → 6大类18种交易策略
│
├── 📊 可视化层 (2个)
│   ├── a-share-visualization → K线图+指标叠加+PNG/HTML导出
│   └── a-share-daily-report → 自动复盘报告（Markdown/HTML/JSON）
│
├── 🤖 入口层 (1个)
│   └── a-share-analysis-toolkit → 总览导航+智能路由
│
└── 📋 策略层 (1个)
    └── a-share-oversold-rebound-strategy → 超跌反弹隔日选股（定时推送）
```

## 数据调度链（四级优先级）

```
用户请求 → SmartDispatcher.dispatch_quote() / dispatch_kline()
           │
           ├─ Level 1: pytdx通达信 ⭐首选
           │    • TCP直连 ~30ms，无配额限制
           │    • 支持：实时行情、日/周/月K线、5/15/30/60分钟K线、Level-1分笔成交
           │    • API: DataFetcher.fetch_pytdx_quote() / fetch_pytdx_kline() / fetch_pytdx_transaction()
           │
           ├─ Level 2: 东方财富直连（原 AKShare 封装）
           │    • HTTP ~500ms，无配额限制
           │    • 支持：全市场行情、K线、财务摘要、概念板块
           │    • API: DataFetcher.fetch_akshare_quote() / fetch_akshare_kline() / fetch_akshare_finance()
           │
           ├─ Level 3: 新浪财经API
           │    • HTTP ~100ms，无配额限制（GBK编码）
           │    • 支持：实时行情、历史K线
           │    • API: DataFetcher.fetch_sina_quote() / fetch_sina_kline()
           │
           └─ Level 4: 腾讯财经API
                • HTTP ~120ms，无配额限制（GBK编码）
                • 支持：实时行情、K线、板块数据
                • API: DataFetcher.fetch_tencent_quote() / fetch_tencent_kline()
```

## 模块间调用约定

### 数据获取统一入口

所有分析模块通过 `a-share-data-cache` 的 `SmartDispatcher` 获取数据：

```python
from a_share_data_cache.data_cache import SmartDispatcher

dispatcher = SmartDispatcher()

# 行情查询（自动走四级调度）
result = dispatcher.dispatch_quote(["600519", "000001"])
# → result["symbols"] 字典, result["source"] 数据来源标识

# K线查询
kline_result = dispatcher.dispatch_kline("600519", period="daily", count=200)
# → kline_result["data"] 列表, kline_result["source"] 来源

# 分钟级K线（pytdx独有）
min_kline = dispatcher.dispatch_kline("600519", period="min30", count=40)

# 财务数据
finance_result = dispatcher.dispatch_finance("600519")
```

### 技术指标计算约定

```python
import pandas as pd, numpy as np
from tech_indicators import calc_macd, calc_kdj, calc_rsi, calc_boll, calc_ma

# ⚠️ 输入必须是 pd.Series（不是numpy数组）
close = pd.Series(kline_data['close'])
high = pd.Series(kline_data['high'])
low = pd.Series(kline_data['low'])

macd = calc_macd(close)           # → {'DIF': Series, 'DEA': Series, 'MACD_Hist': Series}
kdj  = calc_kdj(high, low, close) # → {'K': Series, 'D': Series, 'J': Series}
rsi  = calc_rsi(close, 14)        # → {'RSI14': Series}（支持int或list参数）
boll = calc_boll(close, 20)       # → {'BOLL_UPPER', 'BOLL_MID', 'BOLL_LOWER'}
ma   = calc_ma(close, [5,10,20])  # → {'MA5': Series, 'MA10': Series, 'MA20': Series}
```

### K线形态识别约定

```python
from kline_patterns import detect_bullish_engulfing, detect_morning_star

# ⚠️ 输入必须是 DataFrame（含 OHLCV 列）
df = pd.DataFrame({
    'open': open_prices, 'high': high_prices,
    'low': low_prices, 'close': close_prices, 'volume': volumes
})

patterns = detect_bullish_engulfing(df)  # → List[PatternSignal]
```

## 关键设计决策

| 决策 | 原因 |
|------|------|
| **无缓存架构** | pytdx 30ms直连+无限制，比缓存更快更简洁。原65KB/1571行精简至29KB/742行（-80%） |
| **pd.Series而非numpy数组** | pandas的`.ewm()`, `.rolling()`等方法在技术指标计算中更高效 |
| **kline-patterns需DataFrame输入** | 形态识别需要多列协同分析，DataFrame比独立数组更直观 |

## pytdx注意事项

- **非交易时间**: 收盘后服务器不推送实时数据（正常），历史K线仍可获取
- **连接超时**: 审计测试时设置 `timeout 3` 避免阻塞
- **股票代码格式**: 纯数字字符串 `"600519"`，不带市场前缀
- **市场代码自动推断**: `_code_to_market()` — 6/9开头→上海(0)，0/3开头→深圳(1)

## API凭证说明

所有数据源（pytdx / AKShare / 新浪财经 / 腾讯财经 / 东方财富公开接口）均为免费公开接口，**无需任何 API Key**。

```bash
# 平台自身的 JWT 签名密钥通过环境变量注入
export SECRET_KEY="<随机生成的强密钥>"

# ⚠️ 严禁在代码中硬编码任何密钥
```
