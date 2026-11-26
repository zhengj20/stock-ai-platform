# A股自动化日报 (A-Share Daily Report)

收盘后自动生成综合市场复盘报告，整合多个分析模块生成多维度市场分析报告。

## 功能概述

| 模块 | 说明 | 数据来源 |
|------|------|----------|
| 大盘走势总结 | 三大指数涨跌、成交量变化、支撑阻力位、涨跌家数 | SmartDispatcher + AKShare/pytdx |
| 板块强弱排行 | 行业/概念TOP10涨跌、资金流向、轮动信号 | sector-rotation模块 |
| 市场情绪分析 | 综合评分(0-100)、恐惧贪婪指数、涨跌停统计 | market-sentiment模块 |
| 异动个股追踪 | 涨停股列表、放量突破、龙虎榜机构买入 | dragon-list + data_cache |
| 技术面信号汇总 | MACD金叉/死叉、RSI超买超卖、K线形态 | tech-indicators + kline-patterns |
| 明日展望策略 | 基于情绪评分的操作建议、重点关注池、风险提示 | 综合各模块输出 |

## 报告格式

- **Markdown** (`.md`) — 适合Hermes推送和终端阅读
- **HTML** (`.html`) — 精美排版，支持浏览器查看
- **JSON** (`.json`) — 结构化数据，供其他模块调用

## 依赖安装

```bash
pip install pandas numpy requests
```

> 需要以下skills已安装：`market-sentiment`, `sector-rotation`, `dragon-list`, `tech-indicators`, `kline-patterns`, `a-share-data-cache`

## 使用方法

### CLI入口

```bash
# 手动触发生成今日报告（默认详细模式）
python daily_report.py

# 简洁模式（终端快速浏览）
python daily_report.py --style concise

# 专业模式（完整分析+技术信号）
python daily_report.py --style professional

# 指定日期回查
python daily_report.py --date 2026-06-23

# 仅生成JSON数据版
python daily_report.py --format json

# 仅生成HTML完整版
python daily_report.py --format html

# 全部格式输出
python daily_report.py --format all

# 指定报告保存目录
python daily_report.py --output ./my_reports/

# 强制刷新所有数据（不走缓存）
python daily_report.py --force-refresh

# 定时任务模式（跳过终端输出，仅生成文件）
python daily_report.py --cronjob

# 查看帮助
python daily_report.py --help
```

### Hermes Cronjob 定时推送

通过Hermes cronjob实现每日15:30自动生成报告：

```bash
# 在Hermes中设置cronjob（北京时间15:30 = UTC 07:30）
hermes cron add --name "a-share-daily-report" \
    --schedule "30 7 * * 1-5" \
    --command "python daily_report.py --cronjob --style detailed --format all"
```

> ⏰ 北京时间 = UTC+8，所以北京15:30对应UTC 07:30。`1-5`表示周一至周五交易日执行。

### 三种报告风格

| 风格 | 适用场景 | 内容范围 |
|------|----------|----------|
| `concise` (简洁) | 终端快速浏览/推送通知 | 大盘概览+情绪评分+板块TOP5 |
| `detailed` (详细) | 日常复盘（默认） | 全部6大模块，适中深度 |
| `professional` (专业) | 深度分析/投资决策 | 全部模块+技术信号+策略建议 |

## 数据获取策略

通过 `data_cache.py` 的 **SmartDispatcher** 实现四级智能调度（v2.0无缓存版），全部为免费公开接口：

1. **Level 1**: pytdx通达信行情（TCP直连~30ms，无限制 ⭐首选）
2. **Level 2a**: 东方财富公开接口直连（K线/行情/板块/涨停池，无限制）
3. **Level 2b**: 新浪/腾讯财经备用源（HTTP GET）

> v2.0变更：已移除SQLite缓存层。pytdx 30ms直连+无限制，缓存价值不再存在。
> 任一数据项取不到时，日报中直接标注"暂无数据"，不使用任何估算或占位数据。

## 输出文件结构

```
reports/
├── 2026-06-24/
│   ├── daily_report_2026-06-24.md      # Markdown版
│   ├── daily_report_2026-06-24.html    # HTML精美排版
│   └── daily_report_2026-06-24.json    # JSON结构化数据
├── 2026-06-23/
│   └── ...
```

## 模块集成关系

```
daily_report.py (主入口)
├── market-sentiment/market_sentiment.py → 情绪评分(0-100)
├── sector-rotation/sector_rotation.py   → 板块排名+资金流向
├── dragon-list/dragon_list.py           → 龙虎榜+游资席位
├── tech-indicators/tech_indicators.py   → MACD/KDJ/RSI/BOLL
├── kline-patterns/kline_patterns.py     → K线形态识别
└── a-share-data-cache/data_cache.py     → SmartDispatcher数据调度
```

## 注意事项

1. **交易日判断**：自动跳过周末和节假日，仅交易日生成报告
2. **免费数据源**：全部使用pytdx/东财/新浪/腾讯公开接口，无需API Key
3. **容错机制**：单个模块失败不影响整体报告生成，标记为"暂无数据"
4. **盘中运行**：建议在15:00收盘后运行，确保数据完整
