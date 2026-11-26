"""统一数据源层 — 从 data_sources_clean 导入所有符号

原 data_sources.py 已被 Markdown 格式污染（转义字符+缩进丢失），
此文件作为兼容桥接，将所有符号重新导出。
"""
from app.core.data_sources_clean import (
    # 东财请求基础设施
    em_get,
    em_get_clean,
    em_get_datacenter,
    em_post,
    _EM_HEADERS,
    _EM_SESSION,
    _EM_MIN_INTERVAL,
    EM_MIN_INTERVAL,
    query_datacenter,

    # 工具函数
    call_with_timeout,

    # 东财数据中心 (龙虎榜/融资融券等)
    EastMoneyDataCenterClean,
    EastMoneyDataCenter,
    dragon_tiger_board,
    dragon_tiger_board_range,
    dragon_tiger_seats,
    margin_trading,
    block_trade,
    holder_num_change,
    dividend_history,
    lockup_expiry,

    # 腾讯财经
    TencentSource,

    # 涨停板数据
    EastMoneyZTPool,

    # 北向资金
    THSNorthboundSource,
    _ths_throttle,

    # mootdx
    MootdxSource,

    # 东财通用源
    EastMoneySource,
    THSSectorBuilder,

    # 巨潮公告
    CNInfoSource,

    # 新闻
    EastMoneyNewsSource,

    # 同花顺热点
    THSHotSource,

    # 资金流
    THSCapitalFlowSource,

    # 涨停板池
    THSLimitUpPoolSource,

    # 一致预期
    THSConsensusSource,

    # 研报
    EastMoneyIndustryReport,

    # 资金流历史
    EastMoneyFlowHistory,

    # 辅助函数
    get_last_trade_date,
)

__all__ = [
    "em_get", "em_get_clean", "em_get_datacenter", "em_post", "_EM_HEADERS", "_EM_SESSION",
    "_EM_MIN_INTERVAL", "EM_MIN_INTERVAL",
    "query_datacenter", "call_with_timeout",
    "EastMoneyDataCenterClean", "EastMoneyDataCenter",
    "dragon_tiger_board", "dragon_tiger_board_range", "dragon_tiger_seats",
    "margin_trading", "block_trade", "holder_num_change", "dividend_history",
    "lockup_expiry",
    "TencentSource", "EastMoneyZTPool", "THSNorthboundSource", "_ths_throttle",
    "MootdxSource", "EastMoneySource", "THSSectorBuilder",
    "CNInfoSource", "EastMoneyNewsSource", "THSHotSource",
    "THSCapitalFlowSource", "THSLimitUpPoolSource", "THSConsensusSource",
    "EastMoneyIndustryReport", "EastMoneyFlowHistory", "get_last_trade_date",
]
