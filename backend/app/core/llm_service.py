"""LLM服务 - 连接本地LM Studio模型(OpenAI兼容API)"""
import asyncio
import json
import os
import logging
from typing import Optional, AsyncGenerator
import httpx

log = logging.getLogger(__name__)

# 配置文件放在项目 data/ 目录（运行时生成，已被 .gitignore 排除）
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "data", "llm_config.json")

# 共享的HTTP客户端，避免连接泄漏
# 注：httpx.AsyncClient 与创建时的 event loop 绑定。ai_strategy_generator 等同步上下文
# 每次 asyncio.run() 都会创建新 loop，因此必须在 loop 切换时强制重建 client，
# 否则会出现 "Event loop is closed" 异常。
# 不用 asyncio.Lock：因为 _asyncio.run() 创建的新 event loop 无法使用原 loop 的锁
_shared_client: Optional[httpx.AsyncClient] = None
_shared_client_loop: Optional[asyncio.AbstractEventLoop] = None


class LLMConfig:
    """LLM配置 - 持久化到JSON文件"""
    def __init__(self):
        self.base_url = "http://localhost:1234/v1"
        self.model = ""
        self.temperature = 0.7
        self.max_tokens = 16384
        self.enabled = False
        self.provider = "custom"
        self._load()

    def _load(self):
        """从文件加载配置"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.base_url = data.get("base_url", self.base_url)
                self.model = data.get("model", self.model)
                self.temperature = data.get("temperature", self.temperature)
                self.max_tokens = data.get("max_tokens", self.max_tokens)
                self.enabled = data.get("enabled", False)
                self.provider = data.get("provider", "custom")
                log.info("[LLM] Config loaded from %s: enabled=%s, model=%s, provider=%s", CONFIG_FILE, self.enabled, self.model, self.provider)
        except Exception as e:
            log.error("[LLM] Failed to load config: %s", e)

    def save(self):
        """保存配置到文件，失败时抛出异常"""
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            log.info("[LLM] Config saved to %s", CONFIG_FILE)
        except Exception as e:
            log.error("[LLM] Failed to save config: %s", e)
            raise RuntimeError(f"配置保存失败: {e}") from e

    def to_dict(self):
        return {
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "enabled": self.enabled,
            "provider": self.provider,
        }


# 全局配置实例
llm_config = LLMConfig()

# httpx超时配置：connect=连接超时, read=读取超时(关键), write=写入超时, pool=连接池超时
# read=540s：定时任务总超时 600s，保留 60s 余量让 httpx 先超时（线程可干净退出）
LLM_TIMEOUT = httpx.Timeout(connect=15.0, read=540.0, write=60.0, pool=10.0)


async def get_shared_client() -> httpx.AsyncClient:
    """获取共享的httpx客户端，避免连接泄漏

    自动检测 event loop 切换：若当前 loop 与 client 绑定的 loop 不同，
    则关闭旧 client 并创建新 client（防止 "Event loop is closed"）。

    不使 asyncio.Lock 做并发保护（不同 event loop 无法共享锁），
    asyncio 单线程特性确保同一 loop 内不会真正并发。
    """
    global _shared_client, _shared_client_loop
    current_loop = asyncio.get_running_loop()

    # 同一 event loop + 客户端正常 → 直接复用
    if _shared_client is not None and not _shared_client.is_closed and _shared_client_loop is current_loop:
        return _shared_client

    # event loop 切换或客户端已关闭 → 建新客户端，旧客户端异步关闭
    old_client = _shared_client
    _shared_client = httpx.AsyncClient(timeout=LLM_TIMEOUT)
    _shared_client_loop = current_loop

    if old_client is not None and not old_client.is_closed:
        try:
            await old_client.aclose()
        except Exception:
            pass

    return _shared_client


class LMStudioClient:
    """LM Studio客户端(OpenAI兼容)"""

    def __init__(self, config: LLMConfig):
        self.config = config

    async def check_connection(self) -> dict:
        """检查连接状态"""
        try:
            client = await get_shared_client()
            resp = await client.get(f"{self.config.base_url}/models")
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    return {"connected": False, "error": "响应不是有效JSON", "models": []}
                models = [m['id'] for m in data.get('data', [])]
                return {
                    "connected": True,
                    "models": models,
                    "default_model": models[0] if models else "",
                }
            return {"connected": False, "error": f"HTTP {resp.status_code}", "models": []}
        except Exception as e:
            return {"connected": False, "error": str(e), "models": []}

    async def warm_up(self) -> bool:
        """预热模型：发送最小请求确保模型已加载到GPU

        LM Studio 会将空闲模型从GPU卸载，首次请求需重新加载（可能耗时30-60秒）。
        在交易日开盘前或定时任务执行前调用，避免正式请求超时。

        Returns:
            bool: True=模型已就绪, False=预热失败（服务不可用或模型未配置）
        """
        if not self.config.enabled or not self.config.model:
            return False
        try:
            log.info("[LLM] 预热模型: %s", self.config.model)
            client = await get_shared_client()
            url = f"{self.config.base_url}/chat/completions"
            payload = {
                "model": self.config.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
                "temperature": 0,
            }
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            log.info("[LLM] 模型预热成功: %s", self.config.model)
            return True
        except Exception as e:
            log.warning("[LLM] 模型预热失败: %s", e)
            return False

    async def chat_completion(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
    ):
        """聊天补全 - 支持工具调用和流式输出"""
        if not self.config.enabled:
            raise RuntimeError("LLM服务未启用，请先在设置中配置LM Studio连接")

        url = f"{self.config.base_url}/chat/completions"
        model = self.config.model or ""

        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        log.info("[LLM] Request: url=%s, model=%s, tools=%s, stream=%s",
                 url, model, bool(tools), stream)

        if stream:
            return self._stream_generator(url, payload)
        else:
            MAX_RETRIES = 2
            for attempt in range(1, MAX_RETRIES + 2):
                try:
                    client = await get_shared_client()
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data['choices'][0]
                    msg = choice.get('message', {})
                    content = msg.get('content', '') or ''
                    reasoning = msg.get('reasoning_content', '') or ''
                    # 优先使用 content（实际回复），reasoning_content 仅作参考
                    if content:
                        full_content = content
                    else:
                        full_content = reasoning

                    if 'tool_calls' in msg:
                        return {
                            "role": "assistant",
                            "content": full_content,
                            "tool_calls": msg['tool_calls'],
                        }

                    return {
                        "role": "assistant",
                        "content": full_content,
                        "tool_calls": None,
                    }
                except httpx.ConnectError as e:
                    if attempt <= MAX_RETRIES:
                        delay = 2 ** attempt
                        log.warning(f"[LLM] 连接失败，{delay}s 后重试 ({attempt}/{MAX_RETRIES}): {e}")
                        await asyncio.sleep(delay)
                        continue
                    raise RuntimeError(f"无法连接到 LM Studio ({self.config.base_url})，已重试 {MAX_RETRIES} 次") from e
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt <= MAX_RETRIES:
                        delay = 5
                        log.warning(f"[LLM] 限流 429，{delay}s 后重试 ({attempt}/{MAX_RETRIES})")
                        await asyncio.sleep(delay)
                        continue
                    detail = e.response.text[:200] if hasattr(e, 'response') and e.response else ''
                    raise RuntimeError(f"LM Studio 返回错误 HTTP {e.response.status_code}: {detail}") from e
                except httpx.TimeoutException as e:
                    raise RuntimeError(f"LM Studio 请求超时（{self.config.base_url}），模型可能加载过大或服务器负载过高") from e
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    raise RuntimeError(f"LLM 返回内容为空或格式异常，prompt 可能过大导致服务端处理失败: {e}") from e

    async def stream_chat_completion(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        """直接返回异步生成器（不经过 async def return 包装）"""
        url = f"{self.config.base_url}/chat/completions"
        model = self.config.model or ""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": True,
        }
        async for chunk in self._stream_generator(url, payload):
            yield chunk

    async def _stream_generator(self, url: str, payload: dict) -> AsyncGenerator[str, None]:
        """流式响应 - 使用共享客户端 + 单行超时保护（防 LLM 长推理卡住）"""
        payload["stream"] = True
        STREAM_LINE_TIMEOUT = 180.0  # 任意单行无数据超过此秒数即中断
        chunk_counter = 0
        try:
            client = await get_shared_client()
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                aiter = resp.aiter_lines()

                while True:
                    try:
                        # 单行超时：若 LLM 长时间无输出则强制中断
                        line = await asyncio.wait_for(aiter.__anext__(), timeout=STREAM_LINE_TIMEOUT)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        log.error("[LLM-Stream] Timeout after %ds without data (received %d chunks)",
                                  STREAM_LINE_TIMEOUT, chunk_counter)
                        break

                    if not line.startswith('data: '):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == '[DONE]':
                        log.info("[LLM-Stream] Received [DONE] (total %d chunks)", chunk_counter)
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk['choices'][0].get('delta', {})

                        if delta.get('tool_calls'):
                            yield json.dumps({"tool_call": delta['tool_calls']})
                            continue

                        # Qwen 模型会分别返回 reasoning_content（思维链）和 content（最终回答）
                        # 只取 content，丢弃 reasoning_content —— 这是防止思维链泄露的最有效方式
                        reasoning = delta.get('reasoning_content', '')
                        content = delta.get('content', '')

                        if reasoning:
                            log.debug("[LLM-Stream] Reasoning (discarded): %s", reasoning[:50])

                        if content:
                            chunk_counter += 1
                            if chunk_counter <= 3 or chunk_counter % 20 == 0:
                                log.debug("[LLM-Stream] Content #%d: %s", chunk_counter, content[:50])
                            yield content
                    except (json.JSONDecodeError, KeyError):
                        continue
        except httpx.ConnectError as e:
            raise RuntimeError(f"无法连接到 LM Studio ({self.config.base_url})，请确认服务已启动") from e
        except httpx.TimeoutException as e:
            raise RuntimeError(f"LM Studio 流式响应超时（{self.config.base_url}），模型可能加载过大或服务器负载过高") from e
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:200] if hasattr(e, 'response') and e.response else ''
            raise RuntimeError(f"LM Studio 返回错误 HTTP {e.response.status_code}: {detail}") from e


# 全局客户端实例
llm_client = LMStudioClient(llm_config)