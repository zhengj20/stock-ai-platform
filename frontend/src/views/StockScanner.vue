<template>
  <div class="stock-scanner">
    <h2 class="page-title">
      <el-icon><Aim /></el-icon>
      算法选股
      <el-button size="small" type="primary" plain class="decision-link" @click="$router.push('/decision')">
        <el-icon><Compass /></el-icon> 决策中心
      </el-button>
    </h2>

    <!-- 筛选条件卡片 -->
    <el-card shadow="hover" class="filter-card">
      <div class="filter-row">
        <div class="filter-item filter-algo">
          <label class="filter-label">选择算法</label>
          <el-select v-model="selectedAlgo" placeholder="选择算法类型" :size="inputSize" clearable style="width: 100%">
            <el-option label="神奇电波 (MACD+RSI复合)" value="magic_wave" />
            <el-option label="TD序列 (趋势反转)" value="td_sequential" />
            <el-option label="通道突破 (Donchian Channel)" value="channel_breakout" />
            <el-option label="异动拉升 (放量/突变)" value="anomaly_detect" />
            <el-option label="底部寻机 (超跌反弹)" value="bottom_opportunity" />
            <el-option label="均线雷达 (多周期排列)" value="ma_radar" />
            <el-option label="趋势强度 (ADX评分)" value="trend_strength" />
          </el-select>
        </div>

        <div class="filter-item filter-signal">
          <label class="filter-label">信号方向</label>
          <el-select v-model="selectedSignal" placeholder="信号方向" :size="inputSize" style="width: 100%">
            <el-option label="买入信号" value="buy" />
            <el-option label="卖出信号" value="sell" />
          </el-select>
        </div>

        <div class="filter-item filter-count">
          <label class="filter-label">返回数量</label>
          <el-input-number v-model="topN" :min="5" :max="100" :step="5" :size="inputSize" />
        </div>

        <div class="filter-item filter-action">
          <el-button type="primary" @click="runScan" :loading="scanning" :disabled="!selectedAlgo" style="width: 100%">
            <el-icon><Search /></el-icon> {{ scanning ? '扫描中...' : '开始扫描' }}
          </el-button>
        </div>
      </div>

      <!-- 快捷策略（桌面端显示） -->
      <div class="quick-strategies" v-if="!isMobile">
        <span class="label">快捷策略:</span>
        <el-tag v-for="strategy in quickStrategies" :key="strategy.name" class="qtag" @click="applyStrategy(strategy)" effect="plain" size="small">
          {{ strategy.name }}
        </el-tag>
      </div>
    </el-card>

    <!-- 扫描结果 -->
    <template v-if="scanResults && scanResults.stocks?.length > 0">
      <div class="result-header">
        <span class="total-label">找到 {{ scanResults.total_found }} 只符合条件的股票</span>
        <div class="result-actions" v-if="!isMobile">
          <el-button size="small" @click="viewAllInDecision">
            <el-icon><Compass /></el-icon> 综合分析
          </el-button>
          <el-button size="small" @click="exportCSV">
            <el-icon><Download /></el-icon> 导出CSV
          </el-button>
          <el-button size="small" @click="exportExcel">
            <el-icon><Document /></el-icon> 导出Excel
          </el-button>
          <el-button size="small" @click="shareResults">
            <el-icon><Share /></el-icon> 分享
          </el-button>
        </div>
      </div>

      <!-- 结果列表 -->
      <div class="results-grid">
        <div v-for="(stock, idx) in scanResults.stocks" :key="stock.code" class="result-card" :class="'rank-' + (idx + 1)">
          <div class="card-rank">{{ idx + 1 }}</div>
          <div class="card-content">
            <div class="stock-header">
              <span class="stock-name">{{ stock.name || stock.code }}</span>
              <span class="stock-code">{{ stock.code }}</span>
            </div>

            <!-- 行情数据 -->
            <div class="stock-quote">
              <span class="price">{{ stock.close?.toFixed(2) ?? '--' }}</span>
              <span class="change" :class="stock.change_pct >= 0 ? 'up' : 'down'">
                {{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct ?? '--' }}%
              </span>
            </div>

            <div class="stock-meta">
              <span v-if="stock.change_5d_pct != null" class="meta-item">
                5日 <span :class="stock.change_5d_pct >= 0 ? 'up' : 'down'">{{ stock.change_5d_pct >= 0 ? '+' : '' }}{{ stock.change_5d_pct }}%</span>
              </span>
              <span v-if="stock.change_20d_pct != null" class="meta-item">
                20日 <span :class="stock.change_20d_pct >= 0 ? 'up' : 'down'">{{ stock.change_20d_pct >= 0 ? '+' : '' }}{{ stock.change_20d_pct }}%</span>
              </span>
              <span v-if="stock.volume_ratio" class="meta-item">
                量比 {{ stock.volume_ratio }}
              </span>
            </div>

            <div class="signal-indicator" :class="'sig-' + stock.signal">
              {{ signalTextMap[stock.signal] || '中性' }}
            </div>

            <div class="score-bar">
              <div class="bar-bg">
                <div class="bar-fill" :style="{ width: Math.round(stock.score) + '%', background: scoreGradient(stock.score) }"></div>
              </div>
              <span class="score-val">{{ Math.round(stock.score) }}</span>
            </div>

            <!-- 算法详情摘要 -->
            <div class="algo-summary">
              <template v-if="selectedAlgo === 'magic_wave' && stock.algo_result">
                <span class="tag" :class="'wave-' + stock.algo_result.wave">{{ waveTextMap[stock.algo_result.wave] }}</span>
                <span class="tag strength">{{ strengthTextMap[stock.algo_result.strength] }}</span>
              </template>
              <template v-else-if="selectedAlgo === 'anomaly_detect' && stock.algo_result">
                <span class="tag" v-if="stock.algo_result.anomaly_type">{{ anomalyTypeTextMap[stock.algo_result.anomaly_type] }}</span>
                <span class="tag">量比{{ stock.algo_result.volume_ratio ?? '--' }}</span>
              </template>
              <template v-else-if="selectedAlgo === 'bottom_opportunity' && stock.algo_result">
                <span class="tag" v-for="s in stock.algo_result.signals || []" :key="s">{{ bottomSignalTextMap[s] || s }}</span>
              </template>
            </div>

            <div class="card-actions">
              <el-button size="small" @click="openDiagnosis(stock.code, stock.name)">
                <el-icon><DataLine /></el-icon> 诊断
              </el-button>
              <el-button size="small" @click="openAnalysis(stock.code, stock.name)">
                <el-icon><Compass /></el-icon> 分析
              </el-button>
              <el-button size="small" type="primary" plain @click="addToWatchlist(stock.code)">
                <el-icon><Star /></el-icon> 自选
              </el-button>
              <el-button size="small" type="success" plain @click="openBacktest(stock.code, stock.name)">
                <el-icon><Timer /></el-icon> 回测
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 历史记录 -->
    <el-card v-if="scanHistory.length > 0" shadow="never" class="history-card">
      <template #header>
        <div class="history-header">
          <span><el-icon><Clock /></el-icon> 扫描历史</span>
          <el-button size="small" text @click="scanHistory = []">清空</el-button>
        </div>
      </template>
      <div class="history-list">
        <div v-for="record in scanHistory.slice(0, 10)" :key="record.id" class="history-item" @click="applyHistory(record)">
          <span class="history-time">{{ record.timestamp }}</span>
          <span class="history-algo">{{ algoTextMap[record.algo] || record.algo }}</span>
          <span class="history-signal">{{ record.signal_filter === 'buy' ? '买入' : '卖出' }}</span>
          <span class="history-count">找到{{ record.total_found }}只</span>
          <span class="history-stocks">{{ record.top_stocks?.map(s => s.name).join(', ') }}</span>
        </div>
      </div>
    </el-card>

    <!-- 空状态/加载中 -->
    <el-card v-if="scanning" shadow="never" class="empty-card">
      <div class="scanning-progress">
        <el-progress :percentage="scanProgress" :status="scanProgress === 100 ? 'success' : ''" />
        <p class="progress-text">{{ scanProgressText }}</p>
      </div>
      <el-skeleton :rows="8" animated />
    </el-card>

    <el-empty v-if="!scanning && scanResults?.stocks?.length === 0 && hasScanned" description="未找到符合条件的股票，请调整筛选条件" />

    <el-empty v-if="!scanning && !hasScanned" description="选择算法并点击扫描开始选股" />

    <!-- 诊断抽屉 -->
    <StockDiagnosisDrawer v-model="diagnosisDrawerVisible" :stock-code="currentStockCode" />

    <!-- 分析信号抽屉 -->
    <DecisionSignalsDrawer v-model="analysisDrawerVisible" :stock-code="currentStockCode" :stock-name="currentStockName" />

    <!-- 回测抽屉 -->
    <BacktestDrawer v-model="backtestDrawerVisible" :stock-code="currentStockCode" :stock-name="currentStockName" />

    <!-- 分享对话框 -->
    <el-dialog v-model="shareDialogVisible" title="分享选股结果" width="500px">
      <div class="share-content">
        <div class="share-report">
          <h3>算法选股报告</h3>
          <p>算法: {{ algoTextMap[scanResults?.algo] || scanResults?.algo }}</p>
          <p>信号: {{ scanResults?.signal_filter === 'buy' ? '买入' : '卖出' }}</p>
          <p>时间: {{ new Date().toLocaleString() }}</p>
          <div class="share-stocks">
            <div v-for="(stock, idx) in (scanResults?.stocks || []).slice(0, 5)" :key="stock.code" class="share-stock-item">
              <span>{{ idx + 1 }}. {{ stock.name }} ({{ stock.code }})</span>
              <span :class="stock.change_pct >= 0 ? 'up' : 'down'">{{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct }}%</span>
              <span>评分: {{ stock.score }}</span>
            </div>
          </div>
        </div>
        <div class="share-actions">
          <el-button @click="copyShareText">
            <el-icon><CopyDocument /></el-icon> 复制文本
          </el-button>
          <el-button @click="generateReportImage">
            <el-icon><Picture /></el-icon> 生成图片
          </el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api, { stockApi, backtestApi } from '@/api'
import StockDiagnosisDrawer from './components/StockDiagnosisDrawer.vue'
import DecisionSignalsDrawer from './components/DecisionSignalsDrawer.vue'
import BacktestDrawer from './components/BacktestDrawer.vue'
import { ElMessage } from 'element-plus'

const selectedAlgo = ref('')
const selectedSignal = ref('buy')
const topN = ref(20)
const scanning = ref(false)
const scanResults = ref(null)
const hasScanned = ref(false)
const isMobile = ref(window.innerWidth <= 768)
const inputSize = computed(() => (isMobile.value ? 'small' : 'default'))

// 扫描进度
const scanProgress = ref(0)
const scanProgressText = ref('正在准备扫描...')

// 历史记录
const scanHistory = ref([])

// 抽屉弹窗相关
const diagnosisDrawerVisible = ref(false)
const analysisDrawerVisible = ref(false)
const backtestDrawerVisible = ref(false)
const currentStockCode = ref('')
const currentStockName = ref('')

// 分享相关
const shareDialogVisible = ref(false)

function checkMobile() {
  isMobile.value = window.innerWidth <= 768
}

onMounted(() => {
  window.addEventListener('resize', checkMobile)
  // 从localStorage加载历史记录
  const saved = localStorage.getItem('scan_history')
  if (saved) {
    try { scanHistory.value = JSON.parse(saved) } catch {}
  }
})
onUnmounted(() => window.removeEventListener('resize', checkMobile))

// 文本映射
const signalTextMap = {
  buy: '买入',
  sell: '卖出',
  neutral: '中性',
}

const waveTextMap = {
  red: '红波(多)',
  green: '绿波(空)',
  neutral: '中性',
}

const strengthTextMap = {
  strong: '强',
  medium: '中',
  weak: '弱',
  none: '--',
}

const anomalyTypeTextMap = {
  volume_surge: '放量拉升',
  continuous_rise: '连续上涨',
  high_amplitude: '大振幅高位',
}

const bottomSignalTextMap = {
  rsi_oversold: 'RSI超卖',
  rsi_low: 'RSI偏低',
  shrinking_volume: '缩量企稳',
  deep_drop: '大幅下跌',
  moderate_drop: '温和回调',
  price_stabilizing: '价格企稳',
  macd_divergence: 'MACD底背离',
}

const algoTextMap = {
  magic_wave: '神奇电波',
  td_sequential: 'TD序列',
  channel_breakout: '通道突破',
  anomaly_detect: '异动拉升',
  bottom_opportunity: '底部寻机',
  ma_radar: '均线雷达',
  trend_strength: '趋势强度',
}

// 快捷策略（增加signal字段）
const quickStrategies = [
  { name: '红波强势股', algo: 'magic_wave', signal: 'buy' },
  { name: '底部超跌反弹', algo: 'bottom_opportunity', signal: 'buy' },
  { name: '放量异动拉升', algo: 'anomaly_detect', signal: 'buy' },
  { name: '通道突破买入', algo: 'channel_breakout', signal: 'buy' },
  { name: 'TD序列反转', algo: 'td_sequential', signal: 'buy' },
  { name: '空头趋势卖出', algo: 'ma_radar', signal: 'sell' },
  { name: '强趋势做空', algo: 'trend_strength', signal: 'sell' },
]

function applyStrategy(strategy) {
  selectedAlgo.value = strategy.algo
  selectedSignal.value = strategy.signal || 'buy'
}

// 执行扫描（带进度）
async function runScan() {
  if (!selectedAlgo.value) {
    ElMessage.warning('请选择算法类型')
    return
  }

  scanning.value = true
  scanResults.value = null
  hasScanned.value = false
  scanProgress.value = 0
  scanProgressText.value = '正在准备扫描...'

  // 模拟进度
  const progressTimer = setInterval(() => {
    if (scanProgress.value < 90) {
      scanProgress.value += 5
      if (scanProgress.value >= 20) scanProgressText.value = '正在获取全市场股票...'
      if (scanProgress.value >= 40) scanProgressText.value = '正在获取K线数据...'
      if (scanProgress.value >= 60) scanProgressText.value = '正在运行算法分析...'
      if (scanProgress.value >= 80) scanProgressText.value = '正在排序筛选...'
    }
  }, 300)

  try {
    const res = await api.get('/decision/scan', {
      params: {
        algo: selectedAlgo.value,
        signal: selectedSignal.value,
        top_n: topN.value,
      },
    })

    if (res.status === 'error') {
      throw new Error(res.message || '扫描失败')
    }

    scanResults.value = res
    hasScanned.value = true
    scanProgress.value = 100
    scanProgressText.value = '扫描完成'

    // 保存历史记录
    const historyRecord = {
      id: Date.now(),
      algo: selectedAlgo.value,
      signal_filter: selectedSignal.value,
      timestamp: new Date().toLocaleString(),
      total_found: res.total_found,
      top_stocks: (res.stocks || []).slice(0, 5).map(s => ({ code: s.code, name: s.name, score: s.score })),
    }
    scanHistory.value.unshift(historyRecord)
    if (scanHistory.value.length > 20) scanHistory.value.pop()
    localStorage.setItem('scan_history', JSON.stringify(scanHistory.value))

    if (!res.stocks?.length) {
      ElMessage.info('未找到符合条件的股票，请调整筛选条件')
    }
  } catch (e) {
    ElMessage.error(e.message || '扫描失败，请稍后重试')
    console.error('选股扫描失败:', e)
  } finally {
    clearInterval(progressTimer)
    scanning.value = false
  }
}

// 打开诊断抽屉
function openDiagnosis(code, name) {
  currentStockCode.value = code
  currentStockName.value = name || ''
  diagnosisDrawerVisible.value = true
}

// 打开分析抽屉
function openAnalysis(code, name) {
  currentStockCode.value = code
  currentStockName.value = name || ''
  analysisDrawerVisible.value = true
}

// 打开回测抽屉
function openBacktest(code, name) {
  currentStockCode.value = code
  currentStockName.value = name || ''
  backtestDrawerVisible.value = true
}

// 综合分析全部结果（打开第一只股票的分析）
function viewAllInDecision() {
  if (scanResults.value?.stocks?.length) {
    const firstStock = scanResults.value.stocks[0]
    openAnalysis(firstStock.code, firstStock.name)
  }
}

// 加入自选股
async function addToWatchlist(code) {
  try {
    await api.post('/watchlist/add', { stock_code: code })
    ElMessage.success('已加入自选股')
  } catch (e) {
    if (e.response?.status !== 409) {
      ElMessage.error(e.message || '添加失败')
    } else {
      ElMessage.info('已在自选股中')
    }
  }
}

// 分享
function shareResults() {
  shareDialogVisible.value = true
}

function copyShareText() {
  if (!scanResults.value) return
  const text = `算法选股报告\n算法: ${algoTextMap[scanResults.value.algo]}\n信号: ${scanResults.value.signal_filter === 'buy' ? '买入' : '卖出'}\n时间: ${new Date().toLocaleString()}\n\n${(scanResults.value.stocks || []).slice(0, 5).map((s, i) => `${i+1}. ${s.name} (${s.code}) ${s.change_pct >= 0 ? '+' : ''}${s.change_pct}% 评分:${s.score}`).join('\n')}`
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制到剪贴板')
  })
}

function generateReportImage() {
  ElMessage.info('图片生成功能开发中')
}

// 历史记录操作
function applyHistory(record) {
  selectedAlgo.value = record.algo
  selectedSignal.value = record.signal_filter
  runScan()
}

// 导出CSV
function exportCSV() {
  if (!scanResults.value?.stocks?.length) return

  const headers = ['排名', '代码', '名称', '最新价', '涨跌幅%', '5日涨跌%', '20日涨跌%', '量比', '信号', '分数']
  const rows = scanResults.value.stocks.map((s, i) => [
    i + 1,
    s.code,
    s.name || '',
    s.close ?? '',
    s.change_pct ?? '',
    s.change_5d_pct ?? '',
    s.change_20d_pct ?? '',
    s.volume_ratio ?? '',
    signalTextMap[s.signal] || '',
    s.score,
  ])

  const csvContent = [headers, ...rows].map(row => row.join(',')).join('\n')
  const blob = new Blob(['\uFEFF' + csvContent], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `选股结果_${selectedAlgo.value}_${new Date().toLocaleDateString()}.csv`
  link.click()
  ElMessage.success('CSV导出成功')
}

// 导出Excel（HTML表格格式，可被Excel直接打开）
function exportExcel() {
  if (!scanResults.value?.stocks?.length) return

  const headers = ['排名', '代码', '名称', '最新价', '涨跌幅%', '5日涨跌%', '20日涨跌%', '量比', '信号', '分数']
  const rows = scanResults.value.stocks.map((s, i) => [
    i + 1,
    s.code,
    s.name || '',
    s.close ?? '',
    s.change_pct ?? '',
    s.change_5d_pct ?? '',
    s.change_20d_pct ?? '',
    s.volume_ratio ?? '',
    signalTextMap[s.signal] || '',
    s.score,
  ])

  const html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40">
<head><meta charset="utf-8"><!--[if gte mso 9]><xml><x:ExcelWorkbook><x:ExcelWorksheets><x:ExcelWorksheet><x:Name>选股结果</x:Name></x:ExcelWorksheet></x:ExcelWorksheets></x:ExcelWorkbook></xml><![endif]--></head>
<body><table border="1"><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}</table></body></html>`
  
  const blob = new Blob(['\uFEFF' + html], { type: 'application/vnd.ms-excel;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `选股结果_${selectedAlgo.value}_${new Date().toLocaleDateString()}.xls`
  link.click()
  ElMessage.success('Excel导出成功')
}

// 分数渐变色
function scoreGradient(score) {
  if (score >= 70) return 'linear-gradient(90deg, #f56c6c, #ff8787)'
  if (score >= 40) return 'linear-gradient(90deg, #E6A23C, #F7CA18)'
  return 'linear-gradient(90deg, #67c23a, #85ce61)'
}
</script>

<style scoped>
.stock-scanner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 22px;
  margin-bottom: 16px;
  color: #303133;
}

.decision-link {
  margin-left: auto;
}

/* 筛选卡片 */
.filter-card {
  margin-bottom: 16px;
}

.filter-row {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.filter-item {
  min-width: 0;
}

.filter-algo {
  flex: 3;
}

.filter-signal {
  flex: 1.2;
}

.filter-count {
  flex: 0.8;
}

.filter-label {
  display: block;
  font-size: 13px;
  color: #909399;
  margin-bottom: 6px;
}

.filter-action {
  flex: 0 0 130px;
}

/* 快捷策略 */
.quick-strategies {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
  flex-wrap: wrap;
}

.quick-strategies .label {
  font-size: 13px;
  color: #909399;
}

.qtag {
  cursor: pointer;
  transition: all 0.2s;
}

.qtag:hover {
  transform: translateY(-1px);
}

/* 结果头部 */
.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 8px;
}

.total-label {
  font-size: 14px;
  color: #606266;
}

.result-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* 结果网格 */
.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.result-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  padding: 16px;
  display: flex;
  gap: 12px;
  transition: transform 0.2s, box-shadow 0.2s;
}

.result-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

/* 排名徽章 */
.card-rank {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #f0f2f5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 14px;
  color: #909399;
  flex-shrink: 0;
}

.rank-1 .card-rank { background: linear-gradient(135deg, #FFD700, #FFA500); color: #fff; }
.rank-2 .card-rank { background: linear-gradient(135deg, #C0C0C0, #A9A9A9); color: #fff; }
.rank-3 .card-rank { background: linear-gradient(135deg, #CD7F32, #B8860B); color: #fff; }

/* 卡片内容 */
.card-content {
  flex: 1;
}

.stock-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.stock-name {
  font-weight: bold;
  font-size: 16px;
}

.stock-code {
  font-size: 12px;
  color: #909399;
}

/* 行情数据 */
.stock-quote {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}

.stock-quote .price {
  font-size: 20px;
  font-weight: bold;
  color: #303133;
}

.stock-quote .change {
  font-size: 13px;
  font-weight: 600;
}

.stock-quote .change.up,
.stock-meta .up {
  color: #f56c6c;
}

.stock-quote .change.down,
.stock-meta .down {
  color: #67c23a;
}

.stock-meta {
  display: flex;
  gap: 10px;
  margin-bottom: 6px;
  font-size: 11px;
  color: #909399;
}

.meta-item .up { color: #f56c6c; font-weight: 600; }
.meta-item .down { color: #67c23a; font-weight: 600; }

/* 信号指示器 */
.signal-indicator {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: bold;
  margin-bottom: 8px;
}

.sig-buy { background: #fef0f0; color: #f56c6c; }
.sig-sell { background: #f0f9eb; color: #67c23a; }
.sig-neutral { background: #f4f4f5; color: #909399; }

/* 分数条 */
.score-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.bar-bg {
  flex: 1;
  height: 6px;
  background: #ebeef5;
  border-radius: 3px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.score-val {
  font-size: 14px;
  font-weight: bold;
  min-width: 30px;
  text-align: right;
}

/* 算法摘要标签 */
.algo-summary {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.tag {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  background: #f0f2f5;
  color: #606266;
}

.wave-red { background: #fef0f0; color: #f56c6c; }
.wave-green { background: #f0f9eb; color: #67c23a; }
.strength { background: #f4f4f5; color: #909399; }

/* 操作按钮 */
.card-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* 历史记录 */
.history-card {
  margin-top: 16px;
}

.history-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.history-list {
  max-height: 200px;
  overflow-y: auto;
}

.history-item {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid #ebeef5;
  cursor: pointer;
  font-size: 13px;
}

.history-item:hover {
  background: #f5f7fa;
}

.history-time {
  color: #909399;
  min-width: 140px;
}

.history-algo {
  font-weight: bold;
  min-width: 80px;
}

.history-signal {
  min-width: 40px;
}

.history-count {
  color: #606266;
  min-width: 60px;
}

.history-stocks {
  color: #909399;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 扫描进度 */
.scanning-progress {
  margin-bottom: 16px;
}

.progress-text {
  font-size: 13px;
  color: #909399;
  text-align: center;
  margin-top: 8px;
}

/* 分享内容 */
.share-content {
  padding: 16px 0;
}

.share-report {
  background: #f5f7fa;
  padding: 16px;
  border-radius: 8px;
  margin-bottom: 16px;
}

.share-report h3 {
  margin: 0 0 12px 0;
  font-size: 16px;
}

.share-report p {
  margin: 4px 0;
  font-size: 14px;
  color: #606266;
}

.share-stocks {
  margin-top: 12px;
}

.share-stock-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid #ebeef5;
  font-size: 13px;
}

.share-stock-item:last-child {
  border-bottom: none;
}

.share-actions {
  display: flex;
  justify-content: center;
  gap: 16px;
}

.up { color: #f56c6c; }
.down { color: #67c23a; }

/* 移动端适配 */
@media (max-width: 768px) {
  .stock-scanner {
    padding: 8px;
  }

  .page-title {
    font-size: 16px;
    margin-bottom: 10px;
    gap: 6px;
  }

  .decision-link {
    padding: 4px 8px;
    font-size: 12px;
  }

  .filter-card {
    margin-bottom: 10px;
  }

  .filter-row {
    gap: 8px;
    flex-wrap: wrap;
  }

  .filter-algo {
    flex: 1 1 calc(70% - 4px);
  }

  .filter-signal {
    flex: 1 1 calc(30% - 4px);
  }

  .filter-count {
    flex: 1 1 calc(40% - 4px);
    margin-top: 8px;
  }

  .filter-action {
    flex: 1 1 calc(60% - 4px);
    margin-top: 8px;
  }

  .filter-label {
    font-size: 11px;
    margin-bottom: 4px;
  }

  .result-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
    margin-bottom: 10px;
  }

  .total-label {
    font-size: 13px;
  }

  .result-actions {
    width: 100%;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .result-actions .el-button {
    flex: 1;
    min-width: calc(50% - 4px);
    font-size: 12px;
    padding: 6px 8px;
  }

  .results-grid {
    grid-template-columns: 1fr;
    gap: 8px;
  }

  .result-card {
    padding: 10px;
    border-radius: 8px;
  }

  .card-rank {
    width: 26px;
    height: 26px;
    font-size: 11px;
  }

  .stock-name {
    font-size: 13px;
  }

  .stock-code {
    font-size: 11px;
  }

  .stock-quote .price {
    font-size: 16px;
  }

  .stock-quote .change {
    font-size: 12px;
  }

  .stock-meta {
    font-size: 10px;
    gap: 6px;
  }

  .signal-indicator {
    font-size: 11px;
    padding: 1px 8px;
  }

  .score-val {
    font-size: 13px;
  }

  .card-actions {
    flex-wrap: nowrap;
    gap: 4px;
  }

  .card-actions .el-button {
    flex: 1;
    min-width: 0;
    font-size: 11px;
    padding: 6px 2px;
  }

  .card-actions .el-button :deep(.el-icon) {
    margin-right: 0;
  }

  .history-card {
    margin-top: 10px;
  }

  .history-item {
    flex-wrap: wrap;
    gap: 4px;
    font-size: 11px;
    padding: 6px 0;
  }

  .history-time {
    min-width: 100%;
    font-size: 10px;
  }

  .history-stocks {
    width: 100%;
  }
}
</style>
