# A股可视化图表引擎 (a-share-visualization)

基于 matplotlib + plotly 的K线图+技术指标叠加图生成与导出工具。支持静态PNG高清导出、交互式HTML图表、终端ASCII预览以及批量图表生成。

## 功能概览

| 模块 | 说明 |
|------|------|
| K线图绘制引擎 | 标准蜡烛图（红涨绿跌）+ 成交量柱状图，自动标注前高/前低/支撑/阻力位 |
| 技术指标叠加层 | MACD子图、KDJ/RSI子图（可选切换）、BOLL布林带主图叠加、MA5/10/20/60均线系统 |
| K线形态标注 | 调用kline-patterns模块结果，在图上标记形态名称+置信度标签+箭头指向 |
| 多子图布局管理 | 主图(K线+成交量) + MACD副图 + KDJ或RSI副图，自动调整比例和间距 |
| PNG高清导出 | matplotlib渲染，300 DPI，适合报告引用 |
| HTML交互式图表 | plotly.js输出，支持缩放/十字光标/悬浮提示/图例切换 |
| 终端ASCII预览 | 轻量级字符K线图，无需图形界面即可快速查看走势 |
| 批量生成 | 多股对比图（归一化价格走势）、K线矩阵（网格布局）、多因子雷达图 |

## 依赖环境

```bash
pip install matplotlib plotly mplfinance pandas numpy
```

已安装版本：matplotlib 3.11.0, plotly 6.8.0, mplfinance 0.12.10b0

## 快速开始

### 单股K线图（PNG静态图）

```bash
cd skills/a-share-visualization
python visualization.py 600519 --output chart.png
```

### 交互式HTML图表

```bash
# 生成HTML并自动打开浏览器
python visualization.py 600519 --html output.html --open-browser

# 仅生成HTML文件（不打开）
python visualization.py 000001 --H report.html
```

### 终端ASCII预览（无需图形界面）

```bash
python visualization.py 600519 --ascii
```

### 自定义指标显示

```bash
# 显示RSI替代KDJ
python visualization.py 600519 --rsi --no-kdj --output rsi_chart.png

# 隐藏MACD和布林带
python visualization.py 000001 --no-macd --no-boll --output simple.png

# 只显示均线，不显示其他指标
python visualization.py 600519 --no-macd --no-kdj --no-boll --output ma_only.png
```

### 批量生成 - 多股对比图（归一化价格走势）

```bash
python visualization.py batch \
    --symbols 600519,000001,601318,000858 \
    --mode compare \
    --output comparison.png
```

### 批量生成 - K线矩阵（板块成分股网格布局）

```bash
python visualization.py batch \
    --symbols 600519,000001,601318,000858,600036,600276 \
    --mode matrix \
    --output matrix.png
```

### 多因子雷达图

```bash
# 准备因子得分JSON文件 factors.json:
# {"PE_TTM": 0.85, "PB": 0.72, "ROE": 0.91, "营收增速": 0.65, "净利润增速": 0.78}

python visualization.py radar \
    --factors-file factors.json \
    --output radar.png \
    --title "贵州茅台多因子评分"
```

## CLI参数详解

### 主命令参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `symbol` | A股股票代码或名称（6位数字） | - |
| `--periods, -p` | K线周期数（交易日） | 250 |
| `--output, -o` | PNG输出路径 | auto: output/{symbol}_{timestamp}.png |
| `--html, -H` | HTML交互式图表输出路径 | auto: output/{symbol}_{timestamp}.html |
| `--open-browser` | 生成HTML后自动打开浏览器 | False |
| `--dpi` | PNG导出分辨率 | 300 |
| `--ascii, -a` | 终端内显示ASCII简化版K线图 | False |

### 指标开关参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--no-macd` | 隐藏MACD子图 | 显示 |
| `--kdj` | 显式启用KDJ子图 | 默认开启 |
| `--no-kdj` | 隐藏KDJ子图 | - |
| `--rsi` | 显示RSI子图（替代KDJ） | 关闭 |
| `--no-boll` | 隐藏布林带通道 | 显示 |
| `--no-ma` | 隐藏均线系统(MA5/10/20/60) | 显示 |

### batch子命令参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--symbols, -s` | 逗号分隔的股票代码列表 | 必填 |
| `--mode, -m` | compare=对比图, matrix=K线矩阵 | compare |
| `--output, -o` | 输出文件路径（.png） | 必填 |
| `--periods, -p` | K线周期数 | 250 |

### radar子命令参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--factors-file, -f` | JSON格式的因子得分文件路径 | 必填 |
| `--output, -o` | 输出PNG路径 | 必填 |
| `--title, -t` | 图表标题 | "多因子得分雷达图" |

## Python API使用

```python
from visualization import (
    fetch_kline_data,
    compute_all_indicators,
    detect_patterns,
    find_key_price_levels,
    plot_candlestick_matplotlib,
    plot_candlestick_plotly,
    generate_comparison_chart,
    generate_stock_matrix,
    generate_radar_chart,
    ascii_kline,
)

# 1. 获取K线数据（通过SmartDispatcher自动调度）
df = fetch_kline_data("600519", periods=250)

# 2. 计算技术指标
indicators = compute_all_indicators(df)
# indicators["MA"] -> {"MA5": Series, "MA10": Series, ...}
# indicators["MACD"] -> {"DIF": Series, "DEA": Series, "MACD_Hist": Series}
# indicators["KDJ"] -> {"K": Series, "D": Series, "J": Series}
# indicators["RSI"] -> {"RSI6": Series, "RSI12": Series, "RSI24": Series}
# indicators["BOLL"] -> {"BOLL_UPPER": Series, "BOLL_MID": Series, "BOLL_LOWER": Series}

# 3. 检测K线形态（调用kline-patterns模块）
patterns = detect_patterns(df, min_confidence=0.5)

# 4. 识别重要价格位
key_levels = find_key_price_levels(df)
# key_levels["previous_high"] -> float
# key_levels["support_levels"] -> [float, ...]
# key_levels["resistance_levels"] -> [float, ...]

# 5. 生成PNG静态图（matplotlib）
fig = plot_candlestick_matplotlib(
    df, indicators=indicators, patterns=patterns, key_levels=key_levels,
    show_macd=True, show_kdj=False, show_rsi=True,
    output_path="chart.png", dpi=300
)

# 6. 生成HTML交互式图（plotly）
fig = plot_candlestick_plotly(
    df, indicators=indicators, patterns=patterns, key_levels=key_levels,
    show_macd=True, show_kdj=True,
    output_path="chart.html", open_browser=True
)

# 7. ASCII终端预览
print(ascii_kline(df, width=80, height=20))

# 8. 批量对比图
generate_comparison_chart(["600519", "000001"], output_path="compare.png")

# 9. K线矩阵
generate_stock_matrix(["600519", "000001", "601318"], output_path="matrix.png")

# 10. 多因子雷达图
factors = {"PE_TTM": 0.85, "PB": 0.72, "ROE": 0.91}
generate_radar_chart(factors, title="选股评分", output_path="radar.png")
```

## 图表布局说明

### 默认子图布局（3行）

```
┌─────────────────────────────────────┐
│         K线图 + MA均线              │
│   ┌───────────────────────────┐     │
│   │ 蜡烛图(红涨绿跌)          │     │
│   │ BOLL布林带通道            │     │
│   │ MA5/10/20/60均线         │     │
│   │ K线形态标注(箭头+标签)    │     │
│   │ 前高/前低/支撑/阻力位     │     │
│   └───────────────────────────┘     │
│   [成交量柱状图 - 底部对齐]         │
├─────────────────────────────────────┤
│           MACD                      │
│   DIF曲线 / DEA曲线 / 柱状图        │
├─────────────────────────────────────┤
│          KDJ (或RSI)                │
│   K/D/J三线 + 超买/超卖区域         │
│   RSI: 70/30阈值线                  │
└─────────────────────────────────────┘
```

### 颜色方案

| 元素 | 颜色 | 说明 |
|------|------|------|
| 阳线（涨） | #e74c3c (红) | A股惯例：红色=上涨 |
| 阴线（跌） | #2ecc71 (绿) | A股惯例：绿色=下跌 |
| MA5 | #f39c12 (橙黄) | 短期均线 |
| MA10 | #3498db (蓝) | 中期均线 |
| MA20 | #9b59b6 (紫) | 月线 |
| MA60 | #e67e22 (深橙) | 季线 |
| BOLL通道 | #3498db (浅蓝) | 布林带 |
| MACD柱(正) | #e74c3c (红) | 多头动能 |
| MACD柱(负) | #2ecc71 (绿) | 空头动能 |

## 数据源说明

K线数据通过 `a-share-data-cache/data_cache.py` 的 SmartDispatcher 获取，自动走四级调度（v2.0无缓存版）：
1. **pytdx通达信** → TCP直连~30ms，无限制 ⭐首选
2. **AKShare** → 东方财富数据源，无限制
3. **新浪财经** → HTTP备用实时行情
4. **腾讯财经** → HTTP备用K线/板块数据

## 文件结构

```
a-share-visualization/
├── SKILL.md              # 本说明文档
├── visualization.py      # 主程序 (~1400行)
│   ├── _setup_chinese_font()     # 中文字体自动配置
│   ├── fetch_kline_data()        # K线数据获取（SmartDispatcher）
│   ├── compute_all_indicators()  # 技术指标计算（复用tech-indicators）
│   ├── detect_patterns()         # K线形态识别（复用kline-patterns）
│   ├── find_key_price_levels()   # 重要价格位标注
│   ├── plot_candlestick_matplotlib()  # matplotlib静态图引擎
│   ├── plot_candlestick_plotly()      # plotly交互式图表引擎
│   ├── generate_comparison_chart()    # 多股对比图
│   ├── generate_stock_matrix()        # K线矩阵（网格布局）
│   ├── generate_radar_chart()         # 多因子雷达图
│   └── ascii_kline()                  # 终端ASCII简化版
└── output/               # 自动创建的输出目录
    └── {symbol}_{timestamp}.png/.html
```

## 注意事项

1. **中文字体**：自动检测 SimHei → Microsoft YaHei → PingFang SC → WenQuanYi Micro Hei，未找到则回退到任意CJK字体
2. **输出目录**：首次运行会自动创建 `output/` 子目录
3. **数据依赖**：需要 `a-share-data-cache`、`tech-indicators`、`kline-patterns` 三个Skill模块在同一skills目录下
4. **内存占用**：批量生成矩阵图时，每只股票独立获取数据，大量股票可能耗时较长
