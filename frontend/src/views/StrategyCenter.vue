<template>
  <div class="strategy-center-section">
    <!-- AI策略生成 -->
    <div class="strategy-actions-bar">
      <el-button size="small" @click="showConfigDialog = true">
        <el-icon><Setting /></el-icon> 配置
      </el-button>
      <el-button
        size="small"
        type="primary"
        :loading="generating === 'intraday'"
        @click="generateStrategy('intraday')"
      >盘中策略</el-button>
      <el-button
        size="small"
        type="warning"
        :loading="generating === 'midday'"
        @click="generateStrategy('midday')"
      >午间策略</el-button>
      <el-button
        size="small"
        type="success"
        :loading="generating === 'closing'"
        @click="generateStrategy('closing')"
      >收盘策略</el-button>
    </div>

    <!-- 最新策略摘要 -->
    <el-card v-if="latestStrategy" shadow="hover" class="strategy-summary-card">
      <div class="summary-row">
        <div class="summary-left">
          <span class="summary-date">{{ latestStrategy.decision_date }} {{ latestStrategy.decision_time }}</span>
          <el-tag size="small" :type="getModeTagType(latestStrategy.strategy_mode)">{{ formatMode(latestStrategy.strategy_mode) }}</el-tag>
          <span :class="['sentiment-badge small', latestStrategy.market_sentiment]">{{ formatSentiment(latestStrategy.market_sentiment) }}</span>
          <span v-if="latestStrategy.market_stage" :class="['stage-badge small', getStageClass(latestStrategy.market_stage)]">{{ latestStrategy.market_stage }}</span>
          <span v-if="latestStrategy.position_ratio != null" class="position-ratio-badge">仓位 {{ latestStrategy.position_ratio }}%</span>
        </div>
        <el-button size="small" type="primary" @click="viewStrategyDetail(latestStrategy.id)">查看详情</el-button>
      </div>
    </el-card>

    <!-- 策略详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="drawerTitle" :size="drawerSize" destroy-on-close class="strategy-drawer">
      <template v-if="detailStrategy">
        <!-- 顶部：市场情绪 + 分析 -->
        <div class="top-row">
          <div class="left-panel">
            <div class="strategy-section no-margin">
              <div class="section-title">市场情绪</div>
              <div :class="['sentiment-badge', detailStrategy.market_sentiment]">
                {{ formatSentiment(detailStrategy.market_sentiment) }}
              </div>
            </div>
            <!-- 市场环境卡片（新增） -->
            <div v-if="detailStrategy.market_stage || detailStrategy.dynamic_max_position != null" class="strategy-section no-margin env-card">
              <div class="section-title">市场环境与仓位配置</div>
              <div class="env-grid">
                <div v-if="detailStrategy.market_stage" class="env-item">
                  <span class="env-label">市场阶段</span>
                  <span :class="['env-value', getStageClass(detailStrategy.market_stage)]">{{ detailStrategy.market_stage }}</span>
                </div>
                <div v-if="detailStrategy.position_ratio != null" class="env-item">
                  <span class="env-label">建议仓位</span>
                  <span class="env-value">{{ detailStrategy.position_ratio }}%</span>
                </div>
                <div v-if="detailStrategy.dynamic_max_position != null" class="env-item">
                  <span class="env-label">仓位上限</span>
                  <span class="env-value">{{ detailStrategy.dynamic_max_position }}%</span>
                </div>
                <template v-if="detailStrategy.suggested_allocation">
                  <div class="env-item">
                    <span class="env-label">短线</span>
                    <span class="env-value">{{ detailStrategy.suggested_allocation.short || 0 }}%</span>
                  </div>
                  <div class="env-item">
                    <span class="env-label">中线</span>
                    <span class="env-value">{{ detailStrategy.suggested_allocation.mid || 0 }}%</span>
                  </div>
                  <div class="env-item">
                    <span class="env-label">长线</span>
                    <span class="env-value">{{ detailStrategy.suggested_allocation.long || 0 }}%</span>
                  </div>
                </template>
              </div>
            </div>
            <div class="strategy-section no-margin">
              <div class="section-title">市场分析</div>
              <div class="section-content">{{ detailStrategy.market_analysis }}</div>
            </div>
            <!-- P3: 策略历史回测表现 -->
            <div class="strategy-section no-margin bt-history-card" v-if="detailStrategy?.stocks?.length">
              <div class="section-title">📊 策略历史回测表现</div>
              <div class="bt-stock-list">
                <div v-for="stock in detailStrategy.stocks.slice(0, 5)" :key="stock.code" class="bt-stock-item">
                  <span class="bt-stock-name">{{ stock.name }} ({{ stock.code }})</span>
                  <el-button type="primary" link size="small" @click="loadStrategyBacktest(stock.code)">查看回测</el-button>
                </div>
              </div>
              
              <!-- 回测结果展示 -->
              <template v-if="strategyBacktestResults && activeStrategyStock">
                <div class="bt-result-card">
                  <div class="bt-result-header">
                    <span class="bt-stock-label">{{ strategyBacktestResults.stock }}</span>
                    <el-tag :type="getRatingType(strategyBacktestResults.rating)" size="small">
                      {{ strategyBacktestResults.composite_score }}分 ({{ strategyBacktestResults.rating }})
                    </el-tag>
                  </div>
                  <div class="bt-metrics-row">
                    <div class="bt-mini-metric">
                      <span class="bt-mini-label">总收益</span>
                      <span :class="strategyBacktestResults.total_return_pct >= 0 ? 'profit' : 'loss'">{{ formatReturn(strategyBacktestResults.total_return_pct) }}</span>
                    </div>
                    <div class="bt-mini-metric">
                      <span class="bt-mini-label">夏普比率</span>
                      <span>{{ strategyBacktestResults.sharpe_ratio?.toFixed(2) || '--' }}</span>
                    </div>
                    <div class="bt-mini-metric">
                      <span class="bt-mini-label">最大回撤</span>
                      <span class="loss">{{ formatReturn(strategyBacktestResults.max_drawdown_pct) }}</span>
                    </div>
                    <div class="bt-mini-metric">
                      <span class="bt-mini-label">胜率</span>
                      <span>{{ (strategyBacktestResults.win_rate_pct || 0).toFixed(1) }}%</span>
                    </div>
                  </div>
                </div>
              </template>
              <div v-else-if="strategyBtLoading" class="bt-loading">
                <el-icon class="is-loading"><Loading /></el-icon> 回测计算中...
              </div>
            </div>
            <div v-if="detailStrategy.position_analysis" class="strategy-section no-margin">
              <div class="section-title">持仓分析</div>
              <div class="section-content">{{ detailStrategy.position_analysis }}</div>
            </div>
          </div>
        </div>

        <!-- 决策依据卡片（新增，可折叠） -->
        <el-collapse v-if="detailStrategy.market_indicators && hasMarketIndicators" class="indicators-collapse" v-model="indicatorsActive">
          <el-collapse-item name="indicators">
            <template #title>
              <span class="collapse-title">AI 决策依据（点击展开/收起）</span>
            </template>
            <div class="indicators-grid">
              <div v-if="detailStrategy.market_indicators.northbound" class="indicator-item">
                <div class="indicator-label">北向资金</div>
                <div class="indicator-value">{{ detailStrategy.market_indicators.northbound }}</div>
              </div>
              <div v-if="detailStrategy.market_indicators.dragon_summary" class="indicator-item dragon-item">
                <div class="indicator-label">龙虎榜摘要</div>
                <div class="indicator-value pre-wrap">{{ detailStrategy.market_indicators.dragon_summary }}</div>
              </div>
              <div v-if="detailStrategy.market_indicators.sector_rotation" class="indicator-item">
                <div class="indicator-label">板块轮动</div>
                <div class="indicator-value pre-wrap">{{ detailStrategy.market_indicators.sector_rotation }}</div>
              </div>
              <div v-if="detailStrategy.market_indicators.sectors?.length" class="indicator-item">
                <div class="indicator-label">热门板块 TOP5</div>
                <div class="indicator-value">
                  <el-tag v-for="s in detailStrategy.market_indicators.sectors.slice(0,5)" :key="s.name" size="small" class="sector-tag">
                    {{ s.name }} {{ s.change_pct >= 0 ? '+' : '' }}{{ (s.change_pct || 0).toFixed(2) }}%
                  </el-tag>
                </div>
              </div>
              <div v-if="detailStrategy.market_indicators.hot_stocks_count > 0" class="indicator-item">
                <div class="indicator-label">候选股票池</div>
                <div class="indicator-value">{{ detailStrategy.market_indicators.hot_stocks_count }} 只多源热门股票</div>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>

        <!-- 建议区域：左右两列网格 -->
        <div class="suggestions-grid" v-if="detailStrategy.holdings_suggestions?.length || detailStrategy.watchlist_suggestions?.length">
          <!-- 持仓建议 -->
          <div v-if="detailStrategy.holdings_suggestions?.length" class="strategy-section suggestion-col">
            <div class="section-title">持仓建议</div>
            <div class="suggestion-grid">
              <div v-for="(item, index) in detailStrategy.holdings_suggestions" :key="'h'+index" class="suggestion-card">
                <div class="card-top-row">
                  <span class="stock-code">{{ item.code }}</span>
                  <span class="stock-name">{{ item.name }}</span>
                  <span v-if="item.position_type" :class="['pos-type-badge', item.position_type]">{{ formatPosType(item.position_type) }}</span>
                </div>
                <div class="badge-row">
                  <span :class="['action-badge', item.action]">{{ formatAction(item.action) }}</span>
                  <span :class="['risk-badge', item.risk_level]">{{ formatRisk(item.risk_level) }}</span>
                </div>
                <div v-if="item.technical_summary" class="tech-summary">{{ item.technical_summary }}</div>
                <div class="suggestion-reason">{{ item.reason }}</div>
                <div v-if="item.target_price || item.stop_loss || item.stop_loss_pct || item.take_profit_pct" class="suggestion-prices">
                  <span v-if="item.target_price">目标价: ¥{{ item.target_price }}</span>
                  <span v-if="item.stop_loss">止损价: ¥{{ item.stop_loss }}</span>
                  <span v-if="item.stop_loss_pct" class="price-pct">止损{{ item.stop_loss_pct }}%</span>
                  <span v-if="item.take_profit_pct" class="price-pct profit">止盈{{ item.take_profit_pct }}%</span>
                </div>
                <div class="feedback-row">
                  <el-button-group size="small">
                    <el-button :type="item.adopted === true ? 'success' : ''" @click="submitFeedback('holdings', item.code, true)" :disabled="item.adopted === true">采纳</el-button>
                    <el-button :type="item.adopted === false ? 'danger' : ''" @click="submitFeedback('holdings', item.code, false)" :disabled="item.adopted === false">不采纳</el-button>
                  </el-button-group>
                </div>
              </div>
            </div>
          </div>

          <!-- 自选股建议 -->
          <div v-if="detailStrategy.watchlist_suggestions?.length" class="strategy-section suggestion-col">
            <div class="section-title">自选股建议</div>
            <div class="suggestion-grid">
              <div v-for="(item, index) in detailStrategy.watchlist_suggestions" :key="'w'+index" :class="['suggestion-card', { 'new-rec-card': item.is_new_recommendation }]">
                <div class="card-top-row">
                  <span class="stock-code">{{ item.code }}</span>
                  <span class="stock-name">{{ item.name }}</span>
                  <span v-if="item.is_new_recommendation" class="new-rec-badge">AI 推荐</span>
                  <span v-if="item.position_type" :class="['pos-type-badge', item.position_type]">{{ formatPosType(item.position_type) }}</span>
                </div>
                <div class="badge-row">
                  <span :class="['action-badge', item.action]">{{ formatAction(item.action) }}</span>
                  <span :class="['risk-badge', item.risk_level]">{{ formatRisk(item.risk_level) }}</span>
                </div>
                <div v-if="item.technical_summary" class="tech-summary">{{ item.technical_summary }}</div>
                <div class="suggestion-reason">{{ item.reason }}</div>
                <div v-if="item.entry_price || item.target_price || item.suggested_position_ratio" class="suggestion-prices">
                  <span v-if="item.entry_price">入场价: ¥{{ item.entry_price }}</span>
                  <span v-if="item.target_price">目标价: ¥{{ item.target_price }}</span>
                  <span v-if="item.suggested_position_ratio" class="price-pct">建议仓位{{ item.suggested_position_ratio }}%</span>
                </div>
                <div class="feedback-row">
                  <el-button-group size="small">
                    <el-button :type="item.adopted === true ? 'success' : ''" @click="submitFeedback('watchlist', item.code, true)" :disabled="item.adopted === true">采纳</el-button>
                    <el-button :type="item.adopted === false ? 'danger' : ''" @click="submitFeedback('watchlist', item.code, false)" :disabled="item.adopted === false">不采纳</el-button>
                  </el-button-group>
                  <el-button
                    v-if="item.is_new_recommendation"
                    size="small"
                    type="primary"
                    plain
                    :icon="Plus"
                    @click="addToWatchlist(item.code, item.name)"
                  >加入自选</el-button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="detailStrategy.risk_warning" class="strategy-section risk-warning">
          <el-icon><Warning /></el-icon>
          {{ detailStrategy.risk_warning }}
        </div>
      </template>
    </el-drawer>

    <!-- 历史策略：flex:1 占满剩余空间，内部独立滚动 -->
    <div class="history-card">
      <div class="card-header">
        <span class="card-title">历史策略</span>
        <el-button size="small" @click="loadHistory" :loading="loadingHistory">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>

      <div class="history-list-wrapper">
        <div v-if="strategyHistory.length === 0" class="empty-history">暂无历史策略</div>
        <div v-else class="history-list">
          <div v-for="item in strategyHistory" :key="item.id" class="history-item" @click="viewStrategyDetail(item.id)">
            <div class="history-info">
              <span class="history-date">{{ item.decision_date }} {{ item.decision_time }}</span>
              <el-tag size="small" :type="getModeTagType(item.strategy_mode)">{{ formatMode(item.strategy_mode) }}</el-tag>
              <span :class="['sentiment-badge small', item.market_sentiment]">{{ formatSentiment(item.market_sentiment) }}</span>
              <span v-if="item.market_stage" :class="['stage-badge small', getStageClass(item.market_stage)]">{{ item.market_stage }}</span>
              <span v-if="item.position_ratio != null" class="position-ratio-badge">{{ item.position_ratio }}%</span>
            </div>
            <div class="history-analysis">{{ item.market_analysis }}</div>
            <el-button size="small" type="danger" @click.stop="deleteStrategy(item.id)">删除</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 配置对话框 -->
    <el-dialog v-model="showConfigDialog" title="策略配置" width="500px">
      <el-form :model="configForm" label-width="120px">
        <el-form-item label="启用自动策略">
          <el-switch v-model="configForm.is_enabled" />
        </el-form-item>

        <!-- 盘中策略时间 -->
        <el-form-item label="盘中策略">
          <div class="time-group">
            <div class="time-inputs">
              <div v-for="(time, index) in configForm.intraday_times" :key="'i'+index" class="time-row">
                <el-tag closable @close="removeTime('intraday', index)">{{ time }}</el-tag>
              </div>
            </div>
            <div class="add-time-row">
              <el-time-picker
                v-model="newTimeIntraday"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="选择时间"
                style="width: 120px"
              />
              <el-button size="small" @click="addTimeSlot('intraday')" :disabled="!newTimeIntraday">
                <el-icon><Plus /></el-icon> 添加
              </el-button>
            </div>
          </div>
        </el-form-item>

        <!-- 午间策略时间 -->
        <el-form-item label="午间策略">
          <div class="time-group">
            <div class="time-inputs">
              <div v-for="(time, index) in configForm.midday_times" :key="'m'+index" class="time-row">
                <el-tag closable type="warning" @close="removeTime('midday', index)">{{ time }}</el-tag>
              </div>
            </div>
            <div class="add-time-row">
              <el-time-picker
                v-model="newTimeMidday"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="选择时间"
                style="width: 120px"
              />
              <el-button size="small" @click="addTimeSlot('midday')" :disabled="!newTimeMidday">
                <el-icon><Plus /></el-icon> 添加
              </el-button>
            </div>
          </div>
        </el-form-item>

        <!-- 收盘/次日策略时间 -->
        <el-form-item label="收盘/次日">
          <div class="time-group">
            <div class="time-inputs">
              <div v-for="(time, index) in configForm.closing_times" :key="'c'+index" class="time-row">
                <el-tag closable type="success" @close="removeTime('closing', index)">{{ time }}</el-tag>
              </div>
            </div>
            <div class="add-time-row">
              <el-time-picker
                v-model="newTimeClosing"
                format="HH:mm"
                value-format="HH:mm"
                placeholder="选择时间"
                style="width: 120px"
              />
              <el-button size="small" @click="addTimeSlot('closing')" :disabled="!newTimeClosing">
                <el-icon><Plus /></el-icon> 添加
              </el-button>
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showConfigDialog = false">取消</el-button>
        <el-button type="primary" @click="saveConfig" :loading="savingConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { TrendCharts, Setting, Refresh, Delete, Warning, Plus, Loading } from '@element-plus/icons-vue'
import { holdingsApi, watchlistStrategyApi, watchlistApi, backtestApi } from '@/api/index'

// 持仓数据
const holdingsSummary = ref({})
const loadingHoldings = ref(false)

// 策略数据
const latestStrategy = ref(null)
const strategyHistory = ref([])
const generating = ref(null)
const loadingHistory = ref(false)

// 抽屉详情
const drawerVisible = ref(false)
const detailStrategy = ref(null)
const drawerTitle = ref('')
const mobileWidth = ref(window.innerWidth <= 768)
const drawerSize = computed(() => mobileWidth.value ? '100%' : '65%')

const _handleResize = () => { mobileWidth.value = window.innerWidth <= 768 }

// 配置
const showConfigDialog = ref(false)
const configForm = ref({ is_enabled: true, intraday_times: ['10:25', '14:10'], midday_times: ['12:30'], closing_times: ['16:00'] })
const savingConfig = ref(false)
const newTimeIntraday = ref('')
const newTimeMidday = ref('')
const newTimeClosing = ref('')

onMounted(async () => {
  window.addEventListener('resize', _handleResize)
  await Promise.all([refreshHoldings(), loadHistory(), loadConfig()])
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', _handleResize)
})

const refreshHoldings = async () => {
  loadingHoldings.value = true
  try {
    const res = await holdingsApi.getSummary()
    holdingsSummary.value = res || {}
  } catch (e) { console.error('获取持仓汇总失败:', e) }
  finally { loadingHoldings.value = false }
}

const loadLatestStrategy = async () => {
  try {
    const res = await watchlistStrategyApi.getLatest()
    latestStrategy.value = res?.strategy || null
  } catch (e) { console.error('获取最新策略失败:', e) }
}

const loadHistory = async () => {
  loadingHistory.value = true
  try {
    const res = await watchlistStrategyApi.getHistory({ page: 1, page_size: 20 })
    strategyHistory.value = res?.strategies || []
  } catch (e) { console.error('获取历史策略失败:', e) }
  finally { loadingHistory.value = false }
}

const loadConfig = async () => {
  try {
    const res = await watchlistStrategyApi.getConfig()
    if (res?.config) {
      configForm.value = res.config
    }
  } catch (e) { console.error('获取配置失败:', e) }
}

const generateStrategy = async (mode) => {
  const modeText = formatMode(mode)
  try {
    await ElMessageBox.confirm(
      `确定要生成${modeText}？AI将基于当前持仓和自选股进行分析。`,
      '确认生成策略',
      { confirmButtonText: '确定生成', cancelButtonText: '取消', type: 'info' }
    )
  } catch { return }
  generating.value = mode
  const loadingHint = ElMessage({
    message: `正在调用 AI 生成${modeText}，AI分析 + LLM推理可能需要1-10分钟，请耐心等待...`,
    type: 'info',
    duration: 0,
    showClose: false,
  })
  try {
    await watchlistStrategyApi.generate(mode, { timeout: 580000 })
    loadingHint.close()
    ElMessage.success(`${modeText}生成成功`)
    await Promise.all([loadLatestStrategy(), loadHistory()])
  } catch (e) {
    loadingHint.close()
    if (e.code === 'ECONNABORTED' || e.message?.includes('timeout')) {
      ElMessage.error('AI策略生成超时（580s）。后端可能仍在处理，请稍后刷新查看或重新生成。')
    } else {
      ElMessage.error(e.response?.data?.detail || '策略生成失败')
    }
  } finally { generating.value = null }
}

const viewStrategyDetail = async (id) => {
  try {
    const res = await watchlistStrategyApi.getDetail(id)
    detailStrategy.value = res?.strategy || null
    drawerTitle.value = `策略详情 (${detailStrategy.value.decision_date} ${detailStrategy.value.decision_time})`
    drawerVisible.value = true
  } catch (e) { ElMessage.error('获取策略详情失败') }
}

const deleteStrategy = async (id) => {
  try {
    await ElMessageBox.confirm('确定删除该策略记录？', '提示', { type: 'warning' })
    await watchlistStrategyApi.delete(id)
    ElMessage.success('删除成功')
    await Promise.all([loadLatestStrategy(), loadHistory()])
  } catch (e) { if (e !== 'cancel') ElMessage.error('删除失败') }
}

const saveConfig = async () => {
  savingConfig.value = true
  try {
    await watchlistStrategyApi.updateConfig(configForm.value)
    ElMessage.success('配置保存成功')
    showConfigDialog.value = false
  } catch (e) { ElMessage.error('配置保存失败') }
  finally { savingConfig.value = false }
}

const addTimeSlot = (mode) => {
  const timeMap = { intraday: newTimeIntraday, midday: newTimeMidday, closing: newTimeClosing }
  const ref = timeMap[mode]
  if (!ref.value) return
  const listKey = `${mode}_times`
  if (!configForm.value[listKey]) configForm.value[listKey] = []
  if (!configForm.value[listKey].includes(ref.value)) {
    configForm.value[listKey].push(ref.value)
    configForm.value[listKey].sort()
    ref.value = ''
  }
}

const removeTime = (mode, index) => {
  const listKey = `${mode}_times`
  if (configForm.value[listKey]) {
    configForm.value[listKey].splice(index, 1)
  }
}

const formatMoney = (v) => {
  if (!v) return '0.00'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
const formatSentiment = (s) => ({ bullish: '看多', bearish: '看空', neutral: '中性' }[s] || s)
const formatAction = (a) => ({ sell: '卖出', reduce: '减仓', hold: '持有', add: '加仓', buy: '买入', watch: '关注' }[a] || a)
const formatRisk = (r) => ({ low: '低风险', medium: '中风险', high: '高风险' }[r] || r)
const formatMode = (m) => ({ intraday: '上午盘中', intraday_afternoon: '下午盘中', midday: '午间策略', closing: '收盘策略', morning: '盘中策略-上午', afternoon: '盘中策略-下午' }[m] || m)
const getModeTagType = (m) => ({ intraday: '', intraday_afternoon: '', midday: 'warning', closing: 'success', morning: '', afternoon: '' }[m] || 'info')
const formatPosType = (p) => ({ short: '短线', mid: '中线', long: '长线' }[p] || p)
const getStageClass = (stage) => {
  if (!stage) return ''
  if (stage.includes('牛市')) return 'stage-bull'
  if (stage.includes('熊市')) return 'stage-bear'
  return 'stage-shock'
}
const hasMarketIndicators = computed(() => {
  const mi = detailStrategy.value?.market_indicators
  if (!mi) return false
  return !!(mi.northbound || mi.dragon_summary || mi.sector_rotation || mi.sectors?.length || mi.hot_stocks_count > 0)
})
// 决策依据折叠面板状态（默认折叠）
const indicatorsActive = ref([])

// 提交建议采纳反馈
const submitFeedback = async (suggestionType, code, adopted) => {
  if (!detailStrategy.value?.id) return
  try {
    await watchlistStrategyApi.updateFeedback(detailStrategy.value.id, {
      suggestion_type: suggestionType,
      code,
      adopted,
    })
    // 更新本地数据
    const list = suggestionType === 'holdings'
      ? detailStrategy.value.holdings_suggestions
      : detailStrategy.value.watchlist_suggestions
    const item = list?.find(i => i.code === code)
    if (item) item.adopted = adopted
    ElMessage.success(adopted ? '已标记为采纳' : '已标记为不采纳')
  } catch (e) {
    ElMessage.error('反馈提交失败：' + (e.response?.data?.detail || e.message))
  }
}

// 一键加入自选股（用于 AI 推荐的新标的）
const addToWatchlist = async (code, name) => {
  try {
    await watchlistApi.addStock(code, name, 'AI推荐')
    ElMessage.success(`${name}(${code}) 已加入自选股分组"AI推荐"`)
    // 标记该建议已采纳
    const item = detailStrategy.value?.watchlist_suggestions?.find(i => i.code === code)
    if (item) item.is_new_recommendation = false
  } catch (e) {
    const detail = e.response?.data?.detail || e.message
    // 重复添加的提示
    if (detail.includes('已存在') || detail.includes('duplicate')) {
      ElMessage.warning(`${name}(${code}) 已在自选股中`)
      const item = detailStrategy.value?.watchlist_suggestions?.find(i => i.code === code)
      if (item) item.is_new_recommendation = false
    } else {
      ElMessage.error('加入自选股失败：' + detail)
    }
  }
}

// P3: 策略历史回测表现
const strategyBacktestResults = ref(null)
const strategyBtLoading = ref(false)
const activeStrategyStock = ref('')

async function loadStrategyBacktest(stockCode, strategyName = 'macd') {
  if (!stockCode) return
  activeStrategyStock.value = stockCode
  strategyBtLoading.value = true
  strategyBacktestResults.value = null
  try {
    const res = await backtestApi.verify({ stock: stockCode, strategy: strategyName, days: 120 })
    if (res.status === 'success') {
      strategyBacktestResults.value = res.data
    }
  } catch (e) {
    console.error('策略回测加载失败:', e)
  } finally {
    strategyBtLoading.value = false
  }
}

function formatReturn(val) {
  if (val == null) return '--'
  const num = parseFloat(val)
  const sign = num >= 0 ? '+' : ''
  return sign + num.toFixed(2) + '%'
}

function getRatingType(rating) {
  const map = { '\u4F18\u79C0': 'success', '\u826F\u597D': '', '\u4E00\u822C': 'warning', '\u8F83\u5DEE': 'danger' }
  return map[rating] || 'info'
}

</script>

<style scoped>
/* 根容器：flex column 填满父容器（el-tab-pane） */
.strategy-center-section {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 16px;
}

/* AI策略操作栏 */
.strategy-actions-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px 16px;
  background: #fff;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0,0,0,0.08);
  border: 1px solid #ebeef5;
}

/* 最新策略摘要 */
.strategy-summary-card { flex-shrink: 0; margin-bottom: 12px; }
.strategy-summary-card :deep(.el-card__body) { padding: 12px 16px; }
.strategy-summary-card .summary-row { display: flex; justify-content: space-between; align-items: center; }
.summary-left { display: flex; align-items: center; gap: 10px; }
.summary-date { font-weight: bold; color: #303133; }

/* 历史策略 card：flex:1 占满剩余空间，列表内部独立滚动 */
.history-card {
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
.history-card .card-header {
  flex-shrink: 0;
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
}
.history-list-wrapper {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding: 12px 16px;
  min-height: 0;
}

/* 抽屉内样式（保留原样式） */
.strategy-content { padding: 10px 0; }
.strategy-section { margin-bottom: 20px; }
.strategy-section.no-margin { margin-bottom: 16px; }
.section-title { font-weight: bold; margin-bottom: 10px; color: #303133; }
.section-content { color: #606266; line-height: 1.6; }
.sentiment-badge { display: inline-block; padding: 4px 12px; border-radius: 4px; font-weight: bold; }
.sentiment-badge.bullish { background: #FDE2E2; color: #F56C6C; }
.sentiment-badge.bearish { background: #E1F3D8; color: #67C23A; }
.sentiment-badge.neutral { background: #F4F4F5; color: #909399; }
.sentiment-badge.small { font-size: 12px; padding: 2px 8px; }

/* 建议区域：左右两列 */
.suggestions-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.suggestion-grid { display: flex; flex-direction: column; gap: 8px; }
.suggestion-card { background: #F5F7FA; padding: 10px 12px; border-radius: 8px; }
.card-top-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
.badge-row { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; flex-wrap: wrap; }
.stock-code { font-weight: bold; color: #409EFF; font-size: 14px; }
.stock-name { color: #606266; font-size: 13px; }
.action-badge { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.action-badge.sell, .action-badge.reduce { background: #FDE2E2; color: #F56C6C; }
.action-badge.hold { background: #F4F4F5; color: #909399; }
.action-badge.add, .action-badge.buy { background: #E1F3D8; color: #67C23A; }
.action-badge.watch { background: #D9ECFF; color: #409EFF; }
.risk-badge { padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.risk-badge.low { background: #E1F3D8; color: #67C23A; }
.risk-badge.medium { background: #FAECD8; color: #E6A23C; }
.risk-badge.high { background: #FDE2E2; color: #F56C6C; }
.pos-type-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-left: auto; }
.pos-type-badge.short { background: #FDE2E2; color: #F56C6C; }
.pos-type-badge.mid { background: #FAECD8; color: #E6A23C; }
.pos-type-badge.long { background: #D9ECFF; color: #409EFF; }
.tech-summary { font-size: 12px; color: #909399; background: #F5F7FA; padding: 3px 8px; border-radius: 4px; margin-bottom: 6px; display: inline-block; }
.suggestion-reason { color: #606266; font-size: 13px; line-height: 1.5; margin-bottom: 4px; }
.suggestion-prices { color: #909399; font-size: 12px; display: flex; gap: 15px; flex-wrap: wrap; }
.price-pct { padding: 1px 6px; border-radius: 3px; background: #FDE2E2; color: #F56C6C; }
.price-pct.profit { background: #E1F3D8; color: #67C23A; }
.risk-warning { background: #FDF6EC; padding: 12px; border-radius: 8px; color: #E6A23C; display: flex; align-items: center; gap: 8px; }

/* 市场环境卡片（新增） */
.env-card { background: linear-gradient(135deg, #F0F9FF 0%, #E6F4FF 100%); padding: 12px; border-radius: 8px; border-left: 3px solid #409EFF; }
.env-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px; }
.env-item { display: flex; flex-direction: column; gap: 4px; }
.env-label { color: #909399; font-size: 12px; }
.env-value { font-weight: bold; color: #303133; font-size: 14px; }
.env-value.stage-bull { color: #F56C6C; }
.env-value.stage-bear { color: #67C23A; }
.env-value.stage-shock { color: #E6A23C; }

/* 决策依据卡片（新增） */
.indicators-card { background: #FAFAFA; padding: 12px; border-radius: 8px; border: 1px dashed #DCDFE6; margin-bottom: 16px; }
.indicators-collapse { margin-bottom: 16px; border: 1px dashed #DCDFE6; border-radius: 8px; background: #FAFAFA; }
.indicators-collapse :deep(.el-collapse-item__header) { padding: 0 12px; background: transparent; border-bottom: 1px dashed #DCDFE6; }
.indicators-collapse :deep(.el-collapse-item__content) { padding: 12px; background: transparent; }
.collapse-title { font-weight: bold; color: #606266; font-size: 14px; }
.indicators-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.indicator-item { background: #fff; padding: 10px; border-radius: 6px; border: 1px solid #EBEEF5; }
.indicator-label { color: #909399; font-size: 12px; margin-bottom: 6px; }
.indicator-value { color: #303133; font-size: 13px; line-height: 1.5; word-break: break-all; }
.indicator-value.pre-wrap { white-space: pre-wrap; max-height: 180px; overflow-y: auto; }
.sector-tag { margin: 2px; }

/* AI 推荐新增自选股标记 */
.new-rec-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; background: linear-gradient(135deg, #FF6B6B 0%, #EE5A24 100%); color: #fff; font-weight: bold; }
.new-rec-card { background: linear-gradient(135deg, #FFF5F5 0%, #FFE8E8 100%); border-left: 3px solid #FF6B6B; }

/* 建议采纳反馈按钮区 */
.feedback-row { margin-top: 8px; padding-top: 8px; border-top: 1px dashed #EBEEF5; display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap; }

/* 历史项新增徽章 */
.stage-badge { display: inline-block; padding: 4px 12px; border-radius: 4px; font-weight: bold; font-size: 12px; }
.stage-badge.small { font-size: 11px; padding: 2px 8px; }
.stage-badge.stage-bull { background: #FDE2E2; color: #F56C6C; }
.stage-badge.stage-bear { background: #E1F3D8; color: #67C23A; }
.stage-badge.stage-shock { background: #FAECD8; color: #E6A23C; }
.position-ratio-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; background: #F4F4F5; color: #606266; }

/* 历史列表项 */
.empty-history { text-align: center; color: #909399; padding: 40px 0; }
.history-list { display: flex; flex-direction: column; gap: 12px; }
.history-item {
  display: flex; align-items: center; gap: 15px; padding: 12px;
  background: #F5F7FA; border-radius: 8px; cursor: pointer; transition: background 0.2s;
}
.history-item:hover { background: #ECF5FF; }
.history-info { display: flex; align-items: center; gap: 10px; min-width: 250px; }
.history-date { font-weight: bold; color: #303133; }
.history-analysis { flex: 1; color: #606266; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.time-inputs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.time-row { display: flex; align-items: center; }
.time-group { width: 100%; }
.add-time-row { display: flex; gap: 8px; align-items: center; }

/* Responsive */
@media (max-width: 768px) {
  .strategy-center-section { padding: 8px; }

  /* AI策略操作栏移动端紧凑 */
  .strategy-actions-bar {
    flex-wrap: wrap;
    gap: 4px;
    padding: 6px 8px;
    margin-bottom: 8px;
  }
  .strategy-actions-bar .el-button { flex: 1; min-width: 0; font-size: 11px; padding: 6px 2px; }

  .history-list-wrapper { padding: 8px 10px; }
  .history-item { flex-direction: column; align-items: flex-start; gap: 8px; padding: 10px; }
  .history-info { min-width: auto; flex-wrap: wrap; }
  .history-analysis { white-space: normal; -webkit-line-clamp: 2; display: -webkit-box; -webkit-box-orient: vertical; }

  .suggestions-grid { grid-template-columns: 1fr; }
  .card-top-row { flex-wrap: wrap; }
  .badge-row { flex-wrap: wrap; }
}

@media (max-width: 480px) {
  .strategy-center-section { padding: 6px; }
  .strategy-actions-bar .el-button { font-size: 10px; padding: 5px 2px; }
}

/* P3: 策略历史回测表现样式 */
.bt-history-card { margin-top: 16px; }
.bt-stock-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.bt-stock-item { display: flex; justify-content: space-between; align-items: center; padding: 6px 12px; background: #f5f7fa; border-radius: 4px; font-size: 13px; }
.bt-stock-name { font-weight: 500; }
.bt-result-card { padding: 12px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px; color: #fff; }
.bt-result-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.bt-stock-label { font-weight: 600; font-size: 14px; }
.bt-metrics-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.bt-mini-metric { text-align: center; padding: 8px; background: rgba(255,255,255,0.15); border-radius: 6px; }
.bt-mini-label { display: block; font-size: 11px; opacity: 0.8; margin-bottom: 4px; }
.bt-mini-metric span:last-child { display: block; font-weight: 600; font-size: 13px; }
.bt-loading { text-align: center; padding: 20px; color: #909399; font-size: 13px; }

</style>
