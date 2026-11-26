import axios from 'axios'
import router from '@/router'

// 重试配置：ECONNRESET/网络错误自动重试（最多2次，间隔递增）
const MAX_RETRIES = 2
const RETRY_DELAY_BASE = 1000  // 基础延迟1秒

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器：自动附加JWT token + AbortController 支持 + 请求 ID 追踪
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('gp_access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // 生成请求 ID（前后端日志串联，响应头 X-Request-ID 会回传）
  if (!config.headers['X-Request-ID']) {
    config.headers['X-Request-ID'] = Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
  }
  // 如果调用方传入了 signal，绑定到 config（使用 once: true 避免监听器累积）
  if (config.signal) {
    config.signal.addEventListener('abort', () => {
      console.log('[API] 请求已取消:', config.url)
    }, { once: true })
  }
  return config
})

let isRefreshing = false
let refreshSubscribers = []

const onTokenRefreshed = (newToken) => {
  refreshSubscribers.forEach((cb) => cb(newToken))
  refreshSubscribers = []
}

const onTokenRefreshFailed = () => {
  refreshSubscribers.forEach((cb) => cb(null))
  refreshSubscribers = []
}

const addRefreshSubscriber = (cb) => {
  refreshSubscribers.push(cb)
}

// 响应拦截器：401自动刷新token或跳转登录 + ECONNRESET自动重试
api.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    // 取消的请求不重试
    if (axios.isCancel(error)) {
      return Promise.reject(error)
    }

    const originalRequest = error.config
    
    // ECONNRESET/网络错误自动重试（最多MAX_RETRIES次）
    if (!originalRequest._retryCount && (error.code === 'ECONNRESET' || error.code === 'ERR_BAD_RESPONSE' || error.message?.includes('Network Error'))) {
      originalRequest._retryCount = (originalRequest._retryCount || 0) + 1
      if (originalRequest._retryCount <= MAX_RETRIES) {
        const delay = RETRY_DELAY_BASE * Math.pow(2, originalRequest._retryCount - 1)  // 指数退避: 1s, 2s
        console.warn(`[API] 请求失败，${delay}ms后重试 (${originalRequest._retryCount}/${MAX_RETRIES}): ${originalRequest.url}`)
        await new Promise(resolve => setTimeout(resolve, delay))
        return api(originalRequest)
      }
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          addRefreshSubscriber((newToken) => {
            if (newToken) {
              originalRequest.headers.Authorization = `Bearer ${newToken}`
              resolve(api(originalRequest))
            } else {
              reject(error)
            }
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const refreshToken = localStorage.getItem('gp_refresh_token')
        if (!refreshToken) throw new Error('No refresh token')

        const response = await api.post('/auth/refresh', {
          refresh_token: refreshToken,
        })
        const newAccessToken = response.access_token
        localStorage.setItem('gp_access_token', newAccessToken)
        onTokenRefreshed(newAccessToken)

        originalRequest.headers.Authorization = `Bearer ${newAccessToken}`
        return api(originalRequest)
      } catch {
        onTokenRefreshFailed()
        localStorage.removeItem('gp_access_token')
        localStorage.removeItem('gp_refresh_token')
        router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }

    console.error('API请求错误:', error)
    return Promise.reject(error)
  }
)

// ========== 市场看板API ==========
export const marketApi = {
  getSentiment: (date, refresh, signal) => api.get('/market/sentiment', { params: { date, refresh }, signal }),
  // 快路径：不含资金流拆分，30s 超时（全市场breadth首次需10-15s）
  getSentimentQuick: (refresh, signal) => api.get('/market/sentiment/quick', { params: { refresh }, signal }),
  getSectors: (type = 'industry', top = 30, refresh, signal) => api.get('/market/sectors', { params: { sector_type: type, top, refresh }, signal }),
  getSectorFlow: (type = 'industry', top = 10, signal) => api.get('/market/sectors/flow', { params: { sector_type: type, top }, signal }),
  getSectorStrength: (period = 20, signal) => api.get('/market/sectors/strength', { params: { period }, signal }),
  getHotSectors: (top = 10, refresh, signal) => api.get('/market/hot', { params: { top, refresh }, signal }),
  getSignals: (refresh, signal) => api.get('/market/signals', { params: { refresh }, signal }),
  getDailyReport: (style = 'detailed', fmt = 'json', signal) => api.get('/market/daily-report', { params: { style, fmt }, signal }),
  // 新增：北向资金
  getNorthboundFlow: (signal) => api.get('/market/northbound', { signal }),
  getNorthboundHistory: (n = 20, signal) => api.get('/market/northbound/history', { params: { n }, signal }),
  // 涨停板池（同花顺）
  getLimitUpPool: (refresh = 0, signal) => api.get('/market/limit_up_pool', { params: { refresh }, signal }),
  getLimitDownPool: (refresh = 0, signal) => api.get('/market/limit_down_pool', { params: { refresh }, signal }),
  // 同花顺热门个股榜（综合）
  getTHSHotRank: (top = 30, refresh = 0, signal) => api.get('/market/ths_hot_rank', { params: { top, refresh }, signal }),
  // 合并端点：资金流拆分 + THS热门榜，共享底层数据源
  getDashboardCombined: (top = 30, force = 0, signal) => api.get('/market/dashboard/combined', { params: { top, force }, signal }),
  // 完整聚合：市场看板首页所有数据（一次性返回，减少 80%+ 请求数）
  getDashboardFull: (force = 0, signal) => api.get('/market/dashboard/full', { params: { force }, signal, timeout: 120000 }),
  // 指数列表 + 迷你 K 线（pytdx）
  getIndicesWithKline: (codes = '000001,399001,399006,000300,000016,000688', n = 30, signal) =>
    api.get('/market/indices/kline', { params: { codes, n }, signal }),
  // 交易日信息（供前端轮询检测交易日切换）
  getTradingDate: (signal) => api.get('/market/trading-date', { signal }),
}

// ========== 个股诊断API ==========
export const stockApi = {
  getKline: (code, period = "daily", count = 200, signal) => api.get(`/stock/kline/${code}`, { params: { period, count }, signal }),
  getTechnical: (code, period = '近一年', signal) => {
    if (!code) return Promise.reject(new Error('股票代码为空'))
    return api.get(`/stock/technical/${code}`, { params: { period }, signal })
  },
  getPatterns: (code, periods = 200, signal) => {
    if (!code) return Promise.reject(new Error('股票代码为空'))
    return api.get(`/stock/patterns/${code}`, { params: { periods }, signal })
  },
  getFactors: (stocks, factors, weight = 'equal_weight', signal) =>
    api.get('/stock/factors', { params: { stocks: stocks.join(','), factors: factors?.join(','), weight }, signal }),
  getDiagnosis: (code, signal) => api.get(`/stock/diagnosis/${code}`, { signal }),
  dragonToday: (signal) => api.get('/dragon/today', { signal }),
  search: (query, signal) => api.get('/stock/search', { params: { query }, signal }),
  suggest: (q, signal) => api.get('/stock/suggest', { params: { q }, signal }),
  getNews: (code, topN = 5, signal) => api.get(`/stock/news/${code}`, { params: { top_n: topN }, signal }),
  // 决策中心算法信号（TD序列/均线雷达/通道突破/神奇电波/异动拉升/底部寻机/趋势强度）
  getDecisionSignals: (code, period = 250, signal) => api.get(`/decision/signals/${code}`, { params: { period }, signal }),
  // 批量获取自选股决策信号（full=true返回全部7个算法+综合评分）
  getWatchlistDecisionSignals: (codes, full = false, signal) => api.get('/decision/watchlist-signals', { params: { stock_codes: codes.join(','), full }, signal }),
  // 决策算法预警监控（单只/批量）
  monitorDecision: (stockList, holdingContextMap = null, signal) => api.post('/decision/monitor', { stock_list: stockList, holding_context_map: holdingContextMap }, { signal }),
  // 监控自选股决策信号
  monitorWatchlistDecision: (signal) => api.post('/decision/monitor-watchlist', {}, { signal }),
  // 监控持仓决策信号（含持仓感知）
  monitorHoldingsDecision: (signal) => api.post('/decision/monitor-holdings', {}, { signal }),

  // 资金面深度分析接口已移除（东财datacenter接口不稳定，数据不可用）
  // getMarginTrading: (code, pageSize = 30, signal) => api.get(`/stock/margin/${code}`, { params: { page_size: pageSize }, signal }),
  // getBlockTrade: (code, pageSize = 20, signal) => api.get(`/stock/block-trade/${code}`, { params: { page_size: pageSize }, signal }),
  // getHolderChange: (code, pageSize = 10, signal) => api.get(`/stock/holders/${code}`, { params: { page_size: pageSize }, signal }),
  // getDividendHistory: (code, pageSize = 20, signal) => api.get(`/stock/dividend/${code}`, { params: { page_size: pageSize }, signal }),
  // getFlowHistory120d: (code, signal) => api.get(`/stock/flow-history/${code}`, { signal }),
  // getDragonTigerSeats: (code, tradeDate = null, lookBack = 30, signal) => 
  //   api.get(`/stock/dragon-tiger/seats/${code}`, { params: { trade_date: tradeDate || undefined, look_back: lookBack }, signal }),
  // getLockupExpiry: (code, tradeDate = null, forwardDays = 90, signal) => 
  //   api.get(`/stock/lockup/${code}`, { params: { trade_date: tradeDate || undefined, forward_days: forwardDays }, signal }),
  // getIndustryReports: (industry = '', pageSize = 20, signal) => 
  //   api.get('/industry/reports', { params: { industry, page_size: pageSize }, signal }),
}

// ========== 策略中心API ==========
export const strategyApi = {
  runStrategy: (name, code, params = {}, signal) =>
    api.get(`/strategy/run/${name}/${code}`, { params, signal }),
  runAllStrategies: (code, signal) => api.get(`/strategy/all/${code}`, { signal }),
  getComparison: (refresh = 0, signal) => api.get('/strategy/comparison', { params: { refresh }, signal }),
  getDragonToday: (refresh = false, signal) => api.get('/dragon/today', { params: { refresh }, signal }),
  getDragonStrategy: (type = 'all', refresh = false, topN = 15, filterParams = {}, signal) => api.get('/dragon/strategy', { params: { strategy_type: type, refresh, top_n: topN, ...filterParams }, signal }),
  getDragonHistory: (date, signal) => api.get(`/dragon/history/${date}`, { signal }),
  refreshDragonCache: (signal) => api.post('/dragon/refresh', null, { signal }),
  getDragonCapitalFlow: (refresh = false, signal) => api.get('/dragon/capital-flow', { params: { refresh }, signal }),
  getDragonSeatDetail: (refresh = false, signal) => api.get('/dragon/seat-detail', { params: { refresh }, signal }),
  getDragonSectorAnalysis: (refresh = false, signal) => api.get('/dragon/sector-analysis', { params: { refresh }, signal }),
  getDragonConsecutive: (days = 5, signal) => api.get('/dragon/consecutive', { params: { days }, signal }),
  getDragonNextDayPerformance: (refresh = false, signal) => api.get('/dragon/next-day-performance', { params: { refresh }, signal }),
  trainModel: (days = 250, model = 'lightgbm', signal) => api.post('/ml/train', null, { params: { days, model }, signal, timeout: 600000 }),
  getModelStatus: (signal) => api.get('/ml/status', { signal }),
  predictStocks: (topN = 30, refresh = 0, filterParams = {}, signal) => api.get('/ml/predict', { params: { top_n: topN, refresh, ...filterParams }, signal }),
  getMultiFactorPicks: (topN = 20, refresh = 0, params = {}, signal) => api.get('/strategy/multi-factor-picks', { params: { top_n: topN, refresh, ...params }, signal }),
  getLowAbsorptionPicks: (topN = 20, refresh = 0, params = {}, signal) => api.get('/strategy/low-absorption-picks', { params: { top_n: topN, refresh, ...params }, signal }),
  getCapitalFlowPicks: (topN = 20, refresh = 0, params = {}, signal) => api.get('/strategy/capital-flow-picks', { params: { top_n: topN, refresh, ...params }, signal }),
  getStrategyCombo: (topN = 20, mode = 'vote', refresh = 0, filterParams = {}, signal) => api.get('/strategy/combo', { params: { top_n: topN, mode, refresh, ...filterParams }, signal }),
  getVolumePriceDivergence: (topN = 20, refresh = 0, params = {}, signal) => api.get('/strategy/volume-price-divergence', { params: { top_n: topN, refresh, ...params }, signal }),
  getLeaderPicks: (sectorType = 'industry', topN = 3, sectorCount = 10, refresh = 0, params = {}, signal) => api.get('/strategy/leader-picks', { params: { sector_type: sectorType, top_n: topN, sector_count: sectorCount, refresh, ...params }, signal }),
  // New endpoints for refactored strategy module
  preloadKlines: () => api.post('/strategy/kline/preload'),
  getStrategyInfo: (signal) => api.get('/strategy/info', { signal }),
}

// ========== 每日复盘API ==========
export const dailyReportApi = {
  list: (days = 30, signal) => api.get('/market/daily-reports', { params: { days }, signal }),
  getLatest: (signal) => api.get('/market/daily-reports/latest', { signal }),
  getByDate: (date, signal) => api.get(`/market/daily-reports/${date}`, { signal }),
  generate: (date, signal) => api.post('/market/daily-reports/generate', null, { params: { report_date: date }, signal, timeout: 600000 }),
}

// ========== AI股票推荐API ==========
export const aiStockPickApi = {
  list: (days = 30, signal) => api.get('/ai-stock-picks', { params: { days }, signal }),
  getLatest: (signal) => api.get('/ai-stock-picks/latest', { signal }),
  getByDate: (date, signal) => api.get(`/ai-stock-picks/${date}`, { signal }),
  generate: (date, signal) => api.post('/ai-stock-picks/generate', null, { params: { date }, signal, timeout: 600000 }),
}

// ========== NLP对话API ==========
export const nlpApi = {
  analyze: (message, signal) => api.post('/nlp/analyze', { message }, { signal }),
  classifyIntent: (query, signal) => api.get('/nlp/intent', { params: { query }, signal }),
  smartSearch: (query, signal) => api.get('/nlp/smart-search', { params: { query }, signal }),
  getNewsCache: (days = 1, date = null, signal) => api.get('/nlp/news-cache', { params: { days, ...(date ? { date } : {}) }, signal }),
  newsRefresh: (signal) => api.post('/nlp/news-refresh', {}, { signal }),
  getResearchCache: (params = {}, signal) => api.get('/nlp/research-cache', { params, signal }),
  getNewsLive: (topN = 30, signal) => api.get('/nlp/news-live', { params: { top_n: topN }, signal }),
  getResearchLive: (topN = 30, signal, force = 0) => api.get('/nlp/research-live', { params: { top_n: topN, force }, signal }),
  searchNewsLive: (query, topN = 15, signal) => api.get('/nlp/search-live', { params: { query, top_n: topN }, signal }),
}

// ========== LLM对话API ==========
export const chatApi = {
  getConfig: (signal) => api.get('/chat/config', { signal }),
  updateConfig: (cfg, signal) => api.post('/chat/config', cfg, { signal }),
  testConnection: (signal) => api.post('/chat/config/test', {}, { signal }),
  chat: (messages, stream = true, signal) => api.post('/chat/completions', { messages, stream }, { signal }),
}

// ========== 板块深度分析API ==========
export const sectorAnalysisApi = {
  // P0: 涨停梯队分析
  getLimitUpLadder: (date, refresh = 0, signal) => api.get('/sector-analysis/limit-ladder', { params: { date, refresh }, signal }),
  // P0: 板块轮动量化模型
  getRotationModel: (sector_type = 'industry', top_n = 30, refresh = 0, signal) =>
    api.get('/sector-analysis/rotation-model', { params: { sector_type, top_n, refresh }, signal }),
  // P1: 行业研报聚合
  getIndustryReports: (top_n = 30, refresh = 0, signal) =>
    api.get('/sector-analysis/industry-reports', { params: { top_n, refresh }, signal }),
  // P1: 板块热度排行
  getHeatRank: (top_n = 30, refresh = 0, signal) =>
    api.get('/sector-analysis/heat-rank', { params: { top_n, refresh }, signal }),
  // P2: 产业链深度分析
  getIndustryChain: (refresh = 0, signal) => api.get('/sector-analysis/industry-chain', { params: { refresh }, signal }),
  // P2: 板块对比工具
  getComparison: (names, sector_type = 'industry', refresh = 0, signal) =>
    api.get('/sector-analysis/comparison', { params: { names, sector_type, refresh }, signal }),
}

export default api


// ========== 自选股API ==========
export const watchlistApi = {
  getQuotes: (codes, signal) => api.get('/watchlist/quotes', { params: { codes: codes.join(',') }, signal }),
  batchDiagnosis: (stocks, signal) => api.post('/watchlist/batch-diagnosis', { stocks }, { signal }),
  search: (query, signal) => api.get('/watchlist/search', { params: { query }, signal }),
  // 持久化接口（登录用户走数据库，未登录降级 localStorage）
  getMyWatchlist: (signal) => api.get('/watchlist/my', { signal }),
  getAllWatchlist: (params) => api.get('/watchlist/all', { params }),
  addStock: (stock_code, stock_name = '', group = '默认') => api.post('/watchlist/add', { stock_code, stock_name, group }),
  removeStock: (stock_code) => api.delete(`/watchlist/remove/${stock_code}`),
  updateGroup: (stock_code, group) => api.put('/watchlist/update-group', null, { params: { stock_code, group } }),
  reorder: (order) => api.put('/watchlist/reorder', null, { params: { order: order.join(',') } }),
}

// ========== 持仓管理API ==========
export const holdingsApi = {
  getMy: () => api.get('/holdings/my'),
  getAll: (params) => api.get('/holdings/all', { params }),
  add: (data) => api.post('/holdings/add', data),
  update: (id, data) => api.put(`/holdings/${id}`, data),
  delete: (id) => api.delete(`/holdings/${id}`),
  syncPrices: () => api.post('/holdings/sync-prices'),
  getSummary: () => api.get('/holdings/summary'),
}

// ========== 自选股AI策略API ==========
export const watchlistStrategyApi = {
  generate: (mode, config) => api.post('/watchlist-strategy/generate', mode ? { mode } : {}, config),
  getHistory: (params) => api.get('/watchlist-strategy/history', { params }),
  getLatest: () => api.get('/watchlist-strategy/latest'),
  getDetail: (id) => api.get(`/watchlist-strategy/detail/${id}`),
  delete: (id) => api.delete(`/watchlist-strategy/${id}`),
  getConfig: () => api.get('/watchlist-strategy/config'),
  updateConfig: (data) => api.put('/watchlist-strategy/config', data),
  // 建议采纳反馈
  updateFeedback: (id, data) => api.put(`/watchlist-strategy/${id}/feedback`, data),
}


// ========== 策略回测API ==========
export const backtestApi = {
  // 单策略回测
  run: (data) => api.post("/backtest/run", data),
  // 多策略对比
  compare: (data) => api.post("/backtest/compare", data),
  // 批量回测（多只股票同一策略）
  batch: (data) => api.post("/backtest/batch", data),
  // 快速验证（智能选股内联使用，返回精简指标+综合评分）
  verify: (data) => api.post("/backtest/verify", data),
  // 列出可用策略
  listStrategies: () => api.get("/backtest/strategies"),
  // 列出回测报告
  listReports: () => api.get("/backtest/reports"),
}

// ========== 决策中心API ==========
export const decisionApi = {
  // 获取个股决策信号
  getSignals: (code, period = 250, signal) => api.get(`/decision/signals/${code}`, { params: { period }, signal }),
  // 批量获取自选股决策信号（full=true返回全部7个算法+综合评分）
  getWatchlistSignals: (codes, full = false, signal) => api.get('/decision/watchlist-signals', { params: { stock_codes: codes.join(','), full }, signal }),
  // 决策算法预警监控（单只/批量）
  monitor: (stockList, holdingContextMap = null, signal) => api.post('/decision/monitor', { stock_list: stockList, holding_context_map: holdingContextMap }, { signal }),
  // 监控自选股决策信号
  monitorWatchlist: (signal) => api.post('/decision/monitor-watchlist', {}, { signal }),
  // 监控持仓决策信号（含持仓感知）
  monitorHoldings: (signal) => api.post('/decision/monitor-holdings', {}, { signal }),
  // 获取扫描历史
  getScanHistory: (signal) => api.get('/decision/scan-history', { signal }),
  // 选股扫描
  scan: (algo, signal = 'buy', topN = 20, minScore = 0, httpSignal) => api.get('/decision/scan', { params: { algo, signal, top_n: topN, min_score: minScore }, signal: httpSignal }),
}
