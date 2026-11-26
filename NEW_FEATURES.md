# 新增功能模块说明

本文档说明A股智能分析平台新增的三个核心功能模块。

## 一、ML选股系统 V2（修复过拟合问题）

### 改进内容

1. **扩大训练数据量**
   - 股票数量：20只 → 100只（覆盖主要行业）
   - 数据天数：250天 → 500天
   - 样本量：5400 → 50000+

2. **修复交叉验证**
   - 使用时间序列分割（TimeSeriesSplit）
   - 添加早停机制防止过拟合
   - 改进CV计算，避免NaN结果

3. **增强正则化**
   - 降低学习率：0.05 → 0.03
   - 增加最小样本数：20 → 50
   - 增强L1/L2正则化：0.1 → 0.5

4. **特征选择**
   - 使用SelectKBest进行特征选择
   - 从50+特征筛选到20个关键特征
   - 减少过拟合风险

5. **改进标签生成**
   - 基于百分位数的分类标签
   - 避免类别不平衡问题
   - 默认预测天数：1天 → 5天

### 使用方法

```bash
# 训练模型
cd skills/ml-stock-picker
python ml_stock_picker_v2.py train --days 500 --stocks 100

# 预测选股
python ml_stock_picker_v2.py predict --top_n 30
```

### 输出文件

- `ml_output_v2/train_report_v2.json` - 训练报告
- `ml_output_v2/ml_v2_classifier.pkl` - 分类器模型
- `ml_output_v2/ml_v2_regressor.pkl` - 回归器模型
- `ml_output_v2/feature_names.json` - 特征名列表
- `ml_output_v2/prediction_v2_*.csv` - 预测结果

---

## 二、策略回测系统

### 功能特性

1. **内置策略**
   - MACD策略（金叉/死叉）
   - KDJ策略（超买/超卖）
   - RSI策略（超买/超卖）
   - 布林带策略（突破/回归）
   - 双均线策略（金叉/死叉）

2. **回测功能**
   - 支持自定义初始资金
   - 支持设置佣金费率
   - 支持设置滑点费率
   - 支持设置印花税率

3. **绩效指标**
   - 总收益率/年化收益率
   - 夏普比率/索提诺比率/卡玛比率
   - 最大回撤/回撤持续时间
   - 胜率/盈亏比
   - 月度收益统计

4. **报告生成**
   - JSON格式详细报告
   - 文本格式摘要报告
   - 权益曲线CSV
   - 策略对比报告

### 使用方法

```bash
# 回测单个策略
cd skills/strategy-backtest
python strategy_backtest.py backtest --stock 600519 --strategy macd --start 2023-01-01 --end 2024-01-01

# 对比多个策略
python strategy_backtest.py compare --stock 600519 --strategies "macd,kdj,rsi" --start 2023-01-01

# 列出可用策略
python strategy_backtest.py list
```

### 输出文件

- `backtest_output/backtest_report_*.json` - JSON报告
- `backtest_output/backtest_report_*.txt` - 文本报告
- `backtest_output/equity_curve_*.csv` - 权益曲线
- `backtest_output/strategy_comparison_*.json` - 策略对比

---

## 三、智能预警系统

### 预警类型

1. **技术指标类**
   - MACD金叉/死叉
   - KDJ超买/超卖
   - RSI超买/超卖

2. **量价异动类**
   - 放量突破
   - 大幅下跌

3. **风险类**
   - 止损预警（从高点回撤8%）
   - 高波动预警（年化波动率>300%）

### 预警级别

- `INFO` - 信息（蓝色）
- `WARNING` - 警告（黄色）
- `CRITICAL` - 严重（红色）
- `EMERGENCY` - 紧急（紫色）

### 使用方法

```bash
# 监控单只股票
cd skills/smart-alert
python smart_alert.py monitor --stock 600519

# 监控股票池
python smart_alert.py monitor --pool "600519,300750,002594"

# 使用指定规则
python smart_alert.py monitor --stock 600519 --rules "macd_golden_cross,kdj_oversold"

# 持续监控
python smart_alert.py continuous --pool "600519,300750" --duration 60 --interval 60

# 列出可用规则
python smart_alert.py list
```

### 输出

- 控制台实时预警
- 日志文件：`alerts/alerts_YYYYMMDD.json`

---

## 四、依赖安装

```bash
pip install lightgbm xgboost scikit-learn pandas numpy requests
```

---

## 五、集成到现有系统

### 后端API集成

可以在 `backend/app/api/` 下创建新的路由文件：

```python
# backend/app/api/ml_v2.py
from fastapi import APIRouter
from skills.ml-stock-picker.ml_stock_picker_v2 import MLStockPickerV2

router = APIRouter(prefix="/api/ml-v2", tags=["ML选股V2"])

@router.post("/train")
async def train_model(days: int = 500, stocks: int = 100):
    picker = MLStockPickerV2()
    result = picker.train(days=days, stock_count=stocks)
    return result

@router.post("/predict")
async def predict_stocks(top_n: int = 30):
    picker = MLStockPickerV2()
    result = picker.predict(top_n=top_n)
    return result
```

```python
# backend/app/api/backtest.py
from fastapi import APIRouter
from skills.strategy-backtest.strategy_backtest import StrategyBacktester

router = APIRouter(prefix="/api/backtest", tags=["策略回测"])

@router.post("/run")
async def run_backtest(stock: str, strategy: str, start: str, end: str):
    backtester = StrategyBacktester()
    result = backtester.backtest(stock, strategy, start, end)
    return result
```

```python
# backend/app/api/alerts.py
from fastapi import APIRouter
from skills.smart-alert.smart_alert import SmartAlertSystem

router = APIRouter(prefix="/api/alerts", tags=["智能预警"])

@router.post("/monitor")
async def monitor_stock(stock: str):
    system = SmartAlertSystem()
    alerts = system.monitor_stock(stock)
    return alerts
```

---

## 六、注意事项

1. **ML选股系统**
   - 首次训练需要较长时间（约10-30分钟）
   - 建议定期重新训练（每周或每月）
   - 不要过度依赖单一模型

2. **策略回测**
   - 历史回测不代表未来收益
   - 需要考虑交易成本和滑点
   - 建议进行样本外测试

3. **智能预警**
   - 预警仅供参考，不构成投资建议
   - 需要结合其他分析方法
   - 注意控制风险

---

## 七、免责声明

⚠️ **本平台所有功能仅供学习和研究使用，不构成任何投资建议。**

股市有风险，投资需谨慎。使用者应自行承担投资风险。
