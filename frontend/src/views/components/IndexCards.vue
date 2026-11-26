<template>
  <section class="card-section">
    <div v-if="loading && !indices.length" class="skeleton-bar">
      <el-skeleton :count="1" animated>
        <template #template>
          <div class="sk-grid">
            <div v-for="i in 6" :key="i" class="sk-card">
              <el-skeleton-item variant="text" style="width: 50px; height: 12px;" />
              <el-skeleton-item variant="text" style="width: 70px; height: 18px; margin-top: 6px;" />
              <el-skeleton-item variant="rect" style="width: 100%; height: 32px; margin-top: 8px; border-radius: 4px;" />
            </div>
          </div>
        </template>
      </el-skeleton>
    </div>

    <div v-else-if="!indices.length" class="empty-hint">暂无指数数据</div>

    <div v-else class="index-grid">
      <div
        v-for="idx in indices"
        :key="idx.code"
        class="index-card"
        :class="idx.change_pct >= 0 ? 'up' : 'down'"
      >
        <div class="ic-header">
          <span class="ic-name">{{ idx.name }}</span>
          <span class="ic-code">{{ idx.code }}</span>
        </div>
        <div class="ic-body">
          <span class="ic-price">{{ formatPrice(idx.price) }}</span>
          <span class="ic-change" :class="idx.change_pct >= 0 ? 'up' : 'down'">
            {{ idx.change_pct >= 0 ? '+' : '' }}{{ formatPct(idx.change_pct) }}%
          </span>
        </div>
        <div v-if="idx.kline && idx.kline.length > 1" class="ic-chart">
          <MiniSparkline
            :data="idx.kline"
            :color="idx.change_pct >= 0 ? '#f56c6c' : '#67c23a'"
          />
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { h, defineComponent, computed } from 'vue'

const MiniSparkline = defineComponent({
  name: 'MiniSparkline',
  props: {
    data: { type: Array, required: true },
    color: { type: String, default: '#f56c6c' },
  },
  setup(props) {
    const W = 120
    const H = 36
    const PAD = { top: 4, bottom: 4, left: 0, right: 0 }

    const svgData = computed(() => {
      const closes = props.data.map(k => Number(k.close) || 0).filter(x => x > 0)
      if (closes.length < 2) return null

      const min = Math.min(...closes)
      const max = Math.max(...closes)
      const range = max - min || 1
      const innerW = W - PAD.left - PAD.right
      const innerH = H - PAD.top - PAD.bottom
      const stepX = innerW / (closes.length - 1)

      const points = closes.map((c, i) => ({
        x: PAD.left + i * stepX,
        y: PAD.top + innerH - ((c - min) / range) * innerH,
      }))

      // Line path
      const linePath = points.map((p, i) =>
        `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`
      ).join(' ')

      // Area path (closed for fill)
      const areaPath = linePath +
        ` L ${points[points.length - 1].x.toFixed(1)} ${(H - PAD.bottom).toFixed(1)}` +
        ` L ${points[0].x.toFixed(1)} ${(H - PAD.bottom).toFixed(1)} Z`

      // End dot
      const last = points[points.length - 1]

      // 昨收参考线（数据第一个点=昨收或昨开盘附近）
      const refY = PAD.top + innerH - ((closes[0] - min) / range) * innerH

      return { linePath, areaPath, last, refY }
    })

    return () => {
      if (!svgData.value) return h('span', { class: 'no-data' }, '--')
      const { linePath, areaPath, last, refY } = svgData.value
      const color = props.color
      const gradientId = `grad-${color.replace('#', '')}`

      return h('svg', { width: W, height: H, viewBox: `0 0 ${W} ${H}`, class: 'spark-svg' }, [
        // Gradient definition
        h('defs', null, [
          h('linearGradient', { id: gradientId, x1: '0', y1: '0', x2: '0', y2: '1' }, [
            h('stop', { offset: '0%', 'stop-color': color, 'stop-opacity': '0.25' }),
            h('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': '0.02' }),
          ]),
        ]),
        // Area fill
        h('path', { d: areaPath, fill: `url(#${gradientId})` }),
        // 昨收参考线（虚线）
        h('line', {
          x1: 0, y1: refY, x2: W, y2: refY,
          stroke: '#909399', 'stroke-width': '0.5', 'stroke-dasharray': '2,2', opacity: '0.5',
        }),
        // Line
        h('path', {
          d: linePath,
          fill: 'none',
          stroke: color,
          'stroke-width': '1.5',
          'stroke-linecap': 'round',
          'stroke-linejoin': 'round',
        }),
        // End dot
        h('circle', {
          cx: last.x,
          cy: last.y,
          r: '2',
          fill: color,
        }),
      ])
    }
  },
})

defineProps({
  indices: { type: Array, required: true },
  loading: { type: Boolean, default: false },
})

const formatPrice = (v) => (Number(v) || 0).toFixed(2)
const formatPct = (v) => (Number(v) || 0).toFixed(2)
</script>

<style scoped>
.skeleton-bar {
  background: #fff;
  border-radius: 8px;
  padding: 14px 20px;
  box-shadow: 0 2px 12px rgba(0,0,0,.06);
}
.sk-grid { display: flex; gap: 0; overflow-x: auto; }
.sk-card { flex: 0 0 132px; padding: 4px 0; }

.empty-hint { text-align: center; padding: 30px 0; color: #c0c4cc; font-size: 13px; }

/* Horizontal scroll strip */
.index-grid {
  display: flex;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
  -ms-overflow-style: none;
  background: #fff;
  border-radius: 8px;
  padding: 0;
  box-shadow: 0 2px 12px rgba(0,0,0,.06);
}
.index-grid::-webkit-scrollbar { display: none; }

/* Card - vertical layout */
.index-card {
  flex: 0 0 132px;
  scroll-snap-align: start;
  display: flex;
  flex-direction: column;
  padding: 10px 12px 8px;
  border-right: 1px solid #f5f5f5;
  transition: background .15s;
}
.index-card:last-child { border-right: none; }
.index-card:hover { background: #fafafa; }

.ic-header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 4px; }
.ic-name { color: #303133; font-size: 12.5px; font-weight: 600; white-space: nowrap; }
.ic-code { color: #c0c4cc; font-size: 10px; }

.ic-body { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 6px; min-height: 24px; }
.ic-price {
  font-size: 17px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.3px;
}
.index-card.up .ic-price { color: #f56c6c; }
.index-card.down .ic-price { color: #67c23a; }

.ic-change {
  font-size: 11.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.ic-change.up { color: #f56c6c; }
.ic-change.down { color: #67c23a; }

.ic-chart { margin-top: auto; }
.spark-svg { display: block; width: 100%; height: auto; }
.no-data { color: #c0c4cc; font-size: 11px; }

@media (max-width: 768px) {
  .index-card { flex: 0 0 120px; padding: 8px 10px 6px; }
  .ic-name { font-size: 11.5px; }
  .ic-price { font-size: 15px; }
}
</style>
