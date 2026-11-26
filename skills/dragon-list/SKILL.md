---
name: dragon-list
description: A股龙虎榜数据分析工具——获取当日/历史龙虎榜数据，解析游资席位与机构动向，提供4种龙虎榜选股策略（机构净买入TOP10、游资合力板、机构+游资共振、溢价策略），内置50+知名游资营业部映射数据库。
---

# A股龙虎榜分析工具

## 概述

基于东方财富公开行情接口（数据中心龙虎榜报表，免费且无需 API Key）的龙虎榜全链路分析系统，支持：
- **当日/历史龙虎榜**数据获取与解析
- **游资席位识别**（内置50+知名游资营业部映射）
- **机构vs游资力量对比**分析
- **4种选股策略**自动化执行
- **历史回查与统计**功能

## 核心功能

### 1. 龙虎榜数据获取

```bash
# 今日龙虎榜全览
python dragon_list.py today

# 指定日期历史回查
python dragon_list.py history --date 2026-06-23

# 个股龙虎榜明细
python dragon_list.py stock --code 600519
```

### 2. 席位分析

```bash
# 查询知名游资席位历史操作
python dragon_list.py seat --name "章盟主"

# 查看机构席位净买入排名
python dragon_list.py today --institution
```

### 3. 选股策略

```bash
# 执行全部4种策略
python dragon_list.py strategy

# 仅执行指定策略
python dragon_list.py strategy --type institution   # 机构净买入TOP10
python dragon_list.py strategy --type synergy        # 游资合力板
python dragon_list.py strategy --type resonance      # 机构+游资共振
python dragon_list.py strategy --type premium        # 溢价策略
```

### 4. 统计分析

```bash
# 龙虎榜时间序列统计（近N日上榜家数趋势）
python dragon_list.py stats --days 30

# 不同上榜原因的次日表现对比
python dragon_list.py stats --reason-compare
```

## CLI参数完整说明

| 子命令 | 参数 | 说明 |
|--------|------|------|
| `today` | `--institution` | 今日龙虎榜，可选仅显示机构席位 |
| `history` | `--date YYYY-MM-DD` | 指定日期历史龙虎榜回查 |
| `stock` | `--code 股票代码/名称` | 个股龙虎榜明细查询 |
| `seat` | `--name 游资名称` | 知名游资席位操作记录 |
| `strategy` | `--type institution/synergy/resonance/premium/all` | 选股策略执行 |
| `stats` | `--days N` | 近N日龙虎榜统计趋势 |
| `stats` | `--reason-compare` | 上榜原因次日表现对比 |

## 游资席位数据库（50+知名游资）

内置映射表覆盖以下知名游资营业部：

| 游资名称 | 代表营业部 | 操作风格 |
|----------|-----------|----------|
| 章盟主 | 国泰君安证券上海江苏路 | 趋势流/大资金 |
| 作手新一 | 华鑫证券上海分公司 | 打板流/接力 |
| 方新侠 | 中国银河证券上海嘉定 | 低吸流/趋势 |
| 小鳄鱼 | 华泰证券深圳益田路 | 打板流/快进快出 |
| 炒股养家 | 华泰证券杭州解放东路 | 情绪流/龙头战法 |
| 赵老哥 | 中国银河证券绍兴 | 接力流/连板 |
| 徐翔系 | 东财拉萨团结路/东环路 | 趋势+打板 |
| ... | ... | ... |

## 选股策略方法论

### 机构净买入TOP10
- **逻辑**：机构席位大举买入，通常意味着基本面认可或重大利好预期
- **适用环境**：震荡市、价值回归行情
- **胜率参考**：次日高开概率约55%-60%

### 游资合力板
- **逻辑**：3个以上知名游资同时买入同一标的，形成资金共振
- **适用环境**：题材炒作期、情绪上升阶段
- **胜率参考**：次日溢价率平均2%-4%

### 机构+游资共振
- **逻辑**：机构和游资同时大幅买入，基本面+情绪面双重驱动
- **适用环境**：主升浪初期、板块启动阶段
- **胜率参考**：5日收益率中位数约8%-12%

### 溢价策略
- **逻辑**：基于历史统计，筛选次日高开概率最高的上榜类型
- **适用环境**：短线隔日交易
- **胜率参考**：精选标的次日高开概率>65%

## Python API使用

```python
from dragon_list import DragonListAnalyzer, SeatDatabase

# 初始化分析器
analyzer = DragonListAnalyzer()

# 获取今日龙虎榜
data = analyzer.fetch_today()

# 查询游资席位信息
seats = SeatDatabase().search("章盟主")

# 执行选股策略
results = analyzer.run_strategy("institution")
```

## 输出格式

终端彩色表格 + JSON文件自动保存到 `dragon_list_output/`：
- `today_YYYYMMDD.json` — 今日龙虎榜全量数据
- `strategy_YYYYMMDD.json` — 选股策略结果
- `stats_YYYYMMDD.json` — 统计分析结果

## 依赖

pandas, numpy, requests（均已安装）
