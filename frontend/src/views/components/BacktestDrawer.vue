<template>
  <el-drawer v-model="drawerVisible" :size="drawerSize" :show-close="true" direction="rtl" :with-header="false">
    <div class="backtest-drawer">
      <div class="custom-drawer-header">
        <span class="custom-drawer-title">
          策略回测
          <span v-if="stockName" class="custom-drawer-code">{{ stockName }} ({{ stockCode }})</span>
        </span>
        <button class="custom-drawer-close" @click="drawerVisible = false" aria-label="关闭">
          <el-icon><Close /></el-icon>
        </button>
      </div>

      <div class="drawer-content">
        <!-- 回测参数设置 -->
        <el-card shadow="never" class="param-card">
          <el-form :model="form" label-width="80px" size="default">
            <el-form-item label="策略选择">
              <el-select v-model="form.strategy" style="width: 100%" @change="onStrategyChange" placeholder="请选择回测策略">
                <el-option
                  v-for="s in strategies"
                  :key="s.key"
                  :label="s.name || s.key"
                  :value="s.key"
                  :title="s.desc"
                >
                  <span style="float: left">{{ s.name }}</span>
                  <span style="float: right; color: #909399; font-size: 12px; margin-left: 8px">{{ s.desc }}</span>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="回测天数">
              <el-slider v-model="form.days" :min="30" :max="250" :step="30" show-stops show-markers />
              <div class="days-label">{{ form.days }} 天 (约 {{ Math.round(form.days / 21) }} 个月)</div>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="runBacktest" :loading="running" style="width: 100%">
                <el-icon><Cpu /></el-icon> 开始回测
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 加载状态 -->
        <div v-if="running" class="loading-section">
          <el-skeleton :rows="6" animated />
        </div>

        <!-- 错误状态 -->
        <el-card v-else-if="error" shadow="never" class="error-card">
          <div style="text-align:center;padding:20px">
            <el-icon :size="48" color="#E6A23C"><WarningFilled /></el-icon>
            <p style="margin:12px 0;color:#909399">{{ error }}</p>
            <el-button type="primary" @click="runBacktest">重试</el-button>
          </div>
        </el-card>

        <!-- 回测结果 -->
        <template v-else-if="result">
          <!-- 综合评分 -->
          <el-card shadow="hover" class="score-card">
            <template #header>
              <span><el-icon><TrendCharts /></el-icon> 回测评分</span>
            </template>
            <div class="score-display">
              <div class="score-circle" :class="'rating-' + result.rating">
                <span class="score-num">{{ result.composite_score }}</span>
              </div>
              <div class="rating-info">
                <span class="rating-badge" :class="'badge-' + result.rating">
                  {{ ratingTextMap[result.rating] || result.rating }}
                </span>
                <span class="strategy-name">{{ strategyNameMap[result.strategy] || result.strategy }}</span>
              </div>
            </div>
          </el-card>

          <!-- 核心指标 -->
          <el-card shadow="hover" class="metrics-card">
            <template #header>
              <span><el-icon><DataLine /></el-icon> 核心指标</span>
            </template>
            <div class="metrics-grid">
              <div class="metric-item">
                <div class="metric-label">总收益率</div>
                <div class="metric-value" :class="result.total_return_pct >= 0 ? 'up' : 'down'">
                  {{ result.total_return_pct >= 0 ? '+' : '' }}{{ result.total_return_pct }}%
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-label">年化收益</div>
                <div class="metric-value" :class="result.annual_return_pct >= 0 ? 'up' : 'down'">
                  {{ result.annual_return_pct >= 0 ? '+' : '' }}{{ result.annual_return_pct }}%
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-label">夏普比率</div>
                <div class="metric-value">{{ result.sharpe_ratio }}</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">最大回撤</div>
                <div class="metric-value down">{{ result.max_drawdown_pct }}%</div>
              </div>
              <div class="metric-item">
                <div class="metric-label">胜率</div>
                <div class="metric-value" :class="result.win_rate_pct >= 50 ? 'up' : 'down'">
                  {{ result.win_rate_pct }}%
                </div>
              </div>
              <div class="metric-item">
                <div class="metric-label">盈亏比</div>
                <div class="metric-value">{{ result.profit_factor }}</div>
              </div>
            </div>
          </el-card>

          <!-- 交易统计 -->
          <el-card shadow="hover" class="trades-card">
            <template #header>
              <span><el-icon><Document /></el-icon> 交易统计</span>
            </template>
            <div class="trade-stats">
              <div class="stat-row">
                <span class="stat-label">总交易次数</span>
                <span class="stat-value">{{ result.total_trades }} 次</span>
              </div>
              <div class="stat-row">
                <span class="stat-label">回测周期</span>
                <span class="stat-value">{{ result.period_days }} 天</span>
              </div>
            </div>
          </el-card>

          <!-- 策略说明 -->
          <el-card shadow="never" class="info-card">
            <template #header>
              <span><el-icon><InfoFilled /></el-icon> 策略说明</span>
            </template>
            <div class="strategy-desc">
              {{ strategyDescMap[result.strategy] || '暂无策略说明' }}
            </div>
          </el-card>
        </template>

        <el-empty v-if="!running && !error && !result" description="选择策略并开始回测" />
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'
import { backtestApi } from '@/api'

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

const isMobile = ref(window.innerWidth <= 768)
const drawerSize = computed(() => (isMobile.value ? '100%' : '550px'))

const form = ref({
  strategy: 'macd',
  days: 120,
})

const running = ref(false)
const error = ref(null)
const result = ref(null)
const strategies = ref([])

const ratingTextMap = {
  excellent: '优秀',
  good: '良好',
  fair: '一般',
  poor: '较差',
}

const strategyNameMap = {
  macd: 'MACD策略',
  kdj: 'KDJ策略',
  rsi: 'RSI策略',
  bollinger: '布林带策略',
  dualma: '双均线策略',
}

const strategyDescMap = {
  macd: 'MACD策略：利用MACD指标的零轴穿越和柱状线变化来判断买卖时机。当DIF上穿DEA时买入，下穿时卖出。适合趋势性行情。',
  kdj: 'KDJ策略：K线上穿J线形成金叉时买入，下穿形成死叉时卖出。超买区(>80)卖出，超卖区(<20)买入。适合短线交易。',
  rsi: 'RSI策略：当RSI指标低于30进入超卖区时买入，高于70进入超买区时卖出。适合震荡行情。',
  bollinger: '布林带策略：价格触及下轨时买入，触及上轨时卖出。利用价格回归均值的特性获利。适合区间震荡。',
  dualma: '双均线策略：短期均线上穿长期均线时买入（金叉），下穿时卖出（死叉）。经典的趋势跟踪策略。',
}

function checkMobile() {
  isMobile.value = window.innerWidth <= 768
}

async function loadStrategies() {
  try {
    const res = await backtestApi.listStrategies()
    if (res && res.data && res.data.strategies) {
      strategies.value = res.data.strategies
    } else {
      throw new Error('无效响应')
    }
  } catch (e) {
    console.error('加载策略列表失败:', e)
    strategies.value = [
      { key: 'macd', name: 'MACD', desc: 'MACD金叉/死叉策略' },
      { key: 'kdj', name: 'KDJ', desc: 'KDJ超买/超卖策略' },
      { key: 'rsi', name: 'RSI', desc: 'RSI超买/超卖策略' },
      { key: 'bollinger', name: '布林带', desc: '布林带突破/回归策略' },
      { key: 'dualma', name: '双均线', desc: '双均线金叉/死叉策略' },
    ]
  }
}

function onStrategyChange() {
  result.value = null
  error.value = null
}

async function runBacktest() {
  if (!props.stockCode) {
    error.value = '股票代码无效'
    return
  }

  running.value = true
  error.value = null
  result.value = null

  try {
    const res = await backtestApi.verify({
      stock: props.stockCode,
      strategy: form.value.strategy,
      days: form.value.days,
    })

    if (res.status === 'success' && res.data) {
      result.value = res.data
    } else {
      throw new Error(res.message || '回测失败')
    }
  } catch (e) {
    error.value = e.message || '网络错误，请稍后重试'
    console.error('回测执行失败:', e)
  } finally {
    running.value = false
  }
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      loadStrategies()
      result.value = null
      error.value = null
    }
  }
)

window.addEventListener('resize', checkMobile)
onUnmounted(() => window.removeEventListener('resize', checkMobile))
</script>

<style scoped>
.backtest-drawer {
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

.param-card {
  margin-bottom: 16px;
}

.days-label {
  text-align: center;
  font-size: 12px;
  color: #909399;
  margin-top: -12px;
}

.loading-section {
  margin-top: 20px;
}

.error-card {
  margin-top: 40px;
}

.score-card {
  margin-bottom: 12px;
}

.score-card :deep(.el-card__header) {
  padding: 8px 14px;
  font-size: 13px;
}

.score-card :deep(.el-card__body) {
  padding: 6px 14px;
}

.score-display {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 6px 0;
}

.score-circle {
  width: 50px;
  height: 50px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.rating-excellent { background: linear-gradient(135deg, #f56c6c, #ff8787); }
.rating-good { background: linear-gradient(135deg, #e6a23c, #f7ca18); }
.rating-fair { background: linear-gradient(135deg, #909399, #c0c4cc); }
.rating-poor { background: linear-gradient(135deg, #67c23a, #85ce61); }

.score-num {
  font-size: 18px;
  font-weight: bold;
}

.rating-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
}

.rating-badge {
  display: inline-block;
  padding: 3px 12px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: bold;
}

.badge-excellent { background: #fef0f0; color: #f56c6c; }
.badge-good { background: #fdf6ec; color: #e6a23c; }
.badge-fair { background: #f4f4f5; color: #909399; }
.badge-poor { background: #f0f9eb; color: #67c23a; }

.strategy-name {
  font-size: 14px;
  color: #606266;
}

.metrics-card {
  margin-bottom: 16px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding: 10px 0;
}

.metric-item {
  text-align: center;
  padding: 14px 8px;
  background: #f5f7fa;
  border-radius: 8px;
  transition: all 0.2s ease;
}

.metric-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.metric-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.metric-value {
  font-size: 18px;
  font-weight: bold;
  color: #303133;
}

.up { color: #f56c6c !important; }
.down { color: #67c23a !important; }

.trades-card {
  margin-bottom: 16px;
}

.trade-stats {
  padding: 10px 0;
}

.stat-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.stat-row:last-child {
  border-bottom: none;
}

.stat-label {
  color: #909399;
  font-size: 14px;
}

.stat-value {
  font-weight: bold;
  color: #303133;
}

.info-card {
  margin-top: 8px;
}

.strategy-desc {
  font-size: 13px;
  line-height: 1.8;
  color: #606266;
}

@media (max-width: 768px) {
  .custom-drawer-header {
    padding: 12px 16px;
  }

  .custom-drawer-title {
    font-size: 15px;
  }

  .drawer-content {
    padding: 12px;
  }

  .param-card :deep(.el-form-item) {
    margin-bottom: 12px;
  }

  .param-card :deep(.el-form-item__label) {
    font-size: 13px;
  }

  .metrics-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }

  .metric-item {
    padding: 10px 6px;
  }

  .metric-label {
    font-size: 11px;
  }

  .metric-value {
    font-size: 14px;
  }

  .score-card :deep(.el-card__header) {
    padding: 6px 12px;
    font-size: 12px;
  }

  .score-card :deep(.el-card__body) {
    padding: 4px 12px;
  }

  .score-display {
    gap: 8px;
    padding: 3px 0;
  }

  .score-circle {
    width: 42px;
    height: 42px;
  }

  .score-num {
    font-size: 15px;
  }

  .rating-badge {
    font-size: 12px;
    padding: 2px 8px;
  }

  .strategy-name {
    font-size: 12px;
  }

  .stat-label, .stat-value {
    font-size: 13px;
  }

  .strategy-desc {
    font-size: 12px;
    line-height: 1.6;
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
