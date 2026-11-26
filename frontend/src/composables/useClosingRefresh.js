import { onMounted, onBeforeUnmount } from 'vue'

/**
 * 收盘后自动拉取最新数据
 *
 * 在 A 股交易日 15:00 后，自动对所有传入的 useCachedFetch 实例执行一次 silentRefresh()，
 * 保证缓存数据为当日最终数据。同一天只触发一次（localStorage 标记防重复）。
 *
 * 用法：
 *   useClosingRefresh([multiFactorCache, lowAbsCache, dragonCache, ...])
 */
export function useClosingRefresh(caches) {
  const FLAG_PREFIX = 'gp_closing_refreshed:'
  const CHECK_INTERVAL = 5 * 60 * 1000 // 5 分钟检测一次

  function todayKey() {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }

  function isPastClose() {
    const now = new Date()
    const day = now.getDay()
    if (day === 0 || day === 6) return false // 周末不处理
    const minutes = now.getHours() * 60 + now.getMinutes()
    return minutes >= 900 // >= 15:00
  }

  function alreadyRefreshed() {
    try {
      return localStorage.getItem(FLAG_PREFIX + todayKey()) === '1'
    } catch { return false }
  }

  function markRefreshed() {
    try {
      localStorage.setItem(FLAG_PREFIX + todayKey(), '1')
    } catch {}
  }

  function doClosingRefresh() {
    if (!isPastClose() || alreadyRefreshed()) return
    if (!caches || !caches.length) return
    markRefreshed()
    caches.forEach(c => {
      if (c && typeof c.silentRefresh === 'function') {
        c.silentRefresh()
      }
    })
  }

  let timer = null

  onMounted(() => {
    doClosingRefresh()
    timer = setInterval(doClosingRefresh, CHECK_INTERVAL)
  })

  onBeforeUnmount(() => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  })
}
