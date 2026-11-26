<template>
  <div class="stock-diagnosis">
    <!-- 后台刷新指示器 -->
    <RefreshingIndicator :show="(diagnosis.refreshing.value) && !loading" />

    <h2 class="page-title">
      <el-icon><DataLine /></el-icon>
      个股诊断
    </h2>

    <el-card shadow="hover" class="search-card">
      <el-autocomplete v-model="query" :fetch-suggestions="querySearch" :trigger-on-focus="false"
        placeholder="输入股票代码或名称，如：600519、中国平安"
        :size="inputSize" clearable :disabled="loading" value-key="name"
        @select="handleSuggestSelect">
        <template #prepend>股票</template>
        <template #append>
          <el-button class="diagnose-btn" @click="doDiagnosis" :disabled="loading">
            <el-icon><Search /></el-icon> {{ loading ? '诊断中...' : '开始诊断' }}
          </el-button>
        </template>
      </el-autocomplete>
      <div class="quick-tags">
        <span class="label">快捷:</span>
        <el-tag v-for="s in quickStocks" :key="s.code" class="qtag" @click="quickPick(s)" effect="plain" size="small">{{ s.name }}</el-tag>
      </div>
    </el-card>

    <el-card v-if="loading" shadow="never" class="result-card">
      <el-skeleton :rows="12" animated />
    </el-card>

    <el-card v-if="diagnosisFailed" shadow="never" class="result-card">
      <div class="diag-error">
        <el-icon :size="48" color="#E6A23C"><WarningFilled /></el-icon>
        <p class="diag-error-title">诊断数据加载失败</p>
        <p class="diag-error-msg">{{ diagnosisErrorMsg }}</p>
        <el-button type="primary" @click="doDiagnosis">重新诊断</el-button>
      </div>
    </el-card>

    <template v-if="techData && !loading">
      <!-- ════════ 移动端卡片布局 ════════ -->
      <template v-if="isMobile">
        <!-- 综合评分环 -->
        <div class="m-diag-score" v-if="assessData">
          <div class="m-score-ring">
            <div class="ring" :style="{ background: scoreRingGradient }">
              <span class="val">{{ weightedScore ?? '--' }}</span>
            </div>
            <div class="detail">
              <div class="row"><span class="lbl">诊断结论</span><span class="v" :class="'score-' + conclusionLevel.level">{{ scoreLevelTitle }}</span></div>
              <div class="row"><span class="lbl">技术面</span><span class="v">{{ scoreBreakdownList[0]?.score ?? '--' }}</span></div>
              <div class="row"><span class="lbl">基本面</span><span class="v">{{ scoreBreakdownList[1]?.score ?? '--' }}</span></div>
              <div class="row"><span class="lbl">资金面</span><span class="v">{{ scoreBreakdownList[2]?.score ?? '--' }}</span></div>
            </div>
          </div>
        </div>

        <!-- 实时行情 Stats Row -->
        <template v-if="rtItems.length">
          <div class="m-section-header">实时行情 <span class="meta">{{ stockName }} ({{ query }})</span></div>
          <div class="m-stats-row" style="grid-template-columns: repeat(4, 1fr);">
            <div class="m-stat-card" v-for="(item, i) in rtItems.slice(0, 8)" :key="'rt-' + i">
              <div class="val" :class="item.cls === 'c-red' ? 'up' : item.cls === 'c-green' ? 'down' : ''">{{ item.value }}</div>
              <div class="lbl">{{ item.label }}</div>
            </div>
          </div>
        </template>

        <!-- 操作建议卡片 -->
        <div class="m-card" v-if="pricePlan">
          <div class="m-card-header">操作建议</div>
          <div class="m-diag-metric-row"><span class="lbl">买入区间</span><span class="val">¥{{ pricePlan.buyLow }}-{{ pricePlan.buyHigh }}</span></div>
          <div class="m-diag-metric-row"><span class="lbl">止损位</span><span class="val down">¥{{ pricePlan.stopLoss }}</span></div>
          <div class="m-diag-metric-row"><span class="lbl">保守目标</span><span class="val up">¥{{ pricePlan.target1 }}</span></div>
          <div class="m-diag-metric-row"><span class="lbl">中性目标</span><span class="val up">¥{{ pricePlan.target2 }}</span></div>
          <div class="m-diag-metric-row"><span class="lbl">乐观目标</span><span class="val up">¥{{ pricePlan.target3 }}</span></div>
          <div class="m-diag-metric-row" v-if="positionAdvice"><span class="lbl">建议仓位</span><span class="val accent">{{ positionAdvice.ratio }} ({{ positionAdvice.text }})</span></div>
        </div>

        <!-- 分周期建议 -->
        <div class="m-card" v-if="multiPeriodAdvice">
          <div class="m-card-header">分周期建议</div>
          <div class="m-diag-metric-row"><span class="lbl">短线1-3日</span><span class="val" :class="multiPeriodAdvice.short.type === 'positive' ? 'up' : multiPeriodAdvice.short.type === 'negative' ? 'down' : ''">{{ multiPeriodAdvice.short.text }}</span></div>
          <div class="m-diag-metric-row"><span class="lbl">中线1-2周</span><span class="val" :class="multiPeriodAdvice.mid.type === 'positive' ? 'up' : multiPeriodAdvice.mid.type === 'negative' ? 'down' : ''">{{ multiPeriodAdvice.mid.text }}</span></div>
          <div class="m-diag-metric-row"><span class="lbl">长线1-3月</span><span class="val" :class="multiPeriodAdvice.long.type === 'positive' ? 'up' : multiPeriodAdvice.long.type === 'negative' ? 'down' : ''">{{ multiPeriodAdvice.long.text }}</span></div>
        </div>

        <!-- K线图 -->
        <div class="m-card" v-if="stockCode">
          <div class="m-card-header">K线图表</div>
          <div class="m-ktabs">
            <span class="m-ktab" :class="{ active: klinePeriod === 'daily' }" @click="klinePeriod = 'daily'">日K</span>
            <span class="m-ktab" :class="{ active: klinePeriod === 'weekly' }" @click="klinePeriod = 'weekly'">周K</span>
            <span class="m-ktab" :class="{ active: klinePeriod === 'monthly' }" @click="klinePeriod = 'monthly'">月K</span>
          </div>
          <KlineChart :stock-code="stockCode" :period="klinePeriod" :height="220" @error="handleKlineError" />
        </div>

        <!-- 算法信号矩阵 -->
        <template v-if="decisionData">
          <div class="m-section-header">算法信号矩阵 <span class="meta">{{ algoSignalSummary ? `${algoSignalSummary.buyCount}买/${algoSignalSummary.sellCount}卖` : '加载中...' }}</span></div>
          <div class="m-card" style="padding: 0;">
            <!-- 综合评分 -->
            <div class="m-algo-score-header">
              <div class="m-algo-ring" :style="{ background: `conic-gradient(${getDecisionSignalColor(decisionData.composite_score)} ${(decisionData.composite_score || 0) * 3.6}deg, var(--m-border) ${(decisionData.composite_score || 0) * 3.6}deg 360deg)` }">
                <span class="val">{{ decisionData.composite_score ?? '--' }}</span>
              </div>
              <div class="m-algo-info">
                <div class="m-algo-badge" :class="getDecisionSignalClass(decisionData.overall_signal)">
                  {{ decisionSignalTextMap[decisionData.overall_signal] || '中性观望' }}
                </div>
                <div class="m-algo-count">{{ algoSignalSummary ? `${algoSignalSummary.buyCount}买/${algoSignalSummary.sellCount}卖/${algoSignalSummary.neutralCount}中` : '' }}</div>
              </div>
            </div>
            <!-- 算法列表 -->
            <div class="m-algo-list">
              <div class="m-algo-item" v-for="(algo, i) in algoSignalList" :key="i">
                <div class="m-algo-name">{{ algo.name }}</div>
                <div class="m-algo-signal" :class="getDecisionSignalClass(algo.data?.signal)">
                  {{ (algo.data?.signal === 'buy') ? '买入' : (algo.data?.signal === 'sell') ? '卖出' : '中性' }}
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- 技术指标信号 Pills -->
        <template v-if="techTable.length">
          <div class="m-section-header">技术指标 <span class="meta">{{ buySignals.length }}买 / {{ sellSignals.length }}卖</span></div>
          <div class="m-pills">
            <div class="m-pill" v-for="(item, i) in techTable.slice(0, 12)" :key="'pill-' + i">
              {{ item.name }}<span class="v" :class="item.signalType === 'danger' ? 'up' : item.signalType === 'success' ? 'down' : 'ok'">{{ formatTechVal(item.value) }}</span>
            </div>
          </div>
        </template>

        <!-- 买卖信号 -->
        <div class="m-card" v-if="topBuyReasons.length || topSellReasons.length">
          <div class="m-card-header">买卖信号</div>
          <template v-if="topBuyReasons.length">
            <div class="m-alert-item" v-for="(r, i) in topBuyReasons.slice(0, 3)" :key="'buy-' + i">
              <span class="dot red"></span>
              <div class="body"><div class="title">{{ r }}</div></div>
            </div>
          </template>
          <template v-if="topSellReasons.length">
            <div class="m-alert-item" v-for="(r, i) in topSellReasons.slice(0, 3)" :key="'sell-' + i">
              <span class="dot green"></span>
              <div class="body"><div class="title">{{ r }}</div></div>
            </div>
          </template>
        </div>

        <!-- K线形态识别 -->
        <template v-if="patternList.length">
          <div class="m-section-header">K线形态 <span class="meta">{{ patternList.length }}条</span></div>
          <div class="m-card">
            <div class="m-filter-bar" style="margin-bottom: 8px;">
              <span class="fil" :class="{ active: patternDirectionFilter === 'all' }" @click="patternDirectionFilter = 'all'">全部</span>
              <span class="fil" :class="{ active: patternDirectionFilter === 'bullish' }" @click="patternDirectionFilter = 'bullish'" style="--m-accent: var(--m-up);">看涨</span>
              <span class="fil" :class="{ active: patternDirectionFilter === 'bearish' }" @click="patternDirectionFilter = 'bearish'" style="--m-accent: var(--m-down);">看跌</span>
            </div>
            <div class="m-rank-item" v-for="(row, i) in displayPatterns.slice(0, 6)" :key="'pat-' + i">
              <div class="rank" :class="i < 3 ? 'r' + (i + 1) : ''">{{ i + 1 }}</div>
              <div class="body">
                <div class="name">{{ row.name }} {{ row.direction === 'bullish' ? '(看涨)' : row.direction === 'bearish' ? '(看跌)' : '' }}</div>
                <div class="sub">{{ row.date }}</div>
              </div>
              <div class="aside">
                <span style="font-size: 13px; font-weight: 700;" :style="{ color: getConfidenceColor(row) }">{{ Math.round((row.confidence || 0.5) * 100) }}%</span>
              </div>
            </div>
          </div>
        </template>

        <!-- 财务数据 -->
        <template v-if="financialData && finItems.length">
          <div class="m-section-header">财务数据</div>
          <div class="m-stats-row" style="grid-template-columns: repeat(4, 1fr);">
            <div class="m-stat-card" v-for="(item, i) in finItems.slice(0, 8)" :key="'fin-' + i">
              <div class="val" :class="item.cls === 'c-red' ? 'up' : item.cls === 'c-green' ? 'down' : ''">{{ item.value }}</div>
              <div class="lbl">{{ item.label }}</div>
            </div>
          </div>
        </template>

        <!-- 资金流 -->
        <div class="m-card" v-if="flowTrend">
          <div class="m-card-header">资金流向</div>
          <div class="m-diag-metric-row"><span class="lbl">今日主力</span><span class="val" :class="flowTrend.today.cls === 'c-red' ? 'up' : flowTrend.today.cls === 'c-green' ? 'down' : ''">{{ flowTrend.today.text }}</span></div>
          <div class="m-diag-metric-row"><span class="lbl">大单净额</span><span class="val" :class="flowTrend.bigNet.cls === 'c-red' ? 'up' : flowTrend.bigNet.cls === 'c-green' ? 'down' : ''">{{ flowTrend.bigNet.text }}</span></div>
          <div class="m-diag-metric-row"><span class="lbl">中单净额</span><span class="val" :class="flowTrend.midNet.cls === 'c-red' ? 'up' : flowTrend.midNet.cls === 'c-green' ? 'down' : ''">{{ flowTrend.midNet.text }}</span></div>
          <div class="m-diag-metric-row"><span class="lbl">小单净额</span><span class="val" :class="flowTrend.smallNet.cls === 'c-red' ? 'up' : flowTrend.smallNet.cls === 'c-green' ? 'down' : ''">{{ flowTrend.smallNet.text }}</span></div>
        </div>

        <!-- 综合分析 -->
        <div class="m-card" v-if="analysisLines.length">
          <div class="m-card-header">综合分析</div>
          <div class="m-alert-item" v-for="(line, i) in analysisLines.slice(0, 5)" :key="'anal-' + i">
            <span class="dot" :class="i === analysisLines.length - 1 ? 'gold' : 'blue'"></span>
            <div class="body"><div class="title">{{ line }}</div></div>
          </div>
        </div>

        <!-- 消息面 -->
        <template v-if="stockCode">
          <div class="m-section-header">消息面 <span class="meta">{{ newsList.length }}条</span></div>
          <div class="m-card" style="padding: 0; overflow: hidden;">
            <div class="m-rank-item" v-for="(n, i) in newsList.slice(0, 5)" :key="'news-' + i" @click="openNews(n)">
              <div class="body">
                <div class="name">{{ n.title }}</div>
                <div class="sub">{{ n.date }} · {{ n.source || '资讯' }}</div>
              </div>
            </div>
          </div>
        </template>

        <!-- 风险提示 -->
        <div class="m-card" v-if="riskReasons.length" style="background: #fff8e1; border-color: #ffecb3;">
          <div class="m-card-header" style="color: #e6a23c;">⚠️ 风险提示</div>
          <div class="m-alert-item" v-for="(r, i) in riskReasons.slice(0, 3)" :key="'risk-' + i">
            <span class="dot gold"></span>
            <div class="body"><div class="title">{{ r }}</div></div>
          </div>
        </div>
      </template>

      <!-- ════════ 桌面端布局（原代码不变） ════════ -->
      <!-- 实时行情 -->
      <el-card shadow="hover" class="result-card desktop-only" v-if="rtItems.length">
        <template #header><span>实时行情 — {{ stockName }} ({{ query }})</span></template>
        <el-row :gutter="12">
          <el-col :xs="12" :sm="8" :md="4" :lg="3" v-for="item in rtItems" :key="item.label">
            <div class="rt-item">
              <div class="rt-label">{{ item.label }}</div>
              <div class="rt-value" :class="item.cls">{{ item.value }}</div>
            </div>
          </el-col>
        </el-row>
        <div class="section-analysis" v-if="rtAnalysis">
          <el-icon><DataLine /></el-icon>
          <span>{{ rtAnalysis }}</span>
        </div>
      </el-card>

      <!-- 综合诊断结论（核心决策信息前置） -->
      <el-card shadow="hover" class="result-card assess-card desktop-only" v-if="assessData">
        <template #header>
          <div class="card-header">
            <div class="title-block">
              <span class="title-main">综合诊断结论</span>
              <span class="title-sub">技术面65% + 基本面25% + 资金面10%</span>
              <span class="title-time" v-if="diagnoseTime">· 数据更新 {{ diagnoseTime }}</span>
            </div>
            <div class="header-right">
              <div class="score-box" :class="scoreClass">
                <span class="score-value">{{ weightedScore ?? '--' }}</span>
                <span class="score-max">/100</span>
                <span class="score-level-title" v-if="weightedScore != null">{{ scoreLevelTitle }}</span>
              </div>
              <el-tooltip :content="riskReasons.length ? riskReasons.join('；') : '暂无风险提示'" placement="top" :show-after="200">
                <div class="risk-stars" :class="riskClass">{{ riskStars }}</div>
              </el-tooltip>
            </div>
          </div>
        </template>

        <!-- 评分构成 + 风险提示（合并紧凑布局） -->
        <div class="score-risk-section" v-if="scoreBreakdown">
          <div class="score-breakdown">
            <div class="sb-row" v-for="item in scoreBreakdownList" :key="item.key">
              <div class="sb-label">
                <span class="sb-name">{{ item.name }}</span>
                <span class="sb-weight">{{ item.weightText }}</span>
              </div>
              <div class="sb-bar-wrap">
                <div class="sb-bar" :style="{ width: item.score + '%', background: item.color }"></div>
              </div>
              <div class="sb-score" :style="{ color: item.color }">{{ item.score }}</div>
            </div>
          </div>
          <div class="risk-tags-inline" v-if="riskReasons.length">
            <el-icon class="risk-icon"><WarningFilled /></el-icon>
            <el-tag v-for="(r, i) in riskReasons.slice(0, 3)" :key="i" type="warning" size="small" effect="plain" class="risk-tag">{{ r }}</el-tag>
          </div>
        </div>

        <!-- 结论 + 关键位 + 消息面（合并一行） -->
        <div class="decision-strip">
          <el-alert :title="assessData.title" :type="assessData.type" show-icon :closable="false" class="decision-alert" />
          <div class="key-levels" v-if="assessData.support || assessData.resist">
            <el-tag type="success" size="small" v-if="assessData.resist">压力 ¥{{ assessData.resist }}</el-tag>
            <el-tag type="danger" size="small" v-if="assessData.support">支撑 ¥{{ assessData.support }}</el-tag>
          </div>
          <div class="news-sentiment-inline" v-if="newsSentiment">
            <el-tag :type="newsSentiment.type === 'positive' ? 'danger' : newsSentiment.type === 'negative' ? 'success' : 'info'" size="small" effect="dark">
              {{ newsSentiment.text }}
            </el-tag>
          </div>
        </div>

        <!-- 风险与得分冲突警示 -->
        <el-alert v-if="riskConflict" type="warning" show-icon :closable="false" class="risk-conflict-alert"
          title="注意：综合评分偏高但存在多个风险因素" />

        <!-- 综合分析（紧凑列表） -->
        <div class="analysis-block" v-if="analysisLines.length">
          <ul class="analysis-list">
            <li v-for="(line, i) in analysisLines" :key="i" class="analysis-item">
              <span class="dot" :class="getAnalysisDotClass(i, analysisLines.length)"></span>
              <span class="text">{{ line }}</span>
            </li>
          </ul>
        </div>

        <!-- 操作建议 + 分周期 + 近期表现 + 资金流（2 列网格） -->
        <div class="metrics-grid">
          <div class="metric-card">
            <div class="metric-title"><el-icon><Money /></el-icon><span>操作建议</span></div>
            <div class="metric-body" v-if="pricePlan">
              <div class="m-row"><span class="m-label">买入区间</span><span class="m-val">¥{{ pricePlan.buyLow }}-{{ pricePlan.buyHigh }}</span></div>
              <div class="m-row"><span class="m-label">止损位</span><span class="m-val">¥{{ pricePlan.stopLoss }}<em class="m-pct">{{ pricePlan.stopPct == null ? '--' : (pricePlan.stopPct > 0 ? '+' : '') + pricePlan.stopPct + '%' }}</em></span></div>
              <div class="m-row"><span class="m-label">保守目标</span><span class="m-val">¥{{ pricePlan.target1 }}<em class="m-pct">{{ pricePlan.target1Pct == null ? '--' : (pricePlan.target1Pct > 0 ? '+' : '') + pricePlan.target1Pct + '%' }}</em></span></div>
              <div class="m-row"><span class="m-label">中性目标</span><span class="m-val">¥{{ pricePlan.target2 }}<em class="m-pct">{{ pricePlan.target2Pct == null ? '--' : (pricePlan.target2Pct > 0 ? '+' : '') + pricePlan.target2Pct + '%' }}</em></span></div>
              <div class="m-row"><span class="m-label">乐观目标</span><span class="m-val">¥{{ pricePlan.target3 }}<em class="m-pct">{{ pricePlan.target3Pct == null ? '--' : (pricePlan.target3Pct > 0 ? '+' : '') + pricePlan.target3Pct + '%' }}</em></span></div>
              <div class="m-row position-row" v-if="positionAdvice"><span class="m-label">建议仓位</span><span class="m-val">{{ positionAdvice.ratio }} ({{ positionAdvice.text }})</span></div>
            </div>
            <div class="metric-empty" v-else>--</div>
          </div>

          <div class="metric-card">
            <div class="metric-title"><el-icon><Clock /></el-icon><span>分周期建议</span></div>
            <div class="metric-body" v-if="multiPeriodAdvice">
              <div class="m-row"><span class="m-label">短线1-3日</span><span class="m-val" :class="multiPeriodAdvice.short.type">{{ multiPeriodAdvice.short.text }}</span></div>
              <div class="m-row"><span class="m-label">中线1-2周</span><span class="m-val" :class="multiPeriodAdvice.mid.type">{{ multiPeriodAdvice.mid.text }}</span></div>
              <div class="m-row"><span class="m-label">长线1-3月</span><span class="m-val" :class="multiPeriodAdvice.long.type">{{ multiPeriodAdvice.long.text }}</span></div>
            </div>
            <div class="metric-empty" v-else>--</div>
          </div>

          <div class="metric-card">
            <div class="metric-title"><el-icon><DataLine /></el-icon><span>近期表现</span></div>
            <div class="metric-body" v-if="recentPerformance">
              <div class="m-row" v-for="r in recentPerformance" :key="r.label"><span class="m-label">{{ r.label }}</span><span class="m-val" :class="r.cls">{{ r.text }}</span></div>
            </div>
            <div class="metric-empty" v-else>--</div>
          </div>

          <div class="metric-card">
            <div class="metric-title"><el-icon><Coin /></el-icon><span>资金流</span></div>
            <div class="metric-body" v-if="flowTrend">
              <div class="m-row"><span class="m-label">今日主力</span><span class="m-val" :class="flowTrend.today.cls">{{ flowTrend.today.text }}</span></div>
              <div class="m-row"><span class="m-label">大单净额</span><span class="m-val" :class="flowTrend.bigNet.cls">{{ flowTrend.bigNet.text }}</span></div>
              <div class="m-row"><span class="m-label">中单净额</span><span class="m-val" :class="flowTrend.midNet.cls">{{ flowTrend.midNet.text }}</span></div>
              <div class="m-row"><span class="m-label">小单净额</span><span class="m-val" :class="flowTrend.smallNet.cls">{{ flowTrend.smallNet.text }}</span></div>
              <div class="m-row" v-if="flowTrend.flow3d.cls !== 'flow-na'"><span class="m-label">3日累计</span><span class="m-val" :class="flowTrend.flow3d.cls">{{ flowTrend.flow3d.text }}</span></div>
            </div>
            <div class="metric-empty" v-else>--</div>
          </div>
        </div>

        <!-- 买卖理由（紧凑标签式） -->
        <div class="signals-compact" v-if="topBuyReasons.length || topSellReasons.length">
          <div class="signal-row buy" v-if="topBuyReasons.length">
            <el-icon class="signal-icon"><CaretBottom /></el-icon>
            <el-tag v-for="(r, i) in topBuyReasons.slice(0, 3)" :key="i" type="danger" size="small" effect="plain" class="signal-tag">{{ r }}</el-tag>
          </div>
          <div class="signal-row sell" v-if="topSellReasons.length">
            <el-icon class="signal-icon"><CaretTop /></el-icon>
            <el-tag v-for="(r, i) in topSellReasons.slice(0, 3)" :key="i" type="success" size="small" effect="plain" class="signal-tag">{{ r }}</el-tag>
          </div>
        </div>
      </el-card>

      <!-- K线图 -->
      <el-card shadow="hover" class="result-card desktop-only" v-if="techData && !loading">
        <template #header>
          <div class="kline-header">
            <span class="kline-title">K线图表 — {{ stockName }} ({{ query }})</span>
            <el-radio-group v-model="klinePeriod" size="small" class="kline-period-group">
              <el-radio-button value="daily">日K</el-radio-button>
              <el-radio-button value="weekly">周K</el-radio-button>
              <el-radio-button value="monthly">月K</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <KlineChart v-if="stockCode" :stock-code="stockCode" :period="klinePeriod" :height="420" @error="handleKlineError" />
      </el-card>

      <!-- 算法信号矩阵 - 决策中心 -->
      <el-card shadow="hover" class="result-card algo-matrix-card desktop-only" v-if="decisionData">
        <template #header>
          <div class="card-header">
            <div class="title-block">
              <span class="title-main">算法信号矩阵</span>
              <span class="title-sub">7大算法综合评估 · 决策中心</span>
            </div>
            <div class="algo-summary-badge" v-if="algoSignalSummary">
              <span class="summary-buy">{{ algoSignalSummary.buyCount }}买</span>
              <span class="summary-sell">{{ algoSignalSummary.sellCount }}卖</span>
              <span class="summary-neutral">{{ algoSignalSummary.neutralCount }}中</span>
            </div>
          </div>
        </template>

        <!-- 综合评分 -->
        <div class="algo-score-section">
          <div class="algo-ring-container">
            <div class="algo-ring" :style="{ background: `conic-gradient(${getDecisionSignalColor(decisionData.composite_score)} ${(decisionData.composite_score || 0) * 3.6}deg, #f0f2f5 ${(decisionData.composite_score || 0) * 3.6}deg 360deg)` }">
              <div class="algo-ring-inner">
                <span class="algo-score-val">{{ decisionData.composite_score ?? '--' }}</span>
                <span class="algo-score-label">综合分</span>
              </div>
            </div>
          </div>
          <div class="algo-overall-info">
            <div class="algo-signal-badge" :class="getDecisionSignalClass(decisionData.overall_signal)">
              {{ decisionSignalTextMap[decisionData.overall_signal] || '中性观望' }}
            </div>
            <div class="algo-stock-name">{{ stockName }} ({{ query }})</div>
          </div>
        </div>

        <!-- 算法信号网格 -->
        <div class="algo-grid">
          <div class="algo-cell" v-for="(algo, i) in algoSignalList" :key="i">
            <div class="algo-cell-header">
              <span class="algo-cell-name">{{ algo.name }}</span>
              <span class="algo-cell-signal" :class="getDecisionSignalClass(algo.data?.signal)">
                {{ (algo.data?.signal === 'buy') ? '买入' : (algo.data?.signal === 'sell') ? '卖出' : '中性' }}
              </span>
            </div>
            <div class="algo-cell-desc">{{ algo.desc }}</div>
          </div>
        </div>
      </el-card>

      <!-- 技术指标信号 - 优化版 -->
      <el-card shadow="hover" class="result-card tech-card desktop-only">
        <template #header>
          <div class="card-header">
            <div class="title-block">
              <span class="title-main">技术指标信号</span>
              <span class="title-sub">共 {{ techTable.length }} 项指标 · 实时分析</span>
            </div>
            <div class="tech-summary">
              <div class="summary-item buy" v-if="buySignals.length">
                <span class="summary-dot"></span>
                <span>{{ buySignals.length }} 买入</span>
              </div>
              <div class="summary-item sell" v-if="sellSignals.length">
                <span class="summary-dot"></span>
                <span>{{ sellSignals.length }} 卖出</span>
              </div>
            </div>
          </div>
        </template>

        <div class="tech-grid">
          <!-- 趋势 / 动量 -->
          <div class="tech-section">
            <div class="tech-section-header trend">
              <div class="section-icon">
                <el-icon><DataLine /></el-icon>
              </div>
              <div class="section-info">
                <span class="section-title">趋势 / 动量</span>
                <span class="section-count">{{ techTableLeft.length }} 项</span>
              </div>
              <div class="section-badge" :class="getTrendBadgeClass()">
                {{ getTrendSummary() }}
              </div>
            </div>
            <div class="tech-list-header">
              <span class="col-name">指标名称</span>
              <span class="col-value">数值</span>
              <span class="col-signal">信号</span>
            </div>
            <div class="tech-items">
              <div class="tech-item" v-for="item in techTableLeft" :key="item.name">
                <div class="item-col item-name">
                  <span class="name-text">{{ item.name }}</span>
                  <span class="name-desc" v-if="item.desc">{{ item.desc }}</span>
                </div>
                <div class="item-col item-value" :class="'val-' + item.signalType">{{ formatTechVal(item.value) }}</div>
                <div class="item-col item-signal">
                  <div class="signal-indicator" :class="item.signalType"></div>
                  <el-tag :type="item.signalType" size="small" effect="light" class="signal-tag">
                    {{ item.signal }}
                  </el-tag>
                </div>
              </div>
            </div>
          </div>

          <!-- 震荡 / 量能 -->
          <div class="tech-section">
            <div class="tech-section-header oscillation">
              <div class="section-icon">
                <el-icon><Coin /></el-icon>
              </div>
              <div class="section-info">
                <span class="section-title">震荡 / 量能</span>
                <span class="section-count">{{ techTableRight.length }} 项</span>
              </div>
              <div class="section-badge" :class="getOscillationBadgeClass()">
                {{ getOscillationSummary() }}
              </div>
            </div>
            <div class="tech-list-header">
              <span class="col-name">指标名称</span>
              <span class="col-value">数值</span>
              <span class="col-signal">信号</span>
            </div>
            <div class="tech-items">
              <div class="tech-item" v-for="item in techTableRight" :key="item.name">
                <div class="item-col item-name">
                  <span class="name-text">{{ item.name }}</span>
                  <span class="name-desc" v-if="item.desc">{{ item.desc }}</span>
                </div>
                <div class="item-col item-value" :class="'val-' + item.signalType">{{ formatTechVal(item.value) }}</div>
                <div class="item-col item-signal">
                  <div class="signal-indicator" :class="item.signalType"></div>
                  <el-tag :type="item.signalType" size="small" effect="light" class="signal-tag">
                    {{ item.signal }}
                  </el-tag>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="section-analysis" v-if="techAnalysis">
          <el-icon><DataLine /></el-icon>
          <span>{{ techAnalysis }}</span>
        </div>
      </el-card>

      <!-- K线形态识别 - 优化版 -->
      <el-card shadow="hover" class="result-card pattern-card desktop-only" v-if="patternList.length">
        <template #header>
          <div class="pattern-header-bar">
            <span>K线形态识别</span>
            <el-radio-group v-model="patternDirectionFilter" size="small">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="bullish">看涨</el-radio-button>
              <el-radio-button value="bearish">看跌</el-radio-button>
            </el-radio-group>
          </div>
        </template>
        <div class="pattern-table">
          <div class="pattern-header">
            <span class="col-direction">方向</span>
            <span class="col-name">形态</span>
            <span class="col-date">日期</span>
            <span class="col-confidence">置信度</span>
          </div>
          <div class="pattern-body">
            <div class="pattern-row" v-for="(row, index) in displayPatterns" :key="index">
              <div class="col-direction">
                <el-tag :type="row.direction === 'bullish' ? 'danger' : row.direction === 'bearish' ? 'success' : 'info'" size="small">
                  {{ row.direction === 'bullish' ? '看涨' : row.direction === 'bearish' ? '看跌' : '中性' }}
                </el-tag>
              </div>
              <div class="col-name">{{ row.name }}</div>
              <div class="col-date">{{ row.date }}</div>
              <div class="col-confidence">
                <span :style="{ color: getConfidenceColor(row), fontWeight: 'bold' }">
                  {{ Math.round((row.confidence||0.5)*100) }}%
                </span>
              </div>
            </div>
          </div>
        </div>
        <div class="pattern-footer" v-if="patternHasMore || patternShowAll">
          <el-button text type="primary" size="small" @click="patternShowAll = !patternShowAll">
            {{ patternShowAll ? '收起' : `查看全部 (${patternList.length}条)` }}
          </el-button>
        </div>
        <div class="section-analysis" v-if="patternAnalysis">
          <el-icon><DataLine /></el-icon>
          <span>{{ patternAnalysis }}</span>
        </div>
      </el-card>

      <!-- 财务数据（页面倒数第二个） -->
      <el-card shadow="hover" class="result-card desktop-only" v-if="financialData">
        <template #header><span>财务数据 (最新季报)</span></template>
          <el-row :gutter="16">
            <el-col :xs="6" :sm="4" :md="3" v-for="item in finItems" :key="item.label">
              <div class="fin-item">
                <div class="fin-label">{{ item.label }}</div>
                <div class="fin-value" :class="item.cls">{{ item.value }}</div>
              </div>
            </el-col>
          </el-row>
        <div class="section-analysis" v-if="finAnalysis">
          <el-icon><DataLine /></el-icon>
          <span>{{ finAnalysis }}</span>
        </div>
      </el-card>

      <!-- 消息面分析（页面最底部，紧跟财务数据下） -->
      <el-card shadow="hover" class="result-card news-section desktop-only" v-if="stockCode && !loading">
        <template #header>
          <div class="news-header">
            <span><el-icon><Bell /></el-icon> 消息面 — {{ stockName }}</span>
            <span class="news-count">
              <template v-if="newsCount">{{ newsCount }}条相关</template>
              <el-icon v-else-if="newsRefreshing" class="is-loading"><Loading /></el-icon>
            </span>
          </div>
        </template>
        <div v-if="newsList.length > 0" class="news-list">
          <div v-for="(n, i) in newsList" :key="i" class="news-item">
            <el-tag size="small" :type="n.sentiment === 'positive' ? 'danger' : n.sentiment === 'negative' ? 'success' : ''" effect="light" class="news-sentiment">{{ n.source || '资讯' }}</el-tag>
            <el-tag v-if="n.search_from === '板块'" size="small" type="info" effect="plain" class="news-source-tag">行业</el-tag>
            <span class="news-title" @click="openNews(n)">{{ n.title }}</span>
            <span class="news-date">{{ n.date }}</span>
          </div>
        </div>
        <div v-else class="news-empty">
          <el-icon v-if="newsError"><WarningFilled /></el-icon>
          <el-icon v-else><Bell /></el-icon>
          <span v-if="newsLoading && !newsDataVal && !newsTimedOut">加载中...</span>
          <span v-else-if="newsTimedOut">资讯服务响应超时，请稍后刷新</span>
          <span v-else-if="newsRefreshing">正在获取最新资讯...</span>
          <span v-else-if="newsError">消息面数据获取失败</span>
          <span v-else>暂无相关新闻/公告</span>
        </div>
      </el-card>

    </template>

    <el-empty v-if="!loading && !techData" description="请输入股票代码开始诊断">
      <template #image><el-icon :size="80" color="#c0c4cc"><DataLine /></el-icon></template>
    </el-empty>
  </div>
</template>

<script setup>
defineOptions({ name: 'StockDiagnosis' })
import { ref, computed, onMounted, onBeforeUnmount, onActivated, watch } from 'vue'
import { useRoute } from 'vue-router'
import { stockApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataLine, WarningFilled, Money, Clock, Coin, CaretTop, CaretBottom, Bell, Loading, Search, ArrowUp, QuestionFilled } from '@element-plus/icons-vue'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'
import RefreshingIndicator from '@/components/RefreshingIndicator.vue'
import { useClosingRefresh } from '@/composables/useClosingRefresh'
import KlineChart from "./components/KlineChart.vue"
import { buildAnalysisCtx, runAnalysis, buildMultiPeriodAdvice, getScoreLevel, getPositionAdvice } from '@/composables/useAnalysisRules.js'

const route = useRoute()
const query = ref('')
const searchCode = ref('')
const klinePeriod = ref("daily")
const searching = ref(false)
const isMobile = ref(false)

// 诊断历史记录（localStorage，最多保留20条）
function addToDiagHistory(code, name) {
  try {
    const key = 'diag_history'
    const list = JSON.parse(localStorage.getItem(key) || '[]')
    const idx = list.findIndex(i => i.code === code)
    if (idx >= 0) list.splice(idx, 1)
    list.unshift({ code, name, time: Date.now() })
    if (list.length > 20) list.length = 20
    localStorage.setItem(key, JSON.stringify(list))
  } catch {}
}

const inputSize = computed(() => isMobile.value ? 'default' : 'large')

const quickStocks = [
  { code: '600519', name: '贵州茅台' },
  { code: '300750', name: '宁德时代' },
  { code: '002594', name: '比亚迪' },
  { code: '601318', name: '中国平安' },
]

// ★ query 必须在 useCachedFetch 之前就初始化好，
//   否则 key 函数首次求值会拿到 '' → useCachedFetch 用 "default" 占位 → 后续 watch 触发会重复加载
// 优先级：URL 参数 > 默认第一只
function resolveInitialCode() {
  const fromUrl = route.query.code
  if (typeof fromUrl === 'string' && /^\d{6}$/.test(fromUrl)) return fromUrl
  return quickStocks[0].code
}
const initialCode = resolveInitialCode()
query.value = initialCode
searchCode.value = initialCode

// 各数据类型独立缓存，key 包含 stock code
// 切回上次看过的股票，立即展示缓存 + 后台静默刷新
// 注意：diagnosis 已包含 technical 和 patterns 数据，避免重复请求

const diagnosis = useCachedFetch({
  key: () => `stock:diagnosis:${searchCode.value}`,
  fetcher: () => searchCode.value ? stockApi.getDiagnosis(searchCode.value) : Promise.resolve(null),
  tier: CACHE_TIERS.STOCK,
})

// 消息面数据（与诊断并行获取）
const newsData = useCachedFetch({
  key: () => `stock:news:${searchCode.value}`,
  fetcher: async ({ signal }) => {
    if (!searchCode.value) return null
    return stockApi.getNews(searchCode.value, 5, signal)
  },
  tier: CACHE_TIERS.STOCK,
})

// 决策中心算法信号（与诊断并行获取）
const decisionSignals = useCachedFetch({
  key: () => `stock:decision:${searchCode.value}`,
  fetcher: async ({ signal }) => {
    if (!searchCode.value) return null
    try {
      return await stockApi.getDecisionSignals(searchCode.value, 250, signal)
    } catch {
      return null
    }
  },
  tier: CACHE_TIERS.STOCK,
})

// 顶层解包：模板自动解包顶层 ref，普通对象属性需要手动解包
const newsDataVal = computed(() => newsData.data?.value)
const newsLoading = computed(() => newsData.loading?.value === true)
const newsRefreshing = computed(() => newsData.refreshing?.value === true)
const newsError = computed(() => newsData.error?.value)
const newsList = computed(() => newsDataVal.value?.news || [])
const newsCount = computed(() => newsDataVal.value?.count || 0)

// 从 diagnosis 中提取 technical 和 patterns 数据（避免重复请求）
const technical = computed(() => {
  const d = diagnosis.data.value
  if (!d) return null
  return d.technical_indicators || null
})

const patterns = computed(() => {
  const d = diagnosis.data.value
  if (!d) return null
  return d.kline_patterns || null
})

useClosingRefresh([diagnosis, newsData, decisionSignals])

// 财务数据由下面的 financialData computed 提供（基于 technical.data）

const loading = computed(() => diagnosis.loading.value || searching.value)

// ★ 这些 computed 必须在 watch 之前定义，避免 TDZ
const techData = technical
const stockCode = computed(() => query.value)
const stockName = computed(() => techData.value?.name || query.value)
const patternList = computed(() => patterns.value?.patterns || [])
const diagnosisFailed = computed(() => {
  if (loading.value) return false
  // 后端返回 {error: True} 时 useCachedFetch 会 throw，data 为空但 error 有值
  if (diagnosis.error.value) return true
  // 后端直接返回 {status: "error"} 时 data 有值但无 technical_indicators
  const d = diagnosis.data.value
  if (d?.error === true) return true
  if (d?.status === 'error' && !d?.technical_indicators) return true
  return false
})
const diagnosisErrorMsg = computed(() => {
  const d = diagnosis.data.value
  const err = diagnosis.error.value
  return d?.error_msg || d?.message || err?.message || '诊断服务异常，请稍后重试'
})

// 消息面加载超时降级：超过 12 秒 loading=true 但仍无数据，强制显示空状态
const newsTimedOut = ref(false)
let newsTimer = null
watch([() => newsData.loading, () => stockCode.value], ([ld, code]) => {
  if (newsTimer) { clearTimeout(newsTimer); newsTimer = null }
  newsTimedOut.value = false
  if (ld && code) {
    newsTimer = setTimeout(() => {
      if (newsData.loading && !newsData.data) {
        newsTimedOut.value = true
      }
    }, 12000)
  }
}, { immediate: true })
onBeforeUnmount(() => { if (newsTimer) clearTimeout(newsTimer) })

function checkMobile() {
  isMobile.value = window.innerWidth < 768
}

let resizeTimer = null
function debouncedCheckMobile() {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(checkMobile, 200)
}

// 监听股票代码变化，强制刷新消息面和决策信号
watch(searchCode, (newCode) => {
  if (newCode) {
    newsData.clear()
    newsData.refresh()
    decisionSignals.clear()
    decisionSignals.refresh()
  }
})

// 诊断成功后自动记录历史（techData 有 name 时触发）
watch(techData, (d) => {
  if (d && d.name && searchCode.value) {
    addToDiagHistory(searchCode.value, d.name)
  }
})

function syncRouteCode() {
  const fromUrl = route.query.code
  if (typeof fromUrl === 'string' && /^\d{6}$/.test(fromUrl) && fromUrl !== searchCode.value) {
    searchCode.value = fromUrl
    query.value = fromUrl
    diagnosis.clear()
    newsData.clear()
    decisionSignals.clear()
    diagnosis.refresh()
    newsData.refresh()
    decisionSignals.refresh()
  }
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', debouncedCheckMobile)

  // 同步路由参数并加载数据
  syncRouteCode()
  if (searchCode.value) {
    diagnosis.refresh()
    newsData.clear()
    newsData.refresh()
    decisionSignals.clear()
    decisionSignals.refresh()
  }
})

// keep-alive 激活时同步路由参数（从市场看板跳转回来）
onActivated(() => {
  syncRouteCode()
})

// 监听路由参数变化，支持从其他页面跳转时更新股票
watch(() => route.query.code, (newCode, oldCode) => {
  if (typeof newCode === 'string' && /^\d{6}$/.test(newCode) && newCode !== searchCode.value) {
    searchCode.value = newCode
    query.value = newCode
    diagnosis.clear()
    newsData.clear()
    decisionSignals.clear()
    diagnosis.refresh()
    newsData.refresh()
    decisionSignals.refresh()
  }
})

function handleKlineError(msg) {
  ElMessage.warning(`K线加载失败: ${msg}`)
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', debouncedCheckMobile)
})

// K线形态展开/方向筛选
const patternShowAll = ref(false)
const patternDirectionFilter = ref('all')
const displayPatterns = computed(() => {
  let list = patternList.value
  if (!Array.isArray(list)) return []
  if (patternDirectionFilter.value !== 'all') {
    list = list.filter(p => p.direction === patternDirectionFilter.value)
  }
  const sorted = [...list].sort((a, b) => (b.date || '').localeCompare(a.date || ''))
  return patternShowAll.value ? sorted : sorted.slice(0, 8)
})
const patternHasMore = computed(() => {
  let list = patternList.value
  if (patternDirectionFilter.value !== 'all') {
    list = list.filter(p => p.direction === patternDirectionFilter.value)
  }
  return list.length > 8
})

const topBuyReasons = computed(() => {
  const r = analysisResult.value
  if (!r?.hits?.length) return []
  return r.hits
    .filter(h => h.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map(h => {
      try { return typeof h.text === 'function' ? h.text(r.ctx) : String(h.text) } catch { return '' }
    })
    .filter(Boolean)
})
const topSellReasons = computed(() => {
  const r = analysisResult.value
  if (!r?.hits?.length) return []
  return r.hits
    .filter(h => h.score < 0)
    .sort((a, b) => a.score - b.score)
    .slice(0, 3)
    .map(h => {
      try { return typeof h.text === 'function' ? h.text(r.ctx) : String(h.text) } catch { return '' }
    })
    .filter(Boolean)
})

// 资金面深度分析已移除（接口不稳定，数据不可用）

function extractText(r) { if (!r) return ''; if (r.raw_output) return r.raw_output; if (typeof r === 'string') return r; return '' }

// 提取常用正则为常量，避免重复创建
const RE_PRICE = /最新价[：:]\s*¥?([\d.]+)/
const RE_CHANGE = /涨跌幅[：:]\s*([+-]?[\d.]+)/
const RE_FIELD = (label) => new RegExp(label + '[：:]\\s*[¥]?([\\d.]+)')

// 实时行情 - 优先用结构化数据，fallback到解析raw
const realtimeData = computed(() => {
  const t = techData.value
  if (!t) return null
  // 结构化数据
  if (t.realtime && t.realtime.price) return t.realtime
  // fallback: 解析raw
  const raw = extractText(t)
  if (!raw) return null
  const priceMatch = raw.match(RE_PRICE)
  if (!priceMatch) return null
  const getVal = (label) => {
    const m = raw.match(RE_FIELD(label))
    return m ? m[1] : '--'
  }
  const changeMatch = raw.match(RE_CHANGE)
  return {
    price: priceMatch[1],
    open: getVal('今开'), high: getVal('最高'), low: getVal('最低'),
    last_close: getVal('昨收'), change_pct: changeMatch ? parseFloat(changeMatch[1]) : 0,
    amplitude: getVal('振幅'), avg_price: getVal('均价'),
    volume: getVal('成交量'), amount: getVal('成交额'),
  }
})

const rtItems = computed(() => {
  const d = realtimeData.value
  if (!d) return []
  const pctClass = (d.change_pct || 0) >= 0 ? 'c-red' : 'c-green'
  const fmtAmount = (v) => {
    const n = Number(v) || 0
    if (n >= 10000) return (n / 10000).toFixed(2) + '亿'
    return n.toFixed(0) + '万'
  }
  const items = [
    { label: '最新价', value: '¥' + d.price, cls: pctClass },
    { label: '涨跌幅', value: ((d.change_pct || 0) >= 0 ? '+' : '') + (d.change_pct || 0) + '%', cls: pctClass },
    { label: '今开', value: '¥' + d.open, cls: '' },
    { label: '昨收', value: '¥' + d.last_close, cls: '' },
    { label: '最高', value: '¥' + d.high, cls: 'c-red' },
    { label: '最低', value: '¥' + d.low, cls: 'c-green' },
  ]
  if (d.amount != null) items.push({ label: '成交额', value: fmtAmount(d.amount), cls: '' })
  if (d.amplitude != null) items.push({ label: '振幅', value: Number(d.amplitude).toFixed(2) + '%', cls: '' })
  if (d.turnover_rate != null && d.turnover_rate > 0) items.push({ label: '换手率', value: Number(d.turnover_rate).toFixed(2) + '%', cls: '' })
  if (d.avg_price != null) items.push({ label: '均价', value: '¥' + d.avg_price, cls: '' })
  if (d.bid1) items.push({ label: '买一', value: '¥' + d.bid1, cls: 'c-red' })
  if (d.ask1) items.push({ label: '卖一', value: '¥' + d.ask1, cls: 'c-green' })
  return items
})

// 实时行情分析
const rtAnalysis = computed(() => {
  const d = realtimeData.value
  if (!d) return ''
  const pct = d.change_pct || 0
  let parts = []
  if (pct > 3) parts.push('今日强势上涨')
  else if (pct > 1) parts.push('温和上涨')
  else if (pct > -1) parts.push('窄幅震荡')
  else if (pct > -3) parts.push('小幅回调')
  else parts.push('明显下跌')
  
  const vol = parseFloat(d.volume || 0)
  const amt = parseFloat(d.amount || 0)
  if (amt > 500000) parts.push('成交活跃')
  else if (amt < 100000) parts.push('交投清淡')
  
  return `${parts.join('，')}。现价¥${d.price}，涨跌${pct >= 0 ? '+' : ''}${pct}%`
})

// 财务数据分析
const finAnalysis = computed(() => {
  const f = financialData.value
  if (!f) return ''
  let parts = []
  
  const pe = Number(f.pe) || 0
  const roe = Number(f.roe) || 0
  const debtRatio = Number(f.debt_ratio)
  const revGrowth = Number(f.revenue_yoy) || 0
  const profitGrowth = Number(f.profit_yoy) || 0
  
  // PE evaluation
  if (pe > 0) {
    if (pe < 15) parts.push('估值偏低')
    else if (pe < 30) parts.push('估值合理')
    else parts.push('估值偏高')
  }
  
  // ROE evaluation
  if (roe > 0) {
    if (roe > 15) parts.push('盈利能力优秀')
    else if (roe > 8) parts.push('盈利尚可')
    else parts.push('盈利能力偏弱')
  }
  
  // Revenue/Profit growth
  if (revGrowth > 20 && profitGrowth > 20) parts.push('业绩高增长')
  else if (revGrowth < -10 && profitGrowth < -10) parts.push('业绩下滑明显')
  else if (profitGrowth > revGrowth) parts.push('利润增速优于营收')
  
  // Debt ratio
  if (!isNaN(debtRatio)) {
    if (debtRatio > 80) parts.push('负债率较高，注意风险')
    else if (debtRatio < 40) parts.push('财务稳健')
  }
  
  return parts.length ? parts.join('；') + '。' : '财务数据正常。'
})

// 技术指标分析
const techAnalysis = computed(() => {
  const ind = techData.value?.indicators
  if (!ind) return ''
  
  let buyCount = 0, sellCount = 0
  for (const sig of [ind.MACD_SIGNAL, ind.KDJ_SIGNAL, ind.RSI_SIGNAL, ind.BOLL_SIGNAL]) {
    if (/买入|金叉|多头|超卖/.test(sig)) buyCount++
    else if (/卖出|死叉|空头|超买/.test(sig)) sellCount++
  }
  
  let trend = '多空均衡'
  if (buyCount > sellCount + 1) trend = '偏多格局'
  else if (sellCount > buyCount + 1) trend = '偏空格局'
  
  // MA alignment check
  const ma5 = ind.MA5, ma20 = ind.MA20, ma60 = ind.MA60
  let maTrend = ''
  if (ma5 && ma20 && ma60) {
    if (ma5 > ma20 && ma20 > ma60) maTrend = '均线多头排列'
    else if (ma5 < ma20 && ma20 < ma60) maTrend = '均线空头排列'
    else if (ma5 > ma20) maTrend = '短期偏强'
    else maTrend = '短期偏弱'
  }
  
  return `${trend}（${buyCount}买/${sellCount}卖），${maTrend || '均线交织'}。`
})

// K线形态分析
const patternAnalysis = computed(() => {
  if (!patternList.value.length) return ''
  const bullish = patternList.value.filter(p => p.direction === 'bullish').length
  const bearish = patternList.value.filter(p => p.direction === 'bearish').length
  
  let trend = '中性'
  if (bullish > bearish + 2) trend = '偏多'
  else if (bearish > bullish + 2) trend = '偏空'
  
  const recent = patternList.value.slice(-3).map(p => p.name).join('、')
  return `近期出现${recent}等形态，整体${trend}。`
})

// 综合分析 — 数据驱动规则表（统一 check/text/score，避免 8 段重复 if-else）
// 评分完全用后端 weighted_score，前端规则只生成文本要点
const analysisResult = computed(() => {
  const ind = techData.value?.indicators
  const fin = financialData.value || {}
  const rt = realtimeData.value
  if (!ind) return null
  const ctx = buildAnalysisCtx(ind, fin, rt)
  return runAnalysis(ctx)
})

// 消息面情感倾向：基于 news 列表的 positive/negative/neutral 比例 + 量化得分
const newsSentiment = computed(() => {
  const rawData = newsData.data?.value
  const list = rawData?.news || []
  if (list.length === 0) return null
  const counts = { positive: 0, negative: 0, neutral: 0 }
  // 量化情感分：利好 +5/条，利空 -3/条，中性 0
  let sentimentScore = 0
  list.forEach(n => {
    const s = n.sentiment || 'neutral'
    if (counts[s] != null) counts[s]++
    if (s === 'positive') sentimentScore += 5
    else if (s === 'negative') sentimentScore -= 3
  })
  const total = list.length
  let type = 'neutral', text = `消息面中性(${total}条)`
  if (counts.positive > counts.negative * 1.5) {
    type = 'positive'
    text = `消息面偏多(${counts.positive}/${total}条利好)`
  } else if (counts.negative > counts.positive * 1.5) {
    type = 'negative'
    text = `消息面偏空(${counts.negative}/${total}条利空)`
  }
  return { type, text, counts, sentimentScore, total }
})

// ════════ 决策中心算法信号矩阵 ════════
const decisionData = computed(() => decisionSignals.data?.value)
const decisionLoading = computed(() => decisionSignals.loading?.value === true)

// 算法信号列表（用于展示）
const algoSignalList = computed(() => {
  const d = decisionData.value
  if (!d || !d.signals) return []
  const signals = d.signals
  return [
    { name: 'TD序列', key: 'td_sequential', data: signals.td_sequential, desc: '趋势反转预测' },
    { name: '均线雷达', key: 'ma_radar', data: signals.ma_radar, desc: '多周期排列分析' },
    { name: '通道突破', key: 'channel_breakout', data: signals.channel_breakout, desc: 'Donchian通道' },
    { name: '神奇电波', key: 'magic_wave', data: signals.magic_wave, desc: 'MACD+RSI复合' },
    { name: '异动拉升', key: 'anomaly_detect', data: signals.anomaly_detect, desc: '放量/突变检测' },
    { name: '底部寻机', key: 'bottom_opportunity', data: signals.bottom_opportunity, desc: '超跌反弹识别' },
    { name: '趋势强度', key: 'trend_strength', data: signals.trend_strength, desc: 'ADX评分系统' },
  ]
})

// 综合信号文本映射
const decisionSignalTextMap = {
  strong_buy: '强烈买入',
  buy: '买入',
  neutral: '中性观望',
  sell: '卖出',
  strong_sell: '强烈卖出',
}

function getDecisionSignalClass(signal) {
  if (signal === 'buy' || signal === 'strong_buy') return 'sig-buy'
  if (signal === 'sell' || signal === 'strong_sell') return 'sig-sell'
  return 'sig-neutral'
}

function getDecisionSignalColor(score) {
  if (score == null) return '#909399'
  if (score >= 75) return '#f56c6c'
  if (score >= 60) return '#e6a23c'
  if (score >= 45) return '#909399'
  if (score >= 30) return '#67c23a'
  return '#4e9a4e'
}

// 算法信号汇总：买入/卖出/中性计数
const algoSignalSummary = computed(() => {
  const d = decisionData.value
  if (!d || !d.signals) return null
  const signals = d.signals
  const algos = ['td_sequential', 'channel_breakout', 'magic_wave', 'anomaly_detect', 'bottom_opportunity']
  let buyCount = 0, sellCount = 0, neutralCount = 0
  for (const key of algos) {
    const sig = signals[key]?.signal || 'neutral'
    if (sig === 'buy') buyCount++
    else if (sig === 'sell') sellCount++
    else neutralCount++
  }
  return { buyCount, sellCount, neutralCount, total: algos.length }
})

// 结论文本基于后端加权评分 — 使用统一 getScoreLevel（与后端 SCORE_THRESHOLDS 完全对齐）
const conclusionLevel = computed(() => getScoreLevel(weightedScore.value))
const conclusionText = computed(() => {
  const score = weightedScore.value
  if (score == null) return '数据不足，无法给出明确结论'
  let base = conclusionLevel.value.text
  const ns = newsSentiment.value
  if (ns && ns.type === 'negative' && score >= 60) {
    return `${base}，但需留意近期利空消息`
  }
  if (ns && ns.type === 'positive' && score < 45) {
    return `${base}，但近期有正向消息提振`
  }
  return base
})

// 评分等级标题（统一显示用，避免与 conclusionText 分档冲突）
const scoreLevelTitle = computed(() => conclusionLevel.value.title)
// 评分等级类型（用于颜色映射：偏多/偏空）
const scoreLevelType = computed(() => conclusionLevel.value.type)

const analysisLines = computed(() => {
  const r = analysisResult.value
  if (!r?.hits?.length) return []
  const sorted = [...r.hits].sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
  const lines = sorted.map(h => {
    try { return typeof h.text === 'function' ? h.text(r.ctx) : String(h.text) } catch { return '' }
  }).filter(Boolean)
  lines.push(`综合判断：${conclusionText.value}`)
  return lines
})

// 为每个要点小圆点着色：根据关键词判断正面/负面/中性
function getAnalysisDotClass(index, total) {
  // 简化：最后一条通常是"综合判断"，着色更深；其余按顺序循环
  if (index === total - 1) return 'dot-conclusion'
  return 'dot-normal'
}

// ═══════════════════════════════════════════════
// 增强版：加权评分 / 风险等级 / 操作建议 / 分周期 / 近期表现 / 资金流
// ═══════════════════════════════════════════════

// 加权评分（来自后端）
const weightedScore = computed(() => {
  return techData.value?.weighted_score ?? null
})

// 评分构成（来自后端 SCORE_BREAKDOWN，含分项得分）
const scoreBreakdown = computed(() => techData.value?.score_breakdown ?? null)
const diagnoseTime = computed(() => techData.value?.diagnose_time ?? null)

// 技术面分项标签
const subScoreLabel = {
  trend: '趋势', volume: '量能', macd: 'MACD',
  kdj: 'KDJ', rsi: 'RSI', boll: 'BOLL',
}

// 评分构成可视化列表（三段进度条）
const scoreBreakdownList = computed(() => {
  const sb = scoreBreakdown.value
  if (!sb) return []
  const weights = sb.weights || { technical: 0.65, fundamental: 0.25, capital_flow: 0.10 }
  const colorFor = (s) => {
    if (s >= 75) return '#f56c6c'   // 红（偏多）
    if (s >= 60) return '#e6a23c'   // 橙
    if (s >= 45) return '#909399'   // 灰
    if (s >= 30) return '#67c23a'   // 浅绿
    return '#4e9a4e'                // 深绿（偏空）
  }
  return [
    { key: 'technical',    name: '技术面', score: sb.technical ?? 0,    weightText: (weights.technical * 100).toFixed(0) + '%',  color: colorFor(sb.technical ?? 0) },
    { key: 'fundamental',  name: '基本面', score: sb.fundamental ?? 0,  weightText: (weights.fundamental * 100).toFixed(0) + '%', color: colorFor(sb.fundamental ?? 0) },
    { key: 'capital_flow', name: '资金面', score: sb.capital_flow ?? 0, weightText: (weights.capital_flow * 100).toFixed(0) + '%', color: colorFor(sb.capital_flow ?? 0) },
  ]
})

// 风险等级（来自后端，含 score_conflict 标记）
const riskLevel = computed(() => techData.value?.risk_level ?? null)
const riskConflict = computed(() => {
  const r = riskLevel.value
  if (!r) return false
  // 后端已计算 score_conflict；前端兜底再校验一次（>=4 星且评分 >=70）
  return r.score_conflict === true || (r.level >= 4 && (weightedScore.value ?? 0) >= 70)
})

// 仓位建议（基于综合评分）
const positionAdvice = computed(() => getPositionAdvice(weightedScore.value))

// 评分环渐变（移动端 m-score-ring 用）
const scoreRingGradient = computed(() => {
  const s = weightedScore.value
  if (s == null) return 'conic-gradient(var(--m-border) 0deg 360deg)'
  const deg = (s / 100) * 360
  let color = 'var(--m-accent)'
  if (s >= 75) color = 'var(--m-up)'
  else if (s >= 60) color = 'var(--m-gold)'
  else if (s < 45) color = 'var(--m-down)'
  return `conic-gradient(${color} 0deg ${deg}deg, var(--m-border) ${deg}deg 360deg)`
})

// 评分样式：与 conclusionLevel.type 对齐（5 档）
const scoreClass = computed(() => {
  const lvl = conclusionLevel.value
  if (!lvl || lvl.level === 'no_data') return ''
  if (lvl.level === 'strong_bullish') return 'score-strong-bull'
  if (lvl.level === 'bullish') return 'score-bull'
  if (lvl.level === 'neutral') return 'score-mid'
  if (lvl.level === 'bearish') return 'score-bear'
  if (lvl.level === 'strong_bearish') return 'score-strong-bear'
  return ''
})

// 风险等级
const riskStars = computed(() => {
  const rl = techData.value?.risk_level
  if (!rl || !rl.level) return '☆☆☆☆☆'
  const filled = '★'.repeat(rl.level)
  const empty = '☆'.repeat(5 - rl.level)
  return filled + empty
})

// 风险等级颜色
const riskClass = computed(() => {
  const rl = techData.value?.risk_level
  if (!rl || !rl.level) return ''
  if (rl.level <= 2) return 'risk-low'    // 1-2星：低风险
  if (rl.level <= 3) return 'risk-mid'    // 3星：中风险
  return 'risk-high'                      // 4-5星：高风险
})

// 风险原因（hover/点击展示）
const riskReasons = computed(() => {
  return techData.value?.risk_level?.reasons || []
})

// 入场/止损/目标位（基于 ATR + BOLL + MA20 + MA60 + 近期高低点）
// 优化：关键位分层（近端/远端）
const pricePlan = computed(() => {
  const ind = techData.value?.indicators
  const rt = techData.value?.realtime
  if (!ind || !rt) return null
  const price = Number(rt.price)
  if (!isFinite(price) || price <= 0) return null
  const ma20 = Number(ind.MA20) || 0
  const ma60 = Number(ind.MA60) || 0
  const bollUp = Number(ind.BOLL_UP) || 0
  const bollDn = Number(ind.BOLL_DN) || 0
  const bollMid = Number(ind.BOLL_MID) || 0
  if (ma20 <= 0 || bollUp <= 0 || bollDn <= 0 || bollMid <= 0) return null

  // ATR 估算：BOLL 带宽 / 4（BOLL=MA20±2σ，σ≈带宽/4）
  const atr = (bollUp - bollDn) / 4
  if (!isFinite(atr) || atr <= 0) return null

  // 建议买入区间：MA20 到 现价下方 1.5% (偏保守)
  const buyLow = Math.min(ma20, price * 0.985)
  const buyHigh = Math.max(ma20, price * 0.995)
  if (!isFinite(buyLow) || !isFinite(buyHigh) || buyLow <= 0 || buyHigh <= 0) return null

  // 止损位：max(最近5日最低, 现价-2*ATR) 下方 1% 安全垫
  let recentLow = price
  if (techData.value?.raw_output) {
    const m = techData.value.raw_output.match(/最低[^\d]+(\d+\.\d+)/)
    if (m && Number(m[1]) > 0) recentLow = Math.min(recentLow, Number(m[1]))
  }
  const stopBase = Math.max(0, recentLow * 0.99, price - 2 * atr)
  const stopLoss = round2(stopBase)
  const stopPct = round1((stopLoss / price - 1) * 100)

  // 多级目标位（分层：近端/远端）
  const target1 = round2(bollMid)        // 近端保守：BOLL中轨
  const target2 = round2(bollUp)         // 近端中性：BOLL上轨
  const target3 = round2(price + 3 * atr) // 远端乐观：3倍ATR
  // 远端压力位：MA60（若高于现价）
  const farResistance = ma60 > price ? round2(ma60) : null
  // 远端支撑位：MA20（若低于现价）
  const farSupport = ma20 < price ? round2(ma20) : null

  // 防御：所有百分比必须是有限数字
  const pct = (t) => {
    const v = (t / price - 1) * 100
    return isFinite(v) ? round1(v) : null
  }
  return {
    buyLow: round2(buyLow),
    buyHigh: round2(buyHigh),
    stopLoss,
    stopPct: isFinite(stopPct) ? stopPct : null,
    target1, target1Pct: pct(target1),
    target2, target2Pct: pct(target2),
    target3, target3Pct: pct(target3),
    farResistance,
    farResistancePct: farResistance ? pct(farResistance) : null,
    farSupport,
    farSupportPct: farSupport ? pct(farSupport) : null,
  }
})

// 分周期建议（共享逻辑）
const multiPeriodAdvice = computed(() =>
  buildMultiPeriodAdvice(techData.value?.indicators, techData.value?.realtime, financialData.value, stockCode.value, stockName.value)
)

// 近期表现（1周/1月/3月/1年）
const recentPerformance = computed(() => {
  const perf = techData.value?.recent_performance || {}
  const map = [
    { label: '1周', key: 'PCT_1W' },
    { label: '1月', key: 'PCT_1M' },
    { label: '3月', key: 'PCT_3M' },
    { label: '1年', key: 'PCT_1Y' },
  ]
  const result = []
  for (const m of map) {
    if (perf[m.key] !== undefined) {
      const v = perf[m.key]
      result.push({
        label: m.label,
        text: (v >= 0 ? '+' : '') + v + '%',
        cls: v > 0 ? 'c-red' : v < 0 ? 'c-green' : '',
      })
    }
  }
  return result.length ? result : null
})

// 资金流连续性 + 大/中/小单拆分
const flowTrend = computed(() => {
  const cf = techData.value?.capital_flow
  if (!cf) return null
  const fmt = (v) => {
    if (v == null) return { text: '暂无数据', cls: 'flow-na' }
    const n = Number(v)
    if (Math.abs(n) < 0.05) return { text: '±0', cls: '' }
    return { text: (n >= 0 ? '+' : '') + n.toFixed(2) + '亿', cls: n > 0 ? 'c-red' : 'c-green' }
  }
  const net = (buy, sell) => {
    const b = Number(buy) || 0
    const s = Number(sell) || 0
    return b - s
  }
  return {
    today: fmt(cf.main_net),
    flow3d: fmt(cf.flow_3d),
    flow5d: fmt(cf.flow_5d),
    flow10d: fmt(cf.flow_10d),
    bigNet: fmt(net(cf.big_buy, cf.big_sell)),
    midNet: fmt(net(cf.mid_buy, cf.mid_sell)),
    smallNet: fmt(net(cf.small_buy, cf.small_sell)),
  }
})

function round1(n) { return Math.round(n * 10) / 10 }
function round2(n) { return Math.round(n * 100) / 100 }

// 财务数据
const financialData = computed(() => {
  const t = techData.value
  if (!t) return null
  return t.financial || t.financial_data || null
})

const finItems = computed(() => {
  const f = financialData.value
  if (!f || !Object.keys(f).length) return []
  // 兼容后端字段名（pe_ttm 或 pe）
  const pe = f.pe_ttm || f.pe || 0
  const pb = f.pb || 0
  const roe = f.roe || 0
  const eps = f.eps || 0
  const grossMargin = f.gross_margin
  const debtRatio = f.debt_ratio
  const revenueYoy = f.revenue_yoy
  const profitYoy = f.profit_yoy
  
  return [
    { label: 'PE(动)', value: pe ? pe.toFixed(2) : '--', cls: '' },
    { label: 'PB', value: pb ? pb.toFixed(2) : '--', cls: '' },
    { label: 'ROE', value: roe ? roe.toFixed(2) + '%' : '--', cls: '' },
    { label: 'EPS', value: eps ? '¥' + eps.toFixed(2) : '--', cls: '' },
    { label: '毛利率', value: grossMargin !== undefined && grossMargin !== null ? grossMargin.toFixed(2) + '%' : '--', cls: '' },
    { label: '资产负债率', value: debtRatio !== undefined && debtRatio !== null ? debtRatio.toFixed(2) + '%' : '--', cls: '' },
    { label: '营收同比', value: revenueYoy !== undefined && revenueYoy !== null ? (revenueYoy >= 0 ? '+' : '') + revenueYoy.toFixed(2) + '%' : '--', cls: revenueYoy > 0 ? 'c-red' : revenueYoy < 0 ? 'c-green' : '' },
    { label: '净利润同比', value: profitYoy !== undefined && profitYoy !== null ? (profitYoy >= 0 ? '+' : '') + profitYoy.toFixed(2) + '%' : '--', cls: profitYoy > 0 ? 'c-red' : profitYoy < 0 ? 'c-green' : '' },
  ]
})

// 解析技术指标表格 - 优先使用结构化 indicators，回退到 raw_output 正则
const techTable = computed(() => {
  const t = techData.value
  if (!t) return []
  const ind = t.indicators
  const rt = t.realtime || {}
  const price = rt.price || 0
  const result = []

  // 辅助函数: 根据指标值计算信号
  function calcSignal(key, val) {
    if (val === undefined || val === null) return '--'
    // MA均线: 价格在上方/下方
    if (key.startsWith('MA') && price > 0) {
      const diff = Math.abs((price - val) / val * 100).toFixed(2)
      return price > val ? `上方+${diff}%` : `下方${diff}%`
    }
    // MACD柱: 红/绿
    if (key === 'MACD_BAR') {
      return val > 0 ? '红柱(多头)' : val < 0 ? '绿柱(空头)' : '零轴'
    }
    // KDJ: 超买/超卖区域（与后端 KDJ_SIGNAL 文本对齐）
    if (key.startsWith('KDJ')) {
      if (val > 80) return '超买'
      if (val < 20) return '超卖'
      if (val > 50) return '偏强'
      return '偏弱'
    }
    // RSI: 强弱判断（与后端 RSI_SIGNAL 文本对齐）
    if (key.startsWith('RSI')) {
      if (val > 80) return '超买'
      if (val > 60) return '偏强'
      if (val > 40) return '中性'
      if (val > 20) return '偏弱'
      return '超卖'
    }
    // 布林带: 相对位置（上/下轨为中性位，不分类为买卖信号）
    if (key === 'BOLL_UP') return '上轨压力'
    if (key === 'BOLL_MID') return '中轨'
    if (key === 'BOLL_DN') return '下轨支撑'
    // 量比
    if (key === 'VOL_RATIO') {
      if (val > 2) return '明显放量'
      if (val > 1.5) return '温和放量'
      if (val > 0.8) return '量能平稳'
      return '缩量'
    }
    return '--'
  }

  function signalType(val) {
    const s = String(val)
    if (/上方|红柱|多头|超卖|买入|金叉|突破上轨/.test(s)) return 'danger'
    if (/下方|绿柱|空头|超买|卖出|死叉|跌破下轨/.test(s)) return 'success'
    return 'info'
  }

  if (ind && Object.keys(ind).length > 0) {
    // 结构化数据优先
    const sections = [
      { name: 'MA5', key: 'MA5', desc: '5日均线' },
      { name: 'MA10', key: 'MA10', desc: '10日均线' },
      { name: 'MA20', key: 'MA20', desc: '20日均线' },
      { name: 'MA60', key: 'MA60', desc: '60日均线' },
      { name: 'DIF', key: 'MACD_DIF', desc: 'MACD快线' },
      { name: 'DEA', key: 'MACD_DEA', desc: 'MACD慢线' },
      { name: 'MACD柱', key: 'MACD_BAR', desc: 'MACD柱状图' },
      { name: 'KDJ-K', key: 'KDJ_K', desc: '随机指标K值' },
      { name: 'KDJ-D', key: 'KDJ_D', desc: '随机指标D值' },
      { name: 'KDJ-J', key: 'KDJ_J', desc: '随机指标J值' },
      { name: 'RSI6', key: 'RSI6', desc: '相对强弱指数(6日)' },
      { name: 'RSI12', key: 'RSI12', desc: '相对强弱指数(12日)' },
      { name: 'RSI24', key: 'RSI24', desc: '相对强弱指数(24日)' },
      { name: '布林上轨', key: 'BOLL_UP', desc: '布林带上轨' },
      { name: '布林中轨', key: 'BOLL_MID', desc: '布林带中轨' },
      { name: '布林下轨', key: 'BOLL_DN', desc: '布林带下轨' },
      { name: '量比', key: 'VOL_RATIO', desc: '' },
    ]
    for (const s of sections) {
      const v = ind[s.key]
      if (v !== undefined && v !== null) {
        const sig = calcSignal(s.key, v)
        result.push({ name: s.name, value: v, signal: sig, signalType: signalType(sig), desc: s.desc })
      }
    }
    // 综合信号行 (来自后端计算)
    const signalMap = [
      { name: 'MACD', key: 'MACD_SIGNAL' },
      { name: 'KDJ', key: 'KDJ_SIGNAL' },
      { name: 'RSI', key: 'RSI_SIGNAL' },
      { name: '布林带', key: 'BOLL_SIGNAL' },
      { name: '量能', key: 'VOL_SIGNAL' },
    ]
    for (const s of signalMap) {
      const val = ind[s.key]
      if (val) {
        result.push({ name: `${s.name}信号`, value: '--', signal: val, signalType: signalType(val), desc: '' })
      }
    }
    return result
  }

  // 回退: raw_output 正则解析
  const raw = extractText(t)
  if (!raw) return []
  const sections = [
    { name: 'MA5', regex: /MA5[：:]\s*[¥]?([\d.]+)/, desc: '5日均线' },
    { name: 'MA10', regex: /MA10[：:]\s*[¥]?([\d.]+)/, desc: '10日均线' },
    { name: 'MA20', regex: /MA20[：:]\s*[¥]?([\d.]+)/, desc: '20日均线' },
    { name: 'MA60', regex: /MA60[：:]\s*[¥]?([\d.]+)/, desc: '60日均线' },
    { name: 'DIF', regex: /DIF[：:]\s*([-\d.]+)\s*DEA/, desc: 'MACD快线' },
    { name: 'DEA', regex: /DEA[：:]\s*([-\d.]+)/, desc: 'MACD慢线' },
    { name: 'MACD柱', regex: /MACD柱[：:]\s*([-\d.]+)/, desc: 'MACD柱状图' },
    { name: 'KDJ-K', regex: /K[：:]\s*([\d.]+)\s*D/, desc: '随机指标K值' },
    { name: 'KDJ-D', regex: /D[：:]\s*([\d.]+)\s*J/, desc: '随机指标D值' },
    { name: 'KDJ-J', regex: /J[：:]\s*([\d.]+)/, desc: '随机指标J值' },
    { name: 'RSI6', regex: /RSI6[：:]\s*([\d.]+)\s*RSI12/, desc: '相对强弱指数(6日)' },
    { name: 'RSI12', regex: /RSI12[：:]\s*([\d.]+)\s*RSI24/, desc: '相对强弱指数(12日)' },
    { name: 'RSI24', regex: /RSI24[：:]\s*([\d.]+)/, desc: '相对强弱指数(24日)' },
    { name: '布林上轨', regex: /上轨[：:]\s*([-\d.]+)\s*中轨/, desc: '布林带上轨' },
    { name: '布林中轨', regex: /中轨[：:]\s*([-\d.]+)\s*下轨/, desc: '布林带中轨' },
    { name: '布林下轨', regex: /下轨[：:]\s*([-\d.]+)/, desc: '布林带下轨' },
    { name: '量比', regex: /量比[：:]\s*([\d.]+)/, desc: '' },
  ]
  for (const s of sections) {
    const m = raw.match(s.regex)
    if (m) result.push({ name: s.name, value: m[1], signal: '--', signalType: 'info', desc: s.desc })
  }
  // 信号行
  const signals = [
    { key: 'MACD信号', regex: /【MACD】[\s\S]*?信号[：:]\s*(.+)/ },
    { key: 'KDJ信号', regex: /【KDJ】[\s\S]*?信号[：:]\s*(.+)/ },
    { key: 'RSI信号', regex: /【RSI】[\s\S]*?信号[：:]\s*(.+)/ },
    { key: '布林带信号', regex: /【布林带】[\s\S]*?信号[：:]\s*(.+)/ },
    { key: '量能信号', regex: /【量能分析】[\s\S]*?信号[：:]\s*(.+)/ },
  ]
  for (const sig of signals) {
    const m = raw.match(sig.regex)
    if (m) {
      const val = m[1].trim()
      result.push({ name: sig.key, value: '--', signal: val, signalType: signalType(val), desc: '' })
    }
  }
  return result
})

// K线形态列表（已通过 patterns.data.value?.patterns 提供于 line 274）
// 这里只保留旧的 patternAnalysis 等基于其的 computed

// 综合评估 — 标题基于后端加权评分分档，与综合分析文本口径一致
const assessData = computed(() => {
  const t = techData.value
  if (!t) return null
  const ind = t.indicators
  const score = weightedScore.value
  const support = ind?.BOLL_DN || null
  const resist = ind?.BOLL_UP || null

  // 使用统一分档（与后端 SCORE_THRESHOLDS 对齐）
  let title, type
  if (score == null) {
    title = '数据不足'
    type = 'info'
  } else {
    const lvl = getScoreLevel(score)
    // el-alert type 只支持 success/warning/info/error/danger
    // 强势偏多/偏多 → error（红色，A 股习惯利好为红）
    // 中性 → info
    // 偏空/弱势偏空 → success（绿色）
    if (lvl.level === 'strong_bullish' || lvl.level === 'bullish') type = 'error'
    else if (lvl.level === 'neutral') type = 'info'
    else type = 'success'
    title = `${lvl.title} ${score}分`
  }

  // 辅助：4 信号买/卖计数（仅作参考展示）
  if (ind && Object.keys(ind).length > 0) {
    const macd = ind.MACD_SIGNAL || ''
    const kdj = ind.KDJ_SIGNAL || ''
    const rsi = ind.RSI_SIGNAL || ''
    const boll = ind.BOLL_SIGNAL || ''
    const buyCount = [macd, kdj, rsi, boll].filter(v => /买入|金叉|多头|超卖/.test(v)).length
    const sellCount = [macd, kdj, rsi, boll].filter(v => /卖出|死叉|空头|超买/.test(v)).length
    title += ` · ${buyCount}买/${sellCount}卖`
  }

  return { title, type, support, resist }
})

// 提取买卖信号的公共函数
function extractSignals(t, structChecks, rawRegexes) {
  if (!t) return []
  const ind = t.indicators
  if (ind && Object.keys(ind).length > 0) {
    return structChecks
      .filter(({ key, regex }) => regex.test(ind[key] || ''))
      .map(({ label }) => label)
  }
  const raw = extractText(t)
  if (!raw) return []
  return rawRegexes
    .filter(({ regex }) => regex.test(raw))
    .map(({ label }) => label)
}

const buySignals = computed(() => extractSignals(techData.value,
  [
    { label: 'MACD多头', key: 'MACD_SIGNAL', regex: /金叉|多头/ },
    { label: 'KDJ偏强', key: 'KDJ_SIGNAL', regex: /超卖|偏强/ },
    { label: 'RSI偏强', key: 'RSI_SIGNAL', regex: /偏强/ },
    { label: '布林带突破', key: 'BOLL_SIGNAL', regex: /突破上轨/ },
  ],
  [
    { label: 'MACD多头', regex: /金叉|多头/ },
    { label: 'KDJ偏强', regex: /超卖|偏强/ },
    { label: 'RSI偏强', regex: /偏强/ },
    { label: '布林带突破', regex: /突破上轨/ },
  ]
))

const sellSignals = computed(() => extractSignals(techData.value,
  [
    { label: 'MACD空头', key: 'MACD_SIGNAL', regex: /死叉|空头/ },
    { label: 'KDJ偏弱', key: 'KDJ_SIGNAL', regex: /超买|偏弱/ },
    { label: 'RSI超买', key: 'RSI_SIGNAL', regex: /超买/ },
    { label: '布林带跌破', key: 'BOLL_SIGNAL', regex: /跌破下轨/ },
  ],
  [
    { label: 'MACD空头', regex: /死叉|空头/ },
    { label: 'KDJ偏弱', regex: /超买|偏弱/ },
    { label: 'RSI超买', regex: /超买/ },
    { label: '布林带跌破', regex: /跌破下轨/ },
  ]
))

// 技术指标分流 — 趋势/动量 (左) | 震荡/量能 (右)
const TREND_KEYS = new Set(['MA5', 'MA10', 'MA20', 'MA60', 'MACD_DIF', 'MACD_DEA', 'MACD_BAR', 'KDJ_K', 'KDJ_D', 'KDJ_J'])

const techTableLeft = computed(() => {
  const t = techTable.value
  if (!Array.isArray(t)) return []
  return t.filter(r => TREND_KEYS.has(r.name) || /^(MA|MACD|KDJ)/.test(r.name))
})
const techTableRight = computed(() => {
  const t = techTable.value
  if (!Array.isArray(t)) return []
  return t.filter(r => !TREND_KEYS.has(r.name) && !/^(MA|MACD|KDJ)/.test(r.name))
})

// 数值统一格式化
function formatTechVal(v) {
  if (v === undefined || v === null || v === '--') return '--'
  const n = Number(v)
  if (Number.isNaN(n)) return v
  return n.toFixed(2)
}

// 趋势/动量板块摘要
function getTrendSummary() {
  const leftItems = techTableLeft.value
  if (!leftItems.length) return '无数据'
  const buyCount = leftItems.filter(item => /上方|红柱|多头|超卖|偏强/.test(item.signal)).length
  const sellCount = leftItems.filter(item => /下方|绿柱|空头|超买|偏弱/.test(item.signal)).length
  if (buyCount > sellCount) return '偏多'
  if (sellCount > buyCount) return '偏空'
  return '均衡'
}

function getTrendBadgeClass() {
  const summary = getTrendSummary()
  if (summary === '偏多') return 'badge-buy'
  if (summary === '偏空') return 'badge-sell'
  return 'badge-neutral'
}

// 震荡/量能板块摘要
function getOscillationSummary() {
  const rightItems = techTableRight.value
  if (!rightItems.length) return '无数据'
  const buyCount = rightItems.filter(item => /超卖|偏强|放量|压力位/.test(item.signal)).length
  const sellCount = rightItems.filter(item => /超买|偏弱|缩量|支撑位/.test(item.signal)).length
  if (buyCount > sellCount) return '偏多'
  if (sellCount > buyCount) return '偏空'
  return '均衡'
}

function getOscillationBadgeClass() {
  const summary = getOscillationSummary()
  if (summary === '偏多') return 'badge-buy'
  if (summary === '偏空') return 'badge-sell'
  return 'badge-neutral'
}

let suggestTimer = null
let suggestAbort = null
function querySearch(queryStr, cb) {
  clearTimeout(suggestTimer)
  if (suggestAbort) suggestAbort.abort()
  const s = queryStr.trim()
  if (s.length < 2) { cb([]); return }
  suggestTimer = setTimeout(async () => {
    const controller = new AbortController()
    suggestAbort = controller
    try {
      const res = await stockApi.suggest(s, controller.signal)
      const items = (res || []).map(item => ({ ...item, value: `${item.code} ${item.name}` }))
      cb(items)
    } catch { cb([]) }
  }, 400)
}

function handleSuggestSelect(item) {
  searchCode.value = item.code
  query.value = item.code
  diagnosis.refresh()
}

async function doDiagnosis() {
  let input = query.value.trim()
  if (!input) return

  if (/^\d{6}$/.test(input)) {
    searchCode.value = input
    await Promise.all([diagnosis.refresh(), newsData.refresh()])
    return
  }

  const extractedCode = input.replace(/[^0-9]/g, '')
  if (extractedCode.length === 6) {
    searchCode.value = extractedCode
    query.value = extractedCode
    await Promise.all([diagnosis.refresh(), newsData.refresh()])
    return
  }

  ElMessage.warning('请输入6位股票代码或从下拉列表中选择')
}

function quickPick(s) {
  searchCode.value = s.code
  query.value = s.code
  diagnosis.refresh()
  newsData.clear()
  newsData.refresh()
}

function openNews(n) {
  if (n.content && n.content !== n.title) {
    ElMessageBox.alert(n.content, n.title || '新闻详情', {
      confirmButtonText: '关闭',
      customClass: 'news-detail-dialog',
      dangerouslyUseHTMLString: false,
    }).catch(() => {})
  } else if (n.url) {
    window.open(n.url, '_blank')
  } else {
    ElMessage.info('暂无详细内容')
  }
}

// K线形态置信度颜色：看涨=红色系，看跌=绿色系
function getConfidenceColor(row) {
  const conf = row.confidence || 0.5
  if (row.direction === 'bearish') {
    return conf > 0.7 ? '#67c23a' : conf > 0.5 ? '#e6a23c' : '#909399'
  }
  // bullish / neutral: 红色系
  return conf > 0.7 ? '#f56c6c' : conf > 0.5 ? '#e6a23c' : '#909399'
}
</script>

<style scoped>
.stock-diagnosis { height: 100%; overflow-y: auto; padding: 10px; }
.page-title { display: flex; align-items: center; gap: 8px; margin-bottom: 20px; color: #303133; font-size: 20px; }
.search-card { z-index: 50; margin-bottom: 20px; }
.diagnose-btn {
  background: #409eff !important;
  border-color: #409eff !important;
  color: #fff !important;
}
.diagnose-btn:hover:not(:disabled) {
  background: #66b1ff !important;
  border-color: #66b1ff !important;
}
.diagnose-btn:disabled {
  opacity: 0.7 !important;
}
/* 移除 Element Plus loading 旋转动画 */
.diagnose-btn :deep(.el-icon) { animation: none !important; }
.result-card { margin-bottom: 16px; }
.quick-tags { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.label { color: #909399; font-size: 13px; }
.qtag { cursor: pointer; }

.rt-item { text-align: center; padding: 4px; }
.rt-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.rt-value { font-size: 16px; font-weight: 600; }

.fin-item { text-align: center; padding: 4px; }
.fin-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.fin-value { font-size: 15px; font-weight: 600; }

.mini-item { text-align: center; padding: 8px; }
.mi-label { color: #909399; font-size: 12px; }

.group-title { margin-bottom: 8px; font-size: 14px; color: #606266; }
.signal-list { display: flex; gap: 6px; flex-wrap: wrap; }
.sig-tag { margin: 0; }
.key-levels { text-align: center; padding: 8px; }

/* ========== 响应式断点 ========== */
@media (max-width: 768px) {
  .stock-diagnosis { padding: 6px !important; }

  /* 搜索区域 fixed 定位，紧贴 app-header(48px + safe-area) 下方 */
  .search-card {
    position: fixed !important;
    top: calc(48px + env(safe-area-inset-top, 0)) !important;
    left: 0 !important;
    right: 0 !important;
    z-index: 95 !important;
    margin-bottom: 0 !important;
  }
  .search-card :deep(.el-card__body) { padding: 6px 12px !important; }

  /* 搜索框高度缩小 */
  .search-card :deep(.el-autocomplete) { min-height: 32px !important; }
  .search-card :deep(.el-input__wrapper) { padding: 4px 8px !important; }
  .search-card :deep(.el-input__inner) { font-size: 13px !important; line-height: 24px !important; height: 24px !important; }

  /* 快捷标签紧凑 */
  .quick-tags { margin-top: 6px !important; gap: 6px !important; }
  .label { font-size: 12px !important; }
  .qtag :deep(.el-tag__content) { padding: 0 4px !important; }

  /* 内容区顶部留出搜索框空间 */
  .stock-diagnosis { padding-top: 105px !important; }

  .page-title { font-size: 16px !important; margin-bottom: 8px !important; }

  /* 实时行情改为两列 */
  .rt-item { padding: 6px 2px; }
  .rt-value { font-size: 14px !important; }

  /* 财务数据缩小 */
  .fin-value { font-size: 13px !important; }

  /* K线图 header：一行显示，缩小字体 */
  .kline-title { font-size: 12px !important; }
  .kline-period-group :deep(.el-radio-button__inner) {
    padding: 4px 8px !important;
    min-height: 28px !important;
    line-height: 20px !important;
    font-size: 11px !important;
    border-radius: 4px !important;
  }

  /* K线图高度缩小 */
  :deep(.kline-chart-container) { height: 180px !important; }

  /* 表格水平滚动 */
  :deep(.el-table) { min-width: 600px; }
  :deep(.el-table__body-wrapper) { overflow-x: auto; -webkit-overflow-scrolling: touch; }

  /* 综合评估信号列表紧凑 */
  .signal-list { gap: 4px !important; }
  .sig-tag { font-size: 12px !important; padding: 2px 6px !important; }

  /* 触摸目标最小44px */
  :deep(.el-button) { min-height: 44px; }

  /* 卡片紧凑化 */
  :deep(.el-card__header) { padding: 10px 14px !important; }
  :deep(.el-card__body) { padding: 10px 12px !important; }
}

/* 板块分析文字 */
.section-analysis {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #f0f9ff, #e8f4fd);
  border-radius: 6px;
  border-left: 3px solid #409eff;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
}

.section-analysis .el-icon {
  color: #409eff;
  flex-shrink: 0;
  margin-top: 2px;
}

/* ========== 技术指标信号板块 - 优化版 ========== */
.tech-card {
  border: 1px solid #e8edf3;
  border-radius: 12px;
  overflow: hidden;
}

.tech-card :deep(.el-card__header) {
  background: linear-gradient(135deg, #fafbfc 0%, #f5f7fa 100%);
  border-bottom: 1px solid #ebeef5;
}

.tech-summary {
  display: flex;
  gap: 12px;
  flex-shrink: 0;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
}

.summary-item.buy {
  background: rgba(245, 108, 108, 0.1);
  color: #f56c6c;
}

.summary-item.sell {
  background: rgba(103, 194, 58, 0.1);
  color: #67c23a;
}

.summary-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.tech-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 900px) {
  .tech-grid {
    grid-template-columns: 1fr;
  }
}

.tech-section {
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  overflow: hidden;
  transition: all 0.3s ease;
}

.tech-section:hover {
  border-color: #d4d9e2;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}

.tech-section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid #ebeef5;
}

.tech-section-header.trend {
  background: linear-gradient(135deg, #ecf5ff 0%, #f0f9ff 100%);
}

.tech-section-header.oscillation {
  background: linear-gradient(135deg, #fdf6ec 0%, #fff7e8 100%);
}

.section-icon {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.tech-section-header.trend .section-icon {
  background: rgba(64, 158, 255, 0.15);
  color: #409eff;
}

.tech-section-header.oscillation .section-icon {
  background: rgba(230, 162, 60, 0.15);
  color: #e6a23c;
}

.section-info {
  flex: 1;
  min-width: 0;
}

.section-title {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  line-height: 1.2;
}

.section-count {
  font-size: 11px;
  color: #909399;
  font-weight: normal;
}

.section-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.badge-buy {
  background: rgba(245, 108, 108, 0.15);
  color: #f56c6c;
}

.badge-sell {
  background: rgba(103, 194, 58, 0.15);
  color: #67c23a;
}

.badge-neutral {
  background: rgba(144, 147, 153, 0.15);
  color: #909399;
}

.tech-list-header {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0;
  padding: 8px 10px;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
  font-size: 11px;
  font-weight: 600;
  color: #909399;
}

.tech-list-header .col-name {
  text-align: left;
  padding-left: 8px;
}

.tech-list-header .col-value {
  text-align: center;
}

.tech-list-header .col-signal {
  text-align: right;
  padding-right: 8px;
}

.tech-items {
  padding: 0 10px 6px 10px;
}

.tech-item {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0;
  padding: 7px 10px;
  border-radius: 0;
  transition: all 0.2s ease;
  border: none;
  border-bottom: 1px solid #f0f2f5;
}

.tech-item:last-child {
  border-bottom: none;
}

.tech-item:hover {
  background: #fafbfc;
}

.item-col {
  min-width: 0;
}

.item-col.item-name {
  padding-left: 8px;
}

.name-text {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}

.name-desc {
  display: block;
  font-size: 10px;
  color: #909399;
  margin-top: 1px;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-col.item-value {
  text-align: center;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  font-family: 'SF Mono', 'Monaco', 'Menlo', monospace;
  white-space: nowrap;
}
.item-col.item-value.val-danger { color: #f56c6c; }
.item-col.item-value.val-success { color: #67c23a; }

.item-col.item-signal {
  display: flex;
  align-items: center;
  gap: 6px;
  justify-content: flex-end;
  padding-right: 8px;
}

.signal-indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.signal-indicator.danger {
  background: #f56c6c;
  box-shadow: 0 0 0 2px rgba(245, 108, 108, 0.2);
}

.signal-indicator.success {
  background: #67c23a;
  box-shadow: 0 0 0 2px rgba(103, 194, 58, 0.2);
}

.signal-indicator.info {
  background: #909399;
  box-shadow: 0 0 0 2px rgba(144, 147, 153, 0.2);
}

.signal-tag {
  margin: 0 !important;
  font-size: 12px !important;
  height: 22px !important;
  line-height: 20px !important;
}

/* ========== K线形态识别 - 优化版 ========== */
.pattern-card .pattern-table {
  width: 100%;
}

.pattern-header {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 0;
  padding: 10px 12px;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
  font-size: 12px;
  font-weight: 600;
  color: #606266;
}

.pattern-header .col-direction,
.pattern-header .col-name,
.pattern-header .col-date,
.pattern-header .col-confidence {
  text-align: center;
}

.pattern-body {
  min-height: 100px;
}

.pattern-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 0;
  padding: 10px 12px;
  border-bottom: 1px solid #f0f2f5;
  transition: background-color 0.2s;
}

.pattern-row:hover {
  background-color: #fafbfc;
}

.pattern-row:last-child {
  border-bottom: none;
}

.pattern-row:nth-child(even) {
  background-color: #fafafa;
}

.pattern-row .col-direction {
  display: flex;
  justify-content: center;
  align-items: center;
}

.pattern-row .col-name {
  text-align: center;
  font-size: 13px;
  color: #303133;
}

.pattern-row .col-date {
  text-align: center;
  font-size: 13px;
  color: #606266;
}

.pattern-row .col-confidence {
  text-align: center;
  font-size: 13px;
  font-weight: 600;
}

/* 响应式优化 */
@media (max-width: 768px) {
  .tech-summary {
    display: none;
  }

  .tech-list-header,
  .tech-item {
    grid-template-columns: 1fr 1fr 1fr;
    padding: 6px 8px;
  }

  .item-value {
    font-size: 12px;
  }

  .signal-tag {
    font-size: 11px !important;
    height: 20px !important;
    line-height: 18px !important;
    padding: 0 6px !important;
  }

  .pattern-header,
  .pattern-row {
    grid-template-columns: 1fr 1fr 1fr 1fr;
    padding: 8px 6px;
    font-size: 11px;
  }

  /* 技术指标板块紧凑 */
  .tech-section-header { padding: 8px 10px; gap: 6px; }
  .section-icon { width: 24px; height: 24px; font-size: 12px; }
  .section-title { font-size: 13px; }

  /* 财务数据卡片移动端：3 列 → 2 列 */
  .fin-item .fin-label { font-size: 11px; }
  .fin-item .fin-value { font-size: 13px; }

  /* 消息面卡片移动端 */
  .news-section :deep(.el-card__body) { padding: 12px; }
  .news-item { padding: 8px 4px; gap: 8px; }
  .news-sentiment { font-size: 10px !important; }
  .news-title { font-size: 12px; line-height: 1.5; }
  .news-date { font-size: 10px; }
  .news-header span:first-child { font-size: 13px; }
  .news-count { font-size: 11px; }
  .news-empty { font-size: 12px; padding: 8px; }

  /* 综合诊断的结论块（移动端） */
  .conclusion-text { font-size: 13px !important; padding: 8px 10px !important; }
  .news-sentiment-bar { font-size: 12px; padding: 6px 10px; }

  /* 实时行情紧凑 */
  .rt-row { padding: 6px 8px; }
  .rt-label { font-size: 11px; }
  .rt-value { font-size: 13px; }
}

@media (max-width: 480px) {
  /* 搜索区域 fixed 定位，紧贴 app-header(44px + safe-area) 下方 */
  .search-card {
    position: fixed !important;
    top: calc(44px + env(safe-area-inset-top, 0)) !important;
    left: 6px !important;
    right: 6px !important;
    z-index: 95 !important;
    margin-bottom: 0 !important;
  }

  /* 内容区顶部留出搜索框空间 */
  .stock-diagnosis { padding-top: 120px !important; }

  /* 财务数据：1 列 */
  .fin-item .fin-label { font-size: 10px; }
  .fin-item .fin-value { font-size: 12px; }

  /* 消息面更紧凑 */
  .news-title { font-size: 11px; }
  .news-sentiment { display: none; }
  .news-item { padding: 6px 2px; }
}

/* ═════════ 综合评估卡片 - 紧凑布局 ═════════ */
.assess-card :deep(.el-card__body) {
  padding: 8px 14px 10px;
}
.assess-card :deep(.el-card__header) {
  padding: 8px 14px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  gap: 10px;
}

.title-block {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.title-main {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.title-sub {
  font-size: 10px;
  color: #909399;
  font-weight: normal;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* 评分盒子 */
.score-box {
  display: flex;
  align-items: baseline;
  gap: 2px;
  padding: 4px 10px;
  border-radius: 6px;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  min-width: 64px;
  justify-content: center;
}
.score-box.score-strong { background: #fef0f0; border-color: #fbc4c4; }
.score-box.score-mid    { background: #fdf6ec; border-color: #f5dab1; }
.score-box.score-weak   { background: #f0f9eb; border-color: #c2e7b0; }
.score-box .score-value {
  font-size: 18px;
  font-weight: 700;
  line-height: 1;
}
.score-box.score-strong .score-value { color: #f56c6c; }
.score-box.score-mid    .score-value { color: #e6a23c; }
.score-box.score-weak   .score-value { color: #67c23a; }
.score-box .score-max {
  font-size: 10px;
  color: #909399;
  font-weight: normal;
}

.risk-stars {
  font-size: 11px;
  letter-spacing: 1px;
  cursor: help;
}
.risk-stars.risk-low  { color: #67c23a; }
.risk-stars.risk-mid  { color: #e6a23c; }
.risk-stars.risk-high { color: #f56c6c; }

/* 评分 + 风险合并区块 */
.score-risk-section {
  margin-bottom: 6px;
}
.risk-tags-inline {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  padding: 4px 0 0;
}
.risk-tags-inline .risk-icon {
  color: #e6a23c;
  font-size: 12px;
  flex-shrink: 0;
}
.risk-tags-inline .risk-tag {
  font-size: 11px;
  padding: 0 6px;
  height: 20px;
  line-height: 18px;
}

/* 决策条（结论 + 关键位 + 消息面） */
.decision-strip {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 5px 8px;
  background: linear-gradient(135deg, #f5f7fa, #fafbfc);
  border-radius: 6px;
  border: 1px solid #ebeef5;
  margin-bottom: 6px;
}
.decision-strip .decision-alert {
  flex: 1;
  min-width: 0;
}
.decision-strip :deep(.el-alert__title) {
  font-size: 12px;
  font-weight: 600;
}
.decision-strip :deep(.el-alert__content) {
  padding: 1px 0;
}
.decision-strip :deep(.el-alert) {
  padding: 4px 8px;
}

.key-levels {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
}
.key-levels .el-tag {
  font-size: 11px;
  padding: 0 5px;
  height: 20px;
  line-height: 18px;
}

.news-sentiment-inline {
  flex-shrink: 0;
}
.news-sentiment-inline .el-tag {
  font-size: 11px;
  padding: 0 6px;
  height: 20px;
  line-height: 18px;
}

/* 综合分析（紧凑列表） */
.analysis-block {
  background: #fffbf5;
  border-radius: 6px;
  padding: 6px 10px;
  border-left: 3px solid #e6a23c;
  margin-bottom: 6px;
}
.analysis-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #b88230;
  margin-bottom: 3px;
  letter-spacing: 0.5px;
}
.analysis-title .el-icon {
  font-size: 12px;
}
.analysis-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.analysis-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  line-height: 1.35;
  color: #606266;
}
.analysis-item .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 7px;
  background: #c0c4cc;
}
.analysis-item .dot.dot-conclusion {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  background: #e6a23c;
  box-shadow: 0 0 0 2px rgba(230, 162, 60, 0.15);
}
.analysis-item .text {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}

/* ── 段 3：2 列指标卡（更紧凑） ── */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
  margin-bottom: 6px;
}
.metric-card {
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.metric-title {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #606266;
  padding-bottom: 4px;
  border-bottom: 1px solid #ebeef5;
}
.metric-title .el-icon {
  color: #409eff;
  font-size: 12px;
}
.metric-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.m-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  gap: 6px;
}
.m-label {
  color: #909399;
  flex-shrink: 0;
}
.m-val {
  font-weight: 600;
  color: #303133;
  text-align: right;
  word-break: break-all;
}
.m-val .m-pct {
  font-style: normal;
  font-size: 9px;
  color: #909399;
  margin-left: 3px;
  font-weight: normal;
}
/* 颜色：操作建议 3 行 */
.m-row.buy .m-val  { color: #f56c6c; }
.m-row.stop .m-val { color: #e6a23c; }
.m-row.target .m-val { color: #f56c6c; }
/* 颜色：分周期 3 行 */
.m-val.positive { color: #f56c6c; }
.m-val.negative { color: #67c23a; }
.m-val.neutral  { color: #606266; }
.metric-empty {
  text-align: center;
  color: #c0c4cc;
  font-size: 11px;
  padding: 4px 0;
}

/* ── 段4：买卖信号（横条） ── */
.signals-bar {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.signal-group {
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 6px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.signal-group.buy {
  border-left: 3px solid #f56c6c;
}
.signal-group.sell {
  border-left: 3px solid #67c23a;
}
.signal-head {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #303133;
}
.signal-group.buy .signal-head { color: #f56c6c; }
.signal-group.sell .signal-head { color: #67c23a; }
.signal-head .el-icon { font-size: 11px; }
.signal-badge {
  margin-left: 4px;
}
.signal-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-height: 22px;
}
.sig-tag {
  margin: 0 !important;
  font-size: 11px !important;
  height: 22px !important;
  line-height: 20px !important;
  padding: 0 8px !important;
}
.signal-empty {
  color: #c0c4cc;
  font-size: 11px;
  font-style: italic;
  line-height: 22px;
}

/* 财务数据紧凑布局（其他卡片用） */
.fin-item {
  text-align: center;
  padding: 8px 4px;
}
.fin-label {
  font-size: 11px;
  color: #909399;
  margin-bottom: 4px;
}
.fin-value {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.c-red { color: #f56c6c !important; }
.c-green { color: #67c23a !important; }

.kline-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.kline-title { font-size: 14px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ── 响应式 ── */
@media (max-width: 1100px) {
  .metrics-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .signals-bar {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .metrics-grid {
    grid-template-columns: 1fr;
  }
  .header-right {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    width: 100%;
  }
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
  .decision-strip {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    padding: 6px 8px;
  }
  .key-levels {
    justify-content: center;
    width: 100%;
  }

  /* 综合评估卡片紧凑 */
  .assess-card :deep(.el-card__body) { padding: 10px 12px !important; }
  .score-box { min-width: 70px; padding: 6px 10px; }
  .score-value { font-size: 20px !important; }

  /* 分析块紧凑 */
  .analysis-block { padding: 8px 12px; }
  .analysis-item { font-size: 12px; gap: 6px; }

  /* 指标卡片紧凑 */
  .metric-card { padding: 10px 12px; }
  .m-row { font-size: 11px; }

  /* 信号栏单列 */
  .signals-bar { grid-template-columns: 1fr; gap: 8px; }
  .signal-group { padding: 8px 10px; }
}

@media (max-width: 480px) {
  .page-title { font-size: 15px !important; margin-bottom: 6px !important; }
  .quick-tags { gap: 4px !important; }
  :deep(.el-tag) { min-height: 32px; line-height: 30px; }
}

/* 板块归属标签 */
.block-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 0;
}
.block-tag {
  font-size: 13px !important;
}

/* 消息面 */
.news-section .news-header { display: flex; justify-content: space-between; align-items: center; }
.news-count { font-size: 12px; color: #909399; }
.news-list { max-height: 240px; overflow-y: auto; }
.news-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f0f0f0;
}
.news-item:last-child { border-bottom: none; }
.news-sentiment { flex-shrink: 0; font-size: 12px; }
.news-title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; color: #303133; font-size: 14px; }
.news-title:hover { color: #409eff; }
.news-date { flex-shrink: 0; font-size: 12px; color: #909399; }
.news-source-tag { flex-shrink: 0; font-size: 11px; margin-left: 4px; }

@media (max-width: 768px) {
  .news-item { gap: 4px; padding: 4px 0; }
  .news-title { font-size: 12px; }
}
.news-empty { display: flex; align-items: center; gap: 6px; padding: 12px; color: #909399; font-size: 14px; }

.is-loading { animation: rotating 1.4s linear infinite; color: #909399; }
@keyframes rotating { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* ========== 消息面情感条 ========== */
.news-sentiment-bar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; margin: 10px 0 0; background: #f5f7fa; border-radius: 6px; border-left: 3px solid #909399; font-size: 13px; color: #606266; }
.news-sentiment-bar .ns-label { font-weight: 500; }
.news-sentiment-bar .el-icon { color: #909399; }
.news-sentiment-bar .color-help { color: #c0c4cc; cursor: help; margin-left: 2px; font-size: 14px; }
.news-sentiment-bar .ns-score { margin-left: auto; color: #606266; font-size: 12px; font-weight: 500; }

/* ========== 评分构成可视化（P2 新增） ========== */
.score-breakdown { padding: 6px 4px 8px; border-bottom: 1px dashed #ebeef5; margin-bottom: 6px; }
.score-breakdown .sb-row { display: grid; grid-template-columns: 80px 1fr 36px; align-items: center; gap: 8px; padding: 2px 0; }
.score-breakdown .sb-label { display: flex; flex-direction: column; gap: 1px; }
.score-breakdown .sb-name { font-size: 12px; color: #303133; font-weight: 500; }
.score-breakdown .sb-weight { font-size: 10px; color: #909399; }
.score-breakdown .sb-bar-wrap { height: 6px; background: #f0f2f5; border-radius: 3px; overflow: hidden; }
.score-breakdown .sb-bar { height: 100%; border-radius: 3px; transition: width 0.6s ease; }
.score-breakdown .sb-score { font-size: 13px; font-weight: 600; text-align: right; }
.score-breakdown .sb-sub-scores { display: flex; flex-wrap: wrap; gap: 4px 8px; margin-top: 4px; padding-top: 4px; border-top: 1px dashed #f5f7fa; font-size: 10px; color: #909399; }
.score-breakdown .sb-sub-item { background: #f5f7fa; padding: 1px 4px; border-radius: 3px; }
.score-breakdown .sb-sub-industry { color: #67c23a; }

/* 风险与得分冲突警示 */
.risk-conflict-alert { margin: 4px 0 6px; }

/* 风险等级常驻显示 */
.risk-reasons-box { margin: 4px 0 6px; padding: 6px 10px; background: #fff8e1; border: 1px solid #ffecb3; border-radius: 6px; }
.risk-reasons-box .rr-title { display: flex; align-items: center; gap: 4px; color: #e6a23c; font-size: 12px; font-weight: 500; margin-bottom: 2px; }
.risk-reasons-box .rr-list { display: flex; flex-direction: column; gap: 1px; }
.risk-reasons-box .rr-item { display: flex; align-items: flex-start; gap: 6px; font-size: 11px; color: #606266; line-height: 1.4; }
.risk-reasons-box .rr-dot { display: inline-block; width: 4px; height: 4px; border-radius: 50%; background: #e6a23c; margin-top: 5px; flex-shrink: 0; }

/* 评分等级标题（在评分数字下方） */
.score-box { position: relative; }
.score-box .score-level-title { display: block; font-size: 11px; color: #909399; font-weight: 500; text-align: center; margin-top: 2px; }

/* 操作建议仓位行 */
.metric-body .position-row .m-val { color: #409eff; font-weight: 500; }

/* ========== 诊断失败卡片 ========== */
.diag-error { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 24px 16px; }
.diag-error-title { margin: 4px 0 0; color: #606266; font-size: 16px; font-weight: 500; }
.diag-error-msg { margin: 0 0 8px; color: #909399; font-size: 13px; line-height: 1.6; max-width: 480px; text-align: center; word-break: break-all; }

/* ========== K线形态头部/底部 ========== */
.pattern-header-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.pattern-footer { text-align: center; padding: 8px 0 0; border-top: 1px dashed #ebeef5; margin-top: 8px; }

/* ========== 决策摘要理由 ========== */
.signal-reasons { display: flex; flex-direction: column; gap: 1px; margin-top: 3px; }
.reason-item { font-size: 12px; color: #606266; line-height: 1.4; padding: 1px 0; border-bottom: 1px dashed #f0f0f0; }
.reason-item:last-child { border-bottom: none; }
.signal-empty { font-size: 11px; color: #c0c4cc; padding: 2px 0; }

/* ========== 手机端布局优化 ========== */
@media (max-width: 768px) {
  .result-card { margin-bottom: 10px !important; margin-top: 10px !important; }
  .result-card :deep(.el-card__body) { padding: 8px 10px !important; }
  .result-card :deep(.el-card__header) { padding: 6px 10px !important; font-size: 13px; }

  /* 综合诊断卡片头部 */
  .assess-card .card-header { flex-direction: row; align-items: center; gap: 6px; flex-wrap: nowrap; }
  .assess-card .title-block { flex-shrink: 0; }
  .assess-card .title-main { font-size: 13px; white-space: nowrap; }
  .assess-card .title-sub { display: none; }
  .assess-card .title-time { display: block; font-size: 9px; color: #c0c4cc; margin-top: 1px; }
  .assess-card .header-right { gap: 6px; }
  .assess-card .score-box { min-width: 44px; padding: 2px 6px; }
  .assess-card .score-value { font-size: 16px; }
  .assess-card .score-max { font-size: 9px; }
  .assess-card .score-level-title { font-size: 9px; }

  /* 评分构成可视化（手机端紧凑） */
  .score-breakdown { padding: 4px 0 6px; }
  .score-breakdown .sb-row { grid-template-columns: 64px 1fr 28px; gap: 4px; }
  .score-breakdown .sb-name { font-size: 11px; }
  .score-breakdown .sb-weight { font-size: 9px; }
  .score-breakdown .sb-bar-wrap { height: 5px; }
  .score-breakdown .sb-score { font-size: 11px; }
  .score-breakdown .sb-sub-scores { font-size: 9px; gap: 3px 4px; }
  .score-breakdown .sb-sub-item { padding: 1px 3px; }

  /* 风险常驻（手机端紧凑） */
  .risk-reasons-box { padding: 4px 8px; margin: 3px 0 4px; }
  .risk-reasons-box .rr-title { font-size: 11px; }
  .risk-reasons-box .rr-item { font-size: 10px; }

  /* 决策条 */
  .decision-strip { flex-direction: column; gap: 6px; }
  .key-levels { align-self: flex-start; flex-wrap: wrap; gap: 3px; }
  .key-levels .el-tag { font-size: 10px; padding: 0 4px; height: 20px; line-height: 18px; }
  .key-levels .m-pct { font-size: 9px; }

  /* 综合分析列表 */
  .analysis-block { padding: 4px 8px; }
  .analysis-list { padding-left: 12px; }
  .analysis-item { font-size: 11px; line-height: 1.4; }

  /* 4 指标卡改单列 */
  .metrics-grid { grid-template-columns: 1fr !important; gap: 6px; }
  .metric-card { padding: 6px 8px; }
  .metric-title { font-size: 11px; margin-bottom: 3px; }
  .m-row { font-size: 11px; padding: 1px 0; }
  .m-label { min-width: 56px; font-size: 10px; }
  .m-val { font-size: 11px; }

  /* 信号栏改单列 */
  .signals-bar { flex-direction: column; gap: 6px; }
  .signal-group { padding: 6px 8px; }
  .signal-head { font-size: 11px; }
  .reason-item { font-size: 11px; padding: 2px 0; }

  /* 实时行情 */
  .rt-item { padding: 4px 2px; }
  .rt-label { font-size: 11px; }
  .rt-value { font-size: 14px; }

  /* K线形态 */
  .pattern-header-bar { flex-direction: row; align-items: center; justify-content: space-between; gap: 8px; }
  .pattern-table { font-size: 12px; }
  .col-name { font-size: 12px; }
  .col-date { font-size: 11px; }
  .pattern-footer { text-align: center; }

  /* 诊断失败 */
  .diag-error { padding: 16px 12px; }
  .diag-error-title { font-size: 15px; }
  .diag-error-msg { font-size: 12px; line-height: 1.5; max-width: 100%; }

  /* 财务数据 */
  .fin-item { padding: 4px 2px; }
  .fin-label { font-size: 11px; }
  .fin-value { font-size: 13px; }

  /* K线图高度 */
  .kline-chart-container { height: 150px !important; }

  /* 消息面情感条（手机端紧凑） */
  .news-sentiment-bar { padding: 6px 10px; font-size: 12px; flex-wrap: wrap; }
  .news-sentiment-bar .ns-score { margin-left: 0; font-size: 11px; }
}

@media (max-width: 768px) {
  .stock-diagnosis { padding: 0; background: var(--m-bg, #f5f7fa); }
  .stock-diagnosis .search-bar { display: none; }

  /* ── Price header ── */
  .stock-diagnosis .price-header { display: flex; align-items: baseline; gap: 10px; padding: 12px 16px; background: var(--m-surface, #fff); border-bottom: 1px solid var(--m-border, #e0e4ea); }
  .stock-diagnosis .price-header .big-price { font-size: 28px; font-weight: 700; }
  .stock-diagnosis .price-header .chg { font-size: 15px; font-weight: 600; }
  .stock-diagnosis .price-header .meta { font-size: 11px; color: var(--m-text3, #8e99ab); margin-left: auto; }

  /* ── K-line: full width ── */
  .stock-diagnosis .kline-section { padding: 8px 12px; background: var(--m-surface, #fff); margin-bottom: 8px; }
  .stock-diagnosis .kline-tabs { display: flex; gap: 2px; background: var(--m-surface2, #f0f2f5); border-radius: 8px; padding: 3px; margin-bottom: 8px; border: 1px solid var(--m-border, #e0e4ea); }
  .stock-diagnosis .kline-tabs .ktab { flex: 1; text-align: center; padding: 6px 0; border-radius: 6px; font-size: 12px; border: none; background: none; color: var(--m-text3, #8e99ab); cursor: pointer; }
  .stock-diagnosis .kline-tabs .ktab.active { background: var(--m-accent, #5b7cfa); color: #fff; }
  .stock-diagnosis .kline-chart-container { height: 220px !important; border-radius: 12px; overflow: hidden; }

  /* ── Metrics grid → horizontal pills ── */
  .stock-diagnosis .metrics-grid { display: flex; gap: 6px; overflow-x: auto; padding: 8px 12px; scrollbar-width: none; }
  .stock-diagnosis .metrics-grid::-webkit-scrollbar { display: none; }
  .stock-diagnosis .metric-card { flex-shrink: 0; padding: 6px 14px; border-radius: 16px; font-size: 12px; background: var(--m-surface, #fff); border: 1px solid var(--m-border, #e0e4ea); white-space: nowrap; box-shadow: none; min-width: auto; }

  /* ── Info panels ── */
  .stock-diagnosis .info-panels { padding: 0 12px 8px; }
  .stock-diagnosis .info-panels .el-card { border-radius: 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.04); }
  .stock-diagnosis .info-panels .el-card__body { padding: 12px 14px !important; }

  /* ── Desktop only ── */
  .stock-diagnosis .desktop-only { display: none; }
}

@media (max-width: 480px) {
  .stock-diagnosis .price-header { padding: 8px 12px; }
  .stock-diagnosis .price-header .big-price { font-size: 24px; }
  .stock-diagnosis .kline-chart-container { height: 180px !important; }

  /* 移动端评分环缩小 */
  .m-diag-score .m-score-ring { padding: 12px; gap: 12px; }
  .m-diag-score .m-score-ring .ring { width: 52px; height: 52px; }
  .m-diag-score .m-score-ring .ring::after { width: 42px; height: 42px; }
  .m-diag-score .m-score-ring .ring .val { font-size: 15px; }
  .m-diag-score .m-score-ring .detail .row { font-size: 11px; padding: 2px 0; }

  /* stats row 缩小 */
  .m-stats-row { gap: 6px !important; }
  .m-stat-card { padding: 8px 4px !important; }
  .m-stat-card .val { font-size: 14px !important; }
  .m-stat-card .lbl { font-size: 9px !important; }

  /* m-card 紧凑 */
  .m-card { padding: 12px !important; margin-bottom: 8px !important; }
  .m-card-header { font-size: 13px !important; padding-bottom: 6px !important; }

  /* 技术指标 pills 缩小 */
  .m-pill { padding: 4px 10px !important; font-size: 11px !important; }

  /* section header 紧凑 */
  .m-section-header { font-size: 13px !important; padding: 10px 0 4px !important; }
}

/* ════════ 移动端诊断页专属样式 ════════ */
.m-diag-score { margin-bottom: 12px; }

.m-diag-metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid var(--m-border, #e0e4ea);
  font-size: 12px;
}
.m-diag-metric-row:last-child { border-bottom: none; }
.m-diag-metric-row .lbl {
  color: var(--m-text3, #8e99ab);
  flex-shrink: 0;
}
.m-diag-metric-row .val {
  font-weight: 600;
  color: var(--m-text, #1a2332);
  text-align: right;
}
.m-diag-metric-row .val.up { color: var(--m-up, #e74c3c); }
.m-diag-metric-row .val.down { color: var(--m-down, #2ecc71); }
.m-diag-metric-row .val.accent { color: var(--m-accent, #5b7cfa); }

/* 评分环内文字颜色 */
.score-strong_bullish { color: var(--m-up, #e74c3c) !important; font-weight: 600; }
.score-bullish { color: var(--m-gold, #f0b429) !important; font-weight: 600; }
.score-neutral { color: var(--m-text2, #5a6577) !important; }
.score-bearish { color: var(--m-down, #2ecc71) !important; font-weight: 600; }
.score-strong_bearish { color: var(--m-down, #2ecc71) !important; font-weight: 700; }

/* 移动端页面整体间距 */
@media (max-width: 768px) {
  .stock-diagnosis { padding: 0 !important; background: var(--m-bg, #f5f7fa); }
  .stock-diagnosis > .m-card,
  .stock-diagnosis > .m-score-ring,
  .stock-diagnosis > .m-stats-row,
  .stock-diagnosis > .m-section-header { padding-left: 12px; padding-right: 12px; }

  /* m-section-header 不需要卡片内边距 */
  .stock-diagnosis > .m-section-header { padding-left: 16px; padding-right: 16px; }

  /* m-stats-row 和 m-score-ring 的外层间距 */
  .stock-diagnosis > .m-stats-row { margin-left: 12px; margin-right: 12px; }
  .stock-diagnosis > .m-diag-score { padding-left: 12px; padding-right: 12px; }

  /* 搜索区域 fixed */
  .search-card {
    position: fixed !important;
    top: calc(48px + env(safe-area-inset-top, 0)) !important;
    left: 0 !important;
    right: 0 !important;
    z-index: 95 !important;
    margin-bottom: 0 !important;
    border-radius: 0 !important;
  }
  .search-card :deep(.el-card__body) { padding: 6px 12px !important; }

  /* 内容区顶部留出搜索框空间 */
  .stock-diagnosis { padding-top: 95px !important; }

  /* page-title 在移动端隐藏（header 已显示） */
  .page-title { display: none !important; }

  /* loading skeleton 紧凑 */
  .result-card :deep(.el-skeleton) { padding: 12px; }

  /* ════════ 移动端算法信号矩阵 ════════ */
  .m-algo-score-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
  }
  .m-algo-ring {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    position: relative;
  }
  .m-algo-ring::before {
    content: '';
    position: absolute;
    inset: 4px;
    border-radius: 50%;
    background: var(--m-surface, #fff);
  }
  .m-algo-ring .val {
    position: relative;
    z-index: 1;
    font-size: 14px;
    font-weight: 700;
    color: var(--m-text, #1a2332);
  }
  .m-algo-info {
    flex: 1;
    min-width: 0;
  }
  .m-algo-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
  }
  .m-algo-badge.sig-buy { background: rgba(245, 108, 108, 0.1); color: #f56c6c; }
  .m-algo-badge.sig-sell { background: rgba(103, 194, 58, 0.1); color: #67c23a; }
  .m-algo-badge.sig-neutral { background: rgba(144, 147, 153, 0.1); color: #909399; }
  .m-algo-count {
    font-size: 11px;
    color: var(--m-text3, #8e99ab);
    margin-top: 2px;
  }
  .m-algo-list {
    padding: 0 14px 10px;
  }
  .m-algo-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 0;
    border-bottom: 1px solid var(--m-border, #e0e4ea);
    font-size: 12px;
  }
  .m-algo-item:last-child { border-bottom: none; }
  .m-algo-name {
    color: var(--m-text2, #5a6577);
  }
  .m-algo-signal {
    padding: 1px 6px;
    border-radius: 8px;
    font-size: 10px;
    font-weight: 600;
  }
  .m-algo-signal.sig-buy { background: rgba(245, 108, 108, 0.1); color: #f56c6c; }
  .m-algo-signal.sig-sell { background: rgba(103, 194, 58, 0.1); color: #67c23a; }
  .m-algo-signal.sig-neutral { background: rgba(144, 147, 153, 0.1); color: #909399; }
}

/* ════════ 桌面端算法信号矩阵 ════════ */
.algo-matrix-card :deep(.el-card__body) {
  padding: 12px 16px;
}

.algo-score-section {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 0 14px;
  border-bottom: 1px solid #f0f2f5;
  margin-bottom: 14px;
}

.algo-ring-container {
  flex-shrink: 0;
}

.algo-ring {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.algo-ring-inner {
  position: absolute;
  inset: 6px;
  border-radius: 50%;
  background: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.algo-score-val {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  line-height: 1;
}

.algo-score-label {
  font-size: 10px;
  color: #909399;
  margin-top: 2px;
}

.algo-overall-info {
  flex: 1;
  min-width: 0;
}

.algo-signal-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 600;
}

.algo-signal-badge.sig-buy { background: rgba(245, 108, 108, 0.1); color: #f56c6c; }
.algo-signal-badge.sig-sell { background: rgba(103, 194, 58, 0.1); color: #67c23a; }
.algo-signal-badge.sig-neutral { background: rgba(144, 147, 153, 0.1); color: #909399; }

.algo-stock-name {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.algo-summary-badge {
  display: flex;
  gap: 8px;
  align-items: center;
}

.summary-buy {
  font-size: 12px;
  color: #f56c6c;
  font-weight: 600;
}

.summary-sell {
  font-size: 12px;
  color: #67c23a;
  font-weight: 600;
}

.summary-neutral {
  font-size: 12px;
  color: #909399;
  font-weight: 500;
}

.algo-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}

@media (max-width: 1200px) {
  .algo-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 900px) {
  .algo-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.algo-cell {
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  transition: all 0.2s ease;
}

.algo-cell:hover {
  border-color: #d4d9e2;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.algo-cell-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.algo-cell-name {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.algo-cell-signal {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.algo-cell-signal.sig-buy { background: rgba(245, 108, 108, 0.1); color: #f56c6c; }
.algo-cell-signal.sig-sell { background: rgba(103, 194, 58, 0.1); color: #67c23a; }
.algo-cell-signal.sig-neutral { background: rgba(144, 147, 153, 0.1); color: #909399; }

.algo-cell-desc {
  font-size: 11px;
  color: #909399;
}
</style>
