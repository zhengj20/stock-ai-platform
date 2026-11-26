# v2.0 缓存层移除 — 迁移记录与兼容性修复

## 背景

v1.0 `a-share-data-cache` 包含 SQLite 缓存层（CacheManager + TTL策略 + 配额追踪器）。集成 pytdx 后，pytdx TCP直连 ~30ms + 无限制使缓存价值消失。用户决定**完全移除缓存层**。

## v2.0 变更摘要

| 项目 | v1.0 | v2.0 |
|------|------|------|
| data_cache.py | 65KB / 1571行 | **29KB / 742行**（-80%） |
| CacheManager类 | ✅ SQLite缓存引擎 | ❌ 已删除 |
| TTL策略 | quote=2h, kline=2h, finance=3d | ❌ 已删除 |
| SmartDispatcher构造 | `SmartDispatcher(CacheManager())` | **`SmartDispatcher()`**（无参） |
| DataFetcher构造 | `DataFetcher(cache)` | **`DataFetcher()`**（无参） |

## ⚠️ 下游模块兼容性修复记录

移除 CacheManager 后，以下模块出现导入断裂：

### 1. a-share-visualization (第83行)
```python
# ❌ v1.0:
from data_cache import CacheManager, SmartDispatcher
return SmartDispatcher(CacheManager())

# ✅ v2.0:
from data_cache import SmartDispatcher
return SmartDispatcher()
```

### 2. a-share-daily-report (第154行 + 第265行)
```python
# ❌ v1.0:
from data_cache import SmartDispatcher, CacheManager
self.dispatcher = SmartDispatcher()
self.cache = self.dispatcher.cache          # ← 断裂点1

fetcher = DataFetcher(self.cache)           # ← 断裂点2

# ✅ v2.0:
from data_cache import SmartDispatcher
self.dispatcher = SmartDispatcher()

fetcher = DataFetcher()
```

### 3. SKILL.md 文档同步更新
以下 Skills 的 SKILL.md 引用了旧缓存架构，已全部修正：
- `a-share-analysis-toolkit` — 调度链描述、data-cache模块说明、RSI bug状态
- `a-share-visualization` — 数据源说明（移除"本地缓存"层级）
- `a-share-daily-report` — 五级调度描述（移除SQLite缓存层）

## RSI calc_rsi() Bug修复记录

### Bug 1: `'int' object is not iterable`
**根因**: 函数签名 `periods: List[int]`，但调用方传了单个 int。
**修复**: 改为 `Union[int, List[int]]` + `isinstance(periods, int)` 自动转换。

### Bug 2: 全涨序列 RSI=50（应为100）
**根因**: `loss=0` → replace成nan → fillna(50) 掩盖了正确值。
**修复**: `np.where(loss==0, 100.0, 100 - 100/(1+rs))` 正确处理边界。

## 数据源依赖（2026-11 更新）

原依赖付费 API 的模块（tech-indicators / market-sentiment / multi-strategy / kline-patterns / multi-factor / ml-stock-picker / sector-rotation / nlp-analyzer 等）已全部改用免费公开接口（东方财富数据中心直连 / pytdx / 新浪 / 腾讯），原 6 个付费数据类技能（行情查询 / 资讯搜索 / 条件选股 / 自选管理 / 模拟组合 / 社区运营）已整体下线删除。

## 教训

1. **移除公共类前必须扫描所有引用** — `grep -rn "CacheManager" skills/` 可快速定位
2. **SKILL.md 文档与代码同步更新** — 缓存架构变更后，5个Skills的文档都需要同步修正
3. **heredoc中测试跨目录模块导入会假阴性** — `$HOME`在bash heredoc中展开为MSYS路径，Python Path无法识别；需用 `os.path.expanduser('~')` 或真实文件路径
