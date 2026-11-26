"""统一常量配置 - 消除魔法数字散落各处"""

# ════════════════════════════════════════════════════════
# 缓存 TTL（秒）- 后端
# ════════════════════════════════════════════════════════

# 市场数据：盘中5分钟，前端刷新间隔略短于后端TTL避免穿透
CACHE_TTL_BREADTH = 300            # 全市场广度
CACHE_TTL_SECTOR_QUOTES = 300      # 板块样本行情
CACHE_TTL_MARKET_FLOW = 300        # 大盘主力资金流向
CACHE_TTL_AK_CONCEPTS = 300        # AkShare 概念板块
CACHE_TTL_TRADE_DATE = 3600        # 交易日历

# 财务/个股数据
CACHE_TTL_FINANCIAL = 3600         # 财务数据（1小时）
CACHE_TTL_STOCK_LIST = 86400       # 全市场股票列表（24小时）
CACHE_TTL_CAPITAL_FLOW = 1800      # 个股资金流向（30分钟，东财限流时延长缓存）

# 策略缓存
STRATEGY_CACHE_DRAGON = 180        # 龙虎榜3分钟
STRATEGY_CACHE_PICK = 300          # 智能选股5分钟
STRATEGY_CACHE_HOT_MONEY = 600     # 游资追踪10分钟
STRATEGY_CACHE_ML_PREDICT = 300    # ML预测5分钟
STRATEGY_CACHE_DRAGON_CONSECUTIVE = 600   # 连板统计10分钟
STRATEGY_CACHE_DRAGON_HISTORY = 3600      # 历史回查1小时

# ════════════════════════════════════════════════════════
# 前端缓存 TTL（毫秒）- 略短于后端TTL避免穿透
# ════════════════════════════════════════════════════════

FRONTEND_CACHE_REALTIME = {
    "storage_ttl": 60_000,       # 1分钟存储
    "refresh_interval": 25_000,  # 25秒刷新（后端TTL=30s）
}
FRONTEND_CACHE_MARKET = {
    "storage_ttl": 4 * 60_000,   # 4分钟存储（后端TTL=5min，错开1min）
    "refresh_interval": 4 * 60_000,
}
FRONTEND_CACHE_STOCK = {
    "storage_ttl": 9 * 60_000,   # 9分钟存储（后端TTL=10min）
    "refresh_interval": 9 * 60_000,
}
FRONTEND_CACHE_STRATEGY = {
    "storage_ttl": 2 * 60 * 60_000,  # 2小时存储
    "refresh_interval": 4 * 60_000,   # 4分钟刷新（后端TTL=5min）
}
FRONTEND_CACHE_REPORT = {
    "storage_ttl": 3 * 60 * 60_000,  # 3小时存储
    "refresh_interval": 9 * 60_000,   # 9分钟刷新（后端TTL=10min）
}
FRONTEND_CACHE_LIST = {
    "storage_ttl": 3 * 60 * 60_000,  # 3小时存储
    "refresh_interval": 4 * 60_000,   # 4分钟刷新（后端TTL=5min）
}
FRONTEND_CACHE_USER = {
    "storage_ttl": 4 * 60_000,        # 4分钟存储
    "refresh_interval": 4 * 60_000,
}

# ════════════════════════════════════════════════════════
# 评分阈值
# ════════════════════════════════════════════════════════

RATING_STRONG_BUY = 80   # ≥80 强烈推荐
RATING_BUY = 70          # 70-79 推荐
RATING_HOLD = 60         # 60-69 观望
# <60 回避

# ════════════════════════════════════════════════════════
# AkShare并发控制
# ════════════════════════════════════════════════════════

AKSHARE_MAX_CONCURRENT = 3  # 最大并发AkShare请求数
AKSHARE_TIMEOUT = 30        # AkShare请求超时（秒）

# ════════════════════════════════════════════════════════
# 资讯缓存
# ════════════════════════════════════════════════════════

NEWS_CACHE_TTL = 600         # 资讯10分钟TTL
RESEARCH_CACHE_TTL = 1800   # 研报30分钟TTL（更新频率低，缓存更久）
NEWS_RETENTION_DAYS = 7      # 资讯保留天数（过滤过期数据）
RESEARCH_RETENTION_DAYS = 7  # 研报保留天数

# ════════════════════════════════════════════════════════
# 全市场缓存
# ════════════════════════════════════════════════════════

FULL_MARKET_CACHE_TTL = 300   # 全市场行情缓存5分钟
PRICE_MAP_CACHE_TTL = 60      # 价格映射缓存60秒

# ════════════════════════════════════════════════════════
# 默认配额
# ════════════════════════════════════════════════════════

DEFAULT_QUOTAS = {
    "normal": 30,
    "vip": 200,
    "admin": 9999,
}

