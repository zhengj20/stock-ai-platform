<template>
  <div class="holdings-section">
    <!-- 持仓概览 -->
    <el-card shadow="hover" class="summary-card">
      <div class="summary-grid">
        <div class="summary-item">
          <div class="summary-label">持仓数量</div>
          <div class="summary-value">{{ summary.count || 0 }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-label">总市值</div>
          <div class="summary-value">¥{{ formatMoney(summary.total_market_value) }}</div>
        </div>
        <div class="summary-item">
          <div class="summary-label">总盈亏</div>
          <div :class="['summary-value', summary.total_profit >= 0 ? 'profit' : 'loss']">
            {{ summary.total_profit >= 0 ? '+' : '' }}¥{{ formatMoney(summary.total_profit) }}
          </div>
        </div>
        <div class="summary-item">
          <div class="summary-label">盈亏比例</div>
          <div :class="['summary-value', summary.profit_ratio >= 0 ? 'profit' : 'loss']">
            {{ summary.profit_ratio >= 0 ? '+' : '' }}{{ summary.profit_ratio?.toFixed(2) || '0.00' }}%
          </div>
        </div>
      </div>
    </el-card>

    <!-- 持仓列表 -->
    <div class="holdings-card">
      <div class="card-header">
        <span>持仓列表</span>
        <div style="display:flex;gap:8px;">
          <el-button size="small" @click="syncPrices" :loading="syncing">
            <el-icon><Refresh /></el-icon> 同步现价
          </el-button>
          <el-button size="small" type="primary" @click="openAddDialog">
            <el-icon><Plus /></el-icon> 添加持仓
          </el-button>
        </div>
      </div>

      <div v-if="holdings.length === 0 && !loading" class="empty-state">
        <el-empty description="暂无持仓，点击「添加持仓」开始管理">
          <el-button type="primary" @click="openAddDialog">
            <el-icon><Plus /></el-icon> 添加持仓
          </el-button>
        </el-empty>
      </div>

      <div v-else class="table-section">
        <!-- Desktop Table -->
        <div class="table-scroll-wrapper desktop-only" v-loading="loading">
          <el-table :data="paginatedEnrichedHoldings" stripe border class="holdings-table" height="100%" table-layout="fixed">
            <el-table-column type="index" label="#" width="50" align="center" :index="holdingIndex" />
            <el-table-column prop="stock_code" label="代码" width="90" sortable align="center" />
            <el-table-column prop="stock_name" label="名称" min-width="120" show-overflow-tooltip align="left" />
            <el-table-column prop="quantity" label="持仓数量" width="100" align="right" />
            <el-table-column prop="cost_price" label="成本价" width="95" align="right">
              <template #default="{ row }">¥{{ row.cost_price?.toFixed(2) || '--' }}</template>
            </el-table-column>
            <el-table-column prop="current_price" label="现价" width="95" align="right">
              <template #default="{ row }">¥{{ row.current_price?.toFixed(2) || '--' }}</template>
            </el-table-column>
            <el-table-column prop="market_value" label="市值" width="120" sortable align="right">
              <template #default="{ row }">¥{{ formatMoney(row.market_value) }}</template>
            </el-table-column>
            <el-table-column prop="profit" label="盈亏" width="120" sortable align="right">
              <template #default="{ row }">
                <span :class="row.profit >= 0 ? 'profit' : 'loss'">
                  {{ row.profit >= 0 ? '+' : '' }}¥{{ formatMoney(row.profit) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="profit_ratio" label="盈亏比例" width="105" sortable align="right">
              <template #default="{ row }">
                <span :class="row.profit_ratio >= 0 ? 'profit' : 'loss'">
                  {{ row.profit_ratio >= 0 ? '+' : '' }}{{ row.profit_ratio?.toFixed(2) || '0.00' }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="position_type" label="类型" width="80" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="getPositionType(row.position_type)">
                  {{ formatPositionType(row.position_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="decision_signal" label="算法信号" width="100" align="center">
              <template #header>
                <div style="display:flex;align-items:center;gap:4px;">
                  <el-tooltip content="基于7个量化算法的综合信号（结合持仓感知）" placement="top">
                    算法信号
                  </el-tooltip>
                  <el-icon v-if="decisionLoading" class="is-loading"><Loading /></el-icon>
                </div>
              </template>
              <template #default="{ row }">
                <div v-if="row.decision_signal" class="decision-signal-cell">
                  <el-tag
                    :type="getDecisionSignalType(row.decision_signal)"
                    size="small"
                    effect="dark"
                  >{{ getDecisionSignalLabel(row.decision_signal) }}</el-tag>
                  <span class="decision-score" :class="getDecisionScoreClass(row.decision_score)">
                    {{ row.decision_score ?? '--' }}
                  </span>
                </div>
                <span v-else style="color:#909399">--</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" align="center">
              <template #default="{ row }">
                <div style="display:flex;gap:4px;">
                  <el-button size="small" @click="editHolding(row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="deleteHolding(row)">删除</el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- Mobile Card List -->
        <div class="mobile-cards mobile-only">
          <div v-for="(row, idx) in paginatedEnrichedHoldings" :key="row.id || idx" class="m-holding-card">
            <div class="m-hl-top">
              <div class="m-hl-left">
                <div class="m-hl-name">{{ row.stock_name }}</div>
                <div class="m-hl-code">{{ row.stock_code }}</div>
              </div>
              <div class="m-hl-right">
                <div class="m-hl-price" :class="(row.current_price || 0) > (row.cost_price || 0) ? 'profit' : 'loss'">
                  ¥{{ row.current_price?.toFixed(2) || '--' }}
                </div>
                <div class="m-hl-pct" :class="(row.profit_ratio || 0) >= 0 ? 'profit' : 'loss'">
                  {{ (row.profit_ratio || 0) >= 0 ? '+' : '' }}{{ row.profit_ratio?.toFixed(2) || '0.00' }}%
                </div>
              </div>
            </div>

            <div class="m-hl-mid">
              <div class="m-hl-stat">
                <span class="stat-label">持仓</span>
                <span class="stat-val">{{ row.quantity || 0 }}股</span>
              </div>
              <div class="m-hl-stat">
                <span class="stat-label">成本</span>
                <span class="stat-val">¥{{ row.cost_price?.toFixed(2) || '--' }}</span>
              </div>
              <div class="m-hl-stat">
                <span class="stat-label">市值</span>
                <span class="stat-val">¥{{ formatMoney(row.market_value) }}</span>
              </div>
              <div class="m-hl-stat">
                <span class="stat-label">盈亏</span>
                <span class="stat-val" :class="(row.profit || 0) >= 0 ? 'profit' : 'loss'">
                  {{ (row.profit || 0) >= 0 ? '+' : '' }}¥{{ formatMoney(row.profit) }}
                </span>
              </div>
            </div>

            <div class="m-hl-bottom">
              <div class="m-hl-tags">
                <el-tag size="small" :type="getPositionType(row.position_type)">
                  {{ formatPositionType(row.position_type) }}
                </el-tag>
                <div v-if="row.decision_signal" class="m-decision-tag">
                  <el-tag :type="getDecisionSignalType(row.decision_signal)" size="small" effect="dark">
                    {{ getDecisionSignalLabel(row.decision_signal) }}
                  </el-tag>
                  <span class="m-decision-score" :class="getDecisionScoreClass(row.decision_score)">
                    {{ row.decision_score ?? '--' }}
                  </span>
                </div>
              </div>
              <div class="m-hl-actions">
                <button class="m-card-action m-card-action--primary" @click="editHolding(row)">编辑</button>
                <button class="m-card-action m-card-action--danger" @click="deleteHolding(row)">删除</button>
              </div>
            </div>
          </div>
        </div>

        <div class="pagination-wrapper">
          <el-pagination
            v-model:current-page="pagination.page"
            v-model:page-size="pagination.size"
            :page-sizes="[10, 20, 50, 100]"
            :total="holdings.length"
            layout="total, sizes, prev, pager, next, jumper"
            background
          />
        </div>
      </div>
    </div>

    <!-- 添加/编辑对话框 -->
    <el-dialog
      v-model="showAddDialog"
      :title="editingHolding ? '编辑持仓' : '添加持仓'"
      width="500px"
    >
      <el-form :model="form" label-width="100px">
        <el-form-item label="搜索股票" v-if="!editingHolding">
          <el-input
            v-model="searchQuery"
            placeholder="输入股票代码或名称搜索，如：600519、贵州茅台"
            clearable
            @keyup.enter="doSearch"
          >
            <template #append>
              <el-button @click="doSearch" :loading="searchLoading">搜索</el-button>
            </template>
          </el-input>
        </el-form-item>
        <div v-if="searchResults.length > 0 && !editingHolding" class="search-results">
          <div class="result-header">搜索结果 ({{ searchResults.length }})</div>
          <div
            v-for="s in searchResults"
            :key="s.code"
            class="result-item"
            @click="selectStock(s)"
          >
            <span class="r-code">{{ s.code }}</span>
            <span class="r-name">{{ s.name }}</span>
            <el-tag size="small" type="success">选择</el-tag>
          </div>
        </div>
        <el-form-item v-if="!editingHolding" label="">
          <el-button size="small" @click="loadWatchlistStocks" :loading="watchlistLoading" style="width:100%">
            从自选股中选择
          </el-button>
        </el-form-item>
        <div v-if="watchlistStocks.length > 0 && !editingHolding" class="search-results">
          <div class="result-header">自选股 ({{ watchlistStocks.length }})</div>
          <div
            v-for="s in watchlistStocks"
            :key="s.code"
            class="result-item"
            @click="selectFromWatchlist(s)"
          >
            <span class="r-code">{{ s.code }}</span>
            <span class="r-name">{{ s.name }}</span>
            <el-tag size="small" type="warning">选择</el-tag>
          </div>
        </div>
        <el-form-item label="股票代码" required>
          <el-input v-model="form.stock_code" placeholder="请输入或搜索选择" :disabled="!!editingHolding" />
        </el-form-item>
        <el-form-item label="股票名称">
          <el-input v-model="form.stock_name" placeholder="股票名称" :disabled="!!editingHolding" />
        </el-form-item>
        <el-form-item label="持仓数量" required>
          <el-input-number v-model="form.quantity" :min="0" :step="100" />
        </el-form-item>
        <el-form-item label="成本价" required>
          <el-input-number v-model="form.cost_price" :min="0" :precision="2" :step="0.01" />
        </el-form-item>
        <el-form-item label="买入日期">
          <el-date-picker
            v-model="form.buy_date"
            type="date"
            placeholder="选择日期"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
          />
        </el-form-item>
        <el-form-item label="持仓类型">
          <el-select v-model="form.position_type" placeholder="选择类型">
            <el-option label="短线" value="short" />
            <el-option label="中线" value="mid" />
            <el-option label="长线" value="long" />
          </el-select>
        </el-form-item>
        <el-form-item label="买入理由">
          <el-input v-model="form.buy_reason" type="textarea" :rows="2" placeholder="买入理由（可选）" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.notes" type="textarea" :rows="2" placeholder="备注（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Wallet, Refresh, Plus, Loading } from '@element-plus/icons-vue'
import { holdingsApi, watchlistApi, decisionApi } from '@/api'

// 响应式断点：手机端取消操作列固定
const isMobile = ref(window.innerWidth < 768)
const onResize = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

// 数据
const holdings = ref([])
const summary = ref({})
const loading = ref(false)
const syncing = ref(false)
const submitting = ref(false)
const decisionSignalsCache = ref({})  // 决策算法信号缓存
const decisionLoading = ref(false)  // 决策信号加载状态

// 分页
const pagination = ref({ page: 1, size: 20 })
const paginatedHoldings = computed(() => {
  const start = (pagination.value.page - 1) * pagination.value.size
  return holdings.value.slice(start, start + pagination.value.size)
})
function holdingIndex(index) {
  return (pagination.value.page - 1) * pagination.value.size + index + 1
}
watch(() => pagination.value.size, () => { pagination.value.page = 1 })

// 搜索
const searchQuery = ref('')
const searchResults = ref([])
const searchLoading = ref(false)

// 自选股
const watchlistStocks = ref([])
const watchlistLoading = ref(false)

// 表单
const showAddDialog = ref(false)
const editingHolding = ref(null)
const form = ref({
  stock_code: '',
  stock_name: '',
  quantity: 0,
  cost_price: 0,
  buy_date: '',
  position_type: 'short',
  buy_reason: '',
  notes: '',
})

onMounted(async () => {
  await Promise.all([loadHoldings(), loadSummary()])
})

const loadHoldings = async () => {
  loading.value = true
  try {
    const res = await holdingsApi.getMy()
    holdings.value = res?.holdings || []
    pagination.value.page = 1
    // 获取决策算法信号
    await _fetchDecisionSignals()
  } catch (e) {
    console.error('加载持仓失败:', e)
    ElMessage.error('加载持仓失败')
  } finally {
    loading.value = false
  }
}

// 获取决策算法信号
const _fetchDecisionSignals = async () => {
  if (holdings.value.length === 0) return
  decisionLoading.value = true
  try {
    const codes = holdings.value.map(h => h.stock_code).filter(Boolean)
    if (codes.length === 0) return

    const res = await decisionApi.getWatchlistSignals(codes, true)
    // 清空旧缓存，避免显示过期数据
    decisionSignalsCache.value = {}
    if (res && res.stocks) {
      for (const s of res.stocks) {
        decisionSignalsCache.value[s.code] = {
          composite_score: s.composite_score,
          overall_signal: s.overall_signal,
          buy_signal_count: s.buy_signal_count,
          sell_signal_count: s.sell_signal_count,
          signals: s.signals || {},
        }
      }
    }
    if (res && res.fail_count > 0) {
      console.warn(`持仓决策信号获取失败 ${res.fail_count} 只股票:`, res.fail_codes)
    }
    if (res && res.total === 0 && holdings.value.length > 0) {
      console.error('所有持仓股票决策信号获取失败，请检查pytdx连接')
    }
  } catch (e) {
    decisionSignalsCache.value = {}
    console.warn('获取决策算法信号失败:', e?.message || e)
  } finally {
    decisionLoading.value = false
  }
}

// 合并持仓数据和决策算法信号
const enrichedHoldings = computed(() => {
  return holdings.value.map(h => {
    const ds = decisionSignalsCache.value[h.stock_code] || {}
    return {
      ...h,
      decision_score: ds.composite_score ?? null,
      decision_signal: ds.overall_signal ?? null,
      decision_buy_count: ds.buy_signal_count ?? 0,
      decision_sell_count: ds.sell_signal_count ?? 0,
    }
  })
})

// 分页使用合并后的数据
const paginatedEnrichedHoldings = computed(() => {
  const start = (pagination.value.page - 1) * pagination.value.size
  return enrichedHoldings.value.slice(start, start + pagination.value.size)
})

const loadSummary = async () => {
  try {
    const res = await holdingsApi.getSummary()
    summary.value = res || {}
  } catch (e) {
    console.error('加载汇总失败:', e)
  }
}

const syncPrices = async () => {
  syncing.value = true
  try {
    await holdingsApi.syncPrices()
    ElMessage.success('同步成功')
    await Promise.all([loadHoldings(), loadSummary()])
  } catch (e) {
    ElMessage.error('同步失败')
  } finally {
    syncing.value = false
  }
}

const openAddDialog = () => {
  editingHolding.value = null
  resetForm()
  searchQuery.value = ''
  searchResults.value = []
  watchlistStocks.value = []
  showAddDialog.value = true
}

const doSearch = async () => {
  const q = searchQuery.value.trim()
  if (!q) return
  searchLoading.value = true
  try {
    const res = await watchlistApi.search(q)
    const text = typeof res === 'string' ? res : (res.raw_output || JSON.stringify(res))
    searchResults.value = parseSearchText(text)
  } catch (e) {
    searchResults.value = []
  } finally {
    searchLoading.value = false
  }
}

const parseSearchText = (text) => {
  const results = []
  for (const line of String(text).split('\n')) {
    const match = line.match(/(\d{6})\s+(.+)/)
    if (match) {
      results.push({ code: match[1], name: match[2].replace(/[¥\d.\+\-%()（）]/g, '').trim() })
    }
  }
  return results.slice(0, 10)
}

const loadWatchlistStocks = async () => {
  watchlistLoading.value = true
  try {
    const res = await watchlistApi.getMyWatchlist()
    watchlistStocks.value = (res?.stocks || []).map(s => ({
      code: s.stock_code,
      name: s.stock_name || s.stock_code,
    }))
  } catch (e) {
    watchlistStocks.value = []
  } finally {
    watchlistLoading.value = false
  }
}

const selectFromWatchlist = (stock) => {
  form.value.stock_code = stock.code
  form.value.stock_name = stock.name
  watchlistStocks.value = []
}

const selectStock = (stock) => {
  form.value.stock_code = stock.code
  form.value.stock_name = stock.name
  searchResults.value = []
  searchQuery.value = ''
}

const editHolding = (row) => {
  editingHolding.value = row
  form.value = { ...row }
  showAddDialog.value = true
}

const deleteHolding = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除 ${row.stock_name}(${row.stock_code}) 的持仓？`, '提示', { type: 'warning' })
    await holdingsApi.delete(row.id)
    ElMessage.success('删除成功')
    await Promise.all([loadHoldings(), loadSummary()])
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

const submitForm = async () => {
  if (!form.value.stock_code) { ElMessage.warning('请输入股票代码'); return }
  if (form.value.quantity <= 0) { ElMessage.warning('请输入持仓数量'); return }
  if (form.value.cost_price <= 0) { ElMessage.warning('请输入成本价'); return }

  submitting.value = true
  try {
    if (editingHolding.value) {
      await holdingsApi.update(editingHolding.value.id, form.value)
      ElMessage.success('更新成功')
    } else {
      await holdingsApi.add(form.value)
      ElMessage.success('添加成功')
    }
    showAddDialog.value = false
    editingHolding.value = null
    resetForm()
    await Promise.all([loadHoldings(), loadSummary()])
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    submitting.value = false
  }
}

const resetForm = () => {
  form.value = { stock_code: '', stock_name: '', quantity: 0, cost_price: 0, buy_date: '', position_type: 'short', buy_reason: '', notes: '' }
}

const formatMoney = (v) => {
  if (!v) return '0.00'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
const formatPositionType = (t) => ({ short: '短线', mid: '中线', long: '长线' }[t] || t)
const getPositionType = (t) => ({ short: 'info', mid: 'warning', long: 'success' }[t] || 'info')

// 决策算法信号相关函数
function getDecisionSignalType(signal) {
  const map = {
    'strong_buy': 'success',
    'buy': '',
    'sell': 'warning',
    'strong_sell': 'danger',
    'neutral': 'info',
  }
  return map[signal] || 'info'
}

function getDecisionSignalLabel(signal) {
  const map = {
    'strong_buy': '强烈买入',
    'buy': '买入',
    'sell': '卖出',
    'strong_sell': '强烈卖出',
    'neutral': '中性',
  }
  return map[signal] || signal
}

function getDecisionScoreClass(score) {
  if (score == null) return ''
  if (score >= 60) return 'score-high'
  if (score >= 40) return 'score-good'
  if (score >= 20) return 'score-neutral'
  return 'score-low'
}

defineExpose({ loadHoldings, loadSummary })
</script>

<style scoped>
/* 根容器：flex column 填满父容器（el-tab-pane，由父级 WatchList 设为 flex） */
.holdings-section {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 16px;
}

/* 持仓概览 card：固定高度，不收缩 */
.summary-card { flex-shrink: 0; margin-bottom: 12px; }
.summary-card :deep(.el-card__body) { padding: 16px; }
.summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
.summary-item { text-align: center; }
.summary-label { color: #909399; font-size: 14px; margin-bottom: 8px; }
.summary-value { font-size: 24px; font-weight: bold; }
.summary-value.profit { color: #F56C6C; }
.summary-value.loss { color: #67C23A; }

/* 持仓列表 card：flex:1 占满剩余空间，内部表格独立滚动 */
.holdings-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: #fff;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0,0,0,0.08);
  border: 1px solid #ebeef5;
}
.holdings-card .card-header {
  flex-shrink: 0;
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
}
.empty-state { padding: 40px 0; flex: 1; display: flex; align-items: center; justify-content: center; }

/* 表格区域：flex:1 自适应，分页在下方固定 */
.table-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.table-scroll-wrapper {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.holdings-table { height: 100% !important; }
.holdings-table :deep(.el-table__header-wrapper) { overflow: hidden; }
.holdings-table :deep(.el-table__body-wrapper) { overflow-x: auto; -webkit-overflow-scrolling: touch; }

.pagination-wrapper {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  padding: 8px 16px;
  border-top: 1px solid #f0f0f0;
}

.profit { color: #F56C6C; }
.loss { color: #67C23A; }

/* Decision Signal Cell */
.decision-signal-cell {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: center;
  gap: 4px;
  white-space: nowrap;
}
.decision-score {
  font-size: 11px;
  font-weight: 600;
}

/* Decision Signal Colors */
.score-high { color: #d94a4a; font-weight: 700; }
.score-good { color: #f56c6c; font-weight: 600; }
.score-neutral { color: #909399; font-weight: 500; }
.score-low { color: #67c23a; font-weight: 600; }

/* Mobile Decision Tag */
.m-hl-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.m-decision-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.m-decision-score {
  font-size: 11px;
  font-weight: 600;
}

.search-results { border: 1px solid #e4e7ed; border-radius: 4px; max-height: 180px; overflow-y: auto; margin-bottom: 12px; }
.result-header { font-size: 13px; font-weight: 600; color: #303133; padding: 8px 12px; border-bottom: 1px solid #e4e7ed; background: #f5f7fa; }
.result-item { display: flex; align-items: center; gap: 12px; padding: 8px 12px; cursor: pointer; border-bottom: 1px solid #f0f0f0; }
.result-item:last-child { border-bottom: none; }
.result-item:hover { background: #f5f7fa; }
.r-code { font-weight: bold; color: #409EFF; min-width: 60px; }
.r-name { flex: 1; color: #606266; }

/* Desktop-only / Mobile-only visibility */
.desktop-only { display: block !important; }
.mobile-only { display: none !important; }

/* Responsive */
@media (max-width: 768px) {
  .holdings-section { padding: 0; background: var(--m-bg, #f5f7fa); }
  .desktop-only { display: none !important; }
  .mobile-only { display: block !important; }

  /* Summary card mobile — ultra compact */
  .summary-card :deep(.el-card__body) { padding: 6px 8px !important; }
  .summary-grid { grid-template-columns: repeat(4, 1fr); gap: 0; }
  .summary-item { padding: 4px 0; border-right: 1px solid #f0f0f0; }
  .summary-item:last-child { border-right: none; }
  .summary-label { font-size: 10px; margin-bottom: 2px; color: #a8b2c1 !important; }
  .summary-value { font-size: 14px !important; line-height: 1.2; }

  /* Holdings card header mobile */
  .holdings-card { background: transparent !important; box-shadow: none !important; border: none !important; }
  .holdings-card .card-header {
    padding: 8px 12px;
    background: var(--m-surface, #fff);
    border-radius: var(--m-card-radius, 16px);
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06));
    margin-bottom: 8px;
  }
  .holdings-card .card-header > span { font-size: 14px; font-weight: 600; }
  .holdings-card .card-header :deep(.el-button) { min-height: 32px; font-size: 12px; padding: 4px 10px; }

  /* Table section mobile */
  .table-section { background: transparent; }
  .table-scroll-wrapper { display: none; }

  /* Mobile card list — scrollable, pagination stays at bottom */
  .mobile-cards {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 0 12px;
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .m-holding-card {
    background: var(--m-surface, #fff);
    border-radius: var(--m-card-radius, 16px);
    padding: 14px;
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06));
    transition: transform 0.2s;
  }
  .m-holding-card:active { transform: scale(0.98); }

  /* Top row: name + price */
  .m-hl-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .m-hl-name { font-size: 15px; font-weight: 600; color: var(--m-text, #1a2332); }
  .m-hl-code { font-size: 11px; color: var(--m-text3, #8e99ab); margin-top: 1px; }
  .m-hl-price { font-size: 17px; font-weight: 700; text-align: right; }
  .m-hl-pct { font-size: 12px; font-weight: 600; text-align: right; margin-top: 2px; }

  /* Mid row: 4 stats */
  .m-hl-mid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    padding: 10px 0;
    border-top: 1px solid var(--m-border, #e0e4ea);
    border-bottom: 1px solid var(--m-border, #e0e4ea);
    margin-top: 10px;
  }
  .m-hl-stat { text-align: center; }
  .stat-label { font-size: 10.5px; color: var(--m-text3, #8e99ab); display: block; margin-bottom: 2px; }
  .stat-val { font-size: 13px; font-weight: 600; color: var(--m-text, #1a2332); }

  /* Bottom row: tag + actions */
  .m-hl-bottom {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 10px;
  }
  .m-hl-actions { display: flex; gap: 6px; }

  /* Card action buttons */
  .m-card-action {
    border: none;
    padding: 5px 14px;
    border-radius: 12px;
    font-size: 12px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: all 0.2s;
    font-weight: 500;
  }
  .m-card-action:active { transform: scale(0.94); opacity: 0.7; }
  .m-card-action--primary { background: var(--m-accent, #5b7cfa); color: #fff; }
  .m-card-action--danger { background: rgba(231, 76, 60, 0.1); color: var(--m-up, #e74c3c); }

  /* Profit/Loss colors */
  .profit { color: #F56C6C !important; }
  .loss { color: #67C23A !important; }

  /* Pagination — flex layout keeps it at bottom */
  .holdings-card { overflow: visible !important; }
  .pagination-wrapper {
    background: #fff !important;
    z-index: 10 !important;
    box-shadow: 0 -2px 6px rgba(0,0,0,0.06) !important;
    padding: 1px 1px calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0)) !important;
    min-height: 24px !important;
  }
  .pagination-wrapper :deep(.el-pagination) { --el-pagination-font-size: 11px; font-size: 11px !important; padding: 0; }
  .pagination-wrapper :deep(.el-pager li) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; font-size: 11px !important; }
  .pagination-wrapper :deep(.el-pagination button) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; }
  .pagination-wrapper :deep(.el-pagination .el-pagination__sizes) { display: none; }
  .pagination-wrapper :deep(.el-pagination .el-pagination__jump) { display: none; }

  /* Empty state mobile */
  .empty-state { padding: 30px 12px; }
}
</style>
