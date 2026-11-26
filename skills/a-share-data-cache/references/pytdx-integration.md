# pytdx 通达信行情接口集成记录

## 安装与版本

- **包名**: `pytdx` v1.72
- **安装命令**: `pip install pytdx`
- **导入路径**: `from pytdx.hq import TdxHq_API`（v1.x API）

> ⚠️ 注意：pytdx v0.x 使用 `pytdx.tdxhq_API.TdxHq_API`，v1.x 改为 `pytdx.hq.TdxHq_API`。当前环境为 v1.72。

## pytdx API 速查

### 连接服务器
```python
from pytdx.hq import TdxHq_API
api = TdxHq_API()
api.connect('119.147.212.81', 7709)  # 深圳主力
# api.disconnect()
```

### 通达信公共服务器列表
| IP | 端口 | 说明 |
|----|------|------|
| 119.147.212.81 | 7709 | 深圳-主力（推荐） |
| 14.17.75.50 | 7709 | 上海-主力 |
| 112.74.214.43 | 7727 | 备用1 |
| 218.75.126.9 | 7727 | 备用2 |

### 核心方法

#### get_security_quotes — 实时行情
```python
# market: 0=上海, 1=深圳
quotes = api.get_security_quotes([(0, '600519'), (1, '000001')])
# 返回 list[dict]: code, instrument_name, price, last_close, open_price, high_price, low_price, volume, money, bid1, ask1...
```

#### get_security_bars — 日/周/月K线
```python
# category: 8=日线, 32=周线, 16=月线
bars = api.get_security_bars(8, 0, '600519', start=0, count=100)
# 返回 list[dict]: datetime, open, close, high, low, vol
```

#### get_history_minute_time_data — 分钟K线
```python
# unit: 秒数 (300=5min, 900=15min, 1800=30min, 3600=60min)
data = api.get_history_minute_time_data(0, '600519', unit=300, count=48)
```

#### get_transaction_data — 分笔成交
```python
ticks = api.get_transaction_data(0, '600519', start=0, count=100)
# 返回 list[dict]: time, price, vol, type(买卖方向), money
```

## 集成到 data_cache.py 的关键点

### DataSource 枚举扩展
```python
class DataSource(Enum):
    CACHE = "cache"
    PYTDX = "pytdx"         # ⭐新增，最高优先级备用源
    SINA = "sina"
    TENCENT = "tencent"
    AKSHARE = "akshare"
```

### 调度优先级（SmartDispatcher）
```python
# pytdx → akshare → sina → tencent
self._fallback_order = [DataSource.PYTDX, DataSource.AKSHARE, DataSource.SINA, DataSource.TENCENT]
```

### DataFetcher 新增方法
- `fetch_pytdx_quote(symbols)` — 批量实时行情，每次最多800只
- `fetch_pytdx_kline(symbol, period, count)` — K线（日/周/月+5/15/30/60分钟）
- `fetch_pytdx_transaction(symbol, count)` — Level-1分笔成交

### 服务器自动选择逻辑
`_get_pytdx_api()` classmethod：遍历4个通达信公共节点，选择延迟最低的。连接成功后缓存为类变量 `_PYTDX_API`，后续调用复用同一连接。

## 已知限制与注意事项

1. **非交易时间行情为空** — pytdx实时行情仅在交易日9:15-15:00有数据，历史K线不受影响
2. **连接超时处理** — 服务器不可达时自动标记 `_PYTDX_CONNECTED = False`，下次调用重新尝试
3. **批量限制** — `get_security_quotes` 单次最多800只股票，超过需分批
4. **复权数据** — pytdx返回的是不复权价格，需要前/后复权时需另行计算（可通过 `get_xdxr_info` 获取除权除息信息）

## 性能对比

| 指标 | pytdx | HTTP API (新浪/腾讯) |
|------|-------|---------------------|
| 延迟 | ~30ms (TCP直连) | ~200-500ms (HTTP) |
| 配额限制 | ❌ 无 | ⚠️ 部分有频率限制 |
| 分钟K线 | ✅ 原生支持 | ❌ 大多仅日线 |
| 分笔成交 | ✅ Level-1 | ❌ 不支持 |