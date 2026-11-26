"""对话分析API路由 - 意图识别与多模块串联"""
import os
import re
import json
import subprocess
import logging
from datetime import datetime
from datetime import timedelta
from fastapi import APIRouter, Query, Depends
from typing import Optional
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.auth import get_current_user
from app.models.user import User

settings = get_settings()
router = APIRouter()
log = logging.getLogger(__name__)

NEWS_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "news_data")

MIN_OUTPUT_LEN = 50
MIN_DRAGON_LEN = 100


def _save_news_items(items: list[dict], query: str = '') -> None:
    """直接保存新闻条目列表（支持 akshare 数据）"""
    os.makedirs(NEWS_DATA_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%H%M%S")

    if not items:
        return

    data_file = os.path.join(NEWS_DATA_DIR, f"news_{today}.json")
    existing = []
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            existing = []

    existing_titles = {e['title'] for e in existing}
    added = 0
    for item in items:
        if item.get('title') and item['title'] not in existing_titles:
            existing.append({**item, 'query': query or item.get('query', ''), 'savedAt': f"{today} {timestamp}"})
            existing_titles.add(item['title'])
            added += 1

    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    if added > 0:
        log.info("[news_save] 今日新增 %d 条，共 %d 条", added, len(existing))


def _cleanup_old_news(keep_days: int = 7) -> None:
    """清理超过指定天数的旧缓存文件"""
    from datetime import timedelta
    if not os.path.exists(NEWS_DATA_DIR):
        return

    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for fname in os.listdir(NEWS_DATA_DIR):
        if fname.startswith("news_") and fname.endswith(".json"):
            date_str = fname.replace("news_", "").replace(".json", "")
            if date_str < cutoff:
                fpath = os.path.join(NEWS_DATA_DIR, fname)
                try:
                    os.remove(fpath)
                    log.info("[news_cleanup] 删除旧文件: %s", fname)
                except Exception:
                    pass


class ChatRequest(BaseModel):
    """对话请求"""
    message: str
    context: Optional[dict] = None


class ChatResponse(BaseModel):
    """对话响应"""
    intent: str
    confidence: float
    entities: dict
    response: str
    modules_used: list[str]


# 技能脚本白名单：仅允许执行以下脚本，防止 RCE
_ALLOWED_SKILL_SCRIPTS = {
    "tech-indicators/tech_indicators.py",
    "market-sentiment/market_sentiment.py",
    "dragon-list/dragon_list.py",
    "sector-rotation/sector_rotation.py",
    "multi-factor/multi_factor.py",
    "ml-stock-picker/ml_stock_picker.py",
    "kline-patterns/kline_patterns.py",
    "nlp-analyzer/nlp_analyzer.py",
}


def _run_skill(script_rel: str, args: list[str] = None, timeout: int = 60) -> str:
    """安全地运行skill脚本（白名单校验 + 路径遍历防护）"""
    # 白名单检查：拒绝不在列表中的脚本
    if script_rel not in _ALLOWED_SKILL_SCRIPTS:
        log.warning("[skill] 拒绝执行未授权脚本: %s", script_rel)
        return ""

    # 路径遍历防护：确保解析后的路径在 SKILLS_DIR 内
    skills_dir = os.path.realpath(settings.SKILLS_DIR)
    script = os.path.realpath(os.path.join(skills_dir, script_rel))
    if not script.startswith(skills_dir):
        log.warning("[skill] 路径遍历攻击检测: %s", script_rel)
        return ""

    if not os.path.exists(script):
        return ""

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            ["python", script] + (args or []),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            env=env
        )
        if result.returncode != 0 and result.stderr:
            log.warning("[skill %s] stderr: %s", script_rel, result.stderr[:500])
        return result.stdout
    except subprocess.TimeoutExpired:
        log.error("[skill %s] timed out after %ds", script_rel, timeout)
        return ""
    except Exception as e:
        log.error("[skill %s] failed: %s", script_rel, e)
        return ""


# 常见股票名称 → 代码映射（仅用于辅助识别，匹配不到不兜底）
_NAME_TO_CODE = {
    "茅台": "600519", "平安": "000001", "宁德": "300750", "宁德时代": "300750",
    "比亚迪": "002594", "五粮液": "000858", "招商银行": "600036", "招行": "600036",
    "海康": "002415", "海康威视": "002415", "东方财富": "300059",
    "隆基": "601012", "隆基绿能": "601012", "立讯": "002475", "格力": "000651",
    "中信证券": "600030", "伊利": "600887", "片仔癀": "600436",
}

# 关键词集合：每个 intent 独立匹配，靠优先级排序来定最终意图
_INTENT_KEYWORDS = {
    # 复盘报告（最具体）
    "daily_report": ["复盘", "日报", "今日总结", "今天总结", "盘后总结", "市场复盘"],
    # 龙虎榜/游资
    "dragon_list": ["龙虎榜", "游资", "机构买入", "机构净买入", "上榜"],
    # 选股/筛选
    "smart_pick": ["选股", "选什么", "选一只", "选几只", "选几只股", "筛选", "推荐", "买什么", "推荐股票", "有什么股票"],
    # 板块轮动/热点
    "sector_rotation": ["板块", "行业", "概念", "热点", "轮动", "题材"],
    # 资金流向（板块或个股专用关键词）
    "fund_flow": ["资金流向", "主力资金", "资金流入", "净流入", "资金净流入"],
    # 新闻/公告/研报
    "news_search": ["新闻", "公告", "消息", "资讯", "研报", "财报", "研究报告"],
    # 大盘/指数/情绪（最宽泛的，优先级最低）
    "market_sentiment": ["大盘", "上证", "深证", "创业板", "北证", "市场情绪", "情绪", "今天行情", "今日行情", "指数"],
}

# 个股诊断关键词（独立判断：需含"分析/怎么样"等且有具体代码或名称）
_STOCK_DIAGNOSIS_KW = ["怎么样", "分析", "走势", "技术", "指标", "股价", "估值", "财报", "技术面", "基本面"]


def _extract_stock_code(query: str) -> str | None:
    """从查询中提取股票代码（6位数字）或名称"""
    code_match = re.search(r'(\d{6})', query)
    if code_match:
        return code_match.group(1)
    for name, code in _NAME_TO_CODE.items():
        if name in query:
            return code
    return None


def _classify_intent(query: str) -> dict:
    """意图识别 - 按从具体到宽泛的顺序匹配，匹配不到才落到 general_query"""
    q = query.lower()
    entities: dict = {}

    # ── 优先级 1: 个股诊断（必须含股票代码或名称 + 诊断关键词）──
    code = _extract_stock_code(query)
    if code and any(kw in query for kw in _STOCK_DIAGNOSIS_KW):
        return {
            "intent": "stock_diagnosis",
            "confidence": 0.9,
            "entities": {"stock": code},
        }

    # ── 优先级 2-7: 按 _INTENT_KEYWORDS 顺序匹配（具体优先）──
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            if intent == "news_search":
                entities = {"query": query}
            elif intent == "fund_flow" and code:
                entities = {"stock": code}
            return {
                "intent": intent,
                "confidence": 0.85,
                "entities": entities,
            }

    # ── 优先级 8: 含 6 位代码但无明确诊断意图 → 兜底 stock_diagnosis ──
    if code:
        return {
            "intent": "stock_diagnosis",
            "confidence": 0.75,
            "entities": {"stock": code},
        }

    # ── 默认: 通用查询 ──
    return {"intent": "general_query", "confidence": 0.5, "entities": {"query": query}}


@router.post("/nlp/analyze")
async def analyze_nlp(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """自然语言分析 - 识别意图并执行对应分析"""
    intent_result = _classify_intent(request.message)
    intent = intent_result["intent"]

    response_text = ""
    modules_used = []

    if intent == "stock_diagnosis":
        stock_code = intent_result["entities"].get("stock", "600519")
        output = _run_skill("tech-indicators/tech_indicators.py", [stock_code, "近一年"])
        if output.strip() and len(output) > MIN_OUTPUT_LEN:
            response_text = output
            modules_used.append("tech-indicators")
        else:
            response_text = f"暂无法获取 {stock_code} 的技术分析数据，请稍后重试或使用「个股诊断」页面查看。"
            modules_used.append("unavailable")

    elif intent == "market_sentiment":
        output = _run_skill("market-sentiment/market_sentiment.py", ["--report"])
        if output.strip() and len(output) > MIN_OUTPUT_LEN:
            response_text = output
            modules_used.append("market-sentiment")
        else:
            response_text = "暂无法获取市场情绪数据，请稍后重试或前往「市场看板」页面查看。"
            modules_used.append("unavailable")

    elif intent == "sector_rotation":
        output = _run_skill("market-sentiment/market_sentiment.py", ["--sectors"])
        if output.strip() and len(output) > MIN_OUTPUT_LEN:
            response_text = output
            modules_used.append("market-sentiment/sectors")
        else:
            response_text = "暂无法获取板块轮动数据，请稍后重试或前往「板块分析」页面查看。"
            modules_used.append("unavailable")

    elif intent == "smart_pick":
        response_text = ("自然语言条件选股已下线。\n\n"
                         "请在「AI 助手」中直接描述您的选股条件（由大模型完成分析与筛选），"
                         "或前往「策略中心」使用多因子、低吸、资金流向等内置选股策略。")
        modules_used.append("guide")

    elif intent == "dragon_list":
        output = _run_skill("dragon-list/dragon_list.py", ["today"])
        if output.strip() and len(output) > MIN_DRAGON_LEN:
            response_text = output
            modules_used.append("dragon-list")
        else:
            response_text = "暂无法获取龙虎榜数据，请稍后重试或前往「龙虎榜」页面查看。"
            modules_used.append("unavailable")

    elif intent == "news_search":
        query = intent_result["entities"].get("query", request.message)
        from app.services.news_service import search_news, news_to_text
        ak_items = search_news(query, top_n=15)
        if ak_items:
            response_text = news_to_text(ak_items)
            modules_used.append("news-service")
        else:
            cache_result = _search_cache(query)
            if cache_result:
                response_text = cache_result["data"]
                modules_used.append("cache")
            else:
                response_text = f"暂无法获取「{query}」相关资讯，请稍后重试或前往「资讯」页面查看。"
                modules_used.append("unavailable")

    else:
        response_text = f"收到您的问题：{request.message}\n\n我可以帮您分析股票走势、选股策略、龙虎榜数据和市场资讯。请尝试更具体的问题，例如'贵州茅台怎么样'或'今天大盘走势如何'。"
        modules_used.append("general")

    return ChatResponse(
        intent=intent,
        confidence=intent_result["confidence"],
        entities=intent_result.get("entities", {}),
        response=response_text,
        modules_used=modules_used
    )


_NEWS_CACHE_TTL = 600  # 资讯磁盘缓存10分钟过期

@router.get("/nlp/news-cache")
async def get_news_cache(
    days: int = Query(3, ge=1, le=30),
    date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """获取本地缓存的资讯数据，date指定日期则只返回该日"""
    from datetime import timedelta
    import time as _time

    results = []
    if not os.path.exists(NEWS_DATA_DIR):
        return {"news": [], "days": days}

    if date:
        data_file = os.path.join(NEWS_DATA_DIR, f"news_{date}.json")
        if os.path.exists(data_file):
            try:
                with open(data_file, 'r', encoding='utf-8') as f:
                    results = json.load(f)
            except Exception:
                pass
        # 过滤研报：研报只在"研报精选"tab展示，避免与今日热点重复
        results = [it for it in results if it.get('source') != '研报']
        return {"news": results, "date": date}

    today = datetime.now()
    results = []
    for i in range(days):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        data_file = os.path.join(NEWS_DATA_DIR, f"news_{date_str}.json")
        if os.path.exists(data_file):
            try:
                with open(data_file, 'r', encoding='utf-8') as f:
                    items = json.load(f)
                for item in items:
                    results.append(item)
            except Exception:
                continue

    # 过滤研报：研报只在"研报精选"tab展示，避免与今日热点重复
    results = [it for it in results if it.get('source') != '研报']

    # 检查今日缓存是否过期，过期则自动刷新
    today_file = os.path.join(NEWS_DATA_DIR, f"news_{today.strftime('%Y-%m-%d')}.json")
    need_refresh = True
    if os.path.exists(today_file):
        try:
            file_mtime = _time.time() - os.path.getmtime(today_file)
            if file_mtime < _NEWS_CACHE_TTL:
                need_refresh = False
        except Exception:
            pass
    else:
        need_refresh = True

    if need_refresh:
        from app.services.news_service import get_all_news, get_all_research
        all_items = get_all_news(top_n=50)
        if all_items:
            _save_news_items(all_items, 'auto-refresh')
        research_items = get_all_research(top_n=30)
        if research_items:
            _save_research_items(research_items)

        # 重新加载刷新后的数据
        results = []
        for i in range(days):
            date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            data_file = os.path.join(NEWS_DATA_DIR, f"news_{date_str}.json")
            if os.path.exists(data_file):
                try:
                    with open(data_file, 'r', encoding='utf-8') as f:
                        items = json.load(f)
                    for item in items:
                        results.append(item)
                except Exception:
                    continue

    return {"news": results, "days": days}


@router.get("/nlp/intent")
async def classify_intent(
    query: str = Query(..., description="自然语言查询"),
    current_user: User = Depends(get_current_user),
):
    """仅识别意图（不执行分析）"""
    return _classify_intent(query)


def _search_cache(query: str) -> Optional[dict]:
    """从缓存中搜索相关新闻"""
    from datetime import timedelta
    all_items = []
    for i in range(7):
        date_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        data_file = os.path.join(NEWS_DATA_DIR, f"news_{date_str}.json")
        if os.path.exists(data_file):
            try:
                with open(data_file, 'r', encoding='utf-8') as f:
                    all_items.extend(json.load(f))
            except Exception:
                pass

    if not all_items:
        return None

    # 按时间倒序排列（最新的在前）
    all_items.sort(key=lambda x: x.get('savedAt', ''), reverse=True)

    q = query.lower()
    keywords = [kw for kw in q.split() if len(kw) >= 2]

    matched = []
    if keywords:
        # 先用关键词匹配
        for item in all_items:
            text = (item.get('title', '') + ' ' + item.get('content', '')).lower()
            if any(kw in text for kw in keywords):
                matched.append(item)

        # 如果关键词没匹配到，用查询字符串中的常见子串再试
        if not matched and len(q) >= 2:
            sub_keywords = [q[i:i+3] for i in range(len(q)) if len(q[i:i+3]) >= 2]
            for item in all_items:
                text = (item.get('title', '') + ' ' + item.get('content', '')).lower()
                if any(kw in text for kw in sub_keywords):
                    matched.append(item)

    # 还是没有匹配到，返回全部最新数据
    if not matched:
        matched = all_items

    lines = [f"资讯查询: 共找到 {len(matched)} 条相关资讯:\n"]
    for idx, item in enumerate(matched[:15], 1):
        title = item.get("title", "")
        date = item.get("date", "")
        source = item.get("source", "资讯")
        org = item.get("org", "")
        content = item.get("content", "")
        lines.append(f"--- {idx}. {title}")
        meta = []
        if org:
            meta.append(f"机构: {org}")
        if date:
            meta.append(f"日期: {date}")
        meta.append(f"类型: {source}")
        if meta:
            lines.append(" | ".join(meta))
        if content:
            lines.append("")
            lines.append(content[:500])
        lines.append("")

    return {"type": "news", "data": "\n".join(lines)}


@router.get("/nlp/smart-search")
async def smart_search(
    query: str = Query(..., description="自然语言搜索"),
    current_user: User = Depends(get_current_user),
):
    """智能搜索 - 实时资讯接口优先，磁盘缓存兜底"""
    log.info("[smart-search] 收到查询: %s", query)
    q = query.lower()

    if any(kw in q for kw in ["新闻", "公告", "研报", "消息"]):
        log.info("[smart-search] 匹配 news 分支")
        # akshare 实时搜索优先（更快响应）
        from app.services.news_service import search_news, news_to_text, get_all_news
        ak_items = search_news(query, top_n=15)
        if ak_items:
            _save_news_items(ak_items, query)
            text = news_to_text(ak_items)
            return {"type": "news", "data": text}

        # 再尝试缓存
        cache_result = _search_cache(query)
        if cache_result:
            return cache_result
        return {"type": "news", "data": f"资讯查询: {query}\n\n--- 1. 暂无实时数据"}

    elif any(kw in q for kw in ["选", "筛选", "条件", "涨幅", "市盈率"]):
        return {"type": "stock_selection", "data": "自然语言条件选股已下线。\n\n请在「AI 助手」中直接描述您的选股条件（由大模型完成分析与筛选），或前往「策略中心」使用多因子、低吸、资金流向等内置选股策略。"}

    elif any(kw in q for kw in ["龙虎榜", "游资"]):
        output = _run_skill("dragon-list/dragon_list.py", ["today"])
        if output.strip() and len(output) > MIN_DRAGON_LEN:
            return {"type": "dragon_list", "data": output}
        return {"type": "dragon_list", "data": "暂无法获取龙虎榜数据，请稍后重试或前往「龙虎榜」页面查看。"}

    elif any(kw in q for kw in ["情绪", "大盘", "市场", "上证"]):
        output = _run_skill("market-sentiment/market_sentiment.py", ["--report"])
        if output.strip() and len(output) > MIN_OUTPUT_LEN:
            return {"type": "market", "data": output}
        return {"type": "market", "data": "暂无法获取市场情绪数据，请稍后重试或前往「市场看板」页面查看。"}

    else:
        log.info("[smart-search] 匹配 default 分支")
        # akshare 实时搜索优先
        from app.services.news_service import search_news, news_to_text
        ak_items = search_news(query, top_n=15)
        if ak_items:
            text = news_to_text(ak_items)
            return {"type": "general", "data": text}

        # 再尝试缓存
        cache_result = _search_cache(query)
        if cache_result:
            return cache_result
        return {"type": "general", "data": f"资讯查询: {query}\n\n--- 1. 暂无实时数据"}


@router.get("/nlp/news-live")
async def get_news_live(
    top_n: int = Query(100, ge=30, le=500),  # 增加到500条以覆盖近7天数据
    current_user: User = Depends(get_current_user),
):
    """直接获取实时资讯（akshare），不绕磁盘缓存"""
    from app.services.news_service import get_all_news

    items = get_all_news(top_n=top_n)
    return {"news": items, "count": len(items)}


@router.get("/nlp/research-live")
async def get_research_live(
    top_n: int = Query(100, ge=30, le=500),
    force: int = Query(0, ge=0, le=1),
    current_user: User = Depends(get_current_user),
):
    """直接获取实时研报（东方财富API），不绕磁盘缓存"""
    from app.services.news_service import get_all_research

    items = get_all_research(top_n=top_n, force_refresh=bool(force))
    return {"research": items, "count": len(items)}


@router.get("/nlp/search-live")
async def search_news_live(
    query: str = Query(..., description="搜索关键词"),
    top_n: int = Query(15, ge=5, le=50),
    current_user: User = Depends(get_current_user),
):
    """直接搜索实时资讯（akshare），返回结构化 JSON"""
    from app.services.news_service import search_news

    items = search_news(query, top_n=top_n)
    return {"news": items, "count": len(items), "query": query}


@router.post("/nlp/news-refresh")
async def news_refresh(current_user: User = Depends(get_current_user)):
    """聚合刷新：从多个数据源获取最新新闻并保存到缓存"""
    from app.services.news_service import get_all_news, get_all_research, news_to_text

    # 刷新资讯
    all_items = get_all_news(top_n=50)
    if all_items:
        _save_news_items(all_items, 'refresh')

    # 刷新研报（保存到独立文件，最多90条）
    research_items = get_all_research(top_n=30)
    if research_items:
        _save_research_items(research_items)

    # 返回缓存中最新数据
    cache_result = _search_cache('all')
    if cache_result:
        return cache_result

    if all_items:
        return {"type": "news", "data": news_to_text(all_items)}

    return {"type": "news", "data": ""}


def _save_research_items(items: list[dict], max_keep: int = 90, keep_days: int = 7) -> None:
    """保存研报到独立文件，追加去重 + 淘汰过期数据"""
    os.makedirs(NEWS_DATA_DIR, exist_ok=True)

    data_file = os.path.join(NEWS_DATA_DIR, "research_all.json")
    today = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%H%M%S")

    # 加载已有数据，先淘汰超过 keep_days 的旧研报
    existing = []
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                all_existing = json.load(f)
            cutoff_date = datetime.now() - __import__('datetime').timedelta(days=keep_days)
            for item in all_existing:
                saved_at = item.get('savedAt', '')[:10]
                if saved_at:
                    try:
                        item_date = datetime.strptime(saved_at, "%Y-%m-%d")
                        if item_date >= cutoff_date:
                            existing.append(item)
                    except Exception:
                        existing.append(item)  # 解析失败保留
                else:
                    existing.append(item)  # 没有时间戳的保留
        except Exception:
            existing = []

    existing_titles = {e['title'] for e in existing}
    added = 0
    for item in items:
        if item.get('title') and item['title'] not in existing_titles:
            existing.insert(0, {**item, 'savedAt': f"{today} {timestamp}"})
            existing_titles.add(item['title'])
            added += 1

    # 上限淘汰：只保留最新的 max_keep 条
    if len(existing) > max_keep:
        existing = existing[:max_keep]

    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    if added > 0:
        log.info("[research_save] 新增 %d 条研报，共 %d 条", added, len(existing))


def _load_research_cache() -> list[dict]:
    """加载研报缓存"""
    data_file = os.path.join(NEWS_DATA_DIR, "research_all.json")
    if not os.path.exists(data_file):
        return []
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


_RESEARCH_CACHE_TTL = 600  # 研报磁盘缓存10分钟过期

@router.get("/nlp/research-cache")
async def get_research_cache(
    force: int = 0,
    current_user: User = Depends(get_current_user),
):
    """获取研报缓存，过期时自动刷新（force=1 时强制刷新，跳过所有缓存）"""
    import time as _time
    data_file = os.path.join(NEWS_DATA_DIR, "research_all.json")

    # 检查缓存是否过期：文件不存在或超过TTL
    need_refresh = bool(force)
    if not need_refresh and os.path.exists(data_file):
        try:
            file_mtime = _time.time() - os.path.getmtime(data_file)
            if file_mtime < _RESEARCH_CACHE_TTL:
                need_refresh = False
        except Exception:
            pass

    # 缓存过期或强制刷新：从 akshare 拉取最新研报
    if need_refresh:
        from app.services.news_service import get_all_research
        latest_items = get_all_research(top_n=30, force_refresh=bool(force))
        if latest_items:
            _save_research_items(latest_items)
        elif force:
            # 强制刷新时如果拉取失败，更新一下 mtime 以避免下次又走分支
            try:
                if os.path.exists(data_file):
                    os.utime(data_file, None)
            except Exception:
                pass

    items = _load_research_cache()
    return {"research": items, "count": len(items), "forced": bool(force)}

