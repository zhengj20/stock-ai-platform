"""AI策略生成器 - 基于实时行情和资金管理的智能交易

两种模式：
1. generate_strategy (盘中即时): 9:30-15:00 调用，使用实时行情，立即执行
2. generate_next_day_strategy (收盘次日): 15:10 调用，使用收盘数据，生成明日计划
"""
import json
import asyncio
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
import logging

from app.models.sim_trading import SimAccount, SimPosition, AIStrategyDecision
from app.services.trade_engine import TradeEngine

log = logging.getLogger(__name__)


def _is_st_or_delisting(name: str) -> bool:
    """判断是否为 ST/*ST/退市风险股

    - 前缀 ST/*ST：风险警示股
    - 含"退"字：退市整理期或退市风险警示股
    """
    if not name:
        return False
    n = name.strip()
    if n.startswith("ST") or n.startswith("*ST"):
        return True
    if "退" in n:
        return True
    return False


class AIStrategyGenerator:
    """AI策略生成器"""

    DEFAULT_CONFIG = {
        "max_single_position_ratio": 0.20,   # 单只最大20%
        "total_position_ratio": 0.80,        # 总仓位最高80%
        "stop_loss_ratio": 8,                # 止损8%
        "take_profit_ratio": 15,             # 止盈15%
        "min_buy_amount": 5000,              # 最小买入金额
        "enforce_params": False,             # True=按参数严格限制；False=AI自主决定
    }

    # ── 公共基础规则（3 个策略模式共享）────────────────────
    _COMMON_RULES = """## 通用决策规则
1. **数量必须是 100 的整数倍**（A股一手）
2. **资金约束**：实际可用于新委托的资金 = 可用资金 - 冻结资金（限价单占用）。buy_list 的总金额不得超过"实际可用资金"，且必须留有合理现金缓冲
3. **风控声明**：止损止盈由风控系统自动执行，按持仓周期差异化（短线止损5%/止盈8%/持仓5天；中线止损10%/止盈20%/持仓30天；长线止损15%/止盈40%/持仓90天），'sell_list' 仅用于标记需要 AI 主动减仓的持仓，风控触发的卖出不需要在此列出
4. **未成交委托处理**：下方"当前未成交委托"块列出所有 pending/partial 委托（买卖双向，含距市价距离、委托理由、过期时间），请逐一判断：①保留 → 不必在 buy_list/sell_list 重复列出；②改价 → 在对应列表中重新出价并写明理由；③放弃 → 不列出，系统会在新策略执行前自动清空所有旧委托（买卖双向）。不要仅凭"已有未成交"就盲目添加相同标的
5. 参考近期经验教训（如有），避免重复犯错
6. **做T策略**：在"持仓日内振幅"块中，has_t_opportunity=true 的持仓存在做T机会。将需要做T的股票放入 t_trade_list（仅填 code 和 name），系统会自动执行先卖后买的做T操作，做T记录会写入做T表。做T利用已有底仓的日内波动套利，底仓总数量不变但可降低成本

## 持仓周期配置（必须严格遵守，每笔买入必须标注 position_type）
账户持仓分为三个周期，buy_list 每项必须新增 "position_type" 字段（值: short/mid/long）：
- **短线（short）**：持仓 1-5 个交易日，止损 5%，止盈 8-15%，单只仓位 ≤ 10%
  适用：资金流入龙头、放量突破、龙虎榜活跃标的、热点题材
  决策要点：快进快出，不恋战；达到 8% 即可分批止盈，跌破 5% 果断止损
- **中线（mid）**：持仓 5-30 个交易日，止损 10%，止盈 20-40%，单只仓位 ≤ 15%
  适用：板块轮动、业绩预期、技术面突破回踩、北向持续流入
  决策要点：耐心持有，不因短期波动操作；浮盈 20% 后启动移动止盈
- **长线（long）**：持仓 30-90 个交易日，止损 15%，止盈 40-100%，单只仓位 ≤ 20%
  适用：基本面优秀、低估值、行业龙头、政策长期利好
  决策要点：忽略短期波动，聚焦基本面变化；只有基本面恶化或达 40% 以上盈利才考虑退出

## 投资布局建议（AI 自主决策参考，需根据下方"动态仓位配置"调整）
- **金字塔建仓**：对已持有的盈利标的可加仓，加仓数量 ≤ 底仓 1/3，且必须在浮盈时加仓（浮亏不加仓）
- **板块分散**：单一行业集中度不得超过 30%，新买入若导致某行业超限请放弃或减少数量
- **避免追高**：涨幅已超过 6% 的标的一般不追入；候选中优先选择 source=oversold/low_absorption/multi_factor 的反向机会
- **避免杀跌**：浮亏但基本面未恶化的中线/长线持仓不要急于止损，给市场修复时间
- **现金为王**：保留至少 20-40% 现金仓位（按市场情绪调整），用于应对突发机会和风险"""

    _COMMON_OUTPUT_FORMAT = """## 输出格式（纯 JSON，不要其他文字，不要 markdown 标记）
{
  "market_sentiment": "bullish/bearish/neutral",
  "market_analysis": "...",
  "position_ratio": 0-100,
  "buy_list": [
    {"code": "6位代码", "name": "名称", "price": 价格, "quantity": 数量, "position_type": "short/mid/long", "reason": "理由（含周期选择依据）"}
  ],
  "sell_list": [
    {"code": "6位代码", "name": "名称", "reason": "理由"}
  ],
  "t_trade_list": [
    {"code": "6位代码", "name": "名称", "reason": "做T理由"}
  ],
  "risk_warning": "风险提示（30字内）"
}"""

    # ── 盘中即时策略提示词 ────────────────────────────────
    INTRADAY_SYSTEM_PROMPT = """你是A股量化交易操盘手。基于实时行情和账户状态，输出**今日立即执行**的交易策略。

## 模式专属规则
1. 买入：选择有资金流入、涨幅适中(0-8%)、成交额充足的股票
2. 卖出：趋势转弱、基本面恶化的持仓考虑减仓
3. 仓位控制：单只不超过总资产 20%，总仓位不超 80%
4. 关注下方"今日成交"块，避免当日重复加仓同一标的
5. 买入为**限价委托**（按策略价格挂单，达到后自动成交），而非市价单

""" + _COMMON_RULES + """

"market_analysis" 字段请填写：一句话分析当前市场情绪和趋势

""" + _COMMON_OUTPUT_FORMAT

    # ── 收盘次日策略提示词 ────────────────────────────────
    NEXT_DAY_SYSTEM_PROMPT = """你是A股量化交易操盘手。基于今日收盘数据、持仓盈亏、龙虎榜、板块轮动和市场走势，输出**明日交易计划**。

## 模式专属规则
1. 复盘今日持仓：亏损股票分析原因（趋势走弱则减仓），盈利股票判断是否继续持有
2. 明日买入：结合龙虎榜资金动向、板块轮动方向和资金流向，选择明日有上涨潜力的标的
3. 卖出：趋势转弱、基本面恶化的持仓考虑减仓
4. 仓位控制：单只不超过总资产 20%，总仓位不超 80%
5. 参考持仓风控信息（止损位/持仓天数），接近止损位的持仓优先考虑减仓
6. 买入价格用**今日收盘价**作为基准，挂单后次日盘中按规则成交

""" + _COMMON_RULES + """

"market_analysis" 字段请填写：今日市场复盘 + 明日走势预判

""" + _COMMON_OUTPUT_FORMAT

    # ── 午间策略调整提示词 ────────────────────────────────
    MIDDAY_SYSTEM_PROMPT = """你是A股量化交易操盘手。现在是午间休盘（11:30-13:00），请基于上午AI策略执行效果、实际成交记录和市场走势，**调整下午的交易策略**。

## 模式专属规则
1. 上午复盘：回顾上午已执行的交易效果（盈亏情况），判断方向是否正确
2. 上午策略评估：比较"上午AI策略决策"中的买入/卖出计划与实际成交记录，判断哪些决策正确执行、哪些因价格等原因未成交、哪些需要调整
3. 持仓评估：结合上午涨跌和持仓风控信息（止损位/持仓天数），重新评估每只持仓的持有价值
4. 下午调整：上午走势与预期不符的，果断调整买卖计划；上午策略中未成交的标的，重新评估是否继续买入
5. 卖出：趋势转弱、基本面恶化的持仓考虑减仓
6. 仓位控制：单只不超过总资产 20%，总仓位不超 80%
7. 买入为**限价委托**（按策略价格挂单，下午达到后自动成交）

""" + _COMMON_RULES + """

"market_analysis" 字段请填写：上午走势总结 + 下午预判

""" + _COMMON_OUTPUT_FORMAT

    @staticmethod
    def is_trading_time() -> bool:
        """检查是否在交易时段（9:30-11:30, 13:00-15:00，自动排除周末/节假日）"""
        from app.core.trading_calendar import is_trading_hours
        return is_trading_hours()

    @staticmethod
    def _get_next_trade_date() -> str:
        """获取下一个交易日（YYYY-MM-DD），用于标记次日策略的执行日期。

        从 trading_calendar 获取历史交易日集合，找到今天之后的第一个交易日。
        """
        from app.core.trading_calendar import _load_historical_trading_dates, _hist_trading_dates

        today = date.today()
        _load_historical_trading_dates()

        # 从今天+1天开始查找
        d = today + timedelta(days=1)
        for _ in range(10):
            date_str = d.strftime("%Y-%m-%d")
            if date_str in _hist_trading_dates:
                return date_str
            d += timedelta(days=1)

        # 兜底：历史缓存中没有，从今天+1重新开始，至少跳过周末
        d = today + timedelta(days=1)
        for _ in range(10):
            if d.weekday() < 5:
                return d.strftime("%Y-%m-%d")
            d += timedelta(days=1)
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    @staticmethod
    def _get_realtime_quotes(codes: List[str]) -> Dict[str, Dict]:
        """获取实时行情"""
        if not codes:
            return {}
        try:
            from app.core.data_sources import TencentSource
            ts = TencentSource()
            return ts.get_quotes(codes)
        except Exception as e:
            log.warning(f"获取实时行情失败: {e}")
            return {}
    
    @staticmethod
    def _get_market_overview() -> Dict:
        """获取市场概况"""
        data = {"indices": {}, "breadth": {}, "sentiment": "neutral"}
        try:
            from app.services.market_service import MarketService
            ms = MarketService()
            sentiment = ms.get_market_sentiment(include_flow=False)
            if sentiment:
                data["indices"] = sentiment.get("indices", {})
                breadth = sentiment.get("breadth", {})
                data["breadth"] = breadth
                total = breadth.get("total", 1)
                up = breadth.get("up", 0)
                if total > 0:
                    ratio = up / total
                    if ratio > 0.6:
                        data["sentiment"] = "bullish"
                    elif ratio < 0.4:
                        data["sentiment"] = "bearish"
                    else:
                        data["sentiment"] = "neutral"
        except Exception as e:
            log.warning(f"获取市场数据失败: {e}")
        return data
    
    @staticmethod
    def _get_market_extra() -> Dict:
        """获取板块排名和北向资金摘要（用于 prompt 注入）"""
        result = {"sectors": [], "northbound": ""}
        try:
            from app.services.market_service import MarketService
            ms = MarketService()
            # 板块排名 top 5（概念板块）
            sectors_data = ms.get_sectors(sector_type='concept', top=5)
            if sectors_data and sectors_data.get('sectors'):
                result["sectors"] = sectors_data["sectors"]
        except Exception as e:
            log.warning(f"获取板块排名失败: {e}")
        try:
            from app.services.market_service import MarketService
            ms = MarketService()
            nb = ms.get_northbound_flow()
            if nb and nb.get('summary'):
                s = nb['summary']
                hgt = s.get('hgt_latest', 0) or 0
                sgt = s.get('sgt_latest', 0) or 0
                total = hgt + sgt
                direction = "流入" if total > 0 else "流出"
                result["northbound"] = f"北向资金: {direction}{abs(total):.1f}亿 (沪股通{hgt:+.1f}亿 深股通{sgt:+.1f}亿)"
        except Exception as e:
            log.warning(f"获取北向资金失败: {e}")
        return result

    @staticmethod
    def _get_account_info(db: Session, account_id: int) -> Dict:
        """获取账户信息（含冻结资金和待成交委托）"""
        from sqlalchemy import and_
        from app.models.sim_trading import SimOrder

        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        if not account:
            return {}
        
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()
        
        # 获取持仓实时价格
        pos_codes = [p.stock_code for p in positions]
        quotes = AIStrategyGenerator._get_realtime_quotes(pos_codes) if pos_codes else {}
        
        total_market_value = 0
        position_list = []
        for p in positions:
            current_price = p.current_price
            if p.stock_code in quotes:
                current_price = quotes[p.stock_code].get("price", p.current_price)
            market_value = p.total_quantity * current_price
            profit_ratio = (current_price / p.cost_price - 1) * 100 if p.cost_price > 0 else 0
            total_market_value += market_value
            position_list.append({
                "code": p.stock_code,
                "name": p.stock_name,
                "quantity": p.total_quantity,
                "available": p.available_quantity,
                "cost_price": p.cost_price,
                "current_price": current_price,
                "market_value": market_value,
                "profit_ratio": round(profit_ratio, 2),
                "position_type": p.position_type,
                "buy_date": p.buy_date
            })

        # 查询待成交委托单（限价买单占用资金）
        pending_orders = db.query(SimOrder).filter(
            and_(
                SimOrder.account_id == account_id,
                SimOrder.status.in_(["pending", "partial"]),
            )
        ).all()

        pending_buy_list = []
        pending_frozen = 0.0
        for o in pending_orders:
            if o.order_type == "buy":
                frozen = o.order_price * (o.order_quantity - (o.filled_quantity or 0))
                pending_frozen += frozen
                pending_buy_list.append({
                    "code": o.stock_code,
                    "name": o.stock_name,
                    "price": o.order_price,
                    "quantity": o.order_quantity,
                    "frozen_amount": round(frozen, 2),
                })

        frozen_capital = max(0, account.frozen_capital or 0.0)
        real_available = account.current_capital

        return {
            "initial_capital": account.initial_capital,
            "current_capital": account.current_capital,
            "frozen_capital": round(frozen_capital, 2),
            "real_available": round(real_available, 2),
            "total_assets": account.current_capital + frozen_capital + total_market_value,
            "market_value": total_market_value,
            "position_ratio": round(total_market_value / (account.current_capital + frozen_capital + total_market_value) * 100, 1) if (account.current_capital + frozen_capital + total_market_value) > 0 else 0,
            "positions": position_list,
            "pending_buys": pending_buy_list,
            "pending_buy_frozen": round(pending_frozen, 2),
        }

    @staticmethod
    def _get_pending_orders_detail(db: Session, account_id: int) -> List[Dict]:
        """拉取所有 pending/partial 委托（买+卖）完整明细，供 AI 决策

        返回结构包含 order_id, type(buy/sell), code, name, price, quantity,
        filled, current_price, distance_pct, strategy_name, strategy_reason, expire_time
        """
        from sqlalchemy import and_
        from app.models.sim_trading import SimOrder
        orders = db.query(SimOrder).filter(
            and_(
                SimOrder.account_id == account_id,
                SimOrder.status.in_(["pending", "partial"]),
            )
        ).all()
        if not orders:
            return []

        codes = list({o.stock_code for o in orders})
        quotes: dict = {}
        try:
            quotes = AIStrategyGenerator._get_realtime_quotes(codes) or {}
        except Exception as e:
            log.debug(f"获取未成交委托实时行情失败: {e}")

        out = []
        for o in orders:
            cur_data = quotes.get(o.stock_code) or {}
            cur_price = cur_data.get("price") if isinstance(cur_data, dict) else None
            distance = None
            if cur_price and o.order_price:
                distance = round((cur_price / o.order_price - 1) * 100, 2)
            out.append({
                "order_id": o.id,
                "type": o.order_type,
                "code": o.stock_code,
                "name": o.stock_name or "",
                "price": o.order_price,
                "quantity": o.order_quantity,
                "filled": o.filled_quantity or 0,
                "current_price": cur_price,
                "distance_pct": distance,
                "strategy_name": o.strategy_name or "",
                "strategy_reason": o.strategy_reason or "",
                "expire_time": o.expire_time or "15:00:00",
            })
        return out

    @staticmethod
    def _get_hot_stocks() -> List[Dict]:
        """获取多类型候选股票（避免追高偏置）

        候选来源：
        1. capital_flow 资金流入（短线候选）
        2. gainers 涨幅榜前20（短线候选，已过滤ST/涨停）
        3. oversold 超跌反弹（-3%~-8%）（中线候选）
        4. low_absorption 低吸企稳（长线候选）
        5. multi_factor 多因子综合（中线候选）
        """
        candidates = []

        # 方法1：资金流入（短线候选）
        try:
            from app.services.strategy_service import StrategyService
            ss = StrategyService()
            picks = ss.get_capital_flow_picks(top_n=10)
            if picks and picks.get("stocks"):
                for s in picks["stocks"][:10]:
                    candidates.append({
                        "code": s.get("code", ""),
                        "name": s.get("name", ""),
                        "reason": "资金流入",
                        "source": "capital_flow",
                        "suggested_type": "short",
                    })
        except Exception as e:
            log.warning(f"获取资金流向选股失败: {e}")

        # 方法2：涨幅榜前20（短线候选）
        try:
            from app.core.data_sources import TencentSource
            ts = TencentSource()
            market = ts.get_full_market()
            if market:
                # 按涨幅排序取前20
                sorted_stocks = sorted(
                    market,
                    key=lambda x: x.get("change_pct", 0),
                    reverse=True
                )[:20]
                for s in sorted_stocks:
                    if s.get("code") and s.get("change_pct", 0) > 0:
                        candidates.append({
                            "code": s["code"],
                            "name": s.get("name", ""),
                            "reason": f"涨幅{s.get('change_pct', 0):.2f}%",
                            "source": "gainers",
                            "suggested_type": "short",
                        })

                # 方法3：超跌反弹候选（中线机会）：跌幅 -3% ~ -8%，按成交额排序
                try:
                    oversold = [
                        s for s in market
                        if -8 <= s.get("change_pct", 0) <= -3
                        and s.get("amount_wan", 0) > 5000
                    ]
                    oversold.sort(key=lambda x: x.get("amount_wan", 0), reverse=True)
                    for s in oversold[:10]:
                        candidates.append({
                            "code": s["code"],
                            "name": s.get("name", ""),
                            "reason": f"超跌{s.get('change_pct', 0):.2f}%",
                            "source": "oversold",
                            "suggested_type": "mid",
                        })
                except Exception as e:
                    log.warning(f"获取超跌候选失败: {e}")
        except Exception as e:
            log.warning(f"获取涨幅榜失败: {e}")

        # 方法4：低吸企稳（长线候选）
        try:
            from app.services.strategy_service import StrategyService
            ss = StrategyService()
            if hasattr(ss, "get_low_absorption_picks"):
                low_picks = ss.get_low_absorption_picks(top_n=8)
                if low_picks and low_picks.get("stocks"):
                    for s in low_picks["stocks"][:8]:
                        candidates.append({
                            "code": s.get("code", ""),
                            "name": s.get("name", ""),
                            "reason": "低吸企稳",
                            "source": "low_absorption",
                            "suggested_type": "long",
                        })
        except Exception as e:
            log.warning(f"获取低吸候选失败: {e}")

        # 方法5：多因子综合（中线候选）
        try:
            from app.services.strategy_service import StrategyService
            ss = StrategyService()
            if hasattr(ss, "get_multi_factor_picks"):
                multi = ss.get_multi_factor_picks(top_n=8, exclude_st=True)
                if multi and multi.get("stocks"):
                    for s in multi["stocks"][:8]:
                        candidates.append({
                            "code": s.get("code", ""),
                            "name": s.get("name", ""),
                            "reason": "多因子综合",
                            "source": "multi_factor",
                            "suggested_type": "mid",
                        })
        except Exception as e:
            log.warning(f"获取多因子候选失败: {e}")

        # 去重：多源命中标记为高置信度
        seen: Dict[str, Dict] = {}
        for c in candidates:
            code = c.get("code", "")
            if not code:
                continue
            # 过滤 ST/*ST/退市风险股（避免追入退市整理期或风险警示股）
            name = c.get("name", "") or ""
            if _is_st_or_delisting(name):
                continue
            if code not in seen:
                seen[code] = c
            else:
                # 多源命中，追加理由并提升置信度
                seen[code]["reason"] = f"{seen[code]['reason']}+{c['reason']}"
                seen[code]["source"] = f"{seen[code]['source']}+{c['source']}"
                seen[code]["confidence"] = seen[code].get("confidence", 1) + 1

        # 按置信度降序，再按 reason 长度降序
        unique = sorted(
            seen.values(),
            key=lambda x: (x.get("confidence", 1), len(x.get("reason", ""))),
            reverse=True
        )

        # 扩大候选池到25个（原15个），保证多样化
        return unique[:25]

    
    @staticmethod
    def _get_ma_position(codes: List[str]) -> Dict[str, Dict]:
        """获取候选股票的均线位置（轻量版，仅 MA5/MA10/MA20）"""
        if not codes:
            return {}
        result = {}
        try:
            from app.core.pytdx_source import pytdx_data
            for code in codes:
                try:
                    klines = pytdx_data.get_kline(code, period=6, count=25)
                    if klines and len(klines) >= 20:
                        closes = [k['close'] for k in klines]
                        current = closes[-1]
                        ma5 = sum(closes[-5:]) / 5
                        ma10 = sum(closes[-10:]) / 10
                        ma20 = sum(closes[-20:]) / 20
                        result[code] = {
                            "ma5": round(ma5, 2),
                            "ma10": round(ma10, 2),
                            "ma20": round(ma20, 2),
                            "vs_ma5": round((current / ma5 - 1) * 100, 1),
                            "vs_ma20": round((current / ma20 - 1) * 100, 1),
                        }
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"获取MA均线位置失败: {e}")
        return result

    @staticmethod
    def _get_positions_intraday_amplitude(positions: List[Dict]) -> Dict[str, Dict]:
        """获取持仓的日内振幅数据（用于做T策略判断）

        Args:
            positions: 持仓列表，每项包含 code, name 等字段

        Returns:
            {stock_code: {"amplitude_pct": float, "has_t_opportunity": bool, ...}}
        """
        if not positions:
            return {}
        result = {}
        try:
            from app.core.pytdx_source import pytdx_data
            today_str = date.today().strftime("%Y-%m-%d")
            for pos in positions:
                code = pos.get("code", "")
                if not code:
                    continue
                try:
                    klines = pytdx_data.get_kline(code, period=7, count=240)
                    if not klines:
                        continue
                    today_bars = [k for k in klines if k.get("date", "").startswith(today_str)]
                    if not today_bars or len(today_bars) < 2:
                        continue
                    day_high = max(bar["high"] for bar in today_bars)
                    day_low = min(bar["low"] for bar in today_bars if bar["low"] > 0)
                    if day_low <= 0:
                        continue
                    amplitude_pct = (day_high - day_low) / day_low * 100
                    has_t_opportunity = amplitude_pct >= 3.0
                    result[code] = {
                        "amplitude_pct": round(amplitude_pct, 2),
                        "has_t_opportunity": has_t_opportunity,
                        "high": round(day_high, 3),
                        "low": round(day_low, 3),
                    }
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"获取持仓日内振幅失败: {e}")
        return result

    @staticmethod
    def generate_strategy(
        db: Session,
        account_id: int,
        config: Dict = None,
        source: str = "auto",
        mode: str = "intraday",
    ) -> Dict[str, Any]:
        """盘中即时策略（9:30-15:00 调用）

        使用实时行情数据，生成今日立即执行的交易计划。
        decision_date = 今天，盘中监控自动执行。

        Args:
            mode: 策略模式，"intraday"=上午盘中，"intraday_afternoon"=下午盘中
        """
        return AIStrategyGenerator._generate(
            db=db,
            account_id=account_id,
            config=config,
            mode=mode,
            system_prompt=AIStrategyGenerator.INTRADAY_SYSTEM_PROMPT,
            source=source,
        )

    @staticmethod
    def generate_next_day_strategy(
        db: Session,
        account_id: int,
        config: Dict = None,
        review_analysis: str = "",
        source: str = "auto",
    ) -> Dict[str, Any]:
        """收盘次日策略（15:10 调用）

        使用今日收盘数据和持仓分析，生成明日交易计划。
        decision_date = 下一个交易日，次日盘中监控自动执行。

        Args:
            review_analysis: 当日复盘报告文本，注入策略 prompt
        """
        return AIStrategyGenerator._generate(
            db=db,
            account_id=account_id,
            config=config,
            mode="next_day",
            system_prompt=AIStrategyGenerator.NEXT_DAY_SYSTEM_PROMPT,
            review_analysis=review_analysis,
            source=source,
        )

    @staticmethod
    def generate_midday_strategy(
        db: Session,
        account_id: int,
        config: Dict = None,
        source: str = "auto",
    ) -> Dict[str, Any]:
        """午间策略调整（11:30 休盘时调用）

        总结上午交易执行情况，结合上午市场走势，
        调整下午的交易策略。decision_date = 今天，覆盖已有 pending 策略。
        """
        return AIStrategyGenerator._generate(
            db=db,
            account_id=account_id,
            config=config,
            mode="midday",
            system_prompt=AIStrategyGenerator.MIDDAY_SYSTEM_PROMPT,
            source=source,
        )

    @staticmethod
    def _get_morning_trades(db: Session, account_id: int, trade_date: str) -> str:
        """获取上午交易记录摘要，用于午间策略 prompt"""
        from app.models.sim_trading import SimTrade
        from sqlalchemy import and_

        trades = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_date == trade_date,
            )
        ).order_by(SimTrade.trade_time).all()

        if not trades:
            return "  上午无交易"

        buy_trades = [t for t in trades if t.trade_type == "buy"]
        sell_trades = [t for t in trades if t.trade_type == "sell"]

        lines = []
        for t in trades:
            direction = "买入" if t.trade_type == "buy" else "卖出"
            profit_str = ""
            if t.trade_type == "sell" and t.profit is not None:
                profit_str = f", 盈亏={t.profit:+.2f}元({t.profit_ratio:+.2f}%)"
            lines.append(
                f"  {t.trade_time or '--'} {direction} {t.stock_name}({t.stock_code}) "
                f"× {t.trade_quantity}股 @ {t.trade_price:.2f}元"
                f"{profit_str} 策略={t.strategy_name or '无'}"
            )

        summary = f"买入{len(buy_trades)}笔, 卖出{len(sell_trades)}笔, 共{len(trades)}笔\n"
        summary += "\n".join(lines)
        return summary

    @staticmethod
    def _is_buyable(code: str, name: str, change_pct: float) -> bool:
        """过滤不可买入的股票：排除 ST / 涨停 / 北交所"""
        if "ST" in (name or "").upper():
            return False
        # 创业板(30x)/科创板(68x) 涨停阈值 20%，主板 10%
        if code and (code.startswith("30") or code.startswith("68")):
            if change_pct >= 19.8:
                return False
        else:
            if change_pct >= 9.8:
                return False
        if code and (code.startswith("8") or code.startswith("4")):
            return False
        return True

    @staticmethod
    def _get_recent_lessons(db: Session, account_id: int, limit: int = 3) -> str:
        """获取最近 N 天的复盘经验教训 + 策略准确度统计，注入策略 prompt"""
        from app.models.sim_trading import SimDailyReview
        reviews = db.query(SimDailyReview).filter(
            SimDailyReview.account_id == account_id,
        ).order_by(SimDailyReview.review_date.desc()).limit(limit).all()
        if not reviews:
            return ""

        lines = []

        # 策略准确度统计
        accuracy_vals = [r.strategy_accuracy for r in reviews if r.strategy_accuracy is not None]
        win_rates = [r.win_rate for r in reviews if r.win_rate is not None]
        daily_pnls = [r.daily_pnl for r in reviews if r.daily_pnl is not None]

        if accuracy_vals or win_rates:
            lines.append("历史策略表现:")
            if accuracy_vals:
                avg_acc = round(sum(accuracy_vals) / len(accuracy_vals), 1)
                lines.append(f"  近{len(accuracy_vals)}日平均策略准确率: {avg_acc}%")
            if win_rates:
                avg_wr = round(sum(win_rates) / len(win_rates), 1)
                lines.append(f"  近{len(win_rates)}日平均胜率: {avg_wr}%")
            if daily_pnls:
                total_pnl = round(sum(daily_pnls), 2)
                lines.append(f"  近{len(daily_pnls)}日累计盈亏: {total_pnl:+.2f}元")

        # 经验教训
        for r in reviews:
            if r.lessons and r.lessons.strip():
                lines.append(f"[{r.review_date}] {r.lessons.strip()}")

        # P2-7：近30天失败模式 Top3（按 source 聚合）
        try:
            from app.models.sim_trading import SimFailurePattern
            from sqlalchemy import func
            from datetime import date as _date, timedelta as _timedelta
            cutoff = (_date.today() - _timedelta(days=30)).strftime("%Y-%m-%d")
            fail_stats = db.query(
                SimFailurePattern.source.label("src"),
                func.count().label("cnt"),
                func.avg(SimFailurePattern.profit_ratio).label("avg_pnl"),
                func.min(SimFailurePattern.profit_ratio).label("worst_pnl"),
            ).filter(
                SimFailurePattern.account_id == account_id,
                SimFailurePattern.sell_date >= cutoff,
            ).group_by(SimFailurePattern.source).all()

            if fail_stats:
                lines.append("\n近30天失败模式 Top3（避免重复犯错）:")
                # 按 cnt 降序取 Top3
                sorted_stats = sorted(fail_stats, key=lambda x: x.cnt or 0, reverse=True)[:3]
                for fs in sorted_stats:
                    src = fs.src or "manual"
                    cnt = fs.cnt or 0
                    avg_pnl = fs.avg_pnl or 0
                    worst = fs.worst_pnl or 0
                    lines.append(
                        f"  - 来源 {src}: 失败 {cnt} 次, 平均亏损 {avg_pnl:.2f}%, 最差 {worst:.2f}%"
                    )
                lines.append("  → 决策时优先避开上述来源的高风险标的")
        except Exception as e:
            log.warning(f"获取失败模式统计失败: {e}")

        return "\n".join(lines)

    @staticmethod
    def _get_morning_strategy_summary(db: Session, account_id: int) -> str:
        """获取上午策略决策摘要，用于午间策略 prompt"""
        from datetime import date as _date
        today_str = _date.today().strftime("%Y-%m-%d")

        decision = db.query(AIStrategyDecision).filter(
            AIStrategyDecision.account_id == account_id,
            AIStrategyDecision.decision_date == today_str,
            AIStrategyDecision.strategy_mode == "intraday",
        ).first()

        if not decision:
            return ""

        lines = [f"上午AI策略 (生成: {decision.created_at.strftime('%H:%M:%S') if decision.created_at else '未知'}, 状态: {decision.execution_status})"]
        lines.append(f"  市场情绪: {decision.market_sentiment or 'neutral'}, 建议仓位: {decision.position_ratio}%")

        if decision.buy_list:
            try:
                buys = json.loads(decision.buy_list)
                if buys:
                    lines.append(f"  买入计划 ({len(buys)}只):")
                    for b in buys:
                        lines.append(f"    {b.get('code')} {b.get('name','')} ¥{b.get('price',0):.2f} x{b.get('quantity',0)}股 理由: {b.get('reason','')}")
            except json.JSONDecodeError:
                pass

        if decision.sell_list:
            try:
                sells = json.loads(decision.sell_list)
                if sells:
                    lines.append(f"  卖出计划 ({len(sells)}只):")
                    for s in sells:
                        lines.append(f"    {s.get('stock_code','')} {s.get('stock_name','')} {s.get('sell_reason','')}")
            except json.JSONDecodeError:
                pass

        if decision.ai_analysis:
            lines.append(f"  AI分析: {decision.ai_analysis[:200]}")

        return "\n".join(lines)

    @staticmethod
    def _get_dragon_list_summary() -> str:
        """获取今日龙虎榜摘要，注入次日策略 prompt"""
        try:
            from app.services.strategy_service import StrategyService
            ss = StrategyService()
            dragon = ss.get_dragon_list_today()
            if not dragon:
                return ""

            lines = []
            # 涨幅榜
            gainers = dragon.get("gainers_list", [])[:8]
            if gainers:
                lines.append("龙虎榜涨幅榜:")
                for g in gainers:
                    code = g.get("code", "")
                    name = g.get("name", "")
                    change = g.get("change_pct", 0)
                    reason = g.get("reason", "")
                    lines.append(f"  {code} {name} +{change:.2f}% {reason}")

            # 跌幅榜
            losers = dragon.get("losers_list", [])[:5]
            if losers:
                lines.append("龙虎榜跌幅榜:")
                for l in losers:
                    code = l.get("code", "")
                    name = l.get("name", "")
                    change = l.get("change_pct", 0)
                    reason = l.get("reason", "")
                    lines.append(f"  {code} {name} {change:.2f}% {reason}")

            # 涨停/跌停统计
            limit_up = dragon.get("limit_up_count", 0)
            limit_down = dragon.get("limit_down_count", 0)
            if limit_up or limit_down:
                lines.append(f"涨停{limit_up}家 / 跌停{limit_down}家")

            return "\n".join(lines) if lines else ""
        except Exception as e:
            log.warning(f"获取龙虎榜摘要失败: {e}")
            return ""

    @staticmethod
    def _get_sector_rotation_summary() -> str:
        """获取板块轮动摘要，注入次日策略 prompt"""
        try:
            from app.services.sector_analysis_service import sector_analysis_service
            result = sector_analysis_service.get_sector_rotation_model(
                sector_type="concept", top_n=10
            )
            if not result:
                return ""

            sectors = result.get("sectors", [])[:8]
            signal = result.get("rotation_signal", "")
            if not sectors:
                return ""

            lines = ["板块轮动(概念板块TOP8):"]
            for s in sectors:
                name = s.get("name", "")
                score = s.get("score", 0)
                change = s.get("change_pct", 0)
                lifecycle = s.get("lifecycle", "")
                lines.append(f"  {name} 评分{score:.0f} 涨跌{change:+.2f}% {lifecycle}")
            if signal:
                lines.append(f"轮动信号: {signal}")

            return "\n".join(lines)
        except Exception as e:
            log.warning(f"获取板块轮动摘要失败: {e}")
            return ""

    @staticmethod
    def _get_position_risk_info(db: Session, account_id: int) -> str:
        """获取持仓止损/止盈价位信息，注入策略 prompt"""
        from app.models.sim_trading import SimPosition
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()
        if not positions:
            return ""

        lines = ["持仓风控信息:"]
        for p in positions:
            cost = p.cost_price or 0
            current = p.current_price or 0
            atr = p.atr_value or 0
            profit = p.profit_ratio or 0

            # 计算止损位
            if atr > 0 and cost > 0:
                atr_stop_price = cost - 2 * atr
                # ATR止损最低阈值保护：止损线至少在成本价下方5%
                min_stop_price = cost * 0.95
                stop_loss_price = max(atr_stop_price, min_stop_price)
                stop_loss_pct = (stop_loss_price / cost - 1) * 100
                stop_info = f"ATR止损{stop_loss_price:.2f}({stop_loss_pct:+.1f}%)"
            else:
                stop_loss_pct = -8
                stop_info = f"固定止损{stop_loss_pct}%"

            # 计算持仓天数
            buy_date = p.buy_date
            hold_days = 0
            if buy_date:
                from datetime import date as _date
                if isinstance(buy_date, str):
                    bd = _date.fromisoformat(buy_date)
                else:
                    bd = buy_date
                hold_days = (_date.today() - bd).days

            lines.append(
                f"  {p.stock_name}({p.stock_code}): "
                f"成本{cost:.3f} 现价{current:.3f} 盈亏{profit:+.2f}% "
                f"{stop_info} 持仓{hold_days}天"
            )

        return "\n".join(lines)

    @staticmethod
    def _get_sector_exposure(db: Session, account_id: int) -> Dict[str, float]:
        """获取当前持仓的行业暴露（百分比），用于板块分散约束提示

        返回示例: {"银行": 35.2, "医药": 20.5, "电子": 15.0}
        通过腾讯行情接口查询每只股票的行业字段
        """
        from app.models.sim_trading import SimPosition
        from app.core.data_sources import TencentSource

        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()

        if not positions:
            return {}

        total_mv = sum(p.market_value or 0 for p in positions)
        if total_mv <= 0:
            return {}

        # 通过腾讯行情获取行业信息
        sector_map: Dict[str, float] = {}
        codes = [p.stock_code for p in positions]
        try:
            quotes = TencentSource.get_quotes(codes)
            for p in positions:
                q = quotes.get(p.stock_code, {}) if quotes else {}
                # 腾讯行情的 industry 字段（可能不存在，用 "其他" 兜底）
                sector = q.get("industry") or q.get("sector") or "其他"
                sector_map[sector] = sector_map.get(sector, 0) + (p.market_value or 0)
        except Exception as e:
            log.warning(f"获取行业暴露失败，使用其他归类: {e}")
            sector_map["其他"] = total_mv

        return {k: round(v / total_mv * 100, 1) for k, v in sector_map.items()}

    @staticmethod
    def _get_strategy_performance_stats(db: Session, account_id: int) -> str:
        """统计各 position_type 的历史胜率/盈亏，注入 prompt 让 AI 自我修正

        返回空字符串表示无统计数据
        """
        from app.models.sim_trading import SimTrade
        from sqlalchemy import func, and_, case

        try:
            stats = db.query(
                SimTrade.position_type.label('pos_type'),
                func.count().label('total'),
                func.avg(SimTrade.profit).label('avg_profit'),
                func.sum(SimTrade.profit).label('total_profit'),
                func.sum(
                    case(
                        (SimTrade.profit > 0, 1),
                        else_=0,
                    )
                ).label('wins'),
            ).filter(
                and_(
                    SimTrade.account_id == account_id,
                    SimTrade.trade_type == "sell",
                )
            ).group_by(SimTrade.position_type).all()
        except Exception as e:
            log.warning(f"策略表现统计查询失败: {e}")
            return ""

        if not stats:
            return ""

        lines = ["## 历史策略表现（按持仓周期，AI 请据此自我修正）"]
        for s in stats:
            pos_type = s.pos_type or "unknown"
            total = s.total or 0
            if total == 0:
                continue
            wins = s.wins or 0
            win_rate = wins / total * 100
            avg = s.avg_profit or 0
            total_profit = s.total_profit or 0
            lines.append(
                f"- {pos_type}: 共{total}笔, 胜率{win_rate:.0f}%, "
                f"平均盈亏{avg:+.0f}元, 累计{total_profit:+.0f}元"
            )

        if len(lines) == 1:
            return ""

        lines.append(
            "决策建议：胜率<40%或累计亏损的周期类型请减少使用；"
            "胜率>60%且累计盈利的周期类型可适当增加。"
        )
        return "\n".join(lines)

    @staticmethod
    def _get_today_trade_summary(db: Session, account_id: int, period_label: str = "今日") -> str:
        """获取当日交易记录摘要，用于盘中/午间策略 prompt

        Args:
            period_label: 时段标签，如"今日"、"上午"，影响输出文字
        """
        from app.models.sim_trading import SimTrade, SimPosition
        from sqlalchemy import and_
        from datetime import date

        today_str = date.today().strftime("%Y-%m-%d")

        # 当日交易记录
        trades = db.query(SimTrade).filter(
            and_(
                SimTrade.account_id == account_id,
                SimTrade.trade_date == today_str,
            )
        ).order_by(SimTrade.trade_time).all()

        # 当前持仓
        positions = db.query(SimPosition).filter(
            SimPosition.account_id == account_id
        ).all()

        lines = []

        # 1. 交易统计
        buy_trades = [t for t in trades if t.trade_type == "buy"]
        sell_trades = [t for t in trades if t.trade_type == "sell"]
        if not trades:
            return f"{period_label}无交易"

        lines.append(f"{period_label}成交: 买入{len(buy_trades)}笔 卖出{len(sell_trades)}笔")

        # 2. 买入的浮动盈亏
        if buy_trades:
            pos_map = {p.stock_code: p for p in positions}
            for t in buy_trades:
                pos = pos_map.get(t.stock_code)
                if pos:
                    pnl = pos.profit_ratio or 0
                    status = "盈" if pnl > 0 else "亏"
                    lines.append(f"  今日买入 {t.stock_name}({t.stock_code}) {status}{abs(pnl):.2f}%")
                else:
                    lines.append(f"  今日买入 {t.stock_name}({t.stock_code}) 已不在持仓")

        # 3. 卖出的结果
        for t in sell_trades:
            profit = t.profit or 0
            profit_ratio = t.profit_ratio or 0
            lines.append(
                f"  今日卖出 {t.stock_name}({t.stock_code}) "
                f"盈亏{profit:+.2f}元({profit_ratio:+.2f}%)"
            )

        return "\n".join(lines)

    @staticmethod
    def _generate(
        db: Session,
        account_id: int,
        config: Dict,
        mode: str,  # "intraday" | "next_day" | "midday"
        system_prompt: str,
        review_analysis: str = "",
        source: str = "auto",  # auto=定时任务, manual=手动生成
    ) -> Dict[str, Any]:
        """策略生成核心逻辑（盘中/次日/午间共用）"""
        account = db.query(SimAccount).filter(SimAccount.id == account_id).first()
        if not account:
            return {"success": False, "error": "账户不存在"}

        final_config = {**AIStrategyGenerator.DEFAULT_CONFIG, **(config or {})}
        is_trading = AIStrategyGenerator.is_trading_time()

        # ── 数据采集 ────────────────────────────────────────
        market = AIStrategyGenerator._get_market_overview()
        market_extra = AIStrategyGenerator._get_market_extra()
        account_info = AIStrategyGenerator._get_account_info(db, account_id)
        hot_stocks = AIStrategyGenerator._get_hot_stocks()

        # 热门股票实时行情
        hot_codes = [s["code"] for s in hot_stocks[:10]]
        hot_quotes = AIStrategyGenerator._get_realtime_quotes(hot_codes) if hot_codes else {}

        # ── 筛选买入候选 ────────────────────────────────────
        # 排除已持有的股票（避免重复买入同一标的）
        held_codes = {p.get("code") for p in account_info.get("positions", [])}
        # 也排除已挂限价单的股票（已有待成交买单）
        pending_buys = account_info.get("pending_buys", [])
        pending_buy_codes = {b.get("code") for b in pending_buys}
        excluded_codes = held_codes | pending_buy_codes

        buy_candidates = []
        for stock in hot_stocks:
            code = stock["code"]
            if code in excluded_codes:
                continue
            if code not in hot_quotes:
                continue
            q = hot_quotes[code]
            price = q.get("price", 0)
            change_pct = q.get("change_pct", 0)
            amount_wan = q.get("amount_wan", 0)
            turnover_pct = q.get("turnover_pct", 0) or 0
            pe_ttm = q.get("pe_ttm", 0) or 0
            pb = q.get("pb", 0) or 0
            mcap_yi = q.get("mcap_yi", 0) or 0

            if price <= 0 or amount_wan <= 1000:
                continue

            # 过滤低换手率（无人气）
            if turnover_pct < 1.0:
                continue

            # 过滤 ST / 涨停 / 北交所
            if not AIStrategyGenerator._is_buyable(code, stock.get("name", ""), change_pct):
                continue

            # 盘中模式：避免追高，涨幅上限6%（原8%过于宽松，易高位接盘）
            # 次日模式不限涨幅（用收盘价）
            if mode == "intraday" and change_pct > 6:
                continue

            # 估值硬过滤（P0-3）：排除亏损股/估值过高/微盘股
            # - pe_ttm < 0：亏损股，基本面有风险
            # - pe_ttm > 100：估值过高，泡沫风险
            # - pb > 10：PB过高
            # - mcap_yi < 30：市值<30亿的微盘股，流动性风险
            if pe_ttm < 0 or pe_ttm > 100:
                continue
            if pb > 10:
                continue
            if 0 < mcap_yi < 30:
                continue

            buy_candidates.append({
                **stock,
                "price": price,
                "change_pct": change_pct,
                "amount_wan": amount_wan,
                "turnover_pct": round(turnover_pct, 2),
                "vol_ratio": round(q.get("vol_ratio", 0) or 0, 2),
                "pe_ttm": round(pe_ttm, 2),
                "pb": round(pb, 2),
                "mcap_yi": round(mcap_yi, 1),
            })

        # 兜底：若严格过滤后为空，放宽估值限制（PE上限到200，市值放宽到15亿）
        # 仍排除亏损股(pe<0)和ST/涨停/北交所/已持有/已挂单
        if not buy_candidates and hot_stocks:
            for stock in hot_stocks:
                code = stock["code"]
                if code in excluded_codes:
                    continue
                if code not in hot_quotes:
                    continue
                q = hot_quotes[code]
                price = q.get("price", 0)
                change_pct = q.get("change_pct", 0)
                amount_wan = q.get("amount_wan", 0)
                pe_ttm = q.get("pe_ttm", 0) or 0
                pb = q.get("pb", 0) or 0
                mcap_yi = q.get("mcap_yi", 0) or 0
                if price > 0 and amount_wan > 1000:
                    if not AIStrategyGenerator._is_buyable(code, stock.get("name", ""), change_pct):
                        continue
                    # 兜底场景：仍排除亏损股，PE上限放宽到200，PB上限放宽到20
                    if pe_ttm < 0 or pe_ttm > 200:
                        continue
                    if pb > 20:
                        continue
                    if 0 < mcap_yi < 15:
                        continue
                    buy_candidates.append({
                        **stock,
                        "price": price,
                        "change_pct": change_pct,
                        "amount_wan": amount_wan,
                        "turnover_pct": round(q.get("turnover_pct", 0) or 0, 2),
                        "vol_ratio": round(q.get("vol_ratio", 0) or 0, 2),
                        "pe_ttm": round(pe_ttm, 2),
                        "pb": round(pb, 2),
                        "mcap_yi": round(mcap_yi, 1),
                    })
                if len(buy_candidates) >= 3:
                    break

        # 获取候选股票的MA均线位置（仅 top 8，轻量查询）
        if buy_candidates:
            top_codes = [c["code"] for c in buy_candidates[:8]]
            ma_positions = AIStrategyGenerator._get_ma_position(top_codes)
            for c in buy_candidates:
                if c["code"] in ma_positions:
                    c["ma_position"] = ma_positions[c["code"]]

        # ── 检查卖出信号（止损止盈）──────────────────────────
        # 按 position_type 差异化阈值，避免短线持仓被深套、长线被早卖
        # 短线: 止损-5% 止盈8-15% / 中线: 止损-10% 止盈20-40% / 长线: 止损-15% 止盈40-100%
        # 注意：实际硬性止损止盈由 RiskManager 执行（也按 position_type 差异化）
        # 这里 sell_signals 是给 AI 的提示信号
        POS_SELL_THRESHOLDS = {
            "short": {"stop_loss": -5, "take_profit": 8, "strong_profit": 15},
            "mid":   {"stop_loss": -10, "take_profit": 20, "strong_profit": 40},
            "long":  {"stop_loss": -15, "take_profit": 40, "strong_profit": 100},
        }
        sell_signals = []
        _today_str = date.today().strftime("%Y-%m-%d")
        for pos in account_info.get("positions", []):
            if pos["available"] <= 0:
                continue
            # T+1 保护：今日买入的持仓不生成卖出/做T信号
            if pos.get("buy_date") == _today_str:
                continue

            pos_type = pos.get("position_type") or "short"
            thresholds = POS_SELL_THRESHOLDS.get(pos_type, POS_SELL_THRESHOLDS["short"])

            if final_config["enforce_params"]:
                sell_reason = None
                if pos["profit_ratio"] <= thresholds["stop_loss"]:
                    sell_reason = f"[{pos_type}]触发止损 {pos['profit_ratio']:.2f}% (阈值{thresholds['stop_loss']}%)"
                elif pos["profit_ratio"] >= thresholds["strong_profit"]:
                    sell_reason = f"[{pos_type}]触发强止盈 {pos['profit_ratio']:.2f}% (阈值{thresholds['strong_profit']}%)"
            else:
                # AI 自主决定：按持仓周期差异化提示
                sell_reason = None
                if pos["profit_ratio"] <= thresholds["stop_loss"]:
                    sell_reason = (
                        f"[{pos_type}]浮亏{pos['profit_ratio']:.2f}%达止损线，请AI评估是否止损"
                    )
                elif pos["profit_ratio"] >= thresholds["take_profit"]:
                    # 达到止盈线但未到强止盈线，提示AI考虑分批止盈
                    if pos["profit_ratio"] >= thresholds["strong_profit"]:
                        sell_reason = (
                            f"[{pos_type}]浮盈{pos['profit_ratio']:.2f}%达强止盈线，请AI评估是否清仓"
                        )
                    else:
                        sell_reason = (
                            f"[{pos_type}]浮盈{pos['profit_ratio']:.2f}%达止盈线，请AI评估是否分批止盈"
                        )
            if sell_reason:
                sell_signals.append({
                    "stock_code": pos["code"],
                    "stock_name": pos["name"],
                    "sell_reason": sell_reason,
                    "current_price": pos["current_price"],
                    "profit_ratio": pos["profit_ratio"],
                    "position_type": pos_type,
                    "quantity": pos["available"],
                })

        # ── 资金计算 ────────────────────────────────────────
        # available_capital = current_capital（用于限制 AI 决策的资金池）
        # real_available = current_capital - frozen_capital（实际可用于新委托）
        available_capital = account.current_capital
        real_available_capital = max(0, account.current_capital - (account_info.get("frozen_capital") or 0))

        # ── 构建 LLM 提示词 ────────────────────────────────
        positions_str = json.dumps(
            account_info.get("positions", []), ensure_ascii=False, default=str
        )
        candidates_str = json.dumps(buy_candidates[:8], ensure_ascii=False, default=str)
        sell_str = json.dumps(sell_signals, ensure_ascii=False, default=str)

        # 指数信息
        indices_raw = market.get("indices", {})
        indices_list = list(indices_raw.values())[:3] if isinstance(indices_raw, dict) else []
        indices_str = "、".join(
            [f"{v.get('name', '')} {v.get('change_pct', 0):.2f}%"
             for v in indices_list if isinstance(v, dict)]
        ) if indices_list else "暂无"

        breadth = market.get("breadth", {})

        # ── P2-1 动态仓位配置：根据市场情绪+涨跌家数自适应调整仓位上限 ──
        sentiment = market.get("sentiment", "neutral")
        up_count = breadth.get("up", 0) or 0
        down_count = breadth.get("down", 0) or 0

        if sentiment == "bullish" and up_count > down_count * 2:
            dynamic_max_position_ratio = 0.80
            suggested_allocation = {"short": 0.30, "mid": 0.30, "long": 0.20}
            market_stage = "牛市(强势)"
        elif sentiment == "bearish" or (down_count > up_count * 1.5 and up_count > 0):
            dynamic_max_position_ratio = 0.45
            suggested_allocation = {"short": 0.10, "mid": 0.15, "long": 0.20}
            market_stage = "熊市(弱势)"
        else:
            dynamic_max_position_ratio = 0.60
            suggested_allocation = {"short": 0.20, "mid": 0.25, "long": 0.25}
            market_stage = "震荡市"

        dynamic_position_text = f"""## 动态仓位配置（基于市场情绪，AI 必须遵守）
当前市场判定: {market_stage}, 涨{up_count}/跌{down_count}, 情绪={sentiment}
- 总仓位上限: {dynamic_max_position_ratio*100:.0f}%（买入总额 ≤ {account.initial_capital * dynamic_max_position_ratio:,.0f}元）
- 建议周期配置: 短线{suggested_allocation['short']*100:.0f}% + 中线{suggested_allocation['mid']*100:.0f}% + 长线{suggested_allocation['long']*100:.0f}%
- 现金保留: {(1-dynamic_max_position_ratio)*100:.0f}%（应对突发风险）
- 单日新建仓: 短线不超过 3 只，中长线不超过 2 只"""

        # ── P1-3 板块分散约束：注入当前持仓行业分布 ──
        sector_exposure_text = ""
        try:
            sector_exposure = AIStrategyGenerator._get_sector_exposure(db, account_id)
            if sector_exposure:
                lines = [f"  {k}: {v}%" for k, v in sector_exposure.items()]
                sector_exposure_text = "## 当前持仓行业分布\n" + "\n".join(lines) + "\n"
        except Exception as e:
            log.warning(f"获取行业暴露失败: {e}")

        # ── P2-3 策略效果量化反馈：注入历史胜率/盈亏让 AI 自我修正 ──
        performance_text = ""
        try:
            performance_text = AIStrategyGenerator._get_strategy_performance_stats(db, account_id)
        except Exception as e:
            log.warning(f"获取策略表现统计失败: {e}")


        # 板块热度 + 北向资金（所有模式通用）
        sectors_text = ""
        if market_extra.get("sectors"):
            sector_lines = [f"  {s['name']} {s.get('change_pct', 0):+.2f}%" for s in market_extra["sectors"]]
            sectors_text = "板块热度(Top5):\n" + "\n".join(sector_lines) + "\n"
        northbound_text = market_extra.get("northbound", "")
        if northbound_text:
            northbound_text = northbound_text + "\n"

        # 持仓盈亏分析（次日/午间模式额外提供）
        position_analysis = ""
        if mode in ("next_day", "midday"):
            pos_list = account_info.get("positions", [])
            if pos_list:
                lines = []
                for p in pos_list:
                    status = "盈利" if p["profit_ratio"] > 0 else "亏损"
                    lines.append(
                        f"- {p['name']}({p['code']}): {status}{abs(p['profit_ratio']):.2f}%, "
                        f"成本{p['cost_price']:.3f}, 现价{p['current_price']:.3f}, "
                        f"持仓{p['quantity']}股, 买入日{p.get('buy_date', '未知')}"
                    )
                position_analysis = "\n".join(lines)

        # Python 3.11 不支持 f-string 内嵌反斜杠，提前计算
        position_analysis_text = f"### 持仓盈亏分析\n{position_analysis}" if position_analysis else ""

        # 持仓风控信息（止损/止盈价位）——所有模式注入
        position_risk_text = ""
        pos_risk = AIStrategyGenerator._get_position_risk_info(db, account_id)
        if pos_risk:
            position_risk_text = f"## 持仓风控信息\n{pos_risk}\n"

        # 持仓日内振幅（做T策略参考）——盘中/午间模式注入
        amplitude_data = {}
        t_trade_text = ""
        if mode in ("intraday", "midday"):
            positions = account_info.get("positions", [])
            amplitude_data = AIStrategyGenerator._get_positions_intraday_amplitude(positions)
            if amplitude_data:
                t_lines = []
                for code, info in amplitude_data.items():
                    pos = next((p for p in positions if p.get("code") == code), None)
                    name = pos.get("name", "") if pos else ""
                    t_opportunity = "✅可做T" if info["has_t_opportunity"] else ""
                    t_lines.append(
                        f"  {code} {name}: 振幅{info['amplitude_pct']:.2f}% "
                        f"高{info['high']:.3f} 低{info['low']:.3f} {t_opportunity}"
                    )
                t_trade_text = f"## 持仓日内振幅\n" + "\n".join(t_lines) + "\n"

        # 午间模式：注入上午策略决策，让 AI 对比计划 vs 实际
        morning_strategy_text = ""
        if mode == "midday":
            morning_summary = AIStrategyGenerator._get_morning_strategy_summary(db, account_id)
            if morning_summary:
                morning_strategy_text = f"## 上午AI策略决策\n{morning_summary}\n\n"

        # 盘中/午间模式：注入当日已成交记录（让 AI 看到日内实际执行情况）
        today_trades_text = ""
        if mode in ("midday", "intraday"):
            period_label = "上午" if mode == "midday" else "今日"
            today_trades_text = AIStrategyGenerator._get_today_trade_summary(
                db, account_id, period_label
            )
            today_trades_text = f"## {period_label}成交记录\n{today_trades_text}\n\n"

        # 次日模式：注入龙虎榜+板块轮动
        dragon_text = ""
        sector_text = ""
        review_text = ""
        if mode == "next_day":
            dragon_summary = AIStrategyGenerator._get_dragon_list_summary()
            if dragon_summary:
                dragon_text = f"## 龙虎榜数据\n{dragon_summary}\n"

            sector_summary = AIStrategyGenerator._get_sector_rotation_summary()
            if sector_summary:
                sector_text = f"## 板块轮动\n{sector_summary}\n"

            # 复盘报告完整注入
            if review_analysis:
                review_text = f"## 今日复盘报告\n{review_analysis}\n"

        # 获取近期复盘经验教训，注入 prompt
        lessons = AIStrategyGenerator._get_recent_lessons(db, account_id)
        lessons_text = f"## 近期经验教训\n{lessons}" if lessons else ""

        # 注入未成交委托（买+卖）完整明细，AI 据此重新评估
        pending_detail = AIStrategyGenerator._get_pending_orders_detail(db, account_id)
        if pending_detail:
            lines = ["## 当前未成交委托（需重新评估）"]
            for o in pending_detail:
                if o["distance_pct"] is not None:
                    arrow = "↑" if o["distance_pct"] > 0 else "↓"
                    dist = f"{arrow}{abs(o['distance_pct']):.2f}%"
                else:
                    dist = "N/A"
                cur_str = f"{o['current_price']:.2f}" if o["current_price"] else "N/A"
                direction = "买入" if o["type"] == "buy" else "卖出"
                lines.append(
                    f"- [{direction}] {o['name']}({o['code']}) "
                    f"委托价{o['price']:.2f} 现价{cur_str} ({dist}) "
                    f"数量{o['quantity']} 已成{o['filled']} 过期{o['expire_time']} "
                    f"理由: {o['strategy_reason']}"
                )
            lines.append(
                "请判断每笔委托：①保留等待成交 ②在 buy_list/sell_list 中重新出价 ③放弃（不列出即可，"
                "系统会在新策略执行前自动清空所有旧委托）"
            )
            pending_text = "\n".join(lines) + "\n"
        else:
            pending_text = ""

        mode_label = {"intraday": "盘中即时执行", "next_day": "收盘次日计划", "midday": "午间策略调整"}

        # 策略参数约束：仅在 enforce_params=True 时下发到 prompt
        if final_config.get("enforce_params", True):
            rules_text = f"""## 策略参数约束（严格遵守）
- 单只最大仓位: {final_config['max_single_position_ratio']*100:.0f}% (单只金额≤{account.initial_capital * final_config['max_single_position_ratio']:,.0f}元)
- 总仓位上限: {final_config['total_position_ratio']*100:.0f}% (买入总额≤{account.initial_capital * final_config['total_position_ratio']:,.0f}元)
- 止损线: {final_config['stop_loss_ratio']:.0f}% (浮亏达此比例强制卖出)
- 止盈线: {final_config['take_profit_ratio']:.0f}% (浮盈达此比例强制卖出)
- 最小买入金额: {final_config['min_buy_amount']:,.0f}元 (单笔低于此金额不买入)"""
        else:
            rules_text = """## 策略参数约束（AI 自主模式）
- 本次生成不受任何预设参数限制，AI 自主决定所有仓位/止损/止盈/单笔金额
- 单只最大仓位、总仓位上限、止损止盈阈值由 AI 根据市场情况、个股波动性、账户风险承受能力自行判断
- 决策依据：可买入候选的市值/成交额/波动率、当前持仓集中度、市场情绪、近期经验教训
- 仍需保证：单只金额≥1000元、买入数量为100的整数倍、不可超过可用资金
- 注意：冻结资金（限价单占用）不可用于新委托，买入总额不能超过可用资金"""

        user_prompt = f"""当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
策略模式: {mode_label.get(mode, mode)}
交易时段: {'是' if is_trading else '否(非交易时间)'}

{morning_strategy_text}{today_trades_text}## 市场概况
涨跌家数: 涨{breadth.get('up', 0)} / 跌{breadth.get('down', 0)} / 平{breadth.get('flat', 0)}
涨停{breadth.get('limit_up', 0)}家 / 跌停{breadth.get('limit_down', 0)}家
市场情绪: {market.get('sentiment', 'neutral')}
主要指数: {indices_str}
{northbound_text}{sectors_text}
## 账户状态
- 初始资金: {account.initial_capital:,.0f}元
- 可用资金: {account.current_capital:,.0f}元
- 冻结资金(限价单): {account_info['frozen_capital']:,.0f}元
- 实际可用于新委托: {real_available_capital:,.0f}元（= 可用资金 - 冻结资金）
- 持仓市值: {account_info['market_value']:,.0f}元
- 总资产: {account_info['total_assets']:,.0f}元
- 仓位比例: {account_info['position_ratio']}%
{pending_text}

{rules_text}

{dynamic_position_text}

{sector_exposure_text}
## 当前持仓详情
{positions_str}
{position_analysis_text}
{position_risk_text}
{t_trade_text}
{dragon_text}{sector_text}{review_text}
## 可买入候选(实时行情)
{candidates_str}

## 待卖出信号
{sell_str if sell_signals else '无'}
{lessons_text}
{performance_text}
请根据以上数据输出交易策略JSON。每笔买入必须标注 position_type (short/mid/long)，并参考历史策略表现调整决策。"""

        # ── 调用 LLM ───────────────────────────────────────
        try:
            from app.core.llm_service import llm_config, llm_client
            if not llm_config.enabled:
                return {"success": False, "error": "LLM服务未启用"}

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            result = asyncio.run(
                llm_client.chat_completion(messages=messages, stream=False)
            )
            llm_response = result.get("content", "")

        except Exception as e:
            log.error(f"LLM调用失败: {e}")
            return {"success": False, "error": f"AI分析失败: {str(e)}"}

        # ── 解析 LLM 响应 ──────────────────────────────────
        def _extract_json(text):
            """从LLM回复中提取JSON对象（处理推理内容+代码块等）"""
            text = text.strip()
            # 优先尝试代码块
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            # 尝试找到第一个{和最后一个}之间的内容
            first_brace = text.find('{')
            last_brace = text.rfind('}')
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                text = text[first_brace:last_brace + 1]
            return text.strip()

        strategy_data = None
        parse_error = None
        for attempt in range(2):
            try:
                json_str = _extract_json(llm_response)
                strategy_data = json.loads(json_str)
                break
            except json.JSONDecodeError as e:
                parse_error = e
                if attempt == 0:
                    log.warning(f"LLM响应JSON解析失败，尝试重试: {e}")
                    try:
                        retry_messages = messages + [
                            {"role": "assistant", "content": llm_response[:500]},
                            {"role": "user", "content": "你的上一条回复不是有效的JSON格式。请严格按照要求的JSON格式输出，不要添加任何额外的解释文字。直接输出JSON。"},
                        ]
                        retry_result = asyncio.run(
                            llm_client.chat_completion(messages=retry_messages, stream=False)
                        )
                        llm_response = retry_result.get("content", "")
                    except Exception as retry_e:
                        log.error(f"LLM重试调用失败: {retry_e}")
                        break

        if strategy_data is None:
            log.error(f"LLM响应解析失败（含重试）: {parse_error}")
            return {"success": False, "error": "AI响应格式错误，请重试"}

        # ── LLM 响应结构校验 ──────────────────────────────
        if not isinstance(strategy_data, dict):
            return {"success": False, "error": "AI响应格式非对象"}
        if "buy_list" not in strategy_data or not isinstance(strategy_data.get("buy_list"), list):
            strategy_data["buy_list"] = []
        if "sell_list" not in strategy_data or not isinstance(strategy_data.get("sell_list"), list):
            strategy_data["sell_list"] = []

        # 校验买入项字段完整性
        valid_buys = []
        for item in strategy_data["buy_list"]:
            if not isinstance(item, dict):
                continue
            if not item.get("code") or not item.get("price") or not item.get("quantity"):
                continue
            try:
                item["price"] = float(item["price"])
                item["quantity"] = int(item["quantity"])
            except (ValueError, TypeError):
                continue
            valid_buys.append(item)
        strategy_data["buy_list"] = valid_buys

        # 校验买入股票代码是否在候选列表或持仓中（防止 AI 编造不存在的代码）
        valid_codes = set(hot_quotes.keys()) | held_codes
        filtered_buys = []
        for item in strategy_data.get("buy_list", []):
            code = item.get("code", "")
            if code in valid_codes:
                filtered_buys.append(item)
            else:
                log.warning(f"AI 编造了不存在的股票代码 {code}，已从买入列表移除")
        strategy_data["buy_list"] = filtered_buys

        # 校验卖出股票代码是否在持仓中，并统一字段格式
        # AI 输出的 sell_list 使用 "code" 字段，执行引擎使用 "stock_code" 字段
        # 构建持仓映射，用于补充 quantity 等必要字段
        positions_map = {p["code"]: p for p in account_info.get("positions", [])}
        filtered_sells = []
        for item in strategy_data.get("sell_list", []):
            code = item.get("code") or item.get("stock_code", "")
            if code in held_codes:
                pos = positions_map.get(code, {})
                # T+1 保护：今日买入的持仓不可卖出
                if pos.get("buy_date") == _today_str:
                    log.warning(f"AI 卖出的 {code} 是今日买入(T+1)，已移除")
                    continue
                # 统一为执行引擎期望的字段格式
                normalized = {
                    "stock_code": code,
                    "stock_name": item.get("name") or item.get("stock_name") or pos.get("name", ""),
                    "sell_reason": item.get("reason") or item.get("sell_reason", "AI建议减仓"),
                    "quantity": pos.get("available", 0),
                    "current_price": pos.get("current_price", 0),
                    "profit_ratio": pos.get("profit_ratio", 0),
                }
                if normalized["quantity"] > 0:
                    filtered_sells.append(normalized)
            else:
                log.warning(f"AI 卖出不在持仓中的股票 {code}，已从卖出列表移除")
        strategy_data["sell_list"] = filtered_sells

        # 收集卖出列表中的股票代码，排除其做T机会（已计划卖出的不重复做T）
        planned_sell_codes = {s["stock_code"] for s in filtered_sells}

        # 校验做T列表：必须在持仓中，且日内振幅>=3%，且非今日买入（T+1）
        filtered_t_trades = []
        for item in strategy_data.get("t_trade_list", []):
            code = item.get("code", "")
            if code in planned_sell_codes:
                log.info(f"股票 {code} 同时出现在卖出和做T列表，优先执行卖出，已从做T列表移除")
                continue
            if code in held_codes:
                pos = positions_map.get(code, {})
                # T+1 保护：今日买入的持仓不可做T
                if pos.get("buy_date") == _today_str:
                    log.warning(f"AI 建议做T的 {code} 是今日买入(T+1)，已移除")
                    continue
                amp_info = amplitude_data.get(code, {})
                # 仅保留有做T机会的持仓（振幅>=3%）
                if amp_info.get("has_t_opportunity", False):
                    filtered_t_trades.append({
                        "stock_code": code,
                        "stock_name": item.get("name") or pos.get("name", ""),
                        "quantity": pos.get("available", 0),
                        "current_price": pos.get("current_price", 0),
                        "amplitude_pct": amp_info.get("amplitude_pct", 0),
                        "reason": item.get("reason", "AI建议做T"),
                    })
                else:
                    log.warning(f"AI 建议做T的 {code} 振幅不足({amp_info.get('amplitude_pct', 0):.2f}%)，已移除")
            else:
                log.warning(f"AI 做T建议的 {code} 不在持仓中，已移除")
        strategy_data["t_trade_list"] = filtered_t_trades

        # ── 整理买入列表（校验价格和资金）────────────────────
        buy_list = []
        total_buy_amount = 0
        enforce = final_config["enforce_params"]
        # 资金上限必须扣除冻结资金（已挂限价单占用），避免资金被双重占用
        effective_capital = real_available_capital
        max_total = effective_capital * (final_config["total_position_ratio"] if enforce else 1.0)
        max_single = account.initial_capital * (final_config["max_single_position_ratio"] if enforce else 1.0)
        min_buy = final_config["min_buy_amount"] if enforce else 1000

        for item in strategy_data.get("buy_list", []):
            code = item.get("code", "")
            price = item.get("price", 0)
            quantity = item.get("quantity", 0)

            # 使用实时价格覆盖 LLM 可能给出的不准确价格
            if code in hot_quotes:
                price = hot_quotes[code].get("price", price)

            if price <= 0 or quantity <= 0:
                continue

            # 数量规整：100的整数倍
            quantity = (quantity // 100) * 100
            if quantity <= 0:
                continue

            amount = price * quantity

            if enforce:
                # 总资金限制
                if total_buy_amount + amount > max_total:
                    can_amount = max_total - total_buy_amount
                    quantity = int(can_amount / price / 100) * 100
                    amount = price * quantity

                if quantity <= 0 or amount < min_buy:
                    continue

                # 单只限制
                if amount > max_single:
                    quantity = int(max_single / price / 100) * 100
                    amount = price * quantity

                if quantity <= 0 or amount < min_buy:
                    continue
            else:
                # AI 自主模式：仅做基础校验（不可超过实际可用资金）
                if amount < min_buy:
                    continue
                if total_buy_amount + amount > effective_capital:
                    can_amount = effective_capital - total_buy_amount
                    quantity = int(can_amount / price / 100) * 100
                    amount = price * quantity
                    if quantity <= 0:
                        continue

            buy_list.append({
                "code": code,
                "name": item.get("name", ""),
                "price": price,
                "quantity": quantity,
                "amount": amount,
                "position_type": item.get("position_type", "short"),
                "reason": item.get("reason", ""),
            })
            total_buy_amount += amount

        # ── 构建策略摘要 ────────────────────────────────────
        mode_label_map = {"intraday": "盘中即时", "next_day": "次日交易", "midday": "午间调整"}
        mode_label = mode_label_map.get(mode, mode)
        enforce_tag = "【按参数限制】" if enforce else "【AI自主模式】"
        strategy_summary = f"""【AI{mode_label}策略】{enforce_tag}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
📊 市场情绪: {strategy_data.get('market_sentiment', 'neutral')}
📈 {strategy_data.get('market_analysis', '')}

💰 可用资金: {available_capital:,.0f}元
📊 当前仓位: {account_info['position_ratio']}%
🎯 建议仓位: {strategy_data.get('position_ratio', 70)}%
⚙️ 模式: {enforce_tag.strip('【】')}

【买入计划】({len(buy_list)}只，共{total_buy_amount:,.0f}元)
"""
        for i, stock in enumerate(buy_list, 1):
            strategy_summary += (
                f"  {i}. {stock['code']} {stock.get('name', '')} "
                f"¥{stock['price']:.2f} × {stock['quantity']}股 = {stock['amount']:,.0f}元\n"
            )
            strategy_summary += f"     {stock.get('reason', '')}\n"

        # 合并预生成卖出信号（止损止盈）和AI建议卖出列表，去重（以 stock_code 为键）
        ai_sell_list = strategy_data.get("sell_list", [])
        merged_sell_by_code = {}
        for s in sell_signals:
            merged_sell_by_code[s["stock_code"]] = s
        for s in ai_sell_list:
            code = s.get("stock_code", "")
            if code and code not in merged_sell_by_code:
                merged_sell_by_code[code] = s
        merged_sell_list = list(merged_sell_by_code.values())

        if merged_sell_list:
            strategy_summary += f"\n【卖出计划】({len(merged_sell_list)}只)\n"
            for i, stock in enumerate(merged_sell_list, 1):
                strategy_summary += (
                    f"  {i}. {stock['stock_code']} {stock.get('stock_name', '')} "
                    f"¥{stock.get('current_price', 0):.2f} "
                    f"{stock.get('sell_reason', '')}\n"
                )

        if filtered_t_trades:
            strategy_summary += f"\n【做T计划】({len(filtered_t_trades)}只)\n"
            for i, stock in enumerate(filtered_t_trades, 1):
                strategy_summary += (
                    f"  {i}. {stock['stock_code']} {stock.get('stock_name', '')} "
                    f"振幅{stock.get('amplitude_pct', 0):.2f}% "
                    f"{stock.get('reason', '')}\n"
                )

        strategy_summary += f"\n⚠️ {strategy_data.get('risk_warning', '投资有风险，入市需谨慎')}\n"

        # ── 保存策略（次日模式标记为下一个交易日）─────────────
        if mode == "next_day":
            decision_date = AIStrategyGenerator._get_next_trade_date()
        else:
            decision_date = date.today().strftime("%Y-%m-%d")

        decision = db.query(AIStrategyDecision).filter(
            AIStrategyDecision.account_id == account_id,
            AIStrategyDecision.decision_date == decision_date,
            AIStrategyDecision.strategy_mode == mode,
        ).first()

        # manual 来源的策略状态为 manual（不自动执行），auto 来源为 pending（自动执行）
        initial_status = "manual" if source == "manual" else "pending"

        if decision:
            # 同模式策略 → 覆盖更新（无论执行状态）
            decision.market_sentiment = strategy_data.get("market_sentiment", "neutral")
            decision.position_ratio = strategy_data.get("position_ratio", 70)
            decision.buy_list = json.dumps(buy_list, ensure_ascii=False)
            decision.buy_count = len(buy_list)
            decision.sell_list = json.dumps(merged_sell_list, ensure_ascii=False)
            decision.sell_count = len(merged_sell_list)
            decision.t_trade_list = json.dumps(filtered_t_trades, ensure_ascii=False)
            decision.t_trade_count = len(filtered_t_trades)
            decision.ai_analysis = strategy_data.get("market_analysis", "")
            decision.strategy_summary = strategy_summary
            decision.execution_status = initial_status
            decision.source = source
        else:
            decision = AIStrategyDecision(
                account_id=account_id,
                decision_date=decision_date,
                strategy_mode=mode,
                market_sentiment=strategy_data.get("market_sentiment", "neutral"),
                position_ratio=strategy_data.get("position_ratio", 70),
                buy_list=json.dumps(buy_list, ensure_ascii=False),
                buy_count=len(buy_list),
                sell_list=json.dumps(merged_sell_list, ensure_ascii=False),
                sell_count=len(merged_sell_list),
                t_trade_list=json.dumps(filtered_t_trades, ensure_ascii=False),
                t_trade_count=len(filtered_t_trades),
                ai_analysis=strategy_data.get("market_analysis", ""),
                strategy_summary=strategy_summary,
                execution_status=initial_status,
                source=source,
            )
            db.add(decision)

        db.commit()
        db.refresh(decision)

        # 记录 AI 对未成交委托的处置判断（保留/改价/放弃），便于追踪 AI 决策合理性
        # 对比规则：buy 委托看是否出现在新 buy_list（同价=保留，异价=改价，未出现=放弃）；
        # sell 委托看是否出现在 AI 原始 sell_list（出现=重新挂单，未出现=放弃）
        if pending_detail:
            new_buy_map = {item["code"]: item.get("price") for item in buy_list}
            ai_sell_codes = {item.get("code") for item in strategy_data.get("sell_list", []) if isinstance(item, dict)}
            disposition_lines = []
            for o in pending_detail:
                code = o["code"]
                name = o["name"]
                otype = o["type"]
                old_price = o["price"]
                if otype == "buy":
                    if code in new_buy_map:
                        new_price = new_buy_map[code]
                        if new_price is not None and abs(new_price - old_price) < 0.01:
                            action = "保留"
                        else:
                            action = f"改价({old_price:.2f}→{new_price:.2f})"
                    else:
                        action = "放弃"
                else:  # sell
                    action = "重新挂单" if code in ai_sell_codes else "放弃"
                disposition_lines.append(
                    f"  [{otype}] {name}({code}) 委托价{old_price:.2f} → {action}"
                )
            if disposition_lines:
                log.info(
                    f"AI 未成交委托处置判断 (mode={mode}, account={account_id}):\n"
                    + "\n".join(disposition_lines)
                )

        return {
            "success": True,
            "decision_id": decision.id,
            "decision_date": decision.decision_date,
            "mode": mode,
            "is_trading_time": is_trading,
            "market_sentiment": strategy_data.get("market_sentiment", "neutral"),
            "position_ratio": decision.position_ratio,
            "market_analysis": {
                "sentiment": strategy_data.get("market_sentiment", "neutral"),
                "analysis": strategy_data.get("market_analysis", ""),
            },
            "buy_list": buy_list,
            "sell_signals": sell_signals,
            "t_trade_list": filtered_t_trades,
            "t_trade_count": len(filtered_t_trades),
            "strategy_summary": strategy_summary,
            "available_capital": available_capital,
            "total_buy_amount": total_buy_amount,
        }
    
    @staticmethod
    def execute_strategy(db: Session, decision_id: int) -> Dict[str, Any]:
        """执行策略：买卖均走市价单，按执行时实时价成交

        - 非交易时段：返回 skipped="non_trading_hours"
        - 卖出：execute_market_order（市价单，实时价成交）
        - 买入：execute_market_order（市价单，实时价成交）
        - 重试上限：失败3次后标记 failed，不再被 _intraday_monitor 选中
        """
        from app.core.trading_calendar import is_trading_hours
        from app.services.order_service import OrderService
        from app.core.cache import cache_delete

        MAX_RETRY = 3

        decision = db.query(AIStrategyDecision).filter(
            AIStrategyDecision.id == decision_id
        ).first()

        if not decision:
            return {"success": False, "error": "策略不存在"}

        if decision.execution_status == "executed":
            return {"success": False, "error": "策略已执行"}

        if decision.retry_count >= MAX_RETRY:
            decision.execution_status = "failed"
            db.commit()
            return {"success": False, "error": f"策略重试次数已达上限({MAX_RETRY})次，标记为失败"}

        if not is_trading_hours():
            return {
                "success": False,
                "error": "非交易时段不自动执行，请等待交易时段（9:30-11:30, 13:00-15:00）",
                "skipped": "non_trading_hours",
            }

        results = {
            "success": True,
            "buy_orders": [],
            "sell_orders": [],
            "errors": [],
            "mode": "mixed",  # 混合模式：卖出=市价单立即成交，买入=限价委托单待撮合
        }

        # 1. 自动清空所有旧未成交委托单（新策略=全新起点，避免重复挂单；买卖双向都清）
        cancelled_old_orders = []
        try:
            from sqlalchemy import and_ as _and
            from app.models.sim_trading import SimOrder as _SimOrder
            old_pending = db.query(_SimOrder).filter(
                _and(
                    _SimOrder.account_id == decision.account_id,
                    _SimOrder.status.in_(["pending", "partial"]),
                )
            ).all()
            for old_order in old_pending:
                cancel_result = OrderService.cancel_order(db, old_order.id)
                cancelled_old_orders.append({
                    "order_id": old_order.id,
                    "stock_code": old_order.stock_code,
                    "order_type": old_order.order_type,
                    "success": cancel_result.get("success", False),
                    "error": cancel_result.get("error"),
                })
                if not cancel_result.get("success"):
                    results["errors"].append(
                        f"取消旧委托 {old_order.id}({old_order.order_type} {old_order.stock_code}) 失败: {cancel_result.get('error')}"
                    )
            if cancelled_old_orders:
                results["cancelled_old_orders"] = cancelled_old_orders
        except Exception as e:
            results["errors"].append(f"清空旧委托单异常: {str(e)}")

        # 2. 先卖出：市价单立即成交（止损/止盈必须确定性成交）
        sell_list = json.loads(decision.sell_list or "[]")
        _today_str_exec = date.today().strftime("%Y-%m-%d")
        for item in sell_list:
            try:
                # 重新查询持仓可用数量（防止策略生成后用户手动卖出导致数量不一致）
                sell_qty = item["quantity"]
                try:
                    from app.models.sim_trading import SimPosition as _SP
                    from sqlalchemy import and_ as _and
                    cur_pos = db.query(_SP).filter(_and(
                        _SP.account_id == decision.account_id,
                        _SP.stock_code == item["stock_code"],
                    )).first()
                    if cur_pos:
                        # T+1 保护：今日买入的持仓不可卖出
                        if cur_pos.buy_date == _today_str_exec:
                            results["errors"].append(
                                f"卖出{item['stock_code']}跳过: 今日买入(T+1)"
                            )
                            continue
                        sell_qty = min(sell_qty, cur_pos.available_quantity, cur_pos.total_quantity)
                except Exception:
                    pass

                if sell_qty <= 0:
                    results["errors"].append(
                        f"卖出{item['stock_code']}跳过: 可用数量为0"
                    )
                    continue

                result = OrderService.execute_market_order(
                    db=db,
                    account_id=decision.account_id,
                    stock_code=item["stock_code"],
                    stock_name=item.get("stock_name", ""),
                    order_type="sell",
                    quantity=sell_qty,
                    strategy_name="ai_strategy",
                    strategy_reason=item.get("sell_reason", ""),
                    order_source="ai_strategy",
                    auto_commit=True,
                )
                results["sell_orders"].append(result)
                if not result.get("success"):
                    results["errors"].append(
                        f"卖出{item['stock_code']}失败: {result.get('error', '未知错误')}"
                    )
            except Exception as e:
                results["errors"].append(f"卖出{item['stock_code']}异常: {str(e)}")

        # 2a. 执行做T计划（原子化先卖后买，写入做T记录）
        t_trade_list = json.loads(decision.t_trade_list or "[]")
        results["t_trades"] = []
        if t_trade_list:
            from app.services.t_trade_service import TTradeService
            for item in t_trade_list:
                stock_code = item.get("stock_code", "")
                if not stock_code:
                    continue
                # T+1 保护：检查持仓买入日期
                try:
                    from app.models.sim_trading import SimPosition as _SP
                    from sqlalchemy import and_ as _and
                    _t_pos = db.query(_SP).filter(_and(
                        _SP.account_id == decision.account_id,
                        _SP.stock_code == stock_code,
                    )).first()
                    if _t_pos and _t_pos.buy_date == _today_str_exec:
                        results["errors"].append(f"做T{stock_code}跳过: 今日买入(T+1)")
                        continue
                except Exception:
                    pass
                # 做T数量：使用持仓可用数量，或默认100股
                t_qty = item.get("quantity", 0)
                if t_qty <= 0:
                    t_qty = 100
                # 确保是100的整数倍
                t_qty = (t_qty // 100) * 100
                if t_qty <= 0:
                    results["errors"].append(f"做T{stock_code}跳过: 可用数量不足")
                    continue
                # 获取实时价格作为做T的买卖价格
                # 做T需要 sell_price > buy_price，基于振幅估算合理价差
                t_current_price = item.get("current_price", 0)
                t_amplitude = item.get("amplitude_pct", 3.0)
                if t_current_price > 0:
                    t_sell_price = t_current_price
                    t_buy_price = round(t_current_price * (1 - t_amplitude / 200), 2)
                else:
                    t_sell_price = 0
                    t_buy_price = 0
                try:
                    t_result = TTradeService.execute_t_trade(
                        db=db,
                        account_id=decision.account_id,
                        stock_code=stock_code,
                        buy_price=t_buy_price,
                        sell_price=t_sell_price,
                        quantity=t_qty,
                        strategy_reason=item.get("reason", "AI策略做T"),
                    )
                    results["t_trades"].append(t_result)
                    if not t_result.get("success"):
                        results["errors"].append(
                            f"做T{stock_code}失败: {t_result.get('error', '未知错误')}"
                        )
                except Exception as e:
                    results["errors"].append(f"做T{stock_code}异常: {str(e)}")

        # 3. 日内熔断检查：当日亏损 > 3% 时停止开新仓（卖出仍允许）
        buy_list = json.loads(decision.buy_list or "[]")
        if buy_list:
            from app.services.risk_manager import RiskManager
            if RiskManager.check_circuit_breaker(db, decision.account_id):
                decision.execution_status = "executed"  # 卖出已执行，标记为已执行
                decision.executed_at = datetime.now()
                db.commit()
                cache_delete(f"sim_account:{decision.account_id}", namespace="sim")
                results["circuit_breaker"] = True
                results["errors"].append("日内熔断触发，跳过买入（当日亏损>3%）")
                return results

        # 4. 过滤买入列表：排除今日买入的持仓（T+1冻结期不可再买同一只）
        held_today_codes = set()
        try:
            from app.models.sim_trading import SimPosition as _SimPosition
            from datetime import date as _date
            today_str = _date.today().strftime("%Y-%m-%d")
            held_today = db.query(_SimPosition.stock_code).filter(
                and_(
                    _SimPosition.account_id == decision.account_id,
                    _SimPosition.buy_date == today_str,
                )
            ).all()
            held_today_codes = {row[0] for row in held_today}
        except Exception:
            pass

        original_buy_count = len(buy_list)
        buy_list = [b for b in buy_list if b.get("code") not in held_today_codes]
        if len(buy_list) < original_buy_count:
            results["filtered_buy_count"] = original_buy_count - len(buy_list)
            results["filtered_reason"] = "排除今日买入持仓(T+1冻结)"

        # 4a. 获取实时价格，调整偏离过大的限价
        if buy_list:
            buy_codes = [b["code"] for b in buy_list]
            realtime_quotes = AIStrategyGenerator._get_realtime_quotes(buy_codes)
            adjusted_buy_list = []
            for item in buy_list:
                code = item["code"]
                q = realtime_quotes.get(code, {})
                current_price = q.get("price", 0)
                strategy_price = item.get("price", 0)
                if current_price > 0 and strategy_price > 0:
                    deviation = abs(current_price / strategy_price - 1)
                    if deviation > 0.02:
                        if deviation > 0.05:
                            results["errors"].append(
                                f"买入{code}跳过: 价格偏差{deviation*100:.1f}%过大(策略价{strategy_price:.2f} vs 现价{current_price:.2f})"
                            )
                            continue
                        results.setdefault("price_adjustments", []).append({
                            "code": code,
                            "old_price": strategy_price,
                            "new_price": round(current_price, 2),
                            "deviation_pct": round(deviation * 100, 1),
                        })
                        item = dict(item)
                        item["price"] = round(current_price, 2)
                        item["amount"] = item["price"] * item["quantity"]
                adjusted_buy_list.append(item)
            buy_list = adjusted_buy_list

        # 5. 买入：限价委托单（达到策略价格后自动成交）
        # P2-2 金字塔建仓检查：对已持有股票加仓时，必须浮盈才能加仓，加仓数量≤底仓1/3
        try:
            from app.models.sim_trading import SimPosition as _SP
            existing_positions = db.query(_SP).filter(
                _SP.account_id == decision.account_id
            ).all()
            pos_map = {p.stock_code: p for p in existing_positions}
        except Exception:
            pos_map = {}

        # P1-1 position_type 默认填充：AI 未指定时根据候选池 suggested_type 推断
        try:
            hot_stocks_cache = AIStrategyGenerator._get_hot_stocks() if not pos_map else []
            suggested_map = {s["code"]: s.get("suggested_type", "short") for s in hot_stocks_cache}
        except Exception:
            suggested_map = {}

        buy_success_count = 0
        buy_failed_items = []
        for item in buy_list:
            try:
                code = item["code"]

                # position_type 白名单校验：非法值降级为 "short"
                # 防止 AI 返回 "swing"/"day"/"短线" 等非法值污染数据库
                _valid_pos_types = {"short", "mid", "long"}
                _raw_pos_type = item.get("position_type")
                if not _raw_pos_type or _raw_pos_type not in _valid_pos_types:
                    # 非法或缺失 → 用候选池建议，再兜底 "short"
                    item["position_type"] = suggested_map.get(code, "short")
                else:
                    item["position_type"] = _raw_pos_type

                # 金字塔加仓检查
                if code in pos_map:
                    existing_pos = pos_map[code]
                    # 浮亏持仓不允许加仓（避免摊平成本陷阱）
                    if (existing_pos.profit_ratio or 0) < 0:
                        results["errors"].append(
                            f"金字塔加仓跳过 {code}: 浮亏{existing_pos.profit_ratio:.2f}% 不加仓"
                        )
                        continue
                    # 加仓数量 ≤ 底仓 1/3
                    max_add_qty = (existing_pos.total_quantity or 0) // 3
                    max_add_qty = (max_add_qty // 100) * 100
                    if max_add_qty < 100:
                        results["errors"].append(
                            f"金字塔加仓跳过 {code}: 底仓{existing_pos.total_quantity}股过小"
                        )
                        continue
                    if item["quantity"] > max_add_qty:
                        results.setdefault("pyramid_adjustments", []).append({
                            "code": code,
                            "original_qty": item["quantity"],
                            "adjusted_qty": max_add_qty,
                            "reason": f"底仓{existing_pos.total_quantity}股1/3限制",
                        })
                        item = dict(item)
                        item["quantity"] = max_add_qty

                result = OrderService.create_order(
                    db=db,
                    account_id=decision.account_id,
                    stock_code=item["code"],
                    stock_name=item.get("name", ""),
                    order_type="buy",
                    order_price=item["price"],
                    order_quantity=item["quantity"],
                    expire_type="day",
                    position_type=item.get("position_type", "short"),
                    strategy_name="ai_strategy",
                    strategy_reason=item.get("reason", ""),
                    order_source="ai_strategy",
                )
                results["buy_orders"].append(result)
                if result.get("success"):
                    buy_success_count += 1
                else:
                    buy_failed_items.append(item)
                    results["errors"].append(
                        f"买入{item['code']}失败: {result.get('error', '未知错误')}"
                    )
            except Exception as e:
                buy_failed_items.append(item)
                results["errors"].append(f"买入{item['code']}异常: {str(e)}")

        # 6. 执行结果处理
        if buy_list:
            if buy_success_count == 0:
                # 全部失败：重试
                decision.retry_count += 1
                if decision.retry_count >= MAX_RETRY:
                    decision.execution_status = "failed"
                else:
                    decision.execution_status = "pending"
                db.commit()
                cache_delete(f"sim_account:{decision.account_id}", namespace="sim")
                results["success"] = False
                results["error"] = f"买入全部失败，重试 {decision.retry_count}/{MAX_RETRY}"
                return results
            elif buy_failed_items:
                # 部分成功：保留失败项为 pending，继续重试
                remaining_buys = [{
                    "code": item["code"],
                    "name": item.get("name", ""),
                    "price": item["price"],
                    "quantity": item["quantity"],
                    "amount": item.get("amount", item["price"] * item["quantity"]),
                    "position_type": item.get("position_type", "short"),
                    "reason": item.get("reason", ""),
                } for item in buy_failed_items]

                decision.buy_list = json.dumps(remaining_buys, ensure_ascii=False)
                decision.buy_count = len(remaining_buys)
                decision.sell_list = "[]"
                decision.sell_count = 0
                decision.retry_count += 1
                if decision.retry_count >= MAX_RETRY:
                    decision.execution_status = "failed"
                else:
                    decision.execution_status = "pending"
                db.commit()
                cache_delete(f"sim_account:{decision.account_id}", namespace="sim")
                results["partial_success"] = True
                results["remaining_buys"] = len(remaining_buys)
                results["success"] = True
                return results

        # 7. 成功则标记 executed
        # 把执行日志（金字塔调整/错误）追加到 strategy_summary，便于前端可视化
        exec_log_lines = []
        pyramid_adjustments = results.get("pyramid_adjustments") or []
        if pyramid_adjustments:
            exec_log_lines.append("【金字塔加仓调整】")
            for adj in pyramid_adjustments:
                exec_log_lines.append(
                    f"  • {adj.get('code','')}: {adj.get('original_qty',0)}→{adj.get('adjusted_qty',0)}股 ({adj.get('reason','')})"
                )
        errors = results.get("errors") or []
        # 过滤掉买入失败这类已在前段处理的错误，只展示有价值的执行日志
        valuable_errors = [e for e in errors if "金字塔加仓跳过" in str(e) or "网格" in str(e) or "T+" in str(e)]
        if valuable_errors:
            exec_log_lines.append("【执行提示】")
            for e in valuable_errors[:10]:
                exec_log_lines.append(f"  • {e}")
        if exec_log_lines:
            exec_log_text = "\n".join(exec_log_lines)
            decision.strategy_summary = (decision.strategy_summary or "") + "\n\n" + exec_log_text

        decision.execution_status = "executed"
        decision.executed_at = datetime.now()
        db.commit()

        cache_delete(f"sim_account:{decision.account_id}", namespace="sim")

        return results
    
    @staticmethod
    def get_strategy_history(db: Session, account_id: int, limit: int = 30) -> List[Dict]:
        """获取策略历史"""
        decisions = db.query(AIStrategyDecision).filter(
            AIStrategyDecision.account_id == account_id
        ).order_by(AIStrategyDecision.decision_date.desc()).limit(limit).all()

        return [
            {
                "id": d.id,
                "decision_date": d.decision_date,
                "strategy_mode": d.strategy_mode or "intraday",
                "market_sentiment": d.market_sentiment,
                "position_ratio": d.position_ratio,
                "short_term_ratio": getattr(d, "short_term_ratio", None),
                "mid_term_ratio": getattr(d, "mid_term_ratio", None),
                "long_term_ratio": getattr(d, "long_term_ratio", None),
                "buy_count": d.buy_count,
                "sell_count": d.sell_count,
                "t_trade_count": getattr(d, "t_trade_count", 0) or 0,
                "execution_status": d.execution_status,
                "strategy_summary": d.strategy_summary,
                "created_at": d.created_at.strftime("%Y-%m-%d %H:%M:%S") if d.created_at else None,
                "executed_at": d.executed_at.strftime("%Y-%m-%d %H:%M:%S") if d.executed_at else None,
            }
            for d in decisions
        ]