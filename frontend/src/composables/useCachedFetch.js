import { ref, isRef, onMounted, onBeforeUnmount, onActivated, onDeactivated, watch, nextTick } from 'vue'
import { readCache, readStaleCache, writeCache, clearCache, clearAllCache } from './useIndexedDB'
import { isTradingHours } from '@/utils/tradingTime'
import { useTradingDateStore } from '@/stores'

/**
 * 分级缓存 TTL + 刷新间隔（毫秒）
 */
export const CACHE_TIERS = {
  REALTIME: { storageTTL: 55 * 1000, refreshInterval: 25 * 1000 },
  MARKET:   { storageTTL: 4 * 60 * 1000, refreshInterval: 4 * 60 * 1000 },
  STOCK:    { storageTTL: 9 * 60 * 1000, refreshInterval: 9 * 60 * 1000 },
  STRATEGY: { storageTTL: 2 * 60 * 60 * 1000, refreshInterval: 4 * 60 * 1000 },
  REPORT:   { storageTTL: 3 * 60 * 60 * 1000, refreshInterval: 9 * 60 * 1000 },
  LIST:     { storageTTL: 3 * 60 * 60 * 1000, refreshInterval: 4 * 60 * 1000 },
  USER:     { storageTTL: 4 * 60 * 1000, refreshInterval: 4 * 60 * 1000 },
}

// 全局并发限制：同一时刻最多 16 个缓存请求在飞（HTTP/2 多路复用无瓶颈）
const MAX_CONCURRENT_FETCHES = 16
let activeFetchCount = 0
const fetchWaitQueue = []

// 全局 in-flight 请求去重：相同 key 的并发请求共享同一个 Promise
const _inflightPromises = new Map()

function acquireFetchSlot() {
  return new Promise((resolve) => {
    const tryAcquire = () => {
      if (activeFetchCount < MAX_CONCURRENT_FETCHES) {
        activeFetchCount++
        resolve()
      } else {
        fetchWaitQueue.push(tryAcquire)
      }
    }
    tryAcquire()
  })
}

function releaseFetchSlot() {
  activeFetchCount = Math.max(0, activeFetchCount - 1)
  // 释放所有等待中的回调，避免死锁
  while (fetchWaitQueue.length > 0 && activeFetchCount < MAX_CONCURRENT_FETCHES) {
    const next = fetchWaitQueue.shift()
    if (next) {
      activeFetchCount++
      next()
    }
  }
}

/**
 * 带去重的请求执行：相同 key 的并发请求只发一次，其余共享结果。
 * 配合 acquireFetchSlot 使用：只在真正发起请求时占槽位。
 */
function dedupFetch(key, fetcher) {
  if (_inflightPromises.has(key)) {
    return _inflightPromises.get(key)
  }

  const promise = acquireFetchSlot()
    .then(() => fetcher())
    .finally(() => {
      releaseFetchSlot()
      _inflightPromises.delete(key)
    })

  _inflightPromises.set(key, promise)
  return promise
}

/**
 * 把 key 配置（字符串/函数/ref）解析成实际 key 字符串
 */
function resolveKey(key) {
  if (typeof key === 'function') return key()
  if (isRef(key)) return key.value
  return key
}

/**
 * SWR 缓存 Hook —— 打开即显示缓存，后台静默刷新
 *
 * 存储层：IndexedDB（500MB+）→ 降级 localStorage
 *
 * 用法：
 *   const { data, loading, refreshing, lastUpdate, refresh } = useCachedFetch({
 *     key: 'market:sentiment',                     // 静态 key
 *     // 或 key: () => `market:sectors:${type}`   // 动态 key (reactive)
 *     fetcher: () => marketApi.getSentiment(),
 *     tier: CACHE_TIERS.MARKET,
 *   })
 *
 * 关键行为：
 *   1. 首次调用 → 异步读取 IndexedDB 缓存（如有），后台静默刷新
 *   2. 无缓存 → 阻塞 fetcher，loading=true
 *   3. 定时器周期性后台静默 refresh（不触发 loading）
 *   4. keep-alive 切走停定时器，切回恢复
 *   5. 失败时保留旧数据，不清空
 *   6. 支持动态 key：key 变化时自动清旧缓存 + 加载新数据
 */
export function useCachedFetch(options) {
  const {
    key,            // 缓存 key（必填，跨页面唯一）支持字符串/函数/ref
    fetcher,        // 异步拉数据函数（应返回 Promise）
    tier = CACHE_TIERS.MARKET,
    immediate = true,   // 立即拉取（false 表示按需手动触发）
    tradingAware = false,   // 是否根据交易时间动态调整刷新频率
    noAutoRefresh = false,  // 禁用自动刷新定时器（由外部统一调度，如聚合接口）
    onSuccess,      // 拉取成功回调（可选，用于 transform）
    onError,        // 拉取失败回调
  } = options

  const data = ref(null)
  const loading = ref(false)        // 首次加载（无缓存时的阻塞态）
  const refreshing = ref(false)     // 后台静默刷新态
  const error = ref(null)
  const lastUpdate = ref(0)         // 上次成功更新时间
  const fromCache = ref(false)      // 当前数据是否来自缓存

  let timer = null
  let inFlight = false
  let mounted = true
  let lastKey = resolveKey(key)
  let currentController = null   // 当前在飞请求的 AbortController（用于组件卸载时取消）
  let closingRefreshed = false   // 收盘后是否已刷新过
  let closingRefreshedDate = ''  // 记录收盘刷新的日期，用于跨日重置
  let consecutiveFailures = 0    // 连续失败次数（用于退避策略）
  let refreshingTimer = null      // refreshing 超时保护定时器


  function doFetch({ silent = false, force = false } = {}) {
    if (inFlight) {
      if (!force) return Promise.resolve()
      // force 模式：中断当前在飞请求，允许新的请求立即发起
      if (currentController) {
        currentController.abort()
        currentController = null
      }
      inFlight = false
    }
    inFlight = true
    // 首次加载（data 为空）时即使用 silent 模式也要设 loading，避免骨架屏闪空状态
    if (silent && data.value != null) {
      refreshing.value = true
    } else {
      loading.value = true
    }
    error.value = null

    const controller = new AbortController()
    currentController = controller

    const dedupKey = resolveKey(key) + (force ? ':force' : '')

    return dedupFetch(dedupKey, () => {
      if (!mounted) {
        controller.abort()
        return Promise.resolve()
      }
      // refreshing 超时保护：30 秒后强制复位（防止后端崩溃时一直卡在 refreshing）
      if (silent) {
        refreshingTimer = setTimeout(() => {
          controller.abort()
          refreshing.value = false
          inFlight = false
          consecutiveFailures++
        }, 30000)
      }
      const result = fetcher({ signal: controller.signal, force: force })
      return Promise.resolve(result)
    })
      .then(async (result) => {
        if (!mounted) return
        const value = result && typeof result === 'object' && 'data' in result ? result.data : result
        // 后端超时/错误响应应走 catch 路径，不写入 data（避免显示全零占位）
        // 后端错误格式: {error: True, error_msg: "...", message: "..."}
        if (value && typeof value === 'object' && value.error) {
          const err = new Error(value.error_msg || value.message || '请求失败')
          err.code = value.code
          err.data = value  // 保留原始错误数据，供调用方读取
          throw err
        }
        if (value !== undefined && value !== null) {
          const transformed = onSuccess ? onSuccess(value) : value
          // onSuccess 返回 null 表示不更新（保留旧缓存）
          if (transformed !== null && transformed !== undefined) {
            await nextTick()
            data.value = transformed
            lastUpdate.value = Date.now()
            fromCache.value = false
            writeCache(resolveKey(key), data.value, tier.storageTTL).catch((e) => console.warn('[useCachedFetch] write 失败:', resolveKey(key), e?.message))
          }
        }
        consecutiveFailures = 0
        return value
      })
      .catch((e) => {
        if (!mounted) return
        if (e?.name === 'AbortError' || e?.code === 'ERR_CANCELED') return
        consecutiveFailures++
        error.value = e
        const status = e?.response?.status
        if (status === 401 || status === 403) {
          error.value = new Error('未登录或会话已过期')
        } else if (status === 422) {
          error.value = new Error('请求参数错误')
        } else if (status >= 500) {
          error.value = new Error('后端服务异常')
        }
        if (onError) onError(error.value)
        else console.warn(`[useCachedFetch] ${resolveKey(key)} 刷新失败:`, e?.message)
      })
      .finally(() => {
        // 清除 refreshing 超时定时器
        if (refreshingTimer) {
          clearTimeout(refreshingTimer)
          refreshingTimer = null
        }
        inFlight = false
        if (currentController === controller) {
          currentController = null
        }
        if (mounted) {
          loading.value = false
          refreshing.value = false
        }
      })
  }

  function refresh() {
    const prevData = data.value
    return doFetch({ silent: false, force: true }).catch((e) => {
      // 刷新失败：恢复旧数据 + 提示用户
      if (prevData !== null && prevData !== undefined) {
        data.value = prevData
      }
      console.warn('[useCachedFetch] 手动刷新失败，已保留缓存:', e?.message || e)
    })
  }

  function silentRefresh() {
    return doFetch({ silent: true })
  }

  function clear() {
    // 中断当前在飞请求，避免 in-flight 回调覆盖已清空的数据
    if (currentController) {
      currentController.abort()
      currentController = null
    }
    inFlight = false
    clearCache(resolveKey(key)).catch(() => {})
    data.value = null
    lastUpdate.value = 0
    fromCache.value = false
    consecutiveFailures = 0
    closingRefreshed = false
    closingRefreshedDate = ''
  }

  // ── 收盘判断（保留在 useCachedFetch 中以避免引入新工具模块）────
  function isPastClose() {
    const now = new Date()
    const day = now.getDay()
    if (day === 0 || day === 6) return false
    const minutes = now.getHours() * 60 + now.getMinutes()
    return minutes >= 900  // >= 15:00
  }

  function isWithinFiveMinutesAfterClose() {
    const now = new Date()
    const day = now.getDay()
    if (day === 0 || day === 6) return false
    const minutes = now.getHours() * 60 + now.getMinutes()
    return minutes >= 900 && minutes <= 905  // 15:00-15:05
  }

  function getTodayStr() {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  }

  // 启动定时器（支持交易时间感知 + 连续失败退避）
  function startTimer() {
    stopTimer()
    if (!tier.refreshInterval || tier.refreshInterval <= 0) return

    if (tradingAware) {
      // 交易时间感知模式：动态调整刷新间隔
      const checkAndRefresh = async () => {
        // 退避策略：连续失败 3 次以上时跳过刷新；每个 tick 减 1，MARKET tier 4min/tick
        // 大约 12-27 分钟（按 tier 不同）后从 3 减到 0，重新尝试
        if (consecutiveFailures >= 3) {
          consecutiveFailures--
          return
        }

        // 跨日兜底：重置收盘刷新标记（tradingDateStore 异常时仍能正确处理）
        const today = getTodayStr()
        if (closingRefreshedDate !== today) {
          closingRefreshed = false
          closingRefreshedDate = today
        }

        // 检查交易日切换 + 获取精确交易时间状态
        let storeIsTrading = null
        try {
          const tradingDateStore = useTradingDateStore()
          const result = await tradingDateStore.checkTradingDate()

          // 检测到交易日切换，强制刷新
          if (result?.changed) {
            console.log(`[useCachedFetch] 定时检测: 交易日切换，强制刷新: ${result.newDate}`)
            clear()
            await doFetch({ force: true })
            return
          }

          // 使用后端精确判断（含节假日），而非本地 isTradingHours()
          storeIsTrading = tradingDateStore.isTradingHours.value
        } catch (e) {
          // store 未初始化时回退到本地判断
          storeIsTrading = isTradingHours()
        }

        if (storeIsTrading) {
          silentRefresh()
        } else if (isWithinFiveMinutesAfterClose() && !closingRefreshed) {
          // 收盘后5分钟内且未刷新过：执行一次收盘刷新
          silentRefresh()
          closingRefreshed = true
        }
        // 非交易时间不刷新（使用缓存）
      }

      timer = setInterval(checkAndRefresh, tier.refreshInterval)
    } else {
      // 普通模式：固定间隔刷新（同样应用退避）
      const checkAndRefresh = () => {
        if (consecutiveFailures >= 3) {
          consecutiveFailures--
          return
        }
        silentRefresh()
      }
      timer = setInterval(checkAndRefresh, tier.refreshInterval)
    }
  }

  function stopTimer() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  // 处理动态 key：key 变化时中断旧请求，拉新数据
  async function handleKeyChange() {
    const newKey = resolveKey(key)
    if (newKey === lastKey) return
    // 中断当前在飞请求（旧 key），允许新 key 立即发起
    if (currentController) {
      currentController.abort()
      currentController = null
    }
    inFlight = false
    refreshing.value = false
    closingRefreshed = false
    consecutiveFailures = 0
    lastKey = newKey

    // 读取新 key 的 stale 缓存，立即显示（不删除旧 key 缓存，保留 SWR 语义）
    const staleCached = await readStaleCache(newKey)
    if (staleCached && mounted) {
      data.value = staleCached.data
      lastUpdate.value = staleCached.timestamp
      fromCache.value = true
      loading.value = false
    } else {
      // 无缓存：清空数据，显示 loading
      data.value = null
      loading.value = true
      error.value = null
    }

    // key 变化时：immediate=true 直接刷新；immediate=false 也刷新（因为key变了需要新数据）
    // noAutoRefresh 时不主动发请求（由外部聚合接口统一调度）
    if (!noAutoRefresh) {
      silentRefresh()
    }
  }

  onMounted(async () => {
    mounted = true
    const resolved = resolveKey(key)
    lastKey = resolved

    // 1. 读取stale缓存（不检查TTL）→ 立即渲染，永不loading
    const staleCached = await readStaleCache(resolved)
    if (staleCached && mounted) {
      data.value = staleCached.data
      lastUpdate.value = staleCached.timestamp
      fromCache.value = true
    }

    // 2. 检查交易日切换（仅在交易时间感知模式下）
    if (tradingAware && mounted) {
      try {
        const tradingDateStore = useTradingDateStore()
        const result = await tradingDateStore.checkTradingDate()
        
        // 检测到交易日切换，强制刷新
        if (result?.changed) {
          console.log(`[useCachedFetch] 交易日切换，强制刷新: ${result.newDate}`)
          clear()  // 清除当前缓存
          if (immediate) {
            await doFetch({ force: true })
          }
        }
      } catch (e) {
        // store 未初始化时忽略错误
        console.debug('[useCachedFetch] 交易日检测跳过:', e.message)
      }
    }

    // 3. 后台静默刷新（noAutoRefresh 时跳过，由外部统一调度）
    if (immediate && mounted && !noAutoRefresh) {
      silentRefresh()
    }

    // 4. 启动周期性静默刷新（noAutoRefresh 时跳过，由外部统一调度）
    if (!noAutoRefresh) {
      startTimer()
    }

    // 5. 监听动态 key 变化（sync 确保 tab 切换时立即响应）
    if (isRef(key) || typeof key === 'function') {
      watch(key, handleKeyChange, { flush: 'sync' })
    }
  })

  // keep-alive 切回 → 恢复定时器，无数据或过期时刷新（非交易时间也允许获取stale数据）
  onActivated(async () => {
    mounted = true
    if (!noAutoRefresh) {
      startTimer()
    }

    // 检查交易日切换（仅在交易时间感知模式下）
    if (tradingAware) {
      try {
        const tradingDateStore = useTradingDateStore()
        const result = await tradingDateStore.checkTradingDate()
        
        // 检测到交易日切换，强制刷新
        if (result?.changed) {
          console.log(`[useCachedFetch] onActivated: 交易日切换，强制刷新: ${result.newDate}`)
          clear()
          if (immediate) {
            await doFetch({ force: true })
          }
          return
        }
      } catch (e) {
        console.debug('[useCachedFetch] onActivated 交易日检测跳过:', e.message)
      }
    }
    
    if (immediate && (!data.value || Date.now() - lastUpdate.value > 60 * 1000)) {
      silentRefresh()
    }
  })

  // keep-alive 切走 → 暂停定时器
  onDeactivated(() => {
    stopTimer()
  })

  onBeforeUnmount(() => {
    mounted = false
    stopTimer()
    if (refreshingTimer) {
      clearTimeout(refreshingTimer)
      refreshingTimer = null
    }
    if (currentController) {
      currentController.abort()
      currentController = null
    }
    // 重置 inFlight，确保 keep-alive 切回时能重新发起请求
    inFlight = false
  })

  return {
    data,
    loading,
    refreshing,
    error,
    lastUpdate,
    fromCache,
    refresh,
    silentRefresh,
    clear,
  }
}

// 对外导出（兼容旧代码）
export { readCache as readStorage, writeCache as writeStorage, clearCache as clearStorage, clearAllCache as clearAllCache }
