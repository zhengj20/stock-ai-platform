"""智能预警 API"""
import sys
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.watchlist import WatchlistItem
from app.models.holding import Holding

router = APIRouter(prefix="/alerts", tags=["智能预警"], dependencies=[Depends(get_current_user)])

# 添加skills目录到路径
skills_dir = Path(__file__).parent.parent.parent.parent / "skills"
sys.path.insert(0, str(skills_dir / "smart-alert"))

ALERTS_LOG_DIR = Path(__file__).parent.parent.parent.parent / "alerts"


class HoldingContext(BaseModel):
    """持仓上下文（用于持仓感知预警）"""
    cost_price: float = 0.0
    quantity: int = 0
    position_type: str = "short"  # short/mid/long
    max_profit_ratio: float = 0.0
    profit_ratio: float = 0.0


class MonitorRequest(BaseModel):
    """监控请求"""
    stock: Optional[str] = Field(None, description="单只股票代码")
    pool: Optional[List[str]] = Field(None, description="股票池列表")
    rules: Optional[List[str]] = Field(None, description="启用规则列表")
    holding_context_map: Optional[Dict[str, HoldingContext]] = Field(None, description="持仓上下文 {code: {cost_price, position_type, ...}}")


class AlertResponse(BaseModel):
    """预警响应"""
    timestamp: str
    stock_code: str
    stock_name: str
    alert_type: str
    alert_level: str
    message: str
    current_value: float
    threshold_value: float
    recommendation: str


class MonitorSourceRequest(BaseModel):
    """监控来源请求"""
    rules: Optional[List[str]] = Field(None, description="启用规则列表")


@router.post("/monitor")
def monitor_stock(request: MonitorRequest):
    """
    监控股票预警

    - stock: 单只股票代码
    - pool: 股票池列表
    - rules: 启用规则列表 (可选)
    """
    try:
        from smart_alert import SmartAlertSystem

        system = SmartAlertSystem()

        if request.stock:
            stock_codes = [request.stock]
        elif request.pool:
            stock_codes = request.pool
        else:
            raise HTTPException(status_code=400, detail="请指定 stock 或 pool")

        if len(stock_codes) == 1:
            ctx = None
            if request.holding_context_map:
                ctx = request.holding_context_map.get(stock_codes[0])
            alerts = system.monitor_stock(stock_codes[0], request.rules, holding_context=ctx.__dict__ if ctx else None)
            return {
                "status": "success",
                "message": "监控完成",
                "data": {
                    "stock": stock_codes[0],
                    "alerts": [vars(a) for a in alerts],
                    "alert_count": len(alerts)
                }
            }
        else:
            hcm = None
            if request.holding_context_map:
                hcm = {k: v.__dict__ for k, v in request.holding_context_map.items()}
            all_alerts = system.monitor_pool(stock_codes, request.rules, holding_context_map=hcm)
            result = {}
            for code, alerts in all_alerts.items():
                result[code] = {
                    "alerts": [vars(a) for a in alerts],
                    "alert_count": len(alerts)
                }

            return {
                "status": "success",
                "message": "批量监控完成",
                "data": result
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"监控失败: {str(e)}")


@router.post("/monitor-watchlist")
def monitor_watchlist(
    req: MonitorSourceRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """监控自选股"""
    try:
        items = db.query(WatchlistItem).filter(
            WatchlistItem.user_id == current_user.id
        ).order_by(WatchlistItem.sort_order.asc()).all()

        if not items:
            raise HTTPException(status_code=400, detail="自选股为空")

        from smart_alert import SmartAlertSystem
        system = SmartAlertSystem()
        stock_codes = [item.stock_code for item in items]
        stock_map = {item.stock_code: item.stock_name for item in items}
        all_alerts = system.monitor_pool(stock_codes, req.rules)

        result = {}
        for code, alerts in all_alerts.items():
            alert_list = []
            for a in alerts:
                alert_dict = vars(a)
                if not alert_dict.get('stock_name') or alert_dict['stock_name'] == code:
                    alert_dict['stock_name'] = stock_map.get(code, code)
                alert_list.append(alert_dict)
            result[code] = {"alerts": alert_list, "alert_count": len(alert_list)}

        return {
            "status": "success",
            "message": f"自选股监控完成",
            "data": result,
            "summary": {"total": len(stock_codes), "alert_count": sum(v["alert_count"] for v in result.values())}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"自选股监控失败: {str(e)}")


@router.post("/monitor-holdings")
def monitor_holdings(
    req: MonitorSourceRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """监控持仓（含成本价/盈亏/持仓类型的持仓感知预警）"""
    try:
        items = db.query(Holding).filter(
            Holding.user_id == current_user.id
        ).all()

        if not items:
            raise HTTPException(status_code=400, detail="持仓为空")

        from smart_alert import SmartAlertSystem
        system = SmartAlertSystem()

        stock_codes = [item.stock_code for item in items]
        stock_map = {item.stock_code: item.stock_name for item in items}

        # 构建持仓上下文：cost_price / position_type / max_profit_ratio
        holding_context_map = {}
        for item in items:
            if item.cost_price > 0:
                holding_context_map[item.stock_code] = {
                    "cost_price": item.cost_price,
                    "quantity": item.quantity,
                    "position_type": item.position_type or "short",
                    "max_profit_ratio": item.profit_ratio or 0,
                    "profit_ratio": item.profit_ratio or 0,
                }

        # 持仓预警：使用前端传入的规则，或默认全部规则（含持仓感知）
        all_alerts = system.monitor_pool(stock_codes, req.rules, holding_context_map=holding_context_map)

        result = {}
        for code, alerts in all_alerts.items():
            alert_list = []
            for a in alerts:
                alert_dict = vars(a)
                if not alert_dict.get('stock_name') or alert_dict['stock_name'] == code:
                    alert_dict['stock_name'] = stock_map.get(code, code)
                alert_list.append(alert_dict)
            result[code] = {"alerts": alert_list, "alert_count": len(alert_list)}

        return {
            "status": "success",
            "message": f"持仓监控完成",
            "data": result,
            "summary": {"total": len(stock_codes), "alert_count": sum(v["alert_count"] for v in result.values())}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"持仓监控失败: {str(e)}")


@router.get("/rules")
async def list_rules():
    """列出可用预警规则"""
    try:
        from smart_alert import RuleManager

        rules = RuleManager.list_rules()

        rule_descriptions = {
            "macd_golden_cross": {"desc": "MACD金叉 - DIF上穿DEA", "category": "技术指标", "action_signal": "ADD"},
            "macd_death_cross": {"desc": "MACD死叉 - DIF下穿DEA", "category": "技术指标", "action_signal": "SELL"},
            "kdj_oversold": {"desc": "KDJ超卖 - J值低于20", "category": "技术指标", "action_signal": "BUY"},
            "kdj_overbought": {"desc": "KDJ超买 - J值高于80", "category": "技术指标", "action_signal": "REDUCE"},
            "rsi_oversold": {"desc": "RSI超卖反弹 - RSI从30以下回升", "category": "技术指标", "action_signal": "BUY"},
            "rsi_overbought": {"desc": "RSI超买回落 - RSI从70以上回落", "category": "技术指标", "action_signal": "REDUCE"},
            "volume_breakout": {"desc": "放量突破 - 成交量放大2倍以上", "category": "量价异动", "action_signal": "ADD"},
            "price_drop": {"desc": "大幅下跌 - 跌幅超过5%", "category": "风险预警", "action_signal": "SELL"},
            "stop_loss": {"desc": "止损预警 - 从高点回撤8%以上", "category": "风险预警", "action_signal": "SELL"},
            "high_volatility": {"desc": "高波动预警 - 年化波动率超过300%", "category": "风险预警", "action_signal": "REDUCE"},
            "ma_golden_cross": {"desc": "均线金叉 - MA5上穿MA20，趋势转强", "category": "均线系统", "action_signal": "ADD"},
            "ma_death_cross": {"desc": "均线死叉 - MA5下穿MA20，趋势转弱", "category": "均线系统", "action_signal": "SELL"},
            "bollinger_lower_bounce": {"desc": "布林带下轨反弹 - 价格从下轨回升", "category": "布林带", "action_signal": "BUY"},
            "bollinger_upper_reversal": {"desc": "布林带上轨回落 - 价格从上轨回调", "category": "布林带", "action_signal": "REDUCE"},
            "breakout_high": {"desc": "突破20日新高 - 收盘价创近期高点", "category": "价格突破", "action_signal": "ADD"},
            "breakdown_low": {"desc": "跌破20日新低 - 收盘价破近期低点", "category": "价格突破", "action_signal": "SELL"},
            "position_stop_loss": {"desc": "持仓成本止损 - 浮亏触及持仓类型止损位", "category": "持仓感知", "action_signal": "SELL"},
            "position_take_profit": {"desc": "持仓成本止盈 - 浮盈达到持仓类型止盈位", "category": "持仓感知", "action_signal": "REDUCE"},
            "position_trailing_stop": {"desc": "移动止损 - 从最高盈利回撤超过阈值", "category": "持仓感知", "action_signal": "SELL"},
            "position_cost_pressure": {"desc": "成本压力位 - 价格在成本价附近波动", "category": "持仓感知", "action_signal": "HOLD"},
        }

        return {
            "status": "success",
            "data": {
                "rules": [
                    {"name": r, **rule_descriptions.get(r, {"desc": "", "category": "其他", "action_signal": None})}
                    for r in rules
                ],
                "count": len(rules)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取规则列表失败: {str(e)}")


@router.get("/history")
async def get_alert_history(
    stock_code: Optional[str] = Query(None, description="股票代码"),
    alert_type: Optional[str] = Query(None, description="预警类型"),
    days: int = Query(7, ge=1, le=30, description="查询天数"),
    limit: int = Query(50, ge=1, le=200, description="返回条数")
):
    """获取预警历史（从日志文件读取）"""
    try:
        alerts = []

        if not ALERTS_LOG_DIR.exists():
            return {"status": "success", "data": {"alerts": [], "count": 0}}

        cutoff_date = (datetime.now() - __import__('datetime').timedelta(days=days)).strftime('%Y%m%d')

        for log_file in sorted(ALERTS_LOG_DIR.glob("alerts_*.json"), reverse=True):
            date_str = log_file.stem.replace('alerts_', '')
            if date_str < cutoff_date:
                continue

            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    file_alerts = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            for alert in file_alerts:
                if stock_code and alert.get('stock_code') != stock_code:
                    continue
                if alert_type and alert.get('alert_type') != alert_type:
                    continue
                alerts.append(alert)
                if len(alerts) >= limit:
                    break

            if len(alerts) >= limit:
                break

        return {
            "status": "success",
            "data": {"alerts": alerts[:limit], "count": len(alerts)}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取预警历史失败: {str(e)}")


@router.get("/statistics")
async def get_alert_statistics(
    days: int = Query(7, ge=1, le=30, description="统计天数")
):
    """获取预警统计数据"""
    try:
        stats = {
            "total_alerts": 0,
            "by_level": {},
            "by_type": {},
            "by_stock": {},
            "period_days": days
        }

        if not ALERTS_LOG_DIR.exists():
            return {"status": "success", "data": stats}

        cutoff_date = (datetime.now() - __import__('datetime').timedelta(days=days)).strftime('%Y%m%d')

        for log_file in sorted(ALERTS_LOG_DIR.glob("alerts_*.json")):
            date_str = log_file.stem.replace('alerts_', '')
            if date_str < cutoff_date:
                continue

            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    file_alerts = json.load(f)
            except (json.JSONDecodeError, IOError):
                continue

            for alert in file_alerts:
                stats["total_alerts"] += 1

                level = alert.get('alert_level', 'UNKNOWN')
                stats["by_level"][level] = stats["by_level"].get(level, 0) + 1

                atype = alert.get('alert_type', 'UNKNOWN')
                stats["by_type"][atype] = stats["by_type"].get(atype, 0) + 1

                stock = alert.get('stock_code', 'UNKNOWN')
                if stock not in stats["by_stock"]:
                    stats["by_stock"][stock] = {
                        "stock_name": alert.get('stock_name', ''),
                        "count": 0
                    }
                stats["by_stock"][stock]["count"] += 1

        # 按数量排序
        stats["by_stock"] = dict(
            sorted(stats["by_stock"].items(), key=lambda x: x[1]["count"], reverse=True)
        )

        return {"status": "success", "data": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计数据失败: {str(e)}")


@router.get("/levels")
async def get_alert_levels():
    """获取预警级别说明"""
    levels = [
        {"level": "INFO", "description": "信息", "color": "blue"},
        {"level": "WARNING", "description": "警告", "color": "yellow"},
        {"level": "CRITICAL", "description": "严重", "color": "red"},
        {"level": "EMERGENCY", "description": "紧急", "color": "purple"},
    ]

    return {"status": "success", "data": levels}
