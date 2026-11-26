<template>
  <div class="industry-chain">
    <!-- Loading -->
    <div v-if="loading || !hasData" class="loading-container">
      <el-skeleton :rows="8" animated />
    </div>

    <!-- Error -->
    <el-alert v-else-if="error" :title="error" type="error" show-icon :closable="false" class="mb-4">
      <template #default>
        <div class="error-message">{{ error }}</div>
      </template>
    </el-alert>
    <div v-if="error" class="retry-container">
      <el-button type="primary" size="small" :icon="Refresh" @click="fetchData">重新加载</el-button>
    </div>

    <div v-else-if="hasData && !error" class="chain-scroll-area">
      <!-- 刷新时显示骨架屏覆盖层（后台静默刷新或手动刷新） -->
      <div v-if="refreshing || loading" class="skeleton-overlay">
        <el-skeleton :rows="6" animated />
      </div>
      <!-- Top Toolbar -->
      <div class="chain-toolbar">
        <div class="toolbar-left">
          <el-input
            v-model="searchKeyword"
            placeholder="搜索产业链名称"
            clearable
            prefix-icon="Search"
            class="search-input"
          />
          <span class="chain-count">共 {{ chains.length }} 条产业链</span>
        </div>
        <div class="toolbar-right">
          <el-radio-group v-model="sortBy" size="small">
            <el-radio-button value="heat">热度排序</el-radio-button>
            <el-radio-button value="change">涨幅排序</el-radio-button>
            <el-radio-button value="turnover">成交额排序</el-radio-button>
          </el-radio-group>
        </div>
      </div>

      <!-- 热门产业链概览（Top5 卡片） -->
      <div v-if="topHotChains.length > 0" class="section-title">
        <span class="title-icon">🔥</span>
        热门产业链 TOP 5
      </div>
      <div class="hot-chains-grid">
        <div v-for="(chain, idx) in topHotChains" :key="'hot-' + idx"
             class="hot-chain-card"
             :class="{ 'is-up': chain.chain_avg_change >= 0, 'is-down': chain.chain_avg_change < 0 }"
             @click="scrollToChain(chain.chain)">
          <div class="hot-card-header">
            <span class="hot-rank">TOP {{ idx + 1 }}</span>
            <span class="hot-score">热度 {{ chain.heat_score }}</span>
          </div>
          <div class="hot-card-body">
            <div class="hot-chain-name">{{ chain.chain }}</div>
            <div class="hot-chain-change" :class="chain.chain_avg_change >= 0 ? 'up' : 'down'">
              {{ chain.chain_avg_change >= 0 ? '+' : '' }}{{ chain.chain_avg_change?.toFixed(2) }}%
            </div>
          </div>
          <div class="hot-card-footer">
            <span class="stage-tag up">上{{ chain.stages_avg?.upstream?.toFixed(1) }}%</span>
            <span class="stage-tag mid">中{{ chain.stages_avg?.midstream?.toFixed(1) }}%</span>
            <span class="stage-tag down">下{{ chain.stages_avg?.downstream?.toFixed(1) }}%</span>
          </div>
          <div v-if="chain.leading_stage" class="leading-badge">
            领涨: {{ chain.leading_stage }}
          </div>
        </div>
      </div>

      <!-- 产业链详情卡片（默认展开） -->
      <div class="section-title detail-toggle" @click="showDetails = !showDetails">
        <span class="title-icon">📊</span>
        产业链详情 {{ showDetails ? '▲' : '▼' }}
      </div>
      <template v-if="showDetails">
        <div v-for="(chain, idx) in sortedChains" :key="idx" class="chain-card" :id="'chain-' + chain.chain">
          <!-- Chain Header -->
          <div class="chain-header">
            <div class="chain-title-row">
              <h3>{{ chain.chain }}产业链</h3>
              <div class="chain-header-right">
                <span class="heat-badge" :class="heatClass(chain.heat_score)">
                  热度 {{ chain.heat_score }}
                </span>
                <span class="chain-avg-change" :class="chain.chain_avg_change >= 0 ? 'up' : 'down'">
                  平均 {{ chain.chain_avg_change >= 0 ? '+' : '' }}{{ chain.chain_avg_change?.toFixed(2) }}%
                </span>
              </div>
            </div>

            <!-- 关键指标 -->
            <div class="chain-metrics">
              <div class="metric-item">
                <span class="metric-label">领涨环节</span>
                <span class="metric-value lead">{{ chain.leading_stage || '-' }}</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">滞涨环节</span>
                <span class="metric-value lag">{{ chain.lagging_stage || '-' }}</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">联动一致性</span>
                <span class="metric-value">{{ chain.direction_score }}%</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">资金一致性</span>
                <span class="metric-value" :class="chain.flow_consistency >= 60 ? 'up' : 'down'">
                  {{ chain.flow_consistency }}%
                </span>
              </div>
              <div class="metric-item">
                <span class="metric-label">总成交额</span>
                <span class="metric-value">{{ chain.chain_total_turnover?.toFixed(1) }}亿</span>
              </div>
              <div class="metric-item">
                <span class="metric-label">净流入</span>
                <span class="metric-value" :class="chain.chain_total_flow >= 0 ? 'up' : 'down'">
                  {{ chain.chain_total_flow >= 0 ? '+' : '' }}{{ chain.chain_total_flow?.toFixed(1) }}亿
                </span>
              </div>
            </div>

            <el-alert
              v-if="chain.transmission_signal"
              :title="chain.transmission_signal"
              type="warning"
              :closable="false"
              show-icon
              class="signal-alert"
            />
          </div>

          <!-- Chain Stages (Horizontal Layout) -->
          <div class="chain-stages-horizontal">
            <!-- Upstream -->
            <div class="chain-stage-card upstream">
              <div class="stage-header">
                <span class="stage-icon">⬆</span>
                <span class="stage-title">上游</span>
                <span class="stage-avg" :class="chain.stages_avg?.upstream >= 0 ? 'up' : 'down'">
                  {{ chain.stages_avg?.upstream >= 0 ? '+' : '' }}{{ chain.stages_avg?.upstream?.toFixed(2) }}%
                </span>
              </div>
              <div class="stage-sub-info">
                <span>成交额: {{ chain.stages_turnover?.upstream?.toFixed(1) }}亿</span>
                <span>广度: {{ chain.stages_breadth?.upstream?.toFixed(0) }}%</span>
              </div>
              <div v-if="chain.upstream.length === 0" class="empty-stage">
                <el-icon><InfoFilled /></el-icon>
                <span>暂无实时数据</span>
              </div>
              <div v-else class="stage-sectors-grid">
                <div v-for="(s, si) in chain.upstream" :key="si"
                     class="sector-chip"
                     :class="[s.change_pct >= 0 ? 'up' : 'down', getHeatClass(s.change_pct)]">
                  <span class="chip-name">{{ s.name }}</span>
                  <span class="chip-pct">{{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct?.toFixed(2) || '-' }}%</span>
                  <span class="chip-amount">{{ s.turnover_yi?.toFixed(1) || '-' }}亿</span>
                </div>
              </div>
            </div>

            <!-- Arrow -->
            <div class="chain-arrow-h">
              <div class="arrow-line"></div>
              <div class="arrow-icon">→</div>
            </div>

            <!-- Midstream -->
            <div class="chain-stage-card midstream">
              <div class="stage-header">
                <span class="stage-icon">●</span>
                <span class="stage-title">中游</span>
                <span class="stage-avg" :class="chain.stages_avg?.midstream >= 0 ? 'up' : 'down'">
                  {{ chain.stages_avg?.midstream >= 0 ? '+' : '' }}{{ chain.stages_avg?.midstream?.toFixed(2) }}%
                </span>
              </div>
              <div class="stage-sub-info">
                <span>成交额: {{ chain.stages_turnover?.midstream?.toFixed(1) }}亿</span>
                <span>广度: {{ chain.stages_breadth?.midstream?.toFixed(0) }}%</span>
              </div>
              <div v-if="chain.midstream.length === 0" class="empty-stage">
                <el-icon><InfoFilled /></el-icon>
                <span>暂无实时数据</span>
              </div>
              <div v-else class="stage-sectors-grid">
                <div v-for="(s, si) in chain.midstream" :key="si"
                     class="sector-chip"
                     :class="[s.change_pct >= 0 ? 'up' : 'down', getHeatClass(s.change_pct)]">
                  <span class="chip-name">{{ s.name }}</span>
                  <span class="chip-pct">{{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct?.toFixed(2) || '-' }}%</span>
                  <span class="chip-amount">{{ s.turnover_yi?.toFixed(1) || '-' }}亿</span>
                </div>
              </div>
            </div>

            <!-- Arrow -->
            <div class="chain-arrow-h">
              <div class="arrow-line"></div>
              <div class="arrow-icon">→</div>
            </div>

            <!-- Downstream -->
            <div class="chain-stage-card downstream">
              <div class="stage-header">
                <span class="stage-icon">⬇</span>
                <span class="stage-title">下游</span>
                <span class="stage-avg" :class="chain.stages_avg?.downstream >= 0 ? 'up' : 'down'">
                  {{ chain.stages_avg?.downstream >= 0 ? '+' : '' }}{{ chain.stages_avg?.downstream?.toFixed(2) }}%
                </span>
              </div>
              <div class="stage-sub-info">
                <span>成交额: {{ chain.stages_turnover?.downstream?.toFixed(1) }}亿</span>
                <span>广度: {{ chain.stages_breadth?.downstream?.toFixed(0) }}%</span>
              </div>
              <div v-if="chain.downstream.length === 0" class="empty-stage">
                <el-icon><InfoFilled /></el-icon>
                <span>暂无实时数据</span>
              </div>
              <div v-else class="stage-sectors-grid">
                <div v-for="(s, si) in chain.downstream" :key="si"
                     class="sector-chip"
                     :class="[s.change_pct >= 0 ? 'up' : 'down', getHeatClass(s.change_pct)]">
                  <span class="chip-name">{{ s.name }}</span>
                  <span class="chip-pct">{{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct?.toFixed(2) || '-' }}%</span>
                  <span class="chip-amount">{{ s.turnover_yi?.toFixed(1) || '-' }}亿</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 三列汇总表 -->
      <div class="section-title">
        <span class="title-icon">📋</span>
        产业链板块一览（汇总表）
      </div>
      <div class="table-wrapper">
        <el-table :data="sortedChains" stripe style="width: 100%" max-height="400" class="chain-table">
          <el-table-column label="产业链" width="120" fixed>
            <template #default="{ row }">
              <span class="chain-name-cell">{{ row.chain }}</span>
            </template>
          </el-table-column>
          <el-table-column label="热度" width="70" sortable :sort-by="'heat_score'">
            <template #default="{ row }">
              <span class="heat-badge-small" :class="heatClass(row.heat_score)">
                {{ row.heat_score || '-' }}
              </span>
            </template>
          </el-table-column>

          <el-table-column label="上游" min-width="220">
            <el-table-column label="板块" min-width="100">
              <template #default="{ row }">
                <div class="stage-cell">
                  <span v-for="(s, i) in row.upstream" :key="i" class="sector-tag">
                    {{ s.name }}
                  </span>
                  <span v-if="!row.upstream.length" class="empty-text">暂无数据</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="涨跌幅%" width="80">
              <template #default="{ row }">
                <div class="stage-cell pct-cell">
                  <span v-for="(s, i) in row.upstream" :key="i" class="pct-tag" :class="s.change_pct >= 0 ? 'up' : 'down'">
                    {{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct?.toFixed(2) || '-' }}
                  </span>
                  <span v-if="!row.upstream.length" class="empty-text">-</span>
                </div>
              </template>
            </el-table-column>
          </el-table-column>

          <el-table-column label="" width="40" align="center">
            <template #default>
              <span class="arrow-icon">→</span>
            </template>
          </el-table-column>

          <el-table-column label="中游" min-width="220">
            <el-table-column label="板块" min-width="100">
              <template #default="{ row }">
                <div class="stage-cell">
                  <span v-for="(s, i) in row.midstream" :key="i" class="sector-tag mid">
                    {{ s.name }}
                  </span>
                  <span v-if="!row.midstream.length" class="empty-text">暂无数据</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="涨跌幅%" width="80">
              <template #default="{ row }">
                <div class="stage-cell pct-cell">
                  <span v-for="(s, i) in row.midstream" :key="i" class="pct-tag" :class="s.change_pct >= 0 ? 'up' : 'down'">
                    {{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct?.toFixed(2) || '-' }}
                  </span>
                  <span v-if="!row.midstream.length" class="empty-text">-</span>
                </div>
              </template>
            </el-table-column>
          </el-table-column>

          <el-table-column label="" width="40" align="center">
            <template #default>
              <span class="arrow-icon">→</span>
            </template>
          </el-table-column>

          <el-table-column label="下游" min-width="220">
            <el-table-column label="板块" min-width="100">
              <template #default="{ row }">
                <div class="stage-cell">
                  <span v-for="(s, i) in row.downstream" :key="i" class="sector-tag down">
                    {{ s.name }}
                  </span>
                  <span v-if="!row.downstream.length" class="empty-text">暂无数据</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="涨跌幅%" width="80">
              <template #default="{ row }">
                <div class="stage-cell pct-cell">
                  <span v-for="(s, i) in row.downstream" :key="i" class="pct-tag" :class="s.change_pct >= 0 ? 'up' : 'down'">
                    {{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct?.toFixed(2) || '-' }}
                  </span>
                  <span v-if="!row.downstream.length" class="empty-text">-</span>
                </div>
              </template>
            </el-table-column>
          </el-table-column>

          <el-table-column label="传导信号" min-width="200">
            <template #default="{ row }">
              <span v-if="row.transmission_signal" class="signal-tag">{{ row.transmission_signal }}</span>
              <span v-else class="empty-text">-</span>
            </template>
          </el-table-column>

          <el-table-column label="领涨/滞涨" width="110">
            <template #default="{ row }">
              <div class="lead-lag-cell">
                <span class="lead-tag" v-if="row.leading_stage">领:{{ row.leading_stage }}</span>
                <span class="lag-tag" v-if="row.lagging_stage">滞:{{ row.lagging_stage }}</span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- No search results -->
      <el-empty v-if="sortedChains.length === 0 && searchKeyword" :description="emptyDescription" />
    </div>

    <transition name="empty-fade" v-else>
      <el-empty description="暂无产业链数据" />
    </transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { Refresh, Search, InfoFilled } from '@element-plus/icons-vue'
import { sectorAnalysisApi } from '@/api/index.js'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'

const emit = defineEmits(['loading', 'meta-update', 'loaded'])

const searchKeyword = ref('')
const showDetails = ref(true)
const sortBy = ref('heat')

const { data, loading, refreshing, error, refresh: cachedRefresh } = useCachedFetch({
  key: 'sector:industry-chain',
  fetcher: () => sectorAnalysisApi.getIndustryChain(),
  tier: CACHE_TIERS.STOCK,
  tradingAware: true,
  onSuccess: (result) => {
    if (result && !result.error) {
      emit('meta-update', { data_date: result.data_date, update_time: result.update_time })
    }
    return result
  },
})

const hasData = computed(() => {
  if (!data.value) return false
  const chains = data.value.chains || []
  return chains.length > 0
})

let chainLoadedEmitted = false
watch(hasData, (val) => {
  if (val && !chainLoadedEmitted) {
    chainLoadedEmitted = true
    emit('loaded')
  }
})

const chains = computed(() => data.value?.chains || [])

const filteredChains = computed(() => {
  if (!searchKeyword.value.trim()) return chains.value
  const kw = searchKeyword.value.trim().toLowerCase()
  return chains.value.filter(c => c.chain.toLowerCase().includes(kw))
})

const sortedChains = computed(() => {
  const list = [...filteredChains.value]
  switch (sortBy.value) {
    case 'change':
      return list.sort((a, b) => (b.chain_avg_change || 0) - (a.chain_avg_change || 0))
    case 'turnover':
      return list.sort((a, b) => (b.chain_total_turnover || 0) - (a.chain_total_turnover || 0))
    case 'heat':
    default:
      return list.sort((a, b) => (b.heat_score || 0) - (a.heat_score || 0))
  }
})

const topHotChains = computed(() => {
  return sortedChains.value.slice(0, 5)
})

const emptyDescription = computed(() => {
  return `未找到包含"${searchKeyword.value}"的产业链`
})

function heatClass(score) {
  if (!score && score !== 0) return ''
  if (score >= 70) return 'heat-high'
  if (score >= 45) return 'heat-mid'
  return 'heat-low'
}

function getHeatClass(pct) {
  if (pct == null) return ''
  if (pct >= 5) return 'heat-strong'
  if (pct >= 2) return 'heat-warm'
  if (pct >= 0) return 'heat-slight-up'
  if (pct >= -2) return 'heat-slight-down'
  return 'heat-cold'
}

function scrollToChain(chainName) {
  nextTick(() => {
    const el = document.getElementById('chain-' + chainName)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      el.classList.add('flash-highlight')
      setTimeout(() => el.classList.remove('flash-highlight'), 1500)
    }
  })
}

async function fetchData() {
  emit('loading', true)
  try {
    await cachedRefresh()
  } finally {
    emit('loading', false)
  }
}

defineExpose({ fetchData })
</script>

<style scoped>
.industry-chain {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.chain-scroll-area {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  position: relative;
}

.loading-container {
  max-width: 600px;
  margin: 40px auto;
}

/* Toolbar */
.chain-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}

.toolbar-right {
  display: flex;
  align-items: center;
}

.search-input {
  width: 280px;
  max-width: 50%;
}

.chain-count {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
}

/* Section Title */
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin: 10px 0 6px;
  padding-left: 8px;
  border-left: 3px solid #409eff;
  display: flex;
  align-items: center;
  gap: 6px;
}

.title-icon {
  font-size: 16px;
}

.detail-toggle {
  cursor: pointer;
  user-select: none;
}

.detail-toggle:hover {
  color: #409eff;
}

/* Hot Chains Grid */
.hot-chains-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
  margin-bottom: 6px;
}

.hot-chain-card {
  position: relative;
  background: linear-gradient(135deg, #fff 0%, #f8fafc 100%);
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.3s ease;
  overflow: hidden;
}

.hot-chain-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
}

.hot-chain-card.is-up {
  border-top: 3px solid #f56c6c;
}

.hot-chain-card.is-down {
  border-top: 3px solid #67c23a;
}

.hot-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.hot-rank {
  font-size: 10px;
  font-weight: 600;
  color: #909399;
  background: #f4f4f5;
  padding: 1px 6px;
  border-radius: 8px;
}

.hot-score {
  font-size: 10px;
  font-weight: 500;
  color: #e6a23c;
}

.hot-card-body {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 6px;
}

.hot-chain-name {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.hot-chain-change {
  font-size: 14px;
  font-weight: 700;
}

.hot-chain-change.up { color: #f56c6c; }
.hot-chain-change.down { color: #67c23a; }

.hot-card-footer {
  display: flex;
  gap: 4px;
}

.stage-tag {
  flex: 1;
  font-size: 9px;
  padding: 2px 3px;
  text-align: center;
  border-radius: 3px;
  background: #f5f7fa;
  color: #606266;
}

.leading-badge {
  position: absolute;
  top: 8px;
  right: -24px;
  background: #f56c6c;
  color: white;
  font-size: 10px;
  padding: 2px 28px;
  transform: rotate(45deg);
  font-weight: 500;
}

/* Table wrapper */
.table-wrapper {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin-bottom: 8px;
}

/* Chain table cell styles */
.stage-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.pct-cell {
  text-align: right;
  align-items: flex-end;
}

.sector-tag {
  font-size: 12px;
  font-weight: 500;
  color: #333;
  white-space: nowrap;
}

.sector-tag.mid {
  color: #67c23a;
}

.sector-tag.down {
  color: #e6a23c;
}

.pct-tag {
  font-size: 12px;
  font-weight: 600;
}

.amount-tag {
  font-size: 12px;
  color: #909399;
}

.empty-text {
  font-size: 12px;
  color: #c0c4cc;
}

.arrow-icon {
  font-size: 20px;
  color: #409eff;
  font-weight: bold;
}

.signal-tag {
  font-size: 12px;
  color: #e6a23c;
  font-weight: 500;
  line-height: 1.5;
  display: inline-block;
}

.chain-name-cell {
  font-weight: 600;
  color: #303133;
}

.heat-badge-small {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.heat-badge-small.heat-high { background: #fef0f0; color: #f56c6c; }
.heat-badge-small.heat-mid { background: #fdf6ec; color: #e6a23c; }
.heat-badge-small.heat-low { background: #f4f4f5; color: #909399; }

.lead-lag-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.lead-tag {
  font-size: 11px;
  color: #f56c6c;
  font-weight: 500;
}

.lag-tag {
  font-size: 11px;
  color: #909399;
  font-weight: 500;
}

/* Chain Card (Detail) */
.chain-card {
  border: 1px solid #e4e7ed;
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #fafbfc;
  transition: all 0.3s;
}

.chain-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}

.chain-card.flash-highlight {
  animation: flashBorder 1.5s ease;
}

@keyframes flashBorder {
  0% { box-shadow: 0 0 0 3px #409eff; }
  100% { box-shadow: none; }
}

.chain-header {
  margin-bottom: 10px;
}

.chain-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  gap: 12px;
  flex-wrap: wrap;
}

.chain-title-row h3 {
  margin: 0;
  font-size: 15px;
  color: #333;
  white-space: nowrap;
}

.chain-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.heat-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.heat-badge.heat-high { background: #fef0f0; color: #f56c6c; }
.heat-badge.heat-mid { background: #fdf6ec; color: #e6a23c; }
.heat-badge.heat-low { background: #f4f4f5; color: #909399; }

.chain-avg-change {
  font-size: 14px;
  font-weight: 700;
}
.chain-avg-change.up { color: #f56c6c; }
.chain-avg-change.down { color: #67c23a; }

/* Chain Metrics */
.chain-metrics {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 6px;
  margin-bottom: 8px;
  padding: 8px 10px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}

.metric-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: center;
}

.metric-label {
  font-size: 10px;
  color: #909399;
}

.metric-value {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.metric-value.lead { color: #f56c6c; }
.metric-value.lag { color: #909399; }
.metric-value.up { color: #f56c6c; }
.metric-value.down { color: #67c23a; }

.signal-alert {
  margin-top: 8px;
}

/* Horizontal Stages Layout */
.chain-stages-horizontal {
  display: grid;
  grid-template-columns: 1fr 32px 1fr 32px 1fr;
  gap: 0;
  align-items: stretch;
}

.chain-stage-card {
  background: #fff;
  border-radius: 6px;
  padding: 10px 12px;
  border: 1px solid #ebeef5;
}

.chain-stage-card.upstream {
  border-left: 3px solid #409eff;
}

.chain-stage-card.midstream {
  border-left: 3px solid #67c23a;
}

.chain-stage-card.downstream {
  border-left: 3px solid #e6a23c;
}

.stage-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  padding-bottom: 6px;
  border-bottom: 1px solid #f0f0f0;
}

.stage-icon {
  font-size: 13px;
}

.stage-title {
  font-size: 12px;
  font-weight: 600;
  color: #666;
}

.stage-avg {
  margin-left: auto;
  font-size: 12px;
  font-weight: 700;
}
.stage-avg.up { color: #f56c6c; }
.stage-avg.down { color: #67c23a; }

.stage-sub-info {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: #909399;
  margin-bottom: 6px;
}

/* Sector Chips Grid with heat levels */
.stage-sectors-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sector-chip {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 8px;
  border-radius: 5px;
  font-size: 11px;
  background: #f5f7fa;
  border: 1px solid #e8eaed;
  transition: all 0.2s;
  min-width: 64px;
}

.sector-chip:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
}

/* Heat level backgrounds for up chips */
.sector-chip.up {
  border-color: #fde2e2;
  background: #fff5f5;
}

.sector-chip.up.heat-strong {
  background: linear-gradient(135deg, #fff0f0 0%, #ffe0e0 100%);
  border-color: #f56c6c;
}

.sector-chip.up.heat-warm {
  background: #fff5f5;
  border-color: #fab6b6;
}

.sector-chip.up.heat-slight-up {
  background: #fffafa;
  border-color: #fde2e2;
}

/* Heat level backgrounds for down chips */
.sector-chip.down {
  border-color: #e1f3d8;
  background: #f0f9eb;
}

.sector-chip.down.heat-slight-down {
  background: #f7fcf5;
  border-color: #d4ecc8;
}

.sector-chip.down.heat-cold {
  background: linear-gradient(135deg, #f0f9eb 0%, #e0f3d4 100%);
  border-color: #67c23a;
}

.chip-name {
  font-weight: 500;
  color: #333;
  font-size: 12px;
}

.chip-pct {
  font-weight: 600;
  font-size: 11px;
}

.chip-amount {
  font-size: 10px;
  color: #909399;
}

.sector-chip.up .chip-pct {
  color: #f56c6c;
}

.sector-chip.down .chip-pct {
  color: #67c23a;
}

/* Arrow with line */
.chain-arrow-h {
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.arrow-line {
  position: absolute;
  width: 100%;
  height: 2px;
  background: linear-gradient(90deg, #409eff, #67c23a);
  left: 0;
  top: 50%;
  transform: translateY(-50%);
}

.arrow-icon {
  position: relative;
  z-index: 1;
  background: #fafbfc;
  padding: 0 4px;
  font-size: 20px;
  color: #409eff;
  font-weight: bold;
}

/* Empty Stage */
.empty-stage {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #c0c4cc;
  font-size: 12px;
  padding: 20px 0;
}

.empty-stage :deep(.el-icon) {
  font-size: 16px;
  color: #dcdfe6;
}

/* Text colors */
.up { color: #f56c6c; font-weight: 600; }
.down { color: #67c23a; font-weight: 600; }

.retry-container {
  text-align: center;
  margin-top: 16px;
}

.mb-4 :deep(.el-alert__content) {
  display: flex;
  align-items: center;
}

.error-message {
  font-size: 13px;
  color: #909399;
}

/* ========== H5 移动端适配 ========== */
@media (max-width: 1200px) {
  .hot-chains-grid {
    grid-template-columns: repeat(3, 1fr);
  }

  .chain-metrics {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  /* 移动端：滚动区域底部避开导航栏 */
  .chain-scroll-area {
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px);
  }

  .chain-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    margin-bottom: 8px;
  }

  .toolbar-left {
    flex-direction: column;
    align-items: stretch;
    gap: 4px;
  }

  .toolbar-right {
    justify-content: flex-end;
  }

  .search-input {
    width: 100%;
    max-width: none;
  }

  .chain-count {
    text-align: right;
    font-size: 10px;
  }

  .section-title {
    font-size: 12px;
    margin: 6px 0 4px;
  }

  .title-icon {
    font-size: 14px;
  }

  .hot-chains-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 6px;
  }

  .hot-chain-card {
    padding: 8px;
  }

  .hot-chain-name {
    font-size: 12px;
  }

  .hot-chain-change {
    font-size: 13px;
  }

  .hot-card-header { margin-bottom: 4px; }
  .hot-card-body { margin-bottom: 4px; }
  .hot-rank { font-size: 9px; padding: 1px 5px; }
  .hot-score { font-size: 9px; }
  .stage-tag { font-size: 8px; padding: 1px 2px; }

  /* 汇总表横向滚动 */
  .table-wrapper {
    margin: 0 -8px;
    padding: 0;
  }

  .table-wrapper::-webkit-scrollbar {
    display: none;
  }

  :deep(.el-table) {
    font-size: 12px !important;
  }

  :deep(.el-table__header-wrapper),
  :deep(.el-table__body-wrapper) {
    display: block !important;
    width: 100% !important;
    overflow-x: hidden !important;
    -webkit-overflow-scrolling: touch;
  }

  :deep(.el-table) {
    table-layout: fixed !important;
    min-width: 900px !important;
  }

  :deep(.el-table th),
  :deep(.el-table td) {
    padding: 6px 4px !important;
    word-break: keep-all !important;
  }

  /* 详情卡片移动端 */
  .chain-card {
    padding: 8px 10px;
    margin-bottom: 8px;
  }

  .chain-title-row {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
    margin-bottom: 6px;
  }

  .chain-title-row h3 { font-size: 13px; }

  .chain-metrics {
    grid-template-columns: repeat(3, 1fr);
    gap: 4px;
    padding: 6px 8px;
    margin-bottom: 6px;
  }

  .metric-label { font-size: 9px; }
  .metric-value { font-size: 11px; }

  .chain-stages-horizontal {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .chain-arrow-h {
    padding: 0;
    height: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    transform: none;
    overflow: visible;
  }

  .arrow-line {
    position: absolute;
    width: 2px;
    height: 100%;
    background: linear-gradient(180deg, #409eff, #67c23a);
    left: 50%;
    top: 0;
    transform: translateX(-50%);
  }

  .arrow-icon {
    position: relative;
    z-index: 1;
    background: #fafbfc;
    padding: 0 3px;
    font-size: 12px;
    color: #409eff;
    font-weight: bold;
    line-height: 1;
    transform: rotate(90deg);
  }

  .chain-stage-card {
    padding: 8px 10px;
  }

  .stage-header { margin-bottom: 3px; padding-bottom: 4px; }
  .stage-icon { font-size: 12px; }
  .stage-title { font-size: 11px; }
  .stage-avg { font-size: 11px; }
  .stage-sub-info { font-size: 9px; margin-bottom: 4px; }

  .stage-sectors-grid {
    gap: 4px;
  }

  .sector-chip {
    padding: 3px 6px;
    font-size: 10px;
    min-width: auto;
  }

  .chip-name { font-size: 10px; }
  .chip-pct { font-size: 9px; }
  .chip-amount { font-size: 9px; }
}

@media (max-width: 480px) {
  .hot-chains-grid {
    grid-template-columns: 1fr;
  }

  .chain-card {
    padding: 6px 8px;
  }

  .chain-metrics {
    grid-template-columns: repeat(2, 1fr);
  }

  .stage-header {
    flex-wrap: wrap;
  }

  .sector-chip {
    padding: 2px 5px;
    font-size: 9px;
  }
}

/* 刷新时骨架屏覆盖层 */
.skeleton-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.85);
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: skeleton-fade-in 0.3s ease;
}

@keyframes skeleton-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.empty-fade-enter-active,
.empty-fade-leave-active {
  transition: opacity 0.3s ease;
}
.empty-fade-enter-from,
.empty-fade-leave-to {
  opacity: 0;
}
</style>
