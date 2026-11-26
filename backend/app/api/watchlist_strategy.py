"""自选股AI策略API路由 - 仅管理员可用"""
import json
from datetime import datetime
from fastapi import APIRouter, Query, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_admin
from app.models.user import User
from app.models.watchlist_strategy import WatchlistStrategyDecision, WatchlistStrategyConfig


router = APIRouter()


class StrategyConfigRequest(BaseModel):
    intraday_times: Optional[list] = None
    midday_times: Optional[list] = None
    closing_times: Optional[list] = None
    is_enabled: Optional[bool] = None


class GenerateStrategyRequest(BaseModel):
    mode: Optional[str] = None  # intraday/midday/closing，None则自动判断


class FeedbackRequest(BaseModel):
    suggestion_type: str  # "holdings" 或 "watchlist"
    code: str
    adopted: Optional[bool] = None  # True=采纳, False=不采纳, None=取消标记
    note: Optional[str] = None  # 可选备注


@router.post("/generate")
def generate_strategy(
    request: Optional[GenerateStrategyRequest] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """手动生成AI策略（仅管理员）

    mode 可选值:
    - intraday: 盘中策略（自动判断上午 morning / 下午 afternoon）
    - midday: 午间策略
    - closing: 收盘策略
    - morning/afternoon: 直接指定具体盘中模式
    - None: 自动判断
    """
    from app.services.watchlist_strategy_generator import WatchlistAIStrategyGenerator

    mode = request.mode if request else None

    result = WatchlistAIStrategyGenerator.generate_strategy(
        db=db,
        user_id=current_admin.id,
        mode=mode,
        source="manual",
    )

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result.get("error", "策略生成失败"))

    return result


@router.get("/history")
def get_strategy_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """获取策略历史（按日期倒序，仅管理员）"""
    query = db.query(WatchlistStrategyDecision)

    # 管理员可以查看指定用户或所有用户的策略
    if user_id:
        query = query.filter(WatchlistStrategyDecision.user_id == user_id)

    total = query.count()
    strategies = query.order_by(
        WatchlistStrategyDecision.decision_date.desc(),
        WatchlistStrategyDecision.decision_time.desc(),
    ).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "strategies": [_format_strategy(s) for s in strategies],
    }


@router.get("/latest")
def get_latest_strategy(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """获取最新策略（仅管理员）"""
    strategy = db.query(WatchlistStrategyDecision).filter(
        WatchlistStrategyDecision.user_id == current_admin.id,
        WatchlistStrategyDecision.status == "active",
    ).order_by(
        WatchlistStrategyDecision.decision_date.desc(),
        WatchlistStrategyDecision.decision_time.desc(),
    ).first()

    if not strategy:
        return {"strategy": None}

    return {"strategy": _format_strategy_detail(strategy)}


@router.get("/detail/{strategy_id}")
def get_strategy_detail(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """获取策略详情（仅管理员）"""
    strategy = db.query(WatchlistStrategyDecision).filter(
        WatchlistStrategyDecision.id == strategy_id,
    ).first()

    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")

    return {"strategy": _format_strategy_detail(strategy)}


@router.delete("/{strategy_id}")
def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """删除策略记录（仅管理员）"""
    strategy = db.query(WatchlistStrategyDecision).filter(
        WatchlistStrategyDecision.id == strategy_id,
    ).first()

    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")

    db.delete(strategy)
    db.commit()

    return {"success": True}


@router.put("/{strategy_id}/feedback")
def update_strategy_feedback(
    strategy_id: int,
    request: FeedbackRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """更新建议项的采纳状态（仅管理员）

    用于记录用户对 AI 建议的采纳反馈，反哺历史策略表现统计
    """
    strategy = db.query(WatchlistStrategyDecision).filter(
        WatchlistStrategyDecision.id == strategy_id,
    ).first()

    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")

    if request.suggestion_type not in ("holdings", "watchlist"):
        raise HTTPException(status_code=400, detail="suggestion_type 必须为 holdings 或 watchlist")

    # 解析对应建议列表
    field = "holdings_suggestions" if request.suggestion_type == "holdings" else "watchlist_suggestions"
    suggestions = _parse_json_field(getattr(strategy, field), [])

    # 查找匹配的建议项并更新 adopted 字段
    updated = False
    for item in suggestions:
        if isinstance(item, dict) and str(item.get("code", "")).strip() == request.code.strip():
            if request.adopted is None:
                item.pop("adopted", None)
                if request.note:
                    item.pop("feedback_note", None)
            else:
                item["adopted"] = request.adopted
                if request.note:
                    item["feedback_note"] = request.note
            updated = True
            break

    if not updated:
        raise HTTPException(status_code=404, detail=f"未找到代码为 {request.code} 的建议项")

    # 写回数据库
    setattr(strategy, field, json.dumps(suggestions, ensure_ascii=False))
    db.commit()

    return {"success": True, "updated_count": 1}


def _parse_time_list(text):
    """解析时间JSON列表"""
    if not text:
        return []
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []


def _validate_times(times):
    """验证时间格式列表"""
    for time_str in times:
        try:
            hour, minute = time_str.split(":")
            if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的时间格式: {time_str}")


@router.get("/config")
def get_strategy_config(
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """获取策略配置（仅管理员）"""
    config = db.query(WatchlistStrategyConfig).filter(
        WatchlistStrategyConfig.user_id == current_admin.id,
    ).first()

    if not config:
        config = WatchlistStrategyConfig(user_id=current_admin.id)
        db.add(config)
        db.commit()
        db.refresh(config)

    # 迁移旧数据：如果新字段为空但旧字段有值，迁移过来
    if (not config.intraday_times or config.intraday_times == '[]') and config.schedule_times:
        old_times = _parse_time_list(config.schedule_times)
        if old_times:
            config.intraday_times = json.dumps([t for t in old_times if t in ("10:25", "14:10")], ensure_ascii=False)
            config.midday_times = json.dumps([t for t in old_times if t in ("12:30",)], ensure_ascii=False)
            config.closing_times = json.dumps([t for t in old_times if t in ("16:00",)], ensure_ascii=False)
            db.commit()
            db.refresh(config)

    return {
        "config": {
            "id": config.id,
            "intraday_times": _parse_time_list(config.intraday_times),
            "midday_times": _parse_time_list(config.midday_times),
            "closing_times": _parse_time_list(config.closing_times),
            "is_enabled": config.is_enabled,
        }
    }


@router.put("/config")
def update_strategy_config(
    request: StrategyConfigRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """更新策略配置（仅管理员）"""
    config = db.query(WatchlistStrategyConfig).filter(
        WatchlistStrategyConfig.user_id == current_admin.id,
    ).first()

    if not config:
        config = WatchlistStrategyConfig(user_id=current_admin.id)
        db.add(config)

    if request.intraday_times is not None:
        _validate_times(request.intraday_times)
        config.intraday_times = json.dumps(request.intraday_times, ensure_ascii=False)

    if request.midday_times is not None:
        _validate_times(request.midday_times)
        config.midday_times = json.dumps(request.midday_times, ensure_ascii=False)

    if request.closing_times is not None:
        _validate_times(request.closing_times)
        config.closing_times = json.dumps(request.closing_times, ensure_ascii=False)

    if request.is_enabled is not None:
        config.is_enabled = request.is_enabled

    db.commit()
    db.refresh(config)

    return {
        "success": True,
        "config": {
            "id": config.id,
            "intraday_times": _parse_time_list(config.intraday_times),
            "midday_times": _parse_time_list(config.midday_times),
            "closing_times": _parse_time_list(config.closing_times),
            "is_enabled": config.is_enabled,
        },
    }


def _parse_json_field(text, default):
    """安全解析 JSON 字段"""
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def _format_strategy(strategy: WatchlistStrategyDecision) -> dict:
    """格式化策略列表数据"""
    return {
        "id": strategy.id,
        "user_id": strategy.user_id,
        "decision_date": strategy.decision_date,
        "decision_time": strategy.decision_time,
        "strategy_mode": strategy.strategy_mode,
        "market_sentiment": strategy.market_sentiment,
        "market_stage": strategy.market_stage,
        "position_ratio": strategy.position_ratio,
        "market_analysis": strategy.market_analysis[:100] + "..." if strategy.market_analysis and len(strategy.market_analysis) > 100 else strategy.market_analysis,
        "status": strategy.status,
        "created_at": strategy.created_at.strftime("%Y-%m-%d %H:%M:%S") if strategy.created_at else None,
    }


def _format_strategy_detail(strategy: WatchlistStrategyDecision) -> dict:
    """格式化策略详情数据"""
    return {
        "id": strategy.id,
        "user_id": strategy.user_id,
        "decision_date": strategy.decision_date,
        "decision_time": strategy.decision_time,
        "strategy_mode": strategy.strategy_mode,
        "market_sentiment": strategy.market_sentiment,
        "market_analysis": strategy.market_analysis,
        "position_analysis": strategy.position_analysis,
        "holdings_suggestions": _parse_json_field(strategy.holdings_suggestions, []),
        "watchlist_suggestions": _parse_json_field(strategy.watchlist_suggestions, []),
        # 新增字段
        "position_ratio": strategy.position_ratio,
        "dynamic_max_position": strategy.dynamic_max_position,
        "suggested_allocation": _parse_json_field(strategy.suggested_allocation, {}),
        "market_stage": strategy.market_stage,
        "market_indicators": _parse_json_field(strategy.market_indicators, {}),
        # 元信息
        "ai_analysis": strategy.ai_analysis,
        "risk_warning": strategy.risk_warning,
        "status": strategy.status,
        "created_at": strategy.created_at.strftime("%Y-%m-%d %H:%M:%S") if strategy.created_at else None,
    }
