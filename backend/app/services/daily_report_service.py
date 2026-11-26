"""每日复盘报告服务 — AI生成专业研报 + 定时任务（带Redis缓存）"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

# akshare 仅用于全球指数/期货/外汇等 a-stock-data 不覆盖的数据源
# 若未安装 akshare，这些模块将返回空数据，不影响 A 股核心功能
try:
    import akshare as ak
except ImportError:
    ak = None

from app.core.data_sources import EastMoneyDataCenter, EastMoneyZTPool, THSNorthboundSource
import pandas as pd
from sqlalchemy.orm import Session

from app.models.daily_report import DailyReport
from app.core.llm_service import llm_config, llm_client
from app.core.prompts import SYSTEM_PROMPT_REPORT
from app.core.trading_calendar import get_last_trade_date
from app.services.market_service import MarketService
from app.core.cache import cache_get, cache_set, NS_DAILY_REPORT

logger = logging.getLogger(__name__)

# User-Agent for HTTP requests
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Prompt 版本号，用于追溯历史报告使用的 prompt
PROMPT_VERSION = "v2.0"

# 默认保留天数
DEFAULT_RETENTION_DAYS = 30

# 复盘数据缓存TTL（秒）- 盘中1小时，盘后4小时
_REPORT_DATA_TTL = 3600


class DailyReportService:
    """每日复盘报告服务"""

    def __init__(self):
        self.market = MarketService()

    # ── 新增数据源 ────────────────────────────────────────

    @staticmethod
    def _fetch_news_for_report(report_date: str) -> list[dict]:
        """获取当日重要新闻，供复盘报告使用。

        当日无匹配时回退到最近1-2天的数据（标注日期）。
        """
        try:
            from app.services.news_service import get_all_news
            all_items = get_all_news(top_n=20)
            target_date = report_date[:10]

            # 精确匹配当日
            matched = [n for n in all_items if n.get("date", "") == target_date]
            if matched:
                return matched

            # 回退：尝试最近1-2天（向前和向后都尝试）
            from datetime import datetime as _dt, timedelta as _td
            target_dt = _dt.strptime(target_date, "%Y-%m-%d")
            for offset in range(1, 3):
                # 向前回退
                fallback_date = (target_dt - _td(days=offset)).strftime("%Y-%m-%d")
                fallback_items = [n for n in all_items if n.get("date", "") == fallback_date]
                if fallback_items:
                    logger.info(f"当日({target_date})无新闻，回退到 {fallback_date} ({len(fallback_items)}条)")
                    return [{**n, "note": f"实际日期: {fallback_date}"} for n in fallback_items[:10]]
                
                # 向后回退（针对报告日期是昨天，新闻是今天的情况）
                fallback_date = (target_dt + _td(days=offset)).strftime("%Y-%m-%d")
                fallback_items = [n for n in all_items if n.get("date", "") == fallback_date]
                if fallback_items:
                    logger.info(f"当日({target_date})无新闻，回退到 {fallback_date} ({len(fallback_items)}条)")
                    return [{**n, "note": f"实际日期: {fallback_date}"} for n in fallback_items[:10]]

            logger.info(f"当日及近2天({target_date})均无匹配新闻")
            return []
        except Exception as e:
            logger.warning(f"获取新闻数据失败: {e}")
            return []

    @staticmethod
    def _fetch_research_for_report(report_date: str) -> list[dict]:
        """获取最新研报精选，供复盘报告使用。

        当日无匹配时回退到最近1-2天的数据（标注日期）。
        """
        try:
            from app.services.news_service import get_all_research
            items = get_all_research(top_n=15)
            target_date = report_date[:10]

            # 精确匹配当日
            matched = [r for r in items if r.get("date", "") == target_date]
            if matched:
                return matched

            # 回退：尝试最近1-2天
            from datetime import datetime as _dt, timedelta as _td
            target_dt = _dt.strptime(target_date, "%Y-%m-%d")
            for offset in range(1, 3):
                fallback_date = (target_dt - _td(days=offset)).strftime("%Y-%m-%d")
                fallback_items = [r for r in items if r.get("date", "") == fallback_date]
                if fallback_items:
                    logger.info(f"当日({target_date})无研报，回退到 {fallback_date} ({len(fallback_items)}条)")
                    return [{**r, "note": f"实际日期: {fallback_date}"} for r in fallback_items[:8]]

            logger.info(f"当日及近2天({target_date})均无匹配研报")
            return []
        except Exception as e:
            logger.warning(f"获取研报数据失败: {e}")
            return []

    def _fetch_lhb_data(self, report_date: str) -> dict:
        """获取龙虎榜数据（带Redis缓存）"""
        cache_key = f"lhb:{report_date}"
        cached = cache_get(cache_key, NS_DAILY_REPORT)
        if cached:
            return cached

        try:
            date_str = report_date.replace("-", "")
            lhb_data = EastMoneyDataCenter.dragon_tiger_board(date_str)
            if not lhb_data:
                return {"available": False, "message": "当日无龙虎榜数据"}
            
            # 转换为 DataFrame 格式保持兼容
            # 字段映射：BILLBOARD净买额、BUY_AMT买入额、SELL_AMT卖出额（单位：元，转亿元）
            df = pd.DataFrame([{
                '代码': d.get('SECURITY_CODE', ''), '名称': d.get('SECURITY_NAME_ABBR', ''),
                '涨跌幅': float(d.get('CHANGE_RATE', 0) or 0),
                '龙虎榜净买额': float(d.get('BILLBOARD_NET_AMT', 0) or 0) / 1e8,  # 转换为亿元
                '龙虎榜买入额': float(d.get('BUY_AMT', 0) or 0) / 1e8,  # 转换为亿元
                '龙虎榜卖出额': float(d.get('SELL_AMT', 0) or 0) / 1e8,  # 转换为亿元
                '上榜原因': d.get('EXPLANATION', '')
            } for d in lhb_data])
            if df is None or df.empty:
                return {"available": False, "message": "当日无龙虎榜数据"}

            # 按净买额排序，取Top10
            df = df.sort_values("龙虎榜净买额", ascending=False)
            top_buy = df.head(10)
            top_sell = df.tail(10).sort_values("龙虎榜净买额", ascending=True)

            result = {
                "available": True,
                "total_count": len(df),
                "top_buy": [],
                "top_sell": [],
            }

            for _, row in top_buy.iterrows():
                result["top_buy"].append({
                    "code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "change_pct": float(row.get("涨跌幅", 0)),
                    "net_buy": float(row.get("龙虎榜净买额", 0)),
                    "buy_amount": float(row.get("龙虎榜买入额", 0) or 0),
                    "sell_amount": float(row.get("龙虎榜卖出额", 0) or 0),
                    "reason": str(row.get("上榜原因", "")),
                })

            for _, row in top_sell.iterrows():
                result["top_sell"].append({
                    "code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "change_pct": float(row.get("涨跌幅", 0)),
                    "net_buy": float(row.get("龙虎榜净买额", 0)),
                    "buy_amount": float(row.get("龙虎榜买入额", 0) or 0),
                    "sell_amount": float(row.get("龙虎榜卖出额", 0) or 0),
                    "reason": str(row.get("上榜原因", "")),
                })

            # 写入Redis缓存
            cache_set(cache_key, result, ttl=_REPORT_DATA_TTL, namespace=NS_DAILY_REPORT)
            return result
        except Exception as e:
            logger.warning(f"获取龙虎榜数据失败: {e}")
            error_result = {"available": False, "message": f"获取失败: {str(e)}"}
            cache_set(cache_key, error_result, ttl=300, namespace=NS_DAILY_REPORT)  # 错误结果短缓存
            return error_result

    def _fetch_limit_up_data(self, report_date: str) -> dict:
        """获取涨停股数据（含连板梯队，带Redis缓存）。

        历史日期直接用东财四池，不依赖 MarketService（get_sentiment 忽略 date 参数）。
        """
        cache_key = f"limitup:{report_date}"
        cached = cache_get(cache_key, NS_DAILY_REPORT)
        if cached:
            return cached

        try:
            date_str = report_date.replace("-", "")

            # 直接用东财四池获取涨停数据（支持历史日期）
            zt_data = EastMoneyZTPool.get_zt_pool(date_str) or []

            if not zt_data:
                return {"available": False, "message": "当日无涨停数据"}

            total_count = len(zt_data)

            # 转换为 DataFrame 格式保持兼容
            df = pd.DataFrame([{
                '代码': d.get('c', ''), '名称': d.get('n', ''),
                '涨跌幅': d.get('zdp', 0), '成交额': d.get('amount', 0),
                '连板数': d.get('lbc', 1), '炸板次数': d.get('zbc', 0),
                '所属行业': d.get('hybk', ''),
                '首次封板时间': d.get('fbt', ''), '最后封板时间': d.get('lbt', '')
            } for d in zt_data])

            # 连板梯队统计
            board_stats = {}
            if df is not None and not df.empty and "连板数" in df.columns:
                for _, row in df.iterrows():
                    boards = int(row.get("连板数", 1))
                    if boards not in board_stats:
                        board_stats[boards] = []
                    board_stats[boards].append({
                        "code": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "change_pct": float(row.get("涨跌幅", 0)),
                        "turnover": float(row.get("成交额", 0)),
                        "first_time": str(row.get("首次封板时间", "")),
                        "last_time": str(row.get("最后封板时间", "")),
                        "open_count": int(row.get("炸板次数", 0)),
                        "industry": str(row.get("所属行业", "")),
                    })

            # 最高板信息
            max_board = max(board_stats.keys()) if board_stats else 0
            high_board_stocks = board_stats.get(max_board, []) if max_board > 0 else []

            # 炸板统计（有炸板记录的）
            open_board_count = 0
            if df is not None and not df.empty and "炸板次数" in df.columns:
                open_board_count = int((df["炸板次数"] > 0).sum())

            result = {
                "available": True,
                "total_count": total_count or len(zt_data),
                "max_board": max_board,
                "high_board_stocks": high_board_stocks,
                "board_stats": {str(k): v for k, v in sorted(board_stats.items(), reverse=True)},
                "open_board_count": open_board_count,
            }

            # 写入Redis缓存
            cache_set(cache_key, result, ttl=_REPORT_DATA_TTL, namespace=NS_DAILY_REPORT)
            return result
        except Exception as e:
            logger.warning(f"获取涨停数据失败: {e}")
            error_result = {"available": False, "message": f"获取失败: {str(e)}"}
            cache_set(cache_key, error_result, ttl=300, namespace=NS_DAILY_REPORT)
            return error_result

    def _fetch_north_flow(self, report_date: str) -> dict:
        """获取北向资金数据。

        当日：从同花顺实时分时数据中提取沪股通/深股通最新值。
        历史日期：从本地 CSV 缓存中查找对应日期的收盘快照。
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            target_date = report_date[:10]

            hgt_yi = None
            sgt_yi = None
            data_source = "unknown"

            if target_date == today:
                # 当日：走实时接口
                nb_data = THSNorthboundSource.get_realtime()
                if not nb_data:
                    return {"available": False, "message": "无北向资金实时数据"}

                for d in reversed(nb_data):
                    if d.get("hgt_yi") is not None and d.get("sgt_yi") is not None:
                        hgt_yi = float(d["hgt_yi"])
                        sgt_yi = float(d["sgt_yi"])
                        break

                data_source = "ths_realtime"
            else:
                # 历史日期：从本地 CSV 缓存查找
                history = THSNorthboundSource.get_history(n=365)
                for record in history:
                    if record.get("date", "") == target_date:
                        hgt_yi = record.get("hgt_yi")
                        sgt_yi = record.get("sgt_yi")
                        break

                data_source = "local_csv"

            if hgt_yi is None or sgt_yi is None:
                return {
                    "available": False,
                    "message": f"{target_date} 无北向资金数据（来源: {data_source}）",
                }

            boards = {
                "沪股通": {
                    "date": target_date,
                    "net_buy": hgt_yi,
                    "flow_in": hgt_yi,
                },
                "深股通": {
                    "date": target_date,
                    "net_buy": sgt_yi,
                    "flow_in": sgt_yi,
                },
            }

            return {
                "available": True,
                "data_date": target_date,
                "source": data_source,
                "boards": boards,
                "records": [{"board": k, **v} for k, v in boards.items()],
            }
        except Exception as e:
            logger.warning(f"获取北向资金数据失败: {e}")
            return {"available": False, "message": f"获取失败: {str(e)}"}

    def _fetch_global_markets(self, report_date: str) -> dict:
        """获取外盘数据（美股/A50/汇率，带Redis缓存）。

        注意：外盘接口只能返回最新可用数据，不支持历史日期查询。
        非当日时会在结果中标注 data_source_note 提醒 LLM。
        """
        cache_key = f"global:{report_date}"
        cached = cache_get(cache_key, NS_DAILY_REPORT)
        if cached:
            return cached

        today = datetime.now().strftime("%Y-%m-%d")
        target_date = report_date[:10]

        result = {
            "available": True,
            "us_indices": [],
            "a50": None,
            "forex": None,
        }

        # 非当日时标注数据来源，避免 LLM 误用
        if target_date != today:
            result["data_source_note"] = (
                f"外盘数据为最新可用数据，非 {target_date} 的历史收盘价"
            )

        # 美股三大指数：新浪财经API
        try:
            us_data = self._fetch_sina_us_indices()
            if us_data:
                result["us_indices"] = us_data
        except Exception as e:
            logger.warning(f"获取美股指数失败: {e}")

        # A50期货：akshare futures_global_spot_em
        try:
            a50_data = self._fetch_eastmoney_a50()
            if a50_data:
                result["a50"] = a50_data
        except Exception as e:
            logger.warning(f"获取A50期货失败: {e}")

        # 美元/人民币汇率：akshare fx_spot_quote
        try:
            forex_data = self._fetch_sina_forex()
            if forex_data:
                result["forex"] = forex_data
        except Exception as e:
            logger.warning(f"获取汇率失败: {e}")

        if not result["us_indices"] and not result["a50"] and not result["forex"]:
            result["available"] = False

        # 写入Redis缓存（外盘数据变化慢，缓存2小时）
        cache_set(cache_key, result, ttl=7200, namespace=NS_DAILY_REPORT)
        return result

    @staticmethod
    def _fetch_sina_us_indices() -> list:
        """新浪财经API获取美股三大指数（subprocess调用curl绕过TLS fingerprint检测）"""
        import subprocess
        
        result = []
        try:
            cmd = [
                "curl", "-s",
                "-H", "Referer: https://finance.sina.com.cn",
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "https://hq.sinajs.cn/list=gb_dji,gb_spx,gb_ixic",
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=15)
            text = proc.stdout.decode("utf-8", errors="replace")
            
            # 符号到名称的映射（新浪返回的中文可能编码错乱，直接用映射）
            symbol_map = {"gb_dji": "道琼斯", "gb_spx": "标普500", "gb_ixic": "纳斯达克"}
            
            for line in text.strip().split("\n"):
                if "=" not in line or "hq_str_" not in line:
                    continue
                symbol = line.split("=")[0].replace("var hq_str_", "").strip()
                data_str = line.split("=")[1].strip().rstrip(";").strip('"')
                
                if not data_str or data_str.startswith('""'):
                    continue
                
                parts = data_str.split(",")
                if len(parts) < 3:
                    continue
                
                try:
                    price = float(parts[1]) if parts[1] else 0
                    change_pct = float(parts[2]) if parts[2] and parts[2].rstrip('%') else 0
                    
                    if price > 0:
                        result.append({
                            "name": symbol_map.get(symbol, symbol),
                            "price": round(price, 2),
                            "change_pct": round(change_pct, 2),
                        })
                except ValueError:
                    continue
        except FileNotFoundError:
            logger.warning("curl命令未找到，跳过美股指数获取")
        except Exception as e:
            logger.warning(f"获取新浪美股指数失败: {e}")
        
        return result

    @staticmethod
    def _fetch_eastmoney_a50() -> dict:
        """akshare获取富时中国A50期货（通过列位置索引避免编码问题）"""
        if ak is None:
            return {}
        
        try:
            df = ak.futures_global_spot_em()
            if df is None or df.empty:
                return {}
            
            # 按名称筛选A50相关行（iloc[2]=名称）
            name_col = df.iloc[:, 2]
            a50_rows = df[name_col.str.contains("A50", na=False)]
            
            if a50_rows.empty:
                return {}
            
            # 列位置：0=排名, 1=代码, 2=名称, 3=最新价, 4=涨跌额, 5=涨跌幅, 6=昨收...
            # 优先取主力合约（有最新价的行）
            for _, row in a50_rows.iterrows():
                price_val = row.iloc[3] if len(row) > 3 else None
                if pd.notna(price_val) and float(price_val) > 0:
                    change_pct = row.iloc[5] if len(row) > 5 else 0
                    return {
                        "name": "富时中国A50期货",
                        "price": round(float(price_val), 2),
                        "change_pct": round(float(change_pct) if pd.notna(change_pct) else 0, 2),
                    }
            
            # 兜底：返回第一行（即使价格为NaN）
            row = a50_rows.iloc[0]
            return {
                "name": "富时中国A50期货",
                "price": round(float(row.iloc[3]), 2) if len(row) > 3 and pd.notna(row.iloc[3]) else 0,
                "change_pct": round(float(row.iloc[5]), 2) if len(row) > 5 and pd.notna(row.iloc[5]) else 0,
            }
        except Exception as e:
            logger.warning(f"获取A50期货失败: {e}")
        
        return {}

    @staticmethod
    def _fetch_sina_forex() -> dict:
        """akshare fx_spot_quote 获取美元/人民币汇率"""
        if ak is None:
            return {}
        
        try:
            df = ak.fx_spot_quote()
            if df is None or df.empty:
                return {}
            
            # 第一列为货币对，第二列为中间价
            pair_col = df.iloc[:, 0]
            usd_rows = df[pair_col.str.contains("USD/CNY", na=False)]
            
            if usd_rows.empty:
                return {}
            
            row = usd_rows.iloc[0]
            price = float(row.iloc[1]) if len(row) > 1 and pd.notna(row.iloc[1]) else 0
            
            if price > 0:
                return {
                    "name": "USD/CNY",
                    "price": round(price, 4),
                    "change_pct": 0.0,
                }
        except Exception as e:
            logger.warning(f"获取汇率失败: {e}")
        
        return {}

    # ── 查询接口 ────────────────────────────────────────

    def list_reports(self, db: Session, days: int = DEFAULT_RETENTION_DAYS) -> list[dict]:
        """获取最近N天的报告列表"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        reports = (
            db.query(DailyReport)
            .filter(DailyReport.report_date >= cutoff)
            .order_by(DailyReport.report_date.desc())
            .all()
        )
        return [self._to_dict(r) for r in reports]

    def get_report_detail(self, db: Session, report_date: str) -> Optional[dict]:
        """获取指定日期的报告详情（含完整AI文本和市场数据）"""
        report = (
            db.query(DailyReport)
            .filter(DailyReport.report_date == report_date)
            .first()
        )
        if not report:
            return None
        return self._to_detail_dict(report)

    def get_latest_report(self, db: Session) -> Optional[dict]:
        """获取最新一条报告（含完整AI文本和市场数据）"""
        report = (
            db.query(DailyReport)
            .order_by(DailyReport.report_date.desc())
            .first()
        )
        if not report:
            return None
        return self._to_detail_dict(report)

    # ── 生成接口 ────────────────────────────────────────

    async def generate_report(self, db: Session, report_date: Optional[str] = None, force: bool = False) -> dict:
        """
        生成指定日期的复盘报告（数据+AI分析）。
        如果report_date为None，则使用最近交易日。
        """
        if report_date is None:
            # 非交易时间使用最近交易日
            trade_date = get_last_trade_date()
            report_date = datetime.strptime(trade_date, '%Y%m%d').strftime('%Y-%m-%d')

        # 检查是否已存在（SQLite 不支持 with_forupdate，直接查询）
        existing = (
            db.query(DailyReport)
            .filter(DailyReport.report_date == report_date)
            .first()
        )
        
        if existing and existing.status == "completed" and not force:
            logger.info(f"报告 {report_date} 已存在，跳过生成")
            return self._to_dict(existing)
        if existing and force:
            logger.info(f"强制覆盖 {report_date} 的已有报告")

        # 标记为生成中
        is_new = False
        if existing:
            existing.status = "generating"
            existing.error_msg = None
        else:
            is_new = True
            existing = DailyReport(
                report_date=report_date,
                status="generating",
            )
            db.add(existing)
        
        try:
            db.flush()
        except Exception as e:
            logger.warning(f"flush生成中状态失败: {e}")

        try:
            # 1. 获取市场数据快照
            logger.info(f"开始生成 {report_date} 复盘报告...")
            market_data = self.market.get_daily_report(style="detailed", fmt="json")

            # 标注数据来源：get_daily_report 内部调用的情绪/板块/热点等接口均返回最新可用数据
            today = datetime.now().strftime("%Y-%m-%d")
            target_date = report_date[:10]
            if target_date != today:
                market_data["data_source_note"] = (
                    f"市场情绪、指数、板块轮动等为最新可用数据（{today}），非 {target_date} 的历史数据"
                )

            # 2. 并发获取扩展数据源（asyncio.gather，耗时从 sum 降至 max）
            logger.info("并发获取龙虎榜、涨停池、北向资金、外盘、新闻/研报...")
            (lhb_data, limit_up_data, north_flow, global_markets, news_items,
              research_items) = await asyncio.gather(
                asyncio.to_thread(self._fetch_lhb_data, report_date),
                asyncio.to_thread(self._fetch_limit_up_data, report_date),
                asyncio.to_thread(self._fetch_north_flow, report_date),
                asyncio.to_thread(self._fetch_global_markets, report_date),
                asyncio.to_thread(self._fetch_news_for_report, report_date),
                asyncio.to_thread(self._fetch_research_for_report, report_date),
            )

            # 合并所有数据
            market_data["lhb"] = lhb_data
            market_data["limit_up"] = limit_up_data
            market_data["north_flow"] = north_flow
            market_data["global_markets"] = global_markets
            market_data["news"] = news_items
            market_data["research"] = research_items

            existing.market_data = json.dumps(market_data, ensure_ascii=False)

            # 3. AI生成专业研报
            ai_text = await self._generate_ai_report(report_date, market_data)
            existing.ai_report = ai_text
            existing.status = "completed"
            existing.prompt_version = PROMPT_VERSION
            existing.generated_at = datetime.now()
            
            try:
                db.commit()
            except Exception as commit_err:
                logger.warning(f"commit失败，尝试rollback后重新保存: {commit_err}")
                db.rollback()
                # 重新查询最新记录，避免StaleDataError
                existing = db.query(DailyReport).filter(DailyReport.report_date == report_date).first()
                if existing:
                    existing.market_data = json.dumps(market_data, ensure_ascii=False)
                    existing.ai_report = ai_text
                    existing.status = "completed"
                    existing.prompt_version = PROMPT_VERSION
                    existing.generated_at = datetime.now()
                else:
                    existing = DailyReport(
                        report_date=report_date,
                        market_data=json.dumps(market_data, ensure_ascii=False),
                        ai_report=ai_text,
                        status="completed",
                        prompt_version=PROMPT_VERSION,
                        generated_at=datetime.now(),
                    )
                    db.add(existing)
                db.commit()

            logger.info(f"{report_date} 复盘报告生成完成，AI文本长度={len(ai_text)}")
            return self._to_dict(existing)

        except Exception as e:
            logger.error(f"生成 {report_date} 报告失败: {e}", exc_info=True)
            try:
                db.rollback()
            except Exception:
                pass
            # 重新查询记录以设置失败状态
            try:
                existing = db.query(DailyReport).filter(DailyReport.report_date == report_date).first()
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

    async def _generate_ai_report(self, report_date: str, market_data: dict) -> str:
        """调用LLM生成专业研报文本"""
        if not llm_config.enabled or not llm_config.model:
            logger.warning("LLM未启用，返回基础摘要")
            return self._build_fallback_summary(report_date, market_data)

        # 构建精简数据上下文，避免超长截断（给LLM输出留足token空间）
        sentiment = market_data.get("sentiment", {})
        sectors = (market_data.get("sectors") or {}).get("sectors", [])
        lhb = market_data.get("lhb", {})
        limit_up = market_data.get("limit_up", {})
        north_flow = market_data.get("north_flow", {})
        global_markets = market_data.get("global_markets", {})
        news_items = market_data.get("news", [])
        research_items = market_data.get("research", [])

        # 精简情绪数据：只保留关键字段
        sentiment_compact = {
            "score": sentiment.get("score"),
            "signal": sentiment.get("signal"),
            "indices": sentiment.get("indices"),
            "breadth": sentiment.get("breadth"),
            "money_flow": sentiment.get("money_flow"),
        }

        # 精简板块数据：涨幅前3和跌幅前3
        # 注意：market_data["sectors"] 只包含 top=10 的领涨板块（降序截断），无法获取领跌数据
        # 直接调用 _fetch_all_sectors 获取全量板块来正确筛选
        all_sectors = sectors
        try:
            full_list = self.market._fetch_all_sectors('industry')
            if full_list:
                all_sectors = full_list
        except Exception as e:
            logger.warning(f"_fetch_all_sectors 兜底领跌板块失败，将使用 sectors 降序数据: {e}")

        sectors_sorted = sorted(all_sectors, key=lambda x: x.get("change_pct", 0), reverse=True)
        sectors_rise3 = [{k: v for k, v in s.items() if k in ("name", "change_pct", "flow_net")} for s in sectors_sorted[:3]]
        declining_sectors = [s for s in all_sectors if s.get("change_pct", 0) < 0]
        declining_sectors.sort(key=lambda x: x.get("change_pct", 0))
        sectors_decline3 = [{k: v for k, v in s.items() if k in ("name", "change_pct", "flow_net")} for s in declining_sectors[:3]]
        # 若全市场无下跌板块（极少见），降级使用排名末尾3个
        if not sectors_decline3 and len(sectors_sorted) >= 3:
            sectors_decline3 = [{k: v for k, v in s.items() if k in ("name", "change_pct", "flow_net")} for s in sectors_sorted[-3:]]
            logger.info("当日无下跌板块，使用涨幅末尾3个作为跌幅 Top3 参考")

        # 精简新闻：只保留标题+来源+日期+note，最多5条（防御：news可能是 dict {"available": False}）
        # note 字段标注新闻回退到的实际日期，LLM 必须在报告中说明
        news_list = news_items if isinstance(news_items, list) else []
        news_compact = [
            {
                "title": n.get("title", ""),
                "source": n.get("source", ""),
                "date": n.get("date", ""),
                **({"note": n["note"]} if n.get("note") else {}),
            }
            for n in news_list[:5] if isinstance(n, dict) and n.get("title")
        ]

        # 精简研报：同上，透传 note 字段
        research_list = research_items if isinstance(research_items, list) else []
        research_compact = [
            {
                "title": r.get("title", ""),
                "org": r.get("org", ""),
                "date": r.get("date", ""),
                **({"note": r["note"]} if r.get("note") else {}),
            }
            for r in research_list[:5] if isinstance(r, dict)
        ]

        # 精简龙虎榜：只保留净买额前3
        lhb_compact = {}
        if lhb.get("available"):
            lhb_compact = {
                "total_count": lhb.get("total_count", 0),
                "top_buy_3": [{"code": s.get("code", ""), "name": s.get("name", ""), "change_pct": s.get("change_pct", 0), "net_buy": s.get("net_buy", 0), "reason": s.get("reason", "")} for s in (lhb.get("top_buy", []) or [])[:3]],
                "top_sell_3": [{"code": s.get("code", ""), "name": s.get("name", ""), "change_pct": s.get("change_pct", 0), "net_buy": s.get("net_buy", 0), "reason": s.get("reason", "")} for s in (lhb.get("top_sell", []) or [])[:3]],
            }

        # 精简连板数据：只保留关键指标
        limit_compact = {}
        if limit_up.get("available"):
            total_count = limit_up.get("total_count", 0)
            open_board_count = limit_up.get("open_board_count", 0)
            # 计算封板率：涨停数 / (涨停数 + 炸板数)
            seal_rate = round(total_count / (total_count + open_board_count) * 100, 1) if (total_count + open_board_count) > 0 else 0
            limit_compact = {
                "total_count": total_count,
                "max_board": limit_up.get("max_board", 0),
                "high_board_stocks": [{k: v for k, v in s.items() if k in ("code", "name", "industry", "first_time")} for s in (limit_up.get("high_board_stocks", []) or [])[:3]],
                "open_board_count": open_board_count,
                "seal_rate": seal_rate,
            }

        # 精简外盘：只保留关键指数（确保字段完整）
        global_compact = {}
        if global_markets.get("available"):
            # 美股指数：只保留name/price/change_pct
            us_indices = global_markets.get("us_indices", []) or []
            us_compact = []
            for s in us_indices[:3]:
                us_compact.append({
                    "name": s.get("name", ""),
                    "price": s.get("price", 0),
                    "change_pct": s.get("change_pct", 0),
                })
            
            # A50期货：确保有price和change_pct
            a50 = global_markets.get("a50")
            a50_compact = None
            if a50:
                a50_compact = {
                    "name": a50.get("name", "富时中国A50期货"),
                    "price": a50.get("price", 0),
                    "change_pct": a50.get("change_pct", 0),
                }
            
            # 汇率：确保有price
            forex = global_markets.get("forex")
            forex_compact = None
            if forex:
                forex_compact = {
                    "name": forex.get("name", "USD/CNY"),
                    "price": forex.get("price", 0),
                }
            
            global_compact = {
                "us_indices": us_compact,
                "a50": a50_compact,
                "forex": forex_compact,
            }

        # 收集数据来源标注（非当日时提醒 LLM）
        notes_list = []
        md_note = market_data.get("data_source_note")
        if md_note:
            notes_list.append(md_note)
        gm_note = (global_markets or {}).get("data_source_note", "")
        if gm_note:
            notes_list.append(gm_note)

        data_payload = {
            "sentiment": sentiment_compact,
            "sectors_rise3": sectors_rise3,
            "sectors_decline3": sectors_decline3,
            "lhb": lhb_compact if lhb_compact else None,
            "limit_up": limit_compact if limit_compact else None,
            "north_flow": north_flow,
            "global_markets": global_compact if global_compact else None,
            "news": news_compact if news_compact else None,
            "research": research_compact if research_compact else None,
        }
        if notes_list:
            data_payload["data_source_note"] = "\n".join(notes_list)

        data_text = json.dumps(data_payload, ensure_ascii=False)

        # 数据上下文控制在 10KB 以内，给 LLM 输出留足 token
        # 截断时优先按字段边界截断，避免破坏 JSON 结构导致 LLM 解析失败
        if len(data_text) > 10000:
            # 尝试按顶层字段截断：逐个删除 research/news 等次要字段直到满足大小
            trimming_keys = ["research", "news", "global_markets"]
            for k in trimming_keys:
                if len(data_text) <= 10000:
                    break
                if data_payload.get(k):
                    data_payload[k] = f"[已省略：{k}数据过大]"
                    data_text = json.dumps(data_payload, ensure_ascii=False)
            # 仍超长时直接截断到字段末尾（找最后的 }, 保证 JSON 完整性）
            if len(data_text) > 10000:
                last_brace = data_text.rfind('},', 0, 10000)
                if last_brace > 5000:
                    data_text = data_text[:last_brace + 1] + "}"
                    data_text += '\n... [部分次要数据已省略以控制长度]'
                else:
                    data_text = data_text[:10000] + "\n... [数据已截断]"

        system_prompt = SYSTEM_PROMPT_REPORT

        user_prompt = f"""请为 {report_date} 撰写专业复盘报告。

## 当日市场数据
{data_text}

请基于以上数据,按照要求的格式输出完整报告。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            resp = await llm_client.chat_completion(messages, tools=None)
            content = resp.get("content", "").strip()
            if not content or len(content) < 500:
                logger.warning(f"AI生成报告内容过短({len(content or '')}字符)")
                raise ValueError(f"内容过短({len(content or '')}字符)")
            return content
        except Exception as e:
            logger.error(f"AI生成报告失败: {e}", exc_info=True)
            raise RuntimeError(f"LLM调用失败: {str(e)}") from e

    @staticmethod
    def _build_fallback_summary(report_date: str, market_data: dict) -> str:
        """LLM不可用时的基础摘要"""
        sentiment = market_data.get("sentiment", {})
        breadth = sentiment.get("breadth", {})
        volume = sentiment.get("volume", {})

        lines = [f"# {report_date} 市场复盘报告\n"]
        lines.append(f"## 核心结论")
        lines.append(f"当日市场情绪{sentiment.get('signal', '中性')}（评分{sentiment.get('score', '--')}），")
        lines.append(f"上涨{breadth.get('up', 0)}家/下跌{breadth.get('down', 0)}家，成交额{volume.get('total_billion', 0):.0f}亿元。\n")

        # 指数表现
        indices = sentiment.get("indices", {})
        if indices:
            lines.append("## 大盘指数\n| 指数 | 点位 | 涨跌幅 |\n|---|---|---|")
            for code in ["shanghai", "shenzhen", "chiNext", "hs300"]:
                idx = indices.get(code)
                if idx:
                    sign = "+" if idx["change_pct"] >= 0 else ""
                    lines.append(f"| {idx['name']} | {idx['price']} | {sign}{idx['change_pct']:.2f}% |")

        lines.append("\n> 以上为自动生成的基础摘要，LLM服务未启用。")
        return "\n".join(lines)

    # ── 清理接口 ────────────────────────────────────────

    def cleanup_old_reports(self, db: Session, days: int = DEFAULT_RETENTION_DAYS) -> int:
        """删除超过指定天数的报告"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        old_reports = db.query(DailyReport).filter(
            DailyReport.report_date < cutoff
        ).all()

        count = len(old_reports)
        if count > 0:
            for r in old_reports:
                db.delete(r)
            db.commit()
            logger.info(f"已清理 {count} 条过期复盘报告（早于 {cutoff}）")

        return count

    def cleanup_stale_generating(self, db: Session, max_minutes: int = 30) -> int:
        """清理卡在 generating 状态超过 max_minutes 的报告（标记为 failed）。

        防止生成异常崩溃后留下脏数据导致后续生成被去重逻辑跳过。
        """
        threshold = datetime.now() - timedelta(minutes=max_minutes)
        stale_reports = db.query(DailyReport).filter(
            DailyReport.status == "generating",
            DailyReport.generated_at < threshold,
        ).all()

        count = len(stale_reports)
        if count > 0:
            for r in stale_reports:
                r.status = "failed"
                r.error_msg = f"generating 状态超过 {max_minutes} 分钟，自动标记为失败（疑似生成进程崩溃）"
            db.commit()
            logger.warning(f"已清理 {count} 条卡在 generating 状态的复盘报告（超过 {max_minutes} 分钟）")

        return count

    # ── 工具方法 ────────────────────────────────────────

    @staticmethod
    def _to_dict(report: DailyReport) -> dict:
        """模型转字典（列表用，不含完整AI文本）"""
        return {
            "id": report.id,
            "report_date": report.report_date,
            "ai_report_preview": DailyReportService._truncate_by_section(report.ai_report or "", max_chars=300),
            "status": report.status,
            "error_msg": report.error_msg,
            "prompt_version": report.prompt_version,
            "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        }

    @staticmethod
    def _to_detail_dict(report: DailyReport) -> dict:
        """模型转字典（详情用，含完整AI文本和市场数据）"""
        result = {
            "id": report.id,
            "report_date": report.report_date,
            "ai_report": report.ai_report or "",
            "status": report.status,
            "error_msg": report.error_msg,
            "prompt_version": report.prompt_version,
            "generated_at": report.generated_at.isoformat() if report.generated_at else None,
        }
        if report.market_data:
            try:
                result["market_data"] = json.loads(report.market_data)
            except json.JSONDecodeError:
                result["market_data"] = report.market_data
        return result

    @staticmethod
    def _truncate_by_section(text: str, max_chars: int = 300) -> str:
        """按章节截断文本：在最近的章节标题或段落边界处截断，避免切到半句话。"""
        if len(text) <= max_chars:
            return text

        # 尝试在 max_chars 附近找到章节边界（## 开头）或空行
        cutoff = text[:max_chars]
        # 优先找 ## 章节标题位置（回退到上一个完整章节）
        last_section = -1
        last_blank = -1
        for i in range(max_chars, 0, -1):
            if i < len(text) and text[i:i+2] == '##':
                last_section = i
                break
            if text[i:i+1] == '\n' and i > 0 and text[i-1:i] == '\n':
                last_blank = i - 1

        if last_section >= 0:
            return text[:last_section] + "..."
        elif last_blank > max_chars * 0.5:
            return text[:last_blank] + "..."
        else:
            # 退回到最后一个句号/换行
            for i in range(max_chars, 0, -1):
                c = text[i-1:i]
                if c in ('。', '\n', '.', '!', '！', '?', '？'):
                    return text[:i] + "..."
            return cutoff + "..."


# 全局服务实例
daily_report_service = DailyReportService()
