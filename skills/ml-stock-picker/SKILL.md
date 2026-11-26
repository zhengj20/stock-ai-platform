---
name: ml-stock-picker
display_name: A股机器学习选股 (ML Stock Picker)
title: ML-Powered Stock Selection for A-Shares
description: 基于LightGBM/XGBoost的A股量化选股模型，融合技术指标、量价特征、基本面因子和市场情绪。
homepage: ""
author: Hermes Agent
version: 1.0.0
dependencies:
  - pandas
  - numpy
  - lightgbm
  - xgboost
  - scikit-learn
---

# A股机器学习选股 (ML Stock Picker)

本 Skill 提供一套完整的 **A股机器学习量化选股系统**，基于 LightGBM/XGBoost 模型，融合技术指标、量价特征、基本面因子和市场情绪四大维度，实现智能化的股票筛选与预测。

## ML选股方法论

### 核心思路

传统多因子选股采用线性加权合成，而ML选股通过非线性模型自动学习因子间的复杂交互关系：

```
原始数据 → 特征工程(50+特征) → 标签生成 → 模型训练(LightGBM/XGBoost) → 全市场打分排序 → TOP30选股
```

### 为什么用LightGBM？

| 特性 | LightGBM | XGBoost |
|------|----------|---------|
| 训练速度 | ⚡ 极快（直方图算法） | 较快 |
| 内存占用 | 📦 低 | 中等 |
| 分类任务精度 | ✅ 优秀 | ✅ 优秀 |
| 特征重要性 | ✅ 内置 | ✅ 内置 |
| 推荐场景 | **默认首选** | 备选/对比验证 |

### 训练流程

```
1. 数据获取（免费公开接口，无需API Key）
   ├── 历史行情数据（腾讯前复权日K线：开高低收、成交量）
   ├── 财务指标数据（东方财富估值明细 + F10财务：PE/PB/ROE/毛利率等）
   └── 市场情绪数据（东方财富涨停池/跌停池家数）

2. 特征工程 (50+特征)
   ├── 技术指标特征：MACD/KDJ/RSI/BOLL及变化率、均线偏离度
   ├── 量价特征：成交量变化率、换手率分位、振幅、量比
   ├── 基本面特征：PE/PB/PS、ROE、毛利率、营收增速（东财免费接口直取）
   ├── 市场情绪特征：涨停跌停比、综合情绪评分
   └── 时间特征：星期几、月份、是否财报季

3. 标签生成
   ├── N日收益率标签（1日/5日/10日后收益率，回归任务）
   ├── 三分类标签（涨>3%为1，跌<-3%为-1，中间为0，分类任务）
   └── 分位数排名标签（当日涨幅百分位，排序任务）

4. 模型训练
   ├── LightGBM分类器 → 预测涨跌方向
   ├── LightGBM回归器 → 预测收益率
   ├── XGBoost备选模型
   ├── 交叉验证 + 超参数调优
   └── 特征重要性分析（Top20因子排名）

5. 选股执行
   ├── 加载训练好的模型
   ├── 对全市场股票打分排序
   ├── 输出预测得分TOP30
   └── 支持过滤条件（市值范围、ST排除、行业限制）

6. 模型评估
   ├── 准确率/精确率/召回率/F1分数
   ├── IC/IR（信息系数/信息比率）
   ├── 分组回测收益（按预测得分分5组）
   └── 累计收益曲线数据
```

## 特征体系详解

### 一、技术指标特征 (Technical Indicators)

| # | 特征名 | 计算方式 | 说明 |
|---|--------|---------|------|
| 1 | MACD_DIF | DIF = EMA(12) - EMA(26) | MACD快慢线差值 |
| 2 | MACD_DEA | DEA = EMA(DIF, 9) | MACD信号线 |
| 3 | MACD_HIST | HIST = 2*(DIF-DEA) | MACD柱状图 |
| 4 | MACD_DIF_CHG | DIF变化率(5日) | MACD趋势变化速度 |
| 5 | KDJ_K | K值 (9日周期) | KDJ随机指标K线 |
| 6 | KDJ_D | D值 (3日平滑) | KDJ随机指标D线 |
| 7 | KDJ_J | J = 3K - 2D | KDJ超买超卖信号 |
| 8 | RSI_6 | 6日RSI | 短期相对强弱指数 |
| 9 | RSI_14 | 14日RSI | 中期相对强弱指数 |
| 10 | BOLL_UPPER | MA(20) + 2*STD(20) | 布林带上轨 |
| 11 | BOLL_LOWER | MA(20) - 2*STD(20) | 布林带下轨 |
| 12 | BOLL_PCT | (Close-LOWER)/(UPPER-LOWER) | 布林带位置百分比 |
| 13 | MA5_DEVIATION | (Close-MA5)/MA5 | 5日均线偏离度 |
| 14 | MA10_DEVIATION | (Close-MA10)/MA10 | 10日均线偏离度 |
| 15 | MA20_DEVIATION | (Close-MA20)/MA20 | 20日均线偏离度 |

### 二、量价特征 (Volume-Price Features)

| # | 特征名 | 计算方式 | 说明 |
|---|--------|---------|------|
| 16 | VOL_CHANGE_5D | 近5日成交量变化率 | 量能趋势 |
| 17 | TURNOVER_PCTILE | 换手率在20日内的分位数 | 交易活跃度相对位置 |
| 18 | AMPLITUDE | (High-Low)/Close*100 | 日内振幅 |
| 19 | VOL_RATIO | 今日量比(成交量/5日均量) | 量能异常程度 |
| 20 | PRICE_CHANGE_1D | 日涨跌幅 | 单日价格变化 |
| 21 | PRICE_CHANGE_5D | 5日累计涨幅 | 短期动量 |

### 三、基本面特征 (Fundamental Factors)

复用 multi-factor 模块的27个因子，核心包括：

| # | 特征名 | 说明 |
|---|--------|------|
| 22 | PE_TTM | 市盈率（滚动） |
| 23 | PB | 市净率 |
| 24 | PS_TTM | 市销率 |
| 25 | ROE | 净资产收益率 |
| 26 | ROA | 总资产收益率 |
| 27 | GROSS_MARGIN | 毛利率 |
| 28 | NET_MARGIN | 净利率 |
| 29 | DEBT_RATIO | 资产负债率 |
| 30 | REVENUE_GROWTH | 营收同比增长率 |
| 31 | PROFIT_GROWTH | 净利润同比增长率 |

### 四、市场情绪特征 (Market Sentiment)

复用 market-sentiment 模块：

| # | 特征名 | 说明 |
|---|--------|------|
| 32 | LIMIT_UP_DOWN_RATIO | 涨停/跌停比 |
| 33 | ADVANCE_DECLINE_RATIO | 上涨/下跌家数比 |
| 34 | SENTIMENT_SCORE | 综合情绪评分(0-100) |

### 五、时间特征 (Time Features)

| # | 特征名 | 说明 |
|---|--------|------|
| 35 | DAY_OF_WEEK | 星期几(0=周一, 4=周五) |
| 36 | MONTH | 月份(1-12) |
| 37 | IS_EARNINGS_SEASON | 是否财报季(4月/8月/10月=1) |

## 标签体系

### N日收益率标签（回归任务）

```python
# 预测未来N日的累计收益率
label_return_1d = (close[t+1] - close[t]) / close[t]    # 1日后收益率
label_return_5d = (close[t+5] - close[t]) / close[t]    # 5日后收益率
label_return_10d = (close[t+10] - close[t]) / close[t]  # 10日后收益率
```

### 三分类标签（分类任务）

```python
# 涨跌方向三分类
if future_return > 3%:    label = 1   # 大涨
elif future_return < -3%: label = -1  # 大跌
else:                     label = 0   # 震荡
```

### 分位数排名标签（排序任务）

```python
# 当日涨幅在全部股票中的百分位排名
label_rank = percentile_rank(stock_return, all_stocks_returns)
```

## 使用方法

### 安装依赖

```bash
pip install lightgbm xgboost scikit-learn pandas numpy
```

数据源均为免费公开接口，无需配置任何 API Key。

### CLI使用方式

#### 1. 训练模型

```bash
# 基本训练（默认250个交易日历史数据）
python ml_stock_picker.py train --days 250

# 指定股票池和标签类型
python ml_stock_picker.py train \
    --days 250 \
    --stocks "贵州茅台,宁德时代,比亚迪,东方财富,招商银行" \
    --label-type classification \
    --model lightgbm

# 使用回归模型（预测收益率）
python ml_stock_picker.py train \
    --days 300 \
    --label-type regression \
    --return-days 5 \
    --tune-hyperparams

# XGBoost备选模型
python ml_stock_picker.py train \
    --model xgboost \
    --cv-folds 5
```

#### 2. 预测选股

```bash
# 基本预测（加载最新训练好的模型）
python ml_stock_picker.py predict

# 指定过滤条件
python ml_stock_picker.py predict \
    --top_n 30 \
    --exclude_st \
    --min_cap 50 \
    --max_cap 2000

# 对比ML选股与多因子选股结果
python ml_stock_picker.py predict --compare-multi-factor
```

### CLI参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `train` / `predict` | subcommand | - | 训练/预测模式 |
| `--days` | int | 250 | 训练数据天数 |
| `--stocks` | str | - | 股票池（逗号分隔），不指定则用默认沪深300成分股 |
| `--label-type` | str | classification | classification/regression/ranking |
| `--return-days` | int | 1 | N日收益率标签的N值 |
| `--model` | str | lightgbm | lightgbm/xgboost |
| `--cv-folds` | int | 5 | 交叉验证折数 |
| `--tune-hyperparams` | flag | False | 启用超参数调优（RandomSearch） |
| `--top_n` | int | 30 | 输出前N只股票 |
| `--exclude_st` | flag | True | 排除ST股票 |
| `--min_cap` | float | - | 最小市值（亿元） |
| `--max_cap` | float | - | 最大市值（亿元） |
| `--compare-multi-factor` | flag | False | 对比ML与多因子选股结果 |
| `--output_dir` | str | ./ml_output/ | 输出目录 |

### Python API调用

```python
from ml_stock_picker import MLStockPicker

# 初始化
picker = MLStockPicker()

# 训练模型
train_result = picker.train(
    days=250,
    stock_names=["贵州茅台", "宁德时代", "比亚迪"],
    label_type="classification",
    model_name="lightgbm",
    tune_hyperparams=True
)

# 预测选股
predict_result = picker.predict(
    top_n=30,
    exclude_st=True,
    min_market_cap=50
)

print(predict_result["top_stocks"])
```

## 输出说明

### 训练输出

| 文件 | 格式 | 说明 |
|------|------|------|
| `model_classifier.pkl` | pickle | LightGBM分类器模型 |
| `model_regressor.pkl` | pickle | LightGBM回归器模型 |
| `feature_importance.json` | JSON | Top20特征重要性排名 |
| `train_report.json` | JSON | 训练报告（含评估指标） |

### 预测输出

| 文件 | 格式 | 说明 |
|------|------|------|
| `prediction_YYYYMMDD.csv` | CSV | TOP30选股列表及得分 |
| `prediction_YYYYMMDD.json` | JSON | 完整预测结果（含过滤信息） |

### 特征重要性JSON示例

```json
{
  "model": "lightgbm_classifier",
  "top_features": [
    {"rank": 1, "feature": "ROE", "importance": 0.152},
    {"rank": 2, "feature": "PE_TTM", "importance": 0.128},
    ...
  ]
}
```

## 模型评估指标

| 指标 | 说明 | 优秀阈值 |
|------|------|---------|
| **准确率 (Accuracy)** | 预测正确的比例 | >60% |
| **精确率 (Precision)** | 预测为涨中实际上涨的比例 | >55% |
| **召回率 (Recall)** | 实际上涨中被正确预测的比例 | >50% |
| **F1分数** | 精确率和召回率的调和平均 | >52% |
| **IC (信息系数)** | 预测值与实际收益的Spearman相关系数 | >0.03 |
| **IR (信息比率)** | IC均值 / IC标准差 | >0.5 |

## 注意事项

1. **接口限流**：免费公开接口对高频请求会限流，脚本已内置退避重试与腾讯多入口切换，批量训练时建议控制股票池规模
2. **数据质量**：财务指标可能因财报未披露而缺失，框架会自动处理缺失值（填充中位数）
3. **过拟合风险**：ML模型容易过拟合历史数据，建议使用交叉验证和正则化
4. **回测验证**：生产环境使用前务必进行样本外回测验证
5. **市场风格切换**：不同市场环境下因子有效性会变化，建议定期重新训练模型（每月/每季度）

## 文件结构

```
ml-stock-picker/
├── SKILL.md            # 本说明文档
└── ml_stock_picker.py  # 主脚本（特征工程+标签生成+模型训练+选股执行+评估）
```
