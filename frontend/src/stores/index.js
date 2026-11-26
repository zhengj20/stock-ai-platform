import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { marketApi, stockApi, strategyApi } from '@/api'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'

/**
 * Store 层职责：
 * - 内部封装 useCachedFetch，统一数据获取 + 缓存逻辑
 * - 提供字段映射（后端 → 前端命名）
 * - 对外暴露响应式 data / loading / refreshing / refresh
 *
 * 组件可以选择：
 *   A. 直接调用 store（推荐，减少重复代码）
 *   B. 继续使用 useCachedFetch（兼容现有代码，后续逐步迁移）
 */

// ====== Market Store ======
function mapSentiment(raw) {
  if (!raw) return raw
  const idxMap = { '000001': 'shanghai', '399001': 'shenzhen', '399006': 'chiNext', '000016': 'sh50', '000300': 'hs300', '399005': 'smallMid', '000688': 'star50', '000905': 'csi500', '000852': 'csi1000' }
  const indices = {}
  if (raw.indices) {
    for (const [code, key] of Object.entries(idxMap)) {
      if (raw.indices[code]) indices[key] = raw.indices[code]
    }
  }
  const mf = raw.money_flow || {}
  const net = mf.net_inflow_billion ?? 0
  let money_flow
  if (mf.source === 'eastmoney' && mf.inflow_billion > 0) {
    money_flow = { ...mf }
  } else {
    money_flow = {
      ...mf,
      inflow_billion: Math.max(0, net),
      outflow_billion: Math.abs(Math.min(0, net)),
      source: mf.source || 'estimate',
    }
  }
  return {
    ...raw,
    indices,
    status: raw.signal || '暂无数据',
    trend: raw.score >= 50 ? '偏多' : '偏空',
    money_flow,
  }
}

function mapSignals(raw) {
  if (!raw) return raw
  return {
    ...raw,
    leading_style: raw.leading_style || '',
    style_performance: raw.style_performance || {},
    flow_leading_style: raw.flow_leading_style || '',
    style_flow: raw.style_flow || {},
    heat_score: raw.heat_score ?? 50,
    warning_divergence: raw.warning_divergence || [],
    accumulation_divergence: raw.accumulation_divergence || [],
    concentration_ratio: raw.concentration_ratio ?? 50,
    top_inflow_sectors: raw.top_inflow_sectors || [],
    advice: raw.advice || '',
  }
}

export const useMarketStore = defineStore('market', () => {
  // 市场情绪 - SWR + localStorage 缓存
  const sentimentCache = useCachedFetch({
    key: 'store:market:sentiment',
    fetcher: () => marketApi.getSentiment(),
    tier: CACHE_TIERS.MARKET,
    onSuccess: mapSentiment,
  })

  // 板块排行
  const sectorsCache = useCachedFetch({
    key: 'store:market:sectors:industry:30',
    fetcher: () => marketApi.getSectors('industry', 30),
    tier: CACHE_TIERS.MARKET,
    immediate: false,
  })

  // 热点题材
  const hotCache = useCachedFetch({
    key: 'store:market:hot:10',
    fetcher: () => marketApi.getHotSectors(10),
    tier: CACHE_TIERS.MARKET,
    immediate: false,
  })

  // 轮动信号
  const signalsCache = useCachedFetch({
    key: 'store:market:signals',
    fetcher: () => marketApi.getSignals(),
    tier: CACHE_TIERS.MARKET,
    onSuccess: mapSignals,
    immediate: false,
  })

  // 日报
  const reportCache = useCachedFetch({
    key: 'store:market:daily-report',
    fetcher: () => marketApi.getDailyReport('detailed'),
    tier: CACHE_TIERS.REPORT,
    immediate: false,
  })

  // 对外暴露
  const sentiment = computed(() => sentimentCache.data.value)
  const sectors = computed(() => sectorsCache.data.value || [])
  const hotSectors = computed(() => hotCache.data.value || [])
  const signals = computed(() => signalsCache.data.value)
  const dailyReport = computed(() => reportCache.data.value)

  return {
    // 数据
    sentiment, sectors, hotSectors, signals, dailyReport,
    // loading 状态
    sentimentLoading: sentimentCache.loading,
    sectorsLoading: sectorsCache.loading,
    hotLoading: hotCache.loading,
    signalsLoading: signalsCache.loading,
    // 刷新方法
    refreshSentiment: () => sentimentCache.refresh(),
    refreshSectors: (type = 'industry', top = 30) => {
      sectorsCache.key = `store:market:sectors:${type}:${top}`
      return sectorsCache.refresh()
    },
    refreshHot: (top = 10) => hotCache.refresh(),
    refreshSignals: () => signalsCache.refresh(),
    refreshReport: () => reportCache.refresh(),
    // 底层缓存对象（供高级用法）
    _raw: { sentimentCache, sectorsCache, hotCache, signalsCache, reportCache },
  }
})

// ====== Stock Store ======
export const useStockStore = defineStore('stock', () => {
  const __currentCode = ref(null)
  const diagnosisLoading = ref(false)

  // 技术指标（动态 key，随股票代码变化）
  const technicalCache = useCachedFetch({
    key: () => `store:stock:technical:${__currentCode.value || ''}`,
    fetcher: () => {
      if (!__currentCode.value) throw new Error('未设置股票代码')
      return stockApi.getTechnical(__currentCode.value)
    },
    tier: CACHE_TIERS.STOCK,
    immediate: false,
  })

  // K线形态
  const patternsCache = useCachedFetch({
    key: () => `store:stock:patterns:${__currentCode.value || ''}`,
    fetcher: () => {
      if (!__currentCode.value) throw new Error('未设置股票代码')
      return stockApi.getPatterns(__currentCode.value)
    },
    tier: CACHE_TIERS.STOCK,
    immediate: false,
  })

  // 因子数据
  const factorsCache = useCachedFetch({
    key: () => `store:stock:factors:${__currentCode.value || ''}`,
    fetcher: () => {
      if (!__currentCode.value) throw new Error('未设置股票代码')
      return stockApi.getFactors([__currentCode.value])
    },
    tier: CACHE_TIERS.STOCK,
    immediate: false,
  })

  async function fetchDiagnosis(code) {
    __currentCode.value = code
    diagnosisLoading.value = true
    try {
      await Promise.all([
        technicalCache.refresh(),
        patternsCache.refresh(),
        factorsCache.refresh(),
      ])
    } catch (e) {
      console.error('获取诊断数据失败:', e)
    } finally {
      diagnosisLoading.value = false
    }
  }

  async function searchStocks(query) {
    try {
      const result = await stockApi.search(query)
      return result
    } catch (e) {
      console.error('搜索失败:', e)
    }
  }

  return {
    technical: computed(() => technicalCache.data.value),
    patterns: computed(() => patternsCache.data.value),
    factors: computed(() => factorsCache.data.value),
    diagnosisLoading,
    fetchDiagnosis, searchStocks,
  }
})

// ====== Strategy Store ======
export const useStrategyStore = defineStore('strategy', () => {
  // 全部策略
  const allStrategiesCache = useCachedFetch({
    key: 'store:strategy:all',
    fetcher: () => strategyApi.getComparison(),
    tier: CACHE_TIERS.REPORT,
    persist: false,
    immediate: false,
  })

  // 龙虎榜今日
  const dragonTodayCache = useCachedFetch({
    key: 'store:strategy:dragon:today',
    fetcher: () => strategyApi.getDragonToday(),
    tier: CACHE_TIERS.MARKET,
    persist: false,
    immediate: false,
  })

  // ML 预测
  const mlCache = useCachedFetch({
    key: 'store:strategy:ml:30',
    fetcher: () => strategyApi.predictStocks(30),
    tier: CACHE_TIERS.REPORT,
    persist: false,
    immediate: false,
  })

  return {
    strategyResult: computed(() => allStrategiesCache.data.value),
    dragonList: computed(() => dragonTodayCache.data.value),
    mlPrediction: computed(() => mlCache.data.value),
    strategyLoading: allStrategiesCache.loading,
    dragonLoading: dragonTodayCache.loading,
    mlLoading: mlCache.loading,
    refreshAllStrategies: (code) => allStrategiesCache.refresh(),
    refreshDragonToday: () => dragonTodayCache.refresh(),
    refreshMLPrediction: (topN = 30) => mlCache.refresh(),
  }
})

// ====== Trading Date Store ======
export const useTradingDateStore = defineStore('tradingDate', () => {
  const currentTradingDate = ref(null)  // 当前交易日 YYYYMMDD
  const isTradingDay = ref(false)
  const isTradingHours = ref(false)
  const lastCheckTime = ref(0)
  const lastCachedDate = ref(localStorage.getItem('gp_trading_date') || null)
  let pendingCheck = null // 防并发重复请求

  // 检查交易日切换（带去重：30秒内不重复请求）
  async function checkTradingDate() {
    // 30秒内有缓存结果，直接返回
    if (lastCheckTime.value && Date.now() - lastCheckTime.value < 30000) {
      return { changed: false, newDate: currentTradingDate.value }
    }

    // 如果有请求在飞，复用同一个 Promise
    if (pendingCheck) return pendingCheck

    pendingCheck = doCheck()
    try {
      return await pendingCheck
    } finally {
      pendingCheck = null
    }
  }

  async function doCheck() {
    try {
      const res = await marketApi.getTradingDate()
      const oldDate = currentTradingDate.value
      currentTradingDate.value = res.trading_date
      isTradingDay.value = res.is_trading_day
      isTradingHours.value = res.is_trading_hours
      lastCheckTime.value = Date.now()

      // 检测到交易日切换
      if (oldDate && oldDate !== res.trading_date) {
        console.log(`[TradingDate] 交易日切换: ${oldDate} -> ${res.trading_date}`)
        // 清除 localStorage 中的旧缓存标记
        localStorage.removeItem('gp_trading_date')
        lastCachedDate.value = null
        return { changed: true, newDate: res.trading_date }
      }

      // 更新 localStorage 缓存标记
      localStorage.setItem('gp_trading_date', res.trading_date)
      lastCachedDate.value = res.trading_date
      return { changed: false, newDate: res.trading_date }
    } catch (e) {
      console.warn('[TradingDate] 获取交易日失败:', e)
      return null
    }
  }

  // 检查是否需要强制刷新（基于交易日切换）
  function shouldForceRefresh() {
    const cachedDate = lastCachedDate.value
    if (!cachedDate || !currentTradingDate.value) return false
    return cachedDate !== currentTradingDate.value
  }

  return {
    currentTradingDate,
    isTradingDay,
    isTradingHours,
    lastCheckTime,
    lastCachedDate,
    checkTradingDate,
    shouldForceRefresh,
  }
})
