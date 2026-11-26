<template>
  <div class="report-page">
    <div class="page-header">
      <div class="header-left">
        <h2 class="page-title"><el-icon><MagicStick /></el-icon> AI股票推荐</h2>
        <span class="disclaimer-inline">本报告由AI智能生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。</span>
      </div>
      <div class="header-actions" :class="{ 'mobile-header': isMobile }">
        <RefreshingIndicator :show="listCache.refreshing.value || detailCache.refreshing.value" text="数据更新中" />
        <el-date-picker
          v-model="selectedDate"
          type="date"
          placeholder="选择日期"
          value-format="YYYY-MM-DD"
          :disabled-date="disableMobileDate"
          :clearable="false"
          @change="loadByDate"
          :style="{ width: isMobile ? 'auto' : '160px', flex: isMobile ? '1' : 'none' }"
        />
        <el-button type="primary" :icon="Refresh" circle @click="refreshCurrent" :loading="loading" class="desktop-only" />
        <el-button v-if="isMobile" type="primary" text :icon="Refresh" @click="refreshCurrent" :loading="loading" class="mobile-refresh">刷新</el-button>
        <el-button v-if="authStore.isAdmin && !isMobile" type="warning" @click="handleGenerate" :loading="generating">
          生成当日推荐
        </el-button>
        <el-button v-if="authStore.isAdmin && isMobile" type="warning" text size="small" @click="handleGenerate" :loading="generating" class="mobile-gen-btn">生成</el-button>
        <el-popconfirm title="将对所有推荐股票执行MACD策略回测（近1年），确定继续？" @confirm="runBatchVerify" width="200">
          <template #reference>
            <el-button type="info" :loading="batchVerifyLoading" size="default" class="desktop-only">
              <el-icon><DataAnalysis /></el-icon> 批量回测
            </el-button>
          </template>
        </el-popconfirm>
        <el-popconfirm v-if="isMobile" title="将对所有推荐股票执行MACD策略回测（近1年），确定继续？" @confirm="runBatchVerify" width="200">
          <template #reference>
            <el-button type="info" text size="small" :loading="batchVerifyLoading" class="mobile-batch-btn">
              <el-icon><DataAnalysis /></el-icon> 回测
            </el-button>
          </template>
        </el-popconfirm>
      </div>
    </div>

    <!-- 移动端：报告详情（卡片化设计） -->
    <template v-if="isMobile">
      <div class="mob-pick-container" v-loading="loadingReport">

        <!-- 日期快速选择器 -->
        <div v-if="pickList.length > 1" class="m-card mob-date-tabs">
          <div class="m-hscroll-tabs">
            <span
              v-for="item in pickList.slice(0, 14)"
              :key="'tab-' + item.pick_date"
              class="tab"
              :class="{ active: currentPick?.pick_date === item.pick_date }"
              @click="selectDate(item.pick_date)"
            >
              {{ formatDateTab(item.pick_date) }}
            </span>
          </div>
        </div>

        <!-- 推荐头部信息卡 -->
        <div v-if="currentPick" class="m-card mob-report-header">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div>
              <div style="font-size:16px;font-weight:700;color:var(--m-text);">{{ currentPick.pick_date }}</div>
              <div style="font-size:12px;color:var(--m-text3);margin-top:2px;">AI股票推荐</div>
            </div>
            <el-tag :type="currentPick.status === 'completed' ? 'success' : currentPick.status === 'generating' ? 'warning' : 'danger'" size="small" style="min-height:24px;padding:0 10px;">{{ statusLabel(currentPick.status) }}</el-tag>
          </div>

          <!-- 已完成：统计卡片 -->
          <div v-if="currentPick.status === 'completed'" class="m-stats-row mob-stats">
            <div class="m-stat-card" style="cursor:default;">
              <div class="val accent">{{ shortPicks.length + longPicks.length }}</div>
              <div class="lbl">推荐总数</div>
            </div>
            <div class="m-stat-card" style="cursor:default;">
              <div class="val accent">{{ currentPick.word_count || '-' }}</div>
              <div class="lbl">字数</div>
            </div>
            <div class="m-stat-card" style="cursor:default;">
              <div class="val accent">{{ formatTime(currentPick.generated_at) }}</div>
              <div class="lbl">AI生成</div>
            </div>
          </div>

          <!-- 生成中：进度提示 -->
          <div v-if="currentPick.status === 'generating'" class="mob-generating">
            <div class="m-alert-item" style="border-bottom:none;padding:8px 0;">
              <span class="dot blue"></span>
              <div class="body">
                <div class="title" style="color:#409eff;">推荐生成中，请稍候...</div>
                <div class="desc">AI推理通常需要1-3分钟</div>
              </div>
            </div>
            <el-button type="primary" size="small" style="margin-top:8px;width:100%;min-height:40px;" @click="refreshCurrent" :loading="loading">刷新查看进度</el-button>
          </div>

          <!-- 生成失败：错误提示 -->
          <div v-if="currentPick.status === 'failed'" class="mob-failed">
            <div class="m-alert-item" style="border-bottom:none;padding:8px 0;">
              <span class="dot red"></span>
              <div class="body">
                <div class="title" style="color:#f56c6c;">推荐生成失败</div>
                <div class="desc">{{ currentPick.error_msg || '未知错误' }}</div>
              </div>
            </div>
            <el-button v-if="authStore.isAdmin" type="warning" size="small" style="margin-top:8px;width:100%;min-height:40px;" @click="handleGenerate">重新生成</el-button>
          </div>
        </div>

        <!-- AI报告（Markdown渲染） -->
        <div v-if="currentPick?.ai_report && currentPick.ai_report.trim()" class="m-card mob-report-body">
          <div class="mob-md-content" v-html="renderMarkdown(currentPick.ai_report)" />
        </div>

        <!-- 结构化数据：卡片化展示（无ai_report时） -->
        <template v-else-if="currentPick && currentPick.status === 'completed' && (shortPicks.length > 0 || longPicks.length > 0)">

          <!-- 市场研判：统计卡片行 -->
          <div v-if="picksData.market_outlook">
            <div class="m-section-header">📊 市场研判</div>
            <div class="m-stats-row" style="grid-template-columns:repeat(3,1fr);">
              <div class="m-stat-card">
                <div class="val accent">{{ picksData.market_outlook.trend || '震荡' }}</div>
                <div class="lbl">趋势</div>
              </div>
              <div class="m-stat-card">
                <div class="val" :class="riskType === 'success' ? 'down' : riskType === 'danger' ? 'up' : 'accent'">{{ picksData.market_outlook.risk_level || '中等' }}</div>
                <div class="lbl">风险</div>
              </div>
              <div class="m-stat-card">
                <div class="val accent">{{ picksData.market_outlook.suggested_position || '50-60%' }}</div>
                <div class="lbl">建议仓位</div>
              </div>
            </div>
          </div>

          <!-- 短线推荐：股票卡片列表 -->
          <template v-if="shortPicks.length > 0">
            <div class="m-section-header">🔥 短线推荐 TOP{{ shortPicks.length }}</div>
            <div v-for="s in shortPicks" :key="'sh-'+s.code" class="m-stock-card mob-pick-card" @click="runQuickVerify(s.code)">
              <div class="mob-pick-top">
                <div class="mob-pick-rank" :class="'r'+s.rank">#{{ s.rank }}</div>
                <div class="mob-pick-info">
                  <div class="mob-pick-name">{{ s.name }}</div>
                  <div class="mob-pick-code">{{ s.code }}</div>
                </div>
                <div class="mob-pick-score" :class="scoreLevel(s.score)">
                  <span class="mob-pick-score-val">{{ s.score }}</span>
                  <span class="mob-pick-score-label">AI评分</span>
                </div>
              </div>
              <div class="mob-pick-bottom">
                <div class="mob-pick-price">¥{{ s.price?.toFixed(2) || '--' }}</div>
                <div class="mob-pick-reason" v-if="s.recommendation">{{ s.recommendation }}</div>
              </div>
              <div class="mob-pick-action" v-if="verifyResults[s.code]">
                <el-tag :type="getRatingType(verifyResults[s.code].rating)" size="small">回测: {{ verifyResults[s.code].rating }} ({{ formatReturn(verifyResults[s.code].total_return_pct) }})</el-tag>
              </div>
              <div class="mob-pick-action" v-else-if="verifyLoading[s.code]">
                <el-icon class="is-loading"><Loading /></el-icon> 回测中...
              </div>
            </div>
          </template>

          <!-- 中长线推荐：股票卡片列表 -->
          <template v-if="longPicks.length > 0">
            <div class="m-section-header">📈 中长线推荐 TOP{{ longPicks.length }}</div>
            <div v-for="s in longPicks" :key="'lg-'+s.code" class="m-stock-card mob-pick-card" @click="runQuickVerify(s.code)">
              <div class="mob-pick-top">
                <div class="mob-pick-rank" :class="'r'+s.rank">#{{ s.rank }}</div>
                <div class="mob-pick-info">
                  <div class="mob-pick-name">{{ s.name }}</div>
                  <div class="mob-pick-code">{{ s.code }}</div>
                </div>
                <div class="mob-pick-score" :class="scoreLevel(s.score)">
                  <span class="mob-pick-score-val">{{ s.score }}</span>
                  <span class="mob-pick-score-label">AI评分</span>
                </div>
              </div>
              <div class="mob-pick-bottom">
                <div class="mob-pick-price">¥{{ s.price?.toFixed(2) || '--' }}</div>
                <div class="mob-pick-reason" v-if="s.recommendation">{{ s.recommendation }}</div>
              </div>
              <div class="mob-pick-action" v-if="verifyResults[s.code]">
                <el-tag :type="getRatingType(verifyResults[s.code].rating)" size="small">回测: {{ verifyResults[s.code].rating }} ({{ formatReturn(verifyResults[s.code].total_return_pct) }})</el-tag>
              </div>
              <div class="mob-pick-action" v-else-if="verifyLoading[s.code]">
                <el-icon class="is-loading"><Loading /></el-icon> 回测中...
              </div>
            </div>
          </template>

          <!-- 风险提示 -->
          <div class="m-card mob-disclaimer">
            <div style="font-size:13px;color:#6b5900;line-height:1.8;">
              ⚠️ 以上推荐由AI生成，仅供参考<br />股市有风险，投资需谨慎<br />请根据自身风险承受能力做出决策
            </div>
          </div>
        </template>

        <!-- 加载中 -->
        <div v-if="!currentPick && loadingReport" class="m-card mob-placeholder">
          <el-icon class="is-loading" :size="32"><Loading /></el-icon>
          <p style="margin-top:12px;color:var(--m-text3);font-size:13px;">正在加载推荐内容...</p>
        </div>

        <!-- 空状态 -->
        <div v-if="!currentPick && !loadingReport" class="m-card mob-placeholder">
          <el-empty description="暂无推荐数据" :image-size="80">
            <template #description>
              <p style="color:var(--m-text3);font-size:12px;margin-top:8px;text-align:center;line-height:1.6;">系统定时生成推荐报告，当前暂无数据。<br /><span v-if="authStore.isAdmin">点击上方「生成当日推荐」手动触发</span><span v-else>请联系管理员生成</span></p>
            </template>
          </el-empty>
        </div>
      </div>
    </template>

    <!-- 桌面端：双栏布局 -->
    <template v-else>
      <!-- 报告列表 -->
      <el-row :gutter="16">
        <!-- 左侧：历史推荐列表 -->
        <el-col :xs="24" :sm="5">
          <el-card shadow="hover" class="list-card">
            <template #header>
              <div class="card-header">
                <span>历史推荐</span>
                <el-tag size="small" type="info">最近30天</el-tag>
              </div>
            </template>
            <div class="report-list" v-loading="loadingList">
              <div
                v-for="item in pickList"
                :key="item.pick_date"
                class="report-item"
                :class="{ active: currentPick?.pick_date === item.pick_date }"
                @click="selectDate(item.pick_date)"
              >
                <div class="item-date">{{ item.pick_date }}</div>
                <div class="item-meta">
                  <el-tag
                    :type="item.status === 'completed' ? 'success' : item.status === 'failed' ? 'danger' : 'warning'"
                    size="small"
                  >
                    {{ statusLabel(item.status) }}
                  </el-tag>
                  <span class="item-time">{{ formatTime(item.generated_at) }}</span>
                </div>
              </div>
              <el-empty
                v-if="!loadingList && pickList.length === 0"
                :description="listError ? listError : '暂无推荐'"
              />
            </div>
          </el-card>
        </el-col>

        <!-- 右侧：推荐详情 -->
        <el-col :xs="24" :sm="19">
          <el-card shadow="hover" class="report-card" v-loading="loadingReport">
<template #header v-if="currentPick">
              <div class="card-header">
                <span>{{ currentPick.pick_date }} AI股票推荐</span>
                <el-tag :type="currentPick.status === 'completed' ? 'success' : 'danger'" size="small">
                  {{ statusLabel(currentPick.status) }}
                </el-tag>
              </div>
            </template>

            <!-- AI报告内容（优先显示AI生成的完整报告） -->
            <div v-if="currentPick?.ai_report && currentPick.ai_report.trim()" class="report-content" v-html="renderMarkdown(currentPick.ai_report)" />

            <!-- 结构化数据展示（当ai_report为空时回退到结构化表格） -->
            <div v-else-if="currentPick && (shortPicks.length > 0 || longPicks.length > 0)" class="report-content picks-structured">
              <!-- 市场研判 -->
              <div class="outlook-section" v-if="picksData.market_outlook">
                <h2>📊 市场研判</h2>
                <div class="outlook-grid">
                  <div class="outlook-item"><span class="label">趋势:</span> {{ picksData.market_outlook.trend || '震荡' }}</div>
                  <div class="outlook-item"><span class="label">风险:</span> <el-tag :type="riskType" size="small">{{ picksData.market_outlook.risk_level || '中等' }}</el-tag></div>
                  <div class="outlook-item"><span class="label">建议仓位:</span> {{ picksData.market_outlook.suggested_position || '50-60%' }}</div>
                </div>
              </div>

              <!-- 短线推荐 -->
              <template v-if="shortPicks.length > 0">
                <h2>🔥 短线推荐 TOP10</h2>
                <div class="picks-table-wrap">
                  <table class="picks-table">
                    <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>现价</th><th>评分</th><th>推荐理由</th><th style="width:80px">回测验证</th></tr></thead>
                    <tbody>
                      <tr v-for="s in shortPicks" :key="s.code">
                        <td>{{ s.rank }}</td><td>{{ s.code }}</td><td>{{ s.name }}</td>
                        <td class="price">{{ s.price?.toFixed(2) || '--' }}</td>
                        <td>{{ s.score }}</td><td>{{ s.recommendation }}</td><td>
                          <el-button type="primary" link size="small" @click.stop="runQuickVerify(s.code)" :loading="verifyLoading[s.code]">验证</el-button>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>

              <!-- 中长线推荐 -->
              <template v-if="longPicks.length > 0">
                <h2>📈 中长线推荐 TOP10</h2>
                <div class="picks-table-wrap">
                  <table class="picks-table">
                    <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>现价</th><th>评分</th><th>推荐理由</th><th style="width:80px">回测验证</th></tr></thead>
                    <tbody>
                      <tr v-for="s in longPicks" :key="s.code">
                        <td>{{ s.rank }}</td><td>{{ s.code }}</td><td>{{ s.name }}</td>
                        <td class="price">{{ s.price?.toFixed(2) || '--' }}</td>
                        <td>{{ s.score }}</td><td>{{ s.recommendation }}</td><td>
                          <el-button type="primary" link size="small" @click.stop="runQuickVerify(s.code)" :loading="verifyLoading[s.code]">验证</el-button>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>

              <!-- 操盘策略 -->
              <div class="strategy-section" v-if="(shortPicks.length > 0 || longPicks.length > 0)">
                <h2>📋 操盘策略明细</h2>
                <el-collapse>
                  <el-collapse-item v-for="s in shortPicks" :key="'s-'+s.code" :title="`${s.rank}. ${s.name} (${s.code})`">
                    <div class="strategy-grid">
                      <div class="strategy-item"><span class="label">📈 建仓区间:</span> {{ s.strategy?.entry_price || '-' }}</div>
                      <div class="strategy-item"><span class="label">🛑 止损位:</span> {{ s.strategy?.stop_loss || '-' }}</div>
                      <div class="strategy-item"><span class="label">🎯 目标位:</span> {{ s.strategy?.target_price || '-' }}</div>
                      <div class="strategy-item"><span class="label">💰 仓位建议:</span> {{ s.strategy?.position || '-' }}</div>
                      <div class="strategy-item"><span class="label">📅 持股周期:</span> {{ s.strategy?.hold_days || '-' }}</div>
                      <div class="strategy-item"><span class="label">📤 卖出信号:</span> {{ s.strategy?.sell_signal || '-' }}</div>
                    </div>
                    <div class="ai-analysis" v-if="s.ai_analysis">{{ s.ai_analysis }}</div>
                  </el-collapse-item>
                  <!-- P0: 内联回测结果 -->
                  <el-collapse-item v-if="verifyResults[s.code]" :key="'v-'+s.code" title="📊 回测验证结果">
                    <div class="backtest-inline-result">
                      <template v-if="verifyResults[s.code].error">
                        <el-alert type="error" :title="verifyResults[s.code].error" show-icon :closable="false" />
                      </template>
                      <template v-else>
                        <div class="bt-score-row">
                          <span class="bt-label">综合评分</span>
                          <el-tag :type="getRatingType(verifyResults[s.code].rating)" size="large">{{ verifyResults[s.code].composite_score }}分 ({{ verifyResults[s.code].rating }})</el-tag>
                        </div>
                        <div class="bt-metrics-grid">
                          <div class="bt-metric"><span class="bt-label">总收益</span><span :class="verifyResults[s.code].total_return_pct >= 0 ? 'positive' : 'negative'">{{ formatReturn(verifyResults[s.code].total_return_pct) }}</span></div>
                          <div class="bt-metric"><span class="bt-label">年化收益</span><span :class="verifyResults[s.code].annual_return_pct >= 0 ? 'positive' : 'negative'">{{ formatReturn(verifyResults[s.code].annual_return_pct) }}</span></div>
                          <div class="bt-metric"><span class="bt-label">夏普比率</span><span>{{ verifyResults[s.code].sharpe_ratio?.toFixed(2) || '--' }}</span></div>
                          <div class="bt-metric"><span class="bt-label">最大回撤</span><span class="negative">{{ formatReturn(verifyResults[s.code].max_drawdown_pct) }}</span></div>
                          <div class="bt-metric"><span class="bt-label">胜率</span><span>{{ (verifyResults[s.code].win_rate_pct || 0).toFixed(1) }}%</span></div>
                          <div class="bt-metric"><span class="bt-label">盈亏比</span><span>{{ verifyResults[s.code].profit_factor?.toFixed(2) || '--' }}</span></div>
                        </div>
                        <el-button type="primary" link size="small" @click.stop="goToBacktest(s.code, 'macd')">查看完整回测 →</el-button>
                      </template>
                    </div>
                  </el-collapse-item>
                  <el-collapse-item v-for="s in longPicks" :key="'l-'+s.code" :title="`${s.rank}. ${s.name} (${s.code})`">
                    <div class="strategy-grid">
                      <div class="strategy-item"><span class="label">📈 建仓区间:</span> {{ s.strategy?.entry_price || '-' }}</div>
                      <div class="strategy-item"><span class="label">🛑 止损位:</span> {{ s.strategy?.stop_loss || '-' }}</div>
                      <div class="strategy-item"><span class="label">🎯 目标位:</span> {{ s.strategy?.target_price || '-' }}</div>
                      <div class="strategy-item"><span class="label">💰 仓位建议:</span> {{ s.strategy?.position || '-' }}</div>
                      <div class="strategy-item"><span class="label">📅 持股周期:</span> {{ s.strategy?.hold_days || '-' }}</div>
                      <div class="strategy-item"><span class="label">📤 卖出信号:</span> {{ s.strategy?.sell_signal || '-' }}</div>
                    </div>
                    <div class="ai-analysis" v-if="s.ai_analysis">{{ s.ai_analysis }}</div>
                  </el-collapse-item>
                  <!-- P0: 内联回测结果 -->
                  <el-collapse-item v-if="verifyResults[s.code]" :key="'v-'+s.code" title="📊 回测验证结果">
                    <div class="backtest-inline-result">
                      <template v-if="verifyResults[s.code].error">
                        <el-alert type="error" :title="verifyResults[s.code].error" show-icon :closable="false" />
                      </template>
                      <template v-else>
                        <div class="bt-score-row">
                          <span class="bt-label">综合评分</span>
                          <el-tag :type="getRatingType(verifyResults[s.code].rating)" size="large">{{ verifyResults[s.code].composite_score }}分 ({{ verifyResults[s.code].rating }})</el-tag>
                        </div>
                        <div class="bt-metrics-grid">
                          <div class="bt-metric"><span class="bt-label">总收益</span><span :class="verifyResults[s.code].total_return_pct >= 0 ? 'positive' : 'negative'">{{ formatReturn(verifyResults[s.code].total_return_pct) }}</span></div>
                          <div class="bt-metric"><span class="bt-label">年化收益</span><span :class="verifyResults[s.code].annual_return_pct >= 0 ? 'positive' : 'negative'">{{ formatReturn(verifyResults[s.code].annual_return_pct) }}</span></div>
                          <div class="bt-metric"><span class="bt-label">夏普比率</span><span>{{ verifyResults[s.code].sharpe_ratio?.toFixed(2) || '--' }}</span></div>
                          <div class="bt-metric"><span class="bt-label">最大回撤</span><span class="negative">{{ formatReturn(verifyResults[s.code].max_drawdown_pct) }}</span></div>
                          <div class="bt-metric"><span class="bt-label">胜率</span><span>{{ (verifyResults[s.code].win_rate_pct || 0).toFixed(1) }}%</span></div>
                          <div class="bt-metric"><span class="bt-label">盈亏比</span><span>{{ verifyResults[s.code].profit_factor?.toFixed(2) || '--' }}</span></div>
                        </div>
                        <el-button type="primary" link size="small" @click.stop="goToBacktest(s.code, 'macd')">查看完整回测 →</el-button>
                      </template>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </div>



              <!-- 风险提示 -->
              <div class="disclaimer-section">
                <h3>⚠️ 风险提示</h3>
                <p>1. 以上推荐由AI生成，仅供参考，不构成投资建议</p>
                <p>2. 股市有风险，投资需谨慎</p>
                <p>3. 请根据自身风险承受能力做出投资决策</p>
              </div>
            </div>

            <!-- 加载中提示 -->
            <div v-else-if="loadingReport" class="report-placeholder">
              <el-icon class="is-loading" :size="32"><Loading /></el-icon>
              <p>正在加载推荐内容...</p>
            </div>

            <!-- 生成中状态 -->
            <div v-else-if="currentPick && currentPick.status === 'generating'" class="report-placeholder">
              <el-icon class="is-loading" :size="32"><Loading /></el-icon>
              <p style="margin-top:12px;color:#409eff;font-weight:500;">推荐生成中，请稍候...</p>
              <p style="color:#909399;font-size:13px;margin-top:4px;">AI推理通常需要1-3分钟</p>
              <el-button type="primary" size="small" style="margin-top:12px;" @click="refreshCurrent" :loading="loading">刷新查看进度</el-button>
            </div>

            <!-- 生成失败状态 -->
            <div v-else-if="currentPick && currentPick.status === 'failed'" class="report-placeholder">
              <el-icon :size="32"><WarningFilled /></el-icon>
              <p style="color:#f56c6c;margin-top:12px;font-weight:500;">推荐生成失败</p>
              <p style="color:#909399;font-size:13px;margin-top:8px;text-align:center;max-width:400px;">{{ currentPick.error_msg || '未知错误' }}</p>
              <el-button v-if="authStore.isAdmin" type="warning" size="small" style="margin-top:12px;" @click="handleGenerate">重新生成</el-button>
            </div>

            <!-- 空状态 -->
            <div v-else class="report-placeholder">
              <el-empty description="暂无推荐数据">
                <template #description>
                  <p style="color:#909399;font-size:13px;margin-top:8px;text-align:center;line-height:1.6;">
                     系统定时生成推荐报告，当前暂无数据。<br />
                    <span v-if="authStore.isAdmin">点击上方「生成当日推荐」手动触发</span>
                    <span v-else>请联系管理员生成</span>
                  </p>
                </template>
              </el-empty>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </template>
  
    <!-- P0: 批量回测抽屉 -->
    <el-drawer v-model="batchDrawerVisible" :modal="false" title="📊 批量回测结果" :size="isMobile ? '100%' : '750px'" destroy-on-close>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center;width:100%;">
          <span>📊 批量回测结果</span>
          <el-button type="primary" size="small" @click="runBatchVerify" :loading="batchVerifyLoading">重新回测</el-button>
        </div>
      </template>

      <div v-if="batchVerifyResults" class="drawer-backtest-content">
        <div class="batch-summary">
          <span class="summary-item">策略: {{ batchVerifyResults.strategy?.toUpperCase() }}</span>
          <span class="summary-item">周期: {{ batchVerifyResults.period }}</span>
          <span class="summary-item">成功: {{ batchVerifyResults.success_count }}/{{ batchVerifyResults.total_stocks }}</span>
        </div>

        <!-- 桌面端：表格展示 -->
        <template v-if="!isMobile">
          <el-table :data="batchVerifyResults.results || []" border stripe size="small" max-height="600">
            <el-table-column type="index" label="#" width="50" align="center" />
            <el-table-column prop="stock" label="代码" width="80" align="center" />
            <el-table-column label="名称" min-width="70"><template #default="{ row }">{{ getStockName(row.stock) || row.stock }}</template></el-table-column>
            <el-table-column label="总收益" width="100"><template #default="{ row }"><span :class="row.total_return_pct >= 0 ? 'positive' : 'negative'" style="font-weight:600">{{ formatReturn(row.total_return_pct) }}</span></template></el-table-column>
            <el-table-column label="年化收益" width="100"><template #default="{ row }"><span :class="row.annual_return_pct >= 0 ? 'positive' : 'negative'">{{ formatReturn(row.annual_return_pct) }}</span></template></el-table-column>
            <el-table-column prop="sharpe_ratio" label="夏普比率" width="90" align="center" />
            <el-table-column label="最大回撤" width="100"><template #default="{ row }"><span class="negative">{{ formatReturn(row.max_drawdown_pct) }}</span></template></el-table-column>
            <el-table-column label="胜率" width="80" align="center"><template #default="{ row }">{{ (row.win_rate_pct || 0).toFixed(1) }}%</template></el-table-column>
            <el-table-column prop="profit_factor" label="盈亏比" width="80" align="center" />
            <el-table-column prop="total_trades" label="交易次数" width="90" align="center" />
          </el-table>
        </template>

        <!-- 移动端：卡片展示 -->
        <template v-else>
          <div class="mob-bt-card-list">
            <div v-for="(row, idx) in batchVerifyResults.results || []" :key="'bt-'+idx" class="m-stock-card mob-bt-card">
              <div class="mob-bt-top">
                <div class="mob-bt-rank" :class="idx === 0 ? 'r1' : idx === 1 ? 'r2' : idx === 2 ? 'r3' : ''">{{ idx + 1 }}</div>
                <div class="mob-bt-info">
                  <div class="mob-bt-name">{{ getStockName(row.stock) || row.stock }}</div>
                  <div class="mob-bt-code">{{ row.stock }}</div>
                </div>
                <div class="mob-bt-return" :class="row.total_return_pct >= 0 ? 'up' : 'down'">
                  {{ formatReturn(row.total_return_pct) }}
                </div>
              </div>
              <div class="mob-bt-metrics">
                <div class="mob-bt-metric">
                  <span class="mob-bt-m-label">年化收益</span>
                  <span :class="row.annual_return_pct >= 0 ? 'up' : 'down'">{{ formatReturn(row.annual_return_pct) }}</span>
                </div>
                <div class="mob-bt-metric">
                  <span class="mob-bt-m-label">夏普比率</span>
                  <span>{{ row.sharpe_ratio?.toFixed(2) || '--' }}</span>
                </div>
                <div class="mob-bt-metric">
                  <span class="mob-bt-m-label">最大回撤</span>
                  <span class="down">{{ formatReturn(row.max_drawdown_pct) }}</span>
                </div>
                <div class="mob-bt-metric">
                  <span class="mob-bt-m-label">胜率</span>
                  <span>{{ (row.win_rate_pct || 0).toFixed(1) }}%</span>
                </div>
                <div class="mob-bt-metric">
                  <span class="mob-bt-m-label">盈亏比</span>
                  <span>{{ row.profit_factor?.toFixed(2) || '--' }}</span>
                </div>
                <div class="mob-bt-metric">
                  <span class="mob-bt-m-label">交易次数</span>
                  <span>{{ row.total_trades || 0 }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- 失败列表 -->
        <div v-if="batchVerifyResults.failed && batchVerifyResults.failed.length > 0" class="bt-failed-section">
          <h4 style="color:#f56c6c;font-size:13px;">回测失败 ({{ batchVerifyResults.failed.length }})</h4>
          <div v-for="f in batchVerifyResults.failed" :key="f.stock" class="bt-failed-item">{{ f.stock }}: {{ f.error }}</div>
        </div>
      </div>

      <el-empty v-else description="点击「重新回测」开始批量回测" />
    </el-drawer>
  </div>
</template>

<script setup>
defineOptions({ name: 'AIStockPick' })
import { ref, reactive, computed, onMounted, onBeforeUnmount, onActivated, onDeactivated } from 'vue'

import { Refresh, MagicStick, Loading, DataAnalysis, WarningFilled } from '@element-plus/icons-vue'

import { ElMessage, ElMessageBox } from 'element-plus'
import { aiStockPickApi, backtestApi } from '@/api'

import { useAuthStore } from '@/stores/auth'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'
import RefreshingIndicator from '@/components/RefreshingIndicator.vue'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'

const authStore = useAuthStore()

// 本地时间格式化为 YYYY-MM-DD（避免 toISOString 在 UTC+8 凌晨返回昨天）
function getTodayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// 移动端检测
const isMobile = ref(false)
function _updateIsMobile() {
  isMobile.value = window.innerWidth <= 768
}

const loading = ref(false)
const generating = ref(false)

// P0: 回测验证状态
const verifyLoading = reactive({})  // { stock_code: true/false }
const verifyResults = reactive({})  // { stock_code: result_data }
const batchVerifyLoading = ref(false)
const batchVerifyResults = ref(null)
const batchDrawerVisible = ref(false)
const selectedDate = ref('')

// 推荐列表缓存：打开即看到最近30天列表 + 后台静默刷新
const listCache = useCachedFetch({
  key: () => 'stockpick:list:30d',
  fetcher: () => aiStockPickApi.list(30),
  tier: CACHE_TIERS.REPORT,
  onSuccess: (res) => Array.isArray(res) ? res : (res?.items || []),
  onError: (e) => {
    const status = e?.response?.status
    if (status === 401 || status === 403) {
      listError.value = '未登录或会话已过期'
    } else if (status >= 500) {
      listError.value = '后端服务异常'
    } else {
      listError.value = '加载失败，请稍后重试'
    }
  },
})

const pickList = computed(() => listCache.data.value || [])
const loadingList = computed(() => listCache.loading.value)
const listError = ref(null)

// 推荐详情缓存：打开即看到最新推荐 + 后台静默刷新
const detailCache = useCachedFetch({
  key: () => 'stockpick:latest',
  fetcher: () => aiStockPickApi.getLatest(),
  tier: CACHE_TIERS.REPORT,
  onSuccess: (res) => {
      // Filter out error responses like {"message": "暂无推荐"}
      if (!res || !res.pick_date) return null
      return res
    },
})

const currentPick = ref(null)
const loadingReport = ref(false)

// 结构化数据（当ai_report为空时展示）
const picksData = computed(() => {
  if (!currentPick.value?.picks_data) return {}
  try {
    return typeof currentPick.value.picks_data === 'string'
      ? JSON.parse(currentPick.value.picks_data)
      : currentPick.value.picks_data
  } catch { return {} }
})

const shortPicks = computed(() => picksData.value?.short_term || [])
const longPicks = computed(() => picksData.value?.long_term || [])

// 风险等级颜色映射
const riskTypeMap = { '低': 'success', '中': 'warning', '高': 'danger' }
const riskType = computed(() => riskTypeMap[picksData.value?.market_outlook?.risk_level] || 'info')

function renderMarkdown(text) {
  if (!text) return ''
  marked.setOptions({ breaks: true, gfm: true })
  let rawHtml = marked.parse(text)
  // 表格包裹 div，方便手机端横向滚动
  rawHtml = rawHtml.replace(/<table([^>]*)>([\s\S]*?)<\/table>/g, '<div class="table-wrapper"><table$1>$2</table></div>')
  return `<div class="md-body">${sanitizeHtml(rawHtml)}</div>`
}

function statusLabel(s) {
  const map = { completed: '已完成', generating: '生成中', failed: '失败' }
  return map[s] || s
}

function formatTime(t) {
  if (!t) return ''
  try {
    const d = new Date(t)
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  } catch { return t }
}

function formatDateTab(dateStr) {
  if (!dateStr) return ''
  const [y, m, d] = dateStr.split('-')
  const months = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']
  return `${months[parseInt(m, 10) - 1] || m}${parseInt(d, 10)}日`
}

function disableFutureDate(d) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return d.getTime() > today.getTime()
}

// 移动端日期选择器：只允许选择有报告的日期；列表为空时回退到只禁用未来日期
function disableMobileDate(d) {
  if (disableFutureDate(d)) return true
  // 列表为空（尚未加载或全部失败）时，允许选择任意过去日期，避免用户无法手动选今天触发生成
  if (!pickList.value || pickList.value.length === 0) return false
  const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  return !pickList.value.some(item => item.pick_date === dateStr)
}

async function loadByDate(date) {
  if (!date) date = selectedDate.value
  loadingReport.value = true
  try {
    const detail = await aiStockPickApi.getByDate(date)
    currentPick.value = detail || null
  } catch (e) {
    ElMessage.error('加载推荐失败')
  } finally {
    loadingReport.value = false
  }
}

async function selectDate(date) {
  selectedDate.value = date
  await loadByDate(date)
}

const refreshCurrent = async () => {
  loading.value = true
  try {
    await listCache.refresh()
    if (selectedDate.value) {
      await loadByDate(selectedDate.value)
    } else {
      await detailCache.refresh()
      currentPick.value = detailCache.data.value
    }
  } finally {
    loading.value = false
  }
}

const handleGenerate = async () => {
  // 按钮文案为"生成当日推荐"，强制使用今天，避免 selectedDate 被预填为历史推荐日期导致生成错误日期
  const date = getTodayStr()

  // 任何已存在的相同日期报告都提示覆盖（不仅限 completed，failed/generating 也会被覆盖）
  const exists = currentPick.value?.pick_date === date
  try {
    await ElMessageBox.confirm(
      `${exists ? `${date} 的推荐已存在，确定要重新生成并覆盖吗？` : `确定要生成 ${date} 的股票推荐吗？`}（AI推理可能需要1-3分钟）`,
      exists ? '确认覆盖' : '确认生成',
      { type: 'warning' }
    )
  } catch {
    return
  }

  generating.value = true
  const loadingMsg = ElMessage({ message: '正在生成推荐，请稍候...', duration: 0, type: 'info' })
  try {
    await aiStockPickApi.generate(date)
    loadingMsg.close()
    ElMessage.success(exists ? '推荐已重新生成并覆盖' : '推荐生成成功')
    await listCache.refresh()
    selectedDate.value = date
    detailCache.clear()
    await loadByDate(date)
  } catch (e) {
    loadingMsg.close()
    const errMsg = e.response?.data?.detail || e.message || '生成失败'
    // 超时错误：后端可能仍在执行，提示用户刷新查看（30秒后自动刷新一次，比5秒更接近实际生成时间）
    if (e.code === 'ECONNABORTED' || errMsg.includes('超时')) {
      ElMessage.warning('请求超时，但后端可能仍在生成中，请稍后刷新页面查看结果')
      setTimeout(async () => {
        await listCache.refresh()
        if (selectedDate.value === date) {
          await loadByDate(date)
        }
      }, 30000)
    } else {
      ElMessage.error(errMsg)
    }
  } finally {
    generating.value = false
  }
}

onMounted(async () => {
  _updateIsMobile()
  window.addEventListener('resize', _updateIsMobile)
  await detailCache.refresh()
  currentPick.value = detailCache.data.value
  if (currentPick.value?.pick_date) {
    selectedDate.value = currentPick.value.pick_date
  }
})

// keep-alive 切回时同步 isMobile（用户可能在切走期间旋转设备/调整窗口）
onActivated(() => {
  _updateIsMobile()
})

onDeactivated(() => {
  // keep-alive 切走时不移除监听器，避免切回后丢失（onBeforeUnmount 仍会处理真正卸载场景）
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', _updateIsMobile)
})

// P0: 快速回测验证（单只股票）
async function runQuickVerify(stockCode, strategy = 'macd') {
  if (verifyLoading[stockCode]) return
  verifyLoading[stockCode] = true
  verifyResults[stockCode] = null
  try {
    const res = await backtestApi.verify({ stock: stockCode, strategy, days: 120 })
    if (res.status === 'success') {
      verifyResults[stockCode] = res.data
    } else {
      verifyResults[stockCode] = { error: '回测失败' }
    }
  } catch (e) {
    verifyResults[stockCode] = { error: e.message || '回测异常' }
  } finally {
    verifyLoading[stockCode] = false
  }
}

// P0: 批量回测验证（所有推荐股票）
async function runBatchVerify() {
  const allStocks = [...shortPicks.value, ...longPicks.value]
  if (allStocks.length === 0) {
    ElMessage.warning('暂无可回测的股票')
    return
  }
  batchVerifyLoading.value = true
  batchVerifyResults.value = null
  try {
    const stocks = allStocks.map(s => s.code).slice(0, 20)
    const today = new Date()
    const endDate = today.toISOString().slice(0, 10)
    const startDate = new Date(today.getTime() - 365 * 86400000).toISOString().slice(0, 10)
    const res = await backtestApi.batch({ stocks, strategy: 'macd', start_date: startDate, end_date: endDate })
    if (res.status === 'success') {
      batchVerifyResults.value = res.data
      ElMessage.success('批量回测完成，成功 ' + res.data.success_count + ' 只')
      batchDrawerVisible.value = true
    }
  } catch (e) {
    ElMessage.error('批量回测失败: ' + (e.message || ''))
  } finally {
    batchVerifyLoading.value = false
  }
}

// P0: 跳转到策略回测页（带预填参数）
function goToBacktest(stockCode, strategy) {
  const today = new Date()
  const endDate = today.toISOString().slice(0, 10)
  const startDate = new Date(today.getTime() - 365 * 86400000).toISOString().slice(0, 10)
  window.open('/strategy-backtest?stock=' + stockCode + '&strategy=' + (strategy || 'macd') + '&start_date=' + startDate + '&end_date=' + endDate, '_blank')
}

// P0: 获取回测评级标签类型
function getRatingType(rating) {
  const map = { '\u4F18\u79C0': 'success', '\u826F\u597D': '', '\u4E00\u822C': 'warning', '\u8F83\u5DEE': 'danger' }
  return map[rating] || 'info'
}

// P0: 格式化收益率显示

// P0: Map stock code to name from picks data
function getStockName(code) {
  const allPicks = [...shortPicks.value, ...longPicks.value]
  const found = allPicks.find(s => s.code === code)
  return found ? found.name : null
}

// 移动端：AI评分等级样式类
function scoreLevel(score) {
  if (score >= 80) return 'score-high'
  if (score >= 60) return 'score-mid'
  return 'score-low'
}

function formatReturn(val) {
  if (val == null) return '--'
  const num = parseFloat(val)
  const sign = num >= 0 ? '+' : ''
  return sign + num.toFixed(2) + '%'
}

</script>

<style scoped>
.report-page { position: relative; height: 100%; overflow-y: auto; padding: 12px; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
.header-left { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.page-title { display: flex; align-items: center; gap: 8px; color: #303133; font-size: 20px; margin: 0; white-space: nowrap; }
.disclaimer-inline { font-size: 12px; color: #909399; line-height: 1.4; }
.header-actions { display: flex; align-items: center; gap: 8px; }

.list-card, .report-card { height: calc(100vh - 160px); display: flex; flex-direction: column; }
.list-card :deep(.el-card__body), .report-card :deep(.el-card__body) { flex: 1; overflow: hidden; display: flex; flex-direction: column; }
.card-header { display: flex; align-items: center; justify-content: space-between; font-weight: 600; }

/* 报告列表 */
.report-list { overflow-y: auto; flex: 1; }
.report-item {
  padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 6px;
  transition: all 0.2s; border: 1px solid transparent;
}
.report-item:hover { background: #f5f7fa; }
.report-item.active { background: #ecf5ff; border-color: #409eff; }
.item-date { font-weight: 600; color: #303133; margin-bottom: 4px; }
.item-meta { display: flex; align-items: center; gap: 8px; }
.item-time { color: #909399; font-size: 12px; }

/* 报告内容 */
.report-content {
  overflow-y: auto; flex: 1; padding: 16px; line-height: 1.8; color: #303133; font-size: 14px;
}
.report-content :deep(.md-body h2) { font-size: 18px; margin: 16px 0 8px; color: #1a1a2e; border-bottom: 2px solid #409eff; padding-bottom: 6px; }
.report-content :deep(.md-body h3) { font-size: 16px; margin: 14px 0 6px; color: #303133; }
.report-content :deep(.md-body h4) { font-size: 15px; margin: 12px 0 4px; color: #606266; }
.report-content :deep(.md-body strong) { color: #409eff; }
.report-content :deep(.md-body li) { margin-left: 20px; margin-bottom: 4px; list-style: disc; }
.report-content :deep(.md-body p) { margin: 8px 0; }
.report-content :deep(.table-wrapper) {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 12px 0;

  &::-webkit-scrollbar { height: 4px; }
  &::-webkit-scrollbar-thumb { background: #dcdfe6; border-radius: 2px; }
}
.report-content :deep(table) {
  width: 100%; border-collapse: collapse; font-size: 13px; margin: 0;
}
.report-content :deep(th) {
  padding: 8px 12px; border: 1px solid #d0d7de; background: #f0f5ff; font-weight: 600; color: #303133; text-align: left;
}
.report-content :deep(td) {
  padding: 8px 12px; border: 1px solid #ebeef5; background: #fafafa;
}
.report-content :deep(tr:hover td) { background: #ecf5ff; }
.report-content :deep(blockquote) {
  margin: 12px 0; padding: 10px 16px; background: #fef9e7; border-left: 4px solid #e6a817; border-radius: 4px; color: #6b5900; font-size: 14px;
}
.report-content :deep(hr) {
  border: none; border-top: 1px solid #e4e7ed; margin: 16px 0;
}
.report-content :deep(code) {
  background: #f5f7fa; padding: 2px 6px; border-radius: 3px; font-size: 13px; color: #c41d7f;
}
.report-content :deep(pre) {
  background: #f5f7fa; padding: 12px; border-radius: 6px; overflow-x: auto; margin: 12px 0; font-size: 13px;
}
.report-content :deep(pre code) {
  background: none; padding: 0; color: inherit;
}
.report-content :deep(ul), .report-content :deep(ol) {
  margin: 8px 0; padding-left: 24px;
}

.report-placeholder { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 300px; color: #909399; }
.report-placeholder p { margin-top: 12px; }

/* 结构化数据展示样式 */
.outlook-section { margin-bottom: 20px; }
.outlook-grid { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px; }
.outlook-item { padding: 8px 16px; background: #f5f7fa; border-radius: 6px; font-size: 14px; }
.outlook-item .label { color: #909399; margin-right: 4px; }

.picks-table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }
.picks-table th { padding: 8px 12px; border: 1px solid #d0d7de; background: #f0f5ff; font-weight: 600; color: #303133; text-align: left; }
.picks-table td { padding: 8px 12px; border: 1px solid #ebeef5; background: #fafafa; }
.picks-table tr:hover td { background: #ecf5ff; }
.picks-table .price { color: #F56C6C; font-weight: 600; }

/* 桌面端结构化表格横向滚动容器（移动端有 mob-table-wrap） */
.picks-table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  margin: 12px 0;
  border-radius: 4px;

  &::-webkit-scrollbar { height: 4px; }
  &::-webkit-scrollbar-thumb { background: #dcdfe6; border-radius: 2px; }

  .picks-table { min-width: 600px; margin: 0; }
}

.strategy-section { margin-top: 20px; }
.strategy-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px; padding: 12px; }
.strategy-item .label { font-weight: 500; white-space: nowrap; }

.ai-analysis { margin-top: 12px; padding: 12px; background: #f5f7fa; border-radius: 6px; line-height: 1.6; font-size: 13px; }
.disclaimer-section { margin-top: 24px; padding: 16px; background: #fef9e7; border-left: 4px solid #e6a817; border-radius: 4px; }
.disclaimer-section p { margin: 4px 0; font-size: 13px; color: #6b5900; }

/* ═══════════════════════════════════════════
   移动端卡片化设计（AI股票推荐页）
   ═══════════════════════════════════════════ */

.mob-pick-container {
  padding: 0 4px calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0));
  overflow-x: visible !important;
}

/* 日期快速选择器卡 */
.mob-date-tabs {
  padding: 12px 0 8px !important;
  margin-bottom: 12px;
}

/* 推荐头部信息卡 */
.mob-report-header {
  margin-bottom: 12px;
}

/* 统计卡片行 - 移动端紧凑间距 */
.mob-stats {
  gap: 6px;
  margin-top: 12px;
  margin-bottom: 0;
}

.mob-stats .m-stat-card {
  padding: 10px 4px;
}

/* 生成中/失败状态区域 */
.mob-generating,
.mob-failed {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--m-border);
}

/* 报告内容卡 - Markdown渲染 */
.mob-report-body {
  padding: 12px !important;
  overflow-x: visible !important;
  margin-bottom: 12px;
}

.mob-md-content {
  font-size: 13px;
  line-height: 1.7;
  color: var(--m-text);
}

.mob-md-content :deep(h2) {
  font-size: 15px;
  margin: 16px 0 8px;
  padding-bottom: 6px;
  border-bottom: 2px solid var(--m-accent);
  color: var(--m-text);
  font-weight: 700;
}

.mob-md-content :deep(h3) {
  font-size: 14px;
  margin: 14px 0 6px;
  color: var(--m-text);
  font-weight: 600;
}

.mob-md-content :deep(p) {
  margin: 8px 0;
  line-height: 1.7;
}

.mob-md-content :deep(strong) {
  color: var(--m-accent);
  font-weight: 600;
}

.mob-md-content :deep(ul), .mob-md-content :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}

.mob-md-content :deep(li) {
  font-size: 13px;
  margin-bottom: 4px;
  line-height: 1.6;
}

/* Markdown表格横向滚动容器 */
.mob-md-content :deep(.table-wrapper) {
  overflow-x: auto !important;
  overflow-y: hidden !important;
  -webkit-overflow-scrolling: touch;
  width: 100% !important;
  margin: 8px 0 !important;
  padding: 0 !important;
  box-sizing: border-box !important;

  &::-webkit-scrollbar { height: 3px; }
  &::-webkit-scrollbar-thumb { background: var(--m-border); border-radius: 2px; }
}

.mob-md-content :deep(.table-wrapper table) {
  width: 100% !important;
  min-width: max-content !important;
  font-size: 11px !important;
  border-collapse: collapse !important;
  margin: 0 auto !important;

  th, td {
    padding: 6px 8px !important;
    font-size: 11px !important;
    box-sizing: border-box !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
  }

  th {
    background: var(--m-surface2) !important;
    font-weight: 600 !important;
    color: var(--m-text) !important;
    border: 1px solid var(--m-border) !important;
  }

  td {
    border: 1px solid var(--m-border) !important;
  }

  th:last-child, td:last-child {
    white-space: normal !important;
    word-break: break-word !important;
  }
}

/* 空状态/加载中占位 */
.mob-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

/* 股票推荐卡片 */
.mob-pick-card {
  position: relative;
  overflow: hidden;
}

.mob-pick-top {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mob-pick-rank {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  background: #f0f2f5;
  color: #8e99ab;
  flex-shrink: 0;
}

.mob-pick-rank.r1 {
  background: rgba(231, 76, 60, 0.1);
  color: #e74c3c;
}

.mob-pick-rank.r2 {
  background: rgba(230, 126, 34, 0.1);
  color: #e67e22;
}

.mob-pick-rank.r3 {
  background: rgba(127, 140, 141, 0.1);
  color: #7f8c8d;
}

.mob-pick-info {
  flex: 1;
  min-width: 0;
}

.mob-pick-name {
  font-size: 15px;
  font-weight: 600;
  color: #1a2332;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mob-pick-code {
  font-size: 11px;
  color: #8e99ab;
  margin-top: 2px;
}

/* AI评分徽章 */
.mob-pick-score {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4px 10px;
  border-radius: 12px;
  flex-shrink: 0;
}

.mob-pick-score-val {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
}

.mob-pick-score-label {
  font-size: 9px;
  opacity: 0.7;
}

.score-high {
  background: rgba(231, 76, 60, 0.08);
  color: #e74c3c;
}

.score-mid {
  background: rgba(91, 124, 250, 0.08);
  color: #5b7cfa;
}

.score-low {
  background: rgba(142, 153, 171, 0.1);
  color: #8e99ab;
}

/* 卡片底部：价格 + 推荐理由 */
.mob-pick-bottom {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #e0e4ea;
}

.mob-pick-price {
  font-size: 16px;
  font-weight: 700;
  color: #e74c3c;
  flex-shrink: 0;
}

.mob-pick-reason {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: #5a6577;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

/* 回测结果行动区 */
.mob-pick-action {
  margin-top: 8px;
  font-size: 12px;
  color: #5a6577;
  display: flex;
  align-items: center;
  gap: 4px;
}

/* 风险提示卡片 */
.mob-disclaimer {
  background: rgba(240, 180, 41, 0.06) !important;
  border: 1px solid rgba(240, 180, 41, 0.2);
}



/* ═══════════════════════════════════════════
   响应式覆盖（max-width: 768px）
   ═══════════════════════════════════════════ */
@media (max-width: 768px) {
  .report-page { padding: 4px 8px; position: absolute !important; top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important; overflow-y: auto !important; overflow-x: visible !important; }

  /* 移动端 header 已有标题，隐藏页面内部重复标题 */
  .page-title { display: none !important; }
  .disclaimer-inline { display: none !important; }

  .page-header { flex-direction: row; align-items: center; justify-content: flex-end; gap: 4px; margin-bottom: 4px; width: 100%; }
  .header-left { display: none !important; }

  /* 桌面端按钮在移动端隐藏 */
  .desktop-only { display: none !important; }

  .header-actions.mobile-header {
    width: 100%;
    justify-content: flex-start;
    flex-wrap: nowrap;
    gap: 2px;
    align-items: center;

    :deep(.el-date-picker) { flex: 1; min-width: 80px; max-width: 140px; }
    :deep(.el-date-editor) { border-radius: 6px !important; }
    :deep(.el-input__wrapper) { box-shadow: none !important; border: 1px solid #e0e4ea !important; padding: 0 8px !important; }
    :deep(.el-input__inner) { font-size: 12px !important; height: 30px; line-height: 30px; }

    .mobile-refresh,
    .mobile-gen-btn,
    .mobile-batch-btn {
      flex-shrink: 0;
      font-size: 12px !important;
      padding: 4px 8px !important;
      min-height: 30px !important;
      line-height: 30px !important;
      height: 30px !important;
      border-radius: 6px !important;
    }

    .mobile-refresh { color: #409eff; background: rgba(64,158,255,0.06); }
    .mobile-gen-btn { color: #e6a23c; background: rgba(230,162,60,0.06); }
    .mobile-batch-btn { color: #909399; background: rgba(144,147,153,0.06); }
  }

  .list-card, .report-card { height: auto; min-height: 0; }

  /* 移动端卡片容器覆盖 */
  .mob-pick-container { padding: 0 2px calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0)); }

  /* m-stats-row 在极小屏幕下调为3列→保持，但缩小间距 */
  .m-stats-row { gap: 6px !important; }
  .m-stat-card { padding: 10px 4px !important; }
  .m-stat-card .val { font-size: 14px !important; }
  .m-stat-card .lbl { font-size: 9px !important; }

  /* m-section-header 紧凑 */
  .m-section-header { padding: 10px 0 4px !important; font-size: 14px !important; }

  /* 股票卡片紧凑模式 */
  .mob-pick-card { padding: 12px !important; margin-bottom: 8px !important; }
  .mob-pick-name { font-size: 14px !important; }
  .mob-pick-price { font-size: 15px !important; }
  .mob-pick-score-val { font-size: 16px !important; }

  /* 隐藏桌面端专属元素 */
  .picks-table-wrap,
  .strategy-section,
  .disclaimer-section { display: none !important; }

  /* el-drawer 全宽 */
  :deep(.el-drawer) { width: 100% !important; }
}

@media (max-width: 480px) {
  .page-title { font-size: 15px !important; }

  .header-actions.mobile-header :deep(.el-date-picker) { min-width: 70px; max-width: 120px; }
  .header-actions.mobile-header :deep(.el-input__inner) { font-size: 11px !important; height: 28px; line-height: 28px; }
  .header-actions.mobile-header .mobile-refresh,
  .header-actions.mobile-header .mobile-gen-btn,
  .header-actions.mobile-header .mobile-batch-btn {
    font-size: 11px !important;
    padding: 3px 6px !important;
    min-height: 28px !important;
    line-height: 28px !important;
    height: 28px !important;
  }

  /* 极小屏幕：统计卡片缩小 */
  .m-stats-row { grid-template-columns: repeat(3, 1fr) !important; gap: 4px !important; }
  .m-stat-card { padding: 8px 2px !important; border-radius: 10px !important; }
  .m-stat-card .val { font-size: 13px !important; }
  .m-stat-card .lbl { font-size: 8px !important; }

  /* 股票卡片更紧凑 */
  .mob-pick-card { padding: 10px !important; margin-bottom: 6px !important; border-radius: 12px !important; }
  .mob-pick-rank { width: 24px !important; height: 24px !important; font-size: 11px !important; }
  .mob-pick-name { font-size: 13px !important; }
  .mob-pick-price { font-size: 14px !important; }
  .mob-pick-score-val { font-size: 15px !important; }
  .mob-pick-score-label { font-size: 8px !important; }
}

/* P0: 回测验证样式 */

.batch-summary { display: flex; gap: 16px; margin-bottom: 12px; font-size: 13px; color: #909399; flex-wrap: wrap; }
.summary-item { background: #f5f7fa; padding: 4px 12px; border-radius: 4px; }
.backtest-rank-table .rank-cell { font-weight: bold; text-align: center; }
.backtest-inline-result { padding: 8px; }
.bt-score-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.bt-label { color: #909399; font-size: 12px; min-width: 60px; }
.bt-metrics-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 12px; }
.bt-metric { display: flex; justify-content: space-between; padding: 6px 12px; background: #f5f7fa; border-radius: 4px; font-size: 13px; }
.positive { color: #f56c6c !important; font-weight: 600; }
.negative { color: #67c23a !important; }


/* P0: 抽屉回测样式 */
.drawer-backtest-content { padding: 0 8px; }

/* ═══════════════════════════════════════════
   移动端批量回测卡片样式
   ═══════════════════════════════════════════ */

.mob-bt-card-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px 0 12px;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

.mob-bt-card {
  position: relative;
  overflow: visible !important;
  padding: 14px 12px !important;
}

/* 卡片顶部：排名 + 股票信息 + 总收益 */
.mob-bt-top {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.mob-bt-rank {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  background: var(--m-surface2, #f0f2f5);
  color: var(--m-text3, #8e99ab);
  flex-shrink: 0;
}

.mob-bt-rank.r1 {
  background: linear-gradient(135deg, #f56c6c, #e74c3c);
  color: #fff;
}

.mob-bt-rank.r2 {
  background: linear-gradient(135deg, #e6a23c, #f0a040);
  color: #fff;
}

.mob-bt-rank.r3 {
  background: linear-gradient(135deg, #7f8c8d, #95a5a6);
  color: #fff;
}

.mob-bt-info {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.mob-bt-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--m-text, #1a2332);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mob-bt-code {
  font-size: 10px;
  color: var(--m-text3, #8e99ab);
  margin-top: 1px;
}

/* 总收益大字 */
.mob-bt-return {
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
  text-align: right;
  min-width: 80px;
  white-space: nowrap;
}

.mob-bt-return.up { color: var(--m-up, #e74c3c); }
.mob-bt-return.down { color: var(--m-down, #2ecc71); }

/* 指标网格 */
.mob-bt-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--m-border, #e0e4ea);
}

.mob-bt-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  background: var(--m-surface2, #f0f2f5);
  border-radius: 6px;
}

.mob-bt-m-label {
  font-size: 9.5px;
  color: var(--m-text3, #8e99ab);
}

.mob-bt-metric span:last-child {
  font-size: 12px;
  font-weight: 600;
  color: var(--m-text, #1a2332);
}

.mob-bt-metric .up { color: var(--m-up, #e74c3c) !important; }
.mob-bt-metric .down { color: var(--m-down, #2ecc71) !important; }

/* 失败列表 */
.bt-failed-section {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--m-border, #e0e4ea);
}

.bt-failed-item {
  padding: 4px 0;
  font-size: 12px;
  color: var(--m-text3, #909399);
}

/* 移动端抽屉内样式覆盖 */
@media (max-width: 768px) {
  .drawer-backtest-content { padding: 0 4px; }

  .batch-summary {
    gap: 6px !important;
    flex-wrap: wrap;
  }

  .batch-summary .summary-item {
    font-size: 11px !important;
    padding: 3px 8px !important;
  }

  .mob-bt-card-list {
    padding: 4px 0 60px;
  }

  .mob-bt-card {
    padding: 12px 10px !important;
  }

  .mob-bt-rank {
    width: 20px !important;
    height: 20px !important;
    font-size: 10px !important;
  }

  .mob-bt-name {
    font-size: 13px !important;
  }

  .mob-bt-return {
    font-size: 14px !important;
    min-width: 70px !important;
  }

  .mob-bt-metrics {
    grid-template-columns: repeat(2, 1fr) !important;
    gap: 4px !important;
    margin-top: 8px !important;
    padding-top: 8px !important;
  }

  .mob-bt-metric {
    padding: 5px 6px !important;
    border-radius: 4px !important;
  }

  .mob-bt-m-label {
    font-size: 9px !important;
  }

  .mob-bt-metric span:last-child {
    font-size: 11px !important;
  }
}

</style>


