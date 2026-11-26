"""AI股票推荐服务 — 量化筛选 + AI智能分析（带Redis缓存）"""
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.llm_service import llm_config, llm_client
from app.core.prompts import SYSTEM_PROMPT_STOCK_PICKS
from app.models.ai_stock_pick import AIStockPick
from app.core.trading_calendar import get_last_trade_date
from app.core.cache import cache_get, cache_set, NS_STRATEGY
from app.services.strategy_backtester import BacktestFactorCalculator

logger = logging.getLogger(__name__)

# 缓存TTL配置（秒）
_AI_MARKET_DATA_TTL = 3600  # 市场数据1小时
_AI_CANDIDATES_TTL = 1800   # 候选池30分钟


def _safe_float(v, default=0.0):
    """安全转换为 float，处理东财返回的 '-'/None/空串（亏损股 PE 字段常为 '-'）"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s == '-' or s.upper() == 'NULL':
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _repair_json(text):
    """修复LLM输出的常见JSON格式问题

    注意：仅修复结构问题（code fence / 尾随逗号 / 括号平衡），不做单引号→双引号的
    全局替换，因为中文内容中的撇号会被误伤。
    """
    if not text:
        return text
    # Remove markdown code fences
    text = _RE_CODE_FENCE_OPEN.sub("", text.strip())
    text = _RE_CODE_FENCE_CLOSE.sub("", text.strip())

    # Fix trailing commas in objects/arrays
    text = _RE_TRAILING_COMMA.sub(r"\1", text)

    # Ensure balanced braces
    open_braces = text.count("{") - text.count("}")
    close_brackets = text.count("[") - text.count("]")
    if open_braces > 0:
        text += "}" * open_braces
    if close_brackets > 0:
        text += "]" * close_brackets

    return text


def _safe_json_loads(text, default=None):
    """安全解析JSON，带自动修复"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        try:
            repaired = _repair_json(text)
            return json.loads(repaired)
        except Exception:
            logger.warning(f"JSON解析失败且无法修复，返回默认值")
            return default if default is not None else {}


PROMPT_VERSION = "v1.1"  # v1.1: 修复 PE/PB '-' 处理、正则兼容中文括号、降级标识透传


# 预编译热路径正则（避免在循环/高频调用路径上重复编译）
_RE_CODE_FENCE_OPEN = re.compile(r"^```json\s*", re.MULTILINE)
_RE_CODE_FENCE_CLOSE = re.compile(r"```$", re.MULTILINE)
_RE_TRAILING_COMMA = re.compile(r",\s*([}\]])")
# 策略明细解析：**1. 名称 (代码)** / **1. 名称（代码）**，代码允许字母+数字
_RE_STRATEGY_HEADER = re.compile(rf'(?:^|\n)\*\*\d+\.\s*(.+?)\s*[（(]\s*([A-Za-z0-9]+)\s*[）)]\*\*')
# 策略块内每行处理：去 emoji 标签 / 去字段名前缀
_RE_LINE_EMOJI_PREFIX = re.compile(r'^-\s*[^\u4e00-\u9fa5A-Za-z]+\s*')
_RE_LINE_DASH_PREFIX = re.compile(r'^-\s*')
_RE_LINE_FIELD_PREFIX = re.compile(r'^[^：:]*[：:]\s*')




def _enhance_with_backtest(candidates: list, top_n: int = 20) -> list:
    """Enhance candidate scores with backtest verification results
    
    For each candidate stock, run a quick backtest and adjust the score.
    This provides historical validation for AI recommendations.
    """
    if not candidates:
        return candidates
    
    try:
        # Extract stock codes
        stock_codes = [c.get('code') for c in candidates[:top_n] if c.get('code')]
        
        if not stock_codes:
            return candidates
        
        # Run batch backtest verification (cached, fast)
        bt_factors = BacktestFactorCalculator.compute_batch_backtest_factors(
            stock_codes, strategy_name='macd', days=120
        )
        
        # Enhance scores with backtest data
        for candidate in candidates[:top_n]:
            code = candidate.get('code')
            if code and code in bt_factors:
                bt_data = bt_factors[code]
                original_score = candidate.get('score', 50)
                bt_score = bt_data.get('backtest_score', 50)
                
                # Blend scores: 70% technical + 30% backtest
                enhanced_score = round(original_score * 0.7 + bt_score * 0.3)
                candidate['score'] = min(100, max(0, enhanced_score))
                candidate['backtest_verified'] = True
                candidate['backtest_score'] = bt_score
                candidate['bt_sharpe'] = bt_data.get('sharpe_ratio', 0)
                candidate['bt_win_rate'] = bt_data.get('win_rate', 50)
            else:
                candidate['backtest_verified'] = False
        
        # Sort by enhanced score
        candidates.sort(key=lambda x: x.get('score', 0), reverse=True)
        
    except Exception as e:
        logger.warning(f"Backtest enhancement failed: {e}")
    
    return candidates


class AIStockPickService:
    """AI股票推荐服务"""

    # ── 查询接口 ────────────────────────────────────────

    def list_picks(self, db: Session, days: int = 30) -> list[dict]:
        """获取最近N天的推荐列表"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        picks = (
            db.query(AIStockPick)
            .filter(AIStockPick.pick_date >= cutoff)
            .order_by(AIStockPick.pick_date.desc())
            .all()
        )
        return [self._to_dict(p) for p in picks]

    def get_latest_pick(self, db: Session) -> Optional[dict]:
        """获取最新一条推荐"""
        pick = (
            db.query(AIStockPick)
            .order_by(AIStockPick.pick_date.desc())
            .first()
        )
        if not pick:
            return None
        return self._to_detail_dict(pick)

    def get_pick_by_date(self, db: Session, pick_date: str) -> Optional[dict]:
        """获取指定日期的推荐详情"""
        pick = (
            db.query(AIStockPick)
            .filter(AIStockPick.pick_date == pick_date)
            .first()
        )
        if not pick:
            return None
        return self._to_detail_dict(pick)

    # ── 生成接口 ────────────────────────────────────────

    async def generate_picks(self, db: Session, pick_date: Optional[str] = None, force: bool = False) -> dict:
        """生成股票推荐"""
        if pick_date is None:
            # 非交易时间使用最近交易日
            trade_date = get_last_trade_date()
            pick_date = datetime.strptime(trade_date, '%Y%m%d').strftime('%Y-%m-%d')

        # 检查是否已存在（SQLite 不支持 with_forupdate，直接查询）
        existing = (
            db.query(AIStockPick)
            .filter(AIStockPick.pick_date == pick_date)
            .first()
        )
        
        if existing and existing.status == "completed" and not force:
            logger.info(f"股票推荐 {pick_date} 已存在，跳过生成")
            return self._to_dict(existing)
        if existing and force:
            logger.info(f"强制覆盖 {pick_date} 的已有推荐")

        # 标记为生成中
        is_new = False
        if existing:
            existing.status = "generating"
            existing.error_msg = None
        else:
            is_new = True
            existing = AIStockPick(
                pick_date=pick_date,
                status="generating",
            )
            db.add(existing)
        
        try:
            db.flush()
        except Exception as e:
            # flush 失败说明 session 状态已异常，必须 rollback 后重新创建记录，否则后续 commit 必然失败
            logger.warning(f"flush生成中状态失败，执行rollback: {e}")
            try:
                db.rollback()
            except Exception:
                pass
            # rollback 后重新插入一条 generating 记录
            existing = AIStockPick(
                pick_date=pick_date,
                status="generating",
            )
            db.add(existing)
            try:
                db.flush()
            except Exception as flush_err:
                logger.error(f"rollback 后重新 flush 仍失败: {flush_err}")

        try:
            # 1. 获取市场数据
            logger.info(f"开始生成 {pick_date} 股票推荐...")
            market_data = self._collect_market_data(pick_date)
            existing.market_data = json.dumps(market_data, ensure_ascii=False)
            # 2. 量化筛选候选池（_screen_candidates 内部已截断到 TOP 20，无需二次截断）
            candidates = self._screen_candidates(market_data)

            # 3. AI生成推荐
            picks_data = await self._ai_generate_picks(candidates, market_data)
            # 标记是否为量化兜底（LLM不可用或调用失败）
            is_fallback = picks_data.get('is_fallback', False)
            existing.picks_data = json.dumps(picks_data, ensure_ascii=False)

            # 4. 生成AI报告文本（优先使用LLM生成的完整报告）
            ai_full_report = picks_data.get('ai_full_report', '')
            if ai_full_report and len(ai_full_report) > 200:
                ai_report = ai_full_report
            else:
                ai_report = self._build_ai_report(pick_date, picks_data, market_data)
            # 量化兜底时在报告头部追加降级标识
            if is_fallback and ai_report and '量化兜底' not in ai_report:
                ai_report = ai_report.replace(
                    f"# 🎯 {pick_date} AI股票推荐报告\n",
                    f"# 🎯 {pick_date} AI股票推荐报告\n\n> ⚠️ **降级提示**：LLM 服务暂不可用，本报告为量化评分自动生成的兜底推荐。\n",
                    1,
                )
            existing.ai_report = ai_report

            # 5. 保存
            existing.status = "completed"
            existing.prompt_version = PROMPT_VERSION
            existing.generated_at = datetime.now()
            
            try:
                db.commit()
            except Exception as commit_err:
                logger.warning(f"commit失败，尝试rollback后重新保存: {commit_err}")
                db.rollback()
                # 重新查询最新记录，避免StaleDataError
                existing = db.query(AIStockPick).filter(AIStockPick.pick_date == pick_date).first()
                if existing:
                    existing.market_data = json.dumps(market_data, ensure_ascii=False)
                    existing.picks_data = json.dumps(picks_data, ensure_ascii=False)
                    existing.ai_report = ai_report
                    existing.status = "completed"
                    existing.prompt_version = PROMPT_VERSION
                    existing.generated_at = datetime.now()
                else:
                    existing = AIStockPick(
                        pick_date=pick_date,
                        market_data=json.dumps(market_data, ensure_ascii=False),
                        picks_data=json.dumps(picks_data, ensure_ascii=False),
                        ai_report=ai_report,
                        status="completed",
                        prompt_version=PROMPT_VERSION,
                        generated_at=datetime.now(),
                    )
                    db.add(existing)
                db.commit()

            logger.info(f"{pick_date} 股票推荐生成完成")
            return self._to_dict(existing)

        except Exception as e:
            logger.error(f"生成 {pick_date} 股票推荐失败: {e}", exc_info=True)
            try:
                db.rollback()
            except Exception:
                pass
            # 重新查询记录以设置失败状态
            try:
                existing = db.query(AIStockPick).filter(AIStockPick.pick_date == pick_date).first()
                if existing:
                    existing.status = "failed"
                    existing.error_msg = str(e)[:500]
                    db.commit()
            except Exception as inner_e:
                logger.warning(f"保存失败状态也出错: {inner_e}")
                try:
                    db.rollback()
                except Exception:
                    pass
            raise

    def _collect_market_data(self, pick_date: str) -> dict:
        """收集市场数据（复用现有服务，带Redis缓存）。

        注意：市场数据和个股行情只能获取实时/最新数据，不支持历史日期。
        非当日时会在结果中标注 data_source_note 提醒 LLM。
        """
        cache_key = f"ai_market:{pick_date}"
        cached = cache_get(cache_key, NS_STRATEGY)
        if cached:
            return cached

        from app.services.market_service import MarketService
        from app.core.data_sources import EastMoneySource

        market = MarketService()
        today = datetime.now().strftime("%Y-%m-%d")
        target_date = pick_date[:10]

        # 获取市场情绪
        sentiment = market.get_daily_report(style="detailed", fmt="json")

        # 获取全市场行情（东财/腾讯财经）
        raw_quotes = EastMoneySource.get_full_market() or []

        # 转换为统一格式 {code, name, price, change_pct, amount}（使用 _safe_float 处理 '-'/None）
        quotes = [
            {
                "code": q.get("f12", ""),
                "name": q.get("f14", ""),
                "price": _safe_float(q.get("f2")),
                "change_pct": _safe_float(q.get("f3")),
                "amount": _safe_float(q.get("f10")),
            }
            for q in raw_quotes if q.get("f12") and _safe_float(q.get("f2")) > 0
        ]

        # 获取热门股票（成交额TOP50）
        active_quotes = sorted(quotes, key=lambda x: x.get('amount', 0), reverse=True)[:50]

        # 获取板块轮动数据（行业涨幅TOP10）
        sector_data = {}
        try:
            sectors = market.get_sectors(sector_type='industry', top=10)
            if sectors and sectors.get('sectors'):
                sector_data['top_sectors'] = [
                    {
                        'name': s['name'],
                        'change_pct': s.get('change_pct', 0),
                        'flow_net': s.get('flow_net', 0),
                        'lead_stock': s.get('lead_stock', ''),
                    }
                    for s in sectors['sectors'][:10]
                ]
        except Exception as e:
            logger.warning(f"获取板块轮动数据失败: {e}")

        # 获取北向资金流向
        northbound_data = {}
        try:
            nf = market.get_northbound_flow()
            if nf and nf.get('summary'):
                northbound_data = nf['summary']
        except Exception as e:
            logger.warning(f"获取北向资金数据失败: {e}")

        result = {
            "pick_date": pick_date,
            "sentiment": sentiment,
            "sector_rotation": sector_data,
            "northbound_flow": northbound_data,
            "active_stocks": [
                {
                    "code": q["code"],
                    "name": q["name"],
                    "price": q["price"],
                    "change_pct": q["change_pct"],
                    "amount": q["amount"],
                }
                for q in active_quotes
            ],
        }

        # 非当日时标注数据来源，避免 LLM 误用
        if target_date != today:
            result["data_source_note"] = (
                f"市场数据和个股行情为最新可用数据（{today}），非 {target_date} 的历史数据"
            )

        # 写入Redis缓存
        cache_set(cache_key, result, ttl=_AI_MARKET_DATA_TTL, namespace=NS_STRATEGY)
        # _raw_quotes 不进缓存，作为运行时属性传递给 _screen_candidates 复用
        result["_raw_quotes"] = raw_quotes
        return result

    def _screen_candidates(self, market_data: dict) -> dict:
        """量化筛选候选池（带Redis缓存）。

        注意：个股行情和K线数据只能获取实时/最新数据，不支持历史日期回测。
        market_data 可携带已拉取的 raw_quotes（来自 _collect_market_data），避免重复拉取。
        """
        cache_key = f"ai_candidates:{market_data.get('pick_date', '')}"
        cached = cache_get(cache_key, NS_STRATEGY)
        if cached:
            return cached

        from app.core.data_sources import EastMoneySource
        from app.core.pytdx_source import pytdx_data

        pick_date = market_data.get("pick_date", "")
        today = datetime.now().strftime("%Y-%m-%d")
        target_date = pick_date[:10] if pick_date else ""

        # 优先复用 _collect_market_data 已拉取的行情数据（避免重复调用 get_full_market）
        raw_quotes = market_data.get("_raw_quotes")
        if raw_quotes is None:
            raw_quotes = EastMoneySource.get_full_market() or []

        # 构建 name_map + 统一格式（PE/PB 使用 _safe_float 处理 '-' 字符串）
        quotes = [
            {
                "code": q.get("f12", ""),
                "name": q.get("f14", ""),
                "price": _safe_float(q.get("f2")),
                "change_pct": _safe_float(q.get("f3")),
                "amount": _safe_float(q.get("f10")),
                "pe_ttm": _safe_float(q.get("f16")),
                "pb": _safe_float(q.get("f17")),
                "industry": q.get("f21", "") or "",
                "main_net_inflow": _safe_float(q.get("f62")),
            }
            for q in raw_quotes if q.get("f12") and _safe_float(q.get("f2")) > 0
        ]
        name_map = {q["code"]: q["name"] for q in quotes}
        industry_map = {q["code"]: q.get("industry", "") for q in quotes}

        # 筛选活跃股：排除ST、价格为0、停牌股票（成交量为0）
        active = [
            q for q in quotes
            if not q['name'].startswith(('ST', '*ST'))
            and q['price'] > 0
            and q.get('amount', 0) > 0  # 排除停牌股票（成交额为0）
        ]

        # 进一步过滤：排除涨跌幅异常的股票（新股上市首日 / 科创板创业板允许更大涨跌幅）
        # 主板新股首日 +44%，创业板/科创板新股前5日不设涨跌幅；阈值放宽到 44% 避免误杀
        filtered = [
            q for q in active
            if abs(q.get('change_pct', 0)) < 44
        ]

        # 限制数量避免超时（按成交额排序取前300）
        scan_quotes = sorted(filtered, key=lambda x: x.get('amount', 0), reverse=True)[:300]
        codes = [q['code'] for q in scan_quotes]

        # 并行获取K线（pytdx直连，不封IP）。MA60 需要60根K线，30根K线足够覆盖短线 + 中长线评分的所有因子
        # max_workers=16：pytdx 每线程独立连接，提升吞吐量（前 useCachedFetch 全局并发上限同步为 16）
        kline_map = pytdx_data.get_batch_klines(codes, count=60, max_workers=16)

        short_candidates = []
        long_candidates = []
        # 统计被K线数据不足跳过的股票（用于日志可观测性）
        skipped_short_kline_short = 0   # 短线因K线<26跳过
        skipped_long_kline_short = 0    # 中长线因K线<60跳过（含次新股）

        for q in scan_quotes:
            code = q['code']
            bars = kline_map.get(code, [])
            # 短线: MACD=26根、KDJ迭代=9根、MA20=20根，至少26根
            # 中长线: MA60=60根，至少60根
            if not bars or len(bars) < 26:
                skipped_short_kline_short += 1
                continue

            closes = [b['close'] for b in bars]
            volumes = [b.get('volume', 0) for b in bars]
            highs = [b['high'] for b in bars]
            lows = [b['low'] for b in bars]

            # 短线评分
            short_result = self._calc_short_score(q, closes, volumes, highs, lows)
            if short_result['score'] >= 40:
                short_candidates.append({
                    'code': code,
                    'name': name_map.get(code, code),
                    'price': q.get('price', 0),
                    'change_pct': q.get('change_pct', 0),
                    'amount': q.get('amount', 0),
                    'pe_ttm': q.get('pe_ttm', 0),
                    'pb': q.get('pb', 0),
                    'industry': industry_map.get(code, ''),
                    'main_net_inflow': q.get('main_net_inflow', 0),
                    'score': short_result['score'],
                    'reasons': short_result['reasons'],
                    'score_breakdown': short_result.get('breakdown', {}),
                })

            # 中长线评分（需要60根K线支持MA60）
            if len(closes) < 60:
                skipped_long_kline_short += 1
                continue
            long_result = self._calc_long_score(q, closes, volumes)
            if long_result['score'] >= 40:
                long_candidates.append({
                    'code': code,
                    'name': name_map.get(code, code),
                    'price': q.get('price', 0),
                    'change_pct': q.get('change_pct', 0),
                    'amount': q.get('amount', 0),
                    'pe_ttm': q.get('pe_ttm', 0),
                    'pb': q.get('pb', 0),
                    'industry': industry_map.get(code, ''),
                    'main_net_inflow': q.get('main_net_inflow', 0),
                    'score': long_result['score'],
                    'reasons': long_result['reasons'],
                    'score_breakdown': long_result.get('breakdown', {}),
                })

        if skipped_short_kline_short > 0 or skipped_long_kline_short > 0:
            logger.info(
                f"候选池筛选：扫描{len(scan_quotes)}只，K线<26根跳过{skipped_short_kline_short}只（含次新股），"
                f"K线<60根跳过{skipped_long_kline_short}只"
            )

        # 按评分排序，取TOP20
        short_candidates.sort(key=lambda x: x['score'], reverse=True)
        long_candidates.sort(key=lambda x: x['score'], reverse=True)

        result = {
            'short_candidates': short_candidates[:20],
            'long_candidates': long_candidates[:20],
            'scan_count': len(scan_quotes),
            'short_kline_skip': skipped_short_kline_short,
            'long_kline_skip': skipped_long_kline_short,
        }

        # 非当日时标注数据来源
        if target_date and target_date != today:
            result["data_source_note"] = (
                f"候选池基于最新行情数据筛选（{today}），非 {target_date} 的历史回测结果。"
                f"如需准确历史回测，请使用 backfill 接口。"
            )

        # 写入Redis缓存
        cache_set(cache_key, result, ttl=_AI_CANDIDATES_TTL, namespace=NS_STRATEGY)
        return result

    def _calc_short_score(self, quote: dict, closes: list, volumes: list, highs: list, lows: list) -> dict:
        """短线评分"""
        score = 50
        reasons = []
        breakdown = {'macd': 0, 'volume': 0, 'ma': 0, 'rsi': 0, 'kdj': 0, 'price_range': 0}

        price = quote.get('price', 0)
        change_pct = quote.get('change_pct', 0)

        # MACD金叉检测 (使用标准EMA)
        if len(closes) >= 26:
            ema12 = AIStockPickService._calc_ema(closes, 12)
            ema26 = AIStockPickService._calc_ema(closes, 26)
            dif = ema12 - ema26
            prev_closes = closes[:-1]
            prev_ema12 = AIStockPickService._calc_ema(prev_closes, 12) if len(prev_closes) >= 12 else ema12
            prev_ema26 = AIStockPickService._calc_ema(prev_closes, 26) if len(prev_closes) >= 26 else ema26
            prev_dif = prev_ema12 - prev_ema26
            if dif > 0 and prev_dif <= 0:
                score += 15
                reasons.append('MACD金叉')
                breakdown['macd'] = 15
            elif dif > prev_dif and dif > 0:
                score += 8
                reasons.append('MACD红柱放大')
                breakdown['macd'] = 8

        # 放量突破
        if len(volumes) >= 5:
            avg_vol = sum(volumes[-5:]) / 5
            if avg_vol > 0:
                vol_ratio = volumes[-1] / avg_vol
                if vol_ratio > 1.5 and change_pct > 2:
                    score += 12
                    reasons.append(f'放量{vol_ratio:.1f}倍')
                    breakdown['volume'] = 12
                elif vol_ratio > 1.2 and change_pct > 0:
                    score += 6
                    reasons.append('温和放量')
                    breakdown['volume'] = 6

        # 站上均线
        if len(closes) >= 20:
            ma5 = sum(closes[-5:]) / 5
            ma10 = sum(closes[-10:]) / 10
            ma20 = sum(closes[-20:]) / 20
            if closes[-1] > ma5 > ma10 > ma20:
                score += 12
                reasons.append('多头排列')
                breakdown['ma'] = 12
            elif closes[-1] > ma5 > ma10:
                score += 8
                reasons.append('短期多头')
                breakdown['ma'] = 8
            elif closes[-1] > ma5:
                score += 4
                reasons.append('站上MA5')
                breakdown['ma'] = 4

        # RSI超卖反弹
        rsi6 = self._calc_rsi(closes, 6)
        if rsi6 < 30:
            score += 10
            reasons.append('RSI超卖')
            breakdown['rsi'] = 10
        elif rsi6 < 40:
            score += 5
            reasons.append('RSI偏低')
            breakdown['rsi'] = 5

        # KDJ金叉 (标准迭代计算)
        if len(closes) >= 9 and len(highs) >= 9 and len(lows) >= 9:
            low9 = min(lows[-9:])
            high9 = max(highs[-9:])
            if high9 > low9:
                # 标准KDJ: 逐日迭代计算K/D值
                k_val = 50.0
                d_val = 50.0
                for i in range(8, len(closes)):
                    low_n = min(lows[i-8:i+1])
                    high_n = max(highs[i-8:i+1])
                    rsv = (closes[i] - low_n) / (high_n - low_n) * 100 if high_n > low_n else 50
                    k_val = 2/3 * k_val + 1/3 * rsv
                    d_val = 2/3 * d_val + 1/3 * k_val
                if k_val < 30 and d_val < 30 and k_val > d_val:
                    score += 8
                    reasons.append('KDJ低位金叉')
                    breakdown['kdj'] = 8

        # 涨跌幅适中
        if 0 < change_pct < 5:
            score += 5
            reasons.append('温和上涨')
            breakdown['price_range'] = 5
        elif change_pct > 7:
            score -= 3
            reasons.append('涨幅偏大')
            breakdown['price_range'] = -3

        return {'score': min(95, max(10, score)), 'reasons': reasons, 'breakdown': breakdown}

    def _calc_long_score(self, quote: dict, closes: list, volumes: list) -> dict:
        """中长线评分"""
        score = 50
        reasons = []
        breakdown = {'trend': 0, 'liquidity': 0, 'stability': 0, 'volume': 0, 'pe': 0, 'pb': 0}

        # 趋势向上
        if len(closes) >= 60:
            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / 60
            if closes[-1] > ma20 > ma60:
                score += 15
                reasons.append('趋势向上')
                breakdown['trend'] = 15
            elif closes[-1] > ma20:
                score += 8
                reasons.append('站上MA20')
                breakdown['trend'] = 8

        # 成交额适中（流动性好）
        amount_yi = quote.get('amount', 0) / 1e8
        if 2 < amount_yi < 30:
            score += 10
            reasons.append('流动性佳')
            breakdown['liquidity'] = 10
        elif amount_yi >= 30:
            score += 5
            reasons.append('大盘股')
            breakdown['liquidity'] = 5

        # 近期走势稳健
        if len(closes) >= 10:
            recent_change = (closes[-1] - closes[-10]) / closes[-10] * 100
            if -5 < recent_change < 10:
                score += 8
                reasons.append('走势稳健')
                breakdown['stability'] = 8
            elif recent_change >= 10:
                score += 3
                reasons.append('近期强势')
                breakdown['stability'] = 3

        # 量能配合
        if len(volumes) >= 5:
            avg_vol = sum(volumes[-5:]) / 5
            if avg_vol > 0:
                vol_ratio = volumes[-1] / avg_vol
                if 0.8 <= vol_ratio <= 1.5:
                    score += 5
                    reasons.append('量能平稳')
                    breakdown['volume'] = 5

        # PE估值（TTM，0-30倍加分，负值/0值视为亏损不加分）
        pe_ttm = quote.get('pe_ttm', 0) or 0
        if 0 < pe_ttm <= 15:
            score += 10
            reasons.append(f'PE{pe_ttm:.1f}低估')
            breakdown['pe'] = 10
        elif 15 < pe_ttm <= 30:
            score += 6
            reasons.append(f'PE{pe_ttm:.1f}合理')
            breakdown['pe'] = 6
        elif pe_ttm > 50:
            score -= 3
            reasons.append(f'PE{pe_ttm:.1f}偏高')
            breakdown['pe'] = -3
        elif pe_ttm <= 0:
            # 亏损股：既不加分也不扣分，但标记原因（区分"周期股亏损"与"基本面恶化"由 LLM 后续判断）
            reasons.append('PE亏损')
            breakdown['pe'] = 0

        # PB估值（0-3倍加分，负值/0值不加分）
        pb = quote.get('pb', 0) or 0
        if 0 < pb <= 1.5:
            score += 8
            reasons.append(f'PB{pb:.1f}破净')
            breakdown['pb'] = 8
        elif 1.5 < pb <= 3:
            score += 4
            reasons.append(f'PB{pb:.1f}合理')
            breakdown['pb'] = 4
        elif pb > 6:
            score -= 2
            reasons.append(f'PB{pb:.1f}偏高')
            breakdown['pb'] = -2

        return {'score': min(95, max(10, score)), 'reasons': reasons, 'breakdown': breakdown}

    @staticmethod
    def _calc_ema(data: list, period: int) -> float:
        """计算指数移动平均 (EMA)"""
        if len(data) < period:
            return sum(data) / len(data) if data else 0
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period  # SMA 作为初始值
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        return ema


    @staticmethod
    def _calc_rsi(closes: list, period: int = 6) -> float:
        """计算RSI"""
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(d, 0) for d in deltas]
        losses = [-min(d, 0) for d in deltas]
        avg_g = sum(gains[-period:]) / period
        avg_l = sum(losses[-period:]) / period
        rs_val = avg_g / max(avg_l, 0.01)
        return min(100, max(0, 100 - 100 / (1 + rs_val)))

    async def _ai_generate_picks(self, candidates: dict, market_data: dict) -> dict:
        """AI生成股票推荐

        返回的 dict 包含 is_fallback 字段：True 表示 LLM 不可用/异常，使用量化兜底。
        前端可据此显示降级标识。
        """
        if not llm_config.enabled or not llm_config.model:
            logger.warning("LLM未启用，使用基础推荐")
            picks = self._fallback_picks(candidates)
            picks['is_fallback'] = True
            picks['fallback_reason'] = 'llm_disabled'
            return picks

        # 构建市场背景
        sentiment = market_data.get('sentiment', {})
        indices = sentiment.get('indices', {})
        breadth = sentiment.get('breadth', {})

        market_context = json.dumps({
            'date': market_data.get('pick_date'),
            'score': sentiment.get('score', 50),
            'signal': sentiment.get('signal', '中性'),
            'indices': {
                'shanghai': indices.get('shanghai', {}).get('change_pct', 0),
                'shenzhen': indices.get('shenzhen', {}).get('change_pct', 0),
                'chiNext': indices.get('chiNext', {}).get('change_pct', 0),
            },
            'breadth': breadth,
        }, ensure_ascii=False)

        # 构建板块轮动摘要
        sector_rotation = market_data.get('sector_rotation', {})
        sector_summary = ""
        if sector_rotation and sector_rotation.get('top_sectors'):
            tops = sector_rotation['top_sectors']
            sector_lines = [f"- {s['name']}: 涨幅{s['change_pct']:+.2f}%, 资金净流{s['flow_net']:+.2f}亿, 龙头{s.get('lead_stock', '-')}" for s in tops]
            sector_summary = "## 板块轮动\n" + "\n".join(sector_lines) + "\n"

        # 构建北向资金摘要
        northbound = market_data.get('northbound_flow', {})
        northbound_summary = ""
        if northbound:
            hgt = northbound.get('hgt_latest', 0)
            sgt = northbound.get('sgt_latest', 0)
            northbound_summary = f"## 北向资金\n沪股通: {hgt:+.2f}亿, 深股通: {sgt:+.2f}亿\n"

        # 构建候选数据
        candidate_data = json.dumps({
            'short_candidates': candidates['short_candidates'][:15],
            'long_candidates': candidates['long_candidates'][:15],
        }, ensure_ascii=False)

        user_prompt = f"""请从以下候选股票池中，选出短线和中长线各10只推荐股票，并提供详细的操盘策略。

## 候选股票池
{candidate_data}

## 市场背景
{market_context}

{sector_summary}{northbound_summary}
请按照指定的格式输出完整的推荐报告，包含市场研判、推荐列表和操盘策略明细。注意候选股中的 industry 字段标识了所属行业，main_net_inflow 为主力资金净流入（万元），请结合板块轮动和资金流向进行综合分析。"""

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_STOCK_PICKS},
            {"role": "user", "content": user_prompt}
        ]

        try:
            resp = await llm_client.chat_completion(messages, tools=None)
            content = resp.get("content", "").strip()

            if not content or len(content) < 100:
                logger.warning("AI返回内容过短，使用基础推荐")
                picks = self._fallback_picks(candidates)
                picks['is_fallback'] = True
                picks['fallback_reason'] = 'content_too_short'
                return picks

            # 解析结构化数据（从AI报告中提取）
            picks = self._parse_ai_response(content, candidates)
            picks['ai_full_report'] = content
            picks['is_fallback'] = False
            return picks
        except Exception as e:
            logger.warning(f"AI生成推荐失败，回退到基础推荐: {e}")
            picks = self._fallback_picks(candidates)
            picks['is_fallback'] = True
            picks['fallback_reason'] = f'llm_error: {str(e)[:200]}'
            return picks

    def _parse_markdown_table(self, content: str, section_header: str) -> list[dict]:
        """从Markdown内容中解析指定章节的表格"""
        results = []
        idx = content.find(section_header)
        if idx < 0:
            return results

        rest = content[idx:]
        # Stop at next major section (## heading) to avoid crossing boundaries
        next_section = re.search(r'\n## [^#]', rest[1:])
        if next_section:
            rest = rest[:next_section.start() + 1]

        pipe_idx = rest.find('|')
        if pipe_idx < 0:
            return results

        table_block = rest[pipe_idx:]
        all_lines = [l.strip() for l in table_block.split(chr(10)) if "|" in l]

        # Filter out separator lines (only dashes, pipes, colons, spaces)
        data_lines = []
        for line in all_lines:
            if all(c in "-|: " for c in line.strip()):
                continue
            data_lines.append(line)

        if len(data_lines) < 2:
            return results

        headers = [h.strip() for h in data_lines[0].split("|") if h.strip()]

        for line in data_lines[1:]:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) < len(headers):
                continue
            row = {}
            for j, header in enumerate(headers):
                row[header] = cells[j] if j < len(cells) else ''
            results.append(row)

        return results


    def _parse_strategy_section(self, content: str) -> list[dict]:
        """解析操盘策略明细部分

        兼容半角 `(...)` 与全角 `（...）` 括号，以及可能带 SH/SZ 前缀的代码。
        """
        strategies = []
        # 支持：**1. 名称 (代码)** 或 **1. 名称（代码）**，代码允许字母+数字
        for match in _RE_STRATEGY_HEADER.finditer(content):
            name = match.group(1).strip()
            code = match.group(2).strip()

            start = match.end()
            end = content.find('\n**', start)
            if end == -1:
                end = len(content)
            block = content[start:end]

            strategy = {'name': name, 'code': code}

            for line in block.split('\n'):
                line = line.strip()
                if not line.startswith('-'):
                    continue
                # 去掉行首的 "- 📈 " 等 emoji 标签，提取后续文本
                text = _RE_LINE_EMOJI_PREFIX.sub('', line).strip()
                # 同时处理 "- 建仓区间: ..." 这种格式
                text = _RE_LINE_DASH_PREFIX.sub('', text).strip()
                # 去掉字段名前缀（"建仓区间: "、"止损位: " 等）
                text = _RE_LINE_FIELD_PREFIX.sub('', text).strip() if ('：' in text or ':' in text) else text

                if '建仓' in line:
                    strategy['entry_price'] = text
                elif '止损' in line:
                    strategy['stop_loss'] = text
                elif '目标' in line:
                    strategy['target_price'] = text
                elif '仓位' in line:
                    strategy['position'] = text
                elif '持股周期' in line or ('持股' in line and '周期' in line):
                    strategy['hold_days'] = text
                elif '卖出信号' in line:
                    strategy['sell_signal'] = text
                elif 'AI分析' in line or '🤖' in line:
                    strategy['ai_analysis'] = text

            strategies.append(strategy)

        return strategies

    def _parse_market_outlook(self, content: str) -> dict:
        """解析市场研判部分"""
        outlook = {
            'trend': '震荡',
            'risk_level': '中等',
            'suggested_position': '50-60%',
            'key_factors': [],
        }

        tables = self._parse_markdown_table(content, '市场研判')
        if tables:
            for row in tables:
                indicator = row.get('指标', '')
                value = row.get('判断', '')
                if '趋势' in indicator and value:
                    outlook['trend'] = value
                elif '风险' in indicator and value:
                    outlook['risk_level'] = value
                elif '仓位' in indicator and value:
                    outlook['suggested_position'] = value
                elif '关键' in indicator and value:
                    outlook['key_factors'] = [f.strip() for f in value.split('、') if f.strip()]

        return outlook

    def _parse_ai_response(self, content: str, candidates: dict) -> dict:
        """解析AI返回的推荐内容"""
        short_tables = self._parse_markdown_table(content, '短线推荐')
        long_tables = self._parse_markdown_table(content, '中长线推荐')

        all_strategies = self._parse_strategy_section(content)

        candidate_lookup = {}
        for c in candidates.get('short_candidates', []) + candidates.get('long_candidates', []):
            candidate_lookup[c['code']] = c

        short_picks = []
        if short_tables:
            for i, row in enumerate(short_tables[:10], 1):
                code = row.get('代码', '')
                name = row.get('名称', '')
                price_str = row.get('现价', '0')
                score_str = row.get('评分', '0')
                recommendation = row.get('推荐理由', '')

                try:
                    price = float(price_str) if price_str else 0
                except ValueError:
                    price = candidate_lookup.get(code, {}).get('price', 0)

                try:
                    score = int(score_str) if score_str else 0
                except ValueError:
                    score = candidate_lookup.get(code, {}).get('score', 50)

                strategy_info = {}
                for s in all_strategies:
                    if s.get('code') == code or s.get('name') == name:
                        strategy_info = s
                        break

                short_picks.append({
                    'rank': i,
                    'code': code,
                    'name': name,
                    'price': price,
                    'score': score,
                    'recommendation': recommendation,
                    'strategy': {
                        'entry_price': strategy_info.get('entry_price', f"{price*0.98:.2f}-{price*1.02:.2f}" if price else '-'),
                        'stop_loss': strategy_info.get('stop_loss', f"{price*0.95:.2f} (-5%)" if price else '-'),
                        'target_price': strategy_info.get('target_price', f"{price*1.10:.2f} (+10%)" if price else '-'),
                        'position': strategy_info.get('position', '半仓'),
                        'hold_days': strategy_info.get('hold_days', '3-5天'),
                        'sell_signal': strategy_info.get('sell_signal', '跌破MA10或MACD死叉'),
                    },
                    'ai_analysis': strategy_info.get('ai_analysis', f"技术面：{recommendation}。建议逢低关注。"),
                })
        else:
            for i, c in enumerate(candidates['short_candidates'][:10], 1):
                short_picks.append({
                    'rank': i,
                    'code': c['code'],
                    'name': c['name'],
                    'price': c['price'],
                    'score': c['score'],
                    'recommendation': '、'.join(c.get('reasons', [])[:3]),
                    'strategy': {
                        'entry_price': f"{c['price']*0.98:.2f}-{c['price']*1.02:.2f}",
                        'stop_loss': f"{c['price']*0.95:.2f} (-5%)",
                        'target_price': f"{c['price']*1.10:.2f} (+10%)",
                        'position': '半仓',
                        'hold_days': '3-5天',
                        'sell_signal': '跌破MA10或MACD死叉',
                    },
                    'ai_analysis': f"技术面：{'; '.join(c.get('reasons', [])[:3])}。建议逢低关注。",
                })

        long_picks = []
        if long_tables:
            for i, row in enumerate(long_tables[:10], 1):
                code = row.get('代码', '')
                name = row.get('名称', '')
                price_str = row.get('现价', '0')
                score_str = row.get('评分', '0')
                recommendation = row.get('推荐理由', '')
                fundamentals = row.get('基本面亮点', '') or ''

                try:
                    price = float(price_str) if price_str else 0
                except ValueError:
                    price = candidate_lookup.get(code, {}).get('price', 0)

                try:
                    score = int(score_str) if score_str else 0
                except ValueError:
                    score = candidate_lookup.get(code, {}).get('score', 50)

                strategy_info = {}
                for s in all_strategies:
                    if s.get('code') == code or s.get('name') == name:
                        strategy_info = s
                        break

                long_picks.append({
                    'rank': i,
                    'code': code,
                    'name': name,
                    'price': price,
                    'score': score,
                    'recommendation': recommendation,
                    'fundamentals': fundamentals or '需确认基本面',
                    'strategy': {
                        'entry_price': strategy_info.get('entry_price', f"{price*0.95:.2f}-{price*1.05:.2f}" if price else '-'),
                        'stop_loss': strategy_info.get('stop_loss', f"{price*0.90:.2f} (-10%)" if price else '-'),
                        'target_price': strategy_info.get('target_price', f"{price*1.25:.2f} (+25%)" if price else '-'),
                        'position': strategy_info.get('position', '15%'),
                        'hold_days': strategy_info.get('hold_days', '1-3个月'),
                        'sell_signal': strategy_info.get('sell_signal', '跌破MA20或趋势破坏'),
                    },
                    'ai_analysis': strategy_info.get('ai_analysis', f"趋势面：{recommendation}。适合中线布局。"),
                })
        else:
            for i, c in enumerate(candidates['long_candidates'][:10], 1):
                long_picks.append({
                    'rank': i,
                    'code': c['code'],
                    'name': c['name'],
                    'price': c['price'],
                    'score': c['score'],
                    'recommendation': '、'.join(c.get('reasons', [])[:3]),
                    'fundamentals': '需确认基本面',
                    'strategy': {
                        'entry_price': f"{c['price']*0.95:.2f}-{c['price']*1.05:.2f}",
                        'stop_loss': f"{c['price']*0.90:.2f} (-10%)",
                        'target_price': f"{c['price']*1.25:.2f} (+25%)",
                        'position': '15%',
                        'hold_days': '1-3个月',
                        'sell_signal': '跌破MA20或趋势破坏',
                    },
                    'ai_analysis': f"趋势面：{'; '.join(c.get('reasons', [])[:3])}。适合中线布局。",
                })

        market_outlook = self._parse_market_outlook(content)

        return {
            'short_term': short_picks,
            'long_term': long_picks,
            'market_outlook': market_outlook,
        }


    def _fallback_picks(self, candidates: dict) -> dict:
        """LLM不可用时的基础推荐"""
        short_picks = []
        for i, c in enumerate(candidates['short_candidates'][:10], 1):
            short_picks.append({
                'rank': i,
                'code': c['code'],
                'name': c['name'],
                'price': c['price'],
                'score': c['score'],
                'recommendation': '、'.join(c.get('reasons', [])[:3]),
                'strategy': {
                    'entry_price': f"{c['price']*0.98:.2f}-{c['price']*1.02:.2f}",
                    'stop_loss': f"{c['price']*0.95:.2f} (-5%)",
                    'target_price': f"{c['price']*1.10:.2f} (+10%)",
                    'position': '半仓',
                    'hold_days': '3-5天',
                    'sell_signal': '跌破MA10',
                },
                'ai_analysis': 'LLM未启用，仅提供量化评分。',
            })

        long_picks = []
        for i, c in enumerate(candidates['long_candidates'][:10], 1):
            long_picks.append({
                'rank': i,
                'code': c['code'],
                'name': c['name'],
                'price': c['price'],
                'score': c['score'],
                'recommendation': '、'.join(c.get('reasons', [])[:3]),
                'fundamentals': '需人工确认',
                'strategy': {
                    'entry_price': f"{c['price']*0.95:.2f}-{c['price']*1.05:.2f}",
                    'stop_loss': f"{c['price']*0.90:.2f} (-10%)",
                    'target_price': f"{c['price']*1.25:.2f} (+25%)",
                    'position': '15%',
                    'hold_days': '1-3个月',
                    'sell_signal': '跌破MA20',
                },
                'ai_analysis': 'LLM未启用，仅提供量化评分。',
            })

        return {
            'short_term': short_picks,
            'long_term': long_picks,
            'market_outlook': {
                'trend': '震荡',
                'risk_level': '中等',
                'suggested_position': '50-60%',
                'key_factors': ['需人工确认'],
            },
            'ai_full_report': '',
        }


    def _build_ai_report(self, pick_date: str, picks_data: dict, market_data: dict) -> str:
        """构建AI推荐报告文本（当LLM报告不可用时的模板回退）"""
        lines = [
            f"# 🎯 {pick_date} AI股票推荐报告\n",
            "> 本报告由AI智能生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。\n",
            "---\n",
        ]

        outlook = picks_data.get('market_outlook', {})
        lines.append("## 📊 市场研判\n")
        lines.append("| 指标 | 判断 |")
        lines.append("|------|------|")
        lines.append(f"| 市场趋势 | {outlook.get('trend', '震荡')} |")
        lines.append(f"| 风险等级 | {outlook.get('risk_level', '中等')} |")
        lines.append(f"| 建议总仓位 | {outlook.get('suggested_position', '50-60%')} |")
        lines.append(f"| 关键因素 | {', '.join(outlook.get('key_factors', []))} |")
        lines.append("")

        short_term = picks_data.get('short_term', [])
        if short_term:
            lines.append("---\n")
            lines.append("## 🔥 短线推荐 TOP10\n")
            lines.append("| 排名 | 代码 | 名称 | 现价 | 评分 | 推荐理由 |")
            lines.append("|------|------|------|------|------|----------|")
            for s in short_term[:10]:
                lines.append(f"| {s['rank']} | {s['code']} | {s['name']} | {s['price']:.2f} | {s['score']} | {s['recommendation']} |")
            lines.append("")

        long_term = picks_data.get('long_term', [])
        if long_term:
            lines.append("---\n")
            lines.append("## 📈 中长线推荐 TOP10\n")
            lines.append("| 排名 | 代码 | 名称 | 现价 | 评分 | 推荐理由 |")
            lines.append("|------|------|------|------|------|----------|")
            for s in long_term[:10]:
                lines.append(f"| {s['rank']} | {s['code']} | {s['name']} | {s['price']:.2f} | {s['score']} | {s['recommendation']} |")
            lines.append("")

        lines.append("---\n")
        lines.append("## 📋 操盘策略明细\n")

        if short_term:
            lines.append("### 短线推荐策略\n")
            for s in short_term[:10]:
                st = s.get('strategy', {})
                lines.append(f"**{s['rank']}. {s['name']} ({s['code']})**")
                lines.append(f"- 📈 建仓区间: {st.get('entry_price', '-')}")
                lines.append(f"- 🛑 止损位: {st.get('stop_loss', '-')}")
                lines.append(f"- 🎯 目标位: {st.get('target_price', '-')}")
                lines.append(f"- 💰 仓位建议: {st.get('position', '-')}")
                lines.append(f"- 📅 持股周期: {st.get('hold_days', '-')}")
                lines.append(f"- 📤 卖出信号: {st.get('sell_signal', '-')}")
                lines.append(f"- 🤖 AI分析: {s.get('ai_analysis', '-')}")
                lines.append("")

        if long_term:
            lines.append("### 中长线推荐策略\n")
            for s in long_term[:10]:
                st = s.get('strategy', {})
                lines.append(f"**{s['rank']}. {s['name']} ({s['code']})**")
                lines.append(f"- 📈 建仓区间: {st.get('entry_price', '-')}")
                lines.append(f"- 🛑 止损位: {st.get('stop_loss', '-')}")
                lines.append(f"- 🎯 目标位: {st.get('target_price', '-')}")
                lines.append(f"- 💰 仓位建议: {st.get('position', '-')}")
                lines.append(f"- 📅 持股周期: {st.get('hold_days', '-')}")
                lines.append(f"- 📤 卖出信号: {st.get('sell_signal', '-')}")
                lines.append(f"- 🤖 AI分析: {s.get('ai_analysis', '-')}")
                lines.append("")

        lines.append("---\n")
        lines.append("## ⚠️ 风险提示\n")
        lines.append("1. 以上推荐由AI生成，仅供参考，不构成投资建议")
        lines.append("2. 股市有风险，投资需谨慎")
        lines.append("3. 请根据自身风险承受能力做出投资决策")
        lines.append("4. 建议设置止损，控制仓位")

        return "\n".join(lines)


    # ── 清理接口 ────────────────────────────────────────

    def cleanup_old_picks(self, db: Session, days: int = 30) -> int:
        """删除超过指定天数的推荐"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        old_picks = db.query(AIStockPick).filter(
            AIStockPick.pick_date < cutoff
        ).all()

        count = len(old_picks)
        if count > 0:
            for p in old_picks:
                db.delete(p)
            db.commit()
            logger.info(f"已清理 {count} 条过期股票推荐（早于 {cutoff}）")

        return count

    def cleanup_stale_generating(self, db: Session, max_minutes: int = 30) -> int:
        """清理卡在 generating 状态超过 max_minutes 的推荐（标记为 failed）。

        防止生成异常崩溃后留下脏数据导致后续生成被去重逻辑跳过。
        """
        threshold = datetime.now() - timedelta(minutes=max_minutes)
        stale_picks = db.query(AIStockPick).filter(
            AIStockPick.status == "generating",
            AIStockPick.generated_at < threshold,
        ).all()

        count = len(stale_picks)
        if count > 0:
            for p in stale_picks:
                p.status = "failed"
                p.error_msg = f"generating 状态超过 {max_minutes} 分钟，自动标记为失败（疑似生成进程崩溃）"
            db.commit()
            logger.warning(f"已清理 {count} 条卡在 generating 状态的股票推荐（超过 {max_minutes} 分钟）")

        return count


    # ── 工具方法 ────────────────────────────────────────

    @staticmethod
    def _to_dict(pick: AIStockPick) -> dict:
        """模型转字典（列表用）"""
        return {
            "id": pick.id,
            "pick_date": pick.pick_date,
            "status": pick.status,
            "error_msg": pick.error_msg,
            "prompt_version": pick.prompt_version,
            "generated_at": pick.generated_at.isoformat() if pick.generated_at else None,
        }

    @staticmethod
    def _to_detail_dict(pick: AIStockPick) -> dict:
        """模型转字典（详情用）"""
        result = {
            "id": pick.id,
            "pick_date": pick.pick_date,
            "ai_report": pick.ai_report or "",
            "status": pick.status,
            "error_msg": pick.error_msg,
            "prompt_version": pick.prompt_version,
            "generated_at": pick.generated_at.isoformat() if pick.generated_at else None,
        }
        if pick.picks_data:
            try:
                result["picks_data"] = json.loads(pick.picks_data)
            except json.JSONDecodeError:
                result["picks_data"] = pick.picks_data
        if pick.market_data:
            try:
                result["market_data"] = json.loads(pick.market_data)
            except json.JSONDecodeError:
                result["market_data"] = pick.market_data
        return result


# 全局服务实例
ai_stock_pick_service = AIStockPickService()
