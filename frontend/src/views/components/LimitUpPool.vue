<template>
  <section class="card-section">
    <div class="section-head" v-if="!noHeader">
      <h3 class="section-title"><el-icon><Lightning /></el-icon>涨停揭秘</h3>
      <div class="meta-chips" v-if="summary">
        <span class="chip chip-hot"><b>{{ summary.total }}</b> 家涨停</span>
        <span class="chip chip-board"><b>{{ summary.max_continuous }}</b> 连板</span>
        <span v-if="summary.total_sealed_yi" class="chip chip-seal"><b>{{ formatYi(summary.total_sealed_yi) }}</b> 亿封单</span>
      </div>
    </div>

    <div v-if="loading && !stocks.length" class="skeleton-wrap">
      <el-skeleton :count="1" animated>
        <template #template>
          <div class="sk-row" v-for="i in 5" :key="i">
            <el-skeleton-item variant="text" style="width: 70px;" />
            <el-skeleton-item variant="text" style="width: 80px; margin-left: 12px;" />
            <el-skeleton-item variant="text" style="width: 50px; margin-left: 12px;" />
          </div>
        </template>
      </el-skeleton>
    </div>

    <div v-else-if="!stocks.length" class="empty-hint">
      <span>当前无涨停股</span>
      <span class="empty-sub">非交易时段或市场未触发涨停</span>
    </div>

    <div v-else>
      <!-- 板型分布 -->
      <div class="pattern-bar" v-if="summary?.patterns">
        <div
          v-for="(count, name) in summary.patterns"
          :key="name"
          class="pattern-chip"
          :class="['pat-' + name]"
        >
          <span class="pat-name">{{ name }}</span>
          <span class="pat-count">{{ count }}</span>
        </div>
      </div>

      <!-- 涨停股表格 -->
      <div class="limit-table">
        <div class="lt-head">
          <span class="lt-col-name">名称/代码</span>
          <span class="lt-col-pct">涨跌幅</span>
          <span class="lt-col-seal">封单(亿)</span>
          <span class="lt-col-board">板型</span>
          <span class="lt-col-reason">涨停原因</span>
        </div>
        <div class="lt-body">
          <div
            v-for="(s, i) in stocks"
            :key="s.code || i"
            class="lt-row"
          >
            <div class="lt-col-name">
              <span class="lt-rank" :class="rankClass(i)">{{ i + 1 }}</span>
              <span class="lt-name" :title="`${s.name} (${s.code})`">{{ s.name }}<small v-if="s.code"> {{ s.code }}</small></span>
            </div>
            <div class="lt-col-pct">
              <span class="lt-pct up">{{ formatPct(s.change_pct) }}%</span>
            </div>
            <div v-if="s.sealed_amount_yi" class="lt-col-seal">
              <span class="lt-seal" :class="sealClass(s.sealed_amount_yi)">{{ formatYi(s.sealed_amount_yi) }}</span>
            </div>
            <div v-else class="lt-col-seal">—</div>
            <div class="lt-col-board">
              <span class="lt-pattern" :class="['pat-' + s.pattern]">{{ s.pattern || '—' }}</span>
              <span class="lt-continuous" v-if="s.continuous_limit_num > 1">
                {{ s.continuous_limit_num }}连板
              </span>
            </div>
            <div class="lt-col-reason" :title="getReason(s)">
              <span class="lt-reason">{{ getReason(s) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { Lightning } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false },
  noHeader: { type: Boolean, default: false },
})

const summary = computed(() => props.data?.patterns ? props.data : null)
const stocks = computed(() => props.data?.stocks || [])

function getReason(s) {
  if (s.reason && s.reason !== '—') return s.reason
  if (s.industry) return s.industry
  const tag = s.change_tag ? { FIRST_LIMIT: '首板涨停', LIMIT_BACK: '开板回封', HIGH_LIMIT: '高位涨停', T_LIMIT: 'T字涨停' }[s.change_tag] : ''
  return tag || '—'
}

const formatPct = (v) => (Number(v) || 0).toFixed(2)
const formatYi = (v) => {
  const n = Number(v) || 0
  if (n === 0) return '—'
  if (n >= 10) return n.toFixed(1)
  return n.toFixed(2)
}
const rankClass = (i) => {
  if (i === 0) return 'rk-1'
  if (i === 1) return 'rk-2'
  if (i === 2) return 'rk-3'
  return ''
}
const sealClass = (v) => {
  const n = Number(v) || 0
  if (n >= 5) return 'seal-strong'
  if (n >= 1) return 'seal-mid'
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
  border-left: 3px solid #f56c6c;
  line-height: 1;
  display: flex;
  align-items: center;
  gap: 6px;
}
.section-title .el-icon { color: #f56c6c; font-size: 16px; }

.meta-chips {
  display: inline-flex;
  gap: 6px;
  flex-wrap: wrap;
}
.chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
  color: #606266;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
}
.chip b { font-weight: 700; font-variant-numeric: tabular-nums; }
.chip-hot b { color: #f56c6c; }
.chip-board b { color: #e6a23c; }
.chip-seal b { color: #409eff; }

.empty-hint, .skeleton-wrap {
  text-align: center;
  padding: 28px 0;
  color: #c0c4cc;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.empty-sub { font-size: 11px; color: #dcdfe6; }

.skeleton-wrap .sk-row {
  display: flex;
  padding: 6px 0;
  border-bottom: 1px solid #f5f5f5;
}

/* 板型分布 */
.pattern-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  padding: 10px 12px;
  background: linear-gradient(135deg, #fef2f2, #fff7ed);
  border-radius: 8px;
  border: 1px solid #fef0f0;
}
.pattern-chip {
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
.pat-name { color: #606266; }
.pat-count { color: #303133; font-weight: 700; font-variant-numeric: tabular-nums; font-size: 13px; }
.pat-一字 .pat-name, .pat-一字 { color: #c45656; background: #fef0f0; border-color: #fbc4c4; }
.pat-开板 .pat-name, .pat-开板 { color: #b88230; background: #fdf6ec; border-color: #f5dab1; }
.pat-连板 .pat-name, .pat-连板 { color: #b91c1c; background: #fef2f2; border-color: #fecaca; font-weight: 600; }
.pat-换手 .pat-name, .pat-换手 { color: #67c23a; background: #f0f9eb; border-color: #c2e7b0; }

/* 表格 */
.limit-table {
  border-radius: 6px;
  overflow: hidden;
}

.lt-head, .lt-row {
  display: grid;
  grid-template-columns: 1.8fr 0.7fr 0.7fr 0.9fr 1.4fr;
  align-items: center;
  padding: 9px 14px;
  font-size: 12.5px;
}
.lt-head {
  background: linear-gradient(180deg, #fafbfc, #f5f7fa);
  color: #606266;
  font-weight: 600;
  border-bottom: 2px solid #ebeef5;
}

/* 可滚动区域 */
.lt-body {
  max-height: 480px;
  overflow-y: auto;
}
.lt-body::-webkit-scrollbar { width: 4px; }
.lt-body::-webkit-scrollbar-thumb { background: #e0e0e0; border-radius: 2px; }
.lt-body::-webkit-scrollbar-track { background: transparent; }

.lt-row {
  border-bottom: 1px solid #f5f7fa;
  transition: background 0.12s;
}
.lt-row:last-child { border-bottom: none; }
.lt-row:hover { background: linear-gradient(90deg, #fef2f2, #fff); }

.lt-col-name { display: flex; align-items: center; gap: 8px; min-width: 0; }
.lt-rank {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #f0f2f5;
  color: #909399;
  font-size: 11px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.lt-rank.rk-1 { background: linear-gradient(135deg, #f56c6c, #e74c3c); color: #fff; box-shadow: 0 2px 4px rgba(245,108,108,0.3); }
.lt-rank.rk-2 { background: linear-gradient(135deg, #e6a23c, #f0a040); color: #fff; box-shadow: 0 2px 4px rgba(230,162,60,0.3); }
.lt-rank.rk-3 { background: linear-gradient(135deg, #f0a040, #e8960c); color: #fff; box-shadow: 0 2px 4px rgba(240,160,64,0.3); }
.lt-name {
  color: #303133;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.lt-col-pct { text-align: right; }
.lt-pct { font-weight: 700; font-variant-numeric: tabular-nums; }
.lt-pct.up { color: #f56c6c; }

.lt-col-seal { text-align: right; }
.lt-seal { color: #303133; font-variant-numeric: tabular-nums; font-weight: 500; }
.seal-strong { color: #f56c6c !important; font-weight: 700 !important; }
.seal-mid { color: #e6a23c !important; font-weight: 600 !important; }

.lt-col-board {
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: flex-start;
}
.lt-pattern {
  display: inline-block;
  padding: 2px 7px;
  font-size: 10.5px;
  border-radius: 4px;
  font-weight: 600;
  border: 1px solid;
}
.lt-pattern.pat-一字 { color: #c45656; background: #fef0f0; border-color: #fbc4c4; }
.lt-pattern.pat-开板 { color: #b88230; background: #fdf6ec; border-color: #f5dab1; }
.lt-pattern.pat-连板 { color: #b91c1c; background: #fef2f2; border-color: #fecaca; }
.lt-pattern.pat-换手 { color: #67c23a; background: #f0f9eb; border-color: #c2e7b0; }
.lt-continuous {
  font-size: 10.5px;
  color: #b91c1c;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}



.lt-col-reason { min-width: 0; padding-left: 4px; }
.lt-reason {
  color: #606266;
  font-size: 12px;
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 1100px) {
  .lt-head, .lt-row { grid-template-columns: 1.5fr 0.7fr 0.7fr 0.9fr 1.3fr; padding: 7px 10px; }
  .lt-body { max-height: 400px; }
}
@media (max-width: 768px) {
  .lt-head, .lt-row {
    grid-template-columns: 1.3fr 0.65fr 0.65fr 0.85fr 1.4fr;
    font-size: 12px;
    padding: 6px 8px;
  }
  .lt-body { max-height: 280px; }
}
</style>
