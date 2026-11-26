---
name: a-share-data-cache
display_name: A股多源数据调度引擎 (A-Share Data Dispatcher)
title: A股多源数据调度引擎 v2.0（无缓存版）
description: pytdx通达信(最高优先级，无限制+毫秒级) → 东财直连 → 新浪 → 腾讯。纯实时获取，零缓存开销。v2.0已移除SQLite缓存层。
version: 2.0.0
---

# a-share-data-cache A股多源数据调度引擎 v2.0

## 概述

本 Skill 提供**四源并行数据获取**，纯实时模式（零缓存），通过智能调度自动选择最优数据源。

> **v2.0变更**: 已移除SQLite缓存层、TTL过期策略和配额追踪器。pytdx通达信接口30ms直连+无限制，缓存价值不再存在。代码从65KB/1571行精简至29KB/742行（-80%）。

### 核心能力

| 功能模块 | 说明 |
|---------|------|
| **DataFetcher** | pytdx通达信/新浪/腾讯/东财直连四源并行数据获取器 |
| **SmartDispatcher** | 智能调度器（pytdx→东财直连→新浪→腾讯） |

---

## 数据源对比表

| 数据源 | 覆盖范围 | 频率限制 | 稳定性评分 | 数据类型支持 |
|--------|---------|---------|-----------|-------------|
| **pytdx通达信** ⭐最高优先级 | A股全市场+分钟K线+分笔成交 | ⚡ 无限制 | ★★★★★ (5/5) | 实时行情、日/周/月K线、5/15/30/60分钟K线、Level-1逐笔成交 |
| **东财直连API** | A股+港股+美股 | ⚡ 无限制 | ★★★★★ (5/5) | 实时行情、K线、财务摘要、概念板块 |
| **新浪财经API** | A股全市场 | ⚡ 无限制 | ★★★★☆ (4/5) | 实时行情、历史K线、指数行情 |
| **腾讯财经API** | A股全市场 | ⚡ 无限制 | ★★★★☆ (4/5) | 实时行情、历史K线、板块数据 |

---

## 调度架构

```
用户请求 → SmartDispatcher
           │
           ├─ Level 1: pytdx通达信 ⭐首选（TCP直连，~30ms，无限制）
           │    └─ 实时行情 / K线(日/周/月/分钟) / 分笔成交
           │
           ├─ Level 2: 东财直连API（HTTP GET，~500ms，无限制）
           │    └─ 全市场行情 / K线 / 财务数据
           │
           ├─ Level 3: 新浪财经API（HTTP GET，~100ms，无限制）
           │    └─ 实时行情 / 历史K线
           │
           └─ Level 4: 腾讯财经API（HTTP GET，~120ms，无限制）
                └─ 实时行情 / K线 / 板块数据
```

---

## CLI使用示例

### 1. 实时行情查询
```bash
cd skills/a-share-data-cache

# 单只股票
python data_cache.py quote 600519

# 多只股票
python data_cache.py quote 600519 000001 601318

# 输出示例:
# 📊 实时行情 (数据源: pytdx)
# ============================================================
#   贵州茅台(600519): ¥1207.68 | 🔴 -1.21% | 量: 32456
```

### 2. K线数据查询
```bash
# 日线（默认）
python data_cache.py kline 600519 --count 200

# 周线/月线
python data_cache.py kline 600519 --period weekly --count 52
python data_cache.py kline 600519 --period monthly --count 24

# 分钟级K线（pytdx独有）
python data_cache.py kline 600519 --period min5 --count 48
python data_cache.py kline 600519 --period min30 --count 40
```

### 3. 财务数据查询
```bash
python data_cache.py finance 600519
# → 东财直连财务接口；取不到时data为None并输出告警
```

### 4. pytdx连通性测试
```bash
python data_cache.py test-pytdx
# → 自动选择最优通达信服务器并获取行情
```

---

## Python API使用

```python
from data_cache import SmartDispatcher, DataFetcher

dispatcher = SmartDispatcher()

# === 实时行情（自动走pytdx→东财直连→新浪→腾讯）===
result = dispatcher.dispatch_quote(["600519", "000001"])
print(f"数据源: {result['source']}")
for code, data in result["symbols"].items():
    print(f"{data['name']}({code}): ¥{data['price']} | {data['change_pct']}%")

# === K线数据（支持分钟级）===
kline_result = dispatcher.dispatch_kline("600519", period="daily", count=200)
for bar in kline_result["data"][:5]:
    print(f"{bar['date']}: O={bar['open']} C={bar['close']}")

# 分钟级K线（pytdx独有）
min_kline = dispatcher.dispatch_kline("600519", period="min5", count=48)

# === 财务数据===
finance_result = dispatcher.dispatch_finance("600519")

# === pytdx专用方法（直接调用）===
fetcher = DataFetcher()

# 实时行情
quotes = fetcher.fetch_pytdx_quote(["600519", "000001"])

# K线（日/周/月/分钟）
klines = fetcher.fetch_pytdx_kline("600519", period="min30", count=40)

# 分笔成交（Level-1逐笔）
ticks = fetcher.fetch_pytdx_transaction("600519", count=200)
```

---

## pytdx核心优势

| 特性 | pytdx | HTTP API(新浪/腾讯) |
|------|-------|-------------------|
| **延迟** | ~30ms (TCP直连) | ~100-500ms (HTTP) |
| **配额限制** | ❌ 无限制 | ⚠️ 部分有频率限制 |
| **分钟级K线** | ✅ 5/15/30/60分钟全支持 | ❌ 大多只有日线 |
| **分笔成交** | ✅ Level-1逐笔委托+成交 | ❌ 不支持 |
| **稳定性** | ★★★★★ (通达信公共服务器) | ★★★★☆ |

---

## ⚠️ 已知问题与注意事项

### pytdx非交易时间获取不到实时行情
A: 正常现象。通达信服务器在非交易时段不推送实时数据，但历史K线仍可获取。pytdx连接测试可能超时（3秒），建议设置合理timeout。

### AKShare安装
```bash
pip install akshare --upgrade
# 如果网络问题：
pip install akshare -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### v2.0变更说明
- **已移除**: SQLite缓存层、TTL过期策略、配额追踪器、批量预加载器
- **原因**: pytdx 30ms直连+无限制，缓存价值不再存在
- **影响**: 代码量从65KB/1571行精简至29KB/742行（-80%）

---

## FAQ

### Q: 数据源有配额限制吗？
A: 没有。pytdx/东财直连/新浪/腾讯均为免费公开接口，无每日配额。本引擎只支持按代码取数，自然语言查询能力已移除；调度失败时返回空结果并输出告警。

### Q: pytdx需要安装吗？
```bash
pip install pytdx   # 已安装 v1.72
```
