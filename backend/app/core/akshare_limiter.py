# -*- coding: utf-8 -*-
"""[已废弃] AkShare 并发控制模块

此模块已被废弃。所有 akshare 调用已替换为直连 API：
- A股行情/板块/龙虎榜 -> EastMoney push2 (data_sources.py)
- K线数据 -> pytdx/mootdx (pytdx_source.py)  
- PE/PB/市值 -> 腾讯财经 (TencentSource)
- 北向资金 -> 同花顺 hsgtApi (THSNorthboundSource)

仅 daily_report_service.py 保留 akshare 用于全球指数/期货/外汇数据。
"""
import asyncio
import threading
import logging
from functools import wraps
from typing import Callable, Any

logger = logging.getLogger(__name__)

# 全局信号量：限制 AkShare 最大并发数（避免 FastAPI 线程池被打满）
_akshare_semaphore = None
_semaphore_lock = threading.Lock()


def _get_semaphore(max_concurrent: int = 10) -> asyncio.Semaphore:
    """获取或创建 AkShare 并发信号量"""
    global _akshare_semaphore
    with _semaphore_lock:
        if _akshare_semaphore is None:
            _akshare_semaphore = asyncio.Semaphore(max_concurrent)
    return _akshare_semaphore


def akshare_limited(func: Callable) -> Callable:
    """装饰器：限制 AkShare 调用并发数
    
    用法（同步函数）：
        @akshare_limited
        def get_data():
            import akshare as ak
            return ak.stock_zt_pool_em(...)
    
    用法（异步包装）：
        data = await asyncio.to_thread(akshare_limited(get_data))
    """
    # 同步版本：使用 threading.Semaphore
    _thread_semaphore = threading.Semaphore(3)
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        with _thread_semaphore:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.debug(f"AkShare 调用失败 [{func.__name__}]: {e}")
                raise
    
    return sync_wrapper


class AkshareThrottle:
    """AkShare 节流器 - 用于异步上下文中"""
    
    def __init__(self, max_concurrent: int = 3):
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """在信号量保护下执行 AkShare 调用"""
        async with self._semaphore:
            return await asyncio.to_thread(func, *args, **kwargs)


# 全局节流器实例（供异步代码使用）
akshare_throttle = AkshareThrottle(max_concurrent=3)

