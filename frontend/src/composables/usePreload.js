import api from '@/api'
import { writeCache } from './useIndexedDB'
import { CACHE_TIERS } from './useCachedFetch'

/**
 * 登录后预加载三大模块数据到 IndexedDB
 * 后端启动预热 + stale 缓存机制保证任何时段都能返回数据，
 * 因此前端无需再按时段跳过。失败自动重试1次。
 */
export async function preloadDashboardData() {
  const ok = await doPreload()
  if (!ok) {
    // 失败后 1s 重试（与后端 120s 超时保持一致，给上游足够时间）
    await new Promise(r => setTimeout(r, 1000))
    await doPreload()
  }
}

async function doPreload() {
  // 与后端 TimeoutMiddleware 保持一致：preload 端点允许 120s
  const ctrl = new AbortController()
  setTimeout(() => ctrl.abort(), 130000)
  try {
    const res = await api.get('/cache/preload', { signal: ctrl.signal, timeout: 130000 })
    if (!res) return false

    const tierMarket = CACHE_TIERS.MARKET
    const tierStrategy = CACHE_TIERS.STRATEGY

    // ── 市场看板 ──────────────────────────────
    const market = res.market || {}
    if (market.sentiment) {
      await writeCache('market:sentiment:quick', market.sentiment, tierMarket.storageTTL)
    }
    if (market.sectors_industry) {
      await writeCache('market:sectors:industry:30', market.sectors_industry, tierMarket.storageTTL)
    }
    if (market.hot) {
      await writeCache('market:hot:10', market.hot, tierMarket.storageTTL)
    }
    if (market.signals) {
      await writeCache('market:signals', market.signals, tierMarket.storageTTL)
    }

    // ── 龙虎榜 ────────────────────────────────
    const dragon = res.dragon || {}
    if (dragon.dragon_today) {
      await writeCache('dragon:today:v6', dragon.dragon_today, tierMarket.storageTTL)
    }
    if (dragon.dragon_capital_flow) {
      await writeCache('dragon:capital-flow', dragon.dragon_capital_flow, tierMarket.storageTTL)
    }
    if (dragon.dragon_seat_detail) {
      await writeCache('dragon:seat-detail', dragon.dragon_seat_detail, tierMarket.storageTTL)
    }
    if (dragon.dragon_sector) {
      await writeCache('dragon:sector-analysis', dragon.dragon_sector, tierMarket.storageTTL)
    }
    if (dragon.dragon_consecutive_5) {
      await writeCache('dragon:consecutive:5', dragon.dragon_consecutive_5, tierMarket.storageTTL)
    }
    if (dragon.dragon_perf) {
      await writeCache('dragon:next-day', dragon.dragon_perf, tierMarket.storageTTL)
    }

    // ── 智能选股（默认tab：多因子 + 策略组合）─────────────
    // key 必须与 SmartStockPick.vue 中的 useCachedFetch key 一致
    const strategy = res.strategy || {}
    if (strategy.multi_factor) {
      await writeCache('smart:multi', strategy.multi_factor, tierStrategy.storageTTL)
    }
    if (strategy.combo) {
      // comboForm 默认值: { count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true }
      const defaultComboForm = JSON.stringify({ count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true })
      await writeCache(`smart:combo:vote:${defaultComboForm}`, strategy.combo, tierStrategy.storageTTL)
    }
    return true
  } catch (e) {
    if (e?.name === 'AbortError' || e?.code === 'ERR_CANCELED') return false
    console.warn('[preload] 预加载失败:', e?.message)
    return false
  }
}
