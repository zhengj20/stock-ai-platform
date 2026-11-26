"""统一日志配置 - 所有日志输出到 logs/ 目录"""
import os
import sys
import shutil
import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

# 日志目录（项目根/logs）
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

# 单文件最大5MB，保留3个备份
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3

_LOG_FORMATTER = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class ConnectionResetFilter(logging.Filter):
    """过滤 Windows asyncio 的 ConnectionResetError 警告

    Windows Proactor 事件循环在远程主机关闭连接时会触发此错误，
    属于正常行为，无需记录。
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and record.exc_info[0] is ConnectionResetError:
            return False
        if "ConnectionResetError" in record.getMessage():
            return False
        if "_call_connection_lost" in record.getMessage():
            return False
        return True


class SafeRotatingFileHandler(RotatingFileHandler):
    """Windows 安全的日志轮转处理器：完整重写 doRollover，避免 PermissionError"""

    @staticmethod
    def _safe_rename(src, dst):
        """安全重命名/移动文件，Windows 下被占用时 fallback 到 copy+delete"""
        if not os.path.exists(src):
            return
        try:
            if os.path.exists(dst):
                os.remove(dst)
            os.rename(src, dst)
        except PermissionError:
            # Windows：目标文件被占用，复制覆盖后删除源文件
            try:
                shutil.copy2(src, dst)
                os.remove(src)
            except OSError:
                pass  # 最坏情况：本轮转跳过，下次再试

    def doRollover(self):
        if self.stream:
            self.stream.close()
            self.stream = None
        if self.backupCount > 0:
            # 备份文件向后移动：.log.2 → .log.3 ...
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename(f"{self.baseFilename}.{i}")
                dfn = self.rotation_filename(f"{self.baseFilename}.{i + 1}")
                self._safe_rename(sfn, dfn)
            # 当前文件 → .log.1
            dfn = self.rotation_filename(self.baseFilename + ".1")
            self._safe_rename(self.baseFilename, dfn)
        if not self.delay:
            self.stream = self._open()


def setup_logging(level: str = "INFO") -> None:
    """配置全局日志，调用一次即可"""
    log_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()

    # 添加 ConnectionResetError 过滤器
    _conn_reset_filter = ConnectionResetFilter()

    # 控制台输出
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(_LOG_FORMATTER)
    console.addFilter(_conn_reset_filter)
    root.addHandler(console)

    # 应用日志 → logs/app.log（5MB轮转，保留3个备份）
    app_handler = SafeRotatingFileHandler(
        os.path.join(_LOG_DIR, "app.log"),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    app_handler.setLevel(log_level)
    app_handler.setFormatter(_LOG_FORMATTER)
    app_handler.addFilter(_conn_reset_filter)
    root.addHandler(app_handler)

    # 错误日志 → logs/error.log（5MB轮转，保留3个备份）
    err_handler = SafeRotatingFileHandler(
        os.path.join(_LOG_DIR, "error.log"),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    err_handler.setLevel(logging.WARNING)
    err_handler.setFormatter(_LOG_FORMATTER)
    err_handler.addFilter(_conn_reset_filter)
    root.addHandler(err_handler)


def cleanup_old_logs(days: int = 7) -> int:
    """清理超过指定天数的日志备份文件（.log.1, .log.2等）"""
    if not os.path.isdir(_LOG_DIR):
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    deleted = 0
    for name in os.listdir(_LOG_DIR):
        # 匹配轮转备份文件：app.log.1, app.log.2, error.log.1 等
        if not (name.endswith('.log') or '.log.' in name):
            continue
        full_path = os.path.join(_LOG_DIR, name)
        if not os.path.isfile(full_path):
            continue
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(full_path))
            # 只清理备份文件（带数字后缀），不清理当前活跃日志
            if '.log.' in name and mtime < cutoff:
                os.remove(full_path)
                deleted += 1
        except OSError:
            pass
    return deleted
