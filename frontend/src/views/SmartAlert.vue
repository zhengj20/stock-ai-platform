<template>
  <div class="smart-alert">
    <div class="page-header-fixed" :class="{ 'mobile-header': isMobile }">
      <h2 class="page-title"><el-icon><Warning /></el-icon> 智能预警</h2>
      <div class="header-right" :class="{ 'mobile-header-actions': isMobile }">
        <div v-if="unreadCount > 0" class="unread-badge">{{ unreadCount }}</div>
        <template v-if="!isMobile">
          <el-tooltip :content="isTradingTime() ? '交易时段：每60秒轮询' : '非交易时段，已暂停'" placement="bottom">
            <el-switch v-model="autoMonitor" active-text="自动监控" @change="toggleAutoMonitor" style="--el-switch-on-color: #e6a23c;" />
          </el-tooltip>
          <el-tooltip content="开启桌面通知" placement="bottom">
            <el-switch v-model="notifyEnabled" active-icon="Bell" inactive-icon="BellFilled" @change="requestNotifyPermission" style="--el-switch-on-color: #409eff;" />
          </el-tooltip>
        </template>
        <template v-else>
          <el-tag :type="autoMonitor ? 'warning' : 'info'" size="small" effect="plain" class="mob-monitor-tag" @click="toggleAutoMonitor(!autoMonitor)" style="cursor:pointer;">{{ autoMonitor ? '监控中' : '已暂停' }}</el-tag>
          <el-button text size="small" :icon="BellFilled" @click="requestNotifyPermission(!notifyEnabled)" class="mob-notify-btn">{{ notifyEnabled ? '通知开' : '通知关' }}</el-button>
        </template>
        <el-tag v-if="rulesSummary && !isMobile" size="small" type="info" effect="plain" class="rules-tag">{{ rulesSummary }}</el-tag>
        <el-button v-if="!isMobile" size="small" :icon="Refresh" @click="refreshAll" circle />
        <el-button v-else text size="small" :icon="Refresh" @click="refreshAll" class="mob-refresh-btn">刷新</el-button>
      </div>
    </div>

    <div class="content-scroll-area">
      <el-tabs v-model="activeTab" type="border-card" class="main-tabs">
        <!-- 监控面板（统一仪表盘） -->
        <el-tab-pane label="监控面板" name="monitor">
          <div class="tab-pane-content">
            <!-- 顶部状态卡片 - 移动端横向滚动 -->
            <div class="dashboard-stats" :class="{ 'mob-hscroll': isMobile }">
              <div class="dash-stat-card" style="background:linear-gradient(135deg,#1a1a2e,#2d2d5e);">
                <div class="dash-stat-icon"><el-icon :size="isMobile ? 16 : 22"><Warning /></el-icon></div>
                <div class="dash-stat-body">
                  <div class="dash-stat-value">{{ totalAlertCount }}</div>
                  <div class="dash-stat-label">预警总数</div>
                </div>
              </div>
              <div class="dash-stat-card" style="background:linear-gradient(135deg,#409eff,#66b1ff);">
                <div class="dash-stat-icon"><el-icon :size="isMobile ? 16 : 22"><StarFilled /></el-icon></div>
                <div class="dash-stat-body">
                  <div class="dash-stat-value">{{ totalMonitoredStocks }}</div>
                  <div class="dash-stat-label">监控股票</div>
                </div>
              </div>
              <div class="dash-stat-card" style="background:linear-gradient(135deg,#e6a23c,#f0c75e);">
                <div class="dash-stat-icon"><el-icon :size="isMobile ? 16 : 22"><InfoFilled /></el-icon></div>
                <div class="dash-stat-body">
                  <div class="dash-stat-value">{{ activeSources }}</div>
                  <div class="dash-stat-label">监控来源</div>
                </div>
              </div>
              <div class="dash-stat-card" style="background:linear-gradient(135deg,#67c23a,#85ce61);">
                <div class="dash-stat-icon"><el-icon :size="isMobile ? 16 : 22"><Refresh /></el-icon></div>
                <div class="dash-stat-body">
                  <div class="dash-stat-value">{{ autoMonitor ? '实时' : '手动' }}</div>
                  <div class="dash-stat-label">{{ autoMonitor ? '60秒轮询' : '点击刷新' }}</div>
                </div>
              </div>
            </div>

            <!-- 来源监控卡片（点击筛选预警）- 移动端紧凑布局 -->
            <div class="dash-sources" :class="{ 'mob-grid': isMobile }">
              <div class="dash-source-card" :class="{ 'source-active': autoMonitor && wlAutoEnabled, 'source-filtered': alertFilterSource === 'wl', 'mob-compact': isMobile }" @click="setFilterSource('wl')" style="cursor:pointer;">
                <div class="dash-source-top">
                  <div class="dash-source-icon" style="background:#409eff;"><el-icon :size="isMobile ? 14 : 20"><StarFilled /></el-icon></div>
                  <div class="dash-source-info">
                    <span class="dash-source-name">自选股</span>
                    <span v-if="!isMobile" class="dash-source-count">{{ wlStockCount || '-' }} 只</span>
                  </div>
                  <el-tag v-if="wlCount !== null" :type="wlCount > 0 ? 'danger' : 'success'" size="small" effect="dark">{{ wlCount }}</el-tag>
                </div>
                <div class="dash-source-actions" @click.stop>
                  <template v-if="!isMobile">
                    <el-button size="mini" :loading="wlLoading" @click="monitorWatchlist">立即扫描</el-button>
                    <el-switch v-model="wlAutoEnabled" size="small" active-text="自动" />
                  </template>
                  <template v-else>
                    <el-button text size="small" :loading="wlLoading" @click="monitorWatchlist" class="mob-scan-btn">扫描</el-button>
                    <el-switch v-model="wlAutoEnabled" size="small" />
                  </template>
                </div>
              </div>
              <div class="dash-source-card" :class="{ 'source-active': autoMonitor && hdAutoEnabled, 'source-filtered': alertFilterSource === 'hd', 'mob-compact': isMobile }" @click="setFilterSource('hd')" style="cursor:pointer;">
                <div class="dash-source-top">
                  <div class="dash-source-icon" style="background:#e6a23c;"><el-icon :size="isMobile ? 14 : 20"><Wallet /></el-icon></div>
                  <div class="dash-source-info">
                    <span class="dash-source-name">持仓</span>
                    <span v-if="!isMobile" class="dash-source-count">{{ hdStockCount || '-' }} 只</span>
                  </div>
                  <el-tag v-if="hdCount !== null" :type="hdCount > 0 ? 'danger' : 'success'" size="small" effect="dark">{{ hdCount }}</el-tag>
                </div>
                <div class="dash-source-actions" @click.stop>
                  <template v-if="!isMobile">
                    <el-button size="mini" :loading="hdLoading" @click="monitorHoldings">立即扫描</el-button>
                    <el-switch v-model="hdAutoEnabled" size="small" active-text="自动" />
                  </template>
                  <template v-else>
                    <el-button text size="small" :loading="hdLoading" @click="monitorHoldings" class="mob-scan-btn">扫描</el-button>
                    <el-switch v-model="hdAutoEnabled" size="small" />
                  </template>
                </div>
              </div>
              <div class="dash-source-card" :class="{ 'source-active': autoMonitor && aiAutoEnabled, 'source-filtered': alertFilterSource === 'ai', 'mob-compact': isMobile }" @click="setFilterSource('ai')" style="cursor:pointer;">
                <div class="dash-source-top">
                  <div class="dash-source-icon" style="background:#67c23a;"><el-icon :size="isMobile ? 14 : 20"><MagicStick /></el-icon></div>
                  <div class="dash-source-info">
                    <span class="dash-source-name">AI推荐</span>
                    <span v-if="!isMobile" class="dash-source-count">{{ aiStockCount || '-' }} 只</span>
                  </div>
                  <el-tag v-if="aiCount !== null" :type="aiCount > 0 ? 'danger' : 'success'" size="small" effect="dark">{{ aiCount }}</el-tag>
                </div>
                <div class="dash-source-actions" @click.stop>
                  <template v-if="!isMobile">
                    <el-button size="mini" :loading="aiLoading" @click="monitorAIPicks">立即扫描</el-button>
                    <el-switch v-model="aiAutoEnabled" size="small" active-text="自动" />
                  </template>
                  <template v-else>
                    <el-button text size="small" :loading="aiLoading" @click="monitorAIPicks" class="mob-scan-btn">扫描</el-button>
                    <el-switch v-model="aiAutoEnabled" size="small" />
                  </template>
                </div>
              </div>

              <!-- 第4个来源：自设股票 -->
              <div class="dash-source-card" :class="{ 'source-active': autoMonitor && customAutoEnabled, 'source-filtered': alertFilterSource === 'custom', 'mob-compact': isMobile }" @click="setFilterSource('custom')" style="cursor:pointer;">
                <div class="dash-source-top">
                  <div class="dash-source-icon" style="background:#9b59b6;"><el-icon :size="isMobile ? 14 : 20"><Setting /></el-icon></div>
                  <div class="dash-source-info">
                    <span class="dash-source-name">自设股票</span>
                    <span v-if="!isMobile" class="dash-source-count">{{ customStocks.length || '-' }} 只</span>
                  </div>
                  <el-tag v-if="customCount !== null" :type="customCount > 0 ? 'danger' : 'success'" size="small" effect="dark">{{ customCount }}</el-tag>
                </div>
                <div class="dash-source-actions" @click.stop>
                  <template v-if="!isMobile">
                    <el-button size="mini" :loading="customLoading" @click="monitorCustom">立即扫描</el-button>
                    <el-switch v-model="customAutoEnabled" size="small" active-text="自动" />
                  </template>
                  <template v-else>
                    <el-button text size="small" :loading="customLoading" @click="monitorCustom" class="mob-scan-btn">扫描</el-button>
                    <el-switch v-model="customAutoEnabled" size="small" />
                  </template>
                </div>
              </div>

              <!-- 第5个来源：决策算法 -->
              <div class="dash-source-card" :class="{ 'source-active': autoMonitor && decisionAutoEnabled, 'source-filtered': alertFilterSource === 'decision', 'mob-compact': isMobile }" @click="setFilterSource('decision')" style="cursor:pointer;">
                <div class="dash-source-top">
                  <div class="dash-source-icon" style="background:#1abc9c;"><el-icon :size="isMobile ? 14 : 20"><TrendCharts /></el-icon></div>
                  <div class="dash-source-info">
                    <span class="dash-source-name">决策算法</span>
                    <span v-if="!isMobile" class="dash-source-count">{{ decisionStockCount || '-' }} 只</span>
                  </div>
                  <el-tag v-if="decisionCount !== null" :type="decisionCount > 0 ? 'danger' : 'success'" size="small" effect="dark">{{ decisionCount }}</el-tag>
                </div>
                <div class="dash-source-actions" @click.stop>
                  <template v-if="!isMobile">
                    <el-button size="mini" :loading="decisionLoading" @click="monitorDecision">立即扫描</el-button>
                    <el-switch v-model="decisionAutoEnabled" size="small" active-text="自动" />
                  </template>
                  <template v-else>
                    <el-button text size="small" :loading="decisionLoading" @click="monitorDecision" class="mob-scan-btn">扫描</el-button>
                    <el-switch v-model="decisionAutoEnabled" size="small" />
                  </template>
                </div>
              </div>
            </div>

            <!-- 最新预警（按股票分组展示）- 移动端卡片化 -->
            <div v-if="groupedAlerts.length > 0" class="dash-alerts" :class="{ 'mob-card-list': isMobile }">
              <div class="dash-alerts-header">
                <span><el-icon><InfoFilled /></el-icon> 最新预警</span>
                <el-tag :type="groupedAlerts.some(g => g.maxLevel >= 3) ? 'danger' : 'warning'" size="small">{{ groupedAlerts.length }} 只股票</el-tag>
                <el-tag v-if="alertFilterSource" size="small" type="info" effect="plain" closable @close="alertFilterSource = null" style="margin-left:4px;">
                  筛选：{{ sourceLabels[alertFilterSource] }}
                </el-tag>
              </div>
              <div class="dash-alerts-list">
                <div v-for="group in paginatedGroups" :key="'grp-'+group.stockCode" class="dash-alert-group" :class="{ 'has-expanded': expandedGroups.has(group.stockCode) }">
                  <!-- 股票分组头部（综合信号） -->
                  <div class="da-group-header" @click="toggleGroup(group.stockCode)">
                    <div class="da-left">
                      <div class="da-dot" :class="group.maxLevel >= 3 ? 'dad-critical' : group.maxLevel >= 2 ? 'dad-warning' : 'dad-info'"></div>
                    </div>
                    <div class="da-body">
                      <div class="da-row1">
                        <span class="da-stock">{{ group.stockName }} <small class="da-code">{{ group.stockCode }}</small></span>
                        <el-tag v-if="group.consolidatedSignal" :type="getActionSignalType(group.consolidatedSignal)" size="mini" effect="dark" class="da-action da-consolidated" :class="{ 'is-conflict': group.consolidatedSignal === 'CONFLICT' }">{{ getActionSignalLabel(group.consolidatedSignal) }} {{ group.alerts.length > 1 ? `(${group.alerts.length}个指标)` : '' }}</el-tag>
                        <el-tag :type="group.maxLevel >= 3 ? 'danger' : group.maxLevel >= 2 ? 'warning' : 'primary'" size="mini" effect="dark" class="da-level">{{ group.maxLevel >= 3 ? 'CRITICAL' : group.maxLevel >= 2 ? 'WARNING' : 'INFO' }}</el-tag>
                        <el-icon class="da-expand-icon"><ArrowDown /></el-icon>
                      </div>
                      <div class="da-row2 da-preview">
                        <span class="da-type">{{ getTypeLabel(group.alerts[0].alert_type) }}</span>
                        <span class="da-msg">{{ group.alerts[0].message }}</span>
                      </div>
                    </div>
                  </div>
                  <!-- 展开：各指标详情 -->
                  <div v-if="expandedGroups.has(group.stockCode)" class="da-group-details">
                    <div v-for="(alert, idx) in group.alerts" :key="'al-'+group.stockCode+'-'+idx" class="dash-alert-item da-sub-item" :class="'da-' + alert.alert_level.toLowerCase()">
                      <div class="da-left">
                        <div class="da-dot" :class="'dad-' + alert.alert_level.toLowerCase()"></div>
                      </div>
                      <div class="da-body">
                        <div class="da-row1">
                          <span class="da-source-tag">{{ alert._source }}</span>
                          <el-tag v-if="alert.action_signal" :type="getActionSignalType(alert.action_signal)" size="mini" effect="dark" class="da-action">{{ getActionSignalLabel(alert.action_signal) }}</el-tag>
                        </div>
                        <div class="da-row2">
                          <span class="da-type">{{ getTypeLabel(alert.alert_type) }}</span>
                          <span class="da-msg">{{ alert.message }}</span>
                        </div>
                        <div v-if="alert.recommendation" class="da-row3">
                          <el-icon style="color:#67c23a;"><InfoFilled /></el-icon>
                          <span>{{ alert.recommendation }}</span>
                        </div>
                        <div class="da-time">{{ formatTime(alert.timestamp) }}</div>
                      </div>
                    </div>
                  </div>
                </div>
                <!-- 分页器放在列表内部，确保移动端滚动后可见 -->
                <div v-if="groupedAlerts.length > alertPageSize" class="dash-alerts-pager">
                  <el-pagination
                    small
                    layout="prev, pager, next"
                    :total="groupedAlerts.length"
                    :page-size="alertPageSize"
                    v-model:current-page="alertCurrentPage"
                  />
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- 自设监控（添加/管理自定义股票） -->
        <el-tab-pane label="自设监控" name="custom">
          <div class="tab-pane-content">
            <div class="custom-add-section">
              <div class="custom-add-row">
                <el-input v-model="customBatchInput" type="textarea" :rows="3" placeholder="批量添加股票，格式：股票代码 名称（用逗号或换行分隔）&#10;例：600519 贵州茅台, 000858 五粮液" size="small" style="flex:1;" />
                <el-button size="small" type="primary" @click="addCustomBatch">批量添加</el-button>
              </div>
            </div>

            <div v-if="customStocks.length > 0" class="custom-stock-list">
              <div v-for="s in customStocks" :key="s.code" class="custom-stock-item">
                <span class="csi-code">{{ s.code }}</span>
                <span class="csi-name">{{ s.name }}</span>
                <el-button size="mini" type="danger" plain :icon="Delete" @click="removeCustomStock(s.code)" circle />
              </div>
            </div>
            <el-empty v-else description="尚未添加自设股票" :image-size="60" />

            <div v-if="customResults.length > 0" class="dash-alerts" style="margin-top:8px;">
              <div class="dash-alerts-header">
                <span><el-icon><InfoFilled /></el-icon> 自设股票预警结果</span>
                <el-tag :type="customResults.some(a => a.alert_level === 'CRITICAL') ? 'danger' : 'warning'" size="small">{{ customResults.length }} 条</el-tag>
              </div>
              <div class="dash-alerts-list">
                <div v-for="(alert, index) in customResults" :key="'cs-'+index" class="dash-alert-item">
                  <div class="da-left">
                    <div class="da-dot" :class="'dad-' + alert.alert_level.toLowerCase()"></div>
                  </div>
                  <div class="da-body">
                    <div class="da-row1">
                      <span class="da-stock">{{ alert.stock_name || alert.stock_code }}</span>
                      <el-tag v-if="alert.action_signal" :type="getActionSignalType(alert.action_signal)" size="mini" effect="dark" class="da-action">{{ getActionSignalLabel(alert.action_signal) }}</el-tag>
                      <el-tag :type="getAlertLevelType(alert.alert_level)" size="mini" effect="dark" class="da-level">{{ alert.alert_level }}</el-tag>
                    </div>
                    <div class="da-row2">
                      <span class="da-type">{{ getTypeLabel(alert.alert_type) }}</span>
                      <span class="da-msg">{{ alert.message }}</span>
                    </div>
                    <div v-if="alert.recommendation" class="da-row3">
                      <el-icon style="color:#67c23a;"><InfoFilled /></el-icon>
                      <span>{{ alert.recommendation }}</span>
                    </div>
                    <div class="da-time">{{ formatTime(alert.timestamp) }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- 规则设置 -->
        <el-tab-pane label="规则设置" name="rules">
          <div class="tab-pane-content">
            <div class="table-scroll-wrapper">
              <el-table :data="rulesList" border stripe size="small" class="data-table" height="100%">
                <el-table-column prop="name" label="规则" min-width="140">
                  <template #default="{ row }">{{ getTypeLabel(row.name) || row.name }}</template>
                </el-table-column>
                <el-table-column prop="desc" label="说明" min-width="240" />
                <el-table-column label="分类" width="80" align="center">
                  <template #default="{ row }">
                    <el-tag :type="getRuleType(row.category)" size="small">{{ row.category }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="交易信号" width="90" align="center">
                  <template #default="{ row }">
                    <el-tag v-if="row.action_signal || getActionSignal(row.name)" :type="getActionSignalType(row.action_signal || getActionSignal(row.name))" size="small" effect="dark">{{ getActionSignalLabel(row.action_signal || getActionSignal(row.name)) }}</el-tag>
                    <span v-else>-</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup>
defineOptions({ name: 'SmartAlert' })
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { Warning, InfoFilled, Refresh, StarFilled, Wallet, MagicStick, Bell, BellFilled, Setting, Delete, ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import api, { watchlistApi, holdingsApi, aiStockPickApi, decisionApi } from '@/api'

/* ========== 基础状态 ========== */
const activeTab = ref('monitor')
const isMobile = ref(window.innerWidth < 768)
const resizeHandler = () => { isMobile.value = window.innerWidth < 768 }
window.addEventListener('resize', resizeHandler)

/* ========== 计算属性 ========== */
const totalAlertCount = computed(() => {
  let n = 0
  if (wlCount.value !== null) n += wlCount.value
  if (hdCount.value !== null) n += hdCount.value
  if (aiCount.value !== null) n += aiCount.value
  if (customCount.value !== null) n += customCount.value
  if (decisionCount.value !== null) n += decisionCount.value
  return n
})
const totalMonitoredStocks = computed(() => wlStockCount.value + hdStockCount.value + aiStockCount.value + customStocks.value.length + decisionStockCount.value)
const activeSources = computed(() => {
  let n = 0
  if (wlAutoEnabled.value && wlStockCount.value > 0) n++
  if (hdAutoEnabled.value && hdStockCount.value > 0) n++
  if (aiAutoEnabled.value && aiStockCount.value > 0) n++
  if (customAutoEnabled.value && customStocks.value.length > 0) n++
  if (decisionAutoEnabled.value && decisionStockCount.value > 0) n++
  return n
})
/* ========== 自动监控 + 通知 ========== */
const autoMonitor = ref(localStorage.getItem('alert_auto_monitor') === '1')
const notifyEnabled = ref(localStorage.getItem('alert_notify') === '1')
let monitorTimer = null
const unreadCount = ref(0)
const lastMonitorTime = ref(null)

// A股交易时段判断（工作日 9:30-11:30 / 13:00-15:00）
function isTradingTime() {
  const now = new Date()
  const day = now.getDay() // 0=周日, 6=周六
  if (day === 0 || day === 6) return false
  const h = now.getHours(), m = now.getMinutes()
  const totalMin = h * 60 + m
  return (totalMin >= 570 && totalMin <= 690) || (totalMin >= 780 && totalMin <= 900)
}

// 保存自动监控开关状态
function saveAutoMonitor(val) {
  localStorage.setItem('alert_auto_monitor', val ? '1' : '0')
}

// 各来源自动启用
const wlAutoEnabled = ref(true)
const hdAutoEnabled = ref(true)
const aiAutoEnabled = ref(true)
const customAutoEnabled = ref(true)
const decisionAutoEnabled = ref(true)

// 缓存股票代码 (减少重复请求)
const cachedWatchlist = ref([])
const cachedHoldings = ref([])
const cachedAIPicks = ref([])

// 上次结果 (用于增量检测)
let prevResultsKey = ''

/* ========== 规则 ========== */
const rulesSummary = computed(() => {
  const names = activeRules.value.map(r => getTypeLabel(r)).filter(Boolean)
  return names.length ? `${names.slice(0, 3).join(', ')}${names.length > 3 ? `等${names.length}项` : ''}` : ''
})
const activeRules = computed(() => {
  const selected = monitorParams.rules
  return selected.length > 0 ? selected : Object.keys(typeLabels)
})

/* ========== 手动监控状态 ========== */
const wlLoading = ref(false)
const hdLoading = ref(false)
const aiLoading = ref(false)
const customLoading = ref(false)
const decisionLoading = ref(false)
const monitorClicked = ref(false)

// 集成计数 & 股票数量
const wlCount = ref(null)
const hdCount = ref(null)
const aiCount = ref(null)
const customCount = ref(null)
const decisionCount = ref(null)
const wlStockCount = ref(0)
const hdStockCount = ref(0)
const aiStockCount = ref(0)
const decisionStockCount = ref(0)

// 分来源存储预警结果
const wlResults = ref([])
const hdResults = ref([])
const aiResults = ref([])
const customResults = ref([])
const decisionResults = ref([])

// 数据变更时自动持久化到 localStorage
watch([wlResults, hdResults, aiResults, customResults, decisionResults, wlCount, hdCount, aiCount, customCount, decisionCount, wlStockCount, hdStockCount, aiStockCount, decisionStockCount], () => {
  _saveAlertsToStorage()
}, { deep: false })

// ---- 持久化：当天预警存 localStorage，次日自动清 ----
const ALERT_STORAGE_KEY = 'smart_alert_today'
const ALERT_STORAGE_DATE_KEY = 'smart_alert_date'
function _loadAlertsFromStorage() {
  try {
    const today = new Date().toISOString().slice(0, 10)
    if (localStorage.getItem(ALERT_STORAGE_DATE_KEY) !== today) {
      localStorage.removeItem(ALERT_STORAGE_KEY)
      localStorage.removeItem(ALERT_STORAGE_DATE_KEY)
      return
    }
    const raw = localStorage.getItem(ALERT_STORAGE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw)
    wlResults.value = saved.wl || []
    hdResults.value = saved.hd || []
    aiResults.value = saved.ai || []
    customResults.value = saved.custom || []
    decisionResults.value = saved.decision || []
    wlCount.value = saved.wlCount ?? null
    hdCount.value = saved.hdCount ?? null
    aiCount.value = saved.aiCount ?? null
    customCount.value = saved.customCount ?? null
    decisionCount.value = saved.decisionCount ?? null
    wlStockCount.value = saved.wlStockCount || 0
    hdStockCount.value = saved.hdStockCount || 0
    aiStockCount.value = saved.aiStockCount || 0
    decisionStockCount.value = saved.decisionStockCount || 0
    if (wlResults.value.length || hdResults.value.length || aiResults.value.length || customResults.value.length || decisionResults.value.length) {
      monitorClicked.value = true
    }
  } catch {}
}
function _saveAlertsToStorage() {
  const today = new Date().toISOString().slice(0, 10)
  localStorage.setItem(ALERT_STORAGE_DATE_KEY, today)
  localStorage.setItem(ALERT_STORAGE_KEY, JSON.stringify({
    wl: wlResults.value, hd: hdResults.value, ai: aiResults.value, custom: customResults.value, decision: decisionResults.value,
    wlCount: wlCount.value, hdCount: hdCount.value, aiCount: aiCount.value, customCount: customCount.value, decisionCount: decisionCount.value,
    wlStockCount: wlStockCount.value, hdStockCount: hdStockCount.value, aiStockCount: aiStockCount.value, decisionStockCount: decisionStockCount.value,
  }))
}

// 来源卡片筛选（null=全部，其他=仅显示对应来源）
const alertFilterSource = ref(null)
const sourceLabels = { wl: '自选股', hd: '持仓', ai: 'AI推荐', custom: '自设股票', decision: '决策算法' }
function setFilterSource(key) {
  alertFilterSource.value = alertFilterSource.value === key ? null : key
  alertCurrentPage.value = 1
  expandedGroups.value = new Set()
}

// 分页
const alertPageSize = ref(20)
const alertCurrentPage = ref(1)

// 分组展开状态
const expandedGroups = ref(new Set())
function toggleGroup(code) {
  const s = new Set(expandedGroups.value)
  if (s.has(code)) s.delete(code)
  else s.add(code)
  expandedGroups.value = s
}

// 自设股票
const customStocks = ref(loadCustomStocks())
const customBatchInput = ref('')
function loadCustomStocks() {
  try { return JSON.parse(localStorage.getItem('alert_custom_stocks') || '[]') }
  catch { return [] }
}
function saveCustomStocks() {
  localStorage.setItem('alert_custom_stocks', JSON.stringify(customStocks.value))
}
const allCustomCodes = computed(() => customStocks.value.map(s => s.code).filter(Boolean))

const showRulesPicker = ref(false)
const monitorParams = reactive({ stock: '', stockName: '', rules: [] })
const rulesList = ref([])

const typeLabels = {
  MACD_GOLDEN_CROSS: 'MACD金叉', MACD_DEATH_CROSS: 'MACD死叉',
  KDJ_OVERSOLD: 'KDJ超卖', KDJ_OVERBOUGHT: 'KDJ超买',
  RSI_OVERSOLD: 'RSI超卖反弹', RSI_OVERBOUGHT: 'RSI超买回落',
  VOLUME_BREAKOUT: '放量突破', PRICE_DROP: '大幅下跌',
  STOP_LOSS: '止损预警', HIGH_VOLATILITY: '高波动预警',
  TREND_REVERSAL: '均线金叉/死叉', SUPPORT_BREAK: '支撑位突破',
  RESISTANCE_BREAK: '阻力位突破', PRICE_BREAKOUT: '价格突破',
  POSITION_STOP_LOSS: '成本止损', POSITION_TAKE_PROFIT: '成本止盈',
  POSITION_TRAILING_STOP: '移动止损', POSITION_COST_PRESSURE: '成本压力位',
  // 决策算法预警类型
  DECISION_BUY: '决策算法买入', DECISION_SELL: '决策算法卖出',
  ALGO_MAGIC_WAVE_BUY: '神奇电波红波', ALGO_MAGIC_WAVE_SELL: '神奇电波绿波',
  ALGO_ANOMALY_DETECT_BUY: '异动拉升', ALGO_BOTTOM_OPPORTUNITY_BUY: '底部寻机',
  ALGO_TD_SEQUENTIAL_BUY: 'TD序列买入', ALGO_TD_SEQUENTIAL_SELL: 'TD序列卖出',
  ALGO_CHANNEL_BREAKOUT_BUY: '通道突破上轨', ALGO_CHANNEL_BREAKOUT_SELL: '通道跌破下轨',
  POSITION_DECISION_SELL: '持仓决策止损', POSITION_DECISION_HOLD: '持仓决策持有',
}

/* ========== 各来源的预警规则（按 action_signal 区分） ========== */
const BUY_ADD_RULES = [
  'macd_golden_cross', 'kdj_oversold', 'rsi_oversold',
  'volume_breakout', 'ma_golden_cross', 'bollinger_lower_bounce', 'breakout_high',
]
const SELL_REDUCE_RULES = [
  'macd_death_cross', 'kdj_overbought', 'rsi_overbought',
  'price_drop', 'stop_loss', 'high_volatility',
  'ma_death_cross', 'bollinger_upper_reversal', 'breakdown_low',
]
const POSITION_RULES = [
  'position_stop_loss', 'position_take_profit', 'position_trailing_stop', 'position_cost_pressure',
]
const SOURCE_RULES = {
  wl: BUY_ADD_RULES,
  ai: BUY_ADD_RULES,
  hd: [...BUY_ADD_RULES, ...SELL_REDUCE_RULES, ...POSITION_RULES],
  custom: null,
}

const actionSignalLabels = {
  BUY: '买入', ADD: '加仓', REDUCE: '减仓', SELL: '卖出', HOLD: '观望', CONFLICT: '多空分歧'
}

/* ========== 按股票分组预警 + 综合信号 ========== */
const BULLISH_SIGNALS = new Set(['BUY', 'ADD'])
const BEARISH_SIGNALS = new Set(['REDUCE', 'SELL'])

function computeConsolidatedSignal(alerts) {
  const signals = new Set(alerts.map(a => a.action_signal).filter(Boolean))
  if (signals.size <= 1) return Array.from(signals)[0] || null

  let hasBullish = false, hasBearish = false, hasHold = false
  for (const s of signals) {
    if (BULLISH_SIGNALS.has(s)) hasBullish = true
    else if (BEARISH_SIGNALS.has(s)) hasBearish = true
    else if (s === 'HOLD') hasHold = true
  }

  if (hasBullish && hasBearish) return 'CONFLICT'
  if (hasBullish && hasHold) return 'ADD'
  if (hasBearish && hasHold) return 'SELL'
  if (hasBullish) return 'ADD'
  if (hasBearish) return 'SELL'
  return 'HOLD'
}

const groupedAlerts = computed(() => {
  const items = [...wlResults.value, ...hdResults.value, ...aiResults.value, ...customResults.value, ...decisionResults.value]
  const seen = new Set()
  const deduped = []
  for (const a of items) {
    const key = `${a.stock_code}|${a.alert_type}|${a.message}`
    if (seen.has(key)) continue
    seen.add(key)
    deduped.push(a)
  }

  const filtered = alertFilterSource.value
    ? deduped.filter(a => a._sourceKey === alertFilterSource.value)
    : deduped

  const grouped = new Map()
  for (const a of filtered) {
    const code = a.stock_code
    if (!grouped.has(code)) grouped.set(code, [])
    grouped.get(code).push(a)
  }

  return Array.from(grouped.entries())
    .map(([stockCode, alerts]) => ({
      stockCode,
      stockName: alerts[0].stock_name || stockCode,
      alerts: alerts.sort((a, b) => new Date(b.timestamp || b._timestamp || 0) - new Date(a.timestamp || a._timestamp || 0)),
      consolidatedSignal: computeConsolidatedSignal(alerts),
      maxLevel: alerts.reduce((max, a) => {
        const order = { EMERGENCY: 4, CRITICAL: 3, WARNING: 2, INFO: 1 }
        return Math.max(max, order[a.alert_level] || 0)
      }, 0),
    }))
    .sort((a, b) => {
      if (b.consolidatedSignal === 'CONFLICT' && a.consolidatedSignal !== 'CONFLICT') return -1
      if (a.consolidatedSignal === 'CONFLICT' && b.consolidatedSignal !== 'CONFLICT') return 1
      return b.maxLevel - a.maxLevel
    })
})

const paginatedGroups = computed(() => {
  const start = (alertCurrentPage.value - 1) * alertPageSize.value
  return groupedAlerts.value.slice(start, start + alertPageSize.value)
})

const allAlerts = computed(() => {
  const items = [...wlResults.value, ...hdResults.value, ...aiResults.value, ...customResults.value, ...decisionResults.value]
  const seen = new Set()
  const deduped = []
  for (const a of items) {
    const key = `${a.stock_code}|${a.alert_type}|${a.message}`
    if (seen.has(key)) continue
    seen.add(key)
    deduped.push(a)
  }
  const filtered = alertFilterSource.value
    ? deduped.filter(a => a._sourceKey === alertFilterSource.value)
    : deduped
  return filtered.sort((a, b) => new Date(b.timestamp || b._timestamp || 0) - new Date(a.timestamp || a._timestamp || 0))
})
const paginatedAlerts = computed(() => {
  const start = (alertCurrentPage.value - 1) * alertPageSize.value
  return allAlerts.value.slice(start, start + alertPageSize.value)
})

/* ========== 通知权限 ========== */
const requestNotifyPermission = async () => {
  if (!notifyEnabled.value) { localStorage.setItem('alert_notify', '0'); return }
  localStorage.setItem('alert_notify', '1')
  if (!('Notification' in window)) { ElMessage.warning('浏览器不支持桌面通知'); return }
  if (Notification.permission === 'granted') return
  if (Notification.permission === 'denied') { ElMessage.warning('通知已被禁止，请在浏览器设置中开启'); return }
  const result = await Notification.requestPermission()
  if (result !== 'granted') notifyEnabled.value = false
}

const sendBrowserNotify = (title, body, level) => {
  if (!notifyEnabled.value || !('Notification' in window) || Notification.permission !== 'granted') return
  try {
    const n = new Notification(`[${level}] ${title}`, {
      body, icon: '/favicon.ico', tag: 'alert-' + Date.now(),
    })
    setTimeout(() => n.close(), 5000)
  } catch (e) { /* 静默失败 */ }
}

const playAlertSound = () => {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain); gain.connect(ctx.destination)
    osc.frequency.value = 880; gain.gain.value = 0.1
    osc.start(); setTimeout(() => { osc.stop(); ctx.close() }, 200)
  } catch (e) { /* 静默失败 */ }
}

/* ========== 自动监控核心逻辑 ========== */
const toggleAutoMonitor = async (val) => {
  if (val) {
    autoMonitor.value = true
    saveAutoMonitor(true)
    // 每60秒轮询（交易时段内执行，非交易时段跳过）
    monitorTimer = setInterval(runAutoMonitorCycle, 60000)
    await runAutoMonitorCycle()
  } else {
    autoMonitor.value = false
    saveAutoMonitor(false)
    clearInterval(monitorTimer); monitorTimer = null
  }
}

const buildResultKey = (results) => {
  return results.map(a => `${a.stock_code}|${a.alert_type}|${a.message}`).join('::')
}

const runAutoMonitorCycle = async () => {
  if (!isTradingTime()) return
  try {
    const wlAlerts = [], hdAlerts = [], aiAlerts = [], customAlerts = [], decisionAlerts = [], allResults = []
    let totalNew = 0
    const timestamp = Date.now()

    const [wlRes, hdRes, aiRes] = await Promise.allSettled([
      watchlistApi.getMyWatchlist(),
      holdingsApi.getMy(),
      aiStockPickApi.getLatest(),
    ])

    // ---- 自选股 ----
    if (wlAutoEnabled.value && wlRes.status === 'fulfilled') {
      const wl = wlRes.value?.stocks || wlRes.value?.data || []
      if (Array.isArray(wl)) {
        cachedWatchlist.value = wl.map(s => ({ code: s.stock_code || s.code, name: s.stock_name || s.name })).filter(s => s.code)
        wlStockCount.value = cachedWatchlist.value.length
        if (cachedWatchlist.value.length > 0) {
          const mon = await api.post('/alerts/monitor', { pool: cachedWatchlist.value.map(s => s.code), rules: SOURCE_RULES.wl })
          if (mon.status === 'success') {
            let count = 0
            for (const [code, info] of Object.entries(mon.data)) {
              const stock = cachedWatchlist.value.find(s => s.code === code)
              for (const a of info.alerts || []) {
                const item = { ...a, stock_name: a.stock_name || stock?.name || code, _source: '自选股', _sourceKey: 'wl', _timestamp: timestamp }
                wlAlerts.push(item); allResults.push(item)
              }
              count += info.alert_count || 0
            }
            wlCount.value = count
          }
        }
      }
    }

    // ---- 持仓 ----
    if (hdAutoEnabled.value && hdRes.status === 'fulfilled') {
      const hd = hdRes.value?.holdings || hdRes.value?.data || []
      if (Array.isArray(hd)) {
        cachedHoldings.value = hd.map(h => ({ code: h.stock_code || h.code, name: h.stock_name || h.name })).filter(s => s.code)
        hdStockCount.value = cachedHoldings.value.length
        if (cachedHoldings.value.length > 0) {
          const hcm = {}
          for (const h of hd) {
            const code = h.stock_code || h.code
            if (!code) continue
            const cp = h.cost_price || h.costPrice || 0
            if (cp > 0) {
              hcm[code] = {
                cost_price: cp, quantity: h.quantity || h.shares || 0,
                position_type: h.position_type || h.positionType || 'short',
                max_profit_ratio: h.max_profit_ratio || h.maxProfitRatio || h.profit_ratio || h.profitRatio || 0,
                profit_ratio: h.profit_ratio || h.profitRatio || 0,
              }
            }
          }
          const mon = await api.post('/alerts/monitor', { pool: cachedHoldings.value.map(s => s.code), rules: SOURCE_RULES.hd, holding_context_map: Object.keys(hcm).length ? hcm : undefined })
          if (mon.status === 'success') {
            let count = 0
            for (const [code, info] of Object.entries(mon.data)) {
              const h = cachedHoldings.value.find(s => s.code === code)
              for (const a of info.alerts || []) {
                const item = { ...a, stock_name: a.stock_name || h?.name || code, _source: '持仓', _sourceKey: 'hd', _timestamp: timestamp }
                hdAlerts.push(item); allResults.push(item)
              }
              count += info.alert_count || 0
            }
            hdCount.value = count
          }
        }
      }
    }

    // ---- AI推荐 ----
    if (aiAutoEnabled.value && aiRes.status === 'fulfilled') {
      const latest = aiRes.value
      const data = latest?.picks_data ? (typeof latest.picks_data === 'string' ? JSON.parse(latest.picks_data) : latest.picks_data) : null
      if (data) {
        const picks = [...(data.short_term || []), ...(data.long_term || [])]
        cachedAIPicks.value = picks.filter(p => p.code).map(p => ({ code: p.code, name: p.name }))
        aiStockCount.value = cachedAIPicks.value.length
        if (cachedAIPicks.value.length > 0) {
          const mon = await api.post('/alerts/monitor', { pool: cachedAIPicks.value.map(s => s.code), rules: SOURCE_RULES.ai })
          if (mon.status === 'success') {
            let count = 0
            for (const [code, info] of Object.entries(mon.data)) {
              const pick = cachedAIPicks.value.find(s => s.code === code)
              for (const a of info.alerts || []) {
                const item = { ...a, stock_name: a.stock_name || pick?.name || code, _source: 'AI推荐', _sourceKey: 'ai', _timestamp: timestamp }
                aiAlerts.push(item); allResults.push(item)
              }
              count += info.alert_count || 0
            }
            aiCount.value = count
          }
        }
      }
    }

    // ---- 自设股票 ----
    if (customAutoEnabled.value && allCustomCodes.value.length > 0) {
      const mon = await api.post('/alerts/monitor', { pool: allCustomCodes.value })
      if (mon.status === 'success') {
        let count = 0
        for (const [code, info] of Object.entries(mon.data)) {
          const stock = customStocks.value.find(s => s.code === code)
          for (const a of info.alerts || []) {
            const item = { ...a, stock_name: a.stock_name || stock?.name || code, _source: '自设股票', _sourceKey: 'custom', _timestamp: timestamp }
            customAlerts.push(item); allResults.push(item)
          }
          count += info.alert_count || 0
        }
        customCount.value = count
      }
    }

    // ---- 决策算法预警 ----
    if (decisionAutoEnabled.value) {
      try {
        const decisionRes = await decisionApi.monitorWatchlist()
        if (decisionRes.status === 'success' && decisionRes.data) {
          const { alerts, stocks, summary } = decisionRes.data
          decisionStockCount.value = summary?.total || 0
          if (alerts && alerts.length > 0) {
            for (const a of alerts) {
              const item = { ...a, _source: '决策算法', _sourceKey: 'decision', _timestamp: timestamp }
              decisionAlerts.push(item); allResults.push(item)
            }
          }
          decisionCount.value = alerts?.length || 0
        }
      } catch (e) {
        console.warn('决策算法预警失败:', e?.message || e)
      }
    }

    // 写入分来源存储
    wlResults.value = wlAlerts
    hdResults.value = hdAlerts
    aiResults.value = aiAlerts
    customResults.value = customAlerts
    decisionResults.value = decisionAlerts

    // ---- 增量检测 + 通知 ----
    const newKey = buildResultKey(allResults)
    if (prevResultsKey && newKey !== prevResultsKey) {
      const prevSet = new Set(prevResultsKey.split('::'))
      for (const a of allResults) {
        const ak = `${a.stock_code}|${a.alert_type}|${a.message}`
        if (!prevSet.has(ak)) {
          a._is_new = true
          totalNew++
          if (a.alert_level === 'CRITICAL' || a.alert_level === 'EMERGENCY') {
            sendBrowserNotify(a.stock_name || a.stock_code, `${getTypeLabel(a.alert_type)}: ${a.message}`, a.alert_level)
          }
        }
      }
      if (totalNew > 0) playAlertSound()
    }
    prevResultsKey = newKey

    unreadCount.value = allResults.filter(a => a._is_new).length
    lastMonitorTime.value = new Date().toISOString()
  } catch (e) {
    console.error('自动监控轮询失败:', e)
  }
}

/* ========== 自设股票管理 ========== */
const addCustomBatch = () => {
  const lines = customBatchInput.value.split(/[,，\n\r]+/).map(s => s.trim()).filter(Boolean)
  if (!lines.length) { ElMessage.warning('请输入股票代码'); return }
  let added = 0
  for (const line of lines) {
    const parts = line.split(/\s+/)
    const code = parts[0]
    const name = parts.slice(1).join(' ') || code
    if (!code || customStocks.value.find(s => s.code === code)) continue
    customStocks.value.push({ code, name })
    added++
  }
  if (added > 0) { saveCustomStocks(); ElMessage.success(`成功添加 ${added} 只股票`) }
  else ElMessage.info('所有股票已存在')
  customBatchInput.value = ''
}

const removeCustomStock = (code) => {
  customStocks.value = customStocks.value.filter(s => s.code !== code)
  saveCustomStocks()
}

/* ========== 手动监控 ========== */
const monitorCustom = async () => {
  if (!customStocks.value.length) { ElMessage.warning('请先添加自设股票'); return }
  customLoading.value = true; monitorClicked.value = true; monitorClicked.value = true
  try {
    const res = await api.post('/alerts/monitor', { pool: allCustomCodes.value })
    if (res.status === 'success') {
      let count = 0
      const results = []
      for (const [code, info] of Object.entries(res.data)) {
        const stock = customStocks.value.find(s => s.code === code)
        for (const a of info.alerts || []) {
          results.push({ ...a, stock_name: a.stock_name || stock?.name || code, _source: '自设股票', _sourceKey: 'custom' })
        }
        count += info.alert_count || 0
      }
      customCount.value = count
      customResults.value = results
      ElMessage.success(count > 0 ? `发现 ${count} 条预警` : '未发现预警')
    }
  } catch (e) {
    ElMessage.error('监控失败: ' + (e.response?.data?.detail || e.message))
  } finally { customLoading.value = false }
}

const fetchRules = async () => {
  try {
    const res = await api.get('/alerts/rules')
    if (res.status === 'success') rulesList.value = res.data.rules
  } catch (e) { console.error('获取规则列表失败:', e) }
}

const monitorWatchlist = async () => {
  wlLoading.value = true
  try {
    const wlRes = await watchlistApi.getMyWatchlist()
    let stocks = wlRes?.stocks || wlRes?.data || []
    if (!Array.isArray(stocks)) stocks = []
    const codes = stocks.map(s => s.stock_code || s.code).filter(Boolean)
    if (!codes.length) { ElMessage.warning('自选股为空'); return }
    const res = await api.post('/alerts/monitor', { pool: codes, rules: SOURCE_RULES.wl })
    if (res.status === 'success') {
      const data = res.data
      const results = []
      let count = 0
      for (const [code, info] of Object.entries(data)) {
        const stock = stocks.find(s => (s.stock_code || s.code) === code)
        for (const a of info.alerts || []) {
          results.push({ ...a, stock_name: a.stock_name || stock?.stock_name || stock?.name || code, _source: '自选股', _sourceKey: 'wl' })
        }
        count += info.alert_count || 0
      }
      wlCount.value = count
      wlStockCount.value = codes.length
      wlResults.value = results
    }
  } catch (e) {
    ElMessage.error('自选股监控失败: ' + (e.response?.data?.detail || e.message))
  } finally { wlLoading.value = false }
}

const monitorHoldings = async () => {
  hdLoading.value = true
  try {
    const hdRes = await holdingsApi.getMy()
    let holdings = hdRes?.holdings || hdRes?.data || []
    if (!Array.isArray(holdings)) holdings = []
    const codes = holdings.map(h => h.stock_code || h.code).filter(Boolean)
    if (!codes.length) { ElMessage.warning('持仓为空'); return }

    // 构建持仓上下文：成本价 / 持仓类型 / 最高盈利
    const holding_context_map = {}
    for (const h of holdings) {
      const code = h.stock_code || h.code
      if (!code) continue
      const costPrice = h.cost_price || h.costPrice || 0
      if (costPrice > 0) {
        holding_context_map[code] = {
          cost_price: costPrice,
          quantity: h.quantity || h.shares || 0,
          position_type: h.position_type || h.positionType || 'short',
          max_profit_ratio: h.max_profit_ratio || h.maxProfitRatio || h.profit_ratio || h.profitRatio || 0,
          profit_ratio: h.profit_ratio || h.profitRatio || 0,
        }
      }
    }

    const res = await api.post('/alerts/monitor', {
      pool: codes,
      rules: SOURCE_RULES.hd,
      holding_context_map: Object.keys(holding_context_map).length ? holding_context_map : undefined,
    })
    if (res.status === 'success') {
      const data = res.data
      const results = []
      let count = 0
      for (const [code, info] of Object.entries(data)) {
        const h = holdings.find(h => (h.stock_code || h.code) === code)
        for (const a of info.alerts || []) {
          results.push({ ...a, stock_name: a.stock_name || h?.stock_name || h?.name || code, _source: '持仓', _sourceKey: 'hd' })
        }
        count += info.alert_count || 0
      }
      hdCount.value = count
      hdStockCount.value = codes.length
      hdResults.value = results
    }
  } catch (e) {
    ElMessage.error('持仓监控失败: ' + (e.response?.data?.detail || e.message))
  } finally { hdLoading.value = false }
}

const monitorAIPicks = async () => {
  aiLoading.value = true
  try {
    const latest = await aiStockPickApi.getLatest()
    const data = latest?.picks_data ? (typeof latest.picks_data === 'string' ? JSON.parse(latest.picks_data) : latest.picks_data) : null
    if (!data) { ElMessage.warning('暂无AI推荐数据'); return }
    const picks = [...(data.short_term || []), ...(data.long_term || [])]
    const codes = picks.map(p => p.code).filter(Boolean)
    if (!codes.length) { ElMessage.warning('AI推荐列表为空'); return }
    const res = await api.post('/alerts/monitor', { pool: codes, rules: SOURCE_RULES.ai })
    if (res.status === 'success') {
      const rdata = res.data
      const results = []
      let count = 0
      for (const [code, info] of Object.entries(rdata)) {
        const pick = picks.find(p => p.code === code)
        for (const a of info.alerts || []) {
          results.push({ ...a, stock_name: a.stock_name || pick?.name || code, _source: 'AI推荐', _sourceKey: 'ai' })
        }
        count += info.alert_count || 0
      }
      aiCount.value = count
      aiStockCount.value = codes.length
      aiResults.value = results
    }
  } catch (e) {
    ElMessage.error('AI推荐监控失败: ' + (e.response?.data?.detail || e.message))
  } finally { aiLoading.value = false }
}

// 决策算法预警监控
const monitorDecision = async () => {
  decisionLoading.value = true
  try {
    const res = await decisionApi.monitorWatchlist()
    if (res.status === 'success' && res.data) {
      const { alerts, stocks, summary } = res.data
      decisionStockCount.value = summary?.total || 0
      decisionCount.value = alerts?.length || 0
      decisionResults.value = (alerts || []).map(a => ({
        ...a,
        _source: '决策算法',
        _sourceKey: 'decision',
      }))
      ElMessage.success(decisionCount.value > 0 ? `发现 ${decisionCount.value} 条决策预警` : '未发现决策预警')
    }
  } catch (e) {
    ElMessage.error('决策算法监控失败: ' + (e.response?.data?.detail || e.message))
  } finally { decisionLoading.value = false }
}

/* ========== 统计 / 历史 / 通用 ========== */
const refreshAll = () => { fetchRules(); if (autoMonitor.value) runAutoMonitorCycle() }

/* ========== 工具函数 ========== */
const getAlertLevelType = (level) => ({ INFO: 'primary', WARNING: 'warning', CRITICAL: 'danger', EMERGENCY: 'danger' }[level] || 'info')
const getTypeLabel = (t) => typeLabels[t] || t
const getRuleType = (cat) => ({ '技术指标': 'primary', '量价异动': 'warning', '风险预警': 'danger', '均线系统': 'success', '布林带': '', '价格突破': '' }[cat] || 'info')
const getActionSignalLabel = (s) => actionSignalLabels[s] || ''
const getActionSignalType = (s) => ({ BUY: 'success', ADD: '', REDUCE: 'warning', SELL: 'danger', HOLD: 'info', CONFLICT: '' }[s] || 'info')

// 规则名称到交易信号的映射（后端规则名 → 信号）
const RULE_ACTION_MAP = {
  macd_golden_cross: 'ADD', macd_death_cross: 'SELL',
  kdj_oversold: 'BUY', kdj_overbought: 'REDUCE',
  rsi_oversold: 'BUY', rsi_overbought: 'REDUCE',
  volume_breakout: 'ADD', price_drop: 'SELL',
  stop_loss: 'SELL', high_volatility: 'REDUCE',
  ma_golden_cross: 'ADD', ma_death_cross: 'SELL',
  bollinger_lower_bounce: 'BUY', bollinger_upper_reversal: 'REDUCE',
  breakout_high: 'ADD', breakdown_low: 'SELL'
}
const getActionSignal = (ruleName) => RULE_ACTION_MAP[ruleName] || ''
const formatTime = (t) => { if (!t) return '-'; try { return new Date(t).toLocaleString('zh-CN') } catch { return t } }

onMounted(async () => {
  fetchRules()
  // 先从 localStorage 恢复当天预警（无需重新请求）
  _loadAlertsFromStorage()
  // 无论是否有缓存，都后台静默刷新一次（不阻塞 UI）
  monitorClicked.value = true
  runAutoMonitorCycle().catch(() => {})
  // 恢复自动监控状态
  if (autoMonitor.value) {
    monitorTimer = setInterval(runAutoMonitorCycle, 60000)
  }
  // 如果之前开启过通知权限，自动启用
  if (notifyEnabled.value && 'Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission()
  }
})

onUnmounted(() => {
  clearInterval(monitorTimer)
  window.removeEventListener('resize', resizeHandler)
})
</script>

<style scoped>
.smart-alert {
  position: absolute; top: 0; left: 0; right: 0; bottom: 0;
  padding: 12px; background: #f0f2f5;
  display: flex; flex-direction: column; min-height: 0; overflow: hidden;
}
.page-header-fixed {
  flex-shrink: 0; padding: 8px 12px; background: #fff;
  border-radius: 6px; margin-bottom: 8px;
  display: flex; align-items: center; gap: 8px;
}
.page-title { margin: 0; font-size: 16px; display: flex; align-items: center; gap: 6px; color: #303133; }
.header-right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.content-scroll-area {
  flex: 1; min-height: 0;
  display: flex; flex-direction: column; overflow: hidden;
}
.main-tabs { flex: 1; display: flex !important; flex-direction: column !important; min-height: 0; overflow: hidden; }
.main-tabs :deep(.el-tabs__header) { flex-shrink: 0; }
.main-tabs :deep(.el-tabs__content) {
  flex: 1; display: flex !important; flex-direction: column !important;
  overflow: hidden !important; min-height: 0; padding: 0 !important;
}
.main-tabs :deep(.el-tabs__content > .el-tab-pane) { display: none; }
.main-tabs :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) {
  display: flex !important; flex-direction: column !important;
  flex: 1; min-height: 0; overflow: hidden;
}
.tab-pane-content {
  display: flex; flex-direction: column; flex: 1; min-height: 0;
  overflow: hidden; padding: 8px 4px; gap: 12px;
}

/* ===== 仪表盘统计卡片 ===== */
.dashboard-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; flex-shrink: 0; }
.dash-stat-card {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px; border-radius: 8px; color: #fff;
}
.dash-stat-icon { opacity: 0.85; flex-shrink: 0; }
.dash-stat-body { flex: 1; min-width: 0; }
.dash-stat-value { font-size: 22px; font-weight: 700; line-height: 1.2; }
.dash-stat-label { font-size: 11px; opacity: 0.85; margin-top: 2px; }

/* ===== 来源监控卡片（紧凑一行显示） ===== */
.dash-sources { display: flex; gap: 8px; flex-shrink: 0; overflow-x: auto; padding-bottom: 2px; scrollbar-width: none; }
.dash-sources::-webkit-scrollbar { display: none; }
.dash-source-card {
  background: #fff; border-radius: 8px; padding: 10px 12px; min-width: 140px; flex-shrink: 0;
  border: 1px solid #ebeef5; transition: box-shadow 0.2s; display: flex; flex-direction: column; gap: 6px;
}
.dash-source-card.source-active { border-color: #e6a23c; background: #fffbf0; }
.dash-source-card.source-filtered { border-color: #409EFF; background: #ecf5ff; box-shadow: 0 0 0 2px rgba(64,158,255,0.25); }
.dash-source-top { display: flex; align-items: center; gap: 8px; margin-bottom: 0; }
.dash-source-icon {
  width: 30px; height: 30px; border-radius: 6px;
  display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0;
}
.dash-source-info { flex: 1; min-width: 0; }
.dash-source-name { font-size: 13px; font-weight: 600; color: #303133; display: block; }
.dash-source-count { font-size: 10px; color: #909399; }
.dash-source-actions { display: flex; align-items: center; gap: 6px; justify-content: flex-end; }

/* ===== 最新预警列表 ===== */
.dash-alerts { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.dash-alerts-header {
  display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #303133;
  padding: 6px 0; flex-shrink: 0;
}
.dash-alerts-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; padding: 2px 0; }
.dash-alerts-pager { display: flex; justify-content: center; padding: 8px 0 0; flex-shrink: 0; }
.dash-alert-item {
  display: flex; gap: 10px; padding: 10px 14px; border-radius: 6px;
  background: #fff; border-left: 3px solid #ebeef5;
}
.da-left { display: flex; align-items: flex-start; padding-top: 3px; }
.da-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dad-info { background: #409eff; } .dad-warning { background: #e6a23c; }
.dad-critical { background: #f56c6c; } .dad-emergency { background: #9b59b6; }
.da-body { flex: 1; min-width: 0; }
.da-row1 { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; flex-wrap: wrap; row-gap: 4px; }
.da-stock { font-weight: 600; font-size: 13px; color: #303133; }
.da-source-tag { font-size: 10px; color: #909399; background: #f0f2f5; padding: 0 5px; border-radius: 3px; }
.da-level { flex-shrink: 0; }
.da-action { flex-shrink: 0; font-weight: 600; }
.da-row2 { display: flex; align-items: center; gap: 6px; margin-bottom: 2px; }
.da-type { font-size: 11px; color: #909399; white-space: nowrap; }
.da-msg { font-size: 12px; color: #606266; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.da-row3 { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #67c23a; margin-bottom: 2px; }
.da-time { font-size: 10px; color: #c0c4cc; }

/* ===== 分组展示样式 ===== */
.dash-alert-group {
  border-radius: 8px; margin-bottom: 8px;
  border: 1px solid #dcdfe6; background: #fff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06); transition: box-shadow 0.2s;
  flex-shrink: 0; min-height: 52px;
}
.dash-alert-group:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.da-group-header {
  display: flex; gap: 10px; padding: 14px 16px; cursor: pointer;
  background: linear-gradient(135deg, #fafbfc 0%, #fff 100%);
  transition: all 0.2s; user-select: none; border-bottom: 1px solid transparent;
  min-height: 50px; align-items: flex-start;
}
.da-group-header:hover { background: #f5f7fa; }
.dash-alert-group.has-expanded .da-group-header { border-bottom-color: #ebeef5; }
.da-code { font-weight: 400; font-size: 11px; color: #909399; margin-left: 4px; }
.da-preview {
  margin-top: 6px; padding-top: 6px; border-top: 1px solid #f0f2f5;
  display: flex; align-items: center; gap: 6px; min-height: 0;
}
.da-preview .da-type { font-size: 11px; color: #909399; white-space: nowrap; flex-shrink: 0; }
.da-preview .da-msg {
  font-size: 12px; color: #606266; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  min-width: 0; line-height: 1.4;
}
.da-consolidated { font-weight: 700 !important; border: 1px dashed rgba(0,0,0,0.15); padding: 0 8px !important; }
.da-consolidated.is-conflict { background: linear-gradient(135deg, #f56c6c 50%, #e6a23c 50%) !important; color: #fff !important; border: none !important; animation: conflictPulse 2s ease-in-out infinite; }
@keyframes conflictPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.85; } }
.da-expand-icon { margin-left: auto; color: #c0c4cc; transition: all 0.3s; flex-shrink: 0; font-size: 14px; }
.dash-alert-group.has-expanded .da-expand-icon { transform: rotate(180deg); }
.da-group-details {
  background: #fafbfc; border-top: 1px solid #ebeef5;
  display: flex; flex-direction: column; padding: 10px 14px; gap: 8px;
  max-height: 600px; overflow-y: auto;
}
.da-sub-item {
  background: #fff !important; border: 1px solid #f0f2f5 !important; border-radius: 6px !important;
  margin-bottom: 0 !important; padding: 12px 14px !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}
.da-sub-item .da-body { overflow: visible !important; min-width: 0 !important; flex-shrink: 1 !important; }
.da-sub-item .da-row1 { flex-wrap: wrap !important; gap: 4px !important; }
.da-sub-item .da-row2 { display: block !important; margin-bottom: 4px !important; }
.da-sub-item .da-type { white-space: normal !important; display: block !important; margin-bottom: 2px !important; font-size: 10px !important; color: #909399 !important; }
.da-sub-item .da-msg { 
  white-space: normal !important; word-break: break-word !important; line-height: 1.6 !important;
  overflow: visible !important; text-overflow: unset !important; display: block !important;
  font-size: 12px !important; color: #606266 !important; max-width: 100% !important;
}

/* ===== 自设监控tab ===== */
.custom-add-section { display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; }
.custom-add-row { display: flex; align-items: center; gap: 8px; }
.custom-stock-list {
  display: flex; flex-wrap: wrap; gap: 6px; max-height: 200px; overflow-y: auto;
  padding: 8px; background: #fff; border-radius: 6px; border: 1px solid #ebeef5;
}
.custom-stock-item {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 8px; background: #f5f7fa; border-radius: 4px; font-size: 12px;
}
.csi-code { font-weight: 600; color: #303133; }
.csi-name { color: #909399; }

/* ===== 通用 ===== */
.flex-shrink-0 { flex-shrink: 0; }

.table-scroll-wrapper {
  flex: 1;
  min-height: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Mobile */
@media (max-width: 768px) {
  .smart-alert { position: absolute; top: 0; left: 0; right: 0; bottom: 0; padding: 6px 8px; overflow: hidden; }
  
  /* 移动端头部优化 */
  .page-header-fixed.mobile-header { 
    padding: 6px 10px; flex-wrap: wrap; gap: 4px; border-radius: 12px; background: #fff; margin-bottom: 6px; box-shadow: 0 1px 4px rgba(0,0,0,0.04); 
  }
  .page-title { font-size: 14px; }
  
  .header-right.mobile-header-actions { 
    gap: 4px; flex-wrap: wrap; align-items: center; 
  }
  .header-right :deep(.el-switch__label) { font-size: 12px !important; }
  .rules-tag { display: none !important; }
  
  /* 移动端按钮样式 */
  .mob-monitor-tag { min-height: 24px; padding: 0 8px; font-weight: 500; }
  .mob-notify-btn { padding: 4px 6px; font-size: 12px; height: auto !important; min-height: 24px; }
  .mob-refresh-btn { padding: 4px 6px; font-size: 12px; height: auto !important; min-height: 24px; }
  
  /* Tab内容区域 - flex布局填充剩余空间，只有预警列表内部滚动 */
  .tab-pane-content { 
    padding: 4px 2px; gap: 8px; overflow: hidden !important;
    flex: 1 !important; min-height: 0 !important; display: flex !important; flex-direction: column !important;
  }
  
  /* 统计卡片和来源监控固定不收缩 */
  .dashboard-stats.mob-hscroll { flex-shrink: 0 !important;
    display: flex !important; overflow-x: auto; scroll-snap-type: x mandatory; gap: 6px; padding-bottom: 4px; 
    scrollbar-width: none; 
  }
  .dashboard-stats.mob-hscroll::-webkit-scrollbar { display: none; }
  .dashboard-stats.mob-hscroll > * { flex-shrink: 0; width: calc(50% - 3px); scroll-snap-align: start; }
  
  /* 确保深色背景卡片上的文字清晰可见 */
  .dash-stat-card { 
    padding: 8px 6px; border-radius: 10px; gap: 6px; min-height: 48px; color: #fff !important; 
  }
  .dash-stat-card * { color: #fff !important; }
  .dash-stat-icon :deep(.el-icon) { width: 24px !important; height: 24px !important; color: #fff !important; }
  .dash-stat-value { font-size: 15px; font-weight: 700; line-height: 1.2; color: #fff !important; }
  .dash-stat-label { font-size: 9px; margin-top: 1px; color: rgba(255,255,255,0.9) !important; }
  
  /* 来源监控卡片 - 移动端横向滚动，一行显示所有 */
  .dash-sources.mob-grid { flex-shrink: 0 !important; gap: 6px !important; padding-bottom: 2px; }
  
  .dash-source-card.mob-compact { 
    padding: 6px 8px !important; border-radius: 8px; min-width: 110px !important; flex-shrink: 0 !important; min-height: auto !important; gap: 4px !important;
  }
  .dash-source-card.mob-compact .dash-source-top { margin-bottom: 0 !important; gap: 5px !important; }
  .dash-source-card.mob-compact .dash-source-icon { width: 22px !important; height: 22px !important; border-radius: 4px; }
  .dash-source-card.mob-compact .dash-source-name { font-size: 11px; }
  .dash-source-card.mob-compact .dash-source-count { display: none; }
  .dash-source-card.mob-compact :deep(.el-tag) { min-height: 16px !important; padding: 0 3px !important; font-size: 9px !important; line-height: 16px !important; }
  
  .mob-scan-btn { 
    padding: 2px 6px !important; height: auto !important; min-height: 20px; font-size: 11px; line-height: 1.4; 
  }
  .dash-source-actions { gap: 3px; justify-content: flex-end; }
  
  /* 预警列表 - 外层固定，内层滚动（含分页器） */
  .dash-alerts.mob-card-list { 
    background: #fff; border-radius: 12px; padding: 8px; box-shadow: 0 1px 4px rgba(0,0,0,0.04); margin-top: 4px; 
    flex: 1 !important; min-height: 0 !important; display: flex !important; flex-direction: column !important; overflow: hidden !important;
  }
  .dash-alerts-header { flex-shrink: 0 !important; padding: 6px 4px; font-size: 12px; border-bottom: 1px solid var(--m-border, #e0e4ea); margin-bottom: 6px; }
  .dash-alerts-list { 
    flex: 1 !important; min-height: 0 !important; overflow-y: auto !important; -webkit-overflow-scrolling: touch;
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px);
  }
  
  .dash-alert-item { 
    padding: 10px 8px; border-radius: 8px; background: #f9fafb; margin-bottom: 6px; min-height: 56px; 
    border-left: none !important; border: 1px solid var(--m-border, #e0e4ea);
    overflow: hidden;
  }
  .dash-alert-item:last-child { margin-bottom: 0; }
  
  .da-stock { font-size: 12px; }
  .da-msg { font-size: 11px; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; word-break: break-all; line-height: 1.4; }
  .da-time { font-size: 9px; }

  /* 移动端分组样式 */
  .dash-alert-group { border-radius: 10px; margin-bottom: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08) !important; flex-shrink: 0; min-height: 52px; }
  .da-group-header { padding: 14px 12px; gap: 8px; min-height: 50px; align-items: flex-start; }
  .da-stock { font-size: 13px !important; }
  .da-code { font-size: 10px !important; }
  .da-consolidated { font-size: 10px !important; padding: 0 6px !important; }
  .da-level { font-size: 10px !important; }
  .da-expand-icon { font-size: 12px !important; }
  .da-group-details { padding: 10px 8px; gap: 8px; max-height: 400px !important; }
  .da-sub-item { padding: 10px 8px !important; border-radius: 8px !important; margin-bottom: 0 !important; }
  .da-sub-item .da-source-tag { font-size: 9px !important; }
  .da-sub-item .da-action { font-size: 9px !important; }
  .da-sub-item .da-type { 
    font-size: 10px !important; white-space: normal !important; display: block !important; 
    margin-bottom: 2px !important; color: #909399 !important;
  }
  .da-sub-item .da-msg { 
    font-size: 11px !important; white-space: normal !important; line-height: 1.6 !important; 
    display: block !important; overflow: visible !important; text-overflow: unset !important;
    word-break: break-word !important; max-width: 100% !important; color: #606266 !important;
  }
  .da-sub-item .da-row1 { flex-wrap: wrap !important; gap: 4px !important; }
  .da-sub-item .da-row2 { display: block !important; margin-bottom: 4px !important; }
  .da-sub-item .da-body { overflow: visible !important; min-width: 0 !important; flex-shrink: 1 !important; }
  .da-sub-item .da-row3 { font-size: 10px !important; }
  .da-preview { margin-top: 4px; padding-top: 4px; gap: 4px; display: flex; align-items: center; }
  .da-preview .da-type { font-size: 10px !important; white-space: nowrap; color: #909399; flex-shrink: 0; }
  .da-preview .da-msg { font-size: 11px !important; color: #909399; line-height: 1.4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .da-sub-item .da-time { font-size: 9px !important; }
  
  /* 自设监控Tab */
  .custom-add-row { flex-direction: column; align-items: stretch; }
  .data-table :deep(.el-table__cell) { padding: 6px 4px !important; font-size: 12px; }
  .table-scroll-wrapper { overflow: visible; height: auto; flex: none; min-height: 0; }
  .table-scroll-wrapper :deep(.el-table) { height: auto !important; max-height: none !important; }
  
  /* 分页器 */
  :deep(.el-pagination) { font-size: 12px; flex-wrap: wrap; justify-content: center; }
  :deep(.el-empty__description p) { font-size: 13px; }
  
  /* ── Tabs horizontal scroll ── */
  :deep(.el-tabs__header) { margin-bottom: 4px; overflow-x: auto; scrollbar-width: none; }
  :deep(.el-tabs__header::-webkit-scrollbar) { display: none; }
  :deep(.el-tabs__nav) { display: flex; }
  :deep(.el-tabs__item) { font-size: 12px; padding: 0 10px; height: 34px; line-height: 34px; }
  
  /* ── Cards border-radius ── */
  :deep(.el-card) { border-radius: 14px !important; box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important; margin-bottom: 8px; }
  :deep(.el-card__body) { padding: 12px 14px !important; }
}

@media (max-width: 480px) {
  .smart-alert { padding: 4px; }
  .page-header-fixed.mobile-header { padding: 4px 8px; }
  .page-title { font-size: 13px; }
  
  /* 极小屏幕统计卡片 */
  .dashboard-stats.mob-hscroll > * { width: calc(50% - 3px); }
  .dash-stat-card { padding: 6px 4px; min-height: 42px; }
  .dash-stat-value { font-size: 14px; }
  
  /* 极小屏幕来源卡片 */
  .dash-source-card.mob-compact { padding: 6px; min-height: 52px; }
}
</style>
