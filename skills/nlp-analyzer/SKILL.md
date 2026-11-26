# A股自然语言对话分析引擎 (NLP Analyzer)

基于规则引擎的A股自然语言对话分析Skill，解析用户自然语言问题后自动组合多个分析模块，给出综合推荐报告。

## 功能概述

| 意图类型 | 示例查询 | 调用模块 |
|---------|---------|---------|
| 🔍 **个股诊断** | "帮我看看贵州茅台怎么样" | 腾讯实时行情 + tech-indicators指标 + kline-patterns形态 + multi-factor基本面 |
| 📊 **选股推荐** | "找一只适合低吸的股票" | multi-factor多因子选股 + market-sentiment情绪过滤 |
| 📈 **行情查询** | "今天大盘走势如何" | 腾讯指数行情 + market-sentiment市场情绪 |
| 🏭 **板块分析** | "新能源板块最近怎么样" | 新浪板块行情（涨跌幅/家数/成交额/领涨股） |
| 📰 **资讯搜索** | "比亚迪有什么最新消息" | 指引至平台 AI 助手（本地无免费资讯源，不伪造新闻） |
| ⚙️ **策略执行** | "超跌反弹选股结果出来了吗" | a-share-oversold-rebound-strategy |

## 核心模块

### 1. 意图识别引擎 (`IntentClassifier`)

基于关键词规则 + 正则表达式的本地NLP分类器，不依赖外部LLM API。

```python
from nlp_analyzer import IntentClassifier

classifier = IntentClassifier()
result = classifier.classify("帮我看看贵州茅台怎么样")
# {
#   "intent": "stock_diagnosis",
#   "confidence": 0.85,
#   "entities": {"stock": "贵州茅台"},
#   "conditions": {},
# }
```

支持的意图类型：
- `stock_diagnosis` — 个股诊断
- `stock_selection` — 选股推荐
- `market_query` — 行情查询
- `sector_analysis` — 板块分析
- `news_search` — 资讯搜索
- `strategy_run` — 策略执行

### 2. 智能路由调度器 (`SkillRouter`)

根据意图自动选择并组合多个Skill模块：

```python
from nlp_analyzer import SkillRouter, IntentClassifier

classifier = IntentClassifier()
router = SkillRouter()

intent_result = classifier.classify("帮我看看贵州茅台怎么样")
plans = router.route(intent_result)  # 生成执行计划

# 串行执行各模块
for plan in plans:
    result = router.execute(plan)
    print(f"[{plan['description']}] {result['status']}")
```

路由策略：
- **单模块调用** — 简单查询（如资讯搜索）直接调用单一模块
- **多模块串联** — 个股诊断依次调用行情→指标→形态→基本面
- **条件过滤** — "找低估值高成长股票"自动设置价值因子+成长因子权重

### 3. 综合报告生成 (`ReportGenerator`)

将多个模块输出整合为结构化中文报告：

#### 个股诊断报告模板
```
============================================================
📊 贵州茅台 — 个股综合诊断报告
   生成时间: 2026-06-24 15:30
============================================================

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 一、行情概览
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   （腾讯实时行情：最新价、涨跌幅、今开/最高/最低、成交额、换手率、PE/PB、总市值）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 二、技术指标信号
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   （tech-indicators输出：MACD金叉/死叉、RSI超买/超卖等）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 三、K线形态识别
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   （kline-patterns输出：十字星、锤子线等形态信号）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 四、基本面多因子分析
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   （multi-factor输出：估值、成长、质量因子评分）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 五、综合评估
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   • 贵州茅台：技术面偏多（买入信号3 vs 卖出信号1），趋势较强
     → 建议关注，但需设置止损位
```

#### 选股推荐报告模板
```
============================================================
📊 A股多因子选股推荐报告
   生成时间: 2026-06-24 15:30
   筛选条件: value_weight=0.7, growth_weight=0.3

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 一、候选股票列表
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   （multi-factor输出：排名、因子得分）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 二、市场情绪环境
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   （market-sentiment输出：当前情绪评分与状态）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 三、风险提示
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   • 选股结果基于历史数据和量化模型，不保证未来表现
```

#### 市场分析报告模板
```
============================================================
📊 A股市场综合分析报告
   生成时间: 2026-06-24 15:30
============================================================

📈 一、大盘指数走势    （上证指数/深证成指/创业板指）
📊 二、市场情绪评分    （恐惧贪婪指数/VIX类比指标）
📊 三、板块强弱分析    （领涨/领跌板块）
📊 四、异动提示        （涨停/跌停/放量个股）
```

### 4. 对话记忆 (`ConversationMemory`)

支持多轮对话上下文理解：

| 用户输入 | 消歧后查询 | 说明 |
|---------|-----------|------|
| "帮我看看贵州茅台怎么样" | (原样) | 首次查询，记录last_stock="贵州茅台" |
| "再看看它的基本面" | "贵州茅台的基本面" | 指代上一只股票 |
| "那这只呢？" | "帮我看看贵州茅台怎么样" | 对比分析同一只股票 |

## 使用方法

### CLI — 单次查询模式

```bash
# 个股诊断
python nlp_analyzer.py "帮我看看贵州茅台怎么样"

# 选股推荐
python nlp_analyzer.py "找一只适合低吸的股票"

# 行情查询
python nlp_analyzer.py "今天大盘走势如何"

# 板块分析
python nlp_analyzer.py "新能源板块最近怎么样"

# 资讯搜索
python nlp_analyzer.py "比亚迪有什么最新消息"

# 策略执行
python nlp_analyzer.py "超跌反弹选股结果出来了吗"

# 仅显示意图识别结果（不执行分析）
python nlp_analyzer.py --intent-only "大盘走势如何"
```

### CLI — 对话模式

```bash
python nlp_analyzer.py --chat
```

进入交互式对话，支持多轮上下文理解。输入 `quit` / `exit` / `q` 退出。

### CLI — 批量处理

```bash
# queries.txt 每行一个查询
python nlp_analyzer.py --batch queries.txt
```

### Python API

```python
from nlp_analyzer import NLPAnalyzer, IntentClassifier, SkillRouter, ReportGenerator

# ── 方式1: 完整分析流程 ────────────────────────
analyzer = NLPAnalyzer()
report = analyzer.analyze("帮我看看贵州茅台怎么样")
print(report)

# ── 方式2: 仅意图识别 ──────────────────────────
classifier = IntentClassifier()
result = classifier.classify("今天大盘走势如何")
print(f"意图: {result['intent']}, 置信度: {result['confidence']}")

# ── 方式3: 手动路由执行 ────────────────────────
router = SkillRouter()
plans = router.route(result)
for plan in plans:
    output = router.execute(plan)
    print(f"[{plan['description']}] → {output['status']}")

# ── 方式4: 自定义报告生成 ────────────────────────
reporter = ReportGenerator()
report = reporter.generate(result["intent"], results, result["entities"])
print(report)
```

## 选股条件映射

| 自然语言关键词 | 因子权重配置 |
|--------------|------------|
| "低估值" | value_weight=0.7, growth_weight=0.3 |
| "高成长" | value_weight=0.3, growth_weight=0.7 |
| "低吸" | momentum_weight=0.5, oversold_filter=True |
| "蓝筹" | large_cap_filter=True, quality_weight=0.8 |
| "白马" | quality_weight=0.9, stability_weight=0.7 |
| "小盘" | small_cap_filter=True |

## 依赖

```
pandas>=2.0
numpy>=1.24
re (Python标准库)
requests (通过子进程调用各模块时由被调模块使用)
```

安装：
```bash
pip install pandas numpy requests openpyxl
```

## 文件结构

```
nlp-analyzer/
├── SKILL.md              # 本说明文档
└── nlp_analyzer.py       # 主脚本（意图识别+路由调度+报告生成+对话记忆）
```

## 注意事项

1. **数据源**：全部使用免费公开接口（腾讯 qt.gtimg.cn 行情、新浪板块行情），无需 API Key
2. **子进程调用**：各分析模块通过subprocess调用，确保Python环境一致
3. **超时控制**：单个模块调用默认60-180秒超时
4. **免责声明**：所有分析报告仅供参考，不构成投资建议
