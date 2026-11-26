"""策略回测 API"""
import asyncio
import sys
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from app.core.auth import get_current_user

router = APIRouter(prefix="/backtest", tags=["策略回测"], dependencies=[Depends(get_current_user)])

# 添加skills目录到路径
skills_dir = Path(__file__).parent.parent.parent.parent / "skills"
sys.path.insert(0, str(skills_dir / "strategy-backtest"))

OUTPUT_DIR = skills_dir / "strategy-backtest" / "backtest_output"
VALID_STRATEGIES = ["macd", "kdj", "rsi", "bollinger", "dualma"]


class BacktestRequest(BaseModel):
    """回测请求"""
    stock: str = Field(..., min_length=6, max_length=6, description="6位股票代码")
    strategy: str = Field(..., description="策略名称")
    start_date: str = Field(..., description="开始日期 (YYYY-MM-DD)")
    end_date: str = Field(..., description="结束日期 (YYYY-MM-DD)")
    initial_capital: float = Field(1000000.0, ge=10000, le=100000000, description="初始资金")
    commission_rate: float = Field(0.001, ge=0, le=0.01, description="佣金费率")
    slippage_rate: float = Field(0.001, ge=0, le=0.01, description="滑点费率")
    stamp_tax_rate: float = Field(0.001, ge=0, le=0.01, description="印花税率")
    params: Optional[Dict[str, Any]] = None

    @validator("strategy")
    def validate_strategy(cls, v):
        if v not in VALID_STRATEGIES:
            raise ValueError(f"策略必须是以下之一: {', '.join(VALID_STRATEGIES)}")
        return v

    @validator("start_date", "end_date")
    def validate_date_format(cls, v):
        from datetime import datetime
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式必须是 YYYY-MM-DD")
        return v


class CompareRequest(BaseModel):
    """策略对比请求"""
    stock: str = Field(..., min_length=6, max_length=6, description="6位股票代码")
    strategies: List[str] = Field(..., min_items=2, max_items=5, description="策略列表(至少2个)")
    start_date: str = Field(..., description="开始日期 (YYYY-MM-DD)")
    end_date: str = Field(..., description="结束日期 (YYYY-MM-DD)")
    initial_capital: float = Field(1000000.0, ge=10000, le=100000000, description="初始资金")

    @validator("strategies")
    def validate_strategies(cls, v):
        for s in v:
            if s not in VALID_STRATEGIES:
                raise ValueError(f"策略 '{s}' 无效，必须是以下之一: {', '.join(VALID_STRATEGIES)}")
        return v

    @validator("start_date", "end_date")
    def validate_date_format(cls, v):
        from datetime import datetime
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式必须是 YYYY-MM-DD")
        return v


class BatchBacktestRequest(BaseModel):
    """批量回测请求"""
    stocks: List[str] = Field(..., min_items=1, max_items=50, description="股票代码列表(最多50只)")
    strategy: str = Field(..., description="策略名称")
    start_date: str = Field(..., description="开始日期 (YYYY-MM-DD)")
    end_date: str = Field(..., description="结束日期 (YYYY-MM-DD)")
    initial_capital: float = Field(1000000.0, ge=10000, le=100000000, description="初始资金")

    @validator("strategy")
    def validate_strategy(cls, v):
        if v not in VALID_STRATEGIES:
            raise ValueError(f"策略必须是以下之一: {', '.join(VALID_STRATEGIES)}")
        return v

    @validator("stocks")
    def validate_stocks(cls, v):
        for s in v:
            if len(s) != 6 or not s.isdigit():
                raise ValueError(f"股票代码 '{s}' 无效，必须是6位数字")
        return v

    @validator("start_date", "end_date")
    def validate_date_format(cls, v):
        from datetime import datetime
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式必须是 YYYY-MM-DD")
        return v


class QuickVerifyRequest(BaseModel):
    """快速验证请求（用于智能选股页面内联回测）"""
    stock: str = Field(..., min_length=6, max_length=6, description="6位股票代码")
    strategy: str = Field("macd", description="策略名称，默认MACD")
    days: int = Field(120, ge=30, le=500, description="回测天数（从结束日期往前推）")

    @validator("strategy")
    def validate_strategy(cls, v):
        if v not in VALID_STRATEGIES:
            raise ValueError(f"策略必须是以下之一: {', '.join(VALID_STRATEGIES)}")
        return v


@router.post("/run")
async def run_backtest(request: BacktestRequest):
    """运行策略回测"""
    try:
        from strategy_backtest import StrategyBacktester, BacktestEngine

        backtester = StrategyBacktester()
        backtester.engine = BacktestEngine(
            initial_capital=request.initial_capital,
            commission_rate=request.commission_rate,
            slippage_rate=request.slippage_rate,
            stamp_tax_rate=request.stamp_tax_rate
        )
        result = backtester.backtest(
            stock_code=request.stock,
            strategy_name=request.strategy,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            params=request.params
        )

        benchmark_return = _calculate_buy_and_hold(result.equity_curve)

        return {
            "status": "success",
            "message": "回测完成",
            "data": {
                "strategy": result.strategy_name,
                "period": f"{result.start_date} ~ {result.end_date}",
                "initial_capital": result.initial_capital,
                "final_capital": result.final_capital,
                "total_return": f"{result.total_return:.2%}",
                "annual_return": f"{result.annual_return:.2%}",
                "sharpe_ratio": f"{result.sharpe_ratio:.2f}",
                "sortino_ratio": f"{result.sortino_ratio:.2f}",
                "calmar_ratio": f"{result.calmar_ratio:.2f}",
                "max_drawdown": f"{result.max_drawdown:.2%}",
                "max_drawdown_duration": result.max_drawdown_duration,
                "volatility": f"{result.volatility:.2%}",
                "win_rate": f"{result.win_rate:.2%}",
                "profit_factor": f"{result.profit_factor:.2f}",
                "total_trades": result.total_trades,
                "avg_holding_days": result.avg_holding_days,
                "monthly_returns": result.monthly_returns,
                "equity_curve": result.equity_curve,
                "trades": result.trades,
                "benchmark_return": benchmark_return,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回测失败: {str(e)}")


@router.post("/compare")
async def compare_strategies(request: CompareRequest):
    """对比多个策略"""
    try:
        from strategy_backtest import StrategyBacktester

        backtester = StrategyBacktester()
        results = backtester.compare(
            stock_code=request.stock,
            strategy_names=request.strategies,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital
        )

        comparison = []
        for result in results:
            comparison.append({
                "strategy": result.strategy_name,
                "total_return_pct": round(result.total_return * 100, 2),
                "annual_return_pct": round(result.annual_return * 100, 2),
                "sharpe_ratio": round(result.sharpe_ratio, 2),
                "max_drawdown_pct": round(result.max_drawdown * 100, 2),
                "win_rate_pct": round(result.win_rate * 100, 2),
                "profit_factor": round(result.profit_factor, 2),
                "total_trades": result.total_trades,
            })

        return {
            "status": "success",
            "message": "策略对比完成",
            "data": comparison
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"策略对比失败: {str(e)}")


@router.post("/batch")
async def batch_backtest(request: BatchBacktestRequest):
    """批量回测 — 对多只股票用同一策略跑回测，返回排行榜"""
    try:
        from strategy_backtest import StrategyBacktester, BacktestEngine

        results = []
        failed = []

        for stock_code in request.stocks:
            try:
                backtester = StrategyBacktester()
                backtester.engine = BacktestEngine(
                    initial_capital=request.initial_capital,
                    commission_rate=0.001,
                    slippage_rate=0.001,
                    stamp_tax_rate=0.001
                )
                result = backtester.backtest(
                    stock_code=stock_code,
                    strategy_name=request.strategy,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    initial_capital=request.initial_capital
                )

                results.append({
                    "stock": stock_code,
                    "strategy": result.strategy_name,
                    "total_return_pct": round(result.total_return * 100, 2),
                    "annual_return_pct": round(result.annual_return * 100, 2),
                    "sharpe_ratio": round(result.sharpe_ratio, 2),
                    "max_drawdown_pct": round(result.max_drawdown * 100, 2),
                    "win_rate_pct": round(result.win_rate * 100, 2),
                    "profit_factor": round(result.profit_factor, 2),
                    "total_trades": result.total_trades,
                    "final_capital": result.final_capital,
                })
            except Exception as e:
                failed.append({"stock": stock_code, "error": str(e)})

        results.sort(key=lambda x: x["total_return_pct"], reverse=True)

        return {
            "status": "success",
            "message": f"批量回测完成，成功 {len(results)} 只，失败 {len(failed)} 只",
            "data": {
                "strategy": request.strategy,
                "period": f"{request.start_date} ~ {request.end_date}",
                "total_stocks": len(request.stocks),
                "success_count": len(results),
                "failed_count": len(failed),
                "results": results,
                "failed": failed,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量回测失败: {str(e)}")


@router.post("/verify")
async def quick_verify(request: QuickVerifyRequest):
    """快速验证 — 智能选股页面内联使用，对单只股票跑短期回测返回关键指标"""
    try:
        import logging
        from datetime import datetime, timedelta
        from strategy_backtest import StrategyBacktester, BacktestEngine

        logger = logging.getLogger(__name__)
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=request.days)).strftime("%Y-%m-%d")

        backtester = StrategyBacktester()
        backtester.engine = BacktestEngine(
            initial_capital=1000000.0,
            commission_rate=0.001,
            slippage_rate=0.001,
            stamp_tax_rate=0.001
        )
        result = backtester.backtest(
            stock_code=request.stock,
            strategy_name=request.strategy,
            start_date=start_date,
            end_date=end_date,
            initial_capital=1000000.0
        )

        score = _calculate_composite_score(result)
        logger.info(f"[verify] {request.stock}: 交易{result.total_trades}次, 胜率{result.win_rate:.2%}, 盈亏比{result.profit_factor:.2f}, 评分={score}")

        return {
            "status": "success",
            "data": {
                "stock": request.stock,
                "strategy": result.strategy_name,
                "period_days": request.days,
                "total_return_pct": round(result.total_return * 100, 2),
                "annual_return_pct": round(result.annual_return * 100, 2),
                "sharpe_ratio": round(result.sharpe_ratio, 2),
                "max_drawdown_pct": round(result.max_drawdown * 100, 2),
                "win_rate_pct": round(result.win_rate * 100, 2),
                "profit_factor": round(result.profit_factor, 2),
                "total_trades": result.total_trades,
                "composite_score": score,
                "rating": _score_to_rating(score),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"快速验证失败: {str(e)}")


@router.get("/strategies")
async def list_strategies():
    """列出可用策略"""
    try:
        from strategy_backtest import StrategyManager

        strategies = StrategyManager.list_strategies()

        strategy_info = {
            "macd": {"name": "MACD", "desc": "MACD金叉/死叉策略"},
            "kdj": {"name": "KDJ", "desc": "KDJ超买/超卖策略"},
            "rsi": {"name": "RSI", "desc": "RSI超买/超卖策略"},
            "bollinger": {"name": "布林带", "desc": "布林带突破/回归策略"},
            "dualma": {"name": "双均线", "desc": "双均线金叉/死叉策略"},
        }

        return {
            "status": "success",
            "data": {
                "strategies": [
                    {"key": s, **strategy_info.get(s, {})} for s in strategies
                ],
                "count": len(strategies)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取策略列表失败: {str(e)}")


@router.get("/reports")
async def list_reports():
    """列出回测报告"""
    if not OUTPUT_DIR.exists():
        return {"status": "success", "data": {"reports": [], "count": 0}}

    reports = []
    for f in OUTPUT_DIR.glob("backtest_report_*.json"):
        reports.append({
            "filename": f.name,
            "modified": f.stat().st_mtime,
            "size": f.stat().st_size
        })

    reports.sort(key=lambda x: x["modified"], reverse=True)

    return {
        "status": "success",
        "data": {"reports": reports[:20], "count": len(reports)}
    }


def _calculate_buy_and_hold(equity_curve: List[Dict]) -> str:
    """计算买入持有基准收益率 — 从持仓日提取首尾价格"""
    if not equity_curve or len(equity_curve) < 2:
        return "0.00%"
    # 找出有持仓的日期，提取价格 = market_value / shares
    prices = []
    for entry in equity_curve:
        shares = entry.get("shares", 0)
        mv = entry.get("market_value", 0)
        if shares > 0 and mv > 0:
            prices.append(mv / shares)
    if len(prices) < 2:
        return "--"
    first_price = prices[0]
    last_price = prices[-1]
    if first_price <= 0:
        return "0.00%"
    return f"{(last_price - first_price) / first_price:.2%}"


def _calculate_composite_score(result) -> int:
    """计算综合评分 (0-100)，用于智能选股页面展示

    加权组合：夏普比率35%% + 胜率25%% + 盈亏比20%% + 回撤控制20%%
    """
    sharpe_score = max(0, min(35, ((result.sharpe_ratio + 1) / 4) * 35))
    win_score = max(0, min(25, ((result.win_rate - 0.4) / 0.3) * 25))
    pf_score = max(0, min(20, ((result.profit_factor - 0.5) / 1.5) * 20))
    dd_score = max(0, min(20, ((0.3 - result.max_drawdown) / 0.25) * 20))
    return round(sharpe_score + win_score + pf_score + dd_score)


def _score_to_rating(score: int) -> str:
    """评分转评级"""
    if score >= 80:
        return "优秀"
    elif score >= 65:
        return "良好"
    elif score >= 50:
        return "一般"
    else:
        return "较差"
