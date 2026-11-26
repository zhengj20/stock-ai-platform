"""资讯服务 - 多数据源聚合（Redis + 内存双缓存）"""
import re
import time
import json
import logging
from collections import OrderedDict
import requests
from datetime import datetime, timedelta

from app.core.data_sources import (
    EastMoneyNewsSource, CNInfoSource, EastMoneySource,
    em_get, em_get_datacenter,  # 东财统一限流入口
)
from app.core.cache import cache_get, cache_set, NS_NEWS

logger = logging.getLogger(__name__)

# ── 缓存配置（从常量模块导入）────────────────────────
from app.core.constants import NEWS_CACHE_TTL, RESEARCH_CACHE_TTL, NEWS_RETENTION_DAYS, RESEARCH_RETENTION_DAYS

_MAX_NEWS_CACHE = 500  # 增加到500条以保存更多历史数据
_news_cache = OrderedDict()  # LRU: {key: {'data': list, 'timestamp': float}}
_NEWS_TTL = NEWS_CACHE_TTL        # 资讯10分钟TTL（短期缓存）
_RESEARCH_TTL = RESEARCH_CACHE_TTL    # 研报10分钟TTL（短期缓存）
_NEWS_RETENTION_DAYS = NEWS_RETENTION_DAYS      # 新闻保留7天
_RESEARCH_RETENTION_DAYS = RESEARCH_RETENTION_DAYS  # 研报保留7天

# ── 东方财富研报API（直接调，不走 akshare）────────────────
_EM_REPORT_URL = "https://reportapi.eastmoney.com/report/list"


def _get_news_cache(key: str) -> list[dict] | None:
    """获取缓存：Redis优先 → 内存LRU兜底"""
    # Redis跨worker共享缓存
    redis_data = cache_get(key, NS_NEWS)
    if redis_data:
        return redis_data

    # 进程内热点缓存（加速）
    cached = _news_cache.get(key)
    if not cached:
        return None
    _news_cache.move_to_end(key)
    ttl = _RESEARCH_TTL if key.startswith('research') else _NEWS_TTL
    if time.time() - cached['timestamp'] < ttl:
        return cached['data']
    del _news_cache[key]
    return None


def _set_news_cache(key: str, data: list[dict], ttl=None):
    """设置缓存：写入Redis + 内存LRU"""
    if ttl is None:
        ttl = _RESEARCH_TTL if key.startswith('research') else _NEWS_TTL

    # Redis跨worker共享
    cache_set(key, data, ttl=ttl, namespace=NS_NEWS)

    # 进程内热点缓存（加速）
    while len(_news_cache) >= _MAX_NEWS_CACHE:
        _news_cache.popitem(last=False)
    _news_cache[key] = {'data': data, 'timestamp': time.time()}


def _extract_date_from_url(url: str) -> str:
    """从 URL 中提取日期，如 https://.../2026-06-27/xxx -> 2026-06-27"""
    from datetime import datetime
    m = re.search(r'(\d{4}-\d{1,2}-\d{1,2})', url)
    if m:
        return m.group(1)
    # Fallback to current date when URL has no embedded date
    return datetime.now().strftime('%Y-%m-%d')


def get_sina_finance_news(top_n: int = 20) -> list[dict]:
    """获取新浪财经实时快讯（feed.mix.sina.com.cn，作为备选源）"""
    try:
        r = requests.get(
            "https://feed.mix.sina.com.cn/api/roll/get",
            params={"pageid": "153", "lid": "2516", "k": "", "num": min(top_n, 50), "page": 1},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0"},
            timeout=10,
        )
        data = r.json()
        items = data.get("result", {}).get("data", [])
        result = []
        for it in items[:top_n]:
            title = it.get("title", "")
            intro = it.get("intro", "")
            ctime = it.get("ctime", "")
            date_str = ""
            time_str = ""
            if ctime:
                try:
                    dt = datetime.fromtimestamp(int(ctime))
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
            source = it.get("media_name", "新浪财经")
            content = intro if intro else title
            result.append({
                "title": title,
                "date": date_str,
                "time": time_str,
                "org": source,
                "source": "快讯",
                "content": content,
            })
        return result
    except Exception as e:
        print(f"[news_service] 新浪财经快讯获取失败: {e}")
        return []


def get_eastmoney_global_news(top_n: int = 50) -> list[dict]:
    """获取全球资讯（东财直连 np-weblist，替代 akshare stock_info_global_em）"""
    try:
        import uuid
        url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        params = {
            "client": "web", "biz": "web_724",
            "fastColumn": "102", "sortEnd": "",
            "pageSize": str(top_n),
            "req_trace": str(uuid.uuid4()),
        }
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://kuaixun.eastmoney.com/"}
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        items = []
        for it in (d.get("data") or {}).get("fastNewsList", [])[:top_n]:
            title = it.get("title", "")
            summary = (it.get("summary") or "")[:200]
            show_time = it.get("showTime", "")
            items.append({
                "title": title,
                "date": str(show_time)[:10],
                "time": str(show_time),
                "org": "东方财富",
                "source": "全球资讯",
                "content": summary or title,
            })
        return items
    except Exception as e:
        logger.debug(f"东财全球资讯获取失败: {e}")
        return []


def get_cls_flash_news(top_n: int = 20) -> list[dict]:
    """获取全球财经快讯（东财直连，替代 ak.stock_news_main_cx）"""
    try:
        raw = EastMoneySource.get_global_news(page_size=top_n)
        if not raw:
            return []
        items = []
        for a in raw[:top_n]:
            title = a.get("title", "")
            pub_time = a.get("time", "")
            source = a.get("source", "财经快讯")
            date_str = pub_time[:10] if pub_time and len(pub_time) >= 10 else ""
            items.append({
                'title': title,
                'date': date_str,
                'time': pub_time,
                'org': source or '财经快讯',
                'source': '快讯',
                'content': title,
            })
        return items
    except Exception as e:
        print(f"[news_service] 财联社快讯获取失败: {e}")
        return []


def get_em_market_news(top_n: int = 20) -> list[dict]:
    """获取东方财富市场新闻（直连 search-api-web）"""
    try:
        # 用热门股票代码做关键词搜索，获取市场级新闻
        raw = EastMoneyNewsSource.get_stock_news(code="A股", page_size=top_n)
        if not raw:
            return []
        items = []
        for a in raw[:top_n]:
            title = a.get("title", "")
            pub_time = a.get("time", "")[:16]
            source = a.get("source", "东方财富")
            date_str = pub_time.split(' ')[0] if ' ' in pub_time else ''
            items.append({
                'title': title,
                'date': date_str,
                'time': pub_time,
                'org': source,
                'source': '新闻',
                'content': a.get("content", title),
            })
        return items
    except Exception as e:
        print(f"[news_service] 东方财富新闻获取失败: {e}")
        return []


def get_cctv_news(top_n: int = 10) -> list[dict]:
    """获取重大财经新闻（东财全球资讯，替代 ak.news_cctv）"""
    try:
        raw = EastMoneySource.get_global_news(page_size=top_n * 2)
        if not raw:
            return []
        items = []
        for a in raw[:top_n]:
            title = a.get("title", "")
            pub_time = a.get("time", "")
            source = a.get("source", "财经资讯")
            date_str = pub_time[:10] if pub_time and len(pub_time) >= 10 else ""
            items.append({
                'title': title,
                'date': date_str,
                'time': pub_time,
                'org': source or '财经资讯',
                'source': '新闻',
                'content': title,
            })
        return items
    except Exception as e:
        print(f"[news_service] 央视新闻获取失败: {e}")
        return []


def get_all_news(top_n: int = 30) -> list[dict]:
    """聚合所有数据源，按时间排序（保留最近7天新闻，非交易时段也能展示）

    数据源优先级：
    1. akshare 全球资讯（主源，200条，稳定）
    2. 新浪财经（备选源）
    
    优化：增加获取数量到300条，确保有足够的近7天新闻数据
    """
    cutoff_date = (datetime.now() - timedelta(days=_NEWS_RETENTION_DAYS)).strftime('%Y-%m-%d')

    today_str = datetime.now().strftime('%Y-%m-%d')
    cached = _get_news_cache(f'all_news_{top_n}_{today_str}')
    if cached is not None:
        return cached[:top_n]

    all_items = []
    seen_titles = set()

    # 主数据源：akshare全球资讯 + 新浪财经备选（增加到300条）
    for source_func, max_count in [
        (get_eastmoney_global_news, 200),
        (get_sina_finance_news, 100),
    ]:
        items = source_func(max_count)
        for item in items:
            item_date = item.get('date', '')[:10] if item.get('date') else ''
            if item_date and item_date < cutoff_date:
                continue
            if item['title'] not in seen_titles:
                seen_titles.add(item['title'])
                all_items.append(item)

    all_items.sort(key=lambda x: x.get('time', ''), reverse=True)
    result = all_items[:top_n]
    _set_news_cache(f'all_news_{top_n}_{today_str}', result, ttl=_NEWS_TTL)
    return result


def search_news(query: str, top_n: int = 15) -> list[dict]:
    """搜索新闻：使用东财搜索API获取与查询关键词匹配的新闻
    
    优化：只保留最近7天的新闻数据，过滤过期内容
    """
    cached = _get_news_cache(f'search_{query}_{top_n}')
    if cached is not None:
        return cached[:top_n]

    # 判断是否为股票代码
    is_stock_code = len(query) == 6 and query.isdigit()

    # 统一解析：代码→名称，中文名称→代码（用于巨潮公告查询+相关性匹配）
    stock_name = ""
    resolved_code = None
    try:
        from app.core.pytdx_source import FullMarketCache
        all_stocks = FullMarketCache.get_all_stocks()
        if is_stock_code:
            # 代码→名称（先查缓存，再查全量列表）
            cache_key = f'stock_name_{query}'
            cached_name = _get_news_cache(cache_key)
            if cached_name:
                stock_name = cached_name[0] if isinstance(cached_name, list) else str(cached_name)
                resolved_code = query
            else:
                for s in all_stocks:
                    if s['code'] == query:
                        stock_name = s['name']
                        resolved_code = query
                        _set_news_cache(cache_key, stock_name, ttl=86400 * 7)
                        break
        else:
            # 中文名称→代码（同时把查询词本身作为stock_name用于匹配）
            import unicodedata
            def _norm(s):
                return unicodedata.normalize('NFKC', s).replace(' ', '')
            q_norm = _norm(query)
            for s in all_stocks:
                if _norm(s['name']) == q_norm:
                    resolved_code = s['code']
                    stock_name = query
                    cache_key = f'stock_name_{resolved_code}'
                    _set_news_cache(cache_key, stock_name, ttl=86400 * 7)
                    break
    except Exception as e:
        logger.debug(f"解析股票信息失败 ({query}): {e}")

    if is_stock_code and resolved_code is None:
        resolved_code = query
    
    # 计算7天前的日期，用于过滤过期新闻
    cutoff_date = datetime.now() - timedelta(days=_NEWS_RETENTION_DAYS)

    def _is_relevant(title, q):
        """检查标题是否与查询相关

        对于股票代码：必须包含股票名称或代码本身
        对于中文名称：检查是否包含公司名称或简称即可（API已做相关性匹配）
        """
        if not title or not q:
            return False

        # 股票代码查询：必须包含股票名称或代码，确保新闻确实与该股票相关
        if is_stock_code:
            # 优先检查股票名称（最精确）
            if stock_name and stock_name in title:
                return True
            # 检查代码本身
            if q in title:
                return True
            return False

        # 中文名称：完整名称或3字符切片（避免2字符太宽泛）
        if q in title:
            return True
        if len(q) >= 4:
            for i in range(len(q) - 2):
                if q[i:i+3] in title:
                    return True

        # 如果获取到了股票名称，也检查股票名称匹配
        if stock_name and stock_name != q and stock_name in title:
            return True

        return False

    def _is_recent(date_str):
        """检查新闻日期是否在最近7天内"""
        if not date_str:
            return True  # 无日期的新闻默认保留
        try:
            # 尝试解析多种日期格式
            for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y%m%d'):
                try:
                    news_date = datetime.strptime(date_str[:10], fmt)
                    return news_date >= cutoff_date
                except ValueError:
                    continue
            return True  # 无法解析的日期默认保留
        except Exception:
            return True

    # 数据源优先级：巨潮公告（专属） > 东财搜索（质量差，仅作补充） > 全局缓存匹配

    # 优先获取巨潮公告（高质量、专属该股票）
    cn_announcements = []
    if resolved_code:
        try:
            cn_announcements = CNInfoSource.get_announcements(code=resolved_code, page_size=top_n) or []
        except Exception as e:
            logger.debug(f"巨潮公告获取失败 ({query}): {e}")

    # 东财搜索API（质量不稳定，仅作补充）
    try:
        em_items = EastMoneyNewsSource.get_stock_news(code=query, page_size=top_n * 2)
    except Exception as e:
        logger.debug(f"东财搜索API失败 ({query}): {e}")
        em_items = []

    logger.info(f"search_news({query}): cn_announcements={len(cn_announcements or [])}条, em_items={len(em_items or [])}条")
    
    # 优先级1：处理巨潮公告结果（专属该股票，不做日期限制）
    result = []
    if cn_announcements:
        for a in (cn_announcements or [])[:top_n]:
            title = a.get("title", "")
            if not title:
                continue
            raw_date = a.get("date", "")
            if raw_date:
                try:
                    ts = int(raw_date)
                    from datetime import datetime as dt
                    date_str = dt.fromtimestamp(ts / 1000 if ts > 9999999999 else ts).strftime('%Y-%m-%d')
                except (ValueError, OSError):
                    date_str = str(raw_date)[:10]
            else:
                date_str = ""
            
            result.append({
                "title": title[:100],
                "date": date_str,
                "source": "巨潮资讯",
                "content": "",
            })

    # 优先级2：处理东财搜索结果（需要相关性+日期过滤）
    if len(result) < top_n and em_items:
        remaining = top_n - len(result)
        for it in (em_items or [])[:remaining * 2]:
            title = it.get("title", "")
            date_str = it.get("time", "")[:10] if it.get("time") else ""
            
            # 检查相关性
            if not _is_relevant(title, query):
                continue
            
            # 检查日期（只保留最近7天）
            if not _is_recent(date_str):
                continue
                
            result.append({
                "title": title,
                "date": date_str,
                "time": it.get("time", ""),
                "org": it.get("source", "东方财富"),
                "source": it.get("source", "新闻"),
                "content": it.get("content", it.get("title", "")),
            })
            if len(result) >= top_n:
                break
    
    if result:
        _set_news_cache(f'search_{query}_{top_n}', result[:top_n])
        logger.info(f"搜索成功 ({query}): {len(result)}条 (公告{len(cn_announcements or [])} 东财{len(em_items or [])})")
        return result[:top_n]

    # 方案3: 从本地缓存中匹配关键词（只返回真正相关的结果）
    all_items = get_all_news(100)

    if is_stock_code:
        keywords = [query]  # 股票代码直接作为整体匹配
    else:
        # 中文：优先用完整查询词，再用3字符切片（避免2字符太宽泛导致不相关匹配）
        keywords = [query]  # 完整名称必须匹配
        if len(query) >= 4:
            keywords.extend([query[i:i+3] for i in range(len(query) - 2)])

    matched = []
    for item in all_items:
        # 检查日期（只保留最近7天）
        date_str = item.get('date', '') or ''
        if not _is_recent(date_str):
            continue
            
        text = (item.get('title', '') + ' ' + item.get('content', ''))
        is_match = any(kw in text for kw in keywords)
        if is_match:
            matched.append(item)

    # 只返回匹配到的结果，不匹配的绝不返回（避免无关新闻）
    final = matched[:top_n]
    _set_news_cache(f'search_{query}_{top_n}', final)
    logger.info(f"新闻搜索 ({query}): {len(final)}条 (从全局缓存匹配{len(matched)})")
    return final


def news_to_text(items: list[dict]) -> str:
    """将新闻列表转为格式化文本"""
    if not items:
        return ""

    lines = [f"资讯查询: 共找到 {len(items)} 条相关资讯:\n"]
    for idx, item in enumerate(items, 1):
        title = item.get('title', '')
        date = item.get('date', '')
        source = item.get('source', '资讯')
        org = item.get('org', '')
        content = item.get('content', '')

        lines.append(f"--- {idx}. {title}")
        meta = []
        if org:
            meta.append(f"机构: {org}")
        if date:
            meta.append(f"日期: {date}")
        meta.append(f"类型: {source}")
        if meta:
            lines.append(" | ".join(meta))
        if content and content != title:
            lines.append("")
            lines.append(content[:500])
        lines.append("")

    return "\n".join(lines)


def _fetch_global_research(page_size: int = 100) -> list[dict]:
    """直接调东方财富"全市场最新研报"接口（带 beginTime 过滤近7天）

    返回字段: title/stockName/stockCode/orgSName/publishDate/emRatingName/indvAimPriceT
    """
    try:
        # 拉近7天研报，endTime+1天确保包含今天的数据
        end_dt = datetime.now() + timedelta(days=1)
        begin_dt = datetime.now() - timedelta(days=7)
        params = {
            "industryCode": "*",
            "pageSize": str(page_size),
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": begin_dt.strftime("%Y-%m-%d"),
            "endTime": end_dt.strftime("%Y-%m-%d"),
            "pageNo": "1",
            "fields": "",
            "qType": "0",
            "orgCode": "",
            "rcode": "",
            "p": "1",
            "pageNum": "1",
            "pageNumber": "1",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://data.eastmoney.com/",
        }
        r = em_get(_EM_REPORT_URL, params=params, headers=headers, timeout=8)
        data = r.json()
        items = []
        for it in data.get("data") or []:
            title = it.get("title") or ""
            stock_code = str(it.get("stockCode") or "").zfill(6)
            stock_name = it.get("stockName") or ""
            org = it.get("orgSName") or it.get("orgName") or ""
            pub = it.get("publishDate") or ""
            date_str = pub[:10]  # "2026-06-29 00:00:00.000" -> "2026-06-29"
            rating = it.get("emRatingName") or "研报"
            aim = it.get("indvAimPriceT") or it.get("indvAimPriceL") or ""
            full_title = f"{stock_code} {stock_name}: {title}".strip(": ")
            content = f"[{org}] {title}"
            if aim:
                content += f" 目标价: {aim}"
            items.append({
                "title": full_title,
                "date": date_str,
                "time": date_str,
                "org": org,
                "source": rating or "研报",
                "content": content,
            })
        return items
    except Exception as e:
        print(f"[news_service] 东方财富全市场研报拉取失败: {e}")
        return []


def _is_nan(v) -> bool:
    """检查值是否为空/NaN"""
    s = str(v).strip().lower()
    return s in ('', 'nan', 'none', 'null')


def get_research_reports(top_n: int = 30, force_refresh: bool = False) -> list[dict]:
    """从东方财富直接拉全市场最新研报，按发布日期倒序

    不再走热门股池循环（akshare 按个股查返回的是旧数据）。
    
    优化：增加获取数量到200条，缓存10分钟
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    cache_key = f'research_pool_{top_n}_{today_str}'
    if not force_refresh:
        cached = _get_news_cache(cache_key)
        if cached is not None:
            return cached[:top_n]

    # 一次拉 200 条足够覆盖近 7 天的活跃研报（增加到200条）
    all_items = _fetch_global_research(page_size=min(top_n * 2, 300))

    # 按发布日期倒序
    all_items.sort(key=lambda x: x.get('time', ''), reverse=True)
    result = all_items[:top_n]
    _set_news_cache(cache_key, result, ttl=_RESEARCH_TTL)  # 短期缓存10分钟，保证数据新鲜
    return result


def get_stock_notices(top_n: int = 20) -> list[dict]:
    """获取最新公告（东财 datacenter，替代 ak.stock_notice_report）"""
    try:
        r = em_get_datacenter("https://datacenter-web.eastmoney.com/api/data/v1/get", params={
            "reportName": "RPT_PUBLIC_GO_announcement",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,ANN_TITLE,ANN_DATE,WEB_PAGE_URL,NOTICE_TYPE",
            "pageSize": top_n, "sortColumns": "ANN_DATE", "sortTypes": "-1"
        }, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.eastmoney.com/"
        }, timeout=8)
        data = r.json().get("result", {}).get("data", []) or []
        items = []
        for d in data[:top_n]:
            stock_code = str(d.get("SECURITY_CODE", ""))
            stock_name = d.get("SECURITY_NAME_ABBR", "")
            title = d.get("ANN_TITLE", "")
            notice_type = d.get("NOTICE_TYPE", "公告") or "公告"
            date_str = str(d.get("ANN_DATE", ""))[:10]
            url = d.get("WEB_PAGE_URL", "")
            items.append({
                'title': f"{stock_code} {stock_name}: {title}",
                'date': date_str,
                'time': date_str,
                'org': stock_name or '',
                'source': notice_type,
                'content': f"[{notice_type}] {title}",
            })
        return items
    except Exception as e:
        print(f"[news_service] 个股公告获取失败: {e}")
        return []


def get_all_research(top_n: int = 30, force_refresh: bool = False) -> list[dict]:
    """聚合所有研报数据源
    
    优化：增加获取数量到200条，缓存10分钟
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    cache_key = f'all_research_{top_n}_{today_str}'
    if not force_refresh:
        cached = _get_news_cache(cache_key)
        if cached is not None:
            return cached[:top_n]

    all_items = []
    seen_titles = set()
    
    # 计算7天前的日期，用于过滤过期研报
    cutoff_date = (datetime.now() - timedelta(days=_RESEARCH_RETENTION_DAYS)).strftime('%Y-%m-%d')

    for source_func, max_count in [
        (get_research_reports, min(top_n * 2, 300)),  # 增加到top_n的2倍，最多300条
    ]:
        items = source_func(max_count, force_refresh=force_refresh)
        for item in items:
            # 过滤过期研报（只保留近7天）
            item_date = item.get('date', '')[:10] if item.get('date') else ''
            if item_date and item_date < cutoff_date:
                continue
                
            if item['title'] not in seen_titles:
                seen_titles.add(item['title'])
                all_items.append(item)

    all_items.sort(key=lambda x: x.get('time', ''), reverse=True)
    result = all_items[:top_n]
    _set_news_cache(cache_key, result, ttl=_RESEARCH_TTL)  # 短期缓存10分钟
    return result


def get_all_notices(top_n: int = 20) -> list[dict]:
    """聚合所有公告数据源"""
    all_items = []
    seen_titles = set()

    for source_func, max_count in [
        (get_stock_notices, top_n),
    ]:
        items = source_func(max_count)
        for item in items:
            if item['title'] not in seen_titles:
                seen_titles.add(item['title'])
                all_items.append(item)

    all_items.sort(key=lambda x: x.get('time', ''), reverse=True)
    return all_items[:top_n]


