<template>
  <div class="decision-center">
    <RefreshingIndicator :show="(signalsData && signalsData.refreshing) && !loading" />

    <h2 class="page-title">
      <el-icon><Compass /></el-icon>
      决策中心
      <el-button size="small" type="primary" plain class="scanner-link" @click="$router.push('/scanner')">
        <el-icon><Aim /></el-icon> 去选股
      </el-button>
    </h2>

    <!-- Tab切换：个股分析 / 自选股信号 -->
    <el-tabs v-model="activeTab" class="main-tabs">
      <el-tab-pane label="个股分析" name="stock">
        <!-- 股票搜索 -->
        <el-card shadow="hover" class="search-card">
          <el-autocomplete v-model="query" :fetch-suggestions="querySearch" :trigger-on-focus="false"
            placeholder="输入股票代码或名称查看算法信号"
            :size="inputSize" clearable :disabled="loading" value-key="name"
            @select="handleSuggestSelect">
            <template #prepend>股票</template>
            <template #append>
              <el-button class="analyze-btn" type="primary" @click="loadSignals" :disabled="loading">
                <el-icon><Aim /></el-icon> {{ loading ? '分析中...' : '分析' }}
              </el-button>
            </template>
          </el-autocomplete>
        </el-card>

        <!-- 分析进度条 -->
        <el-card v-if="loading && !signalsData" shadow="never" class="result-card">
          <div class="progress-container">
            <el-progress :percentage="loadProgress" :status="loadProgress === 100 ? 'success' : ''" />
            <p class="progress-text">{{ progressText }}</p>
          </div>
          <el-skeleton :rows="10" animated />
        </el-card>

        <!-- 错误状态 -->
        <el-card v-if="error" shadow="never" class="result-card">
          <div class="error-box">
            <el-icon :size="48" color="#E6A23C"><WarningFilled /></el-icon>
            <p>{{ error }}</p>
            <el-button type="primary" @click="loadSignals">重试</el-button>
          </div>
        </el-card>

        <!-- 信号总览 -->
        <template v-if="signalsData && !loading">
          <!-- 综合评分卡片 -->
          <div class="score-overview">
            <div class="score-ring" :style="{ background: scoreGradient }">
              <span class="score-val">{{ signalsData.composite_score ?? '--' }}</span>
              <span class="score-label">综合分</span>
            </div>
            <div class="score-info">
              <div class="signal-badge" :class="'sig-' + (signalsData.overall_signal || 'neutral')">
                {{ signalTextMap[signalsData.overall_signal] || '中性' }}
              </div>
              <div class="stock-name">{{ stockName }} ({{ query }})</div>
              <div class="signal-count">
                买入: <span class="c-red">{{ signalsData.buy_signal_count ?? 0 }}</span> /
                卖出: <span class="c-green">{{ signalsData.sell_signal_count ?? 0 }}</span> /
                中性: <span>{{ 7 - (signalsData.buy_signal_count ?? 0) - (signalsData.sell_signal_count ?? 0) }}</span>
              </div>
            </div>
          </div>

          <!-- 算法信号卡片网格 -->
          <div class="algo-grid">
            <!-- TD序列 -->
            <div class="algo-card" :class="'card-' + (tdSignal || 'neutral')">
              <div class="card-header">
                <el-icon><Coin /></el-icon>
                <span class="title">TD序列</span>
                <span class="badge" :class="'sig-' + tdSignal">{{ signalBadgeText(tdSignal) }}</span>
              </div>
              <div class="card-body">
                <template v-if="signalsData.signals?.td_sequential?.setup">
                  <div class="metric-row">
                    <span class="lbl">Setup</span>
                    <span class="val">{{ signalsData.signals.td_sequential.setup.type === 'buy' ? '买入' : '卖出' }} {{ signalsData.signals.td_sequential.setup.count }}/9</span>
                  </div>
                  <div class="metric-row" v-if="signalsData.signals.td_sequential.countdown">
                    <span class="lbl">Countdown</span>
                    <span class="val">{{ signalsData.signals.td_sequential.countdown.count }}/13</span>
                  </div>
                </template>
                <div class="metric-row" v-else>
                  <span class="lbl">进度</span>
                  <span class="val">买{{ signalsData.signals?.td_sequential?.buy_setup_progress ?? 0 }}/9 卖{{ signalsData.signals?.td_sequential?.sell_setup_progress ?? 0 }}/9</span>
                </div>
              </div>
            </div>

            <!-- 均线雷达 -->
            <div class="algo-card" :class="'card-' + maTrend">
              <div class="card-header">
                <el-icon><DataLine /></el-icon>
                <span class="title">均线雷达</span>
                <span class="badge" :class="'sig-' + maTrend">{{ trendTextMap[maTrend] || '震荡' }}</span>
              </div>
              <div class="card-body">
                <div class="metric-row">
                  <span class="lbl">趋势</span>
                  <span class="val" :class="'sig-' + maTrend">{{ trendTextMap[maTrend] || '未知' }}</span>
                </div>
                <div class="metric-row">
                  <span class="lbl">排列</span>
                  <span class="val">{{ alignmentTextMap[signalsData.signals?.ma_radar?.ma_alignment] || '混合' }}</span>
                </div>
                <div class="metric-row" v-if="signalsData.signals?.ma_radar?.divergence_pct !== undefined">
                  <span class="lbl">发散度</span>
                  <span class="val">{{ signalsData.signals.ma_radar.divergence_pct }}%</span>
                </div>
              </div>
            </div>

            <!-- 通道突破 -->
            <div class="algo-card" :class="'card-' + channelSignal">
              <div class="card-header">
                <el-icon><Expand /></el-icon>
                <span class="title">通道突破</span>
                <span class="badge" :class="'sig-' + channelSignal">{{ signalBadgeText(channelSignal) }}</span>
              </div>
              <div class="card-body">
                <template v-if="signalsData.signals?.channel_breakout?.breakout">
                  <div class="metric-row">
                    <span class="lbl">突破</span>
                    <span class="val" :class="channelSignal === 'buy' ? 'up' : 'down'">
                      {{ signalsData.signals.channel_breakout.breakout.type === 'upper' ? '上轨' : '下轨' }} ¥{{ signalsData.signals.channel_breakout.breakout.price }}
                    </span>
                  </div>
                </template>
                <div class="metric-row">
                  <span class="lbl">位置</span>
                  <span class="val">{{ signalsData.signals?.channel_breakout?.position_in_channel ?? '--' }}%</span>
                </div>
                <div class="metric-row">
                  <span class="lbl">通道宽</span>
                  <span class="val">{{ signalsData.signals?.channel_breakout?.channel_width_pct ?? '--' }}%</span>
                </div>
              </div>
            </div>

            <!-- 神奇电波 -->
            <div class="algo-card" :class="'card-' + waveSignal">
              <div class="card-header">
                <el-icon><Lightning /></el-icon>
                <span class="title">神奇电波</span>
                <span class="badge" :class="'sig-wave-' + (signalsData.signals?.magic_wave?.wave || 'neutral')">
                  {{ waveTextMap[signalsData.signals?.magic_wave?.wave] || '中性' }}
                </span>
              </div>
              <div class="card-body">
                <div class="metric-row">
                  <span class="lbl">波色</span>
                  <span class="val" :class="'wave-' + (signalsData.signals?.magic_wave?.wave)">
                    {{ waveTextMap[signalsData.signals?.magic_wave?.wave] || '中性' }}
                  </span>
                </div>
                <div class="metric-row">
                  <span class="lbl">强度</span>
                  <span class="val">{{ strengthTextMap[signalsData.signals?.magic_wave?.strength] || '--' }}</span>
                </div>
                <div class="metric-row" v-if="signalsData.signals?.magic_wave?.rsi !== undefined">
                  <span class="lbl">RSI</span>
                  <span class="val">{{ signalsData.signals.magic_wave.rsi }}</span>
                </div>
              </div>
            </div>

            <!-- 异动拉升 -->
            <div class="algo-card" :class="'card-' + anomalySignal">
              <div class="card-header">
                <el-icon><TrendCharts /></el-icon>
                <span class="title">异动拉升</span>
                <span class="badge" :class="'sig-' + anomalySignal">{{ signalBadgeText(anomalySignal) }}</span>
              </div>
              <div class="card-body">
                <template v-if="signalsData.signals?.anomaly_detect?.anomaly_type">
                  <div class="metric-row">
                    <span class="lbl">异动</span>
                    <span class="val up">{{ anomalyTypeTextMap[signalsData.signals.anomaly_detect.anomaly_type] }}</span>
                  </div>
                </template>
                <div class="metric-row">
                  <span class="lbl">日涨跌</span>
                  <span class="val" :class="dailyChange >= 0 ? 'up' : 'down'">
                    {{ dailyChange >= 0 ? '+' : '' }}{{ dailyChange }}%
                  </span>
                </div>
                <div class="metric-row">
                  <span class="lbl">量比</span>
                  <span class="val">{{ volumeRatio }}</span>
                </div>
              </div>
            </div>

            <!-- 底部寻机 -->
            <div class="algo-card" :class="'card-' + bottomSignal">
              <div class="card-header">
                <el-icon><Bottom /></el-icon>
                <span class="title">底部寻机</span>
                <span class="badge" :class="'sig-' + bottomSignal">{{ signalBadgeText(bottomSignal) }}</span>
              </div>
              <div class="card-body">
                <div class="metric-row">
                  <span class="lbl">底分</span>
                  <span class="val" :class="'score-color-' + ((signalsData.signals?.bottom_opportunity?.bottom_score ?? 0) / 20)">
                    {{ signalsData.signals?.bottom_opportunity?.bottom_score ?? '--' }}/100
                  </span>
                </div>
                <div class="metric-row" v-if="signalsData.signals?.bottom_opportunity?.drop_from_high_pct !== undefined">
                  <span class="lbl">跌幅</span>
                  <span class="val">{{ signalsData.signals.bottom_opportunity.drop_from_high_pct }}%</span>
                </div>
                <div class="metric-row" v-if="signalsData.signals?.bottom_opportunity?.signals?.length">
                  <span class="lbl">信号</span>
                  <span class="val tags">
                    <el-tag v-for="s in signalsData.signals.bottom_opportunity.signals" :key="s" size="small" effect="plain">{{ bottomSignalTextMap[s] || s }}</el-tag>
                  </span>
                </div>
              </div>
            </div>

            <!-- 趋势强度 -->
            <div class="algo-card card-strength">
              <div class="card-header">
                <el-icon><Odometer /></el-icon>
                <span class="title">趋势强度</span>
                <span class="badge" :class="'sig-' + trendDirection">{{ directionTextMap[trendDirection] || '未知' }}</span>
              </div>
              <div class="card-body">
                <div class="strength-bar">
                  <div class="bar-fill" :style="{ width: trendScore + '%', background: strengthGradient }"></div>
                </div>
                <div class="metric-row">
                  <span class="lbl">强度</span>
                  <span class="val">{{ trendScore }}/100</span>
                </div>
                <div class="metric-row" v-if="signalsData.signals?.trend_strength?.adx !== undefined">
                  <span class="lbl">ADX</span>
                  <span class="val">{{ signalsData.signals.trend_strength.adx }}</span>
                </div>
              </div>
            </div>

            <!-- 操作建议 -->
            <div class="algo-card card-advice" v-if="signalsData.overall_signal !== 'neutral'">
              <div class="card-header">
                <el-icon><ChatDotRound /></el-icon>
                <span class="title">综合建议</span>
              </div>
              <div class="card-body advice-body">
                <div class="advice-text" :class="'sig-' + signalsData.overall_signal">
                  {{ adviceText }}
                </div>
              </div>
            </div>
          </div>

          <!-- 算法说明 -->
          <el-card shadow="never" class="info-card">
            <template #header>
              <span><el-icon><InfoFilled /></el-icon> 算法说明</span>
            </template>
            <div class="algo-info-list">
              <div class="info-item"><strong>TD序列:</strong> 识别9根连续看涨/看跌K线，预测趋势反转点</div>
              <div class="info-item"><strong>均线雷达:</strong> MA5/10/20/30/60/120/250排列分析，判断多头/空头格局</div>
              <div class="info-item"><strong>通道突破:</strong> Donchian Channel 20日高低通道，检测价格突破信号</div>
              <div class="info-item"><strong>神奇电波:</strong> MACD+RSI复合指标，红波(多头)/绿波(空头)强度分级</div>
              <div class="info-item"><strong>异动拉升:</strong> 放量拉升/连续上涨/大振幅高位收盘异常检测</div>
              <div class="info-item"><strong>底部寻机:</strong> RSI超卖+MACD底背离+缩量企稳综合评分(0-100)</div>
              <div class="info-item"><strong>趋势强度:</strong> ADX方向性指数+均线斜率，评估趋势跟踪适合度</div>
            </div>
          </el-card>
        </template>

        <!-- 空状态 -->
        <el-empty v-if="!signalsData && !loading && !error" description="请输入股票代码开始分析" />
      </el-tab-pane>

      <!-- 自选股Tab -->
      <el-tab-pane label="自选股信号" name="watchlist">
        <el-card shadow="hover" class="watchlist-card">
          <template #header>
            <div class="watchlist-header">
              <span>自选股决策信号</span>
              <el-button size="small" @click="loadWatchlistSignals" :loading="watchlistLoading">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
            </div>
          </template>

          <!-- 桌面端表格 -->
          <div v-if="!isMobile" class="watchlist-table-wrap">
            <table class="watchlist-table">
              <thead>
                <tr>
                  <th class="col-code">代码</th>
                  <th class="col-name">名称</th>
                  <th class="col-price">最新价</th>
                  <th class="col-change">涨跌</th>
                  <th class="col-signal">综合信号</th>
                  <th class="col-score">评分</th>
                  <th class="col-trend">均线</th>
                  <th class="col-wave">电波</th>
                  <th class="col-action">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="stock in watchlistSignals" :key="stock.code">
                  <td class="col-code">{{ stock.code }}</td>
                  <td class="col-name">{{ stock.name }}</td>
                  <td class="col-price">{{ stock.close?.toFixed(2) ?? '--' }}</td>
                  <td class="col-change" :class="stock.change_pct >= 0 ? 'up' : 'down'">
                    {{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct ?? '--' }}%
                  </td>
                  <td class="col-signal">
                    <span v-if="stock.overall_signal" class="signal-tag" :class="'sig-' + stock.overall_signal">
                      {{ signalTextMap[stock.overall_signal] || '中性' }}
                    </span>
                    <span v-else style="color:#909399">--</span>
                  </td>
                  <td class="col-score" :class="getScoreClass(stock.composite_score)">{{ stock.composite_score ?? '--' }}</td>
                  <td class="col-trend">
                    <span class="trend-tag" :class="'trend-' + (stock.ma_trend || 'unknown')">{{ trendTextMap[stock.ma_trend] || '未知' }}</span>
                  </td>
                  <td class="col-wave">
                    <span class="wave-tag" :class="'wave-' + (stock.wave || 'neutral')">{{ waveTextMap[stock.wave] || '中性' }}</span>
                  </td>
                  <td class="col-action">
                    <el-button size="small" type="primary" link @click="analyzeFromWatchlist(stock.code, stock.name)">分析</el-button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 手机端卡片列表 -->
          <div v-else class="watchlist-mobile">
            <div v-for="stock in watchlistSignals" :key="stock.code" class="watchlist-item" @click="analyzeFromWatchlist(stock.code, stock.name)">
              <div class="item-left">
                <div class="item-name">{{ stock.name || stock.code }}</div>
                <div class="item-code">{{ stock.code }}</div>
              </div>
              <div class="item-center">
                <div class="item-price">{{ stock.close?.toFixed(2) ?? '--' }}</div>
                <div class="item-change" :class="stock.change_pct >= 0 ? 'up' : 'down'">
                  {{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct ?? '--' }}%
                </div>
              </div>
              <div class="item-right">
                <span v-if="stock.overall_signal" class="signal-tag" :class="'sig-' + stock.overall_signal">
                  {{ signalTextMap[stock.overall_signal] || '中性' }}
                </span>
                <span v-else class="wave-tag wave-neutral">--</span>
                <div class="item-tags-row">
                  <span class="trend-tag" :class="'trend-' + (stock.ma_trend || 'unknown')">{{ trendTextMap[stock.ma_trend] || '未知' }}</span>
                  <span class="wave-tag" :class="'wave-' + (stock.wave || 'neutral')">{{ waveTextMap[stock.wave] || '中性' }}</span>
                </div>
              </div>
            </div>
          </div>

          <el-empty v-if="!watchlistLoading && watchlistSignals.length === 0" description="暂无自选股数据" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 预警通知 -->
    <el-drawer v-model="alertDrawerVisible" title="决策预警通知" size="400px">
      <div class="alert-list">
        <div v-for="alert in decisionAlerts" :key="alert.stock_code + alert.alert_type" class="alert-item" :class="'alert-' + alert.alert_level.toLowerCase()">
          <div class="alert-header">
            <span class="alert-name">{{ alert.stock_name }}</span>
            <el-tag :type="alert.alert_level === 'CRITICAL' ? 'danger' : 'warning'" size="small">{{ alert.alert_level }}</el-tag>
          </div>
          <div class="alert-message">{{ alert.message }}</div>
          <div class="alert-recommendation">{{ alert.recommendation }}</div>
        </div>
        <el-empty v-if="!decisionAlerts.length" description="暂无预警" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import api from '@/api'
import { stockApi } from '@/api'
import { watchlistApi } from '@/api'
import RefreshingIndicator from '@/components/RefreshingIndicator.vue'
import { ElMessage } from 'element-plus'

const query = ref('')
const loading = ref(false)
const error = ref(null)
const signalsData = ref(null)
const stockName = ref('')
const isMobile = ref(window.innerWidth <= 768)
const inputSize = computed(() => (isMobile.value ? 'small' : 'default'))
const activeTab = ref('stock')

// 进度条相关
const loadProgress = ref(0)
const progressText = ref('正在获取K线数据...')

// 自选股相关
const watchlistSignals = ref([])
const watchlistLoading = ref(false)

// 预警相关
const alertDrawerVisible = ref(false)
const decisionAlerts = ref([])

function checkMobile() {
  isMobile.value = window.innerWidth <= 768
}

onMounted(() => {
  window.addEventListener('resize', checkMobile)
  loadWatchlistSignals()
})
onUnmounted(() => window.removeEventListener('resize', checkMobile))

// 信号文本映射
const signalTextMap = {
  strong_buy: '强烈买入',
  buy: '买入',
  neutral: '中性观望',
  sell: '卖出',
  strong_sell: '强烈卖出',
}

const trendTextMap = {
  strong_bullish: '强势多头',
  bullish: '多头趋势',
  sideways: '震荡整理',
  bearish: '空头趋势',
  unknown: '未知',
}

const alignmentTextMap = {
  bullish_alignment: '多头排列',
  partial_bullish: '部分多头',
  bearish_alignment: '空头排列',
  mixed: '混合排列',
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

const directionTextMap = {
  bullish: '多头',
  bearish: '空头',
  unknown: '未知',
}

// 计算属性
const tdSignal = computed(() => signalsData.value?.signals?.td_sequential?.signal || 'neutral')
const maTrend = computed(() => signalsData.value?.signals?.ma_radar?.trend || 'unknown')
const channelSignal = computed(() => signalsData.value?.signals?.channel_breakout?.signal || 'neutral')
const waveSignal = computed(() => signalsData.value?.signals?.magic_wave?.signal || 'neutral')
const anomalySignal = computed(() => signalsData.value?.signals?.anomaly_detect?.signal || 'neutral')
const bottomSignal = computed(() => signalsData.value?.signals?.bottom_opportunity?.signal || 'neutral')
const trendScore = computed(() => signalsData.value?.signals?.trend_strength?.strength ?? 0)
const trendDirection = computed(() => signalsData.value?.signals?.trend_strength?.trend_direction || 'unknown')

const dailyChange = computed(() => signalsData.value?.signals?.anomaly_detect?.daily_change_pct ?? '--')
const volumeRatio = computed(() => signalsData.value?.signals?.anomaly_detect?.volume_ratio ?? '--')

const scoreGradient = computed(() => {
  const score = signalsData.value?.composite_score ?? 50
  if (score >= 70) return 'conic-gradient(from 180deg, #f56c6c 0%, #e6a23c 50%, #909399 100%)'
  if (score >= 40) return 'conic-gradient(from 180deg, #e6a23c 0%, #909399 50%, #67c23a 100%)'
  return 'conic-gradient(from 180deg, #67c23a 0%, #909399 50%, #e6a23c 100%)'
})

const strengthGradient = computed(() => {
  const score = trendScore.value
  if (score >= 70) return 'linear-gradient(90deg, #f56c6c, #ff8787)'
  if (score >= 40) return 'linear-gradient(90deg, #E6A23C, #F7CA18)'
  return 'linear-gradient(90deg, #67c23a, #85ce61)'
})

const adviceText = computed(() => {
  const sig = signalsData.value?.overall_signal || 'neutral'
  const texts = {
    strong_buy: '多项算法共振买入信号，趋势强劲，建议积极建仓。注意设置止损位。',
    buy: '多数算法偏向买入，可考虑逢低布局。关注均线支撑和成交量配合。',
    neutral: '信号分歧较大，建议观望等待明确方向。控制仓位，谨慎操作。',
    sell: '多项算法提示卖出风险，趋势偏弱，建议减仓或离场观望。',
    strong_sell: '强烈卖出信号共振，下跌趋势明显，建议果断止损离场。',
  }
  return texts[sig] || texts.neutral
})

function signalBadgeText(signal) {
  return signalTextMap[signal] || '中性'
}

// 股票搜索建议
const querySearch = async (queryString, callback) => {
  if (!queryString.trim()) {
    callback([])
    return
  }
  try {
    const res = await api.get('/stock/suggest', { params: { q: queryString } })
    callback(res || [])
  } catch (e) {
    console.error('搜索建议失败:', e)
    callback([])
  }
}

const handleSuggestSelect = (item) => {
  query.value = `${item.name} (${item.code})`
}

// 加载决策信号（带进度模拟）
async function loadSignals() {
  const codeMatch = query.value.match(/(\d{6})/)
  if (!codeMatch) {
    error.value = '请输入有效的6位股票代码'
    return
  }
  const code = codeMatch[1]
  loading.value = true
  error.value = null
  loadProgress.value = 0
  progressText.value = '正在获取K线数据...'

  // 模拟进度
  const progressTimer = setInterval(() => {
    if (loadProgress.value < 90) {
      loadProgress.value += 10
      if (loadProgress.value >= 30) progressText.value = '正在运行7个算法...'
      if (loadProgress.value >= 60) progressText.value = '正在计算综合评分...'
      if (loadProgress.value >= 80) progressText.value = '正在生成建议...'
    }
  }, 200)

  try {
    const res = await stockApi.getDecisionSignals(code)
    console.log('决策信号返回结果:', res)
    if (res.status === 'error') {
      const errorMsg = res.message || '获取信号失败'
      console.error('K线数据获取失败:', errorMsg)
      throw new Error(errorMsg)
    }
    signalsData.value = res
    stockName.value = query.value.replace(/\(\d+\)/, '').trim()
    loadProgress.value = 100
    progressText.value = '分析完成'
  } catch (e) {
    const errorMsg = e.message || '网络错误，请稍后重试'
    error.value = `分析失败: ${errorMsg}\n\n可能原因：\n1. 网络连接问题，无法连接通达信服务器\n2. 股票代码不正确\n3. 非交易时间或数据源暂不可用\n\n请检查后端日志获取详细信息`
    console.error('加载决策信号失败:', e)
  } finally {
    clearInterval(progressTimer)
    loading.value = false
  }
}

// 加载自选股信号（使用 full=true 获取完整7个算法+综合评分）
async function loadWatchlistSignals() {
  watchlistLoading.value = true
  try {
    const res = await watchlistApi.getMyWatchlist()
    if (res && res.stocks && res.stocks.length > 0) {
      const codes = res.stocks.map(s => s.stock_code)
      // full=true: 获取全部7个算法结果+综合评分，确保数据完整
      const signalRes = await stockApi.getWatchlistDecisionSignals(codes, true)
      watchlistSignals.value = signalRes.stocks || []
      if (signalRes.fail_count > 0) {
        console.warn(`自选股信号获取失败 ${signalRes.fail_count} 只:`, signalRes.fail_codes)
      }
      if (signalRes.total === 0 && res.stocks.length > 0) {
        console.error('所有自选股决策信号获取失败，请检查pytdx连接')
      }
    }
  } catch (e) {
    watchlistSignals.value = []
    console.error('加载自选股信号失败:', e)
  } finally {
    watchlistLoading.value = false
  }
}

// 评分颜色类
function getScoreClass(score) {
  if (score == null) return ''
  if (score >= 60) return 'score-high'
  if (score >= 40) return 'score-mid'
  return 'score-low'
}

// 从自选股跳转到分析
function analyzeFromWatchlist(code, name) {
  query.value = `${name} (${code})`
  activeTab.value = 'stock'
  loadSignals()
}

// 加载预警
async function loadAlerts() {
  try {
    const res = await stockApi.monitorWatchlistDecision()
    if (res.status === 'success' && res.data?.alerts) {
      decisionAlerts.value = res.data.alerts
      if (res.data.alerts.length > 0) {
        alertDrawerVisible.value = true
      }
    }
  } catch (e) {
    console.error('加载预警失败:', e)
  }
}
</script>

<style scoped>
.decision-center {
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

.scanner-link {
  margin-left: auto;
}

.main-tabs {
  margin-bottom: 16px;
}

.search-card {
  margin-bottom: 16px;
}

.analyze-btn {
  border-radius: 0 3px 3px 0;
}

/* 进度条 */
.progress-container {
  margin-bottom: 16px;
}

.progress-text {
  font-size: 13px;
  color: #909399;
  text-align: center;
  margin-top: 8px;
}

/* 综合评分卡片 */
.score-overview {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 24px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  margin-bottom: 16px;
}

.score-ring {
  width: 100px;
  height: 100px;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.score-val {
  font-size: 28px;
  font-weight: bold;
  color: #fff;
}

.score-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
}

.score-info {
  flex: 1;
}

.signal-badge {
  display: inline-block;
  padding: 4px 16px;
  border-radius: 20px;
  font-size: 16px;
  font-weight: bold;
  margin-bottom: 8px;
}

.sig-strong_buy, .sig-buy, .sig-strong_bullish, .sig-bullish {
  background: #fef0f0;
  color: #f56c6c;
}

.sig-sell, .sig-strong_sell, .sig-bearish {
  background: #f0f9eb;
  color: #67c23a;
}

.sig-neutral, .sig-sideways, .sig-unknown {
  background: #f4f4f5;
  color: #909399;
}

.stock-name {
  font-size: 18px;
  font-weight: bold;
  margin-bottom: 4px;
}

.signal-count {
  font-size: 14px;
  color: #606266;
}

/* 算法卡片网格 */
.algo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.algo-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  overflow: hidden;
  transition: transform 0.2s, box-shadow 0.2s;
}

.algo-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
}

.card-header .title {
  flex: 1;
  font-weight: bold;
  font-size: 14px;
}

.badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: bold;
}

.sig-buy, .sig-strong_buy {
  background: #fef0f0;
  color: #f56c6c;
}

.sig-sell, .sig-strong_sell {
  background: #f0f9eb;
  color: #67c23a;
}

.sig-neutral, .sig-unknown, .sig-watch {
  background: #f4f4f5;
  color: #909399;
}

/* 波色特殊样式 */
.sig-wave-red {
  background: linear-gradient(135deg, #ff6b6b, #ee5a24);
  color: #fff;
}

.sig-wave-green {
  background: linear-gradient(135deg, #67c23a, #85ce61);
  color: #fff;
}

.card-body {
  padding: 16px;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
}

.metric-row .lbl {
  color: #909399;
  font-size: 13px;
}

.metric-row .val {
  font-weight: bold;
  font-size: 14px;
}

.up, .c-red {
  color: #f56c6c;
}

.down, .c-green {
  color: #67c23a;
}

/* 波色文字 */
.wave-red {
  color: #f56c6c;
}

.wave-green {
  color: #67c23a;
}

/* 强度条 */
.strength-bar {
  height: 8px;
  background: #ebeef5;
  border-radius: 4px;
  margin-bottom: 12px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
}

/* 底部分数颜色 */
.score-color-0, .score-color-1 { color: #67c23a; }
.score-color-2 { color: #e6a23c; }
.score-color-3, .score-color-4 { color: #f56c6c; }

/* 建议卡片 */
.advice-body {
  padding: 16px;
}

.advice-text {
  font-size: 14px;
  line-height: 1.8;
  padding: 12px;
  border-radius: 8px;
}

.sig-strong_buy, .sig-buy {
  background: #fef0f0;
  color: #f56c6c;
}

.sig-sell, .sig-strong_sell {
  background: #f0f9eb;
  color: #67c23a;
}

/* 信息卡片 */
.info-card {
  margin-top: 16px;
}

.algo-info-list {
  font-size: 13px;
  line-height: 2;
  color: #606266;
}

.info-item {
  padding: 4px 0;
}

/* 错误框 */
.error-box {
  text-align: center;
  padding: 40px 20px;
}

.error-box p {
  margin: 16px 0;
  color: #606266;
}

/* 自选股 */
.watchlist-card {
  margin-top: 16px;
}

.watchlist-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* 原生表格样式 */
.watchlist-table-wrap {
  overflow-x: auto;
}

.watchlist-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.watchlist-table th,
.watchlist-table td {
  padding: 10px 8px;
  text-align: left;
  border-bottom: 1px solid #ebeef5;
  white-space: nowrap;
}

.watchlist-table th {
  background: #f5f7fa;
  font-weight: 600;
  color: #606266;
}

.watchlist-table tbody tr:hover {
  background: #f5f7fa;
}

.watchlist-table .col-code {
  width: 70px;
  font-family: monospace;
}

.watchlist-table .col-name {
  width: 90px;
  font-weight: 500;
}

.watchlist-table .col-price {
  width: 80px;
  text-align: right;
  font-weight: 600;
}

.watchlist-table .col-change {
  width: 70px;
  text-align: right;
  font-weight: 500;
}

.watchlist-table .col-trend,
.watchlist-table .col-wave {
  width: 80px;
  text-align: center;
}

.watchlist-table .col-score {
  width: 60px;
  text-align: center;
  font-weight: 600;
}

.watchlist-table .col-signal {
  width: 80px;
  text-align: center;
}

.watchlist-table .col-score {
  width: 60px;
  text-align: center;
  font-weight: 600;
}

.watchlist-table .col-action {
  width: 60px;
  text-align: center;
}

/* 综合信号标签 */
.signal-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.sig-strong_buy, .sig-buy {
  background: #fef0f0;
  color: #f56c6c;
}

.sig-sell, .sig-strong_sell {
  background: #f0f9eb;
  color: #67c23a;
}

.sig-neutral {
  background: #f4f4f5;
  color: #909399;
}

/* 评分颜色 */
.score-high { color: #f56c6c; font-weight: 700; }
.score-mid { color: #e6a23c; font-weight: 600; }
.score-low { color: #67c23a; font-weight: 600; }

.price-text {
  font-weight: 600;
}

.trend-tag, .wave-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.trend-strong_bullish, .trend-bullish {
  background: #fef0f0;
  color: #f56c6c;
}

.trend-bearish {
  background: #f0f9eb;
  color: #67c23a;
}

.trend-sideways, .trend-unknown {
  background: #f4f4f5;
  color: #909399;
}

.wave-red {
  background: #fef0f0;
  color: #f56c6c;
}

.wave-green {
  background: #f0f9eb;
  color: #67c23a;
}

.wave-neutral {
  background: #f4f4f5;
  color: #909399;
}

.score-text {
  font-weight: 600;
  color: #303133;
}

/* 手机端自选股卡片 */
.watchlist-mobile {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.watchlist-item {
  display: flex;
  align-items: center;
  padding: 12px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  cursor: pointer;
  transition: all 0.2s;
}

.watchlist-item:hover {
  border-color: #409eff;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.15);
}

.watchlist-item:active {
  background: #f5f7fa;
}

.item-left {
  flex: 1;
  min-width: 0;
}

.item-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-code {
  font-size: 12px;
  color: #909399;
}

.item-center {
  width: 80px;
  text-align: right;
  margin: 0 12px;
}

.item-price {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}

.item-change {
  font-size: 12px;
  font-weight: 500;
}

.item-right {
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: flex-end;
}

.item-tags-row {
  display: flex;
  gap: 4px;
  align-items: center;
}

/* 预警 */
.alert-list {
  padding: 16px;
}

.alert-item {
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 12px;
  border-left: 4px solid;
}

.alert-critical {
  background: #fef0f0;
  border-color: #f56c6c;
}

.alert-warning {
  background: #fdf6ec;
  border-color: #e6a23c;
}

.alert-info {
  background: #ecf5ff;
  border-color: #409eff;
}

.alert-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.alert-name {
  font-weight: bold;
  font-size: 14px;
}

.alert-message {
  font-size: 13px;
  color: #606266;
  margin-bottom: 4px;
}

.alert-recommendation {
  font-size: 12px;
  color: #909399;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .decision-center {
    padding: 8px;
  }

  .page-title {
    font-size: 16px;
    margin-bottom: 10px;
    gap: 6px;
  }

  .scanner-link {
    padding: 4px 8px;
    font-size: 12px;
  }

  .main-tabs :deep(.el-tabs__header) {
    margin-bottom: 10px;
  }

  .main-tabs :deep(.el-tabs__item) {
    font-size: 13px;
    height: 36px;
    line-height: 36px;
  }

  .score-overview {
    flex-direction: column;
    text-align: center;
    gap: 10px;
    padding: 12px;
    margin-bottom: 10px;
  }

  .score-ring {
    width: 70px;
    height: 70px;
  }

  .score-val {
    font-size: 20px;
  }

  .score-label {
    font-size: 11px;
  }

  .score-info {
    width: 100%;
  }

  .signal-badge {
    font-size: 13px;
    padding: 3px 12px;
    margin-bottom: 6px;
  }

  .stock-name {
    font-size: 14px;
    margin-bottom: 2px;
  }

  .signal-count {
    font-size: 12px;
  }

  .algo-grid {
    grid-template-columns: 1fr;
    gap: 8px;
    margin-bottom: 10px;
  }

  .algo-card {
    border-radius: 8px;
  }

  .card-header {
    padding: 8px 10px;
  }

  .card-header .title {
    font-size: 12px;
  }

  .badge {
    font-size: 11px;
    padding: 1px 6px;
  }

  .card-body {
    padding: 8px 10px;
  }

  .metric-row {
    padding: 3px 0;
  }

  .metric-row .lbl {
    font-size: 11px;
  }

  .metric-row .val {
    font-size: 12px;
  }

  .info-card {
    margin-top: 10px;
  }

  .algo-info-list {
    font-size: 11px;
    line-height: 1.6;
  }

  .watchlist-card {
    margin-top: 10px;
  }

  .watchlist-header {
    padding: 0;
  }

  .watchlist-header span {
    font-size: 14px;
  }

  /* 手机端自选股卡片紧凑 */
  .watchlist-mobile {
    gap: 6px;
  }

  .watchlist-item {
    padding: 10px;
    border-radius: 6px;
  }

  .item-name {
    font-size: 13px;
  }

  .item-code {
    font-size: 11px;
  }

  .item-center {
    width: 70px;
    margin: 0 8px;
  }

  .item-price {
    font-size: 14px;
  }

  .item-change {
    font-size: 11px;
  }

  .item-right {
    gap: 3px;
  }

  .trend-tag, .wave-tag {
    font-size: 10px;
    padding: 1px 5px;
  }
}
</style>
