"""任务队列服务 - 耗时任务异步执行+进度反馈

功能：
1. 支持异步任务提交和执行
2. 实时进度反馈
3. 任务状态查询
4. 支持取消任务

适用场景：
1. 智能选股组合策略（需要调用多个子策略）
2. 龙虎榜数据分析（需要调用多个API）
3. 批量数据计算
"""

import json
import time
import uuid
import logging
import asyncio
import threading
from typing import Optional, Any, Callable
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"      # 等待执行
    RUNNING = "running"      # 执行中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 失败
    CANCELLED = "cancelled"  # 已取消


@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    task_type: str
    status: TaskStatus
    progress: int  # 0-100
    message: str
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    def to_dict(self):
        return asdict(self)


class TaskQueue:
    """任务队列"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._tasks: dict[str, TaskInfo] = {}
        self._task_funcs: dict[str, Callable] = {}
        self._running = False
        self._thread = None
        self._queue: asyncio.Queue = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    def start(self):
        """启动任务队列"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="task_queue")
        self._thread.start()
        logger.info("任务队列已启动")
    
    def stop(self):
        """停止任务队列"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("任务队列已停止")
    
    def _run_loop(self):
        """任务队列主循环"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
    
    def submit_task(self, task_type: str, func: Callable, *args, **kwargs) -> str:
        """提交任务
        
        Args:
            task_type: 任务类型
            func: 任务函数
            *args, **kwargs: 函数参数
        
        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())[:8]
        
        task_info = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            progress=0,
            message="等待执行",
            created_at=datetime.now().isoformat()
        )
        
        self._tasks[task_id] = task_info
        self._task_funcs[task_id] = (func, args, kwargs)
        
        # 在事件循环中执行任务
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._execute_task(task_id),
                self._loop
            )
        
        logger.info(f"任务已提交: {task_id} ({task_type})")
        return task_id
    
    async def _execute_task(self, task_id: str):
        """执行任务"""
        task_info = self._tasks.get(task_id)
        if not task_info:
            return
        
        func, args, kwargs = self._task_funcs.get(task_id, (None, [], {}))
        if not func:
            task_info.status = TaskStatus.FAILED
            task_info.error = "任务函数不存在"
            return
        
        task_info.status = TaskStatus.RUNNING
        task_info.started_at = datetime.now().isoformat()
        task_info.message = "执行中..."
        
        try:
            # 创建进度回调
            def update_progress(progress: int, message: str = ""):
                task_info.progress = min(100, max(0, progress))
                if message:
                    task_info.message = message
            
            kwargs['progress_callback'] = update_progress
            
            # 执行任务
            result = await asyncio.to_thread(func, *args, **kwargs)
            
            task_info.status = TaskStatus.COMPLETED
            task_info.progress = 100
            task_info.message = "已完成"
            task_info.result = result
            task_info.completed_at = datetime.now().isoformat()
            
        except asyncio.CancelledError:
            task_info.status = TaskStatus.CANCELLED
            task_info.message = "已取消"
        except Exception as e:
            task_info.status = TaskStatus.FAILED
            task_info.error = str(e)
            task_info.message = f"执行失败: {e}"
            logger.error(f"任务执行失败 {task_id}: {e}")
        
        finally:
            # 清理任务函数引用
            self._task_funcs.pop(task_id, None)
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务状态"""
        return self._tasks.get(task_id)
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task_info = self._tasks.get(task_id)
        if not task_info:
            return False
        
        if task_info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        
        task_info.status = TaskStatus.CANCELLED
        task_info.message = "已取消"
        return True
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        cutoff = time.time() - max_age_hours * 3600
        to_remove = []
        
        for task_id, task_info in self._tasks.items():
            try:
                created = datetime.fromisoformat(task_info.created_at)
                if created.timestamp() < cutoff:
                    to_remove.append(task_id)
            except Exception:
                pass
        
        for task_id in to_remove:
            del self._tasks[task_id]
        
        return len(to_remove)


# 全局单例
task_queue = TaskQueue()


# ── 预定义任务类型 ──────────────────────────────────────

def submit_combo_strategy_task(top_n: int = 20, exclude_st: bool = True, **kwargs):
    """提交组合策略任务"""
    from app.services.strategy_service import StrategyService
    
    def run_task(progress_callback=None):
        s = StrategyService()
        if progress_callback:
            progress_callback(10, "正在加载多因子策略...")
        result = s.get_strategy_combo(top_n=top_n, exclude_st=exclude_st, force_refresh=True)
        if progress_callback:
            progress_callback(100, "完成")
        return result
    
    return task_queue.submit_task("combo_strategy", run_task)


def submit_dragon_analysis_task(**kwargs):
    """提交龙虎榜分析任务"""
    from app.services.strategy_service import StrategyService
    
    def run_task(progress_callback=None):
        s = StrategyService()
        if progress_callback:
            progress_callback(10, "正在加载龙虎榜数据...")
        today = s.get_dragon_list_today(force_refresh=True)
        if progress_callback:
            progress_callback(30, "正在加载资金流向...")
        capital = s.get_dragon_capital_flow(force_refresh=True)
        if progress_callback:
            progress_callback(60, "正在加载席位明细...")
        seat = s.get_dragon_seat_detail(force_refresh=True)
        if progress_callback:
            progress_callback(80, "正在加载板块分析...")
        sector = s.get_dragon_sector_analysis(force_refresh=True)
        if progress_callback:
            progress_callback(100, "完成")
        return {
            "today": today,
            "capital_flow": capital,
            "seat_detail": seat,
            "sector_analysis": sector
        }
    
    return task_queue.submit_task("dragon_analysis", run_task)


def submit_market_overview_task(**kwargs):
    """提交市场概览任务"""
    from app.services.market_service import MarketService
    
    def run_task(progress_callback=None):
        m = MarketService()
        if progress_callback:
            progress_callback(10, "正在加载市场情绪...")
        sentiment = m.get_market_sentiment(include_flow=False)
        if progress_callback:
            progress_callback(30, "正在加载板块数据...")
        industry = m.get_sectors(sector_type='industry', top=30)
        if progress_callback:
            progress_callback(50, "正在加载概念板块...")
        concept = m.get_sectors(sector_type='concept', top=30)
        if progress_callback:
            progress_callback(70, "正在加载热门板块...")
        hot = m.get_hot_sectors(top=10)
        if progress_callback:
            progress_callback(90, "正在加载轮动信号...")
        signals = m.get_rotation_signals()
        if progress_callback:
            progress_callback(100, "完成")
        return {
            "sentiment": sentiment,
            "industry": industry,
            "concept": concept,
            "hot_sectors": hot,
            "signals": signals
        }
    
    return task_queue.submit_task("market_overview", run_task)
