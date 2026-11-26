<template>
  <div class="kline-chart-wrapper">
    <div class="ma-legend">
      <span
        class="ma-item"
        :class="{ active: showMA5 }"
        :style="{ '--ma-color': '#f5b731' }"
        @click="toggleMA('ma5')"
      >
        MA5: <span class="ma-value">{{ maValues.ma5 ?? '--' }}</span>
      </span>
      <span
        class="ma-item"
        :class="{ active: showMA10 }"
        :style="{ '--ma-color': '#4dabf7' }"
        @click="toggleMA('ma10')"
      >
        MA10: <span class="ma-value">{{ maValues.ma10 ?? '--' }}</span>
      </span>
      <span
        class="ma-item"
        :class="{ active: showMA20 }"
        :style="{ '--ma-color': '#9775fa' }"
        @click="toggleMA('ma20')"
      >
        MA20: <span class="ma-value">{{ maValues.ma20 ?? '--' }}</span>
      </span>
    </div>
    <div ref="chartContainer" class="chart-container">
      <div id="kline-tooltip" class="kline-tooltip"></div>
    </div>
    <div v-if="loading && !error" class="chart-loading">加载中...</div>
    <div v-if="error" class="chart-error">
      <span>{{ error }}</span>
      <el-button type="primary" size="small" @click="handleRetry" :loading="loading">重试</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts'
import { stockApi } from '@/api'

const props = defineProps({
  stockCode: { type: String, required: true },
  period: { type: String, default: 'daily' },
  height: { type: Number, default: 420 },
})

const emit = defineEmits(['error'])

const chartContainer = ref(null)
const loading = ref(false)
const error = ref('')
const showMA5 = ref(true)
const showMA10 = ref(true)
const showMA20 = ref(true)
const maValues = ref({ ma5: null, ma10: null, ma20: null })
let chart = null
let candleSeries = null
let volumeSeries = null
let ma5Series = null
let ma10Series = null
let ma20Series = null
let crosshairMovedUnsub = null
let rangeChangeUnsub = null
let markersHandler = null
let allCandleData = []
let rangeChangeTimer = null
let retryTimer = null
let currentAbortController = null
let loadId = 0
let resizeObserver = null

onMounted(async () => {
  await nextTick()
  if (chartContainer.value && chartContainer.value.clientWidth > 0) {
    initChart()
    await loadData()
  } else {
    waitForContainerWidth()
  }
  window.addEventListener('resize', handleResize)
})

function waitForContainerWidth(timeout = 5000) {
  if (!chartContainer.value) return
  const startTime = Date.now()

  resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const width = entry.contentBoxSize?.[0]?.inlineSize ?? entry.contentRect?.width ?? 0
      if (width > 0) {
        resizeObserver.disconnect()
        resizeObserver = null
        if (!chart) {
          initChart()
          loadData()
        }
        return
      }
    }
  })
  resizeObserver.observe(chartContainer.value)

  setTimeout(() => {
    if (resizeObserver) {
      resizeObserver.disconnect()
      resizeObserver = null
      if (!chart) {
        error.value = '图表容器初始化超时，请尝试切换周期或刷新页面'
        loading.value = false
      }
    }
  }, timeout)
}

watch(() => props.stockCode, async (newVal) => {
  if (newVal) await loadData()
})

watch(() => props.period, async (newVal) => {
  if (newVal) await loadData()
})

let brandingObserver = null

function removeBranding() {
  if (!chart) return
  const chartEl = chart.chartElement()
  if (!chartEl) return
  chartEl.querySelectorAll('a').forEach(el => el.remove())
  const overlays = chartEl.querySelectorAll('div')
  overlays.forEach(el => {
    const style = el.style
    if (style && style.position === 'absolute' && style.bottom && style.left) {
      if (el.querySelector('a') || el.textContent?.includes('TradingView') || el.innerHTML?.includes('tradingview')) {
        el.remove()
      }
    }
  })
}

function initChart() {
  if (!chartContainer.value) return
  chart = createChart(chartContainer.value, {
    width: chartContainer.value.clientWidth,
    height: props.height,
    layout: {
      background: { type: 'solid', color: '#ffffff' },
      textColor: '#606266',
    },
    grid: {
      vertLines: { color: 'rgba(210, 214, 218, 0.3)' },
      horzLines: { color: 'rgba(210, 214, 218, 0.3)' },
    },
    rightPriceScale: {
      borderColor: '#e4e7ed',
      scaleMargins: { top: 0.1, bottom: 0.25 },
    },
    timeScale: {
      borderColor: '#e4e7ed',
      timeVisible: props.period === 'monthly',
      rightOffset: 5,
      barSpacing: 6,
    },
    crosshair: {
      mode: 1,
      vertLine: { labelBackgroundColor: '#409eff' },
      horzLine: { labelBackgroundColor: '#409eff' },
    },
    handleScroll: true,
    handleScale: true,
  })

  candleSeries = chart.addSeries(CandlestickSeries, {
    upColor: '#f56c6c',
    downColor: '#67c23a',
    borderUpColor: '#f56c6c',
    borderDownColor: '#67c23a',
    wickUpColor: '#f56c6c',
    wickDownColor: '#67c23a',
  })

  volumeSeries = chart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  })

  volumeSeries.priceScale().applyOptions({
    scaleMargins: { top: 0.8, bottom: 0 },
  })

  ma5Series = chart.addSeries(LineSeries, {
    color: '#f5b731',
    lineWidth: 1,
    priceLineVisible: true,
    lastValueVisible: true,
    priceLineStyle: 2,
    title: 'MA5',
  })

  ma10Series = chart.addSeries(LineSeries, {
    color: '#4dabf7',
    lineWidth: 1,
    priceLineVisible: true,
    lastValueVisible: true,
    priceLineStyle: 2,
    title: 'MA10',
  })

  ma20Series = chart.addSeries(LineSeries, {
    color: '#9775fa',
    lineWidth: 1,
    priceLineVisible: true,
    lastValueVisible: true,
    priceLineStyle: 2,
    title: 'MA20',
  })

  crosshairMovedUnsub = chart.subscribeCrosshairMove((param) => {
    if (param.time) {
      const candleData = param.seriesData.get(candleSeries)
      const volumeData = param.seriesData.get(volumeSeries)
      if (candleData) {
        updateTooltip(param.time, candleData, volumeData?.value)
      }
      const ma5Data = param.seriesData.get(ma5Series)
      const ma10Data = param.seriesData.get(ma10Series)
      const ma20Data = param.seriesData.get(ma20Series)
      maValues.value = {
        ma5: ma5Data?.value?.toFixed(2) ?? null,
        ma10: ma10Data?.value?.toFixed(2) ?? null,
        ma20: ma20Data?.value?.toFixed(2) ?? null,
      }
    } else {
      hideTooltip()
      updateMALegendLastValues()
    }
  })

  chart.timeScale().scrollToRealTime()

  brandingObserver = new MutationObserver(removeBranding)
  brandingObserver.observe(chart.chartElement(), { childList: true, subtree: true })
  removeBranding()
  setTimeout(removeBranding, 500)
  setTimeout(removeBranding, 2000)
}

function addHighLowMarkers() {
  const data = allCandleData
  if (!data || data.length === 0) return

  let visibleRange = null
  try {
    visibleRange = chart.timeScale().getVisibleLogicalRange()
  } catch (e) {}

  let filteredData = data
  if (visibleRange && data.length > 10) {
    const fromIdx = Math.max(0, Math.floor(visibleRange.from))
    const toIdx = Math.min(data.length - 1, Math.ceil(visibleRange.to))
    filteredData = data.slice(fromIdx, toIdx + 1)
  }

  let highIdx = 0
  let lowIdx = 0
  for (let i = 1; i < filteredData.length; i++) {
    if (filteredData[i].high > filteredData[highIdx].high) highIdx = i
    if (filteredData[i].low < filteredData[lowIdx].low) lowIdx = i
  }

  const highItem = filteredData[highIdx]
  const lowItem = filteredData[lowIdx]

  const markers = [
    {
      time: highItem.time,
      position: 'aboveBar',
      color: '#f56c6c',
      shape: 'arrowDown',
      text: `高 ${highItem.high.toFixed(2)}`,
    },
    {
      time: lowItem.time,
      position: 'belowBar',
      color: '#67c23a',
      shape: 'arrowUp',
      text: `低 ${lowItem.low.toFixed(2)}`,
    },
  ]

  markers.sort((a, b) => {
    const ta = typeof a.time === 'string' ? a.time : String(a.time)
    const tb = typeof b.time === 'string' ? b.time : String(b.time)
    return ta.localeCompare(tb)
  })

  if (!markersHandler) {
    markersHandler = createSeriesMarkers(candleSeries, markers)
  } else {
    markersHandler.setMarkers(markers)
  }
}

function updateTooltip(time, candle, volume) {
  const tooltip = document.getElementById('kline-tooltip')
  if (!tooltip) return
  const color = candle.close >= candle.open ? '#f56c6c' : '#67c23a'
  tooltip.innerHTML = `
    <div style="font-size:12px;color:#606266">
      <div style="color:${color};font-weight:600;margin-bottom:2px;">${time}</div>
      <div>开: ${candle.open?.toFixed(2)} &nbsp; 高: ${candle.high?.toFixed(2)}</div>
      <div>低: ${candle.low?.toFixed(2)} &nbsp; 收: ${candle.close?.toFixed(2)}</div>
      <div>量: ${(volume || 0).toLocaleString()} 手</div>
    </div>
  `
  tooltip.style.display = 'block'
}

function hideTooltip() {
  const tooltip = document.getElementById('kline-tooltip')
  if (tooltip) tooltip.style.display = 'none'
}

function toggleMA(type) {
  const seriesMap = { ma5: ma5Series, ma10: ma10Series, ma20: ma20Series }
  const showMap = { ma5: showMA5, ma10: showMA10, ma20: showMA20 }
  const show = !showMap[type].value
  showMap[type].value = show
  seriesMap[type].applyOptions({ visible: show })
  updateMALegendLastValues()
}

function updateMALegendLastValues() {
  const getLastValue = (series) => {
    const data = series.data()
    if (data.length === 0) return null
    return data[data.length - 1].value?.toFixed(2) ?? null
  }
  maValues.value = {
    ma5: showMA5.value ? getLastValue(ma5Series) : null,
    ma10: showMA10.value ? getLastValue(ma10Series) : null,
    ma20: showMA20.value ? getLastValue(ma20Series) : null,
  }
}

async function loadData(retryCount = 0) {
  const maxRetries = 2
  const thisLoadId = ++loadId

  clearTimeout(retryTimer)
  if (currentAbortController) currentAbortController.abort()
  currentAbortController = new AbortController()

  loading.value = true
  error.value = ''
  try {
    if (!chart || !candleSeries) {
      if (chartContainer.value && chartContainer.value.clientWidth > 0) {
        initChart()
      } else {
        throw new Error('图表容器未就绪')
      }
    }
    candleSeries.setData([])
    volumeSeries.setData([])
    ma5Series.setData([])
    ma10Series.setData([])
    ma20Series.setData([])
    allCandleData = []

    const res = await stockApi.getKline(props.stockCode, props.period, 200, currentAbortController.signal)

    if (thisLoadId !== loadId) return

    if (!res.klines || res.klines.length === 0) {
      error.value = '暂无K线数据（通达信数据源未返回该股票历史行情）'
      loading.value = false
      return
    }

    const candleData = res.klines.map(k => ({
      time: k.time.split(' ')[0],
      open: k.open,
      high: k.high,
      low: k.low,
      close: k.close,
    }))

    const volumeData = res.klines.map(k => ({
      time: k.time.split(' ')[0],
      value: k.volume,
      color: k.close >= k.open ? 'rgba(245, 108, 108, 0.4)' : 'rgba(103, 194, 58, 0.4)',
    }))

    allCandleData = candleData
    candleSeries.setData(candleData)
    volumeSeries.setData(volumeData)

    const closes = candleData.map(d => d.close)
    function calcMA(data, period) {
      const result = []
      let sum = 0
      for (let i = 0; i < data.length; i++) {
        sum += closes[i]
        if (i >= period) sum -= closes[i - period]
        if (i >= period - 1) {
          result.push({ time: data[i].time, value: Math.round((sum / period) * 100) / 100 })
        }
      }
      return result
    }
    const ma5Data = calcMA(candleData, 5)
    const ma10Data = calcMA(candleData, 10)
    const ma20Data = calcMA(candleData, 20)
    ma5Series.setData(ma5Data)
    ma10Series.setData(ma10Data)
    ma20Series.setData(ma20Data)

    const lastMA = (data) => (data.length > 0 ? Number(data[data.length - 1].value).toFixed(2) : null)
    maValues.value = {
      ma5: lastMA(ma5Data),
      ma10: lastMA(ma10Data),
      ma20: lastMA(ma20Data),
    }

    chart.timeScale().applyOptions({ timeVisible: props.period === 'monthly' })
    chart.timeScale().fitContent()

    setTimeout(() => {
      if (thisLoadId !== loadId) return
      addHighLowMarkers()
      if (rangeChangeUnsub) rangeChangeUnsub()
      const onRangeChange = () => {
        if (allCandleData.length > 0) {
          clearTimeout(rangeChangeTimer)
          rangeChangeTimer = setTimeout(addHighLowMarkers, 150)
        }
      }
      rangeChangeUnsub = chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange)
    }, 200)

    updateMALegendLastValues()
    loading.value = false
  } catch (e) {
    if (thisLoadId !== loadId) return
    if (e.name === 'AbortError') return
    if (retryCount < maxRetries) {
      const delay = Math.pow(2, retryCount) * 1000
      retryTimer = setTimeout(() => loadData(retryCount + 1), delay)
    } else {
      error.value = '加载K线数据失败: ' + e.message
      emit('error', e.message)
      loading.value = false
    }
  }
}

let resizeTimer = null
function handleResize() {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => {
    if (chart && chartContainer.value) {
      chart.applyOptions({ width: chartContainer.value.clientWidth })
    }
  }, 200)
}

onUnmounted(() => {
  clearTimeout(resizeTimer)
  clearTimeout(rangeChangeTimer)
  clearTimeout(retryTimer)
  if (currentAbortController) currentAbortController.abort()
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
  window.removeEventListener('resize', handleResize)
  if (crosshairMovedUnsub) crosshairMovedUnsub()
  if (rangeChangeUnsub) rangeChangeUnsub()
  if (brandingObserver) brandingObserver.disconnect()
  if (chart) chart.remove()
})

function handleRetry() {
  error.value = ''
  loading.value = false  // 重置加载状态，确保按钮可用
  clearTimeout(retryTimer)  // 清除可能的自动重试定时器
  if (currentAbortController) currentAbortController.abort()  // 取消之前的请求
  loadData()
}

defineExpose({ loadData })
</script>

<style scoped>
.kline-chart-wrapper {
  position: relative;
  width: 100%;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}

.ma-legend {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  font-size: 12px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.ma-item {
  cursor: pointer;
  user-select: none;
  color: #909399;
  transition: opacity 0.2s;
}

.ma-item.active {
  color: var(--ma-color);
  font-weight: 600;
}

.ma-item:not(.active) {
  opacity: 0.4;
  text-decoration: line-through;
}

.ma-item:hover {
  opacity: 0.8;
}

.ma-value {
  font-family: monospace;
}

.chart-container {
  width: 100%;
  height: v-bind('props.height + "px"');
}

.chart-container :deep(.tv-lightweight-charts > div:first-child) {
  display: none !important;
}

.kline-tooltip {
  position: absolute;
  z-index: 10;
  top: 8px;
  left: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 2px 8px rgba(0,0,0,0.12);
  font-size: 12px;
  line-height: 1.7;
  pointer-events: none;
  white-space: nowrap;
  display: none;
  font-family: 'Microsoft YaHei', sans-serif;
}

.chart-loading, .chart-error {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 12px 24px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.85);
  font-size: 14px;
  z-index: 5;
}

.chart-loading { color: #409eff; }
.chart-error { color: #f56c6c; flex-direction: column; }
</style>
