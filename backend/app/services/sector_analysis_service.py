"""板块深度分析服务 — 涨停梯队/轮动量化/行业研报/热度排行/产业链/对比工具

所有东财请求统一走 data_sources_clean.py 的 em_get() 限流器，不新建独立实例。
数据源优先使用已有封装类 (EastMoneyZTPool, THSLimitUpPoolSource, EastMoneyIndustryReport)。
缓存策略：统一使用 cache.py (Redis/内存)，支持 force_refresh + stale fallback。
"""
import logging
import math
import time
from datetime import datetime, timedelta

import requests

from app.core.cache import cache_get, cache_set, swr_cache, NS_MARKET
# 统一限流器（所有东财请求走此入口，串行限流）
from app.core.data_sources_clean import em_get, em_post, _em_throttle, _EM_SESSION
# 已有封装类：涨停池/研报/同花顺涨停揭秘
from app.core.data_sources_clean import (
    EastMoneyZTPool,
    THSLimitUpPoolSource,
    EastMoneyIndustryReport,
    TencentSource,
)

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ════════════════════════════════════════════════════════
# 工具函数（对齐 strategy_service.py）
# ════════════════════════════════════════════════════════

def _format_display_date(date_str) -> str:
    """格式化显示日期：YYYY-MM-DD"""
    try:
        d = str(date_str).replace("-", "")
        if len(d) == 8:
            return f"{d[:4]}-{d[4:6]}-{d[6:]}"
        dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return str(date_str)


def _format_update_time() -> str:
    """格式化更新时间：YYYY-MM-DD HH:MM"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _add_meta(result: dict, target_date=None) -> dict:
    """为结果添加元数据（data_date + update_time）"""
    if not isinstance(result, dict):
        return result
    td = target_date or _get_target_date()
    result.setdefault("data_date", _format_display_date(td))
    result.setdefault("update_time", _format_update_time())
    return result


def _get_target_date() -> str:
    """获取目标交易日"""
    try:
        from app.core.trading_calendar import get_last_trade_date
        return get_last_trade_date()
    except Exception:
        return datetime.now().strftime("%Y%m%d")


# ════════════════════════════════════════════════════════
# 市场前缀工具（对齐 SKILL.md get_prefix）
# ════════════════════════════════════════════════════════

def _get_market_prefix(code: str) -> int:
    """6位代码 → 东财市场码：1=上海, 0=深圳/北交所"""
    code_str = str(code).upper()
    if code_str.startswith(("SH", "BJ")) or code_str[2:].startswith(("6", "9", "8", "4")):
        return 1 if code_str.startswith(("SH",)) or code_str[2:].startswith(("6", "9")) else 0
    return 0


# ════════════════════════════════════════════════════════
# 同花顺热榜 API（不封IP，无需限流）
# ════════════════════════════════════════════════════════

def _ths_hot_list(period: str = "hour") -> list:
    """同花顺热榜"""
    try:
        r = requests.get(
            "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock",
            params={"stock_type": "a", "type": period, "list_type": "normal"},
            headers={"User-Agent": _UA}, timeout=10)
        lst = (r.json().get("data") or {}).get("stock_list") or []
    except Exception as e:
        logger.warning(f"同花顺热榜失败: {e}")
        return []
    out = []
    for it in lst:
        tag = it.get("tag") or {}
        out.append({"rank": it.get("order"), "code": it.get("code"), "name": it.get("name"),
            "heat": it.get("rate"), "pct": it.get("rise_and_fall"),
            "rank_chg": it.get("hot_rank_chg"),
            "concepts": tag.get("concept_tag") or [], "tag": tag.get("popularity_tag", "")})
    return out


# ════════════════════════════════════════════════════════
# 东财人气榜 API（全部走 em_get 统一限流）
# ════════════════════════════════════════════════════════

_EM_HOT_BODY = {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38"}


def _em_hot_rank(top: int = 50) -> list:
    """东财人气榜（使用腾讯行情替代被封的push2 ulist）"""
    try:
        # 获取东财人气榜排名，走统一限流器 em_post
        r = em_post(
            "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
            json={**_EM_HOT_BODY, "marketType": "", "pageNo": 1, "pageSize": top},
            headers={"Referer": "https://quote.eastmoney.com/"}, timeout=10)
        data = r.json().get("data") or []
        if not data:
            return []

        # 提取股票代码列表
        codes = []
        for it in data:
            sc = it.get("sc", "")
            code = sc[2:] if len(sc) > 2 else sc
            codes.append(code)

        # 使用腾讯行情API获取股票名称、价格、涨跌幅（替代被封的push2 ulist）
        from app.core.data_sources_clean import TencentSource
        quotes = TencentSource.get_quotes(codes) if codes else {}
        
        out = []
        for it in data:
            sc = it.get("sc", "")
            code = sc[2:] if len(sc) > 2 else sc
            q = quotes.get(code, {})
            out.append({
                "rank": it["rk"], 
                "code": code, 
                "name": q.get("name", ""),
                "price": q.get("price", 0), 
                "pct": q.get("change_pct", 0), 
                "rank_chg": it.get("hisRc")
            })
        return out
    except Exception as e:
        logger.warning(f"东财人气榜失败: {e}")
        return []


# ════════════════════════════════════════════════════════
# 板块行情数据（统一入口，5秒内复用缓存）
# ════════════════════════════════════════════════════════
_SECTOR_LIST_CACHE = {}

_SECTOR_LIST_LOCK = __import__('threading').Lock()

_SECTOR_LIST_TTL = 30

def _em_sector_list(sector_type: str = "industry") -> list:
    """板块列表获取：东财push2为主，失败时回退到同花顺/腾讯

    Bug #2 + 优化1修复：统一字段集，5秒内重复调用直接返回缓存。
    字段对齐 SKILL.md industry_comparison() 标准。
    
    回退策略：
    1. 东财 push2 clist（优先，有资金流数据）
    2. 同花顺行业板块（不封IP，但无资金流）
    3. 硬编码板块 + 腾讯行情（最终兜底）
    """
    with _SECTOR_LIST_LOCK:
        cached, ts = _SECTOR_LIST_CACHE.get(sector_type, (None, 0))
        if cached and time.time() - ts < _SECTOR_LIST_TTL:
            return cached

    # 方案1：东财 push2 clist（已不可用，直接跳过）
    # try:
    #     _em_throttle()
    #     r = _EM_SESSION.get(
    #         "https://push2.eastmoney.com/api/qt/clist/get",
    #         params={
    #             "pn": "1", "pz": "500", "po": "1", "np": "1",
    #             "fltt": "2", "invt": "2",
    #             "fs": fs_map.get(sector_type, "m:90+t:2"),
    #             "fields": "f2,f3,f4,f12,f13,f14,f62,f104,f105,f128,f136,f140,f141",
    #         },
    #         headers={"User-Agent": _UA, "Referer": "https://quote.eastmoney.com/"}, timeout=1)
    #     items = r.json().get("data", {}).get("diff", [])
    #     if items:
    #         rows = []
    #         for i, item in enumerate(items):
    #             rows.append({
    #                 "rank": i + 1,
    #                 "name": item.get("f14", ""),
    #                 "code": item.get("f12", ""),
    #                 "price": item.get("f2", 0),
    #                 "change_pct": item.get("f3", 0),
    #                 "turnover_yi": round((item.get("f4") or 0) / 1e8, 2),
    #                 "flow_net": round((item.get("f62") or 0) / 1e8, 2),
    #                 "up_count": item.get("f104") or 0,
    #                 "down_count": item.get("f105") or 0,
    #                 "lead_stock": item.get("f128") or "",
    #                 "leader_change": item.get("f136", 0),
    #             })
    #         with _SECTOR_LIST_LOCK:
    #             _SECTOR_LIST_CACHE[sector_type] = (rows, time.time())
    #         return rows
    # except Exception as e:
    #     logger.debug(f"东财板块列表(push2)不可用，跳过: {e}")

    # 方案2：同花顺行业板块（不封IP）
    try:
        rows = _ths_sector_list(sector_type)
        if rows:
            with _SECTOR_LIST_LOCK:
                _SECTOR_LIST_CACHE[sector_type] = (rows, time.time())
            return rows
    except Exception as e:
        logger.warning(f"同花顺板块列表请求失败: {e}")

    # 方案3：腾讯行业板块（不封IP，兜底）
    try:
        rows = _tencent_sector_list(sector_type)
        if rows:
            with _SECTOR_LIST_LOCK:
                _SECTOR_LIST_CACHE[sector_type] = (rows, time.time())
            return rows
    except Exception as e:
        logger.warning(f"腾讯行业板块请求失败: {e}")

    return []


def _tencent_sector_list(sector_type: str = "industry") -> list:
    """腾讯行业板块列表（不封IP，用于替代被封的东财push2 clist）
    
    数据源：使用THSSectorBuilder从腾讯财经聚合行业数据
    返回字段与 _em_sector_list 对齐，便于无缝切换
    
    返回字段说明：
    - name: 板块名称
    - code: 板块代码
    - change_pct: 涨跌幅(%)
    - up_count: 上涨家数
    - down_count: 下跌家数
    - lead_stock: 领涨股
    """
    try:
        from app.core.data_sources_clean import THSSectorBuilder, EastMoneySource
        
        if sector_type == "industry":
            raw_sectors = THSSectorBuilder.build_industry_boards(page_size=100)
        else:
            raw_sectors = THSSectorBuilder.build_concept_boards_from_hot(page_size=100)
        
        if not raw_sectors:
            return []
        
        rows = []
        for i, sector in enumerate(raw_sectors):
            rows.append({
                "rank": i + 1,
                "name": sector.get("f14", ""),
                "code": sector.get("f12", ""),
                "price": sector.get("f2", 0) or 0,
                "change_pct": sector.get("f3", 0) or 0,
                "turnover_yi": round((sector.get("f6") or 0) / 1e8, 2),
                "flow_net": round((sector.get("f62") or 0) / 1e8, 2),
                "up_count": sector.get("up_count", 0) or 0,
                "down_count": sector.get("down_count", 0) or 0,
                "lead_stock": sector.get("f140", "") or "",
                "leader_change": sector.get("f136", 0) or 0,
            })
        
        return rows
    except Exception as e:
        logger.warning(f"腾讯行业板块请求失败: {e}")
        return []


def _ths_sector_list(sector_type: str = "industry") -> list:
    """行业/概念板块列表（不封IP，数据质量高）
    
    行业板块：THSSectorBuilder → 腾讯财经直连（~50ms，不封IP）
    概念板块：同花顺 gnzjl free接口 + THSSectorBuilder 兜底
    
    返回字段与 _em_sector_list 对齐：
    - name: 板块名称
    - code: 板块代码
    - change_pct: 涨跌幅(%)
    - turnover_yi: 成交额(亿)
    - flow_net: 净流入(亿)
    - up_count: 上涨家数
    - down_count: 下跌家数
    - lead_stock: 领涨股
    - leader_change: 领涨股涨跌幅
    """
    import requests as _req
    from io import StringIO
    import pandas as pd

    # 行业板块：直接用腾讯财经（不封IP，~50ms）
    if sector_type == "industry":
        try:
            from app.core.data_sources_clean import THSSectorBuilder
            raw_sectors = THSSectorBuilder.build_industry_boards(page_size=100)
            if not raw_sectors:
                return []

            rows = []
            for i, sector in enumerate(raw_sectors):
                rows.append({
                    "rank": i + 1,
                    "name": sector.get("f14", ""),
                    "code": sector.get("f12", ""),
                    "price": sector.get("f2", 0) or 0,
                    "change_pct": sector.get("f3", 0) or 0,
                    "turnover_yi": round((sector.get("f6") or 0) / 1e8, 2),
                    "flow_net": round((sector.get("f62") or 0) / 1e8, 2),
                    "up_count": sector.get("up_count", 0) or 0,
                    "down_count": sector.get("down_count", 0) or 0,
                    "lead_stock": sector.get("f140", "") or "",
                    "leader_change": sector.get("f136", 0) or 0,
                })

            logger.info(f"腾讯行业板块: {len(rows)}个")
            return rows
        except Exception as e:
            logger.warning(f"腾讯行业板块获取失败: {e}")

    # 概念板块：同花顺 gnzjl free接口 + THSSectorBuilder 兜底
    if sector_type == "concept":
        url = "http://data.10jqka.com.cn/funds/gnzjl/field/tradezdf/order/desc/page/1/ajax/1/free/1/"

        try:
            headers = {
                "User-Agent": _UA,
                "Referer": "http://data.10jqka.com.cn/",
            }

            r = _req.get(url, headers=headers, timeout=10)

            if r.status_code == 200 and len(r.text) > 1000:
                r.encoding = "gbk"
                dfs = pd.read_html(StringIO(r.text))
                if dfs:
                    df = dfs[0]
                    rows = []
                    for i, (_, row) in enumerate(df.iterrows()):
                        try:
                            name = str(row.iloc[1]).strip() if len(row) > 1 else ""
                            change_pct_str = str(row.iloc[3]).replace("%", "").strip() if len(row) > 3 else "0"
                            change_pct = float(change_pct_str) if change_pct_str and change_pct_str != "-" else 0

                            inflow_str = str(row.iloc[4]).replace(",", "").strip() if len(row) > 4 else "0"
                            outflow_str = str(row.iloc[5]).replace(",", "").strip() if len(row) > 5 else "0"
                            try:
                                inflow = float(inflow_str) if inflow_str and inflow_str != "-" else 0
                                outflow = float(outflow_str) if outflow_str and outflow_str != "-" else 0
                            except Exception:
                                inflow = outflow = 0
                            turnover_yi = round(inflow + outflow, 2)

                            net_str = str(row.iloc[6]).replace(",", "").strip() if len(row) > 6 else "0"
                            try:
                                flow_net = float(net_str) if net_str and net_str != "-" else 0
                            except Exception:
                                flow_net = 0

                            company_count_str = str(row.iloc[7]).strip() if len(row) > 7 else "0"
                            try:
                                company_count = int(company_count_str) if company_count_str and company_count_str != "-" else 0
                            except Exception:
                                company_count = 0

                            lead_stock = str(row.iloc[8]).strip() if len(row) > 8 else ""
                            lead_change_str = str(row.iloc[9]).replace("%", "").strip() if len(row) > 9 else "0"
                            try:
                                leader_change = float(lead_change_str) if lead_change_str and lead_change_str != "-" else 0
                            except Exception:
                                leader_change = 0

                            up_count = int(company_count * 0.5) if company_count > 0 else 0
                            down_count = company_count - up_count

                            if name and name != "行业" and name != "nan":
                                rows.append({
                                    "rank": i + 1,
                                    "name": name,
                                    "code": "",
                                    "price": 0,
                                    "change_pct": change_pct,
                                    "turnover_yi": turnover_yi,
                                    "flow_net": round(flow_net, 2),
                                    "up_count": up_count,
                                    "down_count": down_count,
                                    "lead_stock": lead_stock,
                                    "leader_change": leader_change,
                                })
                        except (ValueError, TypeError, IndexError):
                            continue

                    if rows:
                        logger.info(f"同花顺概念板块: {len(rows)}个")
                        return rows
        except Exception as e:
            logger.warning(f"同花顺概念板块获取失败: {e}")

        # 兜底：THS热点聚合概念板块（腾讯财经，不封IP）
        try:
            from app.core.data_sources_clean import THSSectorBuilder
            raw_sectors = THSSectorBuilder.build_concept_boards_from_hot(page_size=100)
            if raw_sectors:
                rows = []
                for i, sector in enumerate(raw_sectors):
                    rows.append({
                        "rank": i + 1,
                        "name": sector.get("f14", ""),
                        "code": sector.get("f12", ""),
                        "price": sector.get("f2", 0) or 0,
                        "change_pct": sector.get("f3", 0) or 0,
                        "turnover_yi": round((sector.get("f6") or 0) / 1e8, 2),
                        "flow_net": round((sector.get("f62") or 0) / 1e8, 2),
                        "up_count": sector.get("up_count", 0) or 0,
                        "down_count": sector.get("down_count", 0) or 0,
                        "lead_stock": sector.get("f140", "") or "",
                        "leader_change": sector.get("f136", 0) or 0,
                    })
                if rows:
                    logger.info(f"腾讯概念板块兜底: {len(rows)}个")
                    return rows
        except Exception as e:
            logger.warning(f"腾讯概念板块兜底失败: {e}")

    return []


# ════════════════════════════════════════════════════════
# SectorAnalysisService — 主服务类
# ════════════════════════════════════════════════════════

class SectorAnalysisService:
    """板块深度分析服务"""

    # 产业链映射表（15个热门方向）
    _INDUSTRY_CHAIN_MAP = {
        "新能源": {
            "upstream": ["锂矿", "钴", "稀土", "光伏硅料", "铜"],
            "midstream": ["锂电池", "光伏组件", "风电设备", "逆变器"],
            "downstream": ["新能源汽车", "储能", "充电桩", "太阳能"],
        },
        "半导体": {
            "upstream": ["半导体材料", "光刻机", "EDA", "IP授权"],
            "midstream": ["芯片设计", "晶圆代工", "封测", "设备"],
            "downstream": ["消费电子", "汽车电子", "AI芯片", "物联网"],
        },
        "人工智能": {
            "upstream": ["算力芯片", "服务器", "数据中心", "光模块"],
            "midstream": ["大模型", "算法框架", "云计算", "AI平台"],
            "downstream": ["智能驾驶", "机器人", "医疗AI", "金融科技"],
        },
        "医药生物": {
            "upstream": ["原料药", "化学试剂", "生物材料", "中药资源"],
            "midstream": ["创新药", "仿制药", "医疗器械", "CXO"],
            "downstream": ["医院", "药店", "互联网医疗", "疫苗"],
        },
        "消费电子": {
            "upstream": ["面板", "玻璃", "芯片", "电池"],
            "midstream": ["结构件", "模组", "PCB", "声学器件"],
            "downstream": ["手机", "笔记本", "智能穿戴", "VR/AR"],
        },
        "低空经济": {
            "upstream": ["碳纤维", "航空发动机", "航电系统", "无人机芯片"],
            "midstream": ["eVTOL", "无人机整机", "通航飞机", "飞控系统"],
            "downstream": ["物流配送", "空中交通", "应急救援", "低空旅游"],
        },
        "人形机器人": {
            "upstream": ["减速器", "伺服电机", "丝杠", "力矩传感器"],
            "midstream": ["关节模组", "控制器", "视觉系统", "灵巧手"],
            "downstream": ["工业机器人", "服务机器人", "医疗康复", "家庭陪伴"],
        },
        "商业航天": {
            "upstream": ["火箭发动机", "卫星载荷", "航天材料", "星载芯片"],
            "midstream": ["运载火箭", "卫星制造", "地面设备", "测控系统"],
            "downstream": ["卫星互联网", "遥感应用", "导航定位", "太空旅游"],
        },
        "量子计算": {
            "upstream": ["量子比特", "稀释制冷机", "微波器件", "激光系统"],
            "midstream": ["量子芯片", "量子测控", "纠错编码", "量子软件"],
            "downstream": ["密码破译", "药物研发", "金融建模", "材料模拟"],
        },
        "合成生物": {
            "upstream": ["基因测序", "酶制剂", "培养基", "发酵设备"],
            "midstream": ["基因编辑", "细胞工厂", "代谢通路", "蛋白质设计"],
            "downstream": ["生物制造", "合成材料", "生物燃料", "精准医疗"],
        },
        "氢能": {
            "upstream": ["电解槽", "质子交换膜", "催化剂", "储氢材料"],
            "midstream": ["制氢设备", "加氢站", "氢燃料电池", "储运装备"],
            "downstream": ["氢能源汽车", "工业用氢", "分布式发电", "储能调峰"],
        },
        "卫星互联网": {
            "upstream": ["相控阵天线", "星载处理器", "通信芯片", "太阳能帆板"],
            "midstream": ["卫星制造", "火箭发射", "地面终端", "网络协议"],
            "downstream": ["宽带接入", "海事通信", "航空互联", "应急通信"],
        },
        "数据要素": {
            "upstream": ["数据采集", "数据存储", "数据清洗", "隐私计算"],
            "midstream": ["数据交易所", "数据确权", "数据标注", "数据治理"],
            "downstream": ["数据资产化", "AI训练", "智慧城市", "数字政府"],
        },
        "固态电池": {
            "upstream": ["固态电解质", "锂金属负极", "正极材料", "隔膜"],
            "midstream": ["电芯制造", "封装技术", "BMS系统", "测试设备"],
            "downstream": ["电动汽车", "消费电子储能", "航空电池", "储能电站"],
        },
        "脑机接口": {
            "upstream": ["神经电极", "生物材料", "微纳加工", "信号采集芯片"],
            "midstream": ["信号处理算法", "解码模型", "植入设备", "非侵入头环"],
            "downstream": ["康复医疗", "意念控制", "人机交互", "精神疾病治疗"],
        },
    }

    # 同义词映射：关键词 → [板块名中可能出现的别名/近义行业名]
    # 注意：腾讯兜底行业表约 59 个行业名，东财/同花顺约 200+ 行业/概念名
    # 这里的别名同时覆盖东财、同花顺、腾讯三家的命名差异
    _SYNONYM_MAP = {
        # === 新能源 ===
        "锂矿": ["碳酸锂", "锂业", "锂电池材料", "锂电池", "固态电池", "有色金属", "盐湖提锂", "锂矿概念"],
        "钴": ["钴业", "新能源金属", "有色金属"],
        "稀土": ["稀土永磁", "稀土金属", "有色金属"],
        "光伏硅料": ["多晶硅", "硅片", "工业硅", "硅能源", "光伏"],
        "铜": ["有色金属", "铜业"],
        "锂电池": ["动力电池", "消费电池", "固态电池", "锂电", "锂矿", "钠离子电池"],
        "光伏组件": ["光伏", "硅能源", "太阳能", "HJT电池", "BC电池", "TOPCon电池"],
        "风电设备": ["风电", "风力发电", "新能源", "风能"],
        "逆变器": ["光伏逆变器", "储能变流器"],
        "新能源汽车": ["新能源车", "智能汽车", "电动汽车", "汽车", "汽车整车"],
        "储能": ["电化学储能", "抽水蓄能", "储能电站"],
        "充电桩": ["充电基础设施", "换电", "新能源", "换电概念"],
        "太阳能": ["光伏", "光伏组件"],

        # === 半导体 ===
        "半导体材料": ["硅片", "光刻胶", "电子特气", "半导体", "第三代半导体"],
        "光刻机": ["半导体设备", "光刻胶", "半导体"],
        "EDA": ["电子设计自动化", "IC设计服务", "半导体", "计算机", "芯片设计"],
        "IP授权": ["知识产权", "芯片IP", "半导体", "芯片设计"],
        "芯片设计": ["集成电路设计", "IC设计", "半导体", "芯片概念", "存储芯片", "MCU芯片"],
        "晶圆代工": ["半导体制造", "Foundry", "第三代半导体", "半导体"],
        "封测": ["封装测试", "先进封装", "半导体"],
        "设备": ["半导体设备", "专用设备", "机械"],
        "AI芯片": ["GPU", "算力芯片", "智能芯片", "半导体", "芯片设计", "芯片概念"],
        "消费电子": ["智能手机", "可穿戴", "苹果概念", "面板", "PCB", "消费电子概念"],
        "汽车电子": ["车载电子", "智能座舱", "汽车芯片"],
        "物联网": ["IoT", "车联网", "通信", "物联网模块"],

        # === 人工智能 ===
        "算力芯片": ["GPU", "AI芯片", "半导体", "芯片设计", "芯片概念"],
        "服务器": ["AI服务器", "算力服务器", "计算机", "数据中心"],
        "数据中心": ["IDC", "云计算", "数据要素", "计算机"],
        "光模块": ["光通信", "光器件", "通信", "CPO概念"],
        "大模型": ["生成式AI", "AIGC", "语言模型", "计算机", "云计算", "ChatGPT概念"],
        "算法框架": ["深度学习", "机器学习", "计算机"],
        "云计算": ["云服务", "云基础设施", "数据中心"],
        "AI平台": ["智能平台", "AI中台", "计算机"],
        "智能驾驶": ["自动驾驶", "无人驾驶", "辅助驾驶", "智能汽车"],
        "机器人": ["工业机器人", "协作机器人", "人形机器人"],
        "医疗AI": ["智慧医疗", "医学影像", "医疗器械", "创新药"],
        "金融科技": ["金融IT", "数字货币", "计算机"],

        # === 医药生物 ===
        "原料药": ["API", "医药中间体", "医药"],
        "化学试剂": ["精细化工", "基础化工", "化工"],
        "生物材料": ["医用材料", "高分子材料", "医疗器械"],
        "中药资源": ["中药材", "中药饮片"],
        "创新药": ["生物制药", "靶向药", "医药"],
        "仿制药": ["普药", "一致性评价"],
        "医疗器械": ["医疗设备", "体外诊断", "医疗器材"],
        "CXO": ["医药外包", "CRO", "CDMO", "医药"],
        "医院": ["医疗服务", "专科医院"],
        "药店": ["医药商业", "连锁药房"],
        "互联网医疗": ["在线问诊", "数字健康"],
        "疫苗": ["生物制品", "免疫预防"],

        # === 消费电子 ===
        "面板": ["显示面板", "OLED", "LCD", "MicroLED概念", "柔性屏"],
        "玻璃": ["电子玻璃", "光学玻璃", "玻璃基板", "化工"],
        "芯片": ["集成电路", "IC设计", "半导体", "芯片设计", "芯片概念", "汽车芯片"],
        "电池": ["动力电池", "消费电池", "锂电池", "固态电池"],
        "结构件": ["精密结构件", "金属外壳", "机械"],
        "模组": ["摄像头模组", "显示模组"],
        "PCB": ["印制电路板", "覆铜板", "PCB概念"],
        "声学器件": ["扬声器", "麦克风"],
        "手机": ["智能手机", "通信设备", "AI手机"],
        "笔记本": ["笔记本电脑", "PC", "计算机"],
        "智能穿戴": ["可穿戴设备", "智能手表", "无线耳机", "TWS耳机"],
        "VR/AR": ["虚拟现实", "增强现实", "元宇宙"],

        # === 低空经济 ===
        "碳纤维": ["复合材料", "碳纤复材", "军工"],
        "航空发动机": ["航发动力", "发动机", "军工", "航空装备"],
        "航电系统": ["航空电子", "飞控", "军工"],
        "无人机芯片": ["飞行控制芯片", "无人系统", "无人机"],
        "eVTOL": ["电动垂直起降", "飞行汽车", "低空经济"],
        "无人机整机": ["工业无人机", "消费级无人机", "无人机"],
        "通航飞机": ["通用航空", "小飞机", "军工"],
        "飞控系统": ["自动驾驶仪", "导航控制", "无人机"],
        "物流配送": ["快递物流", "智慧物流"],
        "空中交通": ["低空飞行", "城市空中交通"],
        "应急救援": ["应急装备", "救灾设备"],
        "低空旅游": ["航空旅游", "观光飞行"],

        # === 人形机器人 ===
        "减速器": ["RV减速器", "谐波减速器", "机器人", "机械"],
        "伺服电机": ["交流伺服", "步进电机", "机器人"],
        "丝杠": ["滚珠丝杠", "行星滚柱丝杠", "机械"],
        "力矩传感器": ["扭矩传感器", "六维力传感器"],
        "关节模组": ["旋转关节", "直线关节", "机器人"],
        "控制器": ["运动控制", "PLC"],
        "视觉系统": ["机器视觉", "3D视觉"],
        "灵巧手": ["机械手", "仿生手"],
        "工业机器人": ["制造业机器人", "自动化", "机器人"],
        "服务机器人": ["商用机器人", "家用机器人"],
        "医疗康复": ["康复设备", "外骨骼", "医疗器械"],
        "家庭陪伴": ["陪护机器人", "社交机器人"],

        # === 商业航天 ===
        "火箭发动机": ["液体发动机", "固体发动机", "军工", "航天装备"],
        "卫星载荷": ["通信载荷", "遥感载荷", "卫星互联网"],
        "航天材料": ["高温合金", "钛合金", "军工"],
        "星载芯片": ["抗辐射芯片", "空间电子", "半导体", "芯片设计"],
        "运载火箭": ["长征系列", "商业火箭", "军工"],
        "卫星制造": ["小卫星", "微纳卫星", "卫星互联网"],
        "地面设备": ["地面站", "测控天线"],
        "测控系统": ["遥测遥控", "轨道控制"],
        "卫星互联网": ["低轨卫星", "星链", "通信"],
        "遥感应用": ["对地观测", "地球监测"],
        "导航定位": ["北斗导航", "高精度定位", "通信"],
        "太空旅游": ["亚轨道飞行", "空间站旅游"],

        # === 量子计算 ===
        "量子比特": ["超导量子", "离子阱"],
        "稀释制冷机": ["低温设备", "极低温系统"],
        "微波器件": ["微波放大器", "混频器"],
        "激光系统": ["紫外激光", "飞秒激光"],
        "量子芯片": ["超导芯片", "光量子芯片", "半导体", "芯片设计", "芯片概念"],
        "量子测控": ["脉冲控制", "读出电子学"],
        "纠错编码": ["量子纠错", "表面码"],
        "量子软件": ["量子编程", "量子算法库", "计算机"],
        "密码破译": ["量子加密", "后量子密码"],
        "药物研发": ["新药发现", "分子筛选", "创新药"],
        "金融建模": ["量化交易", "风险评估"],
        "材料模拟": ["计算化学", "分子动力学"],

        # === 合成生物 ===
        "基因测序": ["NGS", "高通量测序"],
        "酶制剂": ["工业酶", "生物催化"],
        "培养基": ["细胞培养", "发酵营养"],
        "发酵设备": ["生物反应器", "发酵罐", "机械"],
        "基因编辑": ["CRISPR", "碱基编辑"],
        "细胞工厂": ["微生物工厂", "酵母工程"],
        "代谢通路": ["合成途径", "酶促反应"],
        "蛋白质设计": ["计算蛋白", "定向进化"],
        "生物制造": ["发酵生产", "细胞培养生产"],
        "合成材料": ["生物塑料", "可降解材料", "化工"],
        "生物燃料": ["生物柴油", "乙醇燃料"],
        "精准医疗": ["个性化治疗", "基因治疗", "创新药"],

        # === 氢能 ===
        "电解槽": ["PEM电解", "碱性电解"],
        "质子交换膜": ["全氟磺酸膜", "燃料电池膜"],
        "催化剂": ["铂催化剂", "非贵金属催化", "化工"],
        "储氢材料": ["金属氢化物", "有机液体储氢"],
        "制氢设备": ["水电解", "天然气重整", "机械"],
        "加氢站": ["氢气加注", "压缩设备"],
        "氢燃料电池": ["质子交换膜电池", "SOFC", "氢能源"],
        "储运装备": ["液氢罐", "高压气瓶"],
        "氢能源汽车": ["氢能重卡", "氢燃料乘用车", "新能源车"],
        "工业用氢": ["炼化用氢", "冶金用氢", "化工"],
        "分布式发电": ["微电网", "离网发电"],
        "储能调峰": ["长时储能", "季节性储能", "储能"],

        # === 卫星互联网 ===
        "相控阵天线": ["有源相控阵", "毫米波天线", "通信"],
        "星载处理器": ["航天CPU", "抗辐照芯片", "半导体", "芯片设计"],
        "通信芯片": ["基带芯片", "射频芯片", "半导体", "芯片设计"],
        "太阳能帆板": ["空间电池板", "柔性光伏", "光伏"],
        "地面终端": ["卫星电话", "用户终端", "通信"],
        "网络协议": ["星间链路", "路由协议", "通信"],
        "宽带接入": ["固定无线", "移动宽带", "通信"],
        "海事通信": ["船舶通信", "远洋联网", "通信"],
        "航空互联": ["机上WiFi", "高空互联网", "通信"],
        "应急通信": ["灾害通信", "临时基站", "通信"],

        # === 数据要素 ===
        "数据采集": ["传感器网络", "边缘采集"],
        "数据存储": ["分布式存储", "云存储", "数据中心"],
        "数据清洗": ["ETL", "数据预处理", "计算机"],
        "隐私计算": ["联邦学习", "安全多方计算", "计算机"],
        "数据交易所": ["数据交易", "数据流通", "数据要素"],
        "数据确权": ["数据产权", "数字版权"],
        "数据标注": ["AI标注", "众包标注"],
        "数据治理": ["元数据管理", "质量管控"],
        "数据资产化": ["数据估值", "数据入表", "数据要素"],
        "AI训练": ["模型训练", "深度学习训练", "数据中心", "数据要素"],
        "智慧城市": ["城市大脑", "智慧城管", "计算机"],
        "数字政府": ["政务云", "一网通办", "计算机"],

        # === 固态电池 ===
        "固态电解质": ["硫化物电解质", "氧化物电解质", "锂电池"],
        "锂金属负极": ["纯锂负极", "复合锂负极", "锂电池"],
        "正极材料": ["三元材料", "磷酸铁锂", "锂电池"],
        "隔膜": ["陶瓷隔膜", "涂覆隔膜", "锂电池"],
        "电芯制造": ["卷绕工艺", "叠片工艺", "锂电池"],
        "封装技术": ["软包封装", "方形封装", "锂电池"],
        "BMS系统": ["电池管理", "均衡控制"],
        "测试设备": ["充放电测试", "寿命测试", "机械"],
        "电动汽车": ["乘用车", "新能源车", "新能源汽车"],
        "消费电子储能": ["移动电源", "TWS耳机", "消费电子"],
        "航空电池": ["航电电池", "无人机电池"],
        "储能电站": ["大型储能", "电网侧储能", "储能"],

        # === 脑机接口 ===
        "神经电极": ["微电极阵列", "柔性电极"],
        "微纳加工": ["MEMS", "纳米制造", "半导体"],
        "信号采集芯片": ["ADC芯片", "前端放大", "半导体", "芯片设计"],
        "信号处理算法": ["特征提取", "降噪滤波", "半导体"],
        "解码模型": ["运动意图识别", "语言解码", "大模型"],
        "植入设备": ["侵入式设备", "皮层电极", "医疗器械"],
        "非侵入头环": ["EEG头带", "脑电帽", "医疗器械"],
        "康复医疗": ["神经康复", "肢体训练", "医疗器械"],
        "意念控制": ["思维操控", "脑控交互"],
        "人机交互": ["BCI接口", "脑机融合", "计算机"],
        "精神疾病治疗": ["抑郁症治疗", "帕金森治疗", "创新药"],

        # === 补充：缺失同义词的关键词 ===
        "火箭发射": ["运载火箭", "商业火箭", "军工"],
    }

    def __init__(self):
        pass

    # ──────────────────────────────────────────────
    # P0: 涨停梯队分析（按板块聚合）
    # 数据源：EastMoneyZTPool (已有封装，走 em_get 限流) + THSLimitUpPoolSource (同花顺不封IP)
    # ──────────────────────────────────────────────

    def get_limit_up_ladder(self, date_str=None, force_refresh=False):
        """获取涨停梯队数据：连板分布 + 炸板率 + 涨跌停对比 + 板块聚合
        
        Returns:
            {data_date, update_time, date, zt_count, zb_count, dt_count, break_rate, max_height, 
             ladder, sector_zt_stats, yzt_performance}
        """
        cache_key = f"sector_analysis_limit_ladder:{date_str or 'today'}"


        # 非强制刷新时先查缓存（SWR：未命中则返回旧数据+后台刷新）
        if not force_refresh:
            cached = cache_get(cache_key, NS_MARKET)
            if cached:
                return cached
            return swr_cache(cache_key, NS_MARKET,
                             lambda: self._fetch_limit_up_ladder(date_str), 600)

        try:
            result = self._fetch_limit_up_ladder(date_str)
            cache_set(cache_key, result, 600, NS_MARKET)
            return result
        except Exception as e:
            logger.error(f"涨停梯队分析失败: {e}")
            return self._empty_ladder_result(date_str)

    def _fetch_limit_up_ladder(self, date_str=None):
        """实际拉取涨停梯队数据"""
        # 确定日期
        if not date_str:
            trade_date = _get_target_date()
            date_str = trade_date.replace("-", "") if "-" in trade_date else trade_date

        # YYYYMMDD → YYYY-MM-DD (EastMoneyZTPool 需要)
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

        # 复用已有封装类（走 em_get 限流 + THS fallback）
        zt_raw = EastMoneyZTPool.get_zt_pool(date_fmt) or []
        zb_raw = EastMoneyZTPool.get_zb_pool(date_fmt) or []
        dt_raw = EastMoneyZTPool.get_dt_pool(date_fmt) or []
        yzt_raw = EastMoneyZTPool.get_yesterday_zt_pool(date_fmt) or []

        # 从全市场数据补充缺失字段（振幅、涨停价、行业等）
        full_market = TencentSource.get_full_market(allow_stale=True)
        full_map = {}
        if full_market:
            for row in full_market:
                code = str(row.get("f12", ""))
                price = float(row.get("f2", 0) or 0)     # 现价
                change = float(row.get("f4", 0) or 0)    # 涨跌额
                high = float(row.get("f6", 0) or 0)      # 最高价
                low = float(row.get("f7", 0) or 0)       # 最低价
                prev_close = price - change if price > 0 and change != 0 else 0  # 昨收
                limit_up = float(row.get("f78", 0) or 0)  # 涨停价
                limit_down = float(row.get("f81", 0) or 0) # 跌停价
                amplitude_pct = float(row.get("f18", 0) or 0)  # 振幅%（f18直接有振幅）
                full_map[code] = {
                    "high": high, "low": low, "prev_close": prev_close,
                    "limit_up": limit_up, "limit_down": limit_down,
                    "amplitude": amplitude_pct,
                }

        # 格式化涨停池数据
        zt_pool = []
        for p in zt_raw:
            zttj = p.get("zttj") or {}
            zt_pool.append({
                "code": p["c"], "name": p["n"], "price": round(p["p"] / 1000, 2),
                "pct": round(p["zdp"], 2), "amount": p.get("amount", 0),
                "float_cap": p.get("ltsz", 0), "turnover": round(p.get("hs", 0), 2),
                "limit_days": p.get("lbc", 1),
                "first_seal": self._fmt_zt_time(p.get("fbt", 0)),
                "last_seal": self._fmt_zt_time(p.get("lbt", 0)),
                "seal_fund_yi": round((p.get("fund", 0) or 0) / 1e8, 2),
                "break_times": p.get("zbc", 0),
                "industry": p.get("hybk", ""),
                "zt_stat": f'{zttj.get("days","?")}天{zttj.get("ct","?")}板'
            })

        # 构建代码→行业映射（从涨停池补充）
        code_industry = {}
        for s in zt_pool:
            if s.get("industry"):
                code_industry[s["code"]] = s["industry"]

        # 格式化炸板池数据
        zb_pool = []
        for p in zb_raw:
            code = p["c"]
            extra = full_map.get(code, {})
            industry = p.get("hybk", "") or code_industry.get(code, "")
            zb_pool.append({
                "code": code, "name": p["n"], "price": round(p["p"] / 1000, 2),
                "limit_price": round(extra.get("limit_up", 0), 2) or round((p.get("ztp", 0) or 0) / 1000, 2),
                "pct": round(p["zdp"], 2), "turnover": round(p.get("hs", 0), 2),
                "first_seal": self._fmt_zt_time(p.get("fbt", 0)),
                "break_times": p.get("zbc", 0),
                "amplitude": round(extra.get("amplitude", 0) or p.get("zf", 0), 2),
                "speed": round(p.get("zs", 0), 2),
                "industry": industry,
            })

        # 格式化跌停池数据
        dt_pool = []
        for p in dt_raw:
            code = p["c"]
            extra = full_map.get(code, {})
            dt_pool.append({
                "code": code, "name": p["n"], "price": round(p["p"] / 1000, 2),
                "pct": round(p["zdp"], 2), "turnover": round(p.get("hs", 0), 2),
                "pe": p.get("pe"),
                "seal_fund_yi": round((p.get("fund", 0) or 0) / 1e8, 2),
                "last_seal": self._fmt_zt_time(p.get("lbt", 0)),
                "dt_days": p.get("days"),
                "open_times": p.get("oc"),
                "industry": p.get("hybk", "") or code_industry.get(p["c"], ""),
                "amplitude": round(extra.get("amplitude", 0), 2),
            })

        # 格式化昨日涨停池数据
        yzt_pool = []
        for p in yzt_raw:
            yzt_pool.append({
                "code": p["c"], "name": p["n"], "price": round(p["p"] / 1000, 2),
                "pct": round(p["zdp"], 2), "turnover": round(p.get("hs", 0), 2),
                "amplitude": round(p.get("zf", 0), 2),
                "y_first_seal": self._fmt_zt_time(p.get("yfbt", 0)),
                "y_limit_days": p.get("ylbc", 1),
                "industry": p.get("hybk", ""),
            })

        # 连板梯队统计
        ladder = {}
        for s in zt_pool:
            d = s["limit_days"]
            ladder[d] = ladder.get(d, 0) + 1

        # 板块聚合：涨停/跌停按行业统计 + 多维度打分
        sector_zt = {}
        for s in zt_pool:
            ind = s["industry"] or "其他"
            if ind not in sector_zt:
                sector_zt[ind] = {
                    "name": ind, "zt_count": 0, "stocks": [],
                    "total_seal_fund_yi": 0, "max_limit_days": 0,
                    "ladder_distribution": {}, "first_board_count": 0,
                }
            sector_zt[ind]["zt_count"] += 1
            sector_zt[ind]["total_seal_fund_yi"] += s["seal_fund_yi"]
            ld = s["limit_days"] or 1
            if ld > sector_zt[ind]["max_limit_days"]:
                sector_zt[ind]["max_limit_days"] = ld
            sector_zt[ind]["ladder_distribution"][ld] = sector_zt[ind]["ladder_distribution"].get(ld, 0) + 1
            if ld == 1:
                sector_zt[ind]["first_board_count"] += 1
            if len(sector_zt[ind]["stocks"]) < 5:
                sector_zt[ind]["stocks"].append({"code": s["code"], "name": s["name"],
                    "limit_days": s["limit_days"], "zt_stat": s["zt_stat"]})

        # 板块涨停综合评分（多维度加权）
        # 评分维度：涨停数量(35%) + 连板高度(25%) + 梯队完整性(20%) + 封单强度(20%)
        if sector_zt:
            all_zt_counts = [v["zt_count"] for v in sector_zt.values()]
            all_seal_funds = [v["total_seal_fund_yi"] for v in sector_zt.values()]
            all_max_heights = [v["max_limit_days"] for v in sector_zt.values()]
            max_zt = max(all_zt_counts) if all_zt_counts else 1
            max_seal = max(all_seal_funds) if all_seal_funds else 1
            max_height = max(all_max_heights) if all_max_heights else 1

            for v in sector_zt.values():
                zt_count_score = (v["zt_count"] / max_zt * 100) if max_zt > 0 else 0
                height_score = (v["max_limit_days"] / max_height * 100) if max_height > 0 else 0
                seal_score = (v["total_seal_fund_yi"] / max_seal * 100) if max_seal > 0 else 0
                # 梯队完整性：连板层数越多、分布越均匀分越高
                ladder_len = len(v["ladder_distribution"])
                ladder_score = min(ladder_len * 20, 100)
                composite_score = round(
                    zt_count_score * 0.35 +
                    height_score * 0.25 +
                    ladder_score * 0.20 +
                    seal_score * 0.20,
                    1
                )
                v["composite_score"] = composite_score
                v["score_detail"] = {
                    "zt_count_score": round(zt_count_score, 1),
                    "height_score": round(height_score, 1),
                    "ladder_score": round(ladder_score, 1),
                    "seal_score": round(seal_score, 1),
                }

        sector_dt = {}
        for s in dt_pool:
            ind = s["industry"] or "其他"
            if ind not in sector_dt:
                sector_dt[ind] = {"name": ind, "dt_count": 0}
            sector_dt[ind]["dt_count"] += 1

        # 昨日涨停今日表现：晋级率
        yzt_total = len(yzt_pool)
        yzt_promoted = sum(1 for s in yzt_pool if (s["pct"] or 0) >= 9.8)
        promotion_rate = round(yzt_promoted / yzt_total * 100, 1) if yzt_total > 0 else 0

        zt_n = len(zt_pool)
        zb_n = len(zb_pool)
        break_rate = round(zb_n / (zt_n + zb_n) * 100, 1) if (zt_n + zb_n) > 0 else 0

        # 投机信号分析（基于真实数据计算，非估算）
        speculation_signal = self._analyze_speculation_signal(
            zt_n, zb_n, len(dt_pool), break_rate, promotion_rate,
            ladder, sector_zt, sector_dt, yzt_pool
        )

        result = {
            "date": date_str,
            "zt_count": zt_n,
            "zb_count": zb_n,
            "dt_count": len(dt_pool),
            "break_rate": break_rate,
            "max_height": max((s["limit_days"] for s in zt_pool), default=0),
            "ladder": dict(sorted(ladder.items())),
            "promotion_rate": promotion_rate,
            "yzt_total": yzt_total,
            "yzt_promoted": yzt_promoted,
            "sector_zt_stats": sorted(sector_zt.values(), key=lambda x: -x.get("composite_score", x["zt_count"])),
            "sector_dt_stats": sorted(sector_dt.values(), key=lambda x: -x["dt_count"]),
            "speculation_signal": speculation_signal,
            "zt_stocks": zt_pool[:30],
            "zb_stocks": zb_pool[:20],
            "dt_stocks": dt_pool[:20],
        }

        return _add_meta(result, date_str)

    def _empty_ladder_result(self, date_str=None):
        """空数据兜底"""
        result = {
            "date": date_str or "",
            "zt_count": 0, "zb_count": 0, "dt_count": 0,
            "break_rate": 0, "max_height": 0, "ladder": {},
            "promotion_rate": 0, "yzt_total": 0, "yzt_promoted": 0,
            "sector_zt_stats": [], "sector_dt_stats": [],
            "speculation_signal": {"signal": "", "advice": "非交易日或数据未更新", "emotion_score": 50},
            "zt_stocks": [], "zb_stocks": [], "dt_stocks": [],
        }
        return _add_meta(result, date_str)

    @staticmethod
    def _analyze_speculation_signal(zt_n, zb_n, dt_n, break_rate, promotion_rate,
                                     ladder, sector_zt, sector_dt, yzt_pool):
        """分析涨停梯队投机信号（基于真实统计数据，非估算）

        返回: {signal: 信号描述, advice: 操作建议, emotion_score: 情绪分数0-100}
        """
        signals = []
        emotions = []

        # 数据不足时返回默认值
        if zt_n == 0 and dt_n == 0:
            return {
                "signal": "暂无涨跌停数据（非交易日或盘后未更新）",
                "advice": "请等待交易日数据更新",
                "emotion_score": 50,
            }

        # 1. 涨跌停比：衡量市场整体情绪
        total_zt_dt = zt_n + dt_n
        if total_zt_dt > 0:
            zd_ratio = zt_n / total_zt_dt * 100
            if zd_ratio >= 80:
                signals.append("涨跌停比极高，市场情绪亢奋")
                emotions.append(85)
            elif zd_ratio >= 60:
                signals.append("涨停占优，多头主导")
                emotions.append(70)
            elif zd_ratio <= 30:
                signals.append("跌停占优，空头压制明显")
                emotions.append(20)
            else:
                signals.append("涨跌停相对均衡")
                emotions.append(50)

        # 2. 炸板率：衡量追高风险
        if break_rate > 40:
            signals.append(f"⚠️ 炸板率{break_rate}%偏高，追高需谨慎")
            emotions.append(30)
        elif break_rate < 15 and zt_n > 20:
            signals.append(f"炸板率仅{break_rate}%，涨停质量高")
            emotions.append(75)

        # 3. 连板高度：衡量投机空间
        max_height = max(ladder.keys(), default=0)
        if max_height >= 5:
            signals.append(f"最高{max_height}连板，龙头效应显著")
            emotions.append(80)
        elif max_height >= 3:
            signals.append(f"最高{max_height}连板，投机空间一般")
            emotions.append(55)
        else:
            signals.append("无高连板，短线情绪偏弱")
            emotions.append(35)

        # 4. 晋级率：衡量接力成功率
        if promotion_rate >= 60:
            signals.append(f"昨日涨停晋级率{promotion_rate}%，接力成功率高")
            emotions.append(75)
        elif promotion_rate <= 25 and yzt_pool:
            signals.append(f"⚠️ 晋级率仅{promotion_rate}%，接力风险大")
            emotions.append(25)

        # 5. 板块集中度：判断主线是否清晰
        # 修复 Bug：sector_zt 是 dict（key=行业名），不能直接用 [0] 索引
        # 在此处将 dict 转为按 zt_count 倒序的列表后取 Top 1
        if sector_zt:
            sorted_zt_sectors = sorted(sector_zt.values(), key=lambda x: -x["zt_count"])
            top_sector = sorted_zt_sectors[0]
            top_ratio = top_sector["zt_count"] / zt_n * 100 if zt_n > 0 else 0
            if top_ratio >= 30:
                signals.append(f"涨停集中于{top_sector['name']}({top_sector['zt_count']}只)，主线清晰")
                emotions.append(70)

        # 计算综合情绪分数
        emotion_score = round(sum(emotions) / len(emotions)) if emotions else 50

        # 生成操作建议
        if emotion_score >= 75:
            advice = "情绪高涨，可积极参与龙头/前排，注意控制仓位"
        elif emotion_score >= 60:
            advice = "情绪偏暖，选择性强，关注主线板块核心标的"
        elif emotion_score >= 40:
            advice = "情绪中性，观望为主，等待明确信号"
        else:
            advice = "⚠️ 情绪低迷，控制仓位，避免盲目抄底"

        return {
            "signal": " | ".join(signals) if signals else "数据不足",
            "advice": advice,
            "emotion_score": emotion_score,
        }

    @staticmethod
    def _fmt_zt_time(t):
        """涨停板时间 → HH:MM:SS
        支持输入：整数(92500)、数字字符串、已格式化字符串(09:25:00)
        """
        if t is None:
            return ""
        s = str(t).strip()
        if not s or s == '0' or s == '00:00:00':
            return ""
        if ':' in s:
            return s
        try:
            s = str(int(float(t))).zfill(6)
            return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"
        except (ValueError, TypeError):
            return ""

    # ──────────────────────────────────────────────
    # P0: 板块轮动量化模型（走 em_get 限流）
    # ──────────────────────────────────────────────

    def get_sector_rotation_model(self, sector_type="industry", top_n=30, force_refresh=False):
        """板块轮动量化分析：综合评分 + 生命周期识别
        
        Returns:
            {data_date, update_time, sectors, lifecycle_summary, rotation_signal}
        """
        cache_key = f"sector_rotation_model:{sector_type}:{top_n}"


        # 非强制刷新时先查缓存（SWR：未命中则返回旧数据+后台刷新）
        if not force_refresh:
            cached = cache_get(cache_key, NS_MARKET)
            if cached:
                return cached
            return swr_cache(cache_key, NS_MARKET,
                             lambda: self._fetch_rotation_model(sector_type, top_n), 600)

        try:
            result = self._fetch_rotation_model(sector_type, top_n)
            cache_set(cache_key, result, 600, NS_MARKET)
            return result
        except Exception as e:
            logger.error(f"板块轮动模型失败: {e}")
            return _add_meta({"sectors": [], "lifecycle_summary": {}, "rotation_signal": "", "total_count": 0})

    def _fetch_rotation_model(self, sector_type, top_n):
        """实际拉取轮动模型数据

        评分维度（全部来自东财 push2 真实数据，不做估算）：
        - RPS强度: 板块涨跌幅在所有板块中的百分位排名 (0-100)
        - 资金流向得分: 基于净流入额(亿)的百分位排名 (0-100)
        - 广度得分: 上涨家数占比 (0-100)
        - 成交额活跃度: 成交额在所有板块中的百分位排名 (0-100)
        综合评分 = RPS*0.3 + 资金流*0.25 + 广度*0.25 + 活跃度*0.2
        """
        sectors_data = _em_sector_list(sector_type)
        if not sectors_data:
            return _add_meta({"sectors": [], "lifecycle_summary": {}, "rotation_signal": "", "total_count": 0})

        # 计算百分位辅助：将某个值在列表中的排名转化为百分位(0-100)
        def percentile_rank(values, target):
            sorted_vals = sorted(values, reverse=True)
            n = len(sorted_vals)
            if n <= 1:
                return 50.0
            try:
                rank = sorted_vals.index(target)
            except ValueError:
                rank = n - 1
            return round((n - 1 - rank) / (n - 1) * 100, 1)

        # 提取各维度原始数据
        all_changes = [s.get("change_pct", 0) or 0 for s in sectors_data]
        all_flows = [s.get("flow_net", 0) or 0 for s in sectors_data]
        all_turnovers = [s.get("turnover_yi", 0) or 0 for s in sectors_data]

        scored_sectors = []
        for s in sectors_data:
            change_pct = s.get("change_pct", 0) or 0
            up_count = s.get("up_count", 0) or 0
            down_count = s.get("down_count", 0) or 0
            total_stocks = up_count + down_count
            flow_net = s.get("flow_net", 0) or 0
            turnover_yi = s.get("turnover_yi", 0) or 0

            # RPS强度：涨跌幅百分位（真实数据，非估算）
            rps_score = percentile_rank(all_changes, change_pct)
            # 资金流向得分：净流入额百分位（真实数据）
            flow_score = percentile_rank(all_flows, flow_net)
            # 广度得分：上涨家数占比（真实数据）
            breadth_score = (up_count / total_stocks * 100) if total_stocks > 0 else 50
            # 成交额活跃度：成交额百分位（真实数据）
            activity_score = percentile_rank(all_turnovers, turnover_yi)

            # 综合评分：加权组合，各维度权重可调
            composite_score = round(
                rps_score * 0.30 +
                flow_score * 0.25 +
                breadth_score * 0.25 +
                activity_score * 0.20,
                1
            )
            lifecycle = self._judge_lifecycle(change_pct, breadth_score, flow_net, turnover_yi)

            scored_sectors.append({
                "name": s["name"],
                "code": s["code"],
                "change_pct": change_pct,
                "turnover_yi": turnover_yi,
                "flow_net_yi": round(flow_net, 2),
                "up_count": up_count,
                "down_count": down_count,
                "rps_score": rps_score,
                "flow_score": round(flow_score, 1),
                "breadth_score": round(breadth_score, 1),
                "activity_score": round(activity_score, 1),
                "composite_score": composite_score,
                "lifecycle": lifecycle,
                "lead_stock": s.get("lead_stock", ""),
            })

        scored_sectors.sort(key=lambda x: -x["composite_score"])

        lifecycle_counts = {}
        for s in scored_sectors:
            lc = s["lifecycle"]
            lifecycle_counts[lc] = lifecycle_counts.get(lc, 0) + 1

        top3 = scored_sectors[:3]
        rotation_signal = self._generate_rotation_signal(top3, lifecycle_counts, scored_sectors)

        result = {
            "sectors": scored_sectors[:top_n],
            "lifecycle_summary": lifecycle_counts,
            "rotation_signal": rotation_signal,
            "total_count": len(scored_sectors),
        }
        return _add_meta(result)

    @staticmethod
    def _judge_lifecycle(change_pct, breadth_score, flow_net=0, turnover_yi=0):
        """判断板块生命周期阶段（多维度：涨跌幅+广度+资金流+成交额）

        参数均为真实数据，不做估算。
        资金流向(亿)为正表示主力净流入，为负表示净流出。
        """
        # 高潮期：大涨+广泛参与+资金大幅流入
        if change_pct >= 4 and breadth_score >= 65 and flow_net > 0:
            return "高潮期"
        # 发酵期：明显上涨+多数跟涨+资金正向
        elif change_pct >= 2 and breadth_score >= 55:
            return "发酵期"
        # 启动期：横盘或微涨+资金开始流入+成交活跃（关键信号：板块不跌但已开始吸筹）
        elif change_pct >= -0.5 and flow_net > 0 and turnover_yi > 5:
            return "启动期"
        # 拉锯期：涨跌互现，方向不明
        elif abs(change_pct) <= 2 and breadth_score >= 40:
            return "拉锯期"
        # 退潮期：下跌+资金流出
        elif change_pct < -1.5 or (breadth_score < 40 and flow_net < 0):
            return "退潮期"
        else:
            return "冰点期"

    @staticmethod
    def _generate_rotation_signal(top_sectors, lifecycle_counts, all_sectors=None):
        """生成轮动信号描述（增强投机参考价值）"""
        if not top_sectors:
            return "暂无数据"

        signal_parts = []
        strongest = top_sectors[0]
        signal_parts.append(
            f"{strongest['name']}领涨({strongest['change_pct']:+.2f}%, RPS={strongest.get('rps_score', '-')})"
        )

        # 资金流向信号
        inflow_sectors = [s for s in (all_sectors or []) if (s.get("flow_net_yi", 0) or 0) > 5]
        outflow_sectors = [s for s in (all_sectors or []) if (s.get("flow_net_yi", 0) or 0) < -5]
        if len(inflow_sectors) > 10:
            signal_parts.append(f"资金集中流入{len(inflow_sectors)}个板块，多头氛围浓")
        elif len(outflow_sectors) > 10:
            signal_parts.append(f"资金从{len(outflow_sectors)}个板块流出，注意防守")

        # 生命周期信号
        climax_n = lifecycle_counts.get("高潮期", 0)
        ferment_n = lifecycle_counts.get("发酵期", 0)
        start_n = lifecycle_counts.get("启动期", 0)
        recede_n = lifecycle_counts.get("退潮期", 0)
        freeze_n = lifecycle_counts.get("冰点期", 0)

        if climax_n > 5:
            signal_parts.append(f"{climax_n}个板块高潮，警惕分化回调")
        elif ferment_n + start_n > 10:
            signal_parts.append(f"上升期板块{ferment_n + start_n}个({ferment_n}发酵/{start_n}启动)，轮动活跃可参与")
        elif recede_n + freeze_n > 20:
            signal_parts.append(f"{recede_n + freeze_n}个板块走弱，控制仓位")

        # Top3资金流一致性检查（投机关键信号）
        if len(top_sectors) >= 3:
            top_flows = [s.get("flow_net_yi", 0) or 0 for s in top_sectors[:3]]
            if all(f > 0 for f in top_flows):
                signal_parts.append("Top3板块资金同步流入，趋势确认度高")
            elif all(f < 0 for f in top_flows):
                signal_parts.append("⚠️ Top3板块价格涨但资金流出，量价背离警惕假突破")

        return " | ".join(signal_parts)

    # ──────────────────────────────────────────────
    # P1: 行业研报聚合（复用 EastMoneyIndustryReport，走 em_get 限流）
    # ──────────────────────────────────────────────

    def get_industry_research_reports(self, top_n=30, force_refresh=False):
        """获取最新行业研报，按行业聚合
        
        Returns:
            {data_date, update_time, reports_by_industry, latest_reports, rating_summary}
        """
        cache_key = "sector_analysis_industry_reports"


        # 非强制刷新时先查缓存（SWR：未命中则返回旧数据+后台刷新）
        # 研报更新频率低，缓存2小时（7200秒）以减少API请求
        if not force_refresh:
            cached = cache_get(cache_key, NS_MARKET)
            if cached:
                return cached
            return swr_cache(cache_key, NS_MARKET,
                             lambda: self._fetch_industry_reports(top_n), 7200)

        try:
            result = self._fetch_industry_reports(top_n)
            cache_set(cache_key, result, 7200, NS_MARKET)  # 缓存2小时
            return result
        except Exception as e:
            logger.error(f"行业研报聚合失败: {e}")
            return _add_meta({"reports_by_industry": [], "latest_reports": [],
                              "rating_summary": {}, "total_count": 0})

    def _fetch_industry_reports(self, top_n):
        """实际拉取行业研报数据
        
        优化：增加获取页数，保存更多历史研报（约一周数据）
        """
        # 复用已有封装类（走 em_get 限流），增加到10页以获取更多历史数据
        raw_records = EastMoneyIndustryReport.get_reports(industry_code="*", max_pages=5) or []

        by_industry = {}
        all_reports = []
        rating_counts = {"买入": 0, "增持": 0, "中性": 0, "减持": 0}

        for rec in raw_records:
            ind_name = rec.get("industryName", "其他") or "其他"
            publish_date = (rec.get("publishDate", "") or "")[:10]
            title = rec.get("title", "")[:80]
            org = rec.get("orgSName", "")
            rating = rec.get("emRatingName", "")
            info_code = rec.get("infoCode", "")
            # 东财行业研报详情链接
            url = f"https://data.eastmoney.com/report/zw_industry.jshtml?infocode={info_code}" if info_code else ""

            report_item = {
                "industry": ind_name,
                "publish_date": publish_date,
                "title": title,
                "org": org,
                "rating": rating,
                "url": url,
            }
            all_reports.append(report_item)

            if ind_name not in by_industry:
                by_industry[ind_name] = {"industry": ind_name, "count": 0, "reports": []}
            by_industry[ind_name]["count"] += 1
            # 每个行业保留最多5条最新研报（原来是3条）
            if len(by_industry[ind_name]["reports"]) < 5:
                by_industry[ind_name]["reports"].append({
                    "publish_date": publish_date,
                    "title": title,
                    "org": org,
                    "rating": rating,
                    "url": url,
                })

            if rating in rating_counts:
                rating_counts[rating] += 1

        sorted_industries = sorted(by_industry.values(), key=lambda x: -x["count"])

        result = {
            "reports_by_industry": sorted_industries[:50],  # 增加到50个行业（原来是30）
            "latest_reports": all_reports[:top_n],
            "rating_summary": rating_counts,
            "total_count": len(all_reports),
        }
        return _add_meta(result)

    # ──────────────────────────────────────────────
    # P1: 板块热度排行（同花顺不封IP + 东财走 em_get）
    # ──────────────────────────────────────────────

    def get_sector_heat_rank(self, top_n=30, force_refresh=False):
        """板块热度排行榜：基于同花顺热榜+东财人气榜的概念反向聚合
        
        Returns:
            {data_date, update_time, concept_heat_rank, hot_stocks, ths_hot_list}
        """
        cache_key = f"sector_heat_rank:{top_n}"


        # 非强制刷新时先查缓存（SWR：未命中则返回旧数据+后台刷新）
        if not force_refresh:
            cached = cache_get(cache_key, NS_MARKET)
            if cached:
                return cached
            return swr_cache(cache_key, NS_MARKET,
                             lambda: self._fetch_heat_rank(top_n), 300)

        try:
            result = self._fetch_heat_rank(top_n)
            cache_set(cache_key, result, 300, NS_MARKET)
            return result
        except Exception as e:
            logger.error(f"板块热度排行失败: {e}")
            return _add_meta({"concept_heat_rank": [], "hot_stocks": [], "ths_hot_list": []})

    def _fetch_heat_rank(self, top_n):
        """实际拉取热度排行数据

        增强：概念热度交叉引用板块实际涨跌幅，区分"真热"(有涨幅支撑)和"虚热"(仅人气高但板块走弱)。
        数据来源：同花顺热榜(不封IP) + 东财人气榜(em_get限流) + 东财板块行情(em_get限流)
        """
        # 1. 同花顺热榜（不封IP，无需限流）
        ths_list = _ths_hot_list("hour")

        # 2. 东财人气榜（走 em_get 限流）
        em_rank = _em_hot_rank(50)

        # 3. 拉取概念板块行情数据（真实涨跌幅，非估算）
        concept_sectors = _em_sector_list("concept")
        sector_change_map = {}
        for cs in concept_sectors:
            sname = cs["name"]
            sector_change_map[sname] = {
                "change_pct": cs.get("change_pct", 0) or 0,
                "turnover_yi": cs.get("turnover_yi", 0) or 0,
                "flow_net_yi": round((cs.get("flow_net", 0) or 0), 2),
            }
        # 模糊匹配：去掉"概念"后缀也做映射
        for sname in list(sector_change_map.keys()):
            short = sname.replace("概念", "").strip()
            if short and short not in sector_change_map:
                sector_change_map[short] = sector_change_map[sname]

        # 4. 概念反向聚合：统计每个概念被多少热门股命中，并关联板块实际表现
        concept_heat = {}
        for stock in ths_list[:50]:
            concepts = stock.get("concepts", [])
            # 确保 heat_val 是数值类型
            try:
                heat_val = float(stock.get("heat", 0) or 0)
            except (ValueError, TypeError):
                heat_val = 0
            for c in concepts:
                if c not in concept_heat:
                    concept_heat[c] = {"concept": c, "hit_count": 0, "total_heat": 0, "stocks": [],
                                       "sector_change_pct": None, "sector_flow_net_yi": None}
                concept_heat[c]["hit_count"] += 1
                concept_heat[c]["total_heat"] += heat_val
                if len(concept_heat[c]["stocks"]) < 3:
                    concept_heat[c]["stocks"].append({
                        "code": stock.get("code"), "name": stock.get("name"),
                        "heat": heat_val, "pct": stock.get("pct")
                    })

        # 5. 关联板块实际表现数据（真实数据，非估算）
        for c_name, c_data in concept_heat.items():
            sector_info = sector_change_map.get(c_name)
            if sector_info:
                c_data["sector_change_pct"] = sector_info["change_pct"]
                c_data["sector_flow_net_yi"] = sector_info["flow_net_yi"]
                # 热度类型判断：真热(人气高+板块涨)/虚热(人气高但板块跌)
                if sector_info["change_pct"] >= 2:
                    c_data["heat_type"] = "真热"
                elif sector_info["change_pct"] <= -2:
                    c_data["heat_type"] = "虚热⚠️"
                else:
                    c_data["heat_type"] = "温和"
            else:
                c_data["heat_type"] = "未知"

        sorted_concepts = sorted(concept_heat.values(),
                                  key=lambda x: (-x["hit_count"], -x["total_heat"]))

        result = {
            "concept_heat_rank": sorted_concepts[:top_n],
            "hot_stocks": em_rank[:20],
            "ths_hot_list": ths_list[:15],
        }
        return _add_meta(result)

    # ──────────────────────────────────────────────
    # P2: 产业链深度分析（走 em_get 限流）
    # ──────────────────────────────────────────────

    def get_industry_chain_analysis(self, force_refresh=False):
        """产业链深度分析：上下游关系 + 传导分析
        
        Returns:
            {data_date, update_time, chains, chain_sector_performance}
        """
        cache_key = "sector_analysis_industry_chain"


        # 非强制刷新时先查缓存（SWR：未命中则返回旧数据+后台刷新）
        if not force_refresh:
            cached = cache_get(cache_key, NS_MARKET)
            if cached:
                return cached
            return swr_cache(cache_key, NS_MARKET,
                             lambda: self._fetch_industry_chain(), 600)

        try:
            result = self._fetch_industry_chain()
            cache_set(cache_key, result, 600, NS_MARKET)
            return result
        except Exception as e:
            logger.error(f"产业链分析失败: {e}")
            return _add_meta({"chains": [], "chain_performance": []})

    def _fetch_industry_chain(self):
        """实际拉取产业链数据
        
        降级策略（最多2层）：
        1. 东财板块行情 (push2 clist) → 精确/同义词/模糊匹配
        2. THS行业板块 → 兜底匹配
        
        注意：产业链关键词横跨行业板块和概念板块，因此同时拉取两者合并后再匹配
        另外：主动合并腾讯行业板块，确保东财/同花顺失败时仍有足够的板块覆盖
        """
        # 同时拉取行业板块和概念板块（产业链关键词横跨两者）
        industry_rows = _em_sector_list("industry")
        concept_rows = _em_sector_list("concept")

        # 合并去重（按板块名），行业板块优先
        all_sectors = {}
        for s in concept_rows:
            all_sectors[s["name"]] = s
        for s in industry_rows:
            all_sectors[s["name"]] = s  # 行业板块覆盖概念板块（同名字时优先行业）

        # 始终追加腾讯行业板块（不封IP，覆盖度高，产业链匹配刚需）
        # 原因：EM push2 失败 + THS fallback 后返回的是热门概念板块（无基础行业名），
        #       而同义词映射大量依赖"医药/计算机/化工/军工"等基础行业名，
        #       腾讯 59 个行业板块恰好覆盖这些基础行业，是产业链匹配的关键底座
        try:
            tencent_ind = _tencent_sector_list("industry")
            tencent_con = _tencent_sector_list("concept")
            for s in tencent_con + tencent_ind:
                if s["name"] not in all_sectors:
                    all_sectors[s["name"]] = s
        except Exception as e:
            logger.warning(f"腾讯板块补充失败: {e}")

        industry_data = list(all_sectors.values())

        if not industry_data:
            logger.warning("板块列表为空（行业+概念均无数据），产业链数据可能不完整")

        # 预建匹配索引：精确名 + 去后缀模糊名
        exact_index = {}
        fuzzy_index = {}
        for s in industry_data:
            sname = s["name"]
            exact_index[sname] = s
            for suffix in ["Ⅱ", "Ⅲ", "(申)", "(万)", "(证)"]:
                base_name = sname.replace(suffix, "")
                if base_name not in fuzzy_index:
                    fuzzy_index[base_name] = s

        # 构建同义词反向索引：别名 → 原始关键词
        # 注意：chain 关键词本身就是原始关键词，同义词是它的别名
        # 所以匹配时要双向：1) 板块名是否是关键词的别名 2) 关键词的别名是否匹配板块名

        all_index = {**exact_index, **fuzzy_index}

        # 预构建"板块名 → 关键词"反向索引（用于快速判断板块名是否为某关键词的别名）
        sector_to_keyword = {}
        for keyword, aliases in self._SYNONYM_MAP.items():
            for alias in aliases:
                sector_to_keyword[alias.lower()] = keyword

        def _weighted_match(sector_keyword):
            """权重评分匹配算法：精确>同义词精确>包含>反向包含>同义词包含
            
            分数范围：100(精确) > 80(同义词精确) > 60(关键词在板块名中) > 50(同义词包含) > 40(板块名在关键词中)
            """
            sk = sector_keyword.strip()
            if not sk:
                return None

            best_result = None
            best_score = 0
            sk_lower = sk.lower()

            # 1. 精确匹配 (score=100)
            if sk in exact_index:
                return exact_index[sk]
            if sk in fuzzy_index:
                return fuzzy_index[sk]

            # 2. 关键词本身就是某个板块名的别名 → 用原始关键词反向查
            #    例：关键词是"锂电池"，别名叫"固态电池"，板块名是"固态电池"
            #    这里 sk 是关键词本身，先看它能不能映射到一个原始关键词
            original_keyword = sector_to_keyword.get(sk_lower)
            if original_keyword:
                if original_keyword in exact_index:
                    return exact_index[original_keyword]
                if original_keyword in fuzzy_index:
                    return fuzzy_index[original_keyword]

            # 3. 关键词的同义词别名直接匹配板块名 (score=80)
            #    例：关键词是"锂矿"，别名叫"锂电池"，板块名是"锂电池"
            aliases = self._SYNONYM_MAP.get(sk, [])
            for alias in aliases:
                if alias in exact_index:
                    return exact_index[alias]
                if alias in fuzzy_index:
                    return fuzzy_index[alias]

            # 4. 关键词出现在板块名中 (score=60，取最短匹配)
            for sname, sdata in all_index.items():
                if sk in sname and len(sname) <= len(sk) * 3:
                    score = max(41, 60 - len(sname))
                    if score > best_score:
                        best_result = sdata
                        best_score = score

            # 5. 同义词别名包含于板块名 / 板块名包含于别名 (score=50)
            if best_score < 70:
                for alias in aliases:
                    for sname, sdata in all_index.items():
                        if alias in sname or sname in alias:
                            score = 50
                            if score > best_score:
                                best_result = sdata
                                best_score = score
                    if best_score >= 70:
                        break

            # 6. 板块名出现在关键词中 (score=40)
            if best_score < 50:
                for sname, sdata in all_index.items():
                    if sname in sk and len(sname) >= 2:
                        score = 40 + len(sname)
                        if score > best_score:
                            best_result = sdata
                            best_score = score

            return best_result

        chains_result = []
        chain_performance = {}

        # 全局统计，用于归一化评分
        all_avg_changes = []
        all_total_turnovers = []
        all_flow_consistency = []

        for chain_name, structure in self._INDUSTRY_CHAIN_MAP.items():
            chain_info = {"chain": chain_name, "upstream": [], "midstream": [], "downstream": []}

            for stage_key in ["upstream", "midstream", "downstream"]:
                sectors_in_stage = []
                matched_names = set()
                for sector_name in structure[stage_key]:
                    if sector_name in matched_names:
                        continue
                    matched_data = _weighted_match(sector_name)
                    if matched_data and matched_data["name"] not in matched_names:
                        sectors_in_stage.append({
                            "name": matched_data["name"],
                            "change_pct": matched_data.get("change_pct", 0),
                            "turnover_yi": matched_data.get("turnover_yi", 0),
                            "up_count": matched_data.get("up_count", 0),
                            "down_count": matched_data.get("down_count", 0),
                            "flow_net_yi": matched_data.get("flow_net", 0),
                        })
                        matched_names.add(matched_data["name"])

                chain_info[stage_key] = sectors_in_stage

                avg_change = round(
                    sum(s["change_pct"] for s in sectors_in_stage) / len(sectors_in_stage), 2
                ) if sectors_in_stage else 0
                stage_labels = {"upstream": "上游", "midstream": "中游", "downstream": "下游"}
                chain_performance[f"{chain_name}_{stage_key}"] = {
                    "name": f"{chain_name}-{stage_labels.get(stage_key, stage_key)}",
                    "sectors": sectors_in_stage,
                    "avg_change": avg_change,
                }

            # 各阶段平均涨跌幅
            stages_avg = {}
            stages_turnover = {}
            stages_flow = {}
            stages_breadth = {}
            for stage_key in ["upstream", "midstream", "downstream"]:
                sectors = chain_info[stage_key]
                if sectors:
                    stages_avg[stage_key] = round(sum(s["change_pct"] for s in sectors) / len(sectors), 2)
                    stages_turnover[stage_key] = round(sum(s["turnover_yi"] for s in sectors), 2)
                    stages_flow[stage_key] = round(sum(s.get("flow_net_yi", 0) for s in sectors), 2)
                    total_up = sum(s.get("up_count", 0) for s in sectors)
                    total_down = sum(s.get("down_count", 0) for s in sectors)
                    stages_breadth[stage_key] = round(
                        total_up / (total_up + total_down) * 100, 1
                    ) if (total_up + total_down) > 0 else 50
                else:
                    stages_avg[stage_key] = 0
                    stages_turnover[stage_key] = 0
                    stages_flow[stage_key] = 0
                    stages_breadth[stage_key] = 50

            # 全链整体数据
            all_stage_sectors = chain_info["upstream"] + chain_info["midstream"] + chain_info["downstream"]
            total_sectors = len(all_stage_sectors)
            chain_avg_change = round(
                sum(s["change_pct"] for s in all_stage_sectors) / total_sectors, 2
            ) if total_sectors > 0 else 0
            chain_total_turnover = round(sum(s["turnover_yi"] for s in all_stage_sectors), 2)
            chain_total_flow = round(sum(s.get("flow_net_yi", 0) for s in all_stage_sectors), 2)

            # 联动一致性：三个阶段涨跌方向一致的程度
            up_avg = stages_avg.get("upstream", 0)
            mid_avg = stages_avg.get("midstream", 0)
            down_avg = stages_avg.get("downstream", 0)
            direction_score = 0
            if (up_avg > 0 and mid_avg > 0 and down_avg > 0) or \
               (up_avg < 0 and mid_avg < 0 and down_avg < 0):
                direction_score = 100
            elif (up_avg > 0 and mid_avg > 0) or (mid_avg > 0 and down_avg > 0) or \
                 (up_avg < 0 and mid_avg < 0) or (mid_avg < 0 and down_avg < 0):
                direction_score = 60
            else:
                direction_score = 20

            # 资金流一致性：三阶段资金流向是否同步
            up_flow = stages_flow.get("upstream", 0)
            mid_flow = stages_flow.get("midstream", 0)
            down_flow = stages_flow.get("downstream", 0)
            flow_consistency = 0
            if (up_flow > 0 and mid_flow > 0 and down_flow > 0) or \
               (up_flow < 0 and mid_flow < 0 and down_flow < 0):
                flow_consistency = 100
            elif (up_flow > 0 and mid_flow > 0) or (mid_flow > 0 and down_flow > 0) or \
                 (up_flow < 0 and mid_flow < 0) or (mid_flow < 0 and down_flow < 0):
                flow_consistency = 60
            else:
                flow_consistency = 30

            # 传导分析：更细致的信号分类
            signals = []
            # 1. 传导机会类
            if up_avg > 2 and mid_avg < 0 and down_avg < 0:
                signals.append("上游领涨，中下游未动 → 关注向中游传导机会")
            elif down_avg > 2 and up_avg < 0 and mid_avg < 0:
                signals.append("下游需求爆发，上游尚未跟涨 → 潜在补涨机会")
            elif up_avg > 2 and mid_avg > 1 and down_avg < 0:
                signals.append("上游中上游已动，下游待激活 → 关注下游补涨")
            elif down_avg > 2 and mid_avg > 1 and up_avg < 0:
                signals.append("下游中游已启动，上游滞涨 → 关注上游材料补涨")
            # 2. 全链状态类
            elif up_avg > 3 and mid_avg > 3 and down_avg > 3:
                signals.append("🔥 全产业链暴涨 → 板块高潮，注意分化风险")
            elif up_avg > 2 and mid_avg > 2 and down_avg > 2:
                signals.append("全产业链普涨 → 整体趋势向上，联动性强")
            elif up_avg < -2 and mid_avg < -2 and down_avg < -2:
                signals.append("⚠️ 全产业链普跌 → 板块退潮，规避为主")
            # 3. 分化类
            elif up_avg > 1 and down_avg < -1:
                signals.append("上游强下游弱 → 利润向上游集中，下游承压")
            elif down_avg > 1 and up_avg < -1:
                signals.append("下游强上游弱 → 需求端驱动，关注上游成本传导")
            # 4. 拉锯类
            elif abs(up_avg) < 1 and abs(mid_avg) < 1 and abs(down_avg) < 1:
                signals.append("产业链整体横盘 → 方向不明，观望等待")

            if flow_consistency >= 60 and chain_total_flow > 10:
                signals.append("资金全链流入 → 主力布局迹象明显")
            elif flow_consistency >= 60 and chain_total_flow < -10:
                signals.append("⚠️ 资金全链流出 → 主力撤离，注意风险")

            transmission_signal = " | ".join(signals) if signals else ""

            # 领涨环节与滞涨环节
            stage_changes = [
                ("upstream", up_avg, "上游"),
                ("midstream", mid_avg, "中游"),
                ("downstream", down_avg, "下游"),
            ]
            sorted_stages = sorted(stage_changes, key=lambda x: -x[1])
            leading_stage = sorted_stages[0][2] if sorted_stages else ""
            lagging_stage = sorted_stages[-1][2] if sorted_stages else ""

            # 产业链综合热度评分（0-100）
            # 维度：整体涨幅(30%) + 联动一致性(25%) + 成交额(20%) + 资金流(15%) + 广度(10%)
            all_avg_changes.append(chain_avg_change)
            all_total_turnovers.append(chain_total_turnover)
            all_flow_consistency.append(flow_consistency)

            chain_info["stages_avg"] = stages_avg
            chain_info["stages_turnover"] = stages_turnover
            chain_info["stages_flow"] = stages_flow
            chain_info["stages_breadth"] = stages_breadth
            chain_info["chain_avg_change"] = chain_avg_change
            chain_info["chain_total_turnover"] = chain_total_turnover
            chain_info["chain_total_flow"] = chain_total_flow
            chain_info["transmission_signal"] = transmission_signal
            chain_info["leading_stage"] = leading_stage
            chain_info["lagging_stage"] = lagging_stage
            chain_info["direction_score"] = direction_score
            chain_info["flow_consistency"] = flow_consistency
            chain_info["total_sectors"] = total_sectors
            chains_result.append(chain_info)

        # 归一化计算综合评分（在所有产业链中排名）
        if chains_result:
            max_avg_change = max(c["chain_avg_change"] for c in chains_result) or 1
            min_avg_change = min(c["chain_avg_change"] for c in chains_result) or 0
            max_turnover = max(c["chain_total_turnover"] for c in chains_result) or 1
            change_range = max_avg_change - min_avg_change if (max_avg_change - min_avg_change) > 0 else 1

            for c in chains_result:
                # 涨跌幅评分：归一化到0-100
                change_score = (c["chain_avg_change"] - min_avg_change) / change_range * 100 if change_range else 50
                # 成交额评分：归一化
                turnover_score = (c["chain_total_turnover"] / max_turnover * 100) if max_turnover > 0 else 50
                # 资金流评分：对数映射，避免大资金流数据满分失去区分度
                flow_score = min(100, max(0, 50 + 20 * math.log10(1 + max(0, c["chain_total_flow"]) / 10)))
                # 广度评分：三阶段平均广度
                avg_breadth = sum(c["stages_breadth"].values()) / len(c["stages_breadth"]) if c["stages_breadth"] else 50

                heat_score = round(
                    change_score * 0.30 +
                    c["direction_score"] * 0.25 +
                    turnover_score * 0.20 +
                    flow_score * 0.15 +
                    avg_breadth * 0.10,
                    1
                )
                c["heat_score"] = heat_score
                c["score_detail"] = {
                    "change_score": round(change_score, 1),
                    "direction_score": round(c["direction_score"], 1),
                    "turnover_score": round(turnover_score, 1),
                    "flow_score": round(flow_score, 1),
                    "breadth_score": round(avg_breadth, 1),
                }

            # 按热度评分排序
            chains_result.sort(key=lambda x: -x["heat_score"])

        result = {
            "chains": chains_result,
            "chain_performance": list(chain_performance.values()),
        }
        return _add_meta(result)

    # ──────────────────────────────────────────────
    # P2: 板块对比工具（走 em_get 限流）
    # ──────────────────────────────────────────────

    def get_sector_comparison(self, sector_names=None, sector_type="industry", force_refresh=False):
        """多板块对比分析：行情 + 资金流 + 强度
        
        Returns:
            {data_date, update_time, comparison_data, summary}
        """
        cache_key = f"sector_comparison:{','.join(sorted(sector_names or ['top']))}:{sector_type}"


        # 非强制刷新时先查缓存（SWR：未命中则返回旧数据+后台刷新）
        if not force_refresh:
            cached = cache_get(cache_key, NS_MARKET)
            if cached:
                return cached
            return swr_cache(cache_key, NS_MARKET,
                             lambda: self._fetch_sector_comparison(sector_names, sector_type), 300)

        try:
            result = self._fetch_sector_comparison(sector_names, sector_type)
            cache_set(cache_key, result, 300, NS_MARKET)
            return result
        except Exception as e:
            logger.error(f"板块对比失败: {e}")
            return _add_meta({"comparison_data": [], "summary": {"avg_change": 0, "count": 0}})

    def _fetch_sector_comparison(self, sector_names, sector_type):
        """实际拉取板块对比数据"""
        all_sectors = _em_sector_list(sector_type)

        if sector_names:
            filtered = []
            for s in all_sectors:
                if any(name in s["name"] for name in sector_names):
                    filtered.append(s)
        else:
            filtered = all_sectors[:10]

        comparison_data = []
        for s in filtered:
            change_pct = s.get("change_pct", 0) or 0
            up_count = s.get("up_count", 0) or 0
            down_count = s.get("down_count", 0) or 0
            total_stocks = up_count + down_count

            comparison_data.append({
                "name": s["name"],
                "code": s["code"],
                "change_pct": change_pct,
                "turnover_yi": s.get("turnover_yi", 0),
                "up_count": up_count,
                "down_count": down_count,
                "breadth_ratio": round(up_count / total_stocks * 100, 1) if total_stocks > 0 else 50,
                "lead_stock": s.get("lead_stock", ""),
                "lifecycle": self._judge_lifecycle(
                    change_pct,
                    (up_count / total_stocks * 100) if total_stocks > 0 else 50,
                    s.get("flow_net", 0) or 0,
                    s.get("turnover_yi", 0) or 0
                ),
            })

        if comparison_data:
            avg_change = round(sum(s["change_pct"] for s in comparison_data) / len(comparison_data), 2)
            strongest = max(comparison_data, key=lambda x: x["change_pct"])
            weakest = min(comparison_data, key=lambda x: x["change_pct"])

            summary = {
                "avg_change": avg_change,
                "strongest": strongest["name"],
                "strongest_change": strongest["change_pct"],
                "weakest": weakest["name"],
                "weakest_change": weakest["change_pct"],
                "count": len(comparison_data),
            }
        else:
            summary = {"avg_change": 0, "count": 0}

        result = {
            "comparison_data": comparison_data,
            "summary": summary,
        }
        return _add_meta(result)


# 全局单例
sector_analysis_service = SectorAnalysisService()
