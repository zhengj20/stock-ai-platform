"""请求去重工具：相同 key 的并发请求只执行一次，其余等待结果共享。

用法：
    from app.core.dedupe import dedupe_request, dedupe_with_timeout

    async def my_endpoint():
        key = f"my_endpoint:{param1}:{param2}"
        return await dedupe_with_timeout(key, lambda: asyncio.to_thread(do_work), timeout=30)
"""
import asyncio
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)

_inflight: dict[str, asyncio.Future] = {}
_inflight_lock = asyncio.Lock()


async def dedupe_request(key: str, func: Callable[[], Any]) -> Any:
    """请求去重：相同 key 的并发请求只执行一次，其余等待共享结果。

    Args:
        key: 唯一标识请求的键
        func: 实际执行的异步函数（或返回协程的可调用对象）

    Returns:
        函数执行结果

    Raises:
        原函数抛出的任何异常
    """
    async with _inflight_lock:
        if key in _inflight and not _inflight[key].done():
            future = _inflight[key]
            logger.debug(f"请求去重命中，共享已有 Future: {key}")
            return await future

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        _inflight[key] = future

    try:
        result = await func()
        if not future.done():
            future.set_result(result)
        return result
    except Exception as e:
        if not future.done():
            future.set_exception(e)
        raise
    finally:
        async with _inflight_lock:
            _inflight.pop(key, None)


async def dedupe_with_timeout(key: str, func: Callable[[], Any], timeout: float) -> Any:
    """带超时的请求去重。

    Args:
        key: 唯一标识请求的键
        func: 实际执行的异步函数
        timeout: 超时时间（秒）

    Returns:
        函数执行结果

    Raises:
        asyncio.TimeoutError: 超时
        原函数抛出的任何异常
    """
    try:
        return await asyncio.wait_for(dedupe_request(key, func), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"请求超时 ({timeout}s): {key}")
        raise
