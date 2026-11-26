<template>
  <el-drawer v-model="drawerVisible" :size="drawerSize" :show-close="true" direction="rtl" :with-header="false">
    <div class="decision-signals-drawer">
      <div class="custom-drawer-header">
        <span class="custom-drawer-title">
          {{ stockName || '决策信号' }}
          <span v-if="stockCode" class="custom-drawer-code">{{ stockCode }}</span>
        </span>
        <button class="custom-drawer-close" @click="drawerVisible = false" aria-label="关闭">
          <el-icon><Close /></el-icon>
        </button>
      </div>

      <div class="drawer-content">
        <el-skeleton :rows="10" animated v-if="loading && !signalsData" />

        <el-card v-else-if="error" shadow="never" class="error-card">
          <div style="text-align:center;padding:20px">
            <el-icon :size="48" color="#E6A23C"><WarningFilled /></el-icon>
            <p style="margin:12px 0;color:#909399">{{ error }}</p>
            <el-button type="primary" @click="loadSignals">重试</el-button>
          </div>
        </el-card>

        <template v-else-if="signalsData">
          <!-- 综合评分 -->
          <div class="score-overview">
            <div class="score-ring" :style="{ background: scoreGradient }">
              <span class="score-val">{{ signalsData.composite_score ?? '--' }}</span>
              <span class="score-label">综合分</span>
            </div>
            <div class="score-info">
              <div class="signal-badge" :class="'sig-' + (signalsData.overall_signal || 'neutral')">
                {{ signalTextMap[signalsData.overall_signal] || '中性' }}
              </div>
              <div class="stock-name">{{ stockName }} ({{ stockCode }})</div>
              <div class="signal-count">
                买入: <span class="c-red">{{ signalsData.buy_signal_count ?? 0 }}</span> /
                卖出: <span class="c-green">{{ signalsData.sell_signal_count ?? 0 }}</span> /
                中性: <span>{{ 7 - (signalsData.buy_signal_count ?? 0) - (signalsData.sell_signal_count ?? 0) }}</span>
              </div>
            </div>
          </div>

          <!-- 算法信号卡片 -->
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
        </template>

        <el-empty v-if="!signalsData && !loading && !error" description="暂无数据" />
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { stockApi } from '@/api'

const props = defineProps({
  modelValue: Boolean,
  stockCode: String,
  stockName: String,
})

const emit = defineEmits(['update:modelValue'])

const drawerVisible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val),
})

const signalsData = ref(null)
const loading = ref(false)
const error = ref(null)

const isMobile = ref(window.innerWidth <= 768)
const drawerSize = computed(() => (isMobile.value ? '100%' : '650px'))

function checkMobile() {
  isMobile.value = window.innerWidth <= 768
}

watch(
  () => props.stockCode,
  (newCode) => {
    if (newCode && props.modelValue) {
      loadSignals()
    }
  }
)

watch(
  () => props.modelValue,
  (visible) => {
    if (visible && props.stockCode) {
      loadSignals()
    }
  }
)

window.addEventListener('resize', checkMobile)

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

const directionTextMap = {
  bullish: '多头',
  bearish: '空头',
  unknown: '未知',
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

const tdSignal = computed(() => signalsData.value?.signals?.td_sequential?.signal || 'neutral')
const maTrend = computed(() => signalsData.value?.signals?.ma_radar?.trend || 'unknown')
const channelSignal = computed(() => signalsData.value?.signals?.channel_breakout?.signal || 'neutral')
const waveSignal = computed(() => signalsData.value?.signals?.magic_wave?.signal || 'neutral')
const anomalySignal = computed(() => signalsData.value?.signals?.anomaly_detect?.signal || 'neutral')
const bottomSignal = computed(() => signalsData.value?.signals?.bottom_opportunity?.signal || 'neutral')
const trendScore = computed(() => Math.round(signalsData.value?.signals?.trend_strength?.strength ?? 0))
const trendDirection = computed(() => signalsData.value?.signals?.trend_strength?.trend_direction || 'unknown')

const dailyChange = computed(() => {
  const val = signalsData.value?.signals?.anomaly_detect?.daily_change_pct
  return val != null ? parseFloat(val).toFixed(2) : '--'
})

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

async function loadSignals() {
  if (!props.stockCode) return
  loading.value = true
  error.value = null
  try {
    const res = await stockApi.getDecisionSignals(props.stockCode)
    if (res.status === 'error') {
      throw new Error(res.message || '获取信号失败')
    }
    signalsData.value = res
  } catch (e) {
    error.value = e.message || '网络错误，请稍后重试'
    console.error('加载决策信号失败:', e)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.decision-signals-drawer {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.custom-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #ebeef5;
  background: #f5f7fa;
  flex-shrink: 0;
}

.custom-drawer-title {
  font-size: 16px;
  font-weight: bold;
  color: #303133;
}

.custom-drawer-code {
  font-size: 12px;
  color: #909399;
  margin-left: 8px;
}

.custom-drawer-close {
  border: none;
  background: none;
  cursor: pointer;
  padding: 4px;
  font-size: 18px;
  color: #909399;
}

.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  min-height: 0;
}

.score-overview {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 20px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  margin-bottom: 16px;
}

.score-ring {
  width: 90px;
  height: 90px;
  border-radius: 50%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.score-val {
  font-size: 24px;
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
  font-size: 15px;
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
  font-size: 16px;
  font-weight: bold;
  margin-bottom: 4px;
}

.signal-count {
  font-size: 13px;
  color: #606266;
}

.algo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.algo-card {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
}

.card-header .title {
  flex: 1;
  font-weight: bold;
  font-size: 13px;
}

.badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
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

.sig-neutral, .sig-unknown {
  background: #f4f4f5;
  color: #909399;
}

.sig-wave-red {
  background: linear-gradient(135deg, #ff6b6b, #ee5a24);
  color: #fff;
}

.sig-wave-green {
  background: linear-gradient(135deg, #67c23a, #85ce61);
  color: #fff;
}

.card-body {
  padding: 12px;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.metric-row .lbl {
  color: #909399;
  font-size: 12px;
}

.metric-row .val {
  font-weight: bold;
  font-size: 13px;
}

.up, .c-red {
  color: #f56c6c;
}

.down, .c-green {
  color: #67c23a;
}

.wave-red {
  color: #f56c6c;
}

.wave-green {
  color: #67c23a;
}

.strength-bar {
  height: 6px;
  background: #ebeef5;
  border-radius: 3px;
  margin-bottom: 10px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.score-color-0, .score-color-1 { color: #67c23a; }
.score-color-2 { color: #e6a23c; }
.score-color-3, .score-color-4 { color: #f56c6c; }

.advice-body {
  padding: 12px;
}

.advice-text {
  font-size: 13px;
  line-height: 1.8;
  padding: 10px;
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

.error-card {
  margin-top: 40px;
}

@media (max-width: 768px) {
  .score-overview {
    flex-direction: column;
    text-align: center;
    gap: 10px;
    padding: 12px;
  }

  .score-ring {
    width: 70px;
    height: 70px;
  }

  .score-val {
    font-size: 20px;
  }

  .algo-grid {
    grid-template-columns: 1fr;
  }

  .signal-badge {
    font-size: 13px;
    padding: 3px 12px;
  }

  .stock-name {
    font-size: 14px;
  }
}
</style>

<style>
/* 移动端：抽屉内容底部避开 Tab Bar */
@media (max-width: 768px) {
  .el-drawer__body {
    padding-bottom: calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0) + 16px) !important;
  }
}
</style>
