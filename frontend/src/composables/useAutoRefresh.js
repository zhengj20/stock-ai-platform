import { ref, onMounted, onBeforeUnmount, onActivated, onDeactivated } from 'vue'
import { isTradingHours, isWeekend } from '@/utils/tradingTime'

/**
 * 通用自动刷新 Hook（不绑缓存）
 *
 * 大多数场景下推荐用 useCachedFetch，它已经内置了分级刷新和持久化。
 * 这个 hook 用于「不需要持久化」或「需要更细粒度控制」的场景。
 *
 * 用法：
 *   const { refreshing, silentRefresh } = useAutoRefresh({
 *     refreshFn: () => store.fetchAll(),
 *     interval: 3 * 60 * 1000,   // 3 分钟
 *     tradingHoursOnly: false,    // true=只在交易时间刷新
 *   })
 */
export function useAutoRefresh({
  refreshFn,
  interval = 180000,
  tradingHoursOnly = false,
  immediate = false,  // 立即执行一次（onMounted 时）
} = {}) {
  const refreshing = ref(false)
  let timer = null
  let isDestroyed = false  // 标记组件是否已销毁，防止异步刷新后操作已卸载的组件

  async function silentRefresh() {
    if (isDestroyed || refreshing.value) return
    refreshing.value = true
    try {
      await Promise.resolve(refreshFn())
    } catch (e) {
      if (!isDestroyed) {
        console.error('[useAutoRefresh] 刷新失败:', e)
      }
    } finally {
      if (!isDestroyed) {
        refreshing.value = false
      }
    }
  }

  function startTimer() {
    stopTimer()
    if (isDestroyed || !interval || interval <= 0) return
    if (tradingHoursOnly && !isTradingHours()) return
    timer = setInterval(() => {
      if (isDestroyed) { stopTimer(); return }
      if (tradingHoursOnly && !isTradingHours()) return
      silentRefresh()
    }, interval)
  }

  function stopTimer() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onMounted(() => {
    isDestroyed = false
    if (immediate) silentRefresh()
    startTimer()
  })

  onActivated(() => {
    isDestroyed = false
    startTimer()
  })

  onDeactivated(() => {
    stopTimer()
  })

  onBeforeUnmount(() => {
    isDestroyed = true
    stopTimer()
  })

  return {
    refreshing,
    silentRefresh,
    startTimer,
    stopTimer,
  }
}


