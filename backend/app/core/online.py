"""用户在线状态追踪 - 基于心跳机制的内存存储"""
import time
from threading import Lock

# 用户ID -> 最后心跳时间(秒级时间戳)
_online_users = {}
_lock = Lock()

# 离线超时阈值（秒）
OFFLINE_TIMEOUT = 30


def heartbeat(user_id: int) -> None:
    """记录用户心跳"""
    with _lock:
        _online_users[user_id] = time.time()


def is_online(user_id: int) -> bool:
    """判断用户是否在线（最近OFFLINE_TIMEOUT秒内有心跳）"""
    with _lock:
        last = _online_users.get(user_id)
        if last is None:
            return False
        return (time.time() - last) < OFFLINE_TIMEOUT


def get_online_user_ids() -> list[int]:
    """获取所有在线用户ID列表"""
    now = time.time()
    with _lock:
        return [uid for uid, ts in _online_users.items() if (now - ts) < OFFLINE_TIMEOUT]


def remove_user(user_id: int) -> None:
    """移除用户（如注销、禁用时）"""
    with _lock:
        _online_users.pop(user_id, None)
