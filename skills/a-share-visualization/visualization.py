#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股可视化图表引擎 (a-share-visualization)
==========================================
基于 matplotlib + plotly 的K线图+技术指标叠加图生成与导出工具。

核心功能：
1. K线图绘制引擎（蜡烛图+成交量）
2. 技术指标叠加层（MACD/KDJ/RSI/BOLL/MA）
3. K线形态标注（调用kline-patterns模块结果）
4. 多子图布局管理
5. PNG高清导出 + HTML交互式图表
6. 批量图表生成（对比图/矩阵/雷达图）

用法:
    python visualization.py <股票代码> [选项]
    python visualization.py batch --symbols 600519,000001,601318 [--mode matrix|compare|radar]
"""

import os
import sys
import json
import argparse
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

# ── 配置中文字体 ────────────────────────────────────────
def _setup_chinese_font():
    """自动检测并配置中文字体"""
    import matplotlib
    import matplotlib.pyplot as plt

    # Windows 常见中文字体优先级
    candidate_fonts = [
        "SimHei",           # 黑体（Windows）
        "Microsoft YaHei",  # 微软雅黑
        "PingFang SC",      # macOS
        "WenQuanYi Micro Hei",  # Linux
        "Noto Sans CJK SC",
    ]

    font_found = False
    for font_name in candidate_fonts:
        try:
            plt.rcParams["font.sans-serif"] = [font_name] + plt.rcParams.get("font.sans-serif", [])
            matplotlib.font_manager.FontProperties(fname=matplotlib.font_manager.findfont(font_name))
            font_found = True
            print(f"  ✅ 使用中文字体: {font_name}")
            break
        except Exception:
            continue

    if not font_found:
        # Fallback: try any available CJK font
        all_fonts = [f.name for f in matplotlib.font_manager.fontManager.ttflist]
        cjk_fonts = [f for f in all_fonts if any(kw in f.lower() for kw in ["hei", "song", "kai", "yahei", "noto", "cjk"])]
        if cjk_fonts:
            plt.rcParams["font.sans-serif"] = [cjk_fonts[0]] + plt.rcParams.get("font.sans-serif", [])
            print(f"  ✅ 使用回退中文字体: {cjk_fonts[0]}")
        else:
            print("  ⚠️ 未找到中文字体，图表中文可能显示为方块")

    plt.rcParams["axes.unicode_minus"] = False  # 正常显示负号
    return plt


# ═══════════════════════════════════════════════════════
# 数据获取层（通过 data_cache.py SmartDispatcher）
# ═══════════════════════════════════════════════════════

def _import_dispatcher():
    """导入 SmartDispatcher"""
    skills_dir = Path(__file__).parent.parent
    cache_script = skills_dir / "a-share-data-cache" / "data_cache.py"
    if cache_script.exists():
        sys.path.insert(0, str(cache_script.parent))
        from data_cache import SmartDispatcher
        return SmartDispatcher()
    else:
        raise RuntimeError("未找到 a-share-data-cache/data_cache.py")


def _import_indicators():
    """导入技术指标计算函数"""
    skills_dir = Path(__file__).parent.parent
    indicator_script = skills_dir / "tech-indicators" / "tech_indicators.py"
    if indicator_script.exists():
        sys.path.insert(0, str(indicator_script.parent))
        import tech_indicators as ti
        return ti
    else:
        raise RuntimeError("未找到 tech-indicators/tech_indicators.py")


def _import_patterns():
    """导入K线形态识别函数"""
    skills_dir = Path(__file__).parent.parent
    pattern_script = skills_dir / "kline-patterns" / "kline_patterns.py"
    if pattern_script.exists():
        sys.path.insert(0, str(pattern_script.parent))
        import kline_patterns as kp
        return kp
    else:
        raise RuntimeError("未找到 kline-patterns/kline_patterns.py")


def fetch_kline_data(symbol: str, periods: int = 250) -> pd.DataFrame:
    """
    通过 SmartDispatcher 获取K线数据，返回标准DataFrame。

    Parameters
    ----------
    symbol : str
        股票代码或名称
    periods : int
        获取最近N根K线（默认250个交易日≈1年）

    Returns
    -------
    pd.DataFrame with columns: date, open, high, low, close, volume
    """
    dispatcher = _import_dispatcher()
    result = dispatcher.dispatch_kline(symbol)

    if not result.get("data"):
        raise RuntimeError(f"无法获取 {symbol} 的K线数据")

    df = pd.DataFrame(result["data"])

    # ── 列名标准化 ────────────────────────────────
    col_map: Dict[str, str] = {}
    for col in df.columns:
        cl = col.lower()
        if "日期" in cl or "date" in cl or "时间" in cl:
            col_map[col] = "date"
        elif "开盘" in cl or cl.startswith("open"):
            col_map[col] = "open"
        elif "最高" in cl or cl.startswith("high"):
            col_map[col] = "high"
        elif "最低" in cl or cl.startswith("low"):
            col_map[col] = "low"
        elif "收盘" in cl or cl.startswith("close") or "最新价" in cl:
            col_map[col] = "close"
        elif "成交量" in cl or "volume" in cl or cl == "量":
            col_map[col] = "volume"

    df.rename(columns=col_map, inplace=True)

    required = ["date", "open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise RuntimeError(f"缺少必要列 {missing}，可用列: {list(df.columns)}")

    # 类型转换
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df.columns:
        df["volume"] = 0
    else:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)

    df.dropna(subset=["close"], inplace=True)
    df.sort_values("date", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # 取最近periods根K线
    if len(df) > periods:
        df = df.iloc[-periods:]
        df.reset_index(drop=True, inplace=True)

    return df


# ═══════════════════════════════════════════════════════
# 技术指标计算（复用 tech_indicators.py）
# ═══════════════════════════════════════════════════════

def compute_all_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算所有技术指标，返回包含各指标Series的字典。

    Returns
    -------
    dict with keys: MA, MACD, KDJ, RSI, BOLL
    """
    ti = _import_indicators()

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    indicators = {}
    indicators["MA"] = ti.calc_ma(close, periods=[5, 10, 20, 60])
    indicators["MACD"] = ti.calc_macd(close)
    indicators["KDJ"] = ti.calc_kdj(high, low, close)
    indicators["RSI"] = ti.calc_rsi(close, periods=[6, 12, 24])
    indicators["BOLL"] = ti.calc_boll(close)

    return indicators


# ═══════════════════════════════════════════════════════
# K线形态识别（复用 kline_patterns.py）
# ═══════════════════════════════════════════════════════

def detect_patterns(df: pd.DataFrame, min_confidence: float = 0.5) -> List[Any]:
    """
    调用kline-patterns模块检测K线形态。

    Returns
    -------
    list of PatternSignal objects
    """
    kp = _import_patterns()
    signals = kp.scan_patterns(df, min_confidence=min_confidence)
    return signals


# ═══════════════════════════════════════════════════════
# 重要价格位标注（前高/前低/支撑/阻力）
# ═══════════════════════════════════════════════════════

def find_key_price_levels(df: pd.DataFrame, lookback: int = 20) -> Dict[str, Any]:
    """
    自动识别重要价格位：前高、前低、支撑位、阻力位。

    Parameters
    ----------
    df : DataFrame with OHLCV columns
    lookback : int
        局部极值检测的回看窗口

    Returns
    -------
    dict with keys: previous_high, previous_low, support_levels, resistance_levels
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)

    # 局部前高（lookback窗口内的最高点）
    prev_high_idx = -1
    if n > lookback:
        segment = high[-(lookback + 1):-1]
        prev_high_idx = np.argmax(segment) + (n - lookback - 1)

    # 局部前低
    prev_low_idx = -1
    if n > lookback:
        segment = low[-(lookback + 1):-1]
        prev_low_idx = np.argmin(segment) + (n - lookback - 1)

    # 支撑位：多次触及的低点区域（聚类）
    local_lows = []
    for i in range(lookback, n - lookback):
        if low[i] == np.min(low[max(0, i - lookback):i + lookback + 1]):
            local_lows.append(low[i])

    support_levels = _cluster_prices(local_lows, tolerance_pct=0.02) if local_lows else []

    # 阻力位：多次触及的高点区域（聚类）
    local_highs = []
    for i in range(lookback, n - lookback):
        if high[i] == np.max(high[max(0, i - lookback):i + lookback + 1]):
            local_highs.append(high[i])

    resistance_levels = _cluster_prices(local_highs, tolerance_pct=0.02) if local_highs else []

    return {
        "previous_high": float(high[prev_high_idx]) if prev_high_idx >= 0 else None,
        "previous_low": float(low[prev_low_idx]) if prev_low_idx >= 0 else None,
        "support_levels": sorted(support_levels),
        "resistance_levels": sorted(resistance_levels, reverse=True),
    }


def _cluster_prices(prices: List[float], tolerance_pct: float = 0.02) -> List[float]:
    """将接近的价格聚类，返回代表值"""
    if not prices:
        return []

    sorted_prices = sorted(prices)
    clusters = [[sorted_prices[0]]]

    for p in sorted_prices[1:]:
        last_cluster_avg = np.mean(clusters[-1])
        if abs(p - last_cluster_avg) / last_cluster_avg < tolerance_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])

    return [round(float(np.mean(c)), 2) for c in clusters]


# ═══════════════════════════════════════════════════════
# Matplotlib K线图绘制引擎（静态图+PNG导出）
# ═══════════════════════════════════════════════════════

def plot_candlestick_matplotlib(
    df: pd.DataFrame,
    indicators: Optional[Dict[str, Any]] = None,
    patterns: Optional[List[Any]] = None,
    key_levels: Optional[Dict[str, Any]] = None,
    show_macd: bool = True,
    show_kdj: bool = False,
    show_rsi: bool = False,
    show_boll: bool = True,
    show_ma: bool = True,
    output_path: Optional[str] = None,
    dpi: int = 300,
    figsize: Tuple[int, int] = (16, 12),
) -> Any:
    """
    使用matplotlib绘制完整的K线图+技术指标叠加图。

    Parameters
    ----------
    df : DataFrame with OHLCV columns
    indicators : dict of indicator series (from compute_all_indicators)
    patterns : list of PatternSignal objects
    key_levels : dict from find_key_price_levels
    show_macd : bool - 显示MACD子图
    show_kdj : bool - 显示KDJ子图（与RSI互斥）
    show_rsi : bool - 显示RSI子图（与KDJ互斥）
    show_boll : bool - 主图叠加布林带
    show_ma : bool - 主图叠加均线系统
    output_path : str - PNG输出路径，None则不保存
    dpi : int - 导出分辨率
    figsize : tuple - 画布尺寸

    Returns
    -------
    matplotlib Figure object
    """
    plt = _setup_chinese_font()
    import mplfinance as mpf

    if indicators is None:
        indicators = compute_all_indicators(df)

    n = len(df)
    dates = pd.to_datetime(df["date"])

    # ── 构建子图布局 ────────────────────────────────
    subplots = []
    subplot_titles = []
    panel_ratios = [0.45]  # 主图K线+成交量

    if show_macd:
        subplots.append("MACD")
        subplot_titles.append("MACD (DIFF/DEA/Histogram)")
        panel_ratios.append(0.18)

    if show_kdj or show_rsi:
        indicator_name = "KDJ" if show_kdj else "RSI"
        subplots.append(indicator_name)
        subplot_titles.append(f"{indicator_name}" + (" (超买/超卖区域)" if show_kdj else " (70/30阈值线)"))
        panel_ratios.append(0.18)

    # 计算总高度
    total_height = sum(panel_ratios) * 6
    fig, axes = plt.subplots(len(subplots) + 1, 1, figsize=figsize,
                             gridspec_kw={"height_ratios": panel_ratios},
                             sharex=True)

    if len(subplots) == 0:
        axes = [axes]

    ax_main = axes[0]       # K线主图
    ax_vol = axes[0].twinx()  # 成交量（共享主图）

    # ── 1. 绘制蜡烛图 ────────────────────────────────
    colors = ["#e74c3c" if c >= o else "#2ecc71" for c, o in zip(df["close"], df["open"])]

    # 使用mplfinance的addplot机制，但这里手动绘制更灵活
    width = 0.6
    x_positions = np.arange(n)

    for i in range(n):
        o, h, l, c = float(df["open"].iloc[i]), float(df["high"].iloc[i]), \
                      float(df["low"].iloc[i]), float(df["close"].iloc[i])
        color = "#e74c3c" if c >= o else "#2ecc71"  # 红涨绿跌

        # 影线（上下）
        ax_main.plot([i, i], [l, h], color=color, linewidth=0.8)
        # 实体
        body_bottom = min(o, c)
        body_height = abs(c - o) if abs(c - o) > 0.01 else 0.01
        ax_main.bar(i, body_height, width=width, bottom=body_bottom,
                    color=color, edgecolor="none", alpha=0.9)

    # ── 2. MA均线叠加 ────────────────────────────────
    if show_ma and "MA" in indicators:
        ma_colors = {"MA5": "#f39c12", "MA10": "#3498db", "MA20": "#9b59b6", "MA60": "#e67e22"}
        for ma_name, color in ma_colors.items():
            if ma_name in indicators["MA"]:
                ax_main.plot(x_positions, indicators["MA"][ma_name],
                             color=color, linewidth=1.0, alpha=0.8, label=ma_name)

    # ── 3. BOLL布林带叠加 ────────────────────────────
    if show_boll and "BOLL" in indicators:
        ax_main.fill_between(x_positions,
                             indicators["BOLL"]["BOLL_UPPER"],
                             indicators["BOLL"]["BOLL_LOWER"],
                             alpha=0.1, color="#3498db", label="BOLL通道")
        ax_main.plot(x_positions, indicators["BOLL"]["BOLL_UPPER"],
                     color="#3498db", linewidth=0.8, linestyle="--", alpha=0.6)
        ax_main.plot(x_positions, indicators["BOLL"]["BOLL_MID"],
                     color="#2980b9", linewidth=1.0, alpha=0.7, label="BOLL中轨")
        ax_main.plot(x_positions, indicators["BOLL"]["BOLL_LOWER"],
                     color="#3498db", linewidth=0.8, linestyle="--", alpha=0.6)

    # ── 4. 成交量柱状图（底部对齐主图）───────────────
    vol_colors = ["#e74c3c" if c >= o else "#2ecc71" for c, o in zip(df["close"], df["open"])]
    max_vol = df["volume"].max() * 0.35  # 成交量占主图高度的35%
    price_range = float(df["high"].max()) - float(df["low"].min())

    ax_vol.bar(x_positions, df["volume"], width=width, color=vol_colors,
               alpha=0.4, edgecolor="none")
    ax_vol.set_ylim(0, max(max_vol * 1.2, 1))
    ax_vol.tick_params(labelleft=False)

    # ── 5. K线形态标注 ────────────────────────────────
    if patterns:
        _annotate_patterns(ax_main, x_positions, df, patterns)

    # ── 6. 重要价格位标注 ────────────────────────────
    if key_levels:
        _annotate_key_levels(ax_main, x_positions, n, key_levels)

    # 主图设置
    ax_main.set_title(f"A股K线图 - {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}",
                      fontsize=12, fontweight="bold", pad=10)
    ax_main.legend(loc="upper left", fontsize=7, framealpha=0.8)
    ax_main.grid(True, alpha=0.3, linestyle="--")

    # ── 7. MACD子图 ──────────────────────────────────
    if show_macd and "MACD" in indicators:
        ax_macd = axes[1]
        dif = indicators["MACD"]["DIF"]
        dea = indicators["MACD"]["DEA"]
        hist = indicators["MACD"]["MACD_Hist"]

        macd_colors = ["#e74c3c" if v >= 0 else "#2ecc71" for v in hist]
        ax_macd.bar(x_positions, hist, width=width * 0.5, color=macd_colors, alpha=0.6)
        ax_macd.plot(x_positions, dif, color="#e74c3c", linewidth=1.2, label="DIF")
        ax_macd.plot(x_positions, dea, color="#f39c12", linewidth=1.2, label="DEA")
        ax_macd.axhline(y=0, color="gray", linewidth=0.5)
        ax_macd.set_ylabel("MACD", fontsize=8)
        ax_macd.legend(loc="upper left", fontsize=7)
        ax_macd.grid(True, alpha=0.3)

    # ── 8. KDJ子图 ───────────────────────────────────
    if show_kdj and "KDJ" in indicators:
        idx = 2 if show_macd else 1
        ax_kdj = axes[idx]
        k = indicators["KDJ"]["K"]
        d = indicators["KDJ"]["D"]
        j = indicators["KDJ"]["J"]

        # 超买/超卖区域标记
        ax_kdj.axhspan(80, 100, alpha=0.1, color="red", label="超买区")
        ax_kdj.axhspan(0, 20, alpha=0.1, color="green", label="超卖区")
        ax_kdj.axhline(y=80, color="red", linewidth=0.5, linestyle="--", alpha=0.5)
        ax_kdj.axhline(y=20, color="green", linewidth=0.5, linestyle="--", alpha=0.5)

        ax_kdj.plot(x_positions, k, color="#e74c3c", linewidth=1.0, label="K")
        ax_kdj.plot(x_positions, d, color="#f39c12", linewidth=1.0, label="D")
        ax_kdj.plot(x_positions, j, color="#3498db", linewidth=1.0, label="J")

        ax_kdj.set_ylim(-20, 120)
        ax_kdj.set_ylabel("KDJ", fontsize=8)
        ax_kdj.legend(loc="upper left", fontsize=7)
        ax_kdj.grid(True, alpha=0.3)

    # ── 9. RSI子图 ───────────────────────────────────
    if show_rsi and "RSI" in indicators:
        idx = 2 if show_macd else 1
        ax_rsi = axes[idx]

        for rsi_key, color in [("RSI6", "#e74c3c"), ("RSI12", "#f39c12"), ("RSI24", "#3498db")]:
            if rsi_key in indicators["RSI"]:
                ax_rsi.plot(x_positions, indicators["RSI"][rsi_key],
                            color=color, linewidth=1.0, label=rsi_key)

        # 70/30阈值线
        ax_rsi.axhline(y=70, color="red", linewidth=0.8, linestyle="--", alpha=0.6, label="超买(70)")
        ax_rsi.axhline(y=30, color="green", linewidth=0.8, linestyle="--", alpha=0.6, label="超卖(30)")
        ax_rsi.axhspan(70, 100, alpha=0.05, color="red")
        ax_rsi.axhspan(0, 30, alpha=0.05, color="green")

        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_ylabel("RSI", fontsize=8)
        ax_rsi.legend(loc="upper left", fontsize=7)
        ax_rsi.grid(True, alpha=0.3)

    # ── X轴日期格式化 ────────────────────────────────
    if n > 120:
        tick_interval = max(1, n // 15)
    elif n > 60:
        tick_interval = max(1, n // 10)
    else:
        tick_interval = max(1, n // 8)

    tick_indices = list(range(0, n, tick_interval))
    tick_labels = [dates.iloc[i].strftime("%m-%d") for i in tick_indices]

    ax_main.set_xticks(tick_indices)
    ax_main.set_xticklabels(tick_labels, fontsize=7)
    plt.xticks(rotation=45)

    # 紧凑布局
    plt.tight_layout(pad=2.0)

    # ── 导出PNG ──────────────────────────────────────
    if output_path:
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
        print(f"✅ PNG图表已保存: {output_path} ({dpi} DPI)")

    return fig


def _annotate_patterns(ax, x_positions: np.ndarray, df: pd.DataFrame, patterns: List[Any]):
    """在K线图上标注形态位置"""
    # 只标注置信度较高的前10个形态，避免过于拥挤
    sorted_patterns = sorted(patterns, key=lambda p: getattr(p, "confidence", 0), reverse=True)[:10]

    for sig in sorted_patterns:
        idx = getattr(sig, "index", None)
        if idx is None or idx >= len(df):
            continue

        name = getattr(sig, "name", "?")
        conf = getattr(sig, "confidence", 0)
        direction = getattr(sig, "direction", "neutral")

        # 颜色：看涨=绿色，看跌=红色，中性=蓝色
        color_map = {"bullish": "#2ecc71", "bearish": "#e74c3c", "neutral": "#3498db"}
        arrow_color = color_map.get(direction, "#3498db")

        # 箭头位置：看涨在下方，看跌在上方
        price = float(df["low"].iloc[idx]) if direction == "bullish" else float(df["high"].iloc[idx])
        offset = (float(df["high"].max()) - float(df["low"].min())) * 0.03

        y_pos = float(df["low"].iloc[idx]) - offset if direction == "bullish" \
                else float(df["high"].iloc[idx]) + offset

        label = f"{name}\n{conf:.0%}"
        ax.annotate(label, xy=(idx, price), xytext=(idx, y_pos),
                    fontsize=6, color=arrow_color, ha="center",
                    arrowprops=dict(arrowstyle="->", color=arrow_color, lw=0.8),
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7, edgecolor=arrow_color))


def _annotate_key_levels(ax, x_positions: np.ndarray, n: int, key_levels: Dict[str, Any]):
    """标注重要价格位"""
    if key_levels.get("previous_high"):
        ax.axhline(y=key_levels["previous_high"], color="#f39c12", linewidth=0.8,
                   linestyle=":", alpha=0.6)
        ax.text(n - 1, key_levels["previous_high"] * 1.001, f'前高: {key_levels["previous_high"]:.2f}',
                fontsize=6, color="#f39c12", ha="right", va="bottom")

    if key_levels.get("previous_low"):
        ax.axhline(y=key_levels["previous_low"], color="#e74c3c", linewidth=0.8,
                   linestyle=":", alpha=0.6)
        ax.text(n - 1, key_levels["previous_low"] * 0.999, f'前低: {key_levels["previous_low"]:.2f}',
                fontsize=6, color="#e74c3c", ha="right", va="top")

    # 支撑位（最多标注3个）
    for i, level in enumerate(key_levels.get("support_levels", [])[:3]):
        if i == 0:
            continue  # 跳过最接近当前价格的
        ax.axhline(y=level, color="#2ecc71", linewidth=0.5, linestyle="-.", alpha=0.4)

    # 阻力位（最多标注3个）
    for i, level in enumerate(key_levels.get("resistance_levels", [])[:3]):
        if i == 0:
            continue
        ax.axhline(y=level, color="#e74c3c", linewidth=0.5, linestyle="-.", alpha=0.4)


# ═══════════════════════════════════════════════════════
# Plotly 交互式图表引擎（HTML输出）
# ═══════════════════════════════════════════════════════

def plot_candlestick_plotly(
    df: pd.DataFrame,
    indicators: Optional[Dict[str, Any]] = None,
    patterns: Optional[List[Any]] = None,
    key_levels: Optional[Dict[str, Any]] = None,
    show_macd: bool = True,
    show_kdj: bool = False,
    show_rsi: bool = False,
    show_boll: bool = True,
    show_ma: bool = True,
    output_path: Optional[str] = None,
    open_browser: bool = False,
) -> Any:
    """
    使用plotly绘制交互式K线图，支持缩放/十字光标/悬浮提示。

    Parameters
    ----------
    df : DataFrame with OHLCV columns
    indicators : dict of indicator series
    patterns : list of PatternSignal objects
    key_levels : dict from find_key_price_levels
    show_macd/show_kdj/show_rsi/show_boll/show_ma : bool flags
    output_path : str - HTML输出路径
    open_browser : bool - 是否自动打开浏览器

    Returns
    -------
    plotly Figure object
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    if indicators is None:
        indicators = compute_all_indicators(df)

    n = len(df)
    dates = pd.to_datetime(df["date"])

    # ── 构建子图规格 ────────────────────────────────
    rows = 1  # K线主图
    if show_macd:
        rows += 1
    if show_kdj or show_rsi:
        rows += 1

    row_heights = [0.45]
    if show_macd:
        row_heights.append(0.2)
    if show_kdj or show_rsi:
        row_heights.append(0.2)

    specs = [[{"secondary_y": True}]]  # K线+成交量共享主图
    for _ in range(rows - 1):
        specs.append([{}])

    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=row_heights, specs=specs,
        subplot_titles=["K线图 + 成交量", "MACD" if show_macd else None,
                        ("KDJ" if show_kdj else "RSI") if (show_kdj or show_rsi) else None]
    )

    # ── 1. K线蜡烛图 ────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=dates, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="K线", increasing_line_color="#e74c3c", decreasing_line_color="#2ecc71",
        increasing_fillcolor="#e74c3c", decreasing_fillcolor="#2ecc71"
    ), row=1, col=1)

    # ── 2. MA均线 ────────────────────────────────────
    if show_ma and "MA" in indicators:
        ma_colors = {"MA5": "#f39c12", "MA10": "#3498db", "MA20": "#9b59b6", "MA60": "#e67e22"}
        for ma_name, color in ma_colors.items():
            if ma_name in indicators["MA"]:
                fig.add_trace(go.Scatter(
                    x=dates, y=indicators["MA"][ma_name], mode="lines",
                    name=ma_name, line=dict(color=color, width=1.2)
                ), row=1, col=1)

    # ── 3. BOLL布林带 ────────────────────────────────
    if show_boll and "BOLL" in indicators:
        fig.add_trace(go.Scatter(
            x=dates, y=indicators["BOLL"]["BOLL_UPPER"], mode="lines",
            name="BOLL上轨", line=dict(color="#3498db", width=0.8, dash="dash"), opacity=0.6
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=indicators["BOLL"]["BOLL_LOWER"], mode="lines",
            name="BOLL下轨", line=dict(color="#3498db", width=0.8, dash="dash"), opacity=0.6,
            fill="tonexty", fillcolor="rgba(52,152,219,0.1)"
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=indicators["BOLL"]["BOLL_MID"], mode="lines",
            name="BOLL中轨", line=dict(color="#2980b9", width=1.0), opacity=0.7
        ), row=1, col=1)

    # ── 4. 成交量（次坐标轴）──────────────────────────
    vol_colors = ["#e74c3c" if c >= o else "#2ecc71" for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=dates, y=df["volume"], name="成交量",
        marker_color=vol_colors, opacity=0.4
    ), row=1, col=1, secondary_y=True)

    # ── 5. K线形态标注（散点+文本）────────────────────
    if patterns:
        _add_pattern_annotations_plotly(fig, dates, df, patterns, row=1, col=1)

    # ── 6. 重要价格位 ────────────────────────────────
    if key_levels:
        if key_levels.get("previous_high"):
            fig.add_hline(y=key_levels["previous_high"], line_dash="dot",
                          line_color="#f39c12", opacity=0.5, row=1, col=1)
        if key_levels.get("previous_low"):
            fig.add_hline(y=key_levels["previous_low"], line_dash="dot",
                          line_color="#e74c3c", opacity=0.5, row=1, col=1)

    # ── 7. MACD子图 ──────────────────────────────────
    if show_macd and "MACD" in indicators:
        macd_row = 2
        hist_colors = ["#e74c3c" if v >= 0 else "#2ecc71" for v in indicators["MACD"]["MACD_Hist"]]
        fig.add_trace(go.Bar(
            x=dates, y=indicators["MACD"]["MACD_Hist"], name="MACD柱",
            marker_color=hist_colors, opacity=0.5
        ), row=macd_row, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=indicators["MACD"]["DIF"], mode="lines",
            name="DIF", line=dict(color="#e74c3c", width=1.2)
        ), row=macd_row, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=indicators["MACD"]["DEA"], mode="lines",
            name="DEA", line=dict(color="#f39c12", width=1.2)
        ), row=macd_row, col=1)

    # ── 8. KDJ子图 ───────────────────────────────────
    if show_kdj and "KDJ" in indicators:
        kdj_row = 3 if show_macd else 2
        fig.add_trace(go.Scatter(
            x=dates, y=indicators["KDJ"]["K"], mode="lines",
            name="K", line=dict(color="#e74c3c", width=1.0)
        ), row=kdj_row, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=indicators["KDJ"]["D"], mode="lines",
            name="D", line=dict(color="#f39c12", width=1.0)
        ), row=kdj_row, col=1)
        fig.add_trace(go.Scatter(
            x=dates, y=indicators["KDJ"]["J"], mode="lines",
            name="J", line=dict(color="#3498db", width=1.0)
        ), row=kdj_row, col=1)
        # 超买/超卖线
        fig.add_hline(y=80, line_dash="dash", line_color="red", opacity=0.5, row=kdj_row, col=1)
        fig.add_hline(y=20, line_dash="dash", line_color="green", opacity=0.5, row=kdj_row, col=1)

    # ── 9. RSI子图 ───────────────────────────────────
    if show_rsi and "RSI" in indicators:
        rsi_row = 3 if show_macd else 2
        for rsi_key, color in [("RSI6", "#e74c3c"), ("RSI12", "#f39c12"), ("RSI24", "#3498db")]:
            if rsi_key in indicators["RSI"]:
                fig.add_trace(go.Scatter(
                    x=dates, y=indicators["RSI"][rsi_key], mode="lines",
                    name=rsi_key, line=dict(color=color, width=1.0)
                ), row=rsi_row, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=rsi_row, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=rsi_row, col=1)

    # ── 布局设置 ──────────────────────────────────────
    stock_name = df.attrs.get("symbol", "A股") if hasattr(df, "attrs") else ""
    fig.update_layout(
        title=dict(text=f"A股K线图 {stock_name}", x=0.5, font=dict(size=16)),
        height=sum(h * 800 for h in row_heights),
        width=1200,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        template="plotly_white",
        margin=dict(l=60, r=40, t=80, b=50)
    )

    # 隐藏成交量次坐标轴的标签
    fig.update_yaxes(title_text="", row=1, col=1, secondary_y=True)

    # ── 导出HTML ─────────────────────────────────────
    if output_path:
        fig.write_html(output_path, include_plotlyjs="cdn")
        print(f"✅ HTML交互式图表已保存: {output_path}")
        if open_browser:
            webbrowser.open(f"file://{os.path.abspath(output_path)}")
            print("  🌐 已在浏览器中打开")

    return fig


def _add_pattern_annotations_plotly(fig, dates: pd.Series, df: pd.DataFrame, patterns: List[Any], row: int, col: int):
    """在plotly图上添加形态标注"""
    sorted_patterns = sorted(patterns, key=lambda p: getattr(p, "confidence", 0), reverse=True)[:8]

    for sig in sorted_patterns:
        idx = getattr(sig, "index", None)
        if idx is None or idx >= len(df):
            continue

        name = getattr(sig, "name", "?")
        conf = getattr(sig, "confidence", 0)
        direction = getattr(sig, "direction", "neutral")

        color_map = {"bullish": "#2ecc71", "bearish": "#e74c3c", "neutral": "#3498db"}
        marker_color = color_map.get(direction, "#3498db")

        price = float(df["low"].iloc[idx]) if direction == "bullish" else float(df["high"].iloc[idx])
        offset = (float(df["high"].max()) - float(df["low"].min())) * 0.02
        y_pos = float(df["low"].iloc[idx]) - offset if direction == "bullish" \
                else float(df["high"].iloc[idx]) + offset

        fig.add_trace(go.Scatter(
            x=[dates.iloc[idx]], y=[y_pos], mode="text",
            text=[f"{name}<br>{conf:.0%}"], textposition="middle center",
            textfont=dict(color=marker_color, size=9),
            hoverinfo="skip", showlegend=False
        ), row=row, col=col)


# ═══════════════════════════════════════════════════════
# 批量图表生成（对比图/矩阵/雷达图）
# ═══════════════════════════════════════════════════════

def generate_comparison_chart(
    symbols: List[str], periods: int = 250, output_path: Optional[str] = None,
    dpi: int = 300
) -> Any:
    """
    多只股票K线对比图（归一化价格，叠加在同一坐标系）。

    Parameters
    ----------
    symbols : list of str - 股票代码列表
    periods : int - K线周期数
    output_path : str - PNG输出路径
    dpi : int - 导出分辨率

    Returns
    -------
    matplotlib Figure object
    """
    plt = _setup_chinese_font()

    all_data: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            df = fetch_kline_data(sym, periods)
            # 归一化：以第一天收盘价为基准，计算相对涨跌幅
            base_price = float(df["close"].iloc[0])
            df["norm_close"] = (df["close"] / base_price - 1) * 100
            all_data[sym] = df
        except Exception as e:
            print(f"  ⚠️ {sym} 数据获取失败: {e}")

    if not all_data:
        raise RuntimeError("所有股票数据获取均失败")

    fig, ax = plt.subplots(figsize=(14, 7))

    colors = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
              "#e67e22", "#1abc9c", "#d35400"]

    for i, (sym, df) in enumerate(all_data.items()):
        color = colors[i % len(colors)]
        ax.plot(pd.to_datetime(df["date"]), df["norm_close"],
                color=color, linewidth=1.2, label=sym)

    ax.set_title("多股票价格走势对比（归一化涨跌幅%）", fontsize=14, fontweight="bold")
    ax.set_ylabel("相对涨跌幅 (%)")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
        print(f"✅ 对比图已保存: {output_path}")

    return fig


def generate_stock_matrix(
    symbols: List[str], periods: int = 120, output_path: Optional[str] = None,
    dpi: int = 300, cols: int = 4
) -> Any:
    """
    板块成分股K线矩阵（网格布局，每只股票一个子图）。

    Parameters
    ----------
    symbols : list of str - 股票代码列表
    periods : int - K线周期数
    output_path : str - PNG输出路径
    dpi : int - 导出分辨率
    cols : int - 矩阵列数（默认4）

    Returns
    -------
    matplotlib Figure object
    """
    plt = _setup_chinese_font()

    all_data: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            df = fetch_kline_data(sym, periods)
            all_data[sym] = df
        except Exception as e:
            print(f"  ⚠️ {sym} 数据获取失败: {e}")

    if not all_data:
        raise RuntimeError("所有股票数据获取均失败")

    n_stocks = len(all_data)
    rows = (n_stocks + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4, rows * 3), squeeze=False)

    for idx, (sym, df) in enumerate(all_data.items()):
        r, c = divmod(idx, cols)
        ax = axes[r, c]

        dates = pd.to_datetime(df["date"])
        colors = ["#e74c3c" if cl >= op else "#2ecc71" for cl, op in zip(df["close"], df["open"])]

        # 简化蜡烛图（使用bar）
        x_pos = np.arange(len(df))
        for i in range(len(df)):
            o, h, l, c = float(df["open"].iloc[i]), float(df["high"].iloc[i]), \
                          float(df["low"].iloc[i]), float(df["close"].iloc[i])
            color = "#e74c3c" if c >= o else "#2ecc71"
            ax.plot([i, i], [l, h], color=color, linewidth=0.5)
            body_bottom = min(o, c)
            body_height = abs(c - o) if abs(c - o) > 0.01 else 0.01
            ax.bar(i, body_height, width=0.6, bottom=body_bottom,
                   color=color, edgecolor="none", alpha=0.85)

        # MA5/MA20
        ti = _import_indicators()
        ma = ti.calc_ma(df["close"], periods=[5, 20])
        ax.plot(x_pos, ma["MA5"], color="#f39c12", linewidth=0.6, alpha=0.7)
        ax.plot(x_pos, ma["MA20"], color="#3498db", linewidth=0.6, alpha=0.7)

        last_close = float(df["close"].iloc[-1])
        first_close = float(df["close"].iloc[0])
        change_pct = (last_close - first_close) / first_close * 100
        color_label = "#e74c3c" if change_pct >= 0 else "#2ecc71"

        ax.set_title(f"{sym} ({change_pct:+.1f}%)", fontsize=9, fontweight="bold", color=color_label)
        ax.tick_params(labelsize=6)
        ax.grid(True, alpha=0.2)

    # 隐藏多余子图
    for idx in range(n_stocks, rows * cols):
        r, c = divmod(idx, cols)
        axes[r, c].set_visible(False)

    plt.suptitle("板块成分股K线矩阵", fontsize=14, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.96])

    if output_path:
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
        print(f"✅ K线矩阵已保存: {output_path}")

    return fig


def generate_radar_chart(
    factors: Dict[str, float], title: str = "多因子得分雷达图",
    output_path: Optional[str] = None, dpi: int = 300
) -> Any:
    """
    多因子选股结果可视化（雷达图）。

    Parameters
    ----------
    factors : dict - {因子名称: 得分(0-1)}
    title : str - 图表标题
    output_path : str - PNG输出路径
    dpi : int - 导出分辨率

    Returns
    -------
    matplotlib Figure object
    """
    plt = _setup_chinese_font()

    labels = list(factors.keys())
    values = list(factors.values())
    n_vars = len(labels)

    # 计算角度
    angles = np.linspace(0, 2 * np.pi, n_vars, endpoint=False).tolist()
    angles += angles[:1]  # 闭合
    values_extended = values + values[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

    ax.fill(angles, values_extended, alpha=0.25, color="#3498db")
    ax.plot(angles, values_extended, linewidth=2, color="#3498db", marker="o", markersize=5)

    # 设置标签
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 1.0)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8", "1.0"], fontsize=7)

    # 添加数值标注
    for angle, val, label in zip(angles[:-1], values, labels):
        offset = 0.05
        ax.text(angle, val + offset, f"{val:.2f}", ha="center", va="bottom",
                fontsize=7, color="#3498db")

    fig.suptitle(title, fontsize=14, fontweight="bold", y=1.02)

    if output_path:
        fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
        print(f"✅ 雷达图已保存: {output_path}")

    return fig


# ═══════════════════════════════════════════════════════
# ASCII终端简化版K线图
# ═══════════════════════════════════════════════════════

def ascii_kline(df: pd.DataFrame, width: int = 80, height: int = 20) -> str:
    """
    在终端内显示ASCII简化版K线图。

    Parameters
    ----------
    df : DataFrame with OHLCV columns
    width : int - 字符宽度
    height : int - 字符高度

    Returns
    -------
    str - ASCII图表文本
    """
    n = len(df)
    if n == 0:
        return "无数据"

    close = df["close"].values.astype(float)
    high_vals = df["high"].values.astype(float)
    low_vals = df["low"].values.astype(float)

    # 采样到宽度
    step = max(1, n // width)
    sampled_close = [float(close[i * step]) for i in range(min(width, (n + step - 1) // step))]
    sampled_high = [float(high_vals[i * step]) for i in range(len(sampled_close))]
    sampled_low = [float(low_vals[i * step]) for i in range(len(sampled_close))]

    min_price = min(sampled_low)
    max_price = max(sampled_high)
    price_range = max_price - min_price if max_price > min_price else 1.0

    # 构建字符矩阵
    grid = [[" " for _ in range(len(sampled_close))] for _ in range(height)]

    for col_idx, (c_val, h_val, l_val) in enumerate(zip(sampled_close, sampled_high, sampled_low)):
        row_top = int((h_val - min_price) / price_range * (height - 1))
        row_bottom = int((l_val - min_price) / price_range * (height - 1))
        row_close = int((c_val - min_price) / price_range * (height - 1))

        # 限制范围
        row_top = max(0, min(height - 1, row_top))
        row_bottom = max(0, min(height - 1, row_bottom))
        row_close = max(0, min(height - 1, row_close))

        for r in range(row_top, row_bottom + 1):
            if grid[r][col_idx] == " ":
                grid[r][col_idx] = "|"

        # 收盘价标记
        is_up = c_val >= sampled_close[max(0, col_idx - 1)] if col_idx > 0 else True
        grid[row_close][col_idx] = "+" if is_up else "-"

    # 构建输出文本
    lines = []
    price_step = price_range / (height - 1) if height > 1 else price_range

    for r in range(height):
        price_at_row = max_price - r * price_step
        line = f"{price_at_row:8.2f} |{''.join(grid[r])}"
        lines.append(line)

    # X轴标签
    x_labels = "         +" + "-" * len(sampled_close)
    lines.append(x_labels)

    last_price = float(close[-1])
    first_price = float(close[0])
    change_pct = (last_price - first_price) / first_price * 100 if first_price > 0 else 0
    lines.append(f"         [{change_pct:+.2f}%] 最新: {last_price:.2f}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════
# CLI入口
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="A股可视化图表引擎 - K线图+技术指标叠加图生成与导出",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 单股K线图（PNG静态图）
  python visualization.py 600519 --output chart.png

  # 交互式HTML图表
  python visualization.py 600519 --html output.html --open-browser

  # 显示RSI而非KDJ
  python visualization.py 000001 --rsi --no-kdj --output rsi_chart.png

  # 终端ASCII简化版
  python visualization.py 600519 --ascii

  # 多股对比图（归一化价格走势）
  python visualization.py batch --symbols 600519,000001,601318 --mode compare

  # K线矩阵（板块成分股网格布局）
  python visualization.py batch --symbols 600519,000001,601318,000858,600036,600276 --mode matrix

  # 多因子雷达图（从JSON文件读取因子得分）
  python visualization.py radar --factors-file factors.json --output radar.png
        """
    )

    parser.add_argument("symbol", nargs="?", help="股票代码或名称，如 600519")
    parser.add_argument("--periods", "-p", type=int, default=250, help="K线周期数（默认250）")
    parser.add_argument("--output", "-o", help="PNG输出路径")
    parser.add_argument("--html", "-H", help="HTML交互式图表输出路径")
    parser.add_argument("--open-browser", action="store_true", help="自动打开浏览器查看HTML")
    parser.add_argument("--dpi", type=int, default=300, help="PNG导出分辨率（默认300）")

    # 指标开关
    parser.add_argument("--no-macd", action="store_true", help="隐藏MACD子图")
    parser.add_argument("--kdj", action="store_true", help="显示KDJ子图（默认）")
    parser.add_argument("--no-kdj", action="store_true", help="隐藏KDJ子图")
    parser.add_argument("--rsi", action="store_true", help="显示RSI子图（替代KDJ）")
    parser.add_argument("--no-boll", action="store_true", help="隐藏布林带")
    parser.add_argument("--no-ma", action="store_true", help="隐藏均线系统")

    # 终端ASCII模式
    parser.add_argument("--ascii", "-a", action="store_true", help="终端内显示ASCII简化版K线图")

    # 批量生成子命令
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    batch_parser = subparsers.add_parser("batch", help="批量图表生成")
    batch_parser.add_argument("--symbols", "-s", required=True,
                              help="逗号分隔的股票代码，如 600519,000001,601318")
    batch_parser.add_argument("--mode", "-m", default="compare",
                              choices=["compare", "matrix"],
                              help="批量模式: compare=对比图, matrix=K线矩阵（默认compare）")
    batch_parser.add_argument("--output", "-o", required=True, help="输出文件路径")
    batch_parser.add_argument("--periods", "-p", type=int, default=250, help="K线周期数")

    radar_parser = subparsers.add_parser("radar", help="多因子雷达图")
    radar_parser.add_argument("--factors-file", "-f", required=True,
                              help="JSON格式的因子得分文件，如 {\"PE\": 0.85, \"PB\": 0.72}")
    radar_parser.add_argument("--output", "-o", required=True, help="输出PNG路径")
    radar_parser.add_argument("--title", "-t", default="多因子得分雷达图", help="图表标题")

    args = parser.parse_args()

    # ── 批量生成命令 ────────────────────────────────
    if args.command == "batch":
        symbols = [s.strip() for s in args.symbols.split(",")]
        print(f"\n📊 批量图表生成 ({args.mode}模式, {len(symbols)}只股票)")
        print("=" * 50)

        if args.mode == "compare":
            generate_comparison_chart(
                symbols, periods=args.periods, output_path=args.output, dpi=args.dpi
            )
        elif args.mode == "matrix":
            generate_stock_matrix(
                symbols, periods=args.periods, output_path=args.output, dpi=args.dpi
            )

        print(f"✅ 批量生成完成: {args.output}")
        return

    # ── 雷达图命令 ──────────────────────────────────
    if args.command == "radar":
        with open(args.factors_file, "r", encoding="utf-8") as f:
            factors = json.load(f)

        print(f"\n📊 多因子雷达图 ({len(factors)}个因子)")
        generate_radar_chart(
            factors, title=args.title, output_path=args.output, dpi=args.dpi
        )
        return

    # ── 单股模式（需要symbol参数）────────────────────
    if not args.symbol:
        parser.print_help()
        sys.exit(0)

    symbol = args.symbol.strip()
    periods = args.periods

    print(f"\n{'='*60}")
    print(f"📊 A股可视化图表引擎")
    print(f"{'='*60}")
    print(f"🔍 股票: {symbol} | 周期: {periods}根K线")
    print()

    # ── ASCII模式（快速预览）─────────────────────────
    if args.ascii:
        try:
            df = fetch_kline_data(symbol, periods)
            chart_text = ascii_kline(df, width=80, height=20)
            print(chart_text)
            return
        except Exception as e:
            print(f"❌ 数据获取失败: {e}")
            sys.exit(1)

    # ── 完整图表模式 ────────────────────────────────
    try:
        df = fetch_kline_data(symbol, periods)
        print(f"✅ 获取到 {len(df)} 根K线数据 ({df['date'].iloc[0]} ~ {df['date'].iloc[-1]})")
    except Exception as e:
        print(f"❌ 数据获取失败: {e}")
        sys.exit(1)

    # 计算技术指标
    print("📐 正在计算技术指标...")
    indicators = compute_all_indicators(df)

    # 检测K线形态
    print("🔎 正在扫描K线形态...")
    patterns = detect_patterns(df, min_confidence=0.5)
    print(f"   发现 {len(patterns)} 个形态信号")

    # 识别重要价格位
    print("📍 正在识别重要价格位...")
    key_levels = find_key_price_levels(df)

    show_macd = not args.no_macd
    show_kdj = args.kdj and not args.no_kdj
    show_rsi = args.rsi
    show_boll = not args.no_boll
    show_ma = not args.no_ma

    # 如果既没有指定kdj也没有rsi，默认显示KDJ
    if not show_kdj and not show_rsi:
        show_kdj = True

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = symbol.replace("/", "_").replace("\\", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── 生成PNG静态图 ────────────────────────────────
    png_path = args.output or str(output_dir / f"{safe_name}_{timestamp}.png")
    print(f"\n📈 正在生成K线图 (PNG)...")
    try:
        fig_png = plot_candlestick_matplotlib(
            df, indicators=indicators, patterns=patterns, key_levels=key_levels,
            show_macd=show_macd, show_kdj=show_kdj, show_rsi=show_rsi,
            show_boll=show_boll, show_ma=show_ma, output_path=png_path, dpi=args.dpi
        )
    except Exception as e:
        print(f"❌ PNG图表生成失败: {e}")
        import traceback
        traceback.print_exc()

    # ── 生成HTML交互式图 ─────────────────────────────
    html_path = args.html or str(output_dir / f"{safe_name}_{timestamp}.html")
    if args.html or True:  # 默认也生成HTML
        print(f"🌐 正在生成交互式图表 (HTML)...")
        try:
            fig_html = plot_candlestick_plotly(
                df, indicators=indicators, patterns=patterns, key_levels=key_levels,
                show_macd=show_macd, show_kdj=show_kdj, show_rsi=show_rsi,
                show_boll=show_boll, show_ma=show_ma, output_path=html_path,
                open_browser=args.open_browser
            )
        except Exception as e:
            print(f"❌ HTML图表生成失败: {e}")
            import traceback
            traceback.print_exc()

    # ── 终端ASCII预览 ────────────────────────────────
    print("\n📊 ASCII简化预览:")
    chart_text = ascii_kline(df, width=70, height=15)
    print(chart_text)

    print(f"\n{'='*60}")
    print(f"✅ 图表生成完成!")
    print(f"   PNG: {png_path}")
    print(f"   HTML: {html_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
