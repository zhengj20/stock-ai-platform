<template>
  <section class="card-section">
    <div class="section-head" v-if="!noHeader">
      <h3 class="section-title"><el-icon><TrendCharts /></el-icon>同花顺热门榜</h3>
      <span class="meta" v-if="stocks.length">综合热度 Top {{ stocks.length }} · 含人工归因</span>
    </div>

    <div v-if="loading && !stocks.length" class="skeleton-wrap">
      <el-skeleton :count="1" animated>
        <template #template>
          <div v-for="i in 6" :key="i" class="sk-row">
            <el-skeleton-item variant="text" style="width: 18px;" />
            <el-skeleton-item variant="text" style="width: 70px; margin-left: 10px;" />
            <el-skeleton-item variant="text" style="width: 50px; margin-left: 10px;" />
            <el-skeleton-item variant="text" style="width: 200px; margin-left: 12px;" />
          </div>
        </template>
      </el-skeleton>
    </div>

    <div v-else-if="!stocks.length" class="empty-hint">暂无热榜数据</div>

    <div v-else>
      <!-- 热度分布 -->
      <div class="heat-bar" v-if="heatStats.total > 0">
        <div class="heat-chip chip-up"><span class="chip-label">上涨</span><span class="chip-count">{{ heatStats.up }}</span></div>
        <div class="heat-chip chip-down"><span class="chip-label">下跌</span><span class="chip-count">{{ heatStats.down }}</span></div>
        <div class="heat-chip chip-hot"><span class="chip-label">高热(≥70)</span><span class="chip-count">{{ heatStats.hot }}</span></div>
      </div>

      <div class="hot-grid">
        <div class="hot-head">
          <span class="hot-col-rank">#</span>
          <span class="hot-col-name">名称</span>
          <span class="hot-col-score">热度</span>
        </div>
        <div class="hot-body">
        <div
          v-for="(s, i) in stocks"
          :key="s.code || i"
          class="hot-row"
        >
          <div class="hot-rank" :class="rankClass(i)">{{ i + 1 }}</div>
          <div class="hot-name-block">
            <div class="hot-name-line">
              <span class="hot-name" :title="s.code">{{ s.name }}</span>
              <span
                v-if="hasRealPct(s)"
                class="hot-pct"
                :class="s.pct_change >= 0 ? 'up' : 'down'"
              >
                {{ s.pct_change >= 0 ? '+' : '' }}{{ formatPct(s.pct_change) }}%
              </span>
              <span v-else class="hot-pct" :class="s.composite_score >= 70 ? 'up' : 'flat'">
                🔥 {{ Math.round(s.composite_score) }}
              </span>
            </div>
            <div class="hot-reason-line" v-if="s.reason || s.tag">
              <span class="hot-reason" :title="s.reason">{{ s.reason || s.tag }}</span>
            </div>
          </div>
          <div class="hot-score" :title="`综合评分 ${s.composite_score}`">
            <span class="score-bar">
              <span class="score-fill" :style="{ width: Math.min(100, s.composite_score) + '%' }"></span>
            </span>
          </div>
        </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { TrendCharts } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false },
  noHeader: { type: Boolean, default: false },
})

const stocks = computed(() => (props.data?.stocks || []).slice(0, 12))

// 热度分布统计
const heatStats = computed(() => {
  const all = props.data?.stocks || []
  let up = 0, down = 0, hot = 0
  for (const s of all) {
    const pct = Number(s?.pct_change)
    if (!isNaN(pct) && pct !== 0) {
      if (pct > 0) up++
      else down++
    }
    const score = Number(s?.composite_score) || 0
    if (score >= 70) hot++
  }
  return { total: all.length, up, down, hot }
})

// 判断是否有真实涨跌幅（非 0/缺失）
const hasRealPct = (s) => {
  const v = Number(s?.pct_change)
  return Number.isFinite(v) && v !== 0
}

const formatPct = (v) => (Number(v) || 0).toFixed(2)
const rankClass = (i) => {
  if (i === 0) return 'rk-1'
  if (i === 1) return 'rk-2'
  if (i === 2) return 'rk-3'
  return ''
}
</script>

<style scoped>
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 8px;
}
.section-title {
  font-size: 15px;
  font-weight: 700;
  color: #303133;
  margin: 0;
  padding-left: 10px;
  border-left: 3px solid #409eff;
  line-height: 1;
  display: flex;
  align-items: center;
  gap: 6px;
}
.section-title .el-icon { color: #409eff; font-size: 16px; }
.meta { font-size: 12px; color: #909399; }

.empty-hint, .skeleton-wrap {
  text-align: center;
  padding: 28px 0;
  color: #c0c4cc;
  font-size: 13px;
}
.sk-row { display: flex; padding: 5px 0; border-bottom: 1px solid #f5f5f5; }

/* 热度分布 */
.heat-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  padding: 10px 12px;
  background: linear-gradient(135deg, #e8f4fd, #f0f9ff);
  border-radius: 8px;
  border: 1px solid #d6ecfa;
}
.heat-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
  background: #fff;
  border: 1px solid #ebeef5;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.chip-label { color: #606266; }
.chip-count { color: #303133; font-weight: 700; font-variant-numeric: tabular-nums; font-size: 13px; }
.chip-up .chip-count { color: #f56c6c; }
.chip-down .chip-count { color: #67c23a; }
.chip-hot .chip-count { color: #e6a23c; }

.hot-grid {
  border-radius: 6px;
  overflow: hidden;
}

/* 表头 */
.hot-head {
  display: grid;
  grid-template-columns: 26px 1fr 56px;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  background: linear-gradient(180deg, #fafbfc, #f5f7fa);
  color: #606266;
  font-weight: 600;
  font-size: 12.5px;
  border-bottom: 2px solid #ebeef5;
}

/* 可滚动区域 */
.hot-body {
  max-height: 480px;
  overflow-y: auto;
}
.hot-body::-webkit-scrollbar { width: 4px; }
.hot-body::-webkit-scrollbar-thumb { background: #e0e0e0; border-radius: 2px; }
.hot-body::-webkit-scrollbar-track { background: transparent; }

.hot-row {
  display: grid;
  grid-template-columns: 26px 1fr 56px;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid #f5f7fa;
  transition: background 0.12s;
}
.hot-row:last-child { border-bottom: none; }
.hot-row:hover { background: linear-gradient(90deg, #e8f4fd, #fff); }

/* 列宽对齐（与表头一致） */
.hot-col-rank { width: 26px; text-align: center; }

.hot-rank {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: #f0f2f5;
  color: #909399;
  font-size: 11.5px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-variant-numeric: tabular-nums;
}
.hot-rank.rk-1 { background: linear-gradient(135deg, #f56c6c, #e74c3c); color: #fff; box-shadow: 0 2px 6px rgba(245,108,108,0.3); }
.hot-rank.rk-2 { background: linear-gradient(135deg, #e6a23c, #f0a040); color: #fff; box-shadow: 0 2px 6px rgba(230,162,60,0.3); }
.hot-rank.rk-3 { background: linear-gradient(135deg, #409eff, #3a8ee6); color: #fff; box-shadow: 0 2px 6px rgba(64,158,255,0.3); }

.hot-name-block { min-width: 0; }
.hot-name-line { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.hot-name {
  color: #303133;
  font-weight: 600;
  font-size: 13.5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hot-pct { font-size: 12.5px; font-weight: 700; font-variant-numeric: tabular-nums; flex-shrink: 0; }
.hot-pct.up { color: #f56c6c; }
.hot-pct.down { color: #67c23a; }
.hot-pct.flat { color: #e6a23c; font-weight: 600; font-size: 12px; }

.hot-reason-line { margin-top: 3px; min-width: 0; }
.hot-reason {
  font-size: 11.5px;
  color: #86909c;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}

.hot-score { display: flex; align-items: center; gap: 6px; }
.score-bar {
  flex: 1;
  height: 5px;
  background: #f0f2f5;
  border-radius: 3px;
  overflow: hidden;
}
.score-fill {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #409eff 0%, #67c23a 50%, #f56c6c 100%);
  border-radius: 3px;
  transition: width 0.3s ease;
}

@media (max-width: 1100px) {
  .hot-body { max-height: 400px; }
}

@media (max-width: 768px) {
  .hot-head { grid-template-columns: 20px 1fr; padding: 8px 10px; gap: 8px; }
  .hot-col-score { display: none; }
  .hot-row { grid-template-columns: 20px 1fr; padding: 8px 10px; gap: 8px; }
  .hot-score { display: none; }
  .hot-body { max-height: 280px; }
}
</style>
