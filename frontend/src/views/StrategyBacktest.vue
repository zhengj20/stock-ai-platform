<template>
  <div class="strategy-backtest">
    <div class="page-header-fixed">
      <h2 class="page-title"><el-icon><TrendCharts /></el-icon> 策略回测</h2>
    </div>
    <div class="content-scroll-area">
      <el-tabs v-model="activeTab" type="border-card" class="main-tabs">
        
        <!-- Tab 1: Smart Batch Backtest (default) -->
        <el-tab-pane label="智能批量回测" name="smart-batch">
          <div class="tab-pane-content">
            <el-card shadow="never" class="params-card flex-shrink-0">
              <template #header><span class="desktop-only">智能批量回测 — 从选股策略中一键获取股票池并回测</span><span class="mobile-only">智能批量回测</span></template>
              <div class="form-grid-compact">
                <div class="form-item-inline mobile-row-source-strategy">
                  <span class="inline-label desktop-only">股票来源</span>
                  <span class="inline-label mobile-only">来源</span>
                  <el-select v-model="smartBatchSource" style="width:160px;" size="small" @change="onSourceChange">
                    <el-option label="AI推荐股票" value="ai-pick" />
                    <el-option-group label="智能选股">
                      <el-option label="涨跌榜-涨停" value="limit-up" />
                      <el-option label="龙虎榜策略" value="dragon-strategy" />
                      <el-option label="主力资金排名" value="main-flow" />
                      <el-option label="量价配合分析" value="volprice-analysis" />
                      <el-option label="行业龙头" value="leader-industry" />
                      <el-option label="概念龙头" value="leader-concept" />
                      <el-option label="趋势突破" value="trend-breakout" />
                      <el-option label="低吸企稳" value="low-absorption" />
                      <el-option label="ML预测/技术评分" value="ml-predict" />
                      <el-option label="量价关系" value="volprice-divergence" />
                      <el-option label="组合选股-投票融合" value="combo-vote" />
                      <el-option label="组合选股-加权融合" value="combo-weight" />
                    </el-option-group>
                    <el-option-group label="其他来源">
                      <el-option label="自选股" value="watchlist" />
                    </el-option-group>
                  </el-select>
                </div>
                <div class="form-item-inline mobile-row-source-strategy">
                  <span class="inline-label">策略</span>
                  <el-radio-group v-model="smartBatchForm.singleStrategy" size="small" class="strategy-radios">
                    <el-radio-button value="macd">MACD</el-radio-button>
                    <el-radio-button value="kdj">KDJ</el-radio-button>
                    <el-radio-button value="rsi">RSI</el-radio-button>
                    <el-radio-button value="bollinger">布林带</el-radio-button>
                    <el-radio-button value="dualma">双均线</el-radio-button>
                  </el-radio-group>
                </div>
                <div class="form-item-inline mobile-row-date-action">
                  <span class="inline-label desktop-only">日期范围</span>
                  <span class="inline-label mobile-only">日期</span>
                  <el-date-picker v-model="smartBatchForm.start_date" type="date" placeholder="起始日" value-format="YYYY-MM-DD" style="width:120px;" size="small" />
                  <span style="margin:0 4px;color:#909399;">~</span>
                  <el-date-picker v-model="smartBatchForm.end_date" type="date" placeholder="结束日" value-format="YYYY-MM-DD" style="width:120px;" size="small" />
                </div>
                <div class="form-item-inline form-actions mobile-row-date-action">

                  <el-button type="primary" @click="runSmartBatchBacktest" :loading="smartBatchFetching || smartBatchLoading" :disabled="!smartBatchStocks.length && !smartBatchFetching" size="small">开始回测</el-button>
                </div>
              </div>
              <div v-if="smartBatchStocks.length > 0" class="stock-count-bar">
                <el-tag type="success" size="small" effect="plain">{{ smartBatchStocks.length }} 只股票已就绪</el-tag>
                <span class="source-label desktop-only">来源: {{ getSourceLabel() }}</span>
              </div>
            </el-card>
            <div v-if="smartBatchResults && smartBatchResults.length > 0" class="table-section">
              <template v-for="(result, idx) in smartBatchResults" :key="result.strategy">
                <div class="batch-summary flex-shrink-0">
                  <span class="summary-tag">{{ result.strategy?.toUpperCase() }} 策略</span>
                  <span class="summary-item desktop-only">周期: {{ result.data.period }}</span>
                  <span class="summary-item desktop-only">成功: {{ result.data.success_count }}/{{ result.data.total_stocks }}</span>
                </div>
              </template>
              <!-- 桌面端表格 -->
              <div class="table-scroll-wrapper" v-if="!isMobile">
                <el-table :data="smartBatchPaginatedData" border stripe size="small" class="result-table" height="100%" style="width:100%;">
                  <el-table-column type="index" label="#" width="50" align="center" fixed />
                  <el-table-column prop="stock" label="代码" width="80" align="center" />
                  <el-table-column prop="name" label="名称" width="120" show-overflow-tooltip><template #default="{ row }">{{ getSmartBatchName(row.stock) || row.stock }}</template></el-table-column>
                  <el-table-column label="总收益" width="100" align="center"><template #default="{ row }"><span :class="{ positive: row.total_return_pct >= 0, negative: row.total_return_pct < 0 }" style="font-weight:600">{{ formatReturn(row.total_return_pct) }}</span></template></el-table-column>
                  <el-table-column label="年化收益" width="100" align="center"><template #default="{ row }"><span :class="{ positive: row.annual_return_pct >= 0, negative: row.annual_return_pct < 0 }">{{ formatReturn(row.annual_return_pct) }}</span></template></el-table-column>
                  <el-table-column prop="sharpe_ratio" label="夏普比率" width="90" align="center" />
                  <el-table-column label="最大回撤" width="100" align="center"><template #default="{ row }"><span class="negative">{{ formatReturn(row.max_drawdown_pct) }}</span></template></el-table-column>
                  <el-table-column label="胜率" width="80" align="center"><template #default="{ row }">{{ (row.win_rate_pct || 0).toFixed(1) }}%</template></el-table-column>
                  <el-table-column prop="profit_factor" label="盈亏比" width="80" align="center" />
                  <el-table-column prop="total_trades" label="交易次数" width="90" align="center" />
                </el-table>
              </div>
              <!-- 移动端卡片 -->
              <div class="bt-mobile-list" v-else>
                <div v-for="(row, idx) in smartBatchPaginatedData" :key="'sb-'+row.stock+idx" class="m-card bt-result-card">
                  <div class="bt-card-top">
                    <div class="bt-rank">{{ idx + 1 }}</div>
                    <div class="bt-info">
                      <span class="bt-name">{{ getSmartBatchName(row.stock) || row.stock }}</span>
                      <span class="bt-code">{{ row.stock }}</span>
                    </div>
                    <div class="bt-return" :class="{ positive: row.total_return_pct >= 0, negative: row.total_return_pct < 0 }">{{ formatReturn(row.total_return_pct) }}</div>
                  </div>
                  <div class="bt-card-stats">
                    <span class="bt-stat"><span class="bt-label">年化</span><span :class="{ positive: row.annual_return_pct >= 0, negative: row.annual_return_pct < 0 }">{{ formatReturn(row.annual_return_pct) }}</span></span>
                    <span class="bt-stat"><span class="bt-label">夏普</span><span>{{ row.sharpe_ratio || '--' }}</span></span>
                    <span class="bt-stat"><span class="bt-label">回撤</span><span class="negative">{{ formatReturn(row.max_drawdown_pct) }}</span></span>
                    <span class="bt-stat"><span class="bt-label">胜率</span><span>{{ (row.win_rate_pct || 0).toFixed(1) }}%</span></span>
                  </div>
                </div>
              </div>
              <div class="pagination-wrapper">
                <el-pagination v-model:current-page="smartBatchPage.current" v-model:page-size="smartBatchPage.size" :page-sizes="[10, 20, 50]" :total="smartBatchResults[0].data.results.length" layout="total, sizes, prev, pager, next, jumper" background />
              </div>
            </div>
          </div>
        </el-tab-pane>
        <!-- Tab 2: Single Strategy Backtest -->
        <el-tab-pane label="单策略回测" name="single">
          <div class="tab-pane-content">
            <el-card shadow="never" class="params-card flex-shrink-0">
              <template #header><span>回测参数</span></template>
              <div class="form-grid-compact">
                <div class="form-item-inline">
                  <span class="inline-label">股票</span>
                  <el-autocomplete v-model="backtestParams.stockName" :fetch-suggestions="queryStockSuggestions" placeholder="代码或名称，如: 600519 / 茅台" @select="handleStockSelect" clearable style="width:200px;" size="small">
                    <template #default="{ item }"><span style="font-weight:600">{{ item.code }}</span><span style="color:#909399;margin-left:8px;">{{ item.name }}</span></template>
                  </el-autocomplete>
                </div>
                <div class="form-item-inline">
                  <span class="inline-label">策略</span>
                  <el-select v-model="backtestParams.strategy" style="width:120px;" size="small">
                    <el-option label="MACD" value="macd" /><el-option label="KDJ" value="kdj" /><el-option label="RSI" value="rsi" /><el-option label="布林带" value="bollinger" /><el-option label="双均线" value="dualma" />
                  </el-select>
                </div>
                <div class="form-item-inline">
                  <span class="inline-label">日期</span>
                  <el-date-picker v-model="backtestParams.start_date" type="date" placeholder="起始日" value-format="YYYY-MM-DD" style="width:120px;" size="small" />
                  <span style="margin:0 4px;color:#909399;">~</span>
                  <el-date-picker v-model="backtestParams.end_date" type="date" placeholder="结束日" value-format="YYYY-MM-DD" style="width:120px;" size="small" />
                </div>

                <div class="form-item-inline form-actions">
                  <el-button type="primary" @click="runBacktest" :loading="backtesting" size="small">{{ backtesting ? '回测中...' : '开始回测' }}</el-button>
                </div>
              </div>
            </el-card>
            <template v-if="backtestResult">
              <el-row :gutter="12" class="metrics-row flex-shrink-0">
                <el-col :span="3" v-for="(val, key) in coreMetrics" :key="key">
                  <div class="metric-card">
                    <div class="metric-label">{{ val.label }}</div>
                    <div class="metric-value" :class="val.class">{{ val.value }}</div>
                  </div>
                </el-col>
              </el-row>
              <el-card shadow="never" class="chart-card flex-shrink-0">
                <template #header><span>权益曲线 - {{ backtestResult.strategy }}</span></template>
                <div class="equity-chart" ref="equityChartRef"></div>
              </el-card>
            </template>
          </div>
        </el-tab-pane>

        <!-- Tab 3: Strategy Comparison -->
        <el-tab-pane label="策略对比" name="compare">
          <div class="tab-pane-content">
            <el-card shadow="never" class="params-card flex-shrink-0">
              <template #header><span>策略对比参数</span></template>
              <div class="form-grid-compact">
                <div class="form-item-inline">
                  <span class="inline-label">股票</span>
                  <el-autocomplete v-model="compareParams.stockName" :fetch-suggestions="queryStockSuggestions" placeholder="代码或名称，如: 600519 / 茅台" @select="(item) => { compareParams.stock = item.code; compareParams.stockName = item.code + ' ' + item.name }" clearable style="width:200px;" size="small">
                    <template #default="{ item }"><span style="font-weight:600">{{ item.code }}</span><span style="color:#909399;margin-left:8px;">{{ item.name }}</span></template>
                  </el-autocomplete>
                </div>
                <div class="form-item-inline">
                  <span class="inline-label">策略</span>
                  <el-select v-model="compareParams.strategies" multiple collapse-tags collapse-tags-tooltip placeholder="选择策略" style="width:160px;" size="small">
                    <el-option label="MACD" value="macd" />
                    <el-option label="KDJ" value="kdj" />
                    <el-option label="RSI" value="rsi" />
                    <el-option label="布林带" value="bollinger" />
                    <el-option label="双均线" value="dualma" />
                  </el-select>
                </div>
                <div class="form-item-inline">
                  <span class="inline-label">日期</span>
                  <el-date-picker v-model="compareParams.start_date" type="date" placeholder="起始日" value-format="YYYY-MM-DD" style="width:120px;" size="small" />
                  <span style="margin:0 4px;color:#909399;">~</span>
                  <el-date-picker v-model="compareParams.end_date" type="date" placeholder="结束日" value-format="YYYY-MM-DD" style="width:120px;" size="small" />
                </div>
                
                <div class="form-item-inline form-actions">
                  <el-button type="primary" @click="compareStrategies" :loading="comparing" size="small">{{ comparing ? '对比中...' : '开始对比' }}</el-button>
                </div>
              </div>
            </el-card>
            <template v-if="compareResults && compareResults.length > 0">
              <div class="table-section">
                <!-- 桌面端表格 -->
                <div class="table-scroll-wrapper" v-if="!isMobile">
                  <el-table :data="comparePaginatedData" border stripe size="small" class="result-table" height="100%" style="width:100%;">
                    <el-table-column prop="strategy" label="策略" width="90" align="center" fixed />
                    <el-table-column label="总收益" width="100" align="center"><template #default="{ row }"><span :class="{ positive: row.total_return_pct >= 0, negative: row.total_return_pct < 0 }" style="font-weight:600">{{ formatReturn(row.total_return_pct) }}</span></template></el-table-column>
                    <el-table-column label="年化收益" width="100" align="center"><template #default="{ row }"><span :class="{ positive: row.annual_return_pct >= 0, negative: row.annual_return_pct < 0 }">{{ formatReturn(row.annual_return_pct) }}</span></template></el-table-column>
                    <el-table-column prop="sharpe_ratio" label="夏普比率" width="90" align="center" />
                    <el-table-column label="最大回撤" width="100" align="center"><template #default="{ row }"><span class="negative">{{ formatReturn(row.max_drawdown_pct) }}</span></template></el-table-column>
                    <el-table-column label="胜率" width="80" align="center"><template #default="{ row }">{{ (row.win_rate_pct || 0).toFixed(1) }}%</template></el-table-column>
                    <el-table-column prop="profit_factor" label="盈亏比" width="80" align="center" />
                    <el-table-column prop="total_trades" label="交易次数" width="90" align="center" />
                  </el-table>
                </div>
                <!-- 移动端卡片 -->
                <div class="bt-mobile-list" v-else>
                  <div v-for="(row, idx) in comparePaginatedData" :key="'cmp-'+row.strategy+idx" class="m-card bt-result-card">
                    <div class="bt-card-top">
                      <el-tag type="primary" effect="plain" size="small">{{ row.strategy?.toUpperCase() }}</el-tag>
                      <div class="bt-info">
                        <span class="bt-name">{{ compareParams.stockName || compareParams.stock }}</span>
                      </div>
                      <div class="bt-return" :class="{ positive: row.total_return_pct >= 0, negative: row.total_return_pct < 0 }">{{ formatReturn(row.total_return_pct) }}</div>
                    </div>
                    <div class="bt-card-stats">
                      <span class="bt-stat"><span class="bt-label">年化</span><span :class="{ positive: row.annual_return_pct >= 0, negative: row.annual_return_pct < 0 }">{{ formatReturn(row.annual_return_pct) }}</span></span>
                      <span class="bt-stat"><span class="bt-label">夏普</span><span>{{ row.sharpe_ratio || '--' }}</span></span>
                      <span class="bt-stat"><span class="bt-label">回撤</span><span class="negative">{{ formatReturn(row.max_drawdown_pct) }}</span></span>
                      <span class="bt-stat"><span class="bt-label">胜率</span><span>{{ (row.win_rate_pct || 0).toFixed(1) }}%</span></span>
                    </div>
                  </div>
                </div>
                <div class="pagination-wrapper">
                  <el-pagination v-model:current-page="comparePage.current" v-model:page-size="comparePage.size" :page-sizes="[10, 20, 50]" :total="compareResults.length" layout="total, sizes, prev, pager, next, jumper" background />
                </div>
              </div>
            </template>
          </div>
        </el-tab-pane>

        <!-- Tab 4: Batch Backtest -->
        <el-tab-pane label="批量回测" name="batch">
          <div class="tab-pane-content">
            <el-card shadow="never" class="params-card flex-shrink-0">
              <template #header><span>批量回测 — 手动输入多只股票</span></template>
              <div class="form-grid-compact">
                <div class="form-item-inline" style="flex:1;">
                  <span class="inline-label">股票代码</span>
                  <el-input v-model="batchForm.stocks" placeholder="多个代码用逗号分隔，如: 600519,000858,300750" size="small" style="flex:1;" clearable />
                </div>
                <div class="form-item-inline">
                  <span class="inline-label">策略</span>
                  <el-select v-model="batchForm.strategy" style="width:120px;" size="small">
                    <el-option label="MACD" value="macd" /><el-option label="KDJ" value="kdj" /><el-option label="RSI" value="rsi" /><el-option label="布林带" value="bollinger" /><el-option label="双均线" value="dualma" />
                  </el-select>
                </div>
                <div class="form-item-inline">
                  <span class="inline-label">日期</span>
                  <el-date-picker v-model="batchForm.start_date" type="date" placeholder="起始日" value-format="YYYY-MM-DD" style="width:120px;" size="small" />
                  <span style="margin:0 4px;color:#909399;">~</span>
                  <el-date-picker v-model="batchForm.end_date" type="date" placeholder="结束日" value-format="YYYY-MM-DD" style="width:120px;" size="small" />
                </div>
                
                <div class="form-item-inline form-actions">
                  <el-button type="primary" @click="runBatchBacktest" :loading="batchLoading" size="small">{{ batchLoading ? '回测中...' : '开始回测' }}</el-button>
                </div>
              </div>
            </el-card>
            <template v-if="batchResults">
              <div class="table-section">
                <div class="batch-summary flex-shrink-0">
                  <span class="summary-item desktop-only">周期: {{ batchResults.period }}</span>
                  <span class="summary-item desktop-only">成功: {{ batchResults.success_count }}/{{ batchResults.total_stocks }}</span>
                </div>
                <!-- 桌面端表格 -->
                <div class="table-scroll-wrapper" v-if="!isMobile">
                  <el-table :data="batchPaginatedData" border stripe size="small" class="result-table" height="100%" style="width:100%;">
                    <el-table-column type="index" label="#" width="50" align="center" fixed />
                    <el-table-column prop="stock" label="代码" width="80" align="center" />
                    <el-table-column label="总收益" width="100" align="center"><template #default="{ row }"><span :class="{ positive: row.total_return_pct >= 0, negative: row.total_return_pct < 0 }" style="font-weight:600">{{ formatReturn(row.total_return_pct) }}</span></template></el-table-column>
                    <el-table-column label="年化收益" width="100" align="center"><template #default="{ row }"><span :class="{ positive: row.annual_return_pct >= 0, negative: row.annual_return_pct < 0 }">{{ formatReturn(row.annual_return_pct) }}</span></template></el-table-column>
                    <el-table-column prop="sharpe_ratio" label="夏普比率" width="90" align="center" />
                    <el-table-column label="最大回撤" width="100" align="center"><template #default="{ row }"><span class="negative">{{ formatReturn(row.max_drawdown_pct) }}</span></template></el-table-column>
                    <el-table-column label="胜率" width="80" align="center"><template #default="{ row }">{{ (row.win_rate_pct || 0).toFixed(1) }}%</template></el-table-column>
                    <el-table-column prop="profit_factor" label="盈亏比" width="80" align="center" />
                    <el-table-column prop="total_trades" label="交易次数" width="90" align="center" />
                  </el-table>
                </div>
                <!-- 移动端卡片 -->
                <div class="bt-mobile-list" v-else>
                  <div v-for="(row, idx) in batchPaginatedData" :key="'batch-'+row.stock+idx" class="m-card bt-result-card">
                    <div class="bt-card-top">
                      <div class="bt-rank">{{ idx + 1 }}</div>
                      <div class="bt-info">
                        <span class="bt-name">{{ row.name || row.stock }}</span>
                        <span class="bt-code">{{ row.stock }}</span>
                      </div>
                      <div class="bt-return" :class="{ positive: row.total_return_pct >= 0, negative: row.total_return_pct < 0 }">{{ formatReturn(row.total_return_pct) }}</div>
                    </div>
                    <div class="bt-card-stats">
                      <span class="bt-stat"><span class="bt-label">年化</span><span :class="{ positive: row.annual_return_pct >= 0, negative: row.annual_return_pct < 0 }">{{ formatReturn(row.annual_return_pct) }}</span></span>
                      <span class="bt-stat"><span class="bt-label">夏普</span><span>{{ row.sharpe_ratio || '--' }}</span></span>
                      <span class="bt-stat"><span class="bt-label">回撤</span><span class="negative">{{ formatReturn(row.max_drawdown_pct) }}</span></span>
                      <span class="bt-stat"><span class="bt-label">胜率</span><span>{{ (row.win_rate_pct || 0).toFixed(1) }}%</span></span>
                    </div>
                  </div>
                </div>
                <div class="pagination-wrapper">
                  <el-pagination v-model:current-page="batchPage.current" v-model:page-size="batchPage.size" :page-sizes="[10, 20, 50]" :total="batchResults.results.length" layout="total, sizes, prev, pager, next, jumper" background />
                </div>
              </div>
            </template>
          </div>
        </el-tab-pane>

      </el-tabs>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, nextTick, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { TrendCharts } from '@element-plus/icons-vue'
import { backtestApi, aiStockPickApi, strategyApi, watchlistApi, stockApi } from '@/api'

const activeTab = ref('smart-batch')
const backtesting = ref(false)
const comparing = ref(false)
const equityChartRef = ref(null)
const isMobile = ref(window.innerWidth < 768)
const onResize = () => {
  isMobile.value = window.innerWidth < 768
  if (backtestResult.value?.equity_curve) drawEquityChart()
}
window.addEventListener('resize', onResize)

// Pagination state for each tab's results
const smartBatchPage = reactive({ current: 1, size: 10 })
const comparePage = reactive({ current: 1, size: 10 })
const batchPage = reactive({ current: 1, size: 10 })

// Computed paginated data
const smartBatchPaginatedData = computed(() => {
  if (!smartBatchResults.value?.[0]?.data?.results) return []
  const all = smartBatchResults.value[0].data.results
  const start = (smartBatchPage.current - 1) * smartBatchPage.size
  return all.slice(start, start + smartBatchPage.size)
})

const comparePaginatedData = computed(() => {
  if (!compareResults.value) return []
  const start = (comparePage.current - 1) * comparePage.size
  return compareResults.value.slice(start, start + comparePage.size)
})

const batchPaginatedData = computed(() => {
  if (!batchResults.value?.results) return []
  const all = batchResults.value.results
  const start = (batchPage.current - 1) * batchPage.size
  return all.slice(start, start + batchPage.size)
})

const _setDefaults = () => {
  const today = new Date()
  return {
    start_date: new Date(today.getTime() - 365 * 86400000).toISOString().slice(0, 10),
    end_date: today.toISOString().slice(0, 10),
  }
}
const _defaults = _setDefaults()

const _checkAuthError = (e) => {
  if (e?.response?.status === 401 || e?.message?.includes('登录')) {
    ElMessage.warning('请先登录后再使用回测功能')
    return true
  }
  return false
}

// ========== Single backtest ==========
const backtestParams = reactive({
  stockName: '',
  stock: '600519',
  strategy: 'macd',
  start_date: _defaults.start_date,
  end_date: _defaults.end_date,
  initial_capital: 1000000,
  commission_rate: 0.001,
  slippage_rate: 0.001,
})

const backtestResult = ref(null)

const coreMetrics = computed(() => {
  if (!backtestResult.value) return {}
  const r = backtestResult.value
  return {
    totalReturn: { label: '总收益率', value: r.total_return, class: parseFloat(r.total_return) >= 0 ? 'positive' : 'negative' },
    annualReturn: { label: '年化收益', value: r.annual_return, class: parseFloat(r.annual_return) >= 0 ? 'positive' : 'negative' },
    sharpe: { label: '夏普比率', value: r.sharpe_ratio, class: '' },
    sortino: { label: '索提诺比率', value: r.sortino_ratio, class: '' },
    maxDD: { label: '最大回撤', value: r.max_drawdown, class: 'negative' },
    winRate: { label: '胜率', value: r.win_rate, class: '' },
    trades: { label: '交易次数', value: String(r.total_trades), class: '' },
    avgHold: { label: '平均持仓', value: `${Math.round(r.avg_holding_days)}天`, class: '' },
  }
})

const runBacktest = async () => {
  if (!backtestParams.stock || !backtestParams.strategy) { ElMessage.warning('请填写股票和策略'); return }
  backtesting.value = true
  try {
    const res = await backtestApi.run({ stock: backtestParams.stock, strategy: backtestParams.strategy, start_date: backtestParams.start_date, end_date: backtestParams.end_date, initial_capital: backtestParams.initial_capital, commission_rate: backtestParams.commission_rate, slippage_rate: backtestParams.slippage_rate })
    console.log('[回测] API响应:', JSON.stringify(res).slice(0, 200))
    if (res.status === 'success') {
      console.log('[回测] res.data.trades:', res.data?.trades)
      console.log('[回测] trades类型:', typeof res.data?.trades, Array.isArray(res.data?.trades), res.data?.trades?.length)
      backtestResult.value = res.data; ElMessage.success('回测完成'); nextTick(() => drawEquityChart())
    } else {
      console.warn('[回测] 状态非success:', res.status, res.message)
    }
  } catch (e) { if (_checkAuthError(e)) return; ElMessage.error('回测失败: ' + (e.response?.data?.detail || e.message || '')) }
  finally { backtesting.value = false }
}

// ========== Strategy comparison ==========
const compareParams = reactive({
  stockName: '',
  stock: '600519',
  strategies: ['macd', 'kdj', 'rsi'],
  start_date: _defaults.start_date,
  end_date: _defaults.end_date,
  initial_capital: 1000000,
})

const compareResults = ref([])

const compareStrategies = async () => {
  if (!compareParams.stock || !compareParams.strategies.length) { ElMessage.warning('请填写股票和策略'); return }
  comparing.value = true
  try {
    const res = await backtestApi.compare({ stock: compareParams.stock, strategies: compareParams.strategies, start_date: compareParams.start_date, end_date: compareParams.end_date, initial_capital: compareParams.initial_capital })
    if (res.status === 'success') { compareResults.value = res.data.sort((a, b) => parseFloat(b.sharpe_ratio) - parseFloat(a.sharpe_ratio)); ElMessage.success('对比完成') }
  } catch (e) { if (_checkAuthError(e)) return; ElMessage.error('对比失败: ' + (e.response?.data?.detail || e.message || '')) }
  finally { comparing.value = false }
}

// ========== Batch backtest ==========
const batchLoading = ref(false)
const batchResults = ref(null)
const batchForm = reactive({ stocks: '', strategy: 'macd', start_date: _defaults.start_date, end_date: _defaults.end_date, initial_capital: 1000000.0 })

async function runBatchBacktest() {
  const stockList = batchForm.stocks.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean)
  if (stockList.length === 0) { ElMessage.warning('请输入至少一个股票代码'); return }
  if (stockList.length > 50) { ElMessage.warning('最多支持50只股票同时回测'); return }
  batchLoading.value = true; batchResults.value = null
  try {
    const res = await backtestApi.batch({ stocks: stockList, strategy: batchForm.strategy, start_date: batchForm.start_date, end_date: batchForm.end_date, initial_capital: batchForm.initial_capital })
    if (res.status === 'success') { batchResults.value = res.data; ElMessage.success('批量回测完成，成功 ' + res.data.success_count + ' 只') }
  } catch (e) { if (_checkAuthError(e)) return; ElMessage.error('批量回测失败: ' + (e.message || '')) }
  finally { batchLoading.value = false }
}

// ========== Smart batch backtest ==========
const smartBatchSource = ref('ai-pick')
const smartBatchStocks = ref([])
const smartBatchLoading = ref(false)
const smartBatchFetching = ref(false)
const smartBatchResults = ref([])
const activeResultTab = ref('0')

const smartBatchForm = reactive({ singleStrategy: 'macd', start_date: _defaults.start_date, end_date: _defaults.end_date, initial_capital: 1000000.0 })

const queryStockSuggestions = (query, cb) => {
  if (!query || query.length < 1) { cb([]); return }
  stockApi.suggest(query).then(res => { const list = Array.isArray(res) ? res : []; cb(list.map(s => ({ code: s.code || s.f12, name: s.name || s.f14 })).filter(s => s.code)) }).catch(() => cb([]))
}

const handleStockSelect = (item) => { backtestParams.stock = item.code; backtestParams.stockName = item.code + ' ' + item.name }

function formatReturn(val) { if (val == null) return '--'; const num = parseFloat(val); const sign = num >= 0 ? '+' : ''; return sign + num.toFixed(2) + '%' }

function onSourceChange() {
  if (smartBatchFetching.value) return
  smartBatchResults.value = []
  fetchSmartBatchStocks()
}

async function fetchSmartBatchStocks() {
  smartBatchFetching.value = true; smartBatchStocks.value = []; smartBatchResults.value = []
  try {
    const source = smartBatchSource.value
    const _extractStocks = (res, limit) => {
      if (!res || res?.error) return []
      let stocks = res?.stocks || res?.combined_stocks || res?.todayList || res?.gainers || res?.data || res?.picks || res?.signals || []
      // Handle nested sector structure (leader picks returns sectors with top_leaders)
      if (!Array.isArray(stocks) && res?.sectors && Array.isArray(res.sectors)) {
        stocks = []
        for (const sec of res.sectors) {
          if (sec?.top_leaders && Array.isArray(sec.top_leaders)) {
            for (const leader of sec.top_leaders) {
              stocks.push(leader)
            }
          }
        }
      }
      if (!Array.isArray(stocks)) stocks = []
      const mapped = stocks.map(s => ({ code: s.code || s.c || s.stock_code || '', name: s.name || s.n || s.stock_name || '' })).filter(s => s.code)
      return limit ? mapped.slice(0, limit) : mapped
    }
    
    if (source === 'ai-pick') {
      const latest = await aiStockPickApi.getLatest()
      if (latest?.picks_data) {
        const data = typeof latest.picks_data === 'string' ? JSON.parse(latest.picks_data) : latest.picks_data
        smartBatchStocks.value = [...(data.short_term || []), ...(data.long_term || [])].map(s => ({ code: s.code, name: s.name }))
      } else { ElMessage.warning('暂无AI推荐数据'); return }
    } else if (source === 'limit-up') {
      const res = await strategyApi.getDragonToday(false)
      smartBatchStocks.value = _extractStocks(res, 20)
    } else if (source === 'dragon-strategy') {
      const res = await strategyApi.getDragonStrategy('all', false, 30)
      smartBatchStocks.value = _extractStocks(res, 20)
    } else if (source === 'main-flow') {
      try { const res = await strategyApi.getCapitalFlowPicks(30); smartBatchStocks.value = _extractStocks(res, 20) }
      catch { const res = await strategyApi.getDragonCapitalFlow(false); smartBatchStocks.value = _extractStocks(res, 20) }
    } else if (source === 'volprice-analysis') {
      try { const res = await strategyApi.getVolumePriceDivergence(30); smartBatchStocks.value = _extractStocks(res, 20) }
      catch { const res = await strategyApi.getDragonSeatDetail(false); smartBatchStocks.value = _extractStocks(res, 20) }
    } else if (source === 'leader-industry') {
      try { const res = await strategyApi.getLeaderPicks('industry', 3, 10); smartBatchStocks.value = _extractStocks(res, 30) }
      catch { const res = await strategyApi.getDragonSectorAnalysis(false); smartBatchStocks.value = _extractStocks(res, 20) }
    } else if (source === 'leader-concept') {
      try { const res = await strategyApi.getLeaderPicks('concept', 3, 10); smartBatchStocks.value = _extractStocks(res, 30) }
      catch { const res = await strategyApi.getDragonSectorAnalysis(false); smartBatchStocks.value = _extractStocks(res, 20) }
    } else if (source === 'trend-breakout') {
      try { const res = await strategyApi.getMultiFactorPicks(30); smartBatchStocks.value = _extractStocks(res, 20) }
      catch { const res = await strategyApi.getDragonConsecutive(5); smartBatchStocks.value = _extractStocks(res, 20) }
    } else if (source === 'low-absorption') {
      try { const res = await strategyApi.getLowAbsorptionPicks(30); smartBatchStocks.value = _extractStocks(res, 20) }
      catch { const res = await strategyApi.getDragonNextDayPerformance(false); smartBatchStocks.value = _extractStocks(res, 20) }
    } else if (source === 'ml-predict') {
      try { const res = await strategyApi.predictStocks(30); smartBatchStocks.value = _extractStocks(res, 20) }
      catch { smartBatchStocks.value = [] }
      if (smartBatchStocks.value.length === 0) {
        try { const res = await strategyApi.getMultiFactorPicks(30); smartBatchStocks.value = _extractStocks(res, 20) }
        catch { ElMessage.warning('ML预测/技术评分暂无数据'); return }
      }
    } else if (source === 'volprice-divergence') {
      try { const res = await strategyApi.getVolumePriceDivergence(30); smartBatchStocks.value = _extractStocks(res, 20) }
      catch { const res = await strategyApi.getDragonStrategy('all', false, 30); smartBatchStocks.value = _extractStocks(res, 20) }
    } else if (source === 'combo-vote') {
      try { const res = await strategyApi.getStrategyCombo(30, 'vote'); smartBatchStocks.value = _extractStocks(res, 20) }
      catch { const res = await strategyApi.getDragonStrategy('all', false, 30); smartBatchStocks.value = _extractStocks(res, 20) }
    } else if (source === 'combo-weight') {
      try { const res = await strategyApi.getStrategyCombo(30, 'weight'); smartBatchStocks.value = _extractStocks(res, 20) }
      catch { const res = await strategyApi.getDragonStrategy('all', false, 30); smartBatchStocks.value = _extractStocks(res, 20) }
    } else if (source === 'watchlist') {
      const res = await watchlistApi.getMyWatchlist()
      let stocks = res?.stocks || res?.data || []
      if (!Array.isArray(stocks)) stocks = []
      smartBatchStocks.value = stocks.map(s => ({ code: s.stock_code || s.code, name: s.stock_name || s.name }))
    }
    
    if (smartBatchStocks.value.length === 0) { ElMessage.warning('该来源暂无股票数据，请切换其他来源或刷新页面') }
    else { ElMessage.success('已加载 ' + smartBatchStocks.value.length + ' 只股票') }
  } catch (e) { if (_checkAuthError(e)) return; ElMessage.error('获取股票失败: ' + (e.message || '')) }
  finally { smartBatchFetching.value = false }
}

async function runSmartBatchBacktest() {
  if (!smartBatchStocks.value.length) { ElMessage.warning('请先加载股票'); return }
  const strat = smartBatchForm.singleStrategy
  if (!strat) { ElMessage.warning('请选择策略'); return }
  smartBatchLoading.value = true; smartBatchResults.value = []
  try {
    const stockList = smartBatchStocks.value.map(s => s.code)
    const res = await backtestApi.batch({ stocks: stockList, strategy: strat, start_date: smartBatchForm.start_date, end_date: smartBatchForm.end_date, initial_capital: smartBatchForm.initial_capital })
    if (res.status === 'success') {
      const stratLabels = { macd: 'MACD', kdj: 'KDJ', rsi: 'RSI', bollinger: '布林带', dualma: '双均线' }
      smartBatchResults.value = [{ strategy: stratLabels[strat] || strat, data: res.data }]
      activeResultTab.value = '0'
      ElMessage.success('批量回测完成')
    }
  } catch (e) { if (_checkAuthError(e)) return; ElMessage.error('批量回测失败: ' + (e.message || '')) }
  finally { smartBatchLoading.value = false }
}

function getSmartBatchName(code) { const found = smartBatchStocks.value.find(s => s.code === code); return found ? found.name : null }

function getSourceLabel() {
  const map = { 'ai-pick': 'AI推荐股票', 'limit-up': '涨跌榜-涨停', 'dragon-strategy': '龙虎榜策略', 'main-flow': '主力资金排名', 'volprice-analysis': '量价配合分析', 'leader-industry': '行业龙头', 'leader-concept': '概念龙头', 'trend-breakout': '趋势突破', 'low-absorption': '低吸企稳', 'ml-predict': 'ML预测/技术评分', 'volprice-divergence': '量价关系', 'combo-vote': '组合选股-投票融合', 'combo-weight': '组合选股-加权融合', 'watchlist': '自选股' }
  return map[smartBatchSource.value] || smartBatchSource.value
}

// Equity chart drawing
const drawEquityChart = () => {
  if (!equityChartRef.value || !backtestResult.value?.equity_curve) return
  const container = equityChartRef.value, data = backtestResult.value.equity_curve
  if (data.length < 2) return
  const width = container.clientWidth || 800
  const height = width < 600 ? 180 : 300
  const padding = { top: 20, right: 60, bottom: 40, left: 70 }
  const chartW = width - padding.left - padding.right, chartH = height - padding.top - padding.bottom
  const equities = data.map(d => d.equity)
  const minEq = Math.min(...equities) * 0.98, maxEq = Math.max(...equities) * 1.02, range = maxEq - minEq || 1
  const points = data.map((d, i) => ({ x: padding.left + (i / (data.length - 1)) * chartW, y: padding.top + chartH - ((d.equity - minEq) / range) * chartH }))
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
  const areaD = pathD + ` L${points[points.length - 1].x},${padding.top + chartH} L${points[0].x},${padding.top + chartH} Z`
  const lastPoint = points[points.length - 1], lineColor = lastPoint.equity >= data[0].equity ? '#f56c6c' : '#67c23a', gradientId = 'eqGrad_' + Date.now()
  const yTicks = []
  for (let i = 0; i <= 4; i++) { const val = minEq + (i / 4) * range; yTicks.push({ y: padding.top + chartH - (i / 4) * chartH, label: '¥' + (val / 10000).toFixed(0) + '万' }) }
  const xTicks = [], step = Math.max(1, Math.floor(data.length / 6))
  for (let i = 0; i < data.length; i += step) { xTicks.push({ x: padding.left + (i / (data.length - 1)) * chartW, label: data[i].date.slice(5) }) }
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" style="width:100%; height:${height}px;"><defs><linearGradient id="${gradientId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${lineColor}" stop-opacity="0.3"/><stop offset="100%" stop-color="${lineColor}" stop-opacity="0.02"/></linearGradient></defs>${yTicks.map(t => `<line x1="${padding.left}" y1="${t.y}" x2="${width - padding.right}" y2="${t.y}" stroke="#eee" stroke-width="1"/><text x="${padding.left - 8}" y="${t.y + 4}" text-anchor="end" font-size="11" fill="#909399">${t.label}</text>`).join('')}${xTicks.map(t => `<text x="${t.x}" y="${height - 8}" text-anchor="middle" font-size="11" fill="#909399">${t.label}</text>`).join('')}<path d="${areaD}" fill="url(#${gradientId})"/><path d="${pathD}" fill="none" stroke="${lineColor}" stroke-width="2"/><circle cx="${points[points.length - 1].x}" cy="${points[points.length - 1].y}" r="4" fill="${lineColor}"/><text x="${points[points.length - 1].x + 8}" y="${points[points.length - 1].y + 4}" font-size="12" fill="${lineColor}" font-weight="bold">¥${(points[points.length - 1].equity / 10000).toFixed(2)}万</text></svg>`
}

// Auto-load default stocks on mount
onMounted(() => {
  fetchSmartBatchStocks()
})

const route = useRoute()
if (route.query.stock) backtestParams.stock = route.query.stock
if (route.query.strategy) backtestParams.strategy = route.query.strategy
if (route.query.start_date) backtestParams.start_date = route.query.start_date
if (route.query.end_date) backtestParams.end_date = route.query.end_date

</script>

<style scoped>
/* Root layout - same pattern as SmartStockPick */
.strategy-backtest {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  padding: 12px;
  background: #f0f2f5;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.page-header-fixed {
  flex-shrink: 0;
  padding: 8px 12px;
  background: #fff;
  border-radius: 6px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-title {
  margin: 0;
  font-size: 16px;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #303133;
}

/* Content scroll area — flex chain between root and tabs */
.content-scroll-area {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Tabs layout - same pattern as SmartStockPick */
.strategy-backtest .el-tabs {
  flex: 1;
  display: flex !important;
  flex-direction: column !important;
  min-height: 0;
  overflow: hidden;
}

.main-tabs :deep(.el-tabs__header) { flex-shrink: 0; }

.main-tabs :deep(.el-tabs__content) {
  flex: 1;
  display: flex !important;
  flex-direction: column !important;
  overflow: visible !important;
  min-height: 0;
  padding: 0 !important;
}

/* Only apply flex to active tab panes - critical for tab switching */
.main-tabs :deep(.el-tabs__content > .el-tab-pane) { display: none; }
.main-tabs :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) {
  display: flex !important;
  flex-direction: column !important;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* Tab pane content - scrollable when content exceeds height */
.tab-pane-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  padding: 8px 4px;
}

/* Params card is fixed (flex-shrink: 0) */
.params-card {
  flex-shrink: 0;
  margin-bottom: 12px;
}

.el-card__header {
  padding: 8px 12px !important;
  font-size: 13px;
}

.el-card__body {
  padding: 10px 12px !important;
}

/* Table section — flex:1 自适应高度，overflow:hidden，分页在下方固定 */
.table-section {
  width: 100%;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  margin-top: 12px;
}

.table-scroll-wrapper {
  flex: 1;
  min-height: 0;
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Table itself — height="100%" 让表格填满父容器，body 内部滚动，表头自动固定 */
.table-section :deep(.el-table),
.table-scroll-wrapper :deep(.el-table) {
  width: 100% !important;
  height: 100% !important;
}

.table-section :deep(.el-table__inner-wrapper),
.table-scroll-wrapper :deep(.el-table__inner-wrapper) {
  height: 100% !important;
  display: flex;
  flex-direction: column;
}

.table-section :deep(.el-table__body-wrapper),
.table-scroll-wrapper :deep(.el-table__body-wrapper) {
  flex: 1;
  min-height: 0;
  overflow-y: auto !important;
  overflow-x: auto !important;
}

/* Pagination — 固定在表格下方，始终可见 */
.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
  padding: 4px 0;
  flex-shrink: 0;
}

.pagination-wrapper :deep(.el-pagination) { font-size: 13px; }
.pagination-wrapper :deep(.el-pagination.is-background .el-pager li:not(.is-disabled).is-active) { background-color: #409eff; }

/* Compact form layout */
.form-grid-compact {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 20px;
  align-items: center;
}

.form-item-inline {
  display: flex;
  align-items: center;
  gap: 8px;
}

.inline-label {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
  min-width: 56px;
  text-align: right;
}

.form-actions {
  margin-left: auto;
}

/* Stock count bar */
.stock-count-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #f0f2f5;
}

.source-label {
  font-size: 12px;
  color: #909399;
}

/* Strategy radio buttons */
.strategy-radios :deep(.el-radio-button__inner),
.strategy-radios :deep(.el-checkbox-button__inner) {
  padding: 7px 12px;
  font-size: 12px;
}

/* Metrics row (single backtest tab) */
.metrics-row {
  flex-shrink: 0;
  margin-bottom: 12px;
}

.metric-card {
  text-align: center;
  padding: 8px 4px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #ebeef5;
}

.metric-label {
  font-size: 11px;
  color: #909399;
  margin-bottom: 2px;
}

.metric-value {
  font-size: 14px;
  font-weight: bold;
  color: #303133;
}

/* Chart area — compact height */
.chart-card {
  flex-shrink: 0;
  margin-bottom: 12px;
}

.chart-card .el-card__body {
  padding: 6px !important;
}

.equity-chart {
  min-height: 180px;
}

/* Table header background */
.table-section :deep(.el-table__header-wrapper th.el-table__cell),
.table-scroll-wrapper :deep(.el-table__header-wrapper th.el-table__cell) {
  background-color: #f5f7fa !important;
}

:deep(.el-table) { --el-table-header-bg-color: #f5f7fa; --el-table-header-text-color: #303133; }
:deep(.el-table th.el-table__cell) { font-weight: 600; background-color: #f5f7fa; white-space: nowrap !important; }
:deep(.el-table td.el-table__cell .cell) { white-space: nowrap !important; overflow: hidden; text-overflow: ellipsis; }

/* 桌面端：固定表格布局，确保表头表体列宽一致 */
.table-section :deep(.el-table__header-wrapper),
.table-section :deep(.el-table__body-wrapper),
.table-scroll-wrapper :deep(.el-table__header-wrapper),
.table-scroll-wrapper :deep(.el-table__body-wrapper) {
  width: 100% !important;
  box-sizing: border-box !important;
}
.table-section :deep(table),
.table-scroll-wrapper :deep(table) {
  table-layout: fixed !important;
  width: 100% !important;
}
/* 确保列宽不被内容撑开 */
.table-section :deep(.el-table__header-wrapper .el-table__cell),
.table-section :deep(.el-table__body-wrapper .el-table__cell),
.table-scroll-wrapper :deep(.el-table__header-wrapper .el-table__cell),
.table-scroll-wrapper :deep(.el-table__body-wrapper .el-table__cell) {
  box-sizing: border-box !important;
  overflow: hidden !important;
}

/* Batch summary */
.batch-summary {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12px;
  color: #909399;
  flex-wrap: wrap;
}

.summary-item, .summary-tag {
  background: #f5f7fa;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 12px;
}

/* Colors */
.positive { color: #f56c6c !important; font-weight: 600; }
.negative { color: #67c23a !important; }

.drawer-backtest-content { padding: 0 8px; }

/* Desktop/mobile visibility — defaults for desktop */
.desktop-only { display: inline !important; }
.mobile-only { display: none !important; }

/* Mobile responsive — follow SmartStockPick pattern: keep flex chain intact */
@media (max-width: 768px) {
  .strategy-backtest {
    position: absolute;
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    padding: 0 !important;
    background: var(--m-bg, #f5f7fa) !important;
  }

  /* 移动端 header 已有标题，隐藏页面内部重复标题 */
  .page-header-fixed { display: none !important; }

  .page-title { display: none !important; }

  /* Tabs — 去除 border-card 样式，节省垂直空间 */
  :deep(.el-tabs--border-card) { border: none !important; }
  :deep(.el-tabs--border-card > .el-tabs__header) { background: var(--m-surface, #fff) !important; border: none !important; margin-bottom: 0; box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important; }
  :deep(.el-tabs__header) { overflow-x: auto; -webkit-overflow-scrolling: touch; white-space: nowrap; scrollbar-width: none; }
  :deep(.el-tabs__header::-webkit-scrollbar) { display: none; }
  :deep(.el-tabs__nav-wrap) { clear: none !important; }
  :deep(.el-tabs__nav-wrap::after) { height: 0 !important; }
  :deep(.el-tabs__nav-scroll) { padding: 0 8px; }
  :deep(.el-tabs__item) { padding: 0 12px !important; font-size: 13px !important; height: 40px !important; line-height: 40px !important; flex-shrink: 0; border-bottom-color: transparent !important; color: var(--m-text3, #8e99ab) !important; }
  :deep(.el-tabs__item.is-active) { color: var(--m-accent, #409eff) !important; font-weight: 600; }
  :deep(.el-tabs__active-bar) { height: 3px !important; border-radius: 3px 3px 0 0; background: var(--m-accent, #409eff) !important; }

  /* Tabs content — 去除边框和内边距 */
  :deep(.el-tabs--border-card > .el-tabs__content) { padding: 0 !important; border: none !important; }

  /* Desktop/mobile visibility toggle */
  .desktop-only { display: none !important; }
  .mobile-only { display: inline !important; }

  .tab-pane-content {
    padding: 6px 10px 8px;
  }

  /* tab-pane 不设 overflow:hidden，让分页可见 */
  .main-tabs :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) {
    overflow: visible !important;
  }

  /* Params card — 使用 m-card 风格 */
  .params-card { margin-bottom: 6px !important; border-radius: 10px !important; box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important; }
  .params-card :deep(.el-card__header) { padding: 6px 12px !important; font-size: 13px !important; line-height: 1.4 !important; border-bottom: 1px solid var(--m-border, #e0e4ea) !important; }
  .params-card :deep(.el-card__body) { padding: 8px 10px !important; }

  /* Results area — ensure visible on mobile */
  .batch-summary, .metrics-row, .chart-card { margin-bottom: 6px !important; }

  /* Form layout — wrap rows on mobile, items share a line */
  .form-grid-compact {
    flex-direction: row !important;
    flex-wrap: wrap !important;
    gap: 6px !important;
    align-items: center;
  }

  .form-item-inline {
    width: auto !important;
    gap: 4px !important;
  }

  /* Source + Strategy share first row */
  .mobile-row-source-strategy { flex: 1 1 auto !important; min-width: 0 !important; }

  /* Date + Button share second row */
  .mobile-row-date-action { flex: 1 1 auto !important; min-width: 0 !important; }

  .inline-label {
    min-width: 36px !important;
    font-size: 12px !important;
    color: var(--m-text3, #8e99ab) !important;
  }

  /* Form inputs — smaller on mobile */
  :deep(.el-input__wrapper),
  :deep(.el-select .el-input__wrapper) {
    padding: 2px 6px !important;
    border-radius: 6px !important;
    box-shadow: none !important;
    border: 1px solid var(--m-border, #e0e4ea) !important;
    height: 30px !important;
  }

  :deep(.el-input__inner) { font-size: 12px !important; }
  :deep(.el-select .el-input__suffix) { font-size: 12px !important; }

  /* Source select + strategy radios share row */
  .mobile-row-source-strategy :deep(.el-select) { width: 90px !important; flex-shrink: 0; }
  .mobile-row-source-strategy .strategy-radios { flex: 1; overflow-x: auto; min-width: 0; }

  /* Date pickers + button share row */
  .mobile-row-date-action :deep(.el-date-editor) { width: 85px !important; }
  .form-actions { margin-left: auto !important; flex-shrink: 0; }

  /* Stock count bar — compact */
  .stock-count-bar { margin-top: 6px !important; padding-top: 6px !important; gap: 6px !important; border-top: 1px solid var(--m-border, #e0e4ea) !important; }

  /* Strategy radios — horizontal scroll, compact */
  .strategy-radios :deep(.el-radio-group),
  .strategy-radios :deep(.el-checkbox-group) {
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    width: 100%;
    scrollbar-width: none;
  }
  .strategy-radios :deep(.el-radio-group::-webkit-scrollbar),
  .strategy-radios :deep(.el-checkbox-group::-webkit-scrollbar) { display: none; }

  .strategy-radios :deep(.el-radio-button__inner),
  .strategy-radios :deep(.el-checkbox-button__inner) {
    padding: 4px 10px !important;
    font-size: 11px !important;
    border-radius: 12px !important;
    border: 1px solid var(--m-border, #e0e4ea) !important;
    background: var(--m-surface, #fff) !important;
    line-height: 1.4 !important;
    min-height: 24px !important;
  }

  /* checkbox/radio button checked state handled by non-scoped style block below */

  /* Metrics row — compact on mobile */
  .metrics-row { margin-bottom: 8px; }
  .metrics-row :deep(.el-col) { padding: 0 3px !important; }
  .metric-card { padding: 6px 2px; border-radius: 8px; }
  .metric-label { font-size: 10px !important; }
  .metric-value { font-size: 12px !important; }

  /* Chart — responsive height on mobile */
  .equity-chart { min-height: 130px !important; }
  .chart-card { border-radius: 10px !important; box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important; }
  .chart-card :deep(.el-card__header) { padding: 6px 12px !important; font-size: 12px !important; }
  .chart-card .el-card__body { padding: 4px !important; }

  /* Table section — keep flex chain, table fills remaining space, pagination below */
  .table-section { margin-top: 6px !important; }

  /* Table horizontal scroll on mobile */
  .table-section :deep(.el-table),
  .table-scroll-wrapper :deep(.el-table) {
    min-width: 0 !important;
    width: 100% !important;
    max-width: none !important;
  }

  /* Internal table uses fixed layout, content stretches for horizontal scroll */
  .table-section :deep(.el-table__header-wrapper > table),
  .table-section :deep(.el-table__body-wrapper > table),
  .table-scroll-wrapper :deep(.el-table__header-wrapper > table),
  .table-scroll-wrapper :deep(.el-table__body-wrapper > table) {
    width: max-content !important;
    min-width: 100% !important;
    max-width: none !important;
    table-layout: fixed !important;
    flex-shrink: 0 !important;
  }

  /* Table body horizontal scroll with touch */
  .table-section :deep(.el-table__body-wrapper),
  .table-scroll-wrapper :deep(.el-table__body-wrapper) {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch !important;
  }

  /* Compact cells on mobile */
  :deep(.el-table th.el-table__cell),
  :deep(.el-table td.el-table__cell) { padding: 6px 2px !important; font-size: 12px !important; }
  :deep(.el-table .cell) { font-size: 11px !important; padding: 0 2px !important; }

  /* Pagination — 紧靠底部导航栏 */
  .pagination-wrapper {
    background: var(--m-surface, #fff) !important;
    box-shadow: 0 -2px 6px rgba(0,0,0,0.06) !important;
    justify-content: center !important;
    padding: 4px 4px calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 8px), 16px) !important;
    flex-shrink: 0;
    margin-top: 4px;
    min-height: 28px !important;
    border-radius: 10px 10px 0 0;
  }
  .pagination-wrapper :deep(.el-pagination) { font-size: 11px !important; flex-wrap: wrap; justify-content: center; gap: 2px; }
  .pagination-wrapper :deep(.el-pager li) { min-width: 24px !important; height: 24px !important; line-height: 24px !important; font-size: 11px !important; margin: 0 1px !important; border-radius: 4px !important; }
  .pagination-wrapper :deep(.el-pagination button) { min-width: 24px !important; height: 24px !important; line-height: 24px !important; border-radius: 4px !important; }
  .pagination-wrapper :deep(.el-pagination__sizes) { display: none !important; }
  .pagination-wrapper :deep(.el-pagination__jump) { display: none !important; }

  /* Batch summary */
  .batch-summary { flex-direction: column; align-items: flex-start; gap: 4px; }
  .summary-item, .summary-tag { font-size: 11px !important; padding: 2px 8px !important; border-radius: 6px !important; background: var(--m-surface2, #f0f2f5) !important; }

  :deep(.el-button) { min-height: 30px !important; padding: 4px 12px !important; font-size: 12px !important; border-radius: 6px !important; }
  :deep(.el-button--small) { min-height: 26px !important; padding: 3px 10px !important; font-size: 11px !important; border-radius: 6px !important; }

  /* Date picker — compact on mobile */
  :deep(.el-date-editor .el-input__wrapper) { padding: 2px 6px !important; height: 30px !important; }

  /* Autocomplete — full width on mobile for single/compare tab */
  .form-item-inline :deep(.el-autocomplete) { width: 100% !important; flex: 1 !important; }

  /* Single strategy & compare form layout — stack vertically on small screens */
  .tab-pane-content .params-card .form-grid-compact .form-item-inline:not(.mobile-row-source-strategy):not(.mobile-row-date-action) {
    flex: 1 1 100% !important;
  }

  /* Fixed column z-index for scroll visibility */
  :deep(.el-table__fixed),
  :deep(.el-table__fixed-right) { z-index: 10 !important; }
  :deep(.el-table__fixed) { box-shadow: 2px 0 6px rgba(0,0,0,0.08) !important; }
  :deep(.el-table__fixed-right) { box-shadow: -2px 0 6px rgba(0,0,0,0.08) !important; }

  /* Empty state compact */
  :deep(.el-empty) { padding: 20px 0 !important; }
  :deep(.el-empty__image) { height: 60px !important; }

  /* 隐藏桌面端表格 */
  .table-section .table-scroll-wrapper { display: none !important; }

  /* 移动端回测结果卡片列表 */
  .bt-mobile-list {
    flex: 1 1 0 !important;
    min-height: 0 !important;
    overflow-y: auto !important;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 8px;
  }
  .bt-mobile-list::-webkit-scrollbar { width: 4px; }
  .bt-mobile-list::-webkit-scrollbar-thumb { background: #c0c4cc; border-radius: 2px; }

  /* 回测结果卡片 */
  .bt-result-card { padding: 10px 12px !important; margin-bottom: 8px !important; border-radius: 10px !important; }

  /* 卡片顶部：排名 + 信息 + 收益 */
  .bt-card-top { display: flex; align-items: center; gap: 8px; }
  .bt-rank { width: 20px; height: 20px; border-radius: 5px; background: var(--m-surface2, #f0f2f5); display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 700; color: var(--m-text3, #8e99ab); flex-shrink: 0; }
  .bt-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
  .bt-name { font-size: 13px; font-weight: 600; color: var(--m-text, #1a2332); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bt-code { font-size: 10px; color: var(--m-text3, #8e99ab); }

  /* 收益列 */
  .bt-return { font-size: 14px; font-weight: 700; flex-shrink: 0; text-align: right; }

  /* 卡片统计行 */
  .bt-card-stats { display: flex; align-items: center; gap: 8px; margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--m-border, #e0e4ea); }
  .bt-stat { font-size: 10px; flex: 1; display: flex; flex-direction: column; align-items: center; gap: 1px; }
  .bt-label { color: var(--m-text3, #8e99ab); font-size: 9px; }

  /* Compare tab strategy tag */
  .bt-result-card :deep(.el-tag) { border-radius: 6px !important; height: 20px !important; line-height: 18px !important; font-size: 10px !important; padding: 0 6px !important; }
}

/* Extra small screens */
@media (max-width: 380px) {
  .strategy-backtest :deep(.el-tabs__item) { font-size: 12px !important; padding: 0 8px !important; height: 36px !important; line-height: 36px !important; }
  .inline-label { min-width: 30px !important; font-size: 11px !important; }
  .mobile-row-source-strategy :deep(.el-select) { width: 75px !important; }
  .mobile-row-date-action :deep(.el-date-editor) { width: 75px !important; }
}
</style>