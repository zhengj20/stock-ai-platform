---
name: a-share-analysis-toolkit
description: A股分析统一入口——全部分析模块的总览导航、智能路由中心、快捷命令执行器与健康检查工具（数据源均为免费公开接口）
version: 2.2.0
---

# A股分析统一入口 (A-Share Analysis Toolkit) v2.1

> **全部12个分析模块的总览导航和智能路由中心** — 一个入口，掌控全局。

## 触发条件

用户需要以下任一能力时加载本 Skill：
- 查看/浏览全部已安装的分析模块
- 通过自然语言指令自动匹配并调用合适的Skill组合
- 执行预设快捷分析模板（个股诊断/选股推荐/市场复盘/策略扫描）
- 检查所有Skills的安装状态和API连通性
- 获取某个Skill的详细使用指南

---

## 一、能力矩阵总览 (Capability Matrix)

### 分类概览

| 类别 | 模块数 | Skills |
|------|--------|--------|
| 📊 **数据获取** | 1 | a-share-data-cache |
| 🔬 **技术分析** | 3 | tech-indicators, kline-patterns, nlp-analyzer |
| 🧮 **量化选股** | 3 | multi-factor, ml-stock-picker, multi-strategy |
| 📡 **市场监控** | 2 | market-sentiment, sector-rotation |
| ⚡ **策略执行** | 1 | dragon-list |
| 📈 **可视化与报告** | 2 | a-share-visualization, a-share-daily-report |

### 完整能力矩阵

#### 📊 数据获取层 (1个模块)

| Skill | 一句话描述 | 适用场景 |
|-------|-----------|---------|
| `a-share-data-cache` | pytdx通达信/新浪/腾讯/AKShare多源智能调度（无缓存版） | pytdx实时行情(无限制毫秒级)/分钟K线(5/15/30/60min)/Level-1分笔成交、AKShare全量数据 |

#### 🔬 技术分析层 (3个模块)

| Skill | 一句话描述 | 适用场景 |
|-------|-----------|---------|
| `tech-indicators` | 10项经典技术指标计算引擎，自动输出金叉死叉和超买超卖信号 | MACD/KDJ/RSI/BOLL/MA/SAR/CCI/WR/OBV/VOL指标计算、均线系统分析、买卖信号识别 |
| `kline-patterns` | 21种经典K线形态自动识别系统，含单根/双根/多根形态及置信度评分 | 看涨看跌形态扫描、反转信号检测（十字星/锤子线/吞没等）、持续形态确认 |
| `nlp-analyzer` | NLP意图识别+智能路由引擎，6种意图分类自动组合多模块生成综合报告 | 自然语言个股诊断、多轮对话上下文记忆、综合分析报告一键生成 |

#### 🧮 量化选股层 (3个模块)

| Skill | 一句话描述 | 适用场景 |
|-------|-----------|---------|
| `multi-factor` | 27个经典量化因子（价值/成长/质量/动量/波动/流动性），支持Z-Score标准化和IC加权合成 | 低估值高成长筛选、自定义因子权重配置、多因子综合评分排名 |
| `ml-stock-picker` | LightGBM/XGBoost模型驱动的智能选股，支持特征工程训练预测全流程 | 模型训练与交叉验证评估、批量股票打分排序、超参数调优 |
| `multi-strategy` | 6大类18种经典交易策略库（趋势跟踪/均值回归/动量/龙头战法/低吸蓝筹/网格交易） | 策略信号扫描、多策略对比回测、信号强度排名输出 |

#### 📡 市场监控层 (2个模块)

| Skill | 一句话描述 | 适用场景 |
|-------|-----------|---------|
| `market-sentiment` | 17项市场情绪指标+综合评分（0-100分），五档状态分类（冰点/低迷/温和/亢奋/过热） | 大盘情绪评估、涨跌家数统计、连板高度分析、恐慌贪婪指数监控 |
| `sector-rotation` | 行业/概念板块行情总览+资金流向TOP10+RPS强度排名+热点题材追踪+四阶段周期定位 | 板块涨跌排行、资金流向分析、热点题材发现、轮动信号判断 |

#### ⚡ 策略执行层 (1个模块)

| Skill | 一句话描述 | 适用场景 |
|-------|-----------|---------|
| `dragon-list` | 龙虎榜数据获取+游资席位数据库(50+)，机构vs游资力量对比，4种选股策略 | 今日龙虎榜查看、游资席位追踪、机构动向分析、龙虎榜选股（机构净买/游资合力/共振/溢价） |

---

## 二、智能路由引擎 (Smart Router)

### 工作原理

```
用户自然语言输入
       │
       ▼
┌─────────────┐     ┌──────────────┐
│ 条件过滤匹配 │────▶│ multi-factor  │ ← "找低估值高成长股票"
│ (优先级最高) │     │ +自定义权重   │
└──────┬──────┘
       │ 未命中
       ▼
┌─────────────┐     ┌──────────────┐
│ 复合规则匹配 │────▶│ 多模块串联    │ ← "帮我看看宁德时代怎么样"
│ (关键词≥1)  │     │ nlp-analyzer + tech-indicators + kline-patterns + multi-factor
└──────┬──────┘
       │ 未命中
       ▼
┌─────────────┐     ┌──────────────┐
│ 单模块匹配   │────▶│ 直接调用      │ ← "贵州茅台最新价" → nlp-analyzer(内置腾讯行情)
│ (关键词≥1)  │     │               │
└──────┬──────┘
       │ 未命中
       ▼
┌─────────────┐
│ 全局扫描    │ ← 遍历所有Skills的关键词库
│ (兜底策略)  │
└─────────────┘
```

### 路由规则说明

#### 1. 条件过滤路由（优先级最高）

当输入包含特定因子关键词时，自动配置multi-factor的参数：

| 关键词 | 目标Skill | 自动参数 |
|--------|----------|---------|
| "低估值" / "低估" | multi-factor | factors=value, weight=PE:0.4,PB:0.3,PS:0.3 |
| "高成长" / "成长型" | multi-factor | factors=growth, weight=营收增速:0.4,利润增速:0.4,PEG:0.2 |
| "低估值高成长" | multi-factor | factors=value,growth, 混合权重配置 |

#### 2. 复合规则路由（多模块串联）

| 模板名称 | 触发关键词 | 调用链 |
|---------|-----------|--------|
| **个股诊断** | "怎么样", "分析一下", "全面分析", "深度分析", "诊断" | nlp-analyzer(行情) → tech-indicators → kline-patterns → multi-factor |
| **选股推荐** | "选只股票", "推荐股票", "买什么", "值得买的" | multi-factor → market-sentiment → dragon-list |
| **市场复盘** | "今天大盘", "市场怎么样", "复盘", "今日行情" | nlp-analyzer(指数) → sector-rotation → market-sentiment → dragon-list |
| **策略扫描** | "运行策略", "策略信号", "信号排名" | multi-strategy → market-sentiment |

#### 3. 单模块精确匹配

关键词直接映射到对应Skill，例如：
- "最新价"/"收盘价"/"行情" → `nlp-analyzer`（内置腾讯实时行情）
- "MACD"/"KDJ"/"RSI"/"技术指标" → `tech-indicators`
- "龙虎榜"/"游资" → `dragon-list`

### 使用示例

```bash
# 单模块路由 — 简单查询
python toolkit.py route "贵州茅台最新价"
# → [nlp-analyzer] 内置腾讯实时行情

# 多模块串联 — 综合分析
python toolkit.py route "帮我看看宁德时代怎么样"
# → nlp-analyzer + tech-indicators + kline-patterns + multi-factor

# 条件过滤路由 — 因子选股
python toolkit.py route "找低估值高成长股票"
# → multi-factor (自动配置价值+成长因子权重)
```

---

## 三、快捷命令系统 (Quick Commands)

### 预设分析模板

| 命令ID | 名称 | 描述 | 调用链 |
|--------|------|------|--------|
| `stock-diag` | **个股诊断** | 全方位个股深度分析 | nlp-analyzer(行情) → tech-indicators(技术指标) → kline-patterns(K线形态) → multi-factor(基本面评分) |
| `stock-pick` | **选股推荐** | 多因子筛选+情绪过滤+龙虎榜验证 | multi-factor(多因子) → market-sentiment(情绪过滤) → dragon-list(龙虎榜验证) |
| `market-review` | **市场复盘** | 大盘走势+板块排行+情绪评分+异动个股 | nlp-analyzer(指数) → sector-rotation(板块) → market-sentiment(情绪) → dragon-list(异动) |
| `strategy-scan` | **策略扫描** | 多策略信号排名+环境判断 | multi-strategy(策略库) → market-sentiment(情绪环境) |

### 使用示例

```bash
# 个股诊断 — 需要股票代码或名称参数
python toolkit.py quick stock-diag 600519
python toolkit.py quick stock-diag "贵州茅台"

# 选股推荐 — 无需参数，自动扫描全市场
python toolkit.py quick stock-pick

# 市场复盘 — 生成当日完整复盘报告
python toolkit.py quick market-review

# 策略扫描 — 运行所有策略并输出信号排名
python toolkit.py quick strategy-scan
```

---

## 四、模块状态监控 (Health Check)

### 检查内容

1. **Skills安装状态** — 遍历全部15个Skills目录，验证：
   - 目录是否存在且为有效文件夹
   - Python脚本文件是否可访问
   - SKILL.md文档是否存在

2. **数据源连通性测试** — 实时检测免费公开接口：
   - `qt.gtimg.cn` (腾讯行情) — 指数快照验证
   - `money.finance.sina.com.cn` (新浪板块) — 板块行情验证
   - `datacenter-web.eastmoney.com` (东财数据中心) — 估值报表验证

3. **Python依赖完整性** — 检查所有必需和可选包：
   - 必需: pandas, numpy, requests
   - 可选: lightgbm, xgboost, scikit-learn, scipy

### 使用方式

```bash
python toolkit.py health
# → 输出完整健康报告，JSON格式保存至 health_report.json
```

---

## 五、使用指南生成器 (Usage Guide)

根据Skill名称或自然语言问题自动生成对应的调用示例：

```bash
# 查看特定Skill的使用指南
python toolkit.py guide tech-indicators

# 通过问题自动匹配并展示相关Skills的用法
python toolkit.py guide "我想做技术分析"
# → 自动匹配 tech-indicators + kline-patterns，展示两者的调用示例
```

输出内容包括：
- Skill描述和适用场景
- CLI命令行调用方式（含具体参数示例）
- Python API导入方式
- 主要参数说明文档

---

## 六、CLI命令参考

### 完整命令列表

| 命令 | 用法 | 功能 |
|------|------|------|
| `overview` | `python toolkit.py overview [关键词]` | 能力矩阵总览，支持关键词过滤查询 |
| `route` | `python toolkit.py route "自然语言指令"` | 智能路由引擎，自动匹配Skill组合 |
| `quick` | `python toolkit.py quick <命令ID> [参数]` | 快捷命令执行（stock-diag/stock-pick/market-review/strategy-scan） |
| `health` | `python toolkit.py health` | 模块健康检查报告 |
| `guide` | `python toolkit.py guide <Skill名或问题>` | 使用指南生成器 |
| `help` | `python toolkit.py help` | 显示帮助信息 |

### 常用示例速查

```bash
# ── 总览 ───────────────────────────────
python toolkit.py overview                    # 查看所有15个Skills
python toolkit.py overview MACD               # 搜索MACD相关模块
python toolkit.py overview "情绪"             # 搜索情绪分析模块

# ── 智能路由 ───────────────────────────
python toolkit.py route "贵州茅台最新价"       # → nlp-analyzer(内置腾讯行情)
python toolkit.py route "帮我看看宁德时代怎么样" # → 多模块串联诊断
python toolkit.py route "找低估值高成长股票"   # → multi-factor条件过滤

# ── 快捷命令 ───────────────────────────
python toolkit.py quick stock-diag 600519     # 个股深度诊断
python toolkit.py quick stock-pick            # 选股推荐
python toolkit.py quick market-review         # 市场复盘
python toolkit.py quick strategy-scan         # 策略扫描

# ── 健康检查 ───────────────────────────
python toolkit.py health                      # 全面健康报告

# ── 使用指南 ───────────────────────────
python toolkit.py guide tech-indicators       # tech-indicators详细用法
python toolkit.py guide "我想做技术分析"       # 自动匹配+展示用法
```

---

## 七、推荐工作流

### 日常分析流程（完整版）

| 时段 | 操作 | 命令 |
|------|------|------|
| **开盘前** | 查看昨日情绪评分 → 判断板块轮动方向 → 搜索隔夜新闻 | `quick market-review` + `route "今日重要政策"` |
| **盘中(9:30-14:30)** | 监控龙虎榜异动 → 个股诊断 → 龙头战法选股 | `guide dragon-list` + `quick stock-diag <代码>` |
| **尾盘(14:30)** | 多因子筛选候选股 → 策略信号扫描 | `route "低估值高成长"` + `quick strategy-scan` |
| **收盘后** | 生成情绪日报 → 板块复盘 → 当日重要公告/研报 | `quick market-review` + `route "今日重要公告"` |

### 个股深度分析流程

```bash
# 一键启动完整诊断（推荐）
python toolkit.py quick stock-diag 600519

# 手动串联（更灵活）
python toolkit.py route "帮我全面分析贵州茅台"
# → nlp-analyzer(行情) + tech-indicators(技术指标)
#   + kline-patterns(K线形态) + multi-factor(基本面评分)
```

---

## 八、数据源与故障排除

### 数据源配置（全部免费公开接口，无需 API Key）

| 数据源 | 端点 | 用途 |
|--------|------|------|
| 腾讯行情 | `qt.gtimg.cn` / `ifzq.gtimg.cn` | 实时行情、前复权日K、名称检索 |
| 新浪板块 | `money.finance.sina.com.cn/q/view/newSinaHy.php` | 行业/概念板块行情 |
| 东财数据中心 | `datacenter-web.eastmoney.com/api/data/v1/get` | 估值、财务、龙虎榜等报表 |
| 东财涨跌停池 | `push2ex.eastmoney.com` | 涨停/跌停池家数 |
| pytdx通达信 | TCP直连 | 实时行情/分钟K线（毫秒级、无限制） |

- **Python依赖**: pandas, numpy, requests（部分模块另需 lightgbm/xgboost/scikit-learn）

### 常见故障处理

| 错误 | 处理方案 |
|------|---------|
| `RemoteDisconnected` | 行情源对高频请求偶发断连，模块内置退避重试；仍失败时切换备用源（腾讯↔新浪↔东财） |
| `Connection refused` | 检查网络能否访问对应公开端点 |
| 返回字段为 `-` 或空 | 非交易时段或部分字段源端不提供，属正常现象，勿用假数据兜底 |

### 调度链

- pytdx通达信（无限制、毫秒级）优先承担行情查询
- **多源调度链**: pytdx → 腾讯 → 新浪 → 东财数据中心
- 自然语言资讯类请求 → 引导至平台 AI 助手（本地无免费资讯源，不伪造内容）

---

## 九、常见问题 FAQ

### Q1: toolkit.py和nlp_analyzer.py有什么区别？

**A:** `toolkit.py`是统一入口导航工具，提供总览/路由/健康检查等管理功能；`nlp_analyzer.py`是NLP意图识别引擎，专注于自然语言对话分析和多模块自动串联。两者互补——toolkit适合管理和探索，nlp-analyzer适合日常对话式分析。

### Q2: 快捷命令执行时如何真正调用API？

**A:** `quick`命令默认会实际执行Python脚本并捕获输出。如果某个模块的数据源临时不可用，该步骤会报错跳过，其他模块（如本地计算的技术指标）仍可正常执行。

### Q3: 智能路由匹配不到怎么办？

**A:** 路由引擎有4层降级策略：条件过滤 → 复合规则 → 单模块匹配 → 全局关键词扫描。如果仍然无法匹配，建议使用`overview <关键词>`浏览所有可用Skills，或直接用`guide`查看具体用法。

### Q4: 如何添加新的分析模块到toolkit？

**A:** 在`SKILLS_METADATA`字典中添加新条目（包含name_cn/category/description/scenarios/script/keywords），并在对应分类的`CATEGORIES`中注册即可。路由规则可在`ROUTE_TABLE`中扩展。

### Q5: health检查报告保存在哪里？

**A:** JSON格式的详细报告保存于 `skills/a-share-analysis-toolkit/health_report.json`，包含所有Skills状态、API测试结果和依赖包版本信息。

### Q6: pytdx数据源怎么用？（v2.1新增）

**A:** `a-share-data-cache`模块已自动集成pytdx作为最高优先级备用源。调度器会自动优先使用pytdx获取行情/K线/分笔成交数据，无需手动配置。pytdx支持：
- 实时行情（无配额限制，毫秒级延迟~30ms）
- 日/周/月K线 + 5/15/30/60分钟K线
- Level-1逐笔委托和成交数据

### Q7: 为什么非交易时间pytdx返回空？（v2.1新增）

**A:** pytdx连接通达信公共服务器，非交易时段（收盘后/周末/节假日）服务器不推送实时行情数据。但历史K线数据仍可正常获取。系统会自动降级到AKShare/新浪等备用源。

---

## 注意事项

- 免费接口单次返回数据量大时建议缩小时间范围/TopN，避免上下文爆炸
- ML选股模块需要lightgbm/xgboost/scikit-learn（已安装）
- 免费接口虽无配额硬限制，但高频请求会被限流断连，模块均内置退避重试
- Python脚本中读取文件路径时不要用`$HOME`字符串字面量，应使用`os.path.expanduser('~')`或`pathlib.Path.home()`

---

## 已知问题与修复记录

### tech-indicators: calc_rsi() 参数兼容性（已修复）
```python
# ✅ 三种调用方式均正常：
rsi = calc_rsi(close)           # 默认 [6,12,24]
rsi = calc_rsi(close, 14)       # 单个int → {'RSI14': ...}
rsi = calc_rsi(close, [9])      # list[int] → {'RSI9': ...}
```
详见 `tech-indicators/SKILL.md` ⚠️已知问题与修复章节。

### kline-patterns: API需要DataFrame而非numpy数组
所有检测函数签名如 `detect_bullish_engulfing(df: DataFrame)`，不接受5个独立数组。
详见 `kline-patterns/SKILL.md` Python API使用章节。

### a-share-data-cache v2.0架构变更
已移除SQLite缓存层（pytdx 30ms直连+无限制使缓存价值消失），代码从65KB/1571行精简至29KB/742行。
详见 `a-share-data-cache/SKILL.md` v2.0变更说明章节。

---

## 注意事项（续）
## 构建记录

详见 `references/v2-build-session.md` — v2.0版本构建经验、依赖清单和常见错误码。  
详见 `references/api-quota-and-fallback.md` — API配额管理经验与降级策略。
详见 `references/v2-cache-removal-migration.md` — 缓存层移除迁移记录、兼容性修复清单和教训。
