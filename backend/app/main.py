"""FastAPI 主应用入口"""
import os
import uuid
from contextvars import ContextVar
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager
import asyncio
import logging
import os
import json
from datetime import datetime
from typing import Optional

from app.core.config import get_settings

settings = get_settings()

# API 限流（slowapi）：按客户端 IP 限速
limiter = Limiter(key_func=get_remote_address, default_limits=[])

from app.api import market, stock, strategy, nlp, chat, watchlist, auth, admin, chat_history, daily_reports, preload, ai_stock_picks, sector_analysis, sim_trading, holdings, watchlist_strategy, backtest, alerts, decision

# 请求 ID 上下文：中间件写入，业务代码可通过 get_request_id() 读取
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    """日志过滤器：自动注入当前请求的 request_id"""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True

# 前端构建产物目录（项目根/frontend/dist）
_FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "frontend", "dist")

# 统一日志配置（输出到 logs/ 目录）
from app.core.logging_config import setup_logging
setup_logging(settings.LOG_LEVEL)

# 给所有 logger 加上 RequestIdFilter，并在日志格式中显示 request_id
_RID_FORMAT = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(request_id)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_rid_filter = RequestIdFilter()
_root = logging.getLogger()
for _h in _root.handlers:
    _h.addFilter(_rid_filter)
    _h.setFormatter(_RID_FORMAT)

app = FastAPI()
logger = logging.getLogger(__name__)


# 定时任务 leader 选举 - 防止多 worker 重复触发 15:30 复盘报告
_DATA_DIR = os.path.dirname(settings.DB_PATH)
_LEADER_LOCK_FILE = os.path.join(_DATA_DIR, "scheduler_leader.lock")
_scheduler_is_leader = False

# 盘中监控各子任务的时间戳（模块级，_intraday_monitor 通过 global 引用）
_last_price_update = 0.0        # 价格更新：每60秒
_last_risk_check = 0.0          # 风控检查：每120秒
_last_order_match = 0.0         # 委托撮合：每60秒
_last_t_trade = 0.0             # 做T检测：每600秒
_last_strategy_exec = 0.0      # 策略执行：每N分钟（可配置）
_strategy_exec_interval = 300   # 策略执行间隔（秒），由 _run_scheduled_tasks 从配置更新
_last_short_close_check = 0.0   # 收盘前短仓清理检查（每天14:50执行一次）
_last_strategy_regenerate_ts = 0.0  # 上次剧变触发策略重生成时间戳（防抖）
_last_market_snapshot = None    # 上次市场快照（指数涨跌幅+账户盈亏），用于剧变检测
_last_decision_alert_ts = 0.0   # 决策算法预警：每10分钟
_last_market_preheat_ts = 0.0   # 市场看板/龙虎榜预热时间戳（模块级，供 _startup_preheat 和调度循环共享）


def _is_process_alive_windows(pid: int) -> bool:
    """Windows 平台可靠地判断进程是否存活

    使用 OpenProcess + GetExitCodeProcess 组合检测：
    - OpenProcess 返回 0：进程不存在或无权限（视为已死）
    - OpenProcess 返回非 0，但 GetExitCodeProcess 返回 STILL_ACTIVE(259)：进程存活
    - OpenProcess 返回非 0，但退出码不是 259：进程已退出（句柄被复用，但实际进程已死）

    解决原代码的 Bug：
    - 仅靠 OpenProcess 返回非 0 判定存活不可靠（PID 复用、僵尸句柄等场景会误判）
    - 静默吞掉异常导致锁文件无法清理（93 次启动都未清理死锁文件）
    """
    if pid <= 0:
        return False

    try:
        import ctypes
        from ctypes import wintypes

        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        # 比 PROCESS_QUERY_INFORMATION(1) 更通用，可查询大多数进程
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # OpenProcess 失败：进程不存在或无权限访问
            # 注意：权限不足时（ERROR_ACCESS_DENIED=5）也视为不可访问，等同死锁
            return False

        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                # GetExitCodeProcess 失败：保守视为存活，避免误清理
                return True
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception as e:
        logger.warning(f"Windows 进程存活检测异常 (pid={pid}): {e}")
        # 异常时保守视为存活，避免误清理正在运行的 leader 锁
        return True


def _is_process_alive_unix(pid: int) -> bool:
    """Unix 平台判断进程是否存活（signal 0 不实际发送信号）"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _try_acquire_scheduler_leader() -> bool:
    """多 worker 启动时仅一个能获得 leader 锁

    使用原子 O_CREAT|O_EXCL，跨平台兼容（Linux/Windows Python 3.3+）

    修复历史 Bug：
    1. Windows 上 OpenProcess 仅靠返回值不可靠（PID 复用、僵尸句柄），
       改用 OpenProcess + GetExitCodeProcess 组合检测 STILL_ACTIVE 状态
    2. 增加锁文件 TTL 兜底（默认 1 小时）：避免清理逻辑被静默吞错导致永久死锁
    3. 清理失败时记录 WARNING 日志（原代码静默吞掉，无法排查）
    """
    global _scheduler_is_leader
    import time as _time

    # 锁文件 TTL：超过此时间未更新视为僵尸锁（覆盖任何清理失败的场景）
    # 1 小时足够所有定时任务完成（最长的 LLM 任务约 10 分钟）
    _LEADER_LOCK_TTL_SECONDS = 3600

    try:
        os.makedirs(_DATA_DIR, exist_ok=True)

        # 旧锁清理：PID 已退出 或 锁文件超过 TTL
        if os.path.exists(_LEADER_LOCK_FILE):
            should_remove = False
            remove_reason = ""

            try:
                # TTL 兜底：检查文件 mtime，超时直接清理
                file_mtime = os.path.getmtime(_LEADER_LOCK_FILE)
                if _time.time() - file_mtime > _LEADER_LOCK_TTL_SECONDS:
                    should_remove = True
                    remove_reason = f"锁文件超过 TTL {_LEADER_LOCK_TTL_SECONDS}s（mtime 太老）"

                if not should_remove:
                    try:
                        with open(_LEADER_LOCK_FILE, "r", encoding="utf-8") as f:
                            old_pid = int(f.read().strip() or "0")
                    except (OSError, ValueError) as e:
                        # 文件内容损坏（非数字、空文件等）：直接清理
                        should_remove = True
                        remove_reason = f"锁文件内容损坏: {e}"

                    # 同进程重复启动（reload 测试）视为 leader
                    if not should_remove and old_pid == os.getpid():
                        _scheduler_is_leader = True
                        return True

                    if not should_remove and old_pid > 0:
                        if os.name == 'nt':
                            is_alive = _is_process_alive_windows(old_pid)
                        else:
                            is_alive = _is_process_alive_unix(old_pid)

                        if not is_alive:
                            should_remove = True
                            remove_reason = f"PID {old_pid} 已退出"

                if should_remove:
                    try:
                        os.remove(_LEADER_LOCK_FILE)
                        logger.info(f"清理僵尸 leader 锁: {remove_reason}")
                    except OSError as e:
                        logger.warning(f"清理 leader 锁失败（可能被其他进程持有）: {e}")
                        # 清理失败时直接尝试 O_EXCL 创建，若仍失败则按未获得锁处理
            except Exception as e:
                logger.warning(f"leader 锁清理逻辑异常: {e}")

        fd = os.open(_LEADER_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        _scheduler_is_leader = True
        logger.info(f"本进程 (pid={os.getpid()}) 获得 scheduler leader 锁")
        return True
    except FileExistsError:
        logger.info(f"本进程 (pid={os.getpid()}) 未获得 scheduler leader 锁（已被其他进程持有）")
        return False
    except Exception as e:
        logger.warning(f"scheduler leader 选举失败: {e}")
        return False


def init_admin_user():
    """首次启动时自动创建管理员账号和邀请码"""
    from app.core.database import SessionLocal, init_db
    from app.models.user import User, InviteCode
    from app.core.auth import get_password_hash

    # 初始化数据库表
    init_db()

    db = SessionLocal()
    try:
        # 检查是否已有用户
        existing_users = db.query(User).count()
        if existing_users == 0:
            logger.info("首次启动，创建管理员账号...")

            import secrets

            # 未配置 ADMIN_PASSWORD 时随机生成，避免公开仓库里的默认弱口令
            generated_password = ""
            admin_password = settings.ADMIN_PASSWORD
            if not admin_password:
                admin_password = secrets.token_urlsafe(9)
                generated_password = admin_password

            admin_user = User(
                username=settings.ADMIN_USERNAME,
                email="admin@localhost",
                password_hash=get_password_hash(admin_password),
                role="admin",
                status="active",
            )
            db.add(admin_user)
            db.flush()

            # 生成初始邀请码
            logger.info(f"生成 {settings.INITIAL_INVITE_CODES} 个初始邀请码...")
            for _ in range(settings.INITIAL_INVITE_CODES):
                code = InviteCode(
                    code=secrets.token_hex(8),
                    created_by=admin_user.id,
                )
                db.add(code)

            db.commit()
            logger.info(f"管理员账号已创建: {settings.ADMIN_USERNAME}")
            if generated_password:
                logger.warning(
                    "未配置 ADMIN_PASSWORD，已生成随机初始密码（仅本次启动显示，请立即登录修改）: %s",
                    generated_password,
                )
            else:
                logger.warning("请在生产环境中修改默认密码！")
        else:
            logger.info("数据库已有用户，跳过初始化")
    except Exception as e:
        db.rollback()
        logger.error(f"管理员初始化失败: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("A股智能分析平台启动中...")
    logger.info(f"技能目录: {settings.SKILLS_DIR}")

    # 初始化管理员和数据库
    await asyncio.to_thread(init_admin_user)

    # 启动时恢复/校准模拟交易数据：WAL checkpoint + 清理重复账户
    try:
        from app.core.database import SessionLocal
        from app.services.sim_trading_maintenance import run_startup_maintenance
        await asyncio.to_thread(run_startup_maintenance)
        logger.info("模拟交易数据恢复完成")
    except Exception as e:
        logger.warning(f"模拟交易启动恢复失败: {e}")

    # 初始化默认配额配置
    try:
        from app.core.database import SessionLocal
        from app.services.quota_service import init_default_quotas
        def _init_quotas():
            db = SessionLocal()
            try:
                init_default_quotas(db)
            finally:
                db.close()
        await asyncio.to_thread(_init_quotas)
        logger.info("配额配置初始化完成")
    except Exception as e:
        logger.warning(f"配额配置初始化失败: {e}")

    # 清理过期对话记录（放后台任务执行，不阻塞应用启动）
    async def _cleanup_old_data_async():
        try:
            from app.core.database import SessionLocal
            from app.api.chat_history import cleanup_old_data
            await asyncio.to_thread(_do_cleanup_old_data)
        except Exception as e:
            logger.warning(f"清理过期数据失败: {e}")

    def _do_cleanup_old_data():
        from app.core.database import SessionLocal
        from app.api.chat_history import cleanup_old_data
        from app.models.sim_trading import SimAccount
        from app.services.order_service import OrderService
        db = SessionLocal()
        try:
            deleted = cleanup_old_data(db, days=30)
            if deleted > 0:
                logger.info(f"已清理 {deleted} 条过期对话记录")
            # 启动时也清理 30 天前的 cancelled 委托（不影响当日 filled/expired）
            for acc in db.query(SimAccount).all():
                cancelled_deleted = OrderService.cleanup_old_cancelled(db, acc.id, days=30)
                if cancelled_deleted > 0:
                    logger.info(f"账户 {acc.id} 启动时清理 {cancelled_deleted} 条 30 天前 cancelled 委托")
        finally:
            db.close()

    asyncio.create_task(_cleanup_old_data_async())

    # 启动定时任务：仅 leader 进程执行（防多 worker 重复触发 15:30 复盘）
    if _try_acquire_scheduler_leader():
        _scheduled_task = asyncio.create_task(_run_scheduled_tasks())
        # 启动后立即预热市场缓存（不阻塞启动，不依赖交易时段）
        asyncio.create_task(_startup_preheat())
        
        # 启动预计算服务
        try:
            from app.services.precompute_service import precompute_service
            precompute_service.start()
            logger.info("预计算服务已启动")
        except Exception as e:
            logger.warning(f"预计算服务启动失败: {e}")
    else:
        _scheduled_task = None
    
    # 启动任务队列（所有worker都需要）
    try:
        from app.services.task_queue import task_queue
        task_queue.start()
        logger.info("任务队列已启动")
    except Exception as e:
        logger.warning(f"任务队列启动失败: {e}")

    yield

    if _scheduled_task is not None:
        _scheduled_task.cancel()
        try:
            await _scheduled_task
        except asyncio.CancelledError:
            pass

    # 显式取消统一调度中的后台 LLM 任务（asyncio.create_task 启动的子任务不会被 _scheduled_task.cancel 级联取消）
    # 修复 Bug：原代码 cancel 后立即 clear，未 await 任务真正结束，finally 块可能未执行。
    # 此外 asyncio.to_thread 底层线程不会因 cancel 中止，需给线程留出收尾时间再执行 WAL checkpoint。
    _cancelled_tasks = []
    for _tk, _task in list(_running_long_tasks.items()):
        if not _task.done():
            _task.cancel()
            _cancelled_tasks.append(_task)
            logger.info(f"关闭后台任务: {_tk}")
    if _cancelled_tasks:
        await asyncio.gather(*_cancelled_tasks, return_exceptions=True)
    _running_long_tasks.clear()
    # 给 asyncio.to_thread 底层线程留出收尾时间（cancel 不会中止底层线程）
    await asyncio.sleep(2)
    
    # 停止预计算服务
    try:
        from app.services.precompute_service import precompute_service
        precompute_service.stop()
        logger.info("预计算服务已停止")
    except Exception:
        pass
    
    # 停止任务队列
    try:
        from app.services.task_queue import task_queue
        task_queue.stop()
        logger.info("任务队列已停止")
    except Exception:
        pass

    # 关闭前强制 WAL checkpoint，确保所有未刷盘数据落盘
    try:
        from sqlalchemy import text
        from app.core.database import SessionLocal
        db = SessionLocal()
        db.execute(text("PRAGMA wal_checkpoint(FULL)"))
        db.close()
        logger.info("关闭前 WAL checkpoint 完成")
    except Exception as e:
        logger.warning(f"关闭前 WAL checkpoint 失败: {e}")

    # 释放 leader 锁
    if _scheduler_is_leader and os.path.exists(_LEADER_LOCK_FILE):
        try:
            os.remove(_LEADER_LOCK_FILE)
        except OSError:
            pass

    logger.info("A股智能分析平台已关闭")


async def _run_scheduled_tasks():
    """后台定时任务循环"""
    from datetime import datetime, time as dtime
    from app.core.database import SessionLocal
    from app.core.trading_calendar import is_trading_day, is_trading_hours, get_last_trade_date
    from app.models.daily_report import DailyReport
    from app.models.ai_stock_pick import AIStockPick
    from app.models.scheduler_config import SchedulerConfig
    from app.services.ai_stock_pick_service import ai_stock_pick_service

    # ============================================================
    # 启动时从 DB 恢复当天任务执行标记
    # 防止服务重启后 _sched_last_run 丢失导致任务漏执行（或重复执行）
    # ============================================================
    try:
        _recover_db = SessionLocal()
        _recover_today = datetime.now().strftime("%Y-%m-%d")
        try:
            # AI 股票推荐（pick_time）
            if _recover_db.query(AIStockPick).filter(
                AIStockPick.pick_date == _recover_today,
                AIStockPick.status == "completed",
            ).first():
                _sched_last_run["pick_time"] = _recover_today
                logger.info(f"[启动恢复] pick_time 当天已完成，标记为已执行")

            # AI 复盘报告（report_time）
            if _recover_db.query(DailyReport).filter(
                DailyReport.report_date == _recover_today,
                DailyReport.status == "completed",
            ).first():
                _sched_last_run["report_time"] = _recover_today
                logger.info(f"[启动恢复] report_time 当天已完成，标记为已执行")

            # 模拟交易 AI 策略（按 strategy_mode 区分）
            try:
                from app.models.sim_trading import AIStrategyDecision
                # ── review_strategy_time：检查今天是否生成了明天的策略（不是检查今天的策略）───
                # next_day 模式的 decision_date = 执行日期（明天），created_at = 生成时间（今天收盘后）
                # Bug修复：原代码用 decision_date == today 判断，会把昨天生成的供今天执行的策略误判为已完成
                from datetime import datetime as _dt, date as _date
                _today_start = _dt.combine(_date.today(), _dt.min.time())
                _next_day_records = _recover_db.query(AIStrategyDecision.decision_date).filter(
                    AIStrategyDecision.strategy_mode == "next_day",
                    AIStrategyDecision.source == "auto",
                    AIStrategyDecision.created_at >= _today_start,  # 今天生成的记录
                ).all()
                if _next_day_records:
                    _sched_last_run["review_strategy_time"] = _recover_today
                    logger.info(f"[启动恢复] review_strategy_time 当天已完成（生成了 {len(_next_day_records)} 条次日策略）")

                # ── 其他模式：decision_date == today 表示今天已执行过该模式的盘中策略───
                _today_modes = _recover_db.query(AIStrategyDecision.strategy_mode).filter(
                    AIStrategyDecision.decision_date == _recover_today,
                    AIStrategyDecision.source == "auto",
                    AIStrategyDecision.strategy_mode != "next_day",  # 排除 next_day（上面已单独处理）
                ).distinct().all()
                _mode_set = {row[0] for row in _today_modes}
                # midday_strategy_time 生成 midday 模式
                if "midday" in _mode_set:
                    _sched_last_run["midday_strategy_time"] = _recover_today
                    logger.info(f"[启动恢复] midday_strategy_time 当天已完成")
                # intraday_strategy_time_1/2 生成 intraday/intraday_afternoon 模式
                # 直接按 mode 恢复：intraday → time_1，intraday_afternoon → time_2
                if "intraday" in _mode_set:
                    _sched_last_run["intraday_strategy_time_1"] = _recover_today
                    logger.info(f"[启动恢复] intraday_strategy_time_1 当天已完成（mode=intraday）")
                if "intraday_afternoon" in _mode_set:
                    _sched_last_run["intraday_strategy_time_2"] = _recover_today
                    logger.info(f"[启动恢复] intraday_strategy_time_2 当天已完成（mode=intraday_afternoon）")
            except Exception as _e:
                logger.warning(f"[启动恢复] 模拟交易策略标记恢复失败: {_e}")

            # 自选股 AI 策略：循环内已有 DB 去重检查（WatchlistStrategyDecision 查询），
            # 重启后即使 _sched_last_run 丢失，DB 去重也会跳过已生成的策略，无需恢复标记
        finally:
            _recover_db.close()
    except Exception as e:
        logger.warning(f"[启动恢复] _sched_last_run 恢复失败（不阻塞调度）: {e}")

    # 资讯/研报预热：每 10 分钟一次，不限交易时间（akshare 同步调用放到线程池避免阻塞 event loop）
    _NEWS_PREHEAT_INTERVAL = 10 * 60  # 秒
    _last_preheat_ts = 0.0

    # 市场看板/龙虎榜预热：交易时间每 5 分钟一次，非交易时间不预热
    _MARKET_PREHEAT_INTERVAL = 5 * 60  # 秒

    # 交易日切换检测：每分钟检查一次，确保开盘后及时初始化
    _TRADING_DATE_CHECK_INTERVAL = 60  # 秒
    _last_trading_date_check_ts = 0.0
    _last_trading_date = None  # 记录上次处理的交易日

    # 工作日9:30判断是否为交易日（排除周末/节假日），用于提前确定是否休市
    _morning_check_done_today = False

    # 定时清理任务日期追踪
    _last_cleanup_date = None

    # _sched_last_run 上次跨日清理日期（避免长期运行后字典无限增长）
    _last_sched_cleanup_date = None

    # -- 交易系统任务标记 --
    global _last_price_update, _last_risk_check, _last_order_match
    global _last_t_trade, _last_strategy_exec, _strategy_exec_interval
    global _last_short_close_check
    global _last_strategy_regenerate_ts, _last_market_snapshot
    global _last_decision_alert_ts, _last_market_preheat_ts
    _intraday_monitor_last_ts = 0.0  # 盘中监控调用时间戳（基础间隔60秒）

    # 调度配置缓存（每5分钟刷新一次，避免频繁查库）
    _sched_config_cache = None
    _sched_config_ts = 0.0
    _SCHED_CONFIG_TTL = 300  # 5分钟

    while True:
      # 顶层异常保护：任一未捕获异常会导致整个调度循环终止，所有定时任务停摆。
      # 包一层 try/except 确保本轮异常不影响下一轮调度，并记录完整堆栈便于排查。
      try:
        now = datetime.now()
        current_time = now.time()

        import time as _time

        # 每日清理 _sched_last_run 旧日期条目，避免长期运行后字典无限增长
        # 自选股策略 key 形如 "watchlist_{uid}_{time_str}"，每天每个用户/时间点累积一条
        if _last_sched_cleanup_date != now.date():
            _last_sched_cleanup_date = now.date()
            _today_str_for_clean = now.strftime("%Y-%m-%d")
            _stale_keys = [k for k, v in _sched_last_run.items() if v != _today_str_for_clean]
            for _k in _stale_keys:
                _sched_last_run.pop(_k, None)
                _sched_retry_count.pop(_k, None)
            if _stale_keys:
                logger.info(f"跨日清理 _sched_last_run：移除 {len(_stale_keys)} 个旧条目")

        # 定时刷新调度配置，确保管理端修改后无需重启即可生效
        if _time.time() - _sched_config_ts >= _SCHED_CONFIG_TTL or _sched_config_cache is None:
            _sched_config_cache = _get_scheduler_config()
            _sched_config_ts = _time.time()
        sched_config = _sched_config_cache

        # ── 工作日 09:30 判断是否为交易日（排除周末/节假日，时间可配）──
        if not _morning_check_done_today and now.weekday() < 5:
            morning_check_time = _parse_hhmm(sched_config["trading_day_check_time"], 9, 30)
            if current_time >= morning_check_time:
                _morning_check_done_today = True
                is_trading = is_trading_day(now)
                logger.info(f"工作日{morning_check_time.strftime('%H:%M')}判断：{now.strftime('%Y-%m-%d')} {'是交易日' if is_trading else '不是交易日（节假日休市）'}")

        # 新交易日重置开盘检查标志（morning_check_time 提前 1 小时重置）
        morning_reset_time = _parse_hhmm(sched_config["trading_day_check_time"], 9, 30)
        if _last_trading_date is not None and current_time < dtime(
            max(0, (morning_reset_time.hour - 1) % 24), morning_reset_time.minute
        ):
            _morning_check_done_today = False

        # 每日重置清理任务日期追踪
        if _last_cleanup_date != now.date():
            _last_cleanup_date = now.date()

        # ── 交易日切换检测（每分钟检查一次）──
        if _time.time() - _last_trading_date_check_ts >= _TRADING_DATE_CHECK_INTERVAL:
            _last_trading_date_check_ts = _time.time()
            try:
                current_trading_date = get_last_trade_date()
                
                # 首次运行：记录当前交易日
                if _last_trading_date is None:
                    _last_trading_date = current_trading_date
                    logger.debug(f"初始化交易日: {_last_trading_date}")
                
                # 检测到交易日切换
                elif current_trading_date != _last_trading_date:
                    logger.info(f"检测到交易日切换: {_last_trading_date} -> {current_trading_date}")
                    _last_trading_date = current_trading_date

                    # 仅在交易时间执行开盘初始化（非交易时间不更新数据）
                    if is_trading_hours():
                        logger.info("交易时间内，执行开盘初始化...")
                        await asyncio.to_thread(_morning_initialization, current_trading_date)
            except Exception as e:
                logger.warning(f"交易日切换检测失败: {e}")

        # 每 10 分钟预热资讯和研报缓存（保证不打开资讯页也有最新数据，不限交易时间）
        if _time.time() - _last_preheat_ts >= _NEWS_PREHEAT_INTERVAL:
            _last_preheat_ts = _time.time()
            try:
                await asyncio.to_thread(_preheat_news_and_research)
                logger.info("定时预热：资讯/研报缓存已更新")
            except Exception as e:
                logger.warning(f"定时预热资讯/研报失败: {e}")

        # ============================================================
        # 区间触发任务（固定间隔，不受统一调度影响）
        # ============================================================

        # 市场看板/龙虎榜预热：交易时段每 5 分钟一次（超时 120 秒，防止计算卡死阻塞调度循环）
        if is_trading_hours():
            if _time.time() - _last_market_preheat_ts >= _MARKET_PREHEAT_INTERVAL:
                _last_market_preheat_ts = _time.time()
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(_preheat_market_and_dragon),
                        timeout=120,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"市场看板预热超时（120秒），跳过本轮，下一轮继续")
                except Exception as e:
                    logger.warning(f"定时预热市场/龙虎榜失败: {e}")
        else:
            _last_market_preheat_ts = 0.0

        # 更新策略执行间隔（分钟→秒），供 _intraday_monitor 使用
        _strategy_exec_interval = sched_config.get("strategy_exec_interval_min", 5) * 60

        # 盘中监控：交易时段每 60 秒一次（超时 120 秒后跳过，防止网络卡死阻塞调度循环）
        if is_trading_day(now) and is_trading_hours():
            _INTRADAY_BASE_INTERVAL = 60
            if _time.time() - _intraday_monitor_last_ts >= _INTRADAY_BASE_INTERVAL:
                _intraday_monitor_last_ts = _time.time()
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(_intraday_monitor, sched_config),
                        timeout=120,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"盘中监控超时（120秒），跳过本轮，下一轮继续")
                except Exception as e:
                    logger.warning(f"盘中监控任务失败: {e}")
        else:
            _intraday_monitor_last_ts = 0.0
            _last_price_update = 0.0
            _last_risk_check = 0.0
            _last_order_match = 0.0
            _last_t_trade = 0.0
            _last_strategy_exec = 0.0
            _last_short_close_check = 0.0
            _last_strategy_regenerate_ts = 0.0
            _last_market_snapshot = None

        # 决策算法预警：每 10 分钟一次（不受交易时间限制，超时 60 秒跳过）
        _DECISION_ALERT_INTERVAL = 600  # 10分钟
        if _time.time() - _last_decision_alert_ts >= _DECISION_ALERT_INTERVAL:
            _last_decision_alert_ts = _time.time()
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(_run_decision_alerts),
                    timeout=60,
                )
            except asyncio.TimeoutError:
                logger.warning(f"决策算法预警超时（60秒），跳过本轮")
            except Exception as e:
                logger.warning(f"决策算法预警任务失败: {e}")

        # ============================================================
        # 统一调度：所有定时任务通过注册表统一管理
        #   - 容错窗口：短任务 30 分钟，AI 类长任务 120 分钟（覆盖 LLM 重试+服务恢复）
        #   - 长耗时任务（LLM类）后台 fire-and-forget 执行，避免阻塞调度循环
        #   - 短任务同步 await 等待
        #   - 失败自动重试（_run_long_task 清除标记，下一轮重新匹配）
        #   - 成功自动去重（_match_scheduled_time 内部记录日期）
        #   - _exec_* 内部 DB 去重防止重复生成（completed 记录检查）
        # ============================================================
        for _task in _unified_tasks:
            _tk = _task["config_key"]
            _ttime = sched_config.get(_tk, "")
            if not _ttime:
                continue

            # 检查条件：交易日限制 / 启用开关
            if _task.get("trading_day") and not is_trading_day(now):
                continue
            _ek = _task.get("enabled_key")
            if _ek and not sched_config.get(_ek):
                continue

            # AI 类长任务使用 120 分钟容错窗口，普通任务保持 30 分钟
            _tolerance = 120 if _tk in _LONG_RUNNING_TASK_KEYS else 30
            if _match_scheduled_time(current_time, _ttime, _sched_last_run, _tk, _tolerance):
                # 长耗时任务：后台执行，不阻塞调度循环
                if _tk in _LONG_RUNNING_TASK_KEYS:
                    # 同类型任务已在执行中：跳过本次触发，不清除标记（避免重复触发）
                    _existing = _running_long_tasks.get(_tk)
                    if _existing is not None and not _existing.done():
                        continue

                    async def _run_long_task(tk=_tk, ttime=_ttime, executor=_task["executor"]):
                        """长耗时任务包装：容错窗口内最多重试 3 次，超限放弃当天

                        - 成功 → 清零重试计数（标记由 _match_scheduled_time 设为今天，不再触发）
                        - 失败/超时 → 递增计数：< 3 清除标记允许重试；>= 3 保留标记放弃当天
                        """
                        try:
                            _result = executor()
                            if asyncio.iscoroutine(_result) or asyncio.isfuture(_result):
                                # LLM 类任务加总超时 + 并发控制，防止 httpx/线程挂起卡死
                                if tk in _LONG_RUNNING_TASK_KEYS:
                                    async with _get_llm_semaphore():
                                        await asyncio.wait_for(_result, timeout=_LLM_TASK_TIMEOUT)
                                else:
                                    await _result
                            # 成功：清零重试计数
                            _sched_retry_count.pop(tk, None)
                            logger.info(f"统一调度任务(后台)完成: {tk} ({ttime})")
                        except asyncio.TimeoutError:
                            retries = _sched_retry_count.get(tk, 0) + 1
                            _sched_retry_count[tk] = retries
                            if retries >= _SCHED_MAX_RETRIES:
                                logger.warning(f"统一调度任务(后台)超时 [{tk}]: 超过{_LLM_TASK_TIMEOUT}秒，重试{retries}次已达上限，放弃当天")
                            else:
                                _sched_last_run.pop(tk, None)
                                logger.warning(f"统一调度任务(后台)超时 [{tk}]: 超过{_LLM_TASK_TIMEOUT}秒，第{retries}次失败，稍后重试")
                        except Exception as e:
                            retries = _sched_retry_count.get(tk, 0) + 1
                            _sched_retry_count[tk] = retries
                            if retries >= _SCHED_MAX_RETRIES:
                                logger.warning(f"统一调度任务(后台)失败 [{tk}]: {e}，重试{retries}次已达上限，放弃当天")
                            else:
                                _sched_last_run.pop(tk, None)
                                logger.warning(f"统一调度任务(后台)失败 [{tk}]: {e}，第{retries}次失败，稍后重试")
                        finally:
                            _running_long_tasks.pop(tk, None)

                    _running_long_tasks[_tk] = asyncio.create_task(_run_long_task())
                    logger.info(f"统一调度任务(后台)启动: {_tk} ({_ttime})")
                else:
                    # 短任务：同步等待
                    try:
                        _result = _task["executor"]()
                        if asyncio.iscoroutine(_result) or asyncio.isfuture(_result):
                            await _result
                        _sched_retry_count.pop(_tk, None)
                        logger.info(f"统一调度任务完成: {_tk} ({_ttime})")
                    except Exception as e:
                        retries = _sched_retry_count.get(_tk, 0) + 1
                        _sched_retry_count[_tk] = retries
                        if retries >= _SCHED_MAX_RETRIES:
                            logger.warning(f"统一调度任务失败 [{_tk}]: {e}，重试{retries}次已达上限，放弃当天")
                        else:
                            _sched_last_run.pop(_tk, None)
                            logger.warning(f"统一调度任务失败 [{_tk}]: {e}，第{retries}次失败，稍后重试")

        # ============================================================
        # 自选股AI策略（独立调度：每个用户/时间组合单独追踪）
        #   - 后台并行执行（asyncio.create_task），不阻塞调度循环
        #   - 同用户同模式互斥，避免并发重复生成
        #   - 内部 DB 去重（WatchlistStrategyDecision 查询）防漏执行补跑时重复
        # ============================================================
        if is_trading_day(now):
            from app.models.watchlist_strategy import WatchlistStrategyConfig, WatchlistStrategyDecision
            from app.core.database import SessionLocal as _SL
            _db = _SL()
            _pending_long_tasks = []  # 本次循环待启动的后台任务（避免在 for 循环中修改 _running_long_tasks）
            try:
                _admin_configs = _db.query(WatchlistStrategyConfig).filter(
                    WatchlistStrategyConfig.is_enabled == True
                ).all()
                _today_str = now.strftime("%Y-%m-%d")
                _cur_total = now.hour * 60 + now.minute
                for _cfg in _admin_configs:
                    _time_mode_map = {}
                    for _t in (_parse_json_list(_cfg.intraday_times) or ["10:25", "14:10"]):
                        _time_mode_map[_t] = "intraday"
                    for _t in (_parse_json_list(_cfg.midday_times) or ["12:30"]):
                        _time_mode_map[_t] = "midday"
                    for _t in (_parse_json_list(_cfg.closing_times) or ["16:00"]):
                        _time_mode_map[_t] = "closing"
                    for _time_str, _mode in _time_mode_map.items():
                        _key = f"watchlist_strategy_{_cfg.user_id}_{_time_str}"

                        # 解析目标时间
                        try:
                            _h, _m = map(int, _time_str.split(":"))
                            _target_total = _h * 60 + _m
                        except (ValueError, IndexError):
                            _target_total = 0

                        # 今天已执行过（内存追踪），跳过
                        if _sched_last_run.get(_key) == _today_str:
                            continue

                        # 未到目标时间，跳过
                        if _cur_total < _target_total:
                            continue

                        # 修复 Bug：调度器查询用 _mode，但生成器内部会把 "intraday" 映射为
                        # "morning"(<12:00) 或 "afternoon"(>=12:00) 后保存到 DB
                        # 因此 DB 去重时需要使用映射后的内部模式，否则 intraday 模式去重永远失效
                        _db_query_mode = _mode
                        if _mode == "intraday":
                            _db_query_mode = "morning" if _target_total < 12 * 60 else "afternoon"

                        # 已到目标时间，检查今天数据库是否已生成过该模式策略（防重复 + 漏执行补跑）
                        _existing = _db.query(WatchlistStrategyDecision).filter(
                            WatchlistStrategyDecision.user_id == _cfg.user_id,
                            WatchlistStrategyDecision.decision_date == _today_str,
                            WatchlistStrategyDecision.strategy_mode == _db_query_mode,
                        ).first()
                        if _existing:
                            # 今天已生成过，标记为已执行避免重复
                            _sched_last_run[_key] = _today_str
                            continue

                        # 同用户同模式已有后台任务在执行：跳过本次触发
                        # 使用映射后的内部模式作为 key（与 DB 存储一致），保证同用户同内部模式互斥
                        _wl_task_key = f"watchlist_{_cfg.user_id}_{_db_query_mode}"
                        _existing_task = _running_long_tasks.get(_wl_task_key)
                        if _existing_task is not None and not _existing_task.done():
                            logger.info(
                                f"自选股AI策略 用户{_cfg.user_id} 模式{_db_query_mode} "
                                f"已有任务在执行，跳过 {_time_str} 触发"
                            )
                            continue

                        # 漏执行超过 120 分钟（如整天宕机恢复后）跳过本次补跑：
                        # 此时交易时段已过或临近结束，生成策略已无实际意义，且 DB 去重已检查过
                        if _cur_total > _target_total + 120:
                            logger.info(
                                f"自选股AI策略漏执行超过 120 分钟（用户{_cfg.user_id}，模式{_db_query_mode}，"
                                f"原定{_time_str}），跳过本次补跑"
                            )
                            _sched_last_run[_key] = _today_str  # 标记为已处理避免下轮重试
                            continue

                        # 超过容错窗口（+30分钟）的漏执行：记录补跑日志并继续执行
                        if _cur_total > _target_total + 30:
                            logger.info(f"检测到漏执行，补跑自选股AI策略（用户{_cfg.user_id}，模式{_db_query_mode}，原定{_time_str}）")
                        else:
                            logger.info(f"开始生成自选股AI策略（用户{_cfg.user_id}，模式{_db_query_mode}，时间{_time_str}）")

                        # 标记为已执行（先标记避免循环重复触发；失败后清除）
                        _sched_last_run[_key] = _today_str

                        # 后台执行：每个用户/模式独立任务，互不阻塞
                        async def _run_wl_strategy(
                            task_key=_wl_task_key, sched_key=_key,
                            user_id=_cfg.user_id, mode=_mode, time_str=_time_str,
                        ):
                            """自选股策略后台任务：容错窗口内最多重试 {_SCHED_MAX_RETRIES} 次，超限放弃"""
                            _wl_db = _SL()
                            try:
                                from app.services.watchlist_strategy_generator import generate_watchlist_strategy_for_scheduler
                                async with _get_llm_semaphore():
                                    result = await asyncio.wait_for(
                                        asyncio.to_thread(
                                            generate_watchlist_strategy_for_scheduler, _wl_db, user_id, mode,
                                        ),
                                        timeout=_LLM_TASK_TIMEOUT,
                                    )
                                if result.get("success"):
                                    _sched_retry_count.pop(sched_key, None)
                                    logger.info(f"自选股AI策略生成完成（{mode}/{time_str}，用户{user_id}）")
                                else:
                                    retries = _sched_retry_count.get(sched_key, 0) + 1
                                    _sched_retry_count[sched_key] = retries
                                    if retries >= _SCHED_MAX_RETRIES:
                                        logger.warning(f"自选股AI策略生成失败（用户{user_id}，重试{retries}次已达上限）: {result.get('error')}")
                                    else:
                                        _sched_last_run.pop(sched_key, None)
                                        logger.warning(f"自选股AI策略生成失败（用户{user_id}，第{retries}次）: {result.get('error')}")
                            except asyncio.TimeoutError:
                                retries = _sched_retry_count.get(sched_key, 0) + 1
                                _sched_retry_count[sched_key] = retries
                                if retries >= _SCHED_MAX_RETRIES:
                                    logger.warning(f"自选股AI策略超时（用户{user_id}，模式{mode}，原定{time_str}，重试{retries}次已达上限）")
                                else:
                                    _sched_last_run.pop(sched_key, None)
                                    logger.warning(f"自选股AI策略超时（用户{user_id}，模式{mode}，原定{time_str}，第{retries}次失败）")
                            except Exception as e:
                                retries = _sched_retry_count.get(sched_key, 0) + 1
                                _sched_retry_count[sched_key] = retries
                                if retries >= _SCHED_MAX_RETRIES:
                                    logger.warning(f"自选股AI策略生成异常（用户{user_id}，重试{retries}次已达上限）: {e}")
                                else:
                                    _sched_last_run.pop(sched_key, None)
                                    logger.warning(f"自选股AI策略生成异常（用户{user_id}，第{retries}次）: {e}")
                            finally:
                                _wl_db.close()
                                _running_long_tasks.pop(task_key, None)

                        _pending_long_tasks.append((_wl_task_key, _run_wl_strategy()))
            except Exception as e:
                logger.warning(f"自选股AI策略任务执行失败: {e}")
                # 异常路径：显式关闭未调度的协程，避免 "coroutine was never awaited" 警告
                for _name, _coro in _pending_long_tasks:
                    try:
                        _coro.close()
                    except Exception:
                        pass
                _pending_long_tasks.clear()
            finally:
                # 修复 Bug：原代码用 try 而非 finally 关闭 _db，异常时连接泄漏
                try:
                    _db.close()
                except Exception:
                    pass

            # 启动本次循环的所有后台任务（在 db session 释放后启动）
            # 修复 Bug：原代码未按 _tk_name 去重，同用户同内部模式可能并发执行破坏互斥不变量
            _seen_keys = set()
            for _tk_name, _coro in _pending_long_tasks:
                if _tk_name in _seen_keys:
                    try:
                        _coro.close()
                    except Exception:
                        pass
                    continue
                _seen_keys.add(_tk_name)
                _running_long_tasks[_tk_name] = asyncio.create_task(_coro)

        # ============================================================
        # ML模型定时训练（智能选股技术评分，每周一次）
        # ============================================================
        ml_enabled = sched_config.get("ml_train_enabled", False)
        if ml_enabled and now.weekday() == sched_config.get("ml_train_day_of_week", 1):
            _ml_time = sched_config.get("ml_train_time", "20:00")
            _ml_key = "ml_model_training"
            if _match_scheduled_time(current_time, _ml_time, _sched_last_run, _ml_key):
                try:
                    from app.services.strategy_service import strategy_service
                    days = sched_config.get("ml_train_days", 250)
                    stocks = sched_config.get("ml_train_stocks", 100)
                    result = await asyncio.to_thread(strategy_service.train_ml_model, days=days, stocks=stocks, model="lightgbm")
                    if result.get("status") == "success":
                        _sched_retry_count.pop(_ml_key, None)
                        logger.info(f"ML模型定时训练完成: {result.get('message')}")
                    else:
                        retries = _sched_retry_count.get(_ml_key, 0) + 1
                        _sched_retry_count[_ml_key] = retries
                        if retries >= _SCHED_MAX_RETRIES:
                            logger.warning(f"ML模型定时训练失败（重试{retries}次已达上限）: {result.get('message')}")
                        else:
                            _sched_last_run.pop(_ml_key, None)
                            logger.warning(f"ML模型定时训练失败（第{retries}次）: {result.get('message')}")
                except Exception as e:
                    retries = _sched_retry_count.get(_ml_key, 0) + 1
                    _sched_retry_count[_ml_key] = retries
                    if retries >= _SCHED_MAX_RETRIES:
                        logger.error(f"ML模型定时训练异常（重试{retries}次已达上限）: {e}")
                    else:
                        _sched_last_run.pop(_ml_key, None)
                        logger.error(f"ML模型定时训练异常（第{retries}次）: {e}")

        # ============================================================
        # 计算 sleep 时间：60秒上限兜底，确保不会错过任何任务的10分钟窗口
        # ============================================================
        now_ts = _time.time()
        next_news = _last_preheat_ts + _NEWS_PREHEAT_INTERVAL
        next_market = _last_market_preheat_ts + _MARKET_PREHEAT_INTERVAL if is_trading_hours() else float('inf')
        next_trade = _last_trading_date_check_ts + _TRADING_DATE_CHECK_INTERVAL

        # 自选股策略：计算到最近目标时间的剩余秒数，提前唤醒（10分钟容错）
        next_watchlist = float('inf')
        if is_trading_day(now):
            try:
                from app.models.watchlist_strategy import WatchlistStrategyConfig as _WSC
                _wl_db = SessionLocal()
                _wl_cfgs = _wl_db.query(_WSC).filter(_WSC.is_enabled == True).all()
                _all_times = []
                for _cfg in _wl_cfgs:
                    for _t in (_parse_json_list(_cfg.intraday_times) or ["10:25", "14:10"]):
                        _all_times.append(_t)
                    for _t in (_parse_json_list(_cfg.midday_times) or ["12:30"]):
                        _all_times.append(_t)
                    for _t in (_parse_json_list(_cfg.closing_times) or ["16:00"]):
                        _all_times.append(_t)
                _wl_db.close()
                _cur_minutes = now.hour * 60 + now.minute
                _min_delta = float('inf')
                for _t in set(_all_times):
                    try:
                        _h, _m = map(int, _t.split(":"))
                        _target = _h * 60 + _m
                        _delta = _target - _cur_minutes
                        if 0 <= _delta <= 10:
                            _min_delta = 0
                            break
                        elif _delta > 0 and _delta < _min_delta:
                            _min_delta = _delta
                    except (ValueError, AttributeError):
                        pass
                if _min_delta <= 10:
                    next_watchlist = now_ts + 60
                elif _min_delta < float('inf'):
                    next_watchlist = now_ts + max(0, _min_delta * 60 - 30)
            except Exception:
                pass

        sleep_secs = max(0.0, min(
            next_news - now_ts,
            next_market - now_ts,
            next_trade - now_ts,
            next_watchlist - now_ts,
            60.0,
        ))
      except asyncio.CancelledError:
        logger.info("定时任务已停止")
        return
      except Exception as _sched_err:
        # 本轮异常不影响下一轮调度；sleep 兜底 60s 避免异常风暴
        logger.exception(f"调度循环本轮异常: {_sched_err}")
        sleep_secs = 60.0
      # sleep 移到 try 之外：本轮异常时仍按计算的间隔或兜底 60s 等待
      try:
        await asyncio.sleep(sleep_secs)
      except asyncio.CancelledError:
        logger.info("定时任务已停止")
        return


def _parse_json_list(text):
    """安全解析 JSON 列表字符串，失败返回 None"""
    if not text:
        return None
    try:
        v = json.loads(text)
        return v if isinstance(v, list) else None
    except Exception:
        return None


def _match_scheduled_time(current_time, scheduled_time: str, last_run_tracker: dict, tracker_key: str | None = None, tolerance_minutes: int = 30) -> bool:
    """判断当前时间是否匹配调度时间。

    使用日期追踪避免同一任务在同一天重复执行，
    容错窗口默认 +30 分钟（LLM 生成策略可能耗时较长，
    且统一调度循环可能被前序任务短暂阻塞，需要足够窗口兜底）。
    tracker_key 指定追踪字典中的键，默认为 scheduled_time 本身。

    修复 Bug：原代码固定 30 分钟容错窗口，AI 类任务失败重试时若超过窗口
    会导致当天永久漏触发。现在通过 tolerance_minutes 参数允许调用方
    指定更长的容错窗口（AI 类任务使用 120 分钟，覆盖 LLM 重试+服务恢复）。
    """
    from datetime import date as _date

    try:
        parts = scheduled_time.split(":")
        target_hour = int(parts[0])
        target_minute = int(parts[1])

        key = tracker_key if tracker_key is not None else scheduled_time
        last_run_date = last_run_tracker.get(key)
        today = _date.today().strftime("%Y-%m-%d")

        # 今天已执行过，跳过
        if last_run_date == today:
            return False

        # 匹配目标分钟，可配置容错窗口
        target_total = target_hour * 60 + target_minute
        current_total = current_time.hour * 60 + current_time.minute

        matched = (target_total <= current_total <= target_total + tolerance_minutes)

        if matched:
            last_run_tracker[key] = today

        return matched
    except (ValueError, IndexError):
        return False


# 追踪定时任务上次执行日期，防止错过精确分钟时遗漏
_sched_last_run = {}

# 后台执行中的长耗时任务（LLM 类）：key=config_key, value=asyncio.Task
# 防止同类型任务并发执行（如 LLM 调用未结束又触发一次）
_running_long_tasks: dict[str, "asyncio.Task"] = {}

# 调度任务重试计数器：key → int，记录当天失败次数
# 容错窗口内最多重试3次（首次+2次重试），超限则放弃当天任务
_sched_retry_count: dict[str, int] = {}
_SCHED_MAX_RETRIES = 3

# 长耗时任务集合（涉及 LLM 调用，可能 1-10 分钟）：后台执行 + LLM 信号量保护
_LONG_RUNNING_TASK_KEYS = frozenset({
    "pick_time",                    # AI 股票推荐 (LLM)
    "report_time",                  # AI 复盘报告 (LLM)
    "review_strategy_time",         # 收盘复盘+次日策略 (LLM)
    "midday_strategy_time",         # 午间策略 (LLM)
    "intraday_strategy_time_1",     # 盘中策略上午 (LLM)
    "intraday_strategy_time_2",     # 盘中策略下午 (LLM)
})

# LLM 调用总超时（秒）：必须大于 httpx read timeout（当前 540s），
# 确保 httpx 先超时让线程干净退出，asyncio.wait_for 再捕获
_LLM_TASK_TIMEOUT = 600

# LLM 并发信号量：延迟初始化，适配不同 event loop
_LLM_SEMAPHORE: Optional[asyncio.Semaphore] = None
_LLM_SEMAPHORE_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    """获取当前 event loop 绑定的 LLM 信号量

    不同 event loop（asyncio.run 创建的新 loop）不能共用同一信号量，
    检测到 loop 切换时重新创建。
    """
    global _LLM_SEMAPHORE, _LLM_SEMAPHORE_LOOP
    current_loop = asyncio.get_running_loop()
    if _LLM_SEMAPHORE is None or _LLM_SEMAPHORE_LOOP is not current_loop:
        _LLM_SEMAPHORE = asyncio.Semaphore(1)
        _LLM_SEMAPHORE_LOOP = current_loop
    return _LLM_SEMAPHORE


async def _run_llm_thread(func, timeout: int = _LLM_TASK_TIMEOUT, *args, **kwargs):
    """在独立线程中运行 LLM 任务，带超时保护

    若任务超时：
    1. asyncio.wait_for 抛出 TimeoutError，scheduler 清除标记允许重试
    2. 后台线程继续运行，httpx read timeout（300s）最终会让它干净退出
    3. DB session 在 func 的 finally 中关闭（httpx 超时后执行）
    """
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(None, lambda: func(*args, **kwargs))
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"LLM 任务超时（>{timeout}秒）: {func.__name__}")


# ============================================================
# 统一调度：异步执行器包装函数
# ============================================================

async def _exec_closing_cache() -> None:
    """收盘缓存更新 + 当日PnL记录（各步骤独立错误处理）"""
    try:
        await asyncio.to_thread(_preheat_market_and_dragon)
        logger.info("收盘缓存更新完成：智能选股/龙虎榜数据已保存")
    except Exception as e:
        logger.warning(f"收盘缓存更新[市场/龙虎榜]失败: {e}")

    try:
        await asyncio.to_thread(_preheat_sector_analysis)
        logger.info("收盘缓存更新完成：板块分析数据已保存")
    except Exception as e:
        logger.warning(f"收盘缓存更新[板块分析]失败: {e}")

    trade_date = datetime.now().strftime("%Y-%m-%d")
    try:
        await asyncio.to_thread(_record_daily_pnl, trade_date)
        logger.info(f"收盘后当日盈亏记录完成 ({trade_date})")
    except Exception as e:
        logger.warning(f"收盘后PnL记录失败: {e}")


async def _exec_stock_pick() -> None:
    """AI股票推荐生成

    重试由调度层统一管理（_sched_retry_count + _SCHED_MAX_RETRIES）。
    本函数只做一次尝试：成功返回 / 失败抛异常。
    DB 去重防止重复生成（completed 记录检查）。
    """
    from app.core.database import SessionLocal
    from app.models.ai_stock_pick import AIStockPick

    pick_date_str = datetime.now().strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        existing = (db.query(AIStockPick)
                    .filter(AIStockPick.pick_date == pick_date_str,
                           AIStockPick.status == "completed")
                    .first())
        if existing:
            logger.info(f"跳过股票推荐：{pick_date_str} 已存在 completed 记录")
            return

        await ai_stock_pick_service.generate_picks(db, pick_date_str)
        logger.info(f"定时任务：股票推荐生成成功（{pick_date_str}）")
    finally:
        db.close()


async def _exec_daily_report() -> None:
    """AI复盘报告生成

    重试由调度层统一管理。本函数只做一次尝试：成功返回 / 失败抛异常。
    """
    from app.core.database import SessionLocal
    from app.models.daily_report import DailyReport

    report_date_str = datetime.now().strftime("%Y-%m-%d")
    db = SessionLocal()
    try:
        existing = (db.query(DailyReport)
                    .filter(DailyReport.report_date == report_date_str,
                           DailyReport.status == "completed")
                    .first())
        if existing:
            logger.info(f"跳过复盘报告：{report_date_str} 已存在 completed 记录")
            return

        await daily_report_service.generate_report(db, report_date_str)
        logger.info(f"定时任务：复盘报告生成成功（{report_date_str}）")
    finally:
        db.close()


async def _exec_cleanup_reports() -> None:
    """清理过期报告和股票推荐 + 清理卡在 generating 状态的脏数据"""
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        deleted = daily_report_service.cleanup_old_reports(db, days=30)
        if deleted > 0:
            logger.info(f"定时清理：已删除 {deleted} 条过期报告")
        deleted_picks = ai_stock_pick_service.cleanup_old_picks(db, days=30)
        if deleted_picks > 0:
            logger.info(f"定时清理：已删除 {deleted_picks} 条过期股票推荐")
        # 清理卡在 generating 状态超过 30 分钟的脏数据（生成进程崩溃后留下的）
        stale_reports = daily_report_service.cleanup_stale_generating(db, max_minutes=30)
        if stale_reports > 0:
            logger.warning(f"定时清理：已标记 {stale_reports} 条卡住的复盘报告为 failed")
        stale_picks = ai_stock_pick_service.cleanup_stale_generating(db, max_minutes=30)
        if stale_picks > 0:
            logger.warning(f"定时清理：已标记 {stale_picks} 条卡住的股票推荐为 failed")
    finally:
        db.close()


async def _exec_cleanup_chat() -> None:
    """清理过期对话、新闻文件、mx缓存、日志"""
    try:
        from app.api.chat_history import cleanup_old_data
        from app.core.database import SessionLocal
        db = SessionLocal()
        deleted = cleanup_old_data(db, days=30)
        if deleted > 0:
            logger.info(f"定时清理：已删除 {deleted} 条过期对话会话")
        db.close()
    except Exception as e:
        logger.warning(f"定时清理对话记录失败: {e}")

    try:
        deleted_files = _cleanup_old_news_files(days=7)
        if deleted_files > 0:
            logger.info(f"定时清理：已删除 {deleted_files} 个过期新闻文件")
    except Exception as e:
        logger.warning(f"定时清理新闻文件失败: {e}")

    try:
        from app.core.logging_config import cleanup_old_logs
        deleted_logs = cleanup_old_logs(days=7)
        if deleted_logs > 0:
            logger.info(f"定时清理：已删除 {deleted_logs} 个过期日志备份")
    except Exception as e:
        logger.warning(f"定时清理日志文件失败: {e}")

    try:
        from app.core.cache import _backend
        _backend._fallback._cleanup_expired()
        logger.debug("SQLite 共享缓存过期条目已清理")
    except Exception as e:
        logger.warning(f"清理 SQLite 缓存失败: {e}")


async def _exec_archive_trades() -> None:
    """P2-9：历史交易记录归档

    策略：
    - 90 天前的 SimTrade 直接删除（已聚合到 SimDailyPnl / SimStrategyStats / SimFailurePattern）
    - 180 天前的 AIStrategyDecision 删除（保留 strategy_summary 字段聚合到 SimDailyReview）
    - 90 天前的 SimTTrade 删除（已聚合到做T统计）
    - 30 天前的已撤单/已过期 SimOrder 删除
    每日凌晨执行一次，避免长期运行后查询变慢。
    """
    from app.core.database import SessionLocal
    from app.models.sim_trading import SimTrade, AIStrategyDecision, SimTTrade, SimOrder
    from datetime import date as _date, timedelta as _timedelta, datetime as _dt

    db = SessionLocal()
    try:
        cutoff_90 = (_date.today() - _timedelta(days=90)).strftime("%Y-%m-%d")
        cutoff_180 = (_date.today() - _timedelta(days=180)).strftime("%Y-%m-%d")
        cutoff_30_dt = _dt.combine(_date.today() - _timedelta(days=30), _dt.min.time())

        # 1. 删除 90 天前的交易记录
        deleted_trades = db.query(SimTrade).filter(
            SimTrade.trade_date < cutoff_90
        ).delete(synchronize_session=False)

        # 2. 删除 180 天前的 AI 策略决策
        deleted_decisions = db.query(AIStrategyDecision).filter(
            AIStrategyDecision.decision_date < cutoff_180
        ).delete(synchronize_session=False)

        # 3. 删除 90 天前的做T记录
        deleted_t_trades = db.query(SimTTrade).filter(
            SimTTrade.buy_date < cutoff_90
        ).delete(synchronize_session=False)

        # 4. 删除 30 天前的已撤单/已过期委托
        deleted_orders = db.query(SimOrder).filter(
            SimOrder.created_at < cutoff_30_dt,
            SimOrder.status.in_(["cancelled", "expired", "rejected"]),
        ).delete(synchronize_session=False)

        db.commit()

        if deleted_trades or deleted_decisions or deleted_t_trades or deleted_orders:
            logger.info(
                f"历史归档: 交易记录-{deleted_trades}条(>90天), "
                f"AI决策-{deleted_decisions}条(>180天), "
                f"做T记录-{deleted_t_trades}条(>90天), "
                f"过期委托-{deleted_orders}条(>30天)"
            )
    except Exception as e:
        db.rollback()
        logger.error(f"历史归档失败: {e}")
    finally:
        db.close()


async def _exec_review_strategy() -> None:
    """收盘复盘+次日策略合并生成"""
    trade_date = datetime.now().strftime("%Y-%m-%d")
    await asyncio.to_thread(_generate_review_and_strategy, trade_date)


async def _exec_market_flow_refresh() -> None:
    """盘后刷新主力资金流向，用收盘后的完整数据覆盖盘中实时值。

    东财大盘资金流接口盘中给出实时值，收盘后给出当日最终值；
    盘后强制刷新一次可把结果写入24小时缓存，避免次日仍展示盘中数据。
    """
    try:
        from app.services.market_service import MarketService
        m = MarketService()
        # force_refresh=True 跳过 stale 缓存拦截，重新拉取并写入 24h 缓存
        result = await asyncio.to_thread(m.get_market_sentiment, None, True, False)
        mf = result.get('money_flow', {}) if isinstance(result, dict) else {}
        net = mf.get('net_inflow_billion', 0)
        source = mf.get('source', '?')
        logger.info(f"盘后资金流刷新完成: 主力净流入={net}亿, source={source}")
    except Exception as e:
        logger.warning(f"盘后资金流刷新失败: {e}")


# ============================================================
# 统一任务注册表：所有定时任务集中管理
#   config_key: sched_config 中的时间配置键（时间格式 HH:MM）
#   executor: async function，无参数，内部自行管理 db session
#   trading_day: 是否仅交易日执行
#   enabled_key: 可选，sched_config 中控制启用的布尔键
# ============================================================
_unified_tasks = [
    {"config_key": "t1_unlock_morning_time", "executor": lambda: asyncio.to_thread(_unlock_t1_positions, False), "trading_day": True},
    {"config_key": "t1_unlock_afternoon_time", "executor": lambda: asyncio.to_thread(_unlock_t1_positions, True), "trading_day": True},
    {"config_key": "closing_cache_time", "executor": _exec_closing_cache, "trading_day": True},
    # 盘后大盘资金流刷新（一次即可，写入24h缓存）
    {"config_key": "mx_flow_refresh_time_1", "executor": _exec_market_flow_refresh, "trading_day": True},
    # mx_flow_refresh_time_2 已禁用：和 _1 调用同一函数写同一缓存，重复无意义
    {"config_key": "order_cleanup_time", "executor": lambda: asyncio.to_thread(_cleanup_orders_job), "trading_day": True},
    {"config_key": "midday_strategy_time", "executor": lambda: asyncio.to_thread(_generate_midday_strategy), "trading_day": True},
    {"config_key": "intraday_strategy_time_1", "executor": lambda: asyncio.to_thread(_generate_intraday_strategy, "", "intraday_strategy_time_1", "intraday"), "trading_day": True},
    {"config_key": "intraday_strategy_time_2", "executor": lambda: asyncio.to_thread(_generate_intraday_strategy, "", "intraday_strategy_time_2", "intraday_afternoon"), "trading_day": True},
    {"config_key": "review_strategy_time", "executor": _exec_review_strategy, "trading_day": True},
    {"config_key": "pick_time", "executor": _exec_stock_pick, "trading_day": True, "enabled_key": "pick_enabled"},
    {"config_key": "report_time", "executor": _exec_daily_report, "trading_day": True, "enabled_key": "report_enabled"},
    {"config_key": "cleanup_report_time", "executor": _exec_cleanup_reports, "trading_day": False},
    {"config_key": "cleanup_conversation_time", "executor": _exec_cleanup_chat, "trading_day": False},
    {"config_key": "archive_trades_time", "executor": _exec_archive_trades, "trading_day": False},
]


def _parse_hhmm(time_str: str, default_h: int = 0, default_m: int = 0):
    """解析 "HH:MM" 字符串为 dtime 对象（容错：解析失败返回默认）"""
    from datetime import time as _dtime
    try:
        parts = (time_str or "").split(":")
        return _dtime(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError, AttributeError):
        return _dtime(default_h, default_m)


def _get_scheduler_config() -> dict:
    """从数据库获取调度配置，异常时返回默认值"""
    from app.core.database import SessionLocal
    from app.models.scheduler_config import SchedulerConfig

    db = SessionLocal()
    try:
        config = db.query(SchedulerConfig).first()
        if not config:
            return _default_scheduler_config()
        return {
            "report_enabled": config.report_enabled,
            "report_time": config.report_time or "16:30",
            "pick_enabled": config.pick_enabled,
            "pick_time": config.pick_time or "15:20",
            # 模拟交易 T+1 解锁
            "t1_unlock_morning_time": config.t1_unlock_morning_time or "09:25",
            "t1_unlock_afternoon_time": config.t1_unlock_afternoon_time or "13:00",
            # 交易日判断
            "trading_day_check_time": config.trading_day_check_time or "09:30",
            # 收盘缓存
            "closing_cache_time": config.closing_cache_time or "15:02",
            # 盘后大盘资金流刷新（只保留一次）
            "mx_flow_refresh_time_1": config.mx_flow_refresh_time_1 or "15:05",
            "mx_flow_refresh_time_2": config.mx_flow_refresh_time_2 or "15:30",
            # 盘中监控间隔
            "intraday_monitor_interval_min": config.intraday_monitor_interval_min or 5,
            # 策略执行间隔（分钟）
            "strategy_exec_interval_min": config.strategy_exec_interval_min or 5,
            # 收盘后委托清理时间
            "order_cleanup_time": "15:30",
            # 收盘复盘+次日策略合并时间
            "review_strategy_time": config.review_strategy_time or "15:08",
            # 午间策略调整时间
            "midday_strategy_time": config.midday_strategy_time or "11:30",
            # 盘中策略生成时间
            "intraday_strategy_time_1": config.intraday_strategy_time_1 or "10:30",
            "intraday_strategy_time_2": config.intraday_strategy_time_2 or "13:30",
            # 凌晨清理
            "cleanup_report_time": config.cleanup_report_time or "02:00",
            "cleanup_conversation_time": config.cleanup_conversation_time or "03:00",
            # P2-9 历史归档
            "archive_trades_time": getattr(config, "archive_trades_time", None) or "03:30",
            # 收盘前自动平短仓
            "auto_close_short_enabled": getattr(config, "auto_close_short_enabled", True),
            "auto_close_short_time": getattr(config, "auto_close_short_time", None) or "14:50",
            # ML 模型定时训练（修复 Bug：原代码遗漏这 4 个字段，前端配置后调度器读不到）
            "ml_train_enabled": getattr(config, "ml_train_enabled", False),
            "ml_train_day_of_week": getattr(config, "ml_train_day_of_week", 1),
            "ml_train_time": getattr(config, "ml_train_time", None) or "20:00",
            "ml_train_days": getattr(config, "ml_train_days", 250),
            # ML模型V2定时训练配置（ML选股V2）
            "ml_v2_train_enabled": getattr(config, "ml_v2_train_enabled", False),
            "ml_v2_train_day_of_week": getattr(config, "ml_v2_train_day_of_week", 2),
            "ml_v2_train_time": getattr(config, "ml_v2_train_time", None) or "21:00",
            "ml_v2_train_days": getattr(config, "ml_v2_train_days", 500),
            "ml_v2_train_stocks": getattr(config, "ml_v2_train_stocks", 100),
        }
    except Exception as e:
        logger.warning(f"读取调度配置失败，使用默认值: {e}")
        return _default_scheduler_config()
    finally:
        db.close()


def _default_scheduler_config() -> dict:
    """返回默认调度配置"""
    return {
        "report_enabled": True,
        "report_time": "16:30",
        "pick_enabled": True,
        "pick_time": "15:20",
        "t1_unlock_morning_time": "09:25",
        "t1_unlock_afternoon_time": "13:00",
        "trading_day_check_time": "09:30",
        "closing_cache_time": "15:02",
        "mx_flow_refresh_time_1": "15:05",
        "mx_flow_refresh_time_2": "15:30",
        "intraday_monitor_interval_min": 5,
        "strategy_exec_interval_min": 5,
        "order_cleanup_time": "15:30",
        "review_strategy_time": "15:08",
        "midday_strategy_time": "11:30",
        "intraday_strategy_time_1": "10:30",
        "intraday_strategy_time_2": "13:30",
        "cleanup_report_time": "02:00",
        "cleanup_conversation_time": "03:00",
        "archive_trades_time": "03:30",
        # 收盘前自动平短仓配置
        "auto_close_short_enabled": True,
        "auto_close_short_time": "14:50",
        # ML模型定时训练配置（默认关闭，管理员可开启）
        "ml_train_enabled": False,
        "ml_train_day_of_week": 1,  # 周一
        "ml_train_time": "20:00",   # 晚上8点
        "ml_train_days": 250,       # 约1年交易日
        "ml_train_stocks": 100,     # 股票数量
    }


def _cleanup_old_news_files(days: int = 30) -> int:
    """清理 news_data 目录下超过指定天数的 news_YYYY-MM-DD.json 文件

    Returns: 删除的文件数
    """
    from datetime import datetime, timedelta

    # nlp.py 中定义的目录路径（项目根/news_data）
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_root = os.path.dirname(backend_dir)
    news_data_dir = os.path.join(project_root, "news_data")
    if not os.path.isdir(news_data_dir):
        return 0

    cutoff = datetime.now() - timedelta(days=days)
    deleted = 0
    for name in os.listdir(news_data_dir):
        # 仅匹配 news_YYYY-MM-DD.json
        if not (name.startswith("news_") and name.endswith(".json")):
            continue
        date_part = name[5:-5]  # 去掉 "news_" 和 ".json"
        try:
            file_date = datetime.strptime(date_part, "%Y-%m-%d")
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                os.remove(os.path.join(news_data_dir, name))
                deleted += 1
            except OSError as e:
                logger.warning(f"删除新闻文件失败 {name}: {e}")
    return deleted


def _morning_initialization(trading_date: str) -> None:
    """开盘初始化：清除旧缓存，预热新交易日数据
    
    仅在交易日9:00后首次检测到交易日切换时执行，确保：
    1. 清除所有后端缓存
    2. 重新预热市场看板和龙虎榜
    3. 记录初始化日志
    
    非交易日不执行此函数。
    """
    from app.core.trading_calendar import is_trading_day
    from datetime import datetime
    
    now = datetime.now()
    
    # 非交易日不执行初始化
    if not is_trading_day(now):
        logger.info(f"非交易日，跳过开盘初始化: {now.strftime('%Y-%m-%d')}")
        return
    
    logger.info(f"=== 开盘初始化开始: {trading_date} ===")
    
    # 1. 清除策略服务缓存
    try:
        from app.services.strategy_service import StrategyService
        s = StrategyService()
        s.clear_dragon_cache()
        logger.info("策略服务缓存已清除")
    except Exception as e:
        logger.warning(f"清除策略服务缓存失败: {e}")
    
    # 2. 预热市场数据
    try:
        from app.services.market_service import MarketService
        m = MarketService()
        m.get_market_sentiment(force_refresh=True)
        m.get_sectors(sector_type='industry', top=30, force_refresh=True)
        m.get_sectors(sector_type='concept', top=30, force_refresh=True)
        m.get_hot_sectors(top=10, force_refresh=True)
        m.get_rotation_signals(force_refresh=True)
        logger.info("市场看板预热完成")
    except Exception as e:
        logger.warning(f"市场看板预热失败: {e}")
    
    # 3. 预热龙虎榜
    try:
        from app.services.strategy_service import StrategyService
        s = StrategyService()
        s.get_dragon_list_today(force_refresh=True)
        s.get_dragon_capital_flow(force_refresh=True)
        s.get_dragon_seat_detail(force_refresh=True)
        s.get_dragon_sector_analysis(force_refresh=True)
        s.get_dragon_next_day_performance(force_refresh=True)
        logger.info("龙虎榜预热完成")
    except Exception as e:
        logger.warning(f"龙虎榜预热失败: {e}")
    
    # 4. 预热智能选股策略
    try:
        _preheat_market_and_dragon()
        logger.info("智能选股策略预热完成")
    except Exception as e:
        logger.warning(f"智能选股策略预热失败: {e}")

    # 5. 批量计算持仓 ATR（用于动态止损）
    try:
        _update_position_atr_batch()
        logger.info("持仓ATR计算完成")
    except Exception as e:
        logger.warning(f"持仓ATR计算失败: {e}")

    logger.info(f"=== 开盘初始化完成: {trading_date} ===")


def _update_position_atr_batch() -> None:
    """批量计算所有持仓的 ATR(14) 值，用于动态止损

    ATR = 14日 True Range 均值
    True Range = max(当日最高-最低, |当日最高-昨收|, |当日最低-昨收|)
    """
    from app.core.database import SessionLocal
    from app.models.sim_trading import SimAccount, SimPosition
    from app.core.pytdx_source import pytdx_data

    db = SessionLocal()
    try:
        accounts = db.query(SimAccount).all()
        for account in accounts:
            positions = db.query(SimPosition).filter(
                SimPosition.account_id == account.id
            ).all()
            for pos in positions:
                try:
                    klines = pytdx_data.get_kline(pos.stock_code, period=6, count=20)
                    if klines and len(klines) >= 14:
                        trs = []
                        for i in range(1, len(klines)):
                            k, k_prev = klines[i], klines[i - 1]
                            tr = max(
                                k["high"] - k["low"],
                                abs(k["high"] - k_prev["close"]),
                                abs(k["low"] - k_prev["close"]),
                            )
                            trs.append(tr)
                        pos.atr_value = round(sum(trs[-14:]) / min(14, len(trs)), 4)
                except Exception as e:
                    logger.debug(f"ATR计算失败 {pos.stock_code}: {e}")
            db.commit()
            logger.info(f"ATR批量计算完成: 账户{account.id} {len(positions)}个持仓")
    except Exception as e:
        logger.warning(f"ATR批量计算异常: {e}")
        db.rollback()
    finally:
        db.close()


def _intraday_monitor(sched_config: dict = None) -> None:
    """盘中监控 - 各子任务独立频率、独立 DB 会话、异常隔离

    任务频率：
    1. 价格更新：每60秒（让盈亏实时反映）
    2. 风控检查：每120秒（止损止盈 + 市价卖出）
    3. 做T检测：每600秒（日内回转交易，频率不宜过高）
    4. 策略执行：每N分钟（可配置，默认5分钟，自动执行 pending 策略）

    每个任务使用独立的 DB 会话，避免一个任务的脏状态影响其他任务。
    """
    global _last_price_update, _last_risk_check, _last_order_match
    global _last_t_trade, _last_strategy_exec, _strategy_exec_interval
    global _last_short_close_check
    global _last_strategy_regenerate_ts, _last_market_snapshot

    from app.services.risk_manager import RiskManager
    from app.services.t_trade_service import TTradeService
    from app.services.trade_engine import TradeEngine
    from app.models.sim_trading import AIStrategyDecision, SimAccount, SimPosition
    from app.services.ai_strategy_generator import AIStrategyGenerator
    from app.core.trading_calendar import is_trading_hours
    from app.core.database import SessionLocal
    from datetime import date as _date, datetime as _datetime
    import time as _time
    import threading as _threading

    PRICE_INTERVAL = 60     # 价格更新：1分钟
    RISK_INTERVAL = 120     # 风控检查：2分钟（快速下跌需及时响应）
    T_TRADE_INTERVAL = 600  # 做T检测：10分钟

    now_ts = _time.time()

    # 获取账户列表（独立会话，用完即关）
    db = SessionLocal()
    try:
        accounts = db.query(SimAccount).all()
        account_ids = [acc.id for acc in accounts]
    finally:
        db.close()

    if not account_ids:
        return

    today_str = _date.today().strftime("%Y-%m-%d")

    # ── 1. 价格更新（60秒）──
    if now_ts - _last_price_update >= PRICE_INTERVAL:
        _last_price_update = now_ts
        for acc_id in account_ids:
            db = SessionLocal()
            try:
                positions = db.query(SimPosition).filter(
                    SimPosition.account_id == acc_id
                ).all()
                if positions:
                    codes = [p.stock_code for p in positions]
                    price_dict = TradeEngine.fetch_realtime_quotes(codes)
                    if price_dict:
                        TradeEngine.update_position_prices(db, acc_id, price_dict)
            except Exception as e:
                logger.error(f"盘中监控-持仓价格更新失败 (account={acc_id}): {e}")
            finally:
                db.close()

    # ── 2. 委托撮合（60秒）──
    if now_ts - _last_order_match >= PRICE_INTERVAL:
        _last_order_match = now_ts
        for acc_id in account_ids:
            db = SessionLocal()
            try:
                from app.services.order_service import OrderService
                result = OrderService.match_orders(db, acc_id)
                matched = result.get("matched_count", 0)
                total = result.get("total_pending", 0)
                if matched > 0:
                    logger.info(f"委托撮合: account={acc_id}, 成交{matched}笔 (共{total}笔待成交)")
                elif total > 0 and result.get("skipped"):
                    logger.info(f"委托撮合跳过: account={acc_id}, {result['skipped']} (待成交{total}笔)")
                elif total > 0:
                    logger.debug(f"委托撮合: account={acc_id}, 待成交{total}笔暂无可成交（委托价未触达现价）")
                # 过期委托单处理：释放冻结资金
                expired = OrderService.expire_orders(db, acc_id)
                if expired.get("expired_count", 0) > 0:
                    logger.info(f"过期委托处理: account={acc_id}, 过期{expired['expired_count']}笔")
            except Exception as e:
                logger.error(f"盘中监控-委托撮合失败 (account={acc_id}): {e}")
            finally:
                db.close()

    # ── 3. 风控检查（120秒）──
    if now_ts - _last_risk_check >= RISK_INTERVAL:
        _last_risk_check = now_ts
        for acc_id in account_ids:
            db = SessionLocal()
            try:
                RiskManager.execute_risk_sells(db, acc_id)
            except Exception as e:
                logger.error(f"盘中监控-止损止盈检查失败 (account={acc_id}): {e}")
            finally:
                db.close()

    # ── 3.5 收盘前自动平短仓（每天配置时间执行一次，默认14:50）──
    # 短线持仓不应隔夜，自动清仓 position_type='short' 的持仓
    # 中长线持仓不动，避免隔夜短线风险
    # 优化：亏损短线强制清仓，盈利短线可保留至次日（AI策略决定）
    # 读取 SchedulerConfig 决定是否启用和具体时间
    current_hhmm = _datetime.now().strftime("%H:%M")
    if now_ts - _last_short_close_check > 60:
        # 仅在分钟匹配时查配置，避免每分钟都查表
        try:
            _cfg_db = SessionLocal()
            from app.models.scheduler_config import SchedulerConfig as _SC
            _sc = _cfg_db.query(_SC).first()
            _close_enabled = _sc.auto_close_short_enabled if _sc and hasattr(_sc, 'auto_close_short_enabled') else True
            _close_time = _sc.auto_close_short_time if _sc and hasattr(_sc, 'auto_close_short_time') else "14:50"
            _cfg_db.close()
        except Exception as _e:
            logger.warning(f"读取平短仓配置失败，使用默认值: {_e}")
            _close_enabled = True
            _close_time = "14:50"

        if _close_enabled and current_hhmm == _close_time:
            _last_short_close_check = now_ts
            from app.services.order_service import OrderService
            from app.core.data_sources import TencentSource
            for acc_id in account_ids:
                db = SessionLocal()
                try:
                    # 仅查询短线持仓
                    short_positions = db.query(SimPosition).filter(
                        SimPosition.account_id == acc_id,
                        SimPosition.position_type == "short",
                        SimPosition.available_quantity > 0,
                    ).all()
                    if not short_positions:
                        continue
                    # 获取实时价格（含涨跌幅、涨停价、跌停价）
                    codes = [p.stock_code for p in short_positions]
                    quotes = {}
                    try:
                        quotes = TencentSource.get_quotes(codes)
                    except Exception as e:
                        logger.warning(f"平短仓获取行情失败: {e}")
                    # 跳过今日买入的（T+1冻结）
                    today_str_local = _date.today().strftime("%Y-%m-%d")
                    closed_count = 0
                    skipped_log = []
                    for pos in short_positions:
                        if pos.buy_date == today_str_local:
                            skipped_log.append(f"{pos.stock_code}({pos.stock_name}) T+1冻结")
                            continue
                        q = quotes.get(pos.stock_code, {})
                        cur_price = q.get("price", 0) if q else 0
                        if cur_price <= 0:
                            cur_price = pos.current_price or 0
                        if cur_price <= 0:
                            skipped_log.append(f"{pos.stock_code}({pos.stock_name}) 无行情")
                            continue
                        # 跌停/停牌检测：成交额为0视为停牌，跳过
                        amount_wan = q.get("amount_wan", 0) if q else 0
                        if amount_wan <= 0:
                            skipped_log.append(f"{pos.stock_code}({pos.stock_name}) 停牌/无成交")
                            continue
                        # 盈利判断：盈利短线可保留，仅强制清亏损短线
                        profit_ratio = (cur_price / pos.cost_price - 1) * 100 if pos.cost_price > 0 else 0
                        if profit_ratio > 0:
                            skipped_log.append(f"{pos.stock_code}({pos.stock_name}) 盈利{profit_ratio:.1f}%保留")
                            continue
                        result = OrderService.execute_market_order(
                            db=db,
                            account_id=acc_id,
                            stock_code=pos.stock_code,
                            stock_name=pos.stock_name,
                            order_type="sell",
                            quantity=pos.available_quantity,
                            price=cur_price,
                            strategy_name="auto_close_short",
                            strategy_reason=f"{_close_time}自动平短仓(亏损{profit_ratio:.1f}%，隔夜风险)",
                            order_source="auto_close_short",
                            auto_commit=False,
                        )
                        if result.get("success"):
                            closed_count += 1
                        else:
                            skipped_log.append(f"{pos.stock_code}({pos.stock_name}) 卖出失败: {result.get('error', '')}")
                    if closed_count > 0:
                        db.commit()
                        logger.info(f"{_close_time}自动平短仓: account={acc_id}, 清仓{closed_count}只短线持仓")
                    else:
                        db.rollback()
                    if skipped_log:
                        logger.info(f"{_close_time}平短仓跳过: account={acc_id}, {skipped_log}")
                except Exception as e:
                    logger.error(f"自动平短仓失败 (account={acc_id}): {e}")
                    try:
                        db.rollback()
                    except Exception:
                        pass
                finally:
                    db.close()

    # ── 3. 做T检测（600秒）──
    # 做T最佳时段：10:00-11:15（早盘波动大）和 13:15-14:30（午盘）
    if now_ts - _last_t_trade >= T_TRADE_INTERVAL:
        _last_t_trade = now_ts
        current_hhmm = _datetime.now().strftime("%H:%M")
        in_t_window = ("10:00" <= current_hhmm <= "11:15") or ("13:15" <= current_hhmm <= "14:30")
        if in_t_window:
            for acc_id in account_ids:
                db = SessionLocal()
                try:
                    TTradeService.detect_opportunities(db, acc_id)
                except Exception as e:
                    logger.error(f"盘中监控-做T机会检测失败 (account={acc_id}): {e}")
                finally:
                    db.close()

    # ── 3.7 盘中剧变纠偏：市场突变或持仓接近止损时自动重生成策略 ──
    # 触发条件（任一）：
    #   1. 主要指数当日涨跌幅突变（跌幅>1.5% 或 涨幅>2%）
    #   2. 账户当日浮亏比例接近止损线（>止损阈值的 80%）
    #   3. 账户当日盈亏在 30 分钟内急剧恶化（恶化幅度 > 2%）
    # 防抖：距上次重生成 > 30 分钟才允许再次触发
    REGENERATE_COOLDOWN = 1800  # 30 分钟
    if now_ts - _last_strategy_regenerate_ts >= REGENERATE_COOLDOWN:
        try:
            from app.services.market_service import MarketService
            ms = MarketService()
            sentiment = ms.get_market_sentiment(include_flow=False)
            indices = sentiment.get("indices", {}) if sentiment else {}

            # 提取主要指数当日涨跌幅
            sh_change = 0.0
            sz_change = 0.0
            cyb_change = 0.0
            for idx_code, idx_data in indices.items():
                if not isinstance(idx_data, dict):
                    continue
                chg = idx_data.get("change_pct", 0) or 0
                if idx_code in ("000001", "1A0001", "sh000001"):
                    sh_change = chg
                elif idx_code in ("399001", "sz399001"):
                    sz_change = chg
                elif idx_code in ("399006", "sz399006"):
                    cyb_change = chg

            # 主要指数突变判定（取最大绝对值）
            max_idx_change = max(abs(sh_change), abs(sz_change), abs(cyb_change))
            idx_shock = (max_idx_change >= 1.5 and (
                sh_change <= -1.5 or sz_change <= -1.5 or cyb_change <= -1.5
            )) or (max_idx_change >= 2.0 and (
                sh_change >= 2.0 or sz_change >= 2.0 or cyb_change >= 2.0
            ))

            # 账户层面：浮亏接近止损线 + 30分钟内急剧恶化
            account_critical = False
            current_snapshot = {"ts": now_ts, "pnl_ratio": 0.0}
            for acc_id in account_ids:
                db = SessionLocal()
                try:
                    summary = TradeEngine.get_account_summary(db, acc_id)
                    # 当日盈亏比例 = (总资产 - 昨日总资产) / 昨日总资产
                    # 简化：使用持仓总盈亏 / 总资产
                    total_profit = summary.get("total_profit", 0) or 0
                    total_assets = summary.get("total_assets", 1) or 1
                    pnl_ratio = total_profit / total_assets * 100 if total_assets > 0 else 0
                    # 接近止损线（账户层面 -5%）
                    if pnl_ratio <= -4.0:
                        account_critical = True
                    # 跟踪最差账户的 pnl_ratio
                    if pnl_ratio < current_snapshot["pnl_ratio"]:
                        current_snapshot["pnl_ratio"] = pnl_ratio
                except Exception as e:
                    logger.warning(f"剧变检测-账户盈亏查询失败 (account={acc_id}): {e}")
                finally:
                    db.close()

            # 30 分钟内急剧恶化检测
            acute_worsen = False
            if _last_market_snapshot is not None:
                last_ts = _last_market_snapshot.get("ts", 0)
                last_pnl = _last_market_snapshot.get("pnl_ratio", 0)
                if now_ts - last_ts <= 1800 and (current_snapshot["pnl_ratio"] - last_pnl) <= -2.0:
                    acute_worsen = True
            _last_market_snapshot = current_snapshot

            should_regen = idx_shock or account_critical or acute_worsen
            if should_regen and is_trading_hours():
                # 检查系统配置时间：当前时间早于该时段配置时间时，跳过紧急重生成
                _emergency_mode = "intraday" if _datetime.now().hour < 12 else "intraday_afternoon"
                _config_key = "intraday_strategy_time_2" if _emergency_mode == "intraday_afternoon" else "intraday_strategy_time_1"
                _configured_time = (sched_config or {}).get(_config_key, "")
                if _configured_time:
                    current_hhmm = _datetime.now().strftime("%H:%M")
                    if current_hhmm < _configured_time:
                        logger.info(f"剧变纠偏跳过：当前{current_hhmm}早于配置时间{_configured_time}（{_config_key}），等待定时调度")
                        # 不更新 _last_strategy_regenerate_ts，下一轮继续检查
                    else:
                        _last_strategy_regenerate_ts = now_ts
                        trigger_reason = (
                            f"指数突变(sh={sh_change:+.2f}% sz={sz_change:+.2f}% cyb={cyb_change:+.2f}%)" if idx_shock
                            else f"账户浮亏接近止损(pnl={current_snapshot['pnl_ratio']:.2f}%)" if account_critical
                            else f"30分钟内盈亏急剧恶化(delta={current_snapshot['pnl_ratio'] - (_last_market_snapshot.get('pnl_ratio', 0) if _last_market_snapshot else 0):+.2f}%)"
                        )
                        logger.warning(f"盘中剧变纠偏触发: {trigger_reason}, 重生成策略")
                        # 后台线程执行，不阻塞调度循环（LLM 调用可能耗时较长）
                        _threading.Thread(
                            target=_generate_intraday_strategy,
                            args=("emergency_regen",),
                            kwargs={"mode": _emergency_mode},
                            daemon=True,
                        ).start()
                else:
                    # 无配置时间时保持原行为（向后兼容）
                    _last_strategy_regenerate_ts = now_ts
                    logger.warning(f"盘中剧变纠偏触发: 重生成策略")
                    _threading.Thread(
                        target=_generate_intraday_strategy,
                        args=("emergency_regen",),
                        kwargs={"mode": _emergency_mode},
                        daemon=True,
                    ).start()
        except Exception as e:
            logger.warning(f"盘中剧变检测异常: {e}")

    # ── 4. 策略执行（可配置间隔，默认5分钟）──
    if now_ts - _last_strategy_exec >= _strategy_exec_interval:
        _last_strategy_exec = now_ts
        if not is_trading_hours():
            return
        for acc_id in account_ids:
            db = SessionLocal()
            try:
                pending = db.query(AIStrategyDecision).filter(
                    AIStrategyDecision.account_id == acc_id,
                    AIStrategyDecision.decision_date == today_str,
                    AIStrategyDecision.execution_status == "pending",
                    AIStrategyDecision.source == "auto",
                ).order_by(AIStrategyDecision.decision_date.asc()).all()
                for decision in pending:
                    if not is_trading_hours():
                        break
                    try:
                        result = AIStrategyGenerator.execute_strategy(db, decision.id)
                        if result.get("success"):
                            logger.info(
                                f"盘中监控-自动执行策略成功: decision_id={decision.id}"
                            )
                        else:
                            logger.debug(
                                f"盘中监控-策略执行跳过: decision_id={decision.id} "
                                f"skipped={result.get('skipped')} error={result.get('error')}"
                            )
                    except Exception as e:
                        logger.error(
                            f"盘中监控-自动执行策略异常: decision_id={decision.id} {e}"
                        )
            except Exception as e:
                logger.error(f"盘中监控-pending 策略扫描失败 (account={acc_id}): {e}")
            finally:
                db.close()


def _run_decision_alerts() -> None:
    """决策算法预警 - 每10分钟扫描自选股和持仓股（不受交易时间限制）
    
    运行全部7个量化算法，结合持仓感知生成预警。
    预警结果存储到日志文件，供前端展示。
    """
    import json
    from pathlib import Path
    from datetime import date as _date, datetime as _datetime
    from app.core.database import SessionLocal

    now = _datetime.now()

    try:
        from app.services.decision_alert_service import decision_alert_service
        from app.models.watchlist import WatchlistItem
        from app.models.holding import Holding

        db = SessionLocal()
        try:
            # 获取所有用户的自选股和持仓
            # 注意：多用户场景下需要遍历所有活跃用户
            # 简化实现：仅处理有自选股或持仓的用户
            watchlist_items = db.query(WatchlistItem).all()
            holding_items = db.query(Holding).all()

            if not watchlist_items and not holding_items:
                return

            # 按用户分组
            user_watchlists = {}
            user_holdings = {}
            for item in watchlist_items:
                uid = item.user_id
                if uid not in user_watchlists:
                    user_watchlists[uid] = []
                user_watchlists[uid].append({"code": item.stock_code, "name": item.stock_name})

            for item in holding_items:
                uid = item.user_id
                if uid not in user_holdings:
                    user_holdings[uid] = []
                user_holdings[uid].append({
                    "code": item.stock_code,
                    "name": item.stock_name,
                    "cost_price": item.cost_price,
                    "quantity": item.quantity,
                    "position_type": item.position_type or "short",
                    "profit_ratio": item.profit_ratio or 0,
                })

            # 合并所有用户的股票列表（去重）
            all_stocks = {}
            all_holdings = {}
            for uid in set(list(user_watchlists.keys()) + list(user_holdings.keys())):
                for stock in user_watchlists.get(uid, []):
                    all_stocks[stock["code"]] = stock
                for h in user_holdings.get(uid, []):
                    all_stocks[h["code"]] = {"code": h["code"], "name": h["name"]}
                    all_holdings[h["code"]] = h

            if not all_stocks:
                return

            # 执行决策算法监控
            stock_list = list(all_stocks.values())
            holding_context_map = all_holdings if all_holdings else None

            result = decision_alert_service.monitor_stocks(stock_list, holding_context_map)

            # 存储预警结果到日志文件
            alerts_dir = Path(__file__).parent.parent.parent / "alerts"
            alerts_dir.mkdir(exist_ok=True)
            today_str = now.strftime("%Y%m%d")
            alert_file = alerts_dir / f"decision_alerts_{today_str}.json"

            # 读取现有预警
            existing_alerts = []
            if alert_file.exists():
                try:
                    with open(alert_file, "r", encoding="utf-8") as f:
                        existing_alerts = json.load(f)
                except (json.JSONDecodeError, IOError):
                    existing_alerts = []

            # 追加新预警
            new_alerts = result.get("alerts", [])
            if new_alerts:
                existing_alerts.extend(new_alerts)
                with open(alert_file, "w", encoding="utf-8") as f:
                    json.dump(existing_alerts, f, ensure_ascii=False, indent=2)
                logger.info(f"决策算法预警: 新增{len(new_alerts)}条预警")

        finally:
            db.close()

    except Exception as e:
        logger.error(f"决策算法预警任务异常: {e}")


def _record_daily_pnl(trade_date: str) -> None:
    """收盘后记录当日盈亏（不复盘，只计算 PnL）

    Args:
        trade_date: 交易日期，格式 YYYY-MM-DD
    """
    try:
        from app.core.database import SessionLocal
        from app.services.trade_engine import TradeEngine
        db = SessionLocal()
        try:
            account = TradeEngine.get_or_create_account(db)
            TradeEngine.record_daily_pnl(db, account.id, trade_date)
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"当日PnL记录失败: {e}")


def _cleanup_orders_job() -> None:
    """15:30 收盘后清理委托：删除当日 filled/expired，30 天前的 cancelled"""
    try:
        from datetime import datetime as _dt
        from app.core.database import SessionLocal
        from app.models.sim_trading import SimAccount
        from app.services.order_service import OrderService
        db = SessionLocal()
        try:
            today = _dt.now().strftime("%Y-%m-%d")
            for acc in db.query(SimAccount).all():
                r1 = OrderService.cleanup_today_orders(db, acc.id, today)
                r2 = OrderService.cleanup_old_cancelled(db, acc.id, days=30)
                if r1["filled"] or r1["expired"] or r2:
                    logger.info(
                        f"账户 {acc.id} 委托清理: filled={r1['filled']}, "
                        f"expired={r1['expired']}, old_cancelled={r2}"
                    )
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"收盘委托清理任务异常: {e}")


def _unlock_t1_positions(unlock_today_morning_buys: bool = False) -> None:
    """T+1 解锁

    Args:
        unlock_today_morning_buys:
          - False (9:25 上午批次)：解锁 buy_date < 今天 的所有冻结持仓
            （覆盖昨天/上周五/节假日前的买入）
          - True (13:00 下午批次)：解锁 buy_date == 今天 的冻结持仓
            （今早买入下午可卖，A 股 T+1 同日规则）
    """
    from datetime import datetime as _dt
    from sqlalchemy import and_ as _and
    from app.core.database import SessionLocal
    from app.models.sim_trading import SimAccount, SimPosition

    db = SessionLocal()
    try:
        accounts = db.query(SimAccount).all()
        if not accounts:
            logger.info("T+1 解锁：当前无模拟交易账户，跳过")
            return

        today_str = _dt.now().strftime("%Y-%m-%d")
        for account in accounts:
            try:
                if unlock_today_morning_buys:
                    # 下午批次：仅解锁今早买入（有总份额大于可用份额的持仓）
                    result = (
                        db.query(SimPosition)
                        .filter(_and(
                            SimPosition.account_id == account.id,
                            SimPosition.buy_date == today_str,
                            SimPosition.total_quantity > SimPosition.available_quantity,
                        ))
                        .update(
                            {SimPosition.available_quantity: SimPosition.total_quantity},
                            synchronize_session=False,
                        )
                    )
                else:
                    # 上午批次：解锁所有早于今天的待解锁持仓（跨周末/节假日）
                    result = (
                        db.query(SimPosition)
                        .filter(_and(
                            SimPosition.account_id == account.id,
                            SimPosition.buy_date < today_str,
                            SimPosition.total_quantity > SimPosition.available_quantity,
                        ))
                        .update(
                            {SimPosition.available_quantity: SimPosition.total_quantity},
                            synchronize_session=False,
                        )
                    )
                db.commit()
                if result:
                    logger.info(
                        f"T+1 解锁：账户 {account.id} 解锁 {result} 个持仓 "
                        f"({'今早买入可下午卖' if unlock_today_morning_buys else '昨日/更早买入可今早卖'})"
                    )
            except Exception as e:
                db.rollback()
                logger.warning(f"T+1 解锁：账户 {account.id} 失败: {e}")
    finally:
        db.close()


def _generate_review_and_strategy(trade_date: str) -> None:
    """收盘复盘+次日策略合并生成（可配置时间，默认15:06）

    一次 LLM 调用链完成闭环：
    1. 复盘当日交易，生成 lessons（经验教训）保存到 SimDailyReview
    2. 生成次日策略时自动注入最近3天 lessons 到 prompt（_get_recent_lessons）
    3. 策略保存为 pending，次日盘中监控自动执行

    Args:
        trade_date: 交易日期，格式 YYYY-MM-DD

    修复 Bug：原代码吞异常导致 _run_long_task 误认为成功，
    _sched_last_run 不清除，30 分钟容错窗口内不重试，当天任务永久漏触发。
    现在失败时抛出异常，让 _run_long_task 捕获并清除标记。
    """
    from app.core.database import SessionLocal
    from app.services.trade_engine import TradeEngine
    from app.services.review_service import generate_daily_review
    from app.services.ai_strategy_generator import AIStrategyGenerator

    db = SessionLocal()
    try:
        account = TradeEngine.get_or_create_account(db)

        # 步骤1：复盘当日交易，生成 lessons
        review_result = generate_daily_review(db, account.id, trade_date)
        if review_result.get("success"):
            logger.info(
                f"复盘完成: {trade_date}, "
                f"交易{review_result.get('trade_count', 0)}笔, "
                f"lessons={'有' if review_result.get('lessons') else '无'}"
            )
        else:
            # 抛出异常让 _run_long_task 清除标记允许重试
            raise RuntimeError(f"复盘失败: {review_result.get('error', '未知错误')}")

        # 提取复盘报告完整内容，注入次日策略 prompt
        review_analysis = review_result.get("ai_review", "") or ""
        if not review_analysis:
            # 兜底：从数据库读取刚生成的复盘
            from app.models.sim_trading import SimDailyReview
            review_obj = db.query(SimDailyReview).filter(
                SimDailyReview.account_id == account.id,
                SimDailyReview.review_date == trade_date,
            ).first()
            if review_obj and review_obj.ai_review:
                review_analysis = review_obj.ai_review

        # 步骤2：生成次日策略（注入复盘分析 + _get_recent_lessons 注入经验教训）
        strategy_result = AIStrategyGenerator.generate_next_day_strategy(
            db, account.id, review_analysis=review_analysis
        )
        if strategy_result.get("success"):
            buy_count = len(strategy_result.get('buy_list', []))
            sell_count = len(strategy_result.get('sell_signals', []))
            decision_date = strategy_result.get('decision_date', '')
            logger.info(
                f"次日策略生成成功: 执行日={decision_date}, "
                f"买入{buy_count}只, 卖出{sell_count}只"
            )
        else:
            raise RuntimeError(f"次日策略生成失败: {strategy_result.get('error', '')}")
    finally:
        db.close()


def _generate_midday_strategy() -> None:
    """午间策略调整（可配置时间，默认11:30）

    总结上午交易执行情况，结合上午市场走势，
    调用 AI 调整下午交易策略，覆盖当日 pending 策略。

    修复 Bug：原代码吞异常导致 _run_long_task 误认为成功，重试失效。
    """
    from app.core.database import SessionLocal
    from app.services.trade_engine import TradeEngine
    from app.services.ai_strategy_generator import AIStrategyGenerator

    db = SessionLocal()
    try:
        account = TradeEngine.get_or_create_account(db)
        result = AIStrategyGenerator.generate_midday_strategy(db, account.id)
        if result.get("success"):
            buy_count = len(result.get("buy_list", []))
            sell_count = len(result.get("sell_signals", []))
            logger.info(
                f"午间策略调整完成: 买入{buy_count}只, 卖出{sell_count}只"
            )
        else:
            # 抛出异常让 _run_long_task 清除标记允许重试
            raise RuntimeError(f"午间策略调整失败: {result.get('error', '')}")
    finally:
        db.close()


def _generate_intraday_strategy(session_label: str = "", config_key: str = "", mode: str = "intraday") -> None:
    """盘中策略生成（可配置时间，默认10:30/13:30）

    调用 generate_strategy(intraday)，结合实时行情、持仓、未成交委托，
    生成新策略覆盖当日 pending。生成后由 _intraday_monitor 周期自动执行。

    Args:
        session_label: 日志标识（兼容旧调用），传空则从配置读取
        config_key: 配置键名（如 "intraday_strategy_time_2"），用于读取实际配置时间
        mode: 策略模式，"intraday"=上午盘中，"intraday_afternoon"=下午盘中

    修复 Bug：原代码吞异常导致 _run_long_task 误认为成功，重试失效。
    """
    from app.core.database import SessionLocal
    from app.services.trade_engine import TradeEngine
    from app.services.ai_strategy_generator import AIStrategyGenerator
    from app.core.trading_calendar import is_trading_hours

    # 若未传 session_label，从配置读取实际时间作为日志标识
    if not session_label and config_key:
        try:
            from app.models.scheduler_config import SchedulerConfig
            _cfg_db = SessionLocal()
            _cfg = _cfg_db.query(SchedulerConfig).first()
            _cfg_db.close()
            if _cfg:
                session_label = getattr(_cfg, config_key, "") or config_key
        except Exception:
            session_label = config_key

    # 触发时立即检查交易时段，避免任务后台排队到午休/收盘后才执行导致被拒
    # 容错：允许 5 分钟偏移（如 10:30 触发但实际已 11:34，仍允许执行上午收盘前）
    if not is_trading_hours():
        _now = datetime.now()
        # 上午 11:30-11:35 容错窗口（避免任务队列延迟导致错过上午收盘）
        _h, _m = _now.hour, _now.minute
        _is_grace_morning = (_h == 11 and 30 <= _m <= 35)
        # 下午 14:55-15:00 容错窗口（避免收盘前最后阶段被拒）
        _is_grace_afternoon = (_h == 14 and _m >= 55)
        if not (_is_grace_morning or _is_grace_afternoon):
            raise RuntimeError(
                f"盘中策略-{session_label}：非交易时段，跳过（当前{_now.strftime('%H:%M')}）"
            )

    db = SessionLocal()
    try:
        account = TradeEngine.get_or_create_account(db)
        result = AIStrategyGenerator.generate_strategy(db, account.id, mode=mode)
        if result.get("success"):
            buy_count = len(result.get("buy_list", []))
            sell_count = len(result.get("sell_signals", []))
            logger.info(
                f"盘中策略-{session_label}生成完成: 买入{buy_count}只, 卖出{sell_count}只"
            )
        else:
            # 抛出异常让 _run_long_task 清除标记允许重试
            raise RuntimeError(f"盘中策略-{session_label}生成失败: {result.get('error', '')}")
    finally:
        db.close()


def _preheat_news_and_research() -> None:
    """预热资讯和研报缓存：从 akshare 拉取最新数据写入 news_data 目录

    与 nlp.news_refresh 端点逻辑一致，但作为后台任务运行：
      1) get_all_news 拉最新 50 条 → news_YYYY-MM-DD.json
      2) get_all_research 拉最新 30 条 → research_all.json
    """
    from app.services.news_service import get_all_news, get_all_research
    from app.api.nlp import _save_news_items, _save_research_items

    all_items = get_all_news(top_n=50)
    if all_items:
        _save_news_items(all_items, 'refresh')

    research_items = get_all_research(top_n=30, force_refresh=True)
    if research_items:
        _save_research_items(research_items)


def _preheat_dragon_and_strategies(s: "StrategyService") -> None:
    """龙虎榜 + 智能选股预热（共享同一份 strategy_calls，7个策略并行）"""
    try:
        s.get_dragon_list_today(force_refresh=True)
        s.get_dragon_capital_flow(force_refresh=True)
        s.get_dragon_seat_detail(force_refresh=True)
        s.get_dragon_sector_analysis(force_refresh=True)
        s.get_dragon_next_day_performance(force_refresh=True)
        logger.debug("龙虎榜预热完成")
    except Exception as e:
        logger.warning(f"龙虎榜预热失败: {e}")

    strategy_calls = [
        ('multi_factor', lambda: s.get_multi_factor_picks(top_n=20, exclude_st=True, force_refresh=True)),
        ('low_absorption', lambda: s.get_low_absorption_picks(top_n=20, exclude_st=True, force_refresh=True)),
        ('dragon_strategy', lambda: s.get_dragon_list_strategy(strategy_type='all', top_n=20, force_refresh=True)),
        ('ml', lambda: s.predict_ml_stocks(top_n=20, exclude_st=True, force_refresh=True)),
        ('capital_flow', lambda: s.get_capital_flow_picks(top_n=20, exclude_st=True, force_refresh=True)),
        ('combo', lambda: s.get_strategy_combo(top_n=20, exclude_st=True, force_refresh=True)),
        ('signal_scan', lambda: s.get_strategy_comparison(force_refresh=True)),
    ]
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="preheat") as executor:
        futures = {executor.submit(fn): name for name, fn in strategy_calls}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
                logger.debug(f"智能选股预热[{name}]完成")
            except Exception as e:
                logger.warning(f"智能选股预热[{name}]失败: {e}")


def _preheat_sector_analysis() -> None:
    """预热板块深度分析缓存（收盘后全量拉取）"""
    from app.services.sector_analysis_service import sector_analysis_service

    try:
        sector_analysis_service.get_limit_up_ladder(force_refresh=True)
        logger.debug("板块分析预热[涨停梯队]完成")
    except Exception as e:
        logger.warning(f"板块分析预热[涨停梯队]失败: {e}")

    try:
        sector_analysis_service.get_sector_rotation_model('industry', 30, force_refresh=True)
        logger.debug("板块分析预热[轮动模型-行业]完成")
    except Exception as e:
        logger.warning(f"板块分析预热[轮动模型-行业]失败: {e}")

    try:
        sector_analysis_service.get_sector_rotation_model('concept', 30, force_refresh=True)
        logger.debug("板块分析预热[轮动模型-概念]完成")
    except Exception as e:
        logger.warning(f"板块分析预热[轮动模型-概念]失败: {e}")

    try:
        sector_analysis_service.get_industry_research_reports(30, force_refresh=True)
        logger.debug("板块分析预热[行业研报]完成")
    except Exception as e:
        logger.warning(f"板块分析预热[行业研报]失败: {e}")

    try:
        sector_analysis_service.get_sector_heat_rank(30, force_refresh=True)
        logger.debug("板块分析预热[热度排行]完成")
    except Exception as e:
        logger.warning(f"板块分析预热[热度排行]失败: {e}")

    try:
        sector_analysis_service.get_industry_chain_analysis(force_refresh=True)
        logger.debug("板块分析预热[产业链]完成")
    except Exception as e:
        logger.warning(f"板块分析预热[产业链]失败: {e}")


def _preheat_market_and_dragon(extended: bool = False) -> None:
    """预热市场看板和龙虎榜缓存（仅在交易时间调用）

    Args:
        extended: True=启动预热（10个端点含 include_flow+indices+limit_up+ths_hot+northbound）
                  False=定时预热（5个核心端点）
    """
    from app.services.market_service import MarketService
    from app.services.strategy_service import StrategyService

    m = MarketService()
    try:
        if extended:
            m.get_market_sentiment(include_flow=True)
            m.get_market_sentiment(include_flow=False)
            m.get_indices_with_kline(
                ['000001', '399001', '399006', '000300', '000016', '000688', '000905', '399005', '000852'],
                30
            )
            m.get_limit_up_pool()
            m.get_ths_hot_rank(top=30)
            m.get_northbound_flow()
        else:
            m.get_market_sentiment()
        m.get_sectors(sector_type='industry', top=30)
        m.get_sectors(sector_type='concept', top=30)
        m.get_hot_sectors(top=10)
        m.get_rotation_signals()
        logger.debug("市场看板预热完成")
    except Exception as e:
        logger.warning(f"市场看板预热失败: {e}")

    _preheat_dragon_and_strategies(StrategyService())


async def _startup_preheat():
    """启动后立即预热，不依赖交易时段。

    非交易时段：仅预热基础端点（避免阻塞请求）
    交易时段：完整预热（含龙虎榜+智能选股）
    预热完成后更新 _last_market_preheat_ts，避免调度循环第一时间重复执行
    """
    from app.core.trading_calendar import is_trading_hours
    import time as _time

    await asyncio.sleep(2)  # 等应用完全就绪
    try:
        trading_hours = is_trading_hours()
        await asyncio.to_thread(_preheat_market_and_dragon, extended=trading_hours)
        logger.info("启动预热完成：市场看板/龙虎榜缓存已就绪")
    except Exception as e:
        logger.warning(f"启动预热失败: {e}")
    finally:
        global _last_market_preheat_ts
        _last_market_preheat_ts = _time.time()


# 导入服务实例供 lifespan 和统一调度使用
from app.services.ai_stock_pick_service import ai_stock_pick_service
from app.services.daily_report_service import daily_report_service

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="基于20个分析模块的A股智能投资决策辅助平台",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "请求过于频繁，请稍后重试"},
    )

# 注册限流器与异常处理
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """请求 ID 中间件：从 header 沿用或生成新 UUID，写入 contextvars 并回传 header"""
    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_var.reset(token)


# 注册请求 ID 中间件（必须在最外层以便所有后续中间件/路由都能获取）
app.add_middleware(RequestIdMiddleware)

# CORS中间件 - 仅放行白名单 origin、限制 methods/headers
# 生产环境通过环境变量 CORS_ORIGINS 覆盖，默认仅允许本地开发地址

class TimeoutMiddleware(BaseHTTPMiddleware):
    """请求超时中间件 - 防止长耗时请求导致 ECONNRESET"""
    
    async def dispatch(self, request: Request, call_next):
        # 不同路径设置不同超时时间
        path = request.url.path
        if "/diagnosis" in path or "/technical/" in path or "/patterns/" in path or "/strategy/combo" in path:
            timeout = 45.0  # 诊断/技术指标/K线形态/组合策略允许更长时间
        elif "/ai-stock-picks/generate" in path or "/daily-reports/generate" in path or "/sim-trading/strategy/generate" in path or "/sim-trading/strategy/next-day" in path or "/sim-trading/strategy/midday" in path or "/watchlist-strategy/generate" in path:
            timeout = 600.0  # AI报告/AI策略生成（LLM调用，资源紧张时可能较慢）
        elif "/market/sentiment" in path:
            timeout = 90.0  # 市场情绪（含资金流全市场聚合 ~30s + 涨跌停+指数）
        elif "/dragon/" in path or "/ml/" in path:
            timeout = 30.0  # 龙虎榜/ML预测
        elif "/strategy/" in path:
            timeout = 60.0  # 策略选股（含资金流、多因子等，可能调用多个外部API）
        elif "/market/ths_hot_rank" in path:
            timeout = 90.0  # 同花顺热门榜（内部调资金流全市场聚合）
        elif "/market/limit_up_pool" in path:
            timeout = 40.0  # 涨停板池
        elif "/market/sectors" in path or "/market/hot" in path:
            timeout = 50.0  # 板块/热点
        elif "/sector-analysis/" in path:
            timeout = 45.0  # 板块深度分析
        elif "/cache/preload" in path:
            timeout = 120.0  # 缓存预加载（并发拉取多个模块）
        else:
            timeout = 30.0  # 其他接口（50+并发时适当放宽）
        
        try:
            response = await asyncio.wait_for(
                call_next(request), 
                timeout=timeout
            )
            return response
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=504,
                content={"detail": f"请求超时（>{timeout}秒），请稍后重试"}
            )

app.add_middleware(TimeoutMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "X-Requested-With"],
    max_age=600,  # 预检请求缓存10分钟，减少 OPTIONS 请求
)

# 生产环境安全检查：如果 CORS_ORIGINS 仍为默认值且 DEBUG=False，发出警告
if not settings.DEBUG and set(settings.CORS_ORIGINS) == {"http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"}:
    logger.warning("生产环境 CORS_ORIGINS 仍为默认开发值，请通过环境变量设置实际域名")


# ========== 认证检查中间件 ==========
PUBLIC_PATHS = [
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
]

# 决策中心公开路径（免认证访问）
DECISION_PUBLIC_PREFIXES = [
    "/api/v1/decision/signals/",
    "/api/v1/decision/scan",
    "/api/v1/decision/watchlist-signals",
]
PUBLIC_PATH_PREFIXES = [
    "/assets/",
    "/favicon",
]


@app.middleware("http")
async def check_auth(request: Request, call_next):
    """请求中间件：检查JWT token（仅保护API路径）
    
    注意：不能在此处 raise HTTPException，否则 BaseHTTPMiddleware 会将其包装为
    ExceptionGroup，导致 Starlette ErrorMiddleware 返回 500 而非 401。
    改为直接返回 JSONResponse 绕过此问题。
    """
    path = request.url.path

    # 公开路径精确匹配
    if any(path == p for p in PUBLIC_PATHS):
        return await call_next(request)

    # 决策中心公开路径（免认证）
    if any(path.startswith(p) for p in DECISION_PUBLIC_PREFIXES):
        return await call_next(request)

    # 公开路径前缀匹配
    if any(path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
        return await call_next(request)

    # 仅保护 API 路径，前端SPA页面直接放行
    if not path.startswith("/api/"):
        return await call_next(request)

    # 检查 Authorization header
    token = request.headers.get("Authorization", "")
    if not token.startswith("Bearer "):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "请先登录"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 验证token有效性
    from app.core.auth import decode_token
    jwt_token = token.replace("Bearer ", "")
    payload = decode_token(jwt_token)
    if not payload:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "登录已过期，请重新登录"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 将用户信息注入request state，供后续使用
    user_id = int(payload.get("sub"))
    request.state.user_id = user_id
    request.state.user_role = payload.get("role", "normal")

    # 记录用户心跳（在线状态追踪）
    from app.core.online import heartbeat as record_heartbeat
    record_heartbeat(user_id)

    response = await call_next(request)
    return response


# ========== 注册路由 ==========
app.include_router(auth.router, prefix=settings.API_V1_PREFIX, tags=["认证"])
app.include_router(admin.router, prefix=settings.API_V1_PREFIX, tags=["管理员"])
app.include_router(chat_history.router, prefix=settings.API_V1_PREFIX, tags=["对话历史"])
app.include_router(daily_reports.router, prefix=settings.API_V1_PREFIX, tags=["复盘报告"])
app.include_router(ai_stock_picks.router, prefix=settings.API_V1_PREFIX, tags=["AI股票推荐"])
app.include_router(market.router, prefix=settings.API_V1_PREFIX, tags=["市场看板"])
app.include_router(stock.router, prefix=settings.API_V1_PREFIX, tags=["个股诊断"])
app.include_router(strategy.router, prefix=settings.API_V1_PREFIX, tags=["智能选股"])
app.include_router(nlp.router, prefix=settings.API_V1_PREFIX, tags=["对话分析"])
app.include_router(chat.router, prefix=settings.API_V1_PREFIX, tags=["LLM对话"])
app.include_router(watchlist.router, prefix=settings.API_V1_PREFIX, tags=["自选股"])
app.include_router(preload.router, prefix=settings.API_V1_PREFIX, tags=["缓存预加载"])
app.include_router(sector_analysis.router, prefix=settings.API_V1_PREFIX, tags=["板块深度分析"])
app.include_router(sim_trading.router, prefix=settings.API_V1_PREFIX, tags=["模拟交易"])
app.include_router(holdings.router, prefix=f"{settings.API_V1_PREFIX}/holdings", tags=["持仓管理"])
app.include_router(watchlist_strategy.router, prefix=f"{settings.API_V1_PREFIX}/watchlist-strategy", tags=["自选股AI策略"])
app.include_router(backtest.router, prefix=settings.API_V1_PREFIX, tags=["策略回测"])
app.include_router(alerts.router, prefix=settings.API_V1_PREFIX, tags=["智能预警"])
app.include_router(decision.router, prefix=settings.API_V1_PREFIX, tags=["决策中心"])


# ========== 健康检查（必须在 SPA catch-all 之前注册）==========
@app.get("/health", tags=["健康检查"])
async def health_check():
    """健康检查接口"""
    return {"status": "healthy", "version": settings.APP_VERSION}


# ========== 前端静态文件服务（单端口部署）==========
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(_FRONTEND_DIST, "assets")), name="assets")

    @app.get("/", tags=["根路径"])
    async def serve_frontend():
        """前端SPA首页"""
        index_path = os.path.join(_FRONTEND_DIST, "index.html")
        if os.path.isfile(index_path):
            response = FileResponse(index_path)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
        return {"name": settings.APP_NAME, "version": settings.APP_VERSION, "status": "running"}

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """SPA路由回退：所有非API路径返回index.html"""
        # 不拦截 API、文档等已知路径，让 Starlette 继续匹配后续路由
        if full_path.startswith(("api", "docs", "redoc", "openapi.json")):
            raise HTTPException(status_code=404, detail="Not Found")
        file_path = os.path.join(_FRONTEND_DIST, full_path)
        if os.path.isfile(file_path):
            response = FileResponse(file_path)
            # index.html 不缓存，其他文件用浏览器默认缓存
            if full_path == "index.html":
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response
        index_path = os.path.join(_FRONTEND_DIST, "index.html")
        if os.path.isfile(index_path):
            response = FileResponse(index_path)
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
        raise HTTPException(status_code=404, detail="Not Found")
else:
    logger.warning(f"前端构建产物不存在 ({_FRONTEND_DIST})，请先运行 npm run build")

    @app.get("/", tags=["根路径"])
    async def root():
        """平台首页"""
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "modules": 20,
            "docs": "/docs",
        }

