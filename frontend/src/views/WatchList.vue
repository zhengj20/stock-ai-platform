<template>
  <div class="watchlist-page">
    <el-tabs v-model="activeTab" type="border-card" class="main-tabs">
      <!-- 自选股Tab -->
      <el-tab-pane label="自选股" name="watchlist">
        <template #label>
          <span><el-icon><StarFilled /></el-icon> 自选股</span>
        </template>

        <div class="tab-pane-content">
          <!-- Group Tabs + Toolbar -->
          <div class="group-toolbar">
            <div class="group-tabs">
              <button
                v-for="g in groups"
                :key="g"
                class="group-tab"
                :class="{ active: activeGroup === g }"
                @click="activeGroup = g"
              >
                {{ g }} ({{ groupCount(g) }})
                <span
                  v-if="g !== '默认' && g !== '全部'"
                  class="delete-group-btn"
                  @click.stop="deleteGroup(g)"
                  title="删除分组"
                >×</span>
              </button>
              <div v-if="editingGroup" class="group-add-inline">
                <el-input
                  ref="newGroupInputRef"
                  v-model="newGroupName"
                  size="small"
                  class="group-input"
                  @keyup.enter="addGroup"
                  placeholder="输入分组名称"
                />
                <el-button text size="small" type="primary" @click="addGroup">确定</el-button>
                <el-button text size="small" @click="cancelEditGroup">取消</el-button>
              </div>
              <el-button v-else text size="small" class="add-group-btn" @click="startAddGroup">
                <el-icon><Plus /></el-icon> 分组
              </el-button>
            </div>
            <div class="toolbar-actions">
              <RefreshingIndicator :show="quotes.refreshing.value" text="数据更新中" />
              <el-button :icon="Refresh" circle @click="refreshQuotes" :loading="loading" />
              <el-button :icon="Plus" circle type="primary" @click="showAddDialog = true" />
            </div>
          </div>

          <!-- Empty State -->
          <el-card v-if="filteredStocks.length === 0 && !loading" shadow="never" class="empty-card">
            <el-empty description="暂无自选股，点击「添加股票」开始管理你的关注列表">
              <el-button type="primary" @click="showAddDialog = true">
                <el-icon><Plus /></el-icon> 添加股票
              </el-button>
            </el-empty>
          </el-card>

          <!-- Stock Table -->
          <div v-else class="table-section">
            <div class="table-toolbar">
              <span class="toolbar-info">{{ filteredStocks.length }} 只股票 | 更新: {{ lastUpdate }}</span>
            </div>

            <div class="table-scroll-wrapper" v-loading="loading">
              <!-- Desktop Table -->
              <el-table :data="paginatedStocks" stripe class="watchlist-table" height="100%" table-layout="fixed">
                <el-table-column type="index" width="48" label="#" :index="stockIndex" />
                <el-table-column prop="code" label="代码" width="82" sortable />
                <el-table-column prop="name" label="名称" min-width="90" show-overflow-tooltip />
                <el-table-column prop="price" label="最新价" width="85">
                  <template #default="{ row }">¥{{ row.price?.toFixed(2) || '--' }}</template>
                </el-table-column>
                <el-table-column prop="change_pct" label="涨跌幅" min-width="100" sortable>
                  <template #default="{ row }">
                    <span :class="numColorClass(row.change_pct)">
                      {{ formatPct(row.change_pct) }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="volume" label="成交量(手)" min-width="100" sortable />
                <el-table-column prop="amount" label="成交额(万)" min-width="100">
                  <template #default="{ row }">{{ formatAmount(row.amount) }}</template>
                </el-table-column>

                <el-table-column prop="diagnosis_score" label="技术评分" width="90" sortable>
                  <template #header>
                    <el-tooltip content="基于MA/MACD/KDJ/RSI等技术指标,不含基本面和资金面" placement="top">
                      评分
                    </el-tooltip>
                  </template>
                  <template #default="{ row }">
                    <span :class="scoreColorClass(row.diagnosis_score)" style="white-space:nowrap">
                      {{ row.diagnosis_score != null ? row.diagnosis_score : '--' }}
                    </span>
                  </template>
                </el-table-column>

                <el-table-column prop="advice" label="建议" width="100">
                  <template #default="{ row }">
                    <el-tag
                      v-if="row.advice"
                      :type="adviceTagType(row.advice)"
                      size="small"
                      effect="light"
                      style="white-space:nowrap"
                    >{{ row.advice }}</el-tag>
                    <span v-else style="color:#909399">--</span>
                  </template>
                </el-table-column>

                <el-table-column prop="decision_signal" label="算法信号" width="100">
                  <template #header>
                    <div style="display:flex;align-items:center;gap:4px;">
                      <el-tooltip content="基于7个量化算法的综合信号（TD序列/MA雷达/通道突破/神奇电波/异动拉升/底部寻机/趋势强度）" placement="top">
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
                        class="decision-signal-tag"
                      >{{ getDecisionSignalLabel(row.decision_signal) }}</el-tag>
                      <span class="decision-score" :class="getDecisionScoreClass(row.decision_score)">
                        {{ row.decision_score ?? '--' }}
                      </span>
                    </div>
                    <span v-else style="color:#909399">--</span>
                  </template>
                </el-table-column>

                <el-table-column prop="group" label="分组" min-width="100">
                  <template #default="{ row }">
                    <el-select v-model="row.group" size="small" @change="onGroupChange(row)" style="width:100px">
                      <el-option v-for="g in groups" :key="g" :label="g" :value="g" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="140" :fixed="isMobile ? undefined : 'right'" class-name="diag-col">
                  <template #default="{ row }">
                    <el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button>
                    <el-button type="danger" link size="small" @click="removeStock(row.code)">移除</el-button>
                  </template>
                </el-table-column>
              </el-table>

              <!-- Mobile Card List -->
              <div class="mobile-cards">
                <div
                  v-for="(row, idx) in paginatedStocks"
                  :key="row.code"
                  class="m-stock-card"
                  @click="goDiag(row.code)"
                >
                  <div class="top-row">
                    <div class="stock-info">
                      <div class="name-code">
                        <span class="sname">{{ row.name }}</span>
                        <span class="scode">{{ row.code }}</span>
                      </div>
                      <div class="group-tag" v-if="row.group && row.group !== '默认'">
                        {{ row.group }}
                      </div>
                    </div>
                    <div class="price-col">
                      <div class="price-big" :class="row.change_pct > 0 ? 'up' : row.change_pct < 0 ? 'down' : ''">
                        ¥{{ row.price?.toFixed(2) || '--' }}
                      </div>
                      <div class="chg-badge" :class="row.change_pct > 0 ? 'up' : row.change_pct < 0 ? 'down' : ''">
                        {{ formatPct(row.change_pct) }}
                      </div>
                    </div>
                  </div>

                  <div class="meta-row">
                    <span class="meta-item" v-if="row.volume">
                      <span class="meta-label">量</span>
                      <span class="meta-value">{{ Number(row.volume).toLocaleString() }}</span>
                    </span>
                    <span class="meta-item" v-if="row.amount">
                      <span class="meta-label">额</span>
                      <span class="meta-value">{{ formatAmount(row.amount) }}万</span>
                    </span>
                  </div>

                  <div class="tech-strip" v-if="row.diagnosis_score != null || row.advice || row.decision_signal">
                    <div class="score-pill" v-if="row.diagnosis_score != null">
                      <span class="pill-label">评分</span>
                      <span class="pill-value" :class="scoreColorClass(row.diagnosis_score)">{{ row.diagnosis_score }}</span>
                    </div>
                    <div class="decision-pill" v-if="row.decision_signal">
                      <span class="pill-label">算法</span>
                      <el-tag :type="getDecisionSignalType(row.decision_signal)" size="small" effect="dark">
                        {{ getDecisionSignalLabel(row.decision_signal) }}
                      </el-tag>
                      <span class="pill-value" :class="getDecisionScoreClass(row.decision_score)">{{ row.decision_score ?? '--' }}</span>
                    </div>
                    <div class="advice-pill" v-if="row.advice">
                      <el-tag :type="adviceTagType(row.advice)" size="small" effect="light">{{ row.advice }}</el-tag>
                    </div>
                  </div>

                  <div class="card-actions">
                    <el-select v-model="row.group" size="small" @change="onGroupChange(row)" @click.stop style="width:80px;font-size:12px">
                      <el-option v-for="g in groups" :key="g" :label="g" :value="g" />
                    </el-select>
                    <div class="action-btns">
                      <button class="m-action-btn m-action-btn--primary" @click.stop="goDiag(row.code)">诊断</button>
                      <button class="m-action-btn m-action-btn--danger" @click.stop="removeStock(row.code)">移除</button>
                    </div>
                  </div>
                </div>

                <div v-if="paginatedStocks.length === 0 && filteredStocks.length > 0" class="mobile-loading">
                  <span>加载中...</span>
                </div>
              </div>
            </div>

            <div class="pagination-wrapper">
              <el-pagination
                v-model:current-page="pagination.page"
                v-model:page-size="pagination.size"
                :page-sizes="[10, 20, 50, 100]"
                :total="filteredStocks.length"
                layout="total, sizes, prev, pager, next, jumper"
                background
              />
            </div>
          </div>
        </div>

        <!-- 诊断抽屉 -->
        <StockDiagnosisDrawer
          v-model="diagDrawerVisible"
          :stock-code="diagStockCode"
        />

        <!-- Add Stock Dialog -->
        <el-dialog v-model="showAddDialog" title="添加股票到自选" width="500px">
          <div class="add-stock-form">
            <el-input
              v-model="searchQuery"
              placeholder="输入股票代码或名称搜索，如：600519、贵州茅台"
              size="large"
              clearable
              @keyup.enter="doSearch"
              ref="searchInputRef"
            >
              <template #append>
                <el-button type="primary" @click="doSearch" :loading="searchLoading">搜索</el-button>
              </template>
            </el-input>

            <div class="quick-add">
              <span class="label">快捷添加（输入6位代码）:</span>
              <el-input v-model="quickCode" placeholder="如 000001" style="width:120px" @keyup.enter="quickAdd" />
              <el-button size="small" @click="quickAdd">添加</el-button>
            </div>

            <div v-if="searchResults.length > 0" class="search-results">
              <div class="result-header">搜索结果 ({{ searchResults.length }})</div>
              <div
                v-for="s in searchResults"
                :key="s.code"
                class="result-item"
                @click="addFromSearch(s)"
              >
                <span class="r-code">{{ s.code }}</span>
                <span class="r-name">{{ s.name }}</span>
                <el-tag size="small" type="success">点击添加</el-tag>
              </div>
            </div>

            <div v-if="searchResults.length === 0 && searched" class="no-result">
              未找到匹配的股票，请尝试其他关键词
            </div>
          </div>
        </el-dialog>
      </el-tab-pane>

      <!-- 持仓管理Tab -->
      <el-tab-pane label="持仓管理" name="holdings">
        <template #label>
          <span><el-icon><Wallet /></el-icon> 持仓管理</span>
        </template>
        <HoldingsView ref="holdingsRef" />
      </el-tab-pane>

      <!-- 策略中心Tab -->
      <el-tab-pane label="策略中心" name="strategy" :disabled="!isAdmin">
        <template #label>
          <span><el-icon><TrendCharts /></el-icon> 策略中心</span>
        </template>
        <StrategyCenterView v-if="isAdmin" />
        <el-empty v-else description="策略功能仅对管理员开放" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
defineOptions({ name: 'WatchList' })
import { ref, computed, onMounted, onBeforeUnmount, nextTick, onActivated, watch } from 'vue'
import { Refresh, Plus, StarFilled, Wallet, TrendCharts, Loading } from '@element-plus/icons-vue'
import { watchlistApi, stockApi, decisionApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import RefreshingIndicator from '@/components/RefreshingIndicator.vue'
import StockDiagnosisDrawer from './components/StockDiagnosisDrawer.vue'
import HoldingsView from './Holdings.vue'
import StrategyCenterView from './StrategyCenter.vue'

const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin)

// 响应式断点：手机端取消操作列固定
const isMobile = ref(window.innerWidth < 768)
const onResize = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

// Tab
const activeTab = ref('watchlist')
const holdingsRef = ref(null)

// 切换tab时刷新数据
watch(activeTab, (tab) => {
  if (tab === 'holdings' && holdingsRef.value) {
    holdingsRef.value.loadHoldings?.()
    holdingsRef.value.loadSummary?.()
  }
})

// ── Watchlist Data ──────────────────────────────
const STORAGE_KEY = 'gp_watchlist'
const GROUPS_STORAGE_KEY = 'gp_watchlist_groups'
const stocks = ref([])
const groups = ref(['默认'])
const useBackend = computed(() => auth.isLoggedIn)

function loadGroups() {
  try {
    const raw = localStorage.getItem(GROUPS_STORAGE_KEY)
    const list = raw ? JSON.parse(raw) : ['默认']
    return ['全部', ...list]
  } catch { return ['全部', '默认'] }
}

function saveGroups(list) {
  groups.value = list
  const toSave = list.filter(g => g !== '全部')
  localStorage.setItem(GROUPS_STORAGE_KEY, JSON.stringify(toSave))
}

const DEFAULT_STOCKS = [
  { code: '600519', name: '贵州茅台', group: '默认' },
  { code: '000001', name: '平安银行', group: '默认' },
  { code: '300750', name: '宁德时代', group: '默认' },
  { code: '002594', name: '比亚迪', group: '默认' },
  { code: '601318', name: '中国平安', group: '默认' },
  { code: '600036', name: '招商银行', group: '默认' },
]

function loadWatchlistLocal() {
  groups.value = loadGroups()
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw || raw === '[]') {
      stocks.value = DEFAULT_STOCKS
      saveWatchlistLocal()
      return
    }
    stocks.value = JSON.parse(raw)
  } catch { stocks.value = [] }
}

function saveWatchlistLocal() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(stocks.value))
}

async function loadWatchlistBackend() {
  try {
    const res = await watchlistApi.getMyWatchlist()
    if (res && res.stocks) {
      stocks.value = res.stocks.map(s => ({
        code: s.stock_code,
        name: s.stock_name || s.stock_code,
        group: s.group || '默认',
      }))
      const groupSet = new Set(stocks.value.map(s => s.group || '默认'))
      if (!groupSet.has('默认')) groupSet.add('默认')
      groups.value = ['全部', ...Array.from(groupSet)]
    }
  } catch (e) {
    console.warn('加载数据库自选股失败，降级 localStorage:', e?.message || e)
    loadWatchlistLocal()
  }
}

// ── Group Management ────────────────────────────
const activeGroup = ref('全部')
const editingGroup = ref(false)
const newGroupName = ref('')
const newGroupInputRef = ref(null)

function groupCount(g) {
  if (g === '全部') return stocks.value.length
  return stocks.value.filter(s => (s.group || '默认') === g).length
}

async function startAddGroup() {
  editingGroup.value = true
  newGroupName.value = ''
  await nextTick()
  newGroupInputRef.value?.focus()
}
function cancelEditGroup() { editingGroup.value = false }
function addGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  if (name === '全部') { ElMessage.warning('不能使用保留名称'); return }
  if (groups.value.includes(name)) { ElMessage.warning('分组已存在'); return }
  const updated = [...groups.value, name]
  saveGroups(updated)
  editingGroup.value = false
  activeGroup.value = name
}

async function deleteGroup(groupName) {
  if (groupName === '默认' || groupName === '全部') { ElMessage.warning('不能删除该分组'); return }
  const count = stocks.value.filter(s => (s.group || '默认') === groupName).length
  try {
    await ElMessageBox.confirm(
      `该分组有 ${count} 只股票，将移到「默认」分组。确定删除吗？`,
      '提示',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }
  stocks.value.forEach(s => {
    if ((s.group || '默认') === groupName) s.group = '默认'
  })
  if (useBackend.value) {
    for (const s of stocks.value) {
      try { await watchlistApi.updateGroup(s.code, s.group) } catch {}
    }
  } else {
    saveWatchlistLocal()
  }
  const updated = groups.value.filter(g => g !== groupName)
  saveGroups(updated)
  if (activeGroup.value === groupName) activeGroup.value = '全部'
  ElMessage.success('已删除分组')
}

async function onGroupChange(row) {
  if (useBackend.value) {
    try {
      await watchlistApi.updateGroup(row.code, row.group)
    } catch (e) {
      ElMessage.warning(`更新分组失败: ${e?.message || e}`)
      return
    }
  } else {
    saveWatchlistLocal()
  }
  // 如果新分组不在列表中，添加分组
  if (!groups.value.includes(row.group)) {
    const updated = [...groups.value, row.group]
    saveGroups(updated)
  }
}

// ── Quotes ──────────────────────────────────────
const loading = ref(false)
const lastUpdate = ref('--')
const quoteData = ref([])

const filteredStocks = computed(() => {
  if (activeGroup.value === '全部') return stocks.value
  return stocks.value.filter(s => (s.group || '默认') === activeGroup.value)
})

const codes = computed(() => stocks.value.map(s => s.code))

const diagnosisCache = ref({})
const decisionSignalsCache = ref({})  // 决策算法信号缓存
const decisionLoading = ref(false)  // 决策信号加载状态

const quotes = {
  data: quoteData,
  refreshing: ref(false),
  refresh: async () => {
    if (codes.value.length === 0) return
    loading.value = true
    quotes.refreshing.value = true
    try {
      const res = await watchlistApi.getQuotes(codes.value)
      quoteData.value = res?.stocks || []
      lastUpdate.value = new Date().toLocaleTimeString()
      // 行情刷新后自动获取诊断评分和建议
      await _fetchDiagnosis()
      // 获取决策算法信号
      await _fetchDecisionSignals()
    } catch (e) {
      console.warn('获取行情失败:', e?.message || e)
    }
    finally { loading.value = false; quotes.refreshing.value = false }
  },
  silentRefresh: async () => {
    if (codes.value.length === 0) return
    quotes.refreshing.value = true
    try {
      const res = await watchlistApi.getQuotes(codes.value)
      quoteData.value = res?.stocks || []
      lastUpdate.value = new Date().toLocaleTimeString()
      // 静默刷新也更新诊断数据和决策信号
      await _fetchDiagnosis(true)
      await _fetchDecisionSignals(true)
    } catch {}
    finally { quotes.refreshing.value = false }
  },
}

async function _fetchDiagnosis(silent = false) {
  if (stocks.value.length === 0) return
  try {
    const payload = stocks.value.map(s => ({ code: s.code, name: s.name, group: s.group || '默认' }))
    const res = await watchlistApi.batchDiagnosis(payload)
    if (res && res.stocks) {
      for (const d of res.stocks) {
        diagnosisCache.value[d.code] = {
          diagnosis_score: d.diagnosis_score,
          advice: d.advice,
        }
      }
    }
  } catch (e) {
    if (!silent) console.warn('获取诊断数据失败:', e?.message || e)
  }
}

// 获取决策算法信号（7个算法+综合评分）
async function _fetchDecisionSignals(silent = false) {
  if (stocks.value.length === 0) return
  decisionLoading.value = true
  try {
    const codesList = stocks.value.map(s => s.code)
    const res = await decisionApi.getWatchlistSignals(codesList, true)
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
    if (res && res.fail_count > 0 && !silent) {
      console.warn(`决策信号获取失败 ${res.fail_count} 只股票:`, res.fail_codes)
    }
    if (res && res.total === 0 && stocks.value.length > 0 && !silent) {
      console.error('所有股票决策信号获取失败，请检查pytdx连接')
    }
  } catch (e) {
    decisionSignalsCache.value = {}
    if (!silent) console.warn('获取决策算法信号失败:', e?.message || e)
  } finally {
    decisionLoading.value = false
  }
}

// 行情与持仓合并显示
const enrichedStocks = computed(() => {
  const qMap = {}
  for (const q of (quotes.data.value || [])) { qMap[q.code] = q }
  return stocks.value.map(s => {
    const q = qMap[s.code] || {}
    return {
      ...s,
      name: q.name || s.name,
      price: q.price,
      change_pct: q.change_pct,
      volume: q.volume,
      amount: q.amount,
    }
  })
})

// 行情数据合并到 filteredStocks，同时合并诊断评分和建议、决策算法信号
const watchEnriched = computed(() => {
  const qMap = {}
  for (const q of quoteData.value) { qMap[q.code] = q }
  return filteredStocks.value.map(s => {
    const q = qMap[s.code] || {}
    const d = diagnosisCache.value[s.code] || {}
    const ds = decisionSignalsCache.value[s.code] || {}
    return {
      ...s,
      name: q.name || s.name,
      price: q.price,
      change_pct: q.change_pct,
      volume: q.volume,
      amount: q.amount,
      diagnosis_score: d.diagnosis_score ?? s.diagnosis_score,
      advice: d.advice ?? s.advice,
      // 决策算法信号
      decision_score: ds.composite_score ?? null,
      decision_signal: ds.overall_signal ?? null,
      decision_buy_count: ds.buy_signal_count ?? 0,
      decision_sell_count: ds.sell_signal_count ?? 0,
      decision_signals: ds.signals ?? {},
    }
  })
})

// 覆盖 filteredStocks 用 enriched 的
const displayStocks = computed(() => watchEnriched.value)

// ── 分页 ─────────────────────────────────────────
const pagination = ref({ page: 1, size: 20 })

const paginatedStocks = computed(() => {
  const start = (pagination.value.page - 1) * pagination.value.size
  return displayStocks.value.slice(start, start + pagination.value.size)
})

// 分页索引（保持序号连续）
function stockIndex(index) {
  return (pagination.value.page - 1) * pagination.value.size + index + 1
}

// 切换分组或刷新数据后回到第一页
watch([activeGroup, () => pagination.value.size], () => {
  pagination.value.page = 1
})

function refreshQuotes() {
  quotes.refresh()
}

// ── Batch Diagnosis ─────────────────────────────
async function batchDiagnose() {
  if (filteredStocks.value.length === 0) return
  try {
    const payload = filteredStocks.value.map(s => ({ code: s.code, name: s.name, group: s.group || '默认' }))
    const res = await watchlistApi.batchDiagnosis(payload)
    if (res && res.diagnosis) {
      for (const s of stocks.value) {
        const d = res.diagnosis[s.code]
        if (d) {
          s.diagnosis_score = d.diagnosis_score
          s.advice = d.advice
        }
      }
    }
  } catch (e) { console.error('批量诊断失败:', e) }
}

// ── Add/Remove Stocks ───────────────────────────
const showAddDialog = ref(false)
const searchQuery = ref('')
const searchResults = ref([])
const searched = ref(false)
const searchLoading = ref(false)
const quickCode = ref('')
const searchInputRef = ref(null)

async function doSearch() {
  if (!searchQuery.value.trim()) return
  searchLoading.value = true
  try {
    const res = await stockApi.search(searchQuery.value)
    const text = typeof res === 'string' ? res : (res.raw_output || JSON.stringify(res))
    searchResults.value = parseSearchText(text)
    searched.value = true
  } catch (e) { console.error('搜索失败:', e) }
  finally { searchLoading.value = false }
}

function parseSearchText(text) {
  const results = []
  for (const line of text.split('\n')) {
    const match = line.match(/(\d{6})\s+(.+)/)
    if (match) {
      results.push({ code: match[1], name: match[2].replace(/[¥\d.\+\-%()（）]/g, '').trim() })
    }
  }
  return results.slice(0, 10)
}

async function quickAdd() {
  const code = quickCode.value.trim()
  if (!/^\d{6}$/.test(code)) { ElMessage.warning('请输入6位股票代码'); return }
  if (stocks.value.find(s => s.code === code)) { ElMessage.warning('已在自选股中'); return }

  try {
    const res = await stockApi.search(code)
    const text = typeof res === 'string' ? res : (res.raw_output || '')
    const match = text.match(/(\d{6})\s+(.+)/)
    if (match) {
      await addStock(match[1], match[2].replace(/[¥\d.\+\-%()（）]/g, '').trim())
    } else {
      await addStock(code, '')
    }
  } catch {
    await addStock(code, '')
  }
}

async function addFromSearch(s) {
  if (stocks.value.find(st => st.code === s.code)) { ElMessage.warning('已在自选股中'); return }
  await addStock(s.code, s.name)
}

async function addStock(code, name = '') {
  const newStock = { code, name: name || code, group: activeGroup.value }
  if (useBackend.value) {
    try {
      await watchlistApi.addStock(code, name || '', activeGroup.value)
      stocks.value.push(newStock)
      if (!groups.value.includes(activeGroup.value)) {
        groups.value.push(activeGroup.value)
        saveGroups(groups.value)
      }
    } catch (e) {
      ElMessage.warning(`添加失败: ${e?.message || e}`)
      return
    }
  } else {
    stocks.value.push(newStock)
    saveWatchlistLocal()
  }
  quotes.refresh()
  ElMessage.success('已添加 ' + code)
  quickCode.value = ''
  searchResults.value = []
  searched.value = false
}

async function removeStock(code) {
  if (useBackend.value) {
    try {
      await watchlistApi.removeStock(code)
    } catch (e) {
      ElMessage.warning(`移除失败: ${e?.message || e}`)
      return
    }
  } else {
    saveWatchlistLocal()
  }
  stocks.value = stocks.value.filter(s => s.code !== code)
  quotes.refresh()
  ElMessage.success('已移除 ' + code)
}

// ── 诊断抽屉 ───────────────────────────────────
const diagDrawerVisible = ref(false)
const diagStockCode = ref('')
function goDiag(code) {
  diagStockCode.value = code
  diagDrawerVisible.value = true
}

// ── Helpers ─────────────────────────────────────
function numColorClass(val) {
  if (val == null || val === 0) return ''
  return val > 0 ? 'c-red' : 'c-green'
}

function formatPct(val) {
  if (val == null) return '--'
  return (val >= 0 ? '+' : '') + val.toFixed(2) + '%'
}

function formatAmount(amount) {
  if (!amount) return '--'
  return (amount / 10000).toFixed(0)
}

function scoreColorClass(score) {
  // 与 useStockDiagnosisComputed.js 的 5 档对齐：75/60/45/30
  if (score == null) return ''
  if (score >= 75) return 'score-high'
  if (score >= 60) return 'score-good'
  if (score >= 45) return 'score-neutral'
  if (score >= 30) return 'score-low'
  return 'score-danger'
}

function adviceTagType(advice) {
  if (advice.includes('买入')) return 'success'
  if (advice.includes('强烈卖出') || advice.includes('卖出减仓')) return 'danger'
  return 'info'
}

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

// ── Lifecycle ───────────────────────────────────
onMounted(async () => {
  if (useBackend.value) {
    await loadWatchlistBackend()
  } else {
    loadWatchlistLocal()
  }
  await nextTick()
  quotes.refresh()
})

onActivated(() => {
  if (stocks.value.length > 0) {
    quotes.silentRefresh()
  }
})
</script>

<style scoped>
/* ========== 页面容器：参考 SmartStockPick，absolute 填满 .app-main ========== */
.watchlist-page {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  padding: 12px;
  background: #f0f2f5;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  z-index: 1;
}

/* Tabs layout — flex:1 填满剩余空间，min-height:0 允许子元素收缩 */
.watchlist-page .main-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.watchlist-page :deep(.el-tabs__header) { margin-bottom: 0; flex-shrink: 0; }
.watchlist-page :deep(.el-tabs__content) {
  flex: 1;
  display: flex !important;
  flex-direction: column !important;
  overflow: hidden !important;
  min-height: 0;
  padding: 0 !important;
}

/* 主 tabs 的 pane：激活占满剩余空间（el-tabs 通过 v-show 控制非激活 pane 的 display:none） */
.watchlist-page :deep(.el-tabs__content > .el-tab-pane) {
  display: flex !important;
  flex-direction: column !important;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
/* 非激活 pane 由 el-tabs 内联 style 设为 display:none，会被上面的 !important 覆盖，需重置 */
.watchlist-page :deep(.el-tabs__content > .el-tab-pane[style*="display: none"]) {
  display: none !important;
}

/* Tab pane content — flex column，让 table-section 能 flex:1 自适应 */
.tab-pane-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 16px;
}

/* Page Header inside tab */
.page-header { display: flex; align-items: center; justify-content: flex-end; margin-bottom: 12px; flex-shrink: 0; }
.header-actions { display: flex; gap: 8px; }

/* Group Tabs + Toolbar */
.group-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; flex-shrink: 0; }
.group-tabs { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; flex-shrink: 0; }
.toolbar-actions { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }
.group-tab {
  padding: 6px 14px; border-radius: 20px; border: 1px solid #dcdfe6; background: #fff;
  cursor: pointer; font-size: 13px; color: #606266; transition: all 0.2s;
}
.group-tab:hover { border-color: #409eff; color: #409eff; }
.group-tab.active { background: #409eff; color: #fff; border-color: #409eff; }
.delete-group-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; margin-left: 4px; border-radius: 50%;
  font-size: 12px; line-height: 1; cursor: pointer; opacity: 0.5; transition: all 0.2s;
}
.delete-group-btn:hover { background: rgba(0,0,0,0.1); opacity: 1; }
.group-tab.active .delete-group-btn { color: #fff; }
.add-group-btn { color: #909399; font-size: 13px; padding: 6px 8px; }
.group-add-inline { display: flex; align-items: center; gap: 4px; }
.group-input { width: 120px; }

/* Table section — flex:1 自适应高度，overflow:hidden，分页在下方固定 */
.table-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.table-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-shrink: 0; }
.toolbar-info { color: #909399; font-size: 13px; }

/* 表格滚动容器：flex:1 占满剩余空间，内部表格 height:100% */
.table-scroll-wrapper {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.watchlist-table { height: 100% !important; }

/* 分页容器：固定在表格下方，始终可见 */
.pagination-wrapper {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  padding: 8px 0 0;
}

/* 移动端卡片列表：桌面端隐藏 */
.mobile-cards { display: none; }

/* Empty */
.empty-card { text-align: center; padding: 40px 0; }

/* Add Dialog */
.add-stock-form { padding: 8px 0; }
.quick-add { display: flex; align-items: center; gap: 8px; margin-top: 12px; }
.label { color: #909399; font-size: 13px; white-space: nowrap; }

.search-results { margin-top: 16px; max-height: 300px; overflow-y: auto; }
.result-header { font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px solid #eee; }
.result-item {
  display: flex; align-items: center; gap: 12px; padding: 8px 12px; cursor: pointer;
  border-radius: 6px; transition: background 0.2s; margin-bottom: 4px;
}
.result-item:hover { background: #f0f7ff; }
.r-code { font-weight: 600; color: #303133; min-width: 60px; }
.r-name { flex: 1; color: #606266; }

.no-result { text-align: center; color: #909399; padding: 24px 0; font-size: 14px; }

/* Colors */
.c-red { color: #f56c6c !important; font-weight: 600; }
.c-green { color: #67c23a !important; font-weight: 600; }

/* Score colors */
/* 5 档评分颜色 — A 股习惯：高分=红=利好，低分=绿=利空 */
.score-high { color: #d94a4a; font-weight: 700; }
.score-good { color: #f56c6c; font-weight: 600; }
.score-neutral { color: #909399; font-weight: 500; }
.score-low { color: #67c23a; font-weight: 600; }
.score-danger { color: #4e8b3a; font-weight: 700; }

/* Decision Signal Cell */
.decision-signal-cell {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: center;
  gap: 4px;
  white-space: nowrap;
}
.decision-signal-tag {
  font-size: 11px !important;
  padding: 2px 6px !important;
}
.decision-score {
  font-size: 11px;
  font-weight: 600;
}

/* Decision Pill (Mobile) */
.decision-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: var(--m-surface2, #f0f2f5);
  border-radius: 12px;
  font-size: 11px;
}

/* ========== Mobile Responsive ========== */
@media (max-width: 768px) {
  /* ── Page Container: absolute 填满视口，不随父容器滚动 ── */
  .watchlist-page {
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    padding: 0 !important;
    position: absolute !important;
    background: var(--m-bg, #f5f7fa);
    overflow: hidden !important;
  }

  /* ── Tabs: flex 布局，header 固定不滚动 ── */
  :deep(.el-tabs__header) { margin-bottom: 0; }
  :deep(.el-tabs__nav-scroll) { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  :deep(.el-tabs__nav-scroll)::-webkit-scrollbar { display: none; }
  :deep(.el-tabs__item) { font-size: 12px !important; padding: 0 8px !important; }

  .watchlist-page :deep(.el-tabs__header) {
    background-color: #f5f7fa !important;
    flex-shrink: 0 !important;
  }

  /* tabs content：flex约束 + overflow:visible 让分页不被裁剪 */
  .watchlist-page :deep(.el-tabs--border-card > .el-tabs__content) {
    padding: 4px 2px !important;
    overflow: visible !important;
  }
  .watchlist-page :deep(.el-tabs__content > .el-tab-pane) {
    overflow: visible !important;
  }

  .tab-pane-content {
    padding: 4px;
    display: flex !important;
    flex-direction: column !important;
    /* overflow 由子元素控制，不在此处限制 */
  }

  /* ── Table Section: overflow:visible 让分页不被裁剪 ── */
  .table-section {
    overflow: visible !important;
  }

  /* ── Group Toolbar: 紧凑工具栏 ── */
  .group-toolbar {
    flex-wrap: nowrap;
    gap: 4px;
    margin-bottom: 6px;
    padding: 4px 8px;
    overflow-x: auto;
    scrollbar-width: none;
  }
  .group-toolbar::-webkit-scrollbar { display: none; }

  .group-tabs {
    gap: 4px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    flex-wrap: nowrap;
    padding-bottom: 0;
  }
  .group-tabs::-webkit-scrollbar { display: none; }
  .group-tab {
    flex-shrink: 0;
    padding: 6px 14px;
    font-size: 12px;
    white-space: nowrap;
    min-height: 32px;
  }
  .add-group-btn { flex-shrink: 0; min-height: 32px; font-size: 12px; }

  /* ── Toolbar Actions ── */
  .toolbar-actions { display: flex; gap: 4px; padding: 0 12px 8px; }
  .toolbar-actions .el-button { font-size: 11px; padding: 4px 10px; min-height: 32px; }

  /* ── Table Toolbar ── */
  .table-toolbar { margin-bottom: 6px; flex-wrap: wrap; gap: 4px; }
  .toolbar-info { font-size: 11px; color: var(--m-text3, #8e99ab); }

  /* ── Hide Desktop Table, Show Mobile Cards ── */
  :deep(.el-table) { display: none !important; }
  .mobile-cards { display: block !important; }

  /* ── Mobile Card Container — scrollable, pagination stays at bottom ── */
  .table-scroll-wrapper {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  /* ── Card Action Buttons ── */
  .m-action-btn {
    border: none;
    padding: 6px 12px;
    border-radius: 8px;
    font-size: 12px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    transition: all 0.2s;
    font-weight: 500;
  }
  .m-action-btn:active { transform: scale(0.94); opacity: 0.7; }
  .m-action-btn--primary { background: var(--m-accent, #5b7cfa); color: #fff; }
  .m-action-btn--danger { background: rgba(231, 76, 60, 0.1); color: var(--m-up, #e74c3c); }

  /* ── Mobile Loading State ── */
  .mobile-loading {
    text-align: center;
    padding: 24px 0;
    color: var(--m-text3, #8e99ab);
    font-size: 13px;
  }

  /* ── Enhanced Stock Card Styles ── */
  .mobile-cards {
    display: flex !important;
    flex-direction: column !important;
    gap: 0;
    padding-bottom: 8px;
  }

  .m-stock-card {
    background: var(--m-surface, #fff);
    border-radius: var(--m-card-radius, 16px);
    padding: 14px 16px;
    margin-bottom: 12px;
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06));
    cursor: pointer;
    transition: all 0.2s ease;
    border: 1px solid transparent;
  }

  .m-stock-card:active {
    box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    transform: scale(0.98);
  }

  .stock-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .name-code {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }

  .sname {
    font-size: 15px;
    font-weight: 600;
    color: var(--m-text, #1a2332);
  }

  .scode {
    font-size: 11px;
    color: var(--m-text3, #8e99ab);
    background: var(--m-surface2, #f0f2f5);
    padding: 2px 6px;
    border-radius: 4px;
  }

  .group-tag {
    display: inline-block;
    font-size: 10px;
    color: var(--m-accent, #5b7cfa);
    background: rgba(91, 124, 250, 0.1);
    padding: 2px 8px;
    border-radius: 10px;
    width: fit-content;
  }

  .price-col {
    text-align: right;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
  }

  .price-big {
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: var(--m-text, #1a2332);
  }

  .price-big.up { color: var(--m-up, #e74c3c); }
  .price-big.down { color: var(--m-down, #2ecc71); }

  .chg-badge {
    font-size: 12px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 6px;
    display: inline-block;
  }

  .chg-badge.up {
    background: var(--m-up-bg, rgba(231, 76, 60, 0.08));
    color: var(--m-up, #e74c3c);
  }

  .chg-badge.down {
    background: var(--m-down-bg, rgba(46, 204, 113, 0.08));
    color: var(--m-down, #2ecc71);
  }

  .meta-row {
    display: flex;
    gap: 16px;
    margin-top: 8px;
    font-size: 12px;
  }

  .meta-item {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .meta-label {
    color: var(--m-text3, #8e99ab);
    font-size: 11px;
  }

  .meta-value {
    color: var(--m-text2, #5a6577);
    font-weight: 500;
  }

  .tech-strip {
    display: flex;
    gap: 8px;
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid var(--m-border, #e0e4ea);
    align-items: center;
    flex-wrap: wrap;
  }

  .score-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    background: var(--m-surface2, #f0f2f5);
    border-radius: 12px;
    font-size: 11px;
  }

  .pill-label {
    color: var(--m-text3, #8e99ab);
  }

  .pill-value {
    font-weight: 700;
    font-size: 13px;
  }

  .advice-pill {
    margin-left: auto;
  }

  .card-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--m-border, #e0e4ea);
  }

  .action-btns {
    display: flex;
    gap: 6px;
  }

  /* ── Pagination — flex layout keeps it at bottom ── */
  .pagination-wrapper {
    background: #fff !important;
    z-index: 10 !important;
    box-shadow: 0 -2px 6px rgba(0,0,0,0.06) !important;
    padding: 1px 1px calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0)) !important;
    min-height: 24px !important;
    margin-top: 1px;
  }
  .pagination-wrapper :deep(.el-pagination) { --el-pagination-font-size: 11px; font-size: 11px !important; }
  .pagination-wrapper :deep(.el-pager li) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; font-size: 11px !important; }
  .pagination-wrapper :deep(.el-pagination button) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; }
  .pagination-wrapper :deep(.el-pagination .el-pagination__sizes) { display: none; }
  .pagination-wrapper :deep(.el-pagination .el-pagination__jump) { display: none; }

  /* ── Empty State ── */
  .empty-card { flex-shrink: 0; padding: 30px 0; }
  .empty-card :deep(.el-empty__description) { font-size: 13px; }

  /* ── Select Compact on Mobile Cards ── */
  :deep(.el-select__wrapper) { min-height: 28px !important; padding: 0 4px !important; }
}

@media (max-width: 480px) {
  .group-tab { font-size: 11px; padding: 5px 10px; }
  .m-action-btn { padding: 5px 10px; font-size: 11px; }

  .m-stock-card {
    padding: 12px 14px;
    margin-bottom: 8px;
  }

  .sname { font-size: 14px; }
  .price-big { font-size: 18px; }
  .meta-row { gap: 12px; }
}
</style>
