<template>
  <div class="dragon-page">
    <!-- 桌面端 Header -->
    <div class="page-header" v-if="!isMobile">
      <h2 class="page-title"><el-icon><TrendCharts /></el-icon> 龙虎榜分析</h2>
      <div class="header-right">
        <RefreshingIndicator :show="anyRefreshing" text="数据更新中" />
        <el-button size="small" :icon="Refresh" @click="refreshActiveTab">刷新当前</el-button>
        <span class="update-time">{{ lastUpdateText }}</span>
      </div>
    </div>

    <!-- 移动端 Header：方案A渐变卡片风格 -->
    <div class="m-page-header" v-else>
      <div class="m-header-card">
        <div class="m-header-left">
          <div class="m-header-icon">📊</div>
          <div class="m-header-info">
            <div class="m-header-title">龙虎榜分析</div>
            <div class="m-header-time">{{ lastUpdateText }}</div>
          </div>
        </div>
        <div class="m-header-right">
          <RefreshingIndicator :show="anyRefreshing" text="" />
          <div class="m-refresh-btn" @click="refreshActiveTab">
            <el-icon :class="{ 'm-refresh-spin': anyRefreshing }"><Refresh /></el-icon>
          </div>
        </div>
      </div>
    </div>

    <!-- 移动端胶囊导航 + 数据摘要（仅手机端显示） -->
    <div class="mobile-tab-nav">
      <div class="m-pill-scroll">
        <span v-for="tab in dragonTabList" :key="tab.name" class="m-pill" :class="{ 'm-pill--active': activeTab === tab.name }" @click="activeTab = tab.name">
          {{ tab.icon }} {{ tab.label }}
          <span v-if="tab.badge" class="m-pill-badge">{{ tab.badge }}</span>
        </span>
      </div>
      <div class="m-summary-bar" v-if="activeTab === 'today' && todaySummary">
        <div class="m-summary-item">
          <div class="m-summary-val c-red">{{ todaySummary.total_net >= 0 ? '+' : '' }}{{ formatMoney(todaySummary.total_net) }}</div>
          <div class="m-summary-label">总净买入</div>
        </div>
        <div class="m-summary-item">
          <div class="m-summary-val" style="color:var(--m-accent,#5b7cfa)">{{ todayList.length }}只</div>
          <div class="m-summary-label">上榜数</div>
        </div>
        <div class="m-summary-item">
          <div class="m-summary-val c-green">{{ todaySummary.inst_buy_count || 0 }}只</div>
          <div class="m-summary-label">机构买入</div>
        </div>
      </div>
    </div>

    <el-tabs v-model="activeTab" type="border-card" class="dragon-tabs">
      <!-- 龙虎榜 -->
      <el-tab-pane label="龙虎榜" name="today">
        <div class="table-toolbar">
          <span class="toolbar-info">共 {{ todayList.length }} 只上榜</span>
        </div>
        <el-empty v-if="!loading && !todayList.length"
          description="今日暂无龙虎榜数据（可能为非交易日或已收盘）" :image-size="80" />
        <template v-else>
        <el-row :gutter="12" class="summary-row" v-if="todaySummary && todaySummary.total_net">
          <el-col :xs="12" :sm="6">
            <div class="summary-card">
              <div class="summary-num c-red">{{ todaySummary.total_net >= 0 ? '+' : '' }}{{ formatMoney(todaySummary.total_net) }}</div>
              <div class="summary-label">整体净买入</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="6">
            <div class="summary-card">
              <div class="summary-num c-red">{{ todaySummary.inst_buy_count || 0 }}只</div>
              <div class="summary-label">净买入上榜</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="6">
            <div class="summary-card">
              <div class="summary-num c-green">{{ todaySummary.inst_sell_count || 0 }}只</div>
              <div class="summary-label">净卖出上榜</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="6">
            <div class="summary-card">
              <div class="summary-num">{{ todaySummary.total_amount ? formatMoney(todaySummary.total_amount) : '--' }}</div>
              <div class="summary-label">总成交额</div>
            </div>
          </el-col>
        </el-row>
        <!-- 桌面端表格 -->
        <div class="table-section" v-if="!isMobile">
        <el-table :data="paginatedTodayList" stripe border v-loading="loading" height="100%" class="dragon-table">
          <el-table-column type="index" width="36" label="#" fixed="left" />
          <el-table-column prop="code" label="代码" width="72" sortable fixed="left" />
          <el-table-column prop="name" label="名称" min-width="80" show-overflow-tooltip fixed="left" />
          <el-table-column prop="price" label="最新价" width="75" sortable>
            <template #default="{ row }">¥{{ row.price || '--' }}</template>
          </el-table-column>
          <el-table-column prop="change_pct" label="涨跌幅" width="80" sortable>
            <template #default="{ row }">
              <span :class="numColorClass(row.change_pct)">{{ formatPct(row.change_pct) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="buy_amount" label="买入额" width="90">
            <template #default="{ row }"><span class="c-red">{{ formatMoney(row.buy_amount) }}</span></template>
          </el-table-column>
          <el-table-column prop="sell_amount" label="卖出额" width="90">
            <template #default="{ row }"><span class="c-green">{{ formatMoney(row.sell_amount) }}</span></template>
          </el-table-column>
          <el-table-column prop="net_amount" label="净买入" width="90">
            <template #default="{ row }">
              <span :class="row.net_amount >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="上榜原因" min-width="150" show-overflow-tooltip />
          <el-table-column prop="direction" label="资金方向" width="70">
            <template #default="{ row }">
              <el-tag :type="row.direction === '净买入' ? 'danger' : row.direction === '净卖出' ? 'success' : 'info'" size="small">{{ row.direction || '--' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right" class-name="diag-col">
            <template #default="{ row }">
              <el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button>
            </template>
          </el-table-column>
        </el-table>
        </div>
        <!-- 移动端卡片列表 -->
        <div class="dragon-mobile-list" v-else v-loading="loading">
          <div v-for="(row, idx) in paginatedTodayList" :key="row.code + idx" class="m-card dragon-stock-card" @click="goDiag(row.code)">
            <div class="dragon-card-top">
              <div class="dragon-card-rank">{{ idx + 1 }}</div>
              <div class="dragon-card-info">
                <span class="dragon-card-name">{{ row.name }}</span>
                <span class="dragon-card-code">{{ row.code }}</span>
              </div>
              <div class="dragon-card-price-col">
                <div class="dragon-card-price">¥{{ row.price || '--' }}</div>
                <div class="dragon-card-chg" :class="(row.change_pct || 0) >= 0 ? 'up' : 'down'">{{ formatPct(row.change_pct) }}</div>
              </div>
            </div>
            <div class="dragon-card-mid">
              <span class="dragon-flow-item"><span class="flow-label">买入</span><span class="c-red">{{ formatMoney(row.buy_amount) }}</span></span>
              <span class="dragon-flow-item"><span class="flow-label">卖出</span><span class="c-green">{{ formatMoney(row.sell_amount) }}</span></span>
              <span class="dragon-flow-item"><span class="flow-label">净买</span><span :class="(row.net_amount || 0) >= 0 ? 'c-red' : 'c-green'" style="font-weight:600">{{ formatMoney(row.net_amount) }}</span></span>
            </div>
            <div class="dragon-card-bottom">
              <el-tag v-if="row.direction" :type="row.direction === '净买入' ? 'danger' : 'success'" size="small" round>{{ row.direction }}</el-tag>
              <span class="dragon-reason" v-if="row.reason">{{ row.reason }}</span>
            </div>
          </div>
        </div>
        <!-- 分页组件 -->
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="todayPage"
            v-model:page-size="todayPageSize"
            :page-sizes="todayPageSizeOptions"
            :total="todayList.length"
            :layout="paginationLayout"
            background
            @size-change="todayPage = 1"
          />
        </div>
        </template>
      </el-tab-pane>

      <!-- 次日表现 -->
      <el-tab-pane label="次日表现" name="nextday">
        <div class="table-toolbar">
          <span class="toolbar-info">上榜后1/2/5/10日涨跌追踪（共{{ nextDayStats.count || 0 }}只，有效数据{{ nextDayStats.valid_count || 0 }}只）</span>
        </div>
        <el-empty v-if="!loadingNextDay && !nextDayList.length"
          description="暂无上榜次日表现数据" :image-size="80" />
        <template v-else>
        <el-row :gutter="16" class="stats-row">
          <el-col :span="6">
            <el-card shadow="hover" class="stat-card">
              <div class="stat-number" :class="(nextDayStats.avg_day1 || 0) >= 0 ? 'c-red' : 'c-green'">{{ formatPct(nextDayStats.avg_day1) }}</div>
              <div class="stat-desc">次日平均涨跌</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover" class="stat-card">
              <div class="stat-number" :class="(nextDayStats.avg_day5 || 0) >= 0 ? 'c-red' : 'c-green'">{{ formatPct(nextDayStats.avg_day5) }}</div>
              <div class="stat-desc">5日平均涨跌</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover" class="stat-card">
              <div class="stat-number" :class="(nextDayStats.avg_day10 || 0) >= 0 ? 'c-red' : 'c-green'">{{ formatPct(nextDayStats.avg_day10) }}</div>
              <div class="stat-desc">10日平均涨跌</div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card shadow="hover" class="stat-card">
              <div class="stat-number" :class="(nextDayStats.win_rate_day1 || 0) >= 50 ? 'c-red' : 'c-green'">{{ nextDayStats.win_rate_day1 || 0 }}%</div>
              <div class="stat-desc">次日胜率({{ nextDayStats.valid_count || 0 }}/{{ nextDayStats.count || 0 }})</div>
            </el-card>
          </el-col>
        </el-row>
        <!-- 桌面端表格 -->
        <div class="table-section" v-if="!isMobile">
        <el-table :data="pagedNextDayList" stripe v-loading="loadingNextDay" height="100%" border>
          <el-table-column type="index" width="36" label="#" fixed="left" />
          <el-table-column prop="code" label="代码" width="72" fixed="left" />
          <el-table-column prop="name" label="名称" min-width="75" show-overflow-tooltip fixed="left" />
          <el-table-column prop="price" label="最新价" width="70" sortable>
            <template #default="{ row }">¥{{ row.price || '--' }}</template>
          </el-table-column>
          <el-table-column prop="change_pct" label="上榜日涨跌" min-width="85" sortable>
            <template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'">{{ formatPct(row.change_pct) }}</span></template>
          </el-table-column>
          <el-table-column prop="net_amount" label="净买入" min-width="85">
            <template #default="{ row }"><span :class="row.net_amount >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template>
          </el-table-column>
          <el-table-column prop="day1" label="次日涨跌" min-width="75">
            <template #default="{ row }"><span v-if="row.day1 != null" :class="row.day1 >= 0 ? 'c-red' : 'c-green'">{{ formatPct(row.day1) }}</span><span v-else class="c-gray">--</span></template>
          </el-table-column>
          <el-table-column prop="day2" label="2日涨跌" min-width="75">
            <template #default="{ row }"><span v-if="row.day2 != null" :class="row.day2 >= 0 ? 'c-red' : 'c-green'">{{ formatPct(row.day2) }}</span><span v-else class="c-gray">--</span></template>
          </el-table-column>
          <el-table-column prop="day5" label="5日涨跌" min-width="75">
            <template #default="{ row }"><span v-if="row.day5 != null" :class="row.day5 >= 0 ? 'c-red' : 'c-green'">{{ formatPct(row.day5) }}</span><span v-else class="c-gray">--</span></template>
          </el-table-column>
          <el-table-column prop="day10" label="10日涨跌" min-width="75">
            <template #default="{ row }"><span v-if="row.day10 != null" :class="row.day10 >= 0 ? 'c-red' : 'c-green'">{{ formatPct(row.day10) }}</span><span v-else class="c-gray">--</span></template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right" class-name="diag-col">
            <template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template>
          </el-table-column>
        </el-table>
        </div>
        <!-- 移动端卡片列表 -->
        <div class="dragon-mobile-list" v-else v-loading="loadingNextDay">
          <div v-for="(row, idx) in pagedNextDayList" :key="row.code + idx" class="m-card dragon-stock-card" @click="goDiag(row.code)">
            <div class="dragon-card-top">
              <div class="dragon-card-rank">{{ idx + 1 }}</div>
              <div class="dragon-card-info">
                <span class="dragon-card-name">{{ row.name }}</span>
                <span class="dragon-card-code">{{ row.code }}</span>
              </div>
              <div class="dragon-card-price-col">
                <div class="dragon-card-price">¥{{ row.price || '--' }}</div>
                <div class="dragon-card-chg" :class="(row.day1 ?? 0) >= 0 ? 'up' : 'down'">{{ row.day1 != null ? formatPct(row.day1) : '--' }}</div>
              </div>
            </div>
            <div class="dragon-card-bottom">
              <span class="dragon-card-pill" :class="(row.day5 ?? 0) >= 0 ? 'm-text-up' : 'm-text-down'">5日 {{ row.day5 != null ? formatPct(row.day5) : '--' }}</span>
              <span class="dragon-card-pill" :class="(row.day10 ?? 0) >= 0 ? 'm-text-up' : 'm-text-down'">10日 {{ row.day10 != null ? formatPct(row.day10) : '--' }}</span>
            </div>
          </div>
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="nextDayPage"
            :page-size="PAGE_SIZE"
            :total="nextDayList.length"
            :layout="paginationLayoutFixed"
            background
          />
        </div>
        </template>
      </el-tab-pane>

      <!-- 连续上榜 -->
      <el-tab-pane label="连续上榜" name="consecutive">
        <div class="table-toolbar">
          <div class="toolbar-left">
            <span class="toolbar-info">多次上榜股票</span>
            <el-select v-model="consecutiveDays" size="small" style="width: 90px; margin-left: 8px;" @change="loadConsecutive">
              <el-option label="近3日" :value="3" />
              <el-option label="近5日" :value="5" />
              <el-option label="近10日" :value="10" />
            </el-select>
          </div>
        </div>
        <el-empty v-if="!loadingConsecutive && !consecutiveList.length"
          description="近{{ consecutiveDays }}日内无连续上榜的股票" :image-size="80" />
        <template v-else>
        <!-- 桌面端表格 -->
        <div class="table-section" v-if="!isMobile">
        <el-table :data="pagedConsecutiveList" stripe border v-loading="loadingConsecutive" height="100%">
          <el-table-column type="index" width="48" label="#" fixed="left" />
          <el-table-column prop="code" label="代码" width="78" fixed="left" />
          <el-table-column prop="name" label="名称" width="88" fixed="left" />
          <el-table-column prop="price" label="最新价" width="88" sortable>
            <template #default="{ row }">¥{{ row.price || '--' }}</template>
          </el-table-column>
          <el-table-column prop="count" label="上榜次数" width="90" sortable>
            <template #default="{ row }"><el-tag :type="row.count >= 3 ? 'danger' : row.count >= 2 ? 'warning' : 'info'" size="small">{{ row.count }}次</el-tag></template>
          </el-table-column>
          <el-table-column prop="total_net" label="累计净买入" width="90">
            <template #default="{ row }"><span :class="row.total_net >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.total_net) }}</span></template>
          </el-table-column>
          <el-table-column label="平均净买" width="85" sortable :sort-method="(a, b) => (a.total_net / a.count) - (b.total_net / b.count)">
            <template #default="{ row }"><span :class="(row.total_net / row.count) >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.total_net / row.count) }}</span></template>
          </el-table-column>
          <el-table-column prop="dates" label="上榜日期" min-width="150">
            <template #default="{ row }"><div class="dates-cell"><el-tag v-for="d in row.dates" :key="d" size="small" class="date-tag">{{ formatDate(d) }}</el-tag></div></template>
          </el-table-column>
          <el-table-column prop="reasons" label="上榜原因" min-width="150">
            <template #default="{ row }"><el-tooltip :content="[...new Set(row.reasons)].join('; ')" placement="top" :show-after="300"><span class="reason-text">{{ [...new Set(row.reasons)].join('; ') }}<el-tag v-if="[...new Set(row.reasons)].length > 1" type="warning" size="small" effect="plain" style="margin-left:6px">原因变化</el-tag></span></el-tooltip></template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right" class-name="diag-col">
            <template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template>
          </el-table-column>
        </el-table>
        </div>
        <!-- 移动端卡片列表 -->
        <div class="dragon-mobile-list" v-else v-loading="loadingConsecutive">
          <div v-for="(row, idx) in pagedConsecutiveList" :key="row.code + idx" class="m-card dragon-stock-card" @click="goDiag(row.code)">
            <div class="dragon-card-top">
              <div class="dragon-card-rank">{{ idx + 1 }}</div>
              <div class="dragon-card-info">
                <span class="dragon-card-name">{{ row.name }}</span>
                <span class="dragon-card-code">{{ row.code }} · {{ row.count }}次上榜</span>
              </div>
              <div class="dragon-card-price-col">
                <div class="dragon-card-price">¥{{ row.price || '--' }}</div>
                <div class="dragon-card-chg" :class="(row.total_net ?? 0) >= 0 ? 'up' : 'down'">{{ formatMoney(row.total_net) }}</div>
              </div>
            </div>
            <div class="dragon-card-bottom">
              <el-tag v-for="d in row.dates" :key="d" size="small" round class="dragon-date-tag">{{ formatDate(d) }}</el-tag>
            </div>
          </div>
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="consecutivePage"
            :page-size="PAGE_SIZE"
            :total="consecutiveList.length"
            :layout="paginationLayoutFixed"
            background
          />
        </div>
        </template>
      </el-tab-pane>

      <el-tab-pane label="资金流向" name="capitalflow">
        <div class="table-toolbar">
          <span class="toolbar-info">机构vs游资资金对比</span>
        </div>
        <div v-loading="loadingCapital" class="tab-content-fill">
        <el-empty v-if="!loadingCapital && !capitalFlow?.institution"
          description="暂无资金流向数据" :image-size="80" />
        <template v-else>
        <div class="flow-compare flow-compare-inline" v-if="capitalFlow?.institution">
          <div class="cmp-item">
            <span class="cmp-label">机构净买</span>
            <div class="bar-track">
              <div class="bar-fill" :class="capitalFlow.institution.net_buy >= 0 ? 'positive' : 'negative'"
                :style="{ width: instVsHotBar(capitalFlow.institution.net_buy) + '%' }"></div>
            </div>
            <span class="cmp-val" :class="capitalFlow.institution.net_buy >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(capitalFlow.institution.net_buy) }}</span>
            <span class="cmp-tag inst-bg">{{ capitalFlow.institution.count || 0 }}只</span>
          </div>
          <div class="cmp-item">
            <span class="cmp-label">游资净买</span>
            <div class="bar-track">
              <div class="bar-fill" :class="capitalFlow.hot_money.net_buy >= 0 ? 'positive' : 'negative'"
                :style="{ width: instVsHotBar(capitalFlow.hot_money.net_buy) + '%' }"></div>
            </div>
            <span class="cmp-val" :class="capitalFlow.hot_money.net_buy >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(capitalFlow.hot_money.net_buy) }}</span>
            <span class="cmp-tag hot-bg">{{ capitalFlow.hot_money.count || 0 }}只</span>
          </div>
        </div>
        <el-row :gutter="16" class="flow-row flow-row-flex">
          <el-col :xs="24" :sm="12">
            <el-card shadow="hover" class="flow-card">
              <template #header>
                <div class="flow-header">
                  <span class="flow-title"><el-icon><OfficeBuilding /></el-icon> 机构资金</span>
                  <el-tag :type="(capitalFlow.institution?.net_buy || 0) >= 0 ? 'danger' : 'success'" size="small">
                    净买: {{ formatMoney(capitalFlow.institution?.net_buy) }}
                  </el-tag>
                </div>
              </template>
              <div class="flow-stats">
                <span class="fs-item">买 <span class="c-red">{{ formatMoney(capitalFlow.institution?.total_buy) }}</span></span>
                <span class="fs-item">卖 <span class="c-green">{{ formatMoney(capitalFlow.institution?.total_sell) }}</span></span>
                <span class="fs-item">{{ capitalFlow.institution?.count || 0 }}只</span>
              </div>
              <div class="flow-table-wrap">
              <!-- 桌面端表格 -->
              <el-table v-if="!isMobile" :data="capitalFlow.institution?.top_stocks || []" size="small" stripe border height="100%" style="width: 100%">
                <el-table-column prop="code" label="代码" width="68" align="center" />
                <el-table-column prop="name" label="名称" min-width="70" show-overflow-tooltip />
                <el-table-column prop="price" label="最新价" width="72" sortable><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
                <el-table-column prop="buy_amount" label="买入额" width="85"><template #default="{ row }"><span class="c-red">{{ formatMoney(row.buy_amount) }}</span></template></el-table-column>
                <el-table-column prop="sell_amount" label="卖出额" width="85"><template #default="{ row }"><span class="c-green">{{ formatMoney(row.sell_amount) }}</span></template></el-table-column>
                <el-table-column prop="net_amount" label="净买入" width="85"><template #default="{ row }"><span :class="row.net_amount >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
                <el-table-column label="操作" width="80" fixed="right" class-name="diag-col"><template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template></el-table-column>
              </el-table>
              <!-- 移动端卡片 -->
              <div class="dragon-mobile-list dragon-flow-mobile" v-else>
                <div v-for="(row, ri) in (capitalFlow.institution?.top_stocks || [])" :key="'inst-'+row.code+ri" class="m-stock-row" @click="goDiag(row.code)">
                  <div class="info"><span class="sname">{{ row.name }}</span> <span class="scode">{{ row.code }}</span></div>
                  <div class="price-col"><span class="price">¥{{ row.price || '--' }}</span><br><span class="chg" :class="(row.net_amount ?? 0) >= 0 ? 'up' : 'down'">{{ formatMoney(row.net_amount) }}</span></div>
                </div>
              </div>
              </div>
            </el-card>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-card shadow="hover" class="flow-card">
              <template #header>
                <div class="flow-header">
                  <span class="flow-title"><el-icon><User /></el-icon> 游资资金</span>
                  <el-tag :type="(capitalFlow.hot_money?.net_buy || 0) >= 0 ? 'danger' : 'success'" size="small">
                    净买: {{ formatMoney(capitalFlow.hot_money?.net_buy) }}
                  </el-tag>
                </div>
              </template>
              <div class="flow-stats">
                <span class="fs-item">买 <span class="c-red">{{ formatMoney(capitalFlow.hot_money?.total_buy) }}</span></span>
                <span class="fs-item">卖 <span class="c-green">{{ formatMoney(capitalFlow.hot_money?.total_sell) }}</span></span>
                <span class="fs-item">{{ capitalFlow.hot_money?.count || 0 }}只</span>
              </div>
              <div class="flow-table-wrap">
              <!-- 桌面端表格 -->
              <el-table v-if="!isMobile" :data="capitalFlow.hot_money?.top_stocks || []" size="small" stripe border height="100%" style="width: 100%">
                <el-table-column prop="code" label="代码" width="68" align="center" />
                <el-table-column prop="name" label="名称" min-width="70" show-overflow-tooltip />
                <el-table-column prop="price" label="最新价" width="72" sortable><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
                <el-table-column prop="buy_amount" label="买入额" width="85"><template #default="{ row }"><span class="c-red">{{ formatMoney(row.buy_amount) }}</span></template></el-table-column>
                <el-table-column prop="sell_amount" label="卖出额" width="85"><template #default="{ row }"><span class="c-green">{{ formatMoney(row.sell_amount) }}</span></template></el-table-column>
                <el-table-column prop="net_amount" label="净买入" width="85"><template #default="{ row }"><span :class="row.net_amount >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
                <el-table-column label="操作" width="80" fixed="right" class-name="diag-col"><template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template></el-table-column>
              </el-table>
              <!-- 移动端卡片 -->
              <div class="dragon-mobile-list dragon-flow-mobile" v-else>
                <div v-for="(row, ri) in (capitalFlow.hot_money?.top_stocks || [])" :key="'hot-'+row.code+ri" class="m-stock-row" @click="goDiag(row.code)">
                  <div class="info"><span class="sname">{{ row.name }}</span> <span class="scode">{{ row.code }}</span></div>
                  <div class="price-col"><span class="price">¥{{ row.price || '--' }}</span><br><span class="chg" :class="(row.net_amount ?? 0) >= 0 ? 'up' : 'down'">{{ formatMoney(row.net_amount) }}</span></div>
                </div>
              </div>
              </div>
            </el-card>
          </el-col>
        </el-row>
        </template>
        </div>
      </el-tab-pane>

      <el-tab-pane label="席位明细" name="seatdetail">
        <div class="table-toolbar">
          <span class="toolbar-info">龙虎榜机构席位统计（东方财富数据）</span>
        </div>
        <el-empty v-if="!loadingSeat && !seatDetailList.length"
          description="暂无席位明细数据" :image-size="80" />
        <template v-else>
        <!-- 桌面端表格 -->
        <div class="table-section" v-if="!isMobile">
        <el-table :data="pagedSeatDetailList" stripe border v-loading="loadingSeat" height="100%">
          <el-table-column type="index" width="48" label="#" fixed="left" />
          <el-table-column prop="code" label="代码" width="78" fixed="left" />
          <el-table-column prop="name" label="名称" width="88" fixed="left" />
          <el-table-column prop="price" label="最新价" width="88" sortable><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
          <el-table-column prop="change_pct" label="涨跌幅" width="90"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
          <el-table-column label="机构席位" width="85"><template #default="{ row }"><span title="买方/卖方机构数">买{{ row.buy_seat_count || 0 }} / 卖{{ row.sell_seat_count || 0 }}</span></template></el-table-column>
          <el-table-column prop="buy_amount" label="机构买入" width="85"><template #default="{ row }"><span class="c-red">{{ formatMoney(row.buy_amount) }}</span></template></el-table-column>
          <el-table-column prop="sell_amount" label="机构卖出" width="85"><template #default="{ row }"><span class="c-green">{{ formatMoney(row.sell_amount) }}</span></template></el-table-column>
          <el-table-column prop="net_amount" label="净买入" width="85"><template #default="{ row }"><span :class="row.net_amount >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
          <el-table-column prop="reason" label="上榜原因" min-width="150" show-overflow-tooltip />
          <el-table-column label="操作" width="80" fixed="right" class-name="diag-col"><template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template></el-table-column>
        </el-table>
        </div>
        <!-- 移动端卡片列表 -->
        <div class="dragon-mobile-list" v-else v-loading="loadingSeat">
          <div v-for="(row, idx) in pagedSeatDetailList" :key="row.code + idx" class="m-card dragon-stock-card" @click="goDiag(row.code)">
            <div class="dragon-card-top">
              <div class="dragon-card-rank">{{ idx + 1 }}</div>
              <div class="dragon-card-info">
                <span class="dragon-card-name">{{ row.name }}</span>
                <span class="dragon-card-code">{{ row.code }} · 机构买{{ row.buy_seat_count || 0 }}/卖{{ row.sell_seat_count || 0 }}</span>
              </div>
              <div class="dragon-card-price-col">
                <div class="dragon-card-price">¥{{ row.price || '--' }}</div>
                <div class="dragon-card-chg" :class="(row.change_pct ?? 0) >= 0 ? 'up' : 'down'">{{ formatPct(row.change_pct) }}</div>
              </div>
            </div>
            <div class="dragon-card-mid">
              <span class="dragon-flow-item"><span class="flow-label">机构买</span><span class="c-red">{{ formatMoney(row.buy_amount) }}</span></span>
              <span class="dragon-flow-item"><span class="flow-label">机构卖</span><span class="c-green">{{ formatMoney(row.sell_amount) }}</span></span>
              <span class="dragon-flow-item"><span class="flow-label">净买</span><span :class="(row.net_amount || 0) >= 0 ? 'c-red' : 'c-green'" style="font-weight:600">{{ formatMoney(row.net_amount) }}</span></span>
            </div>
            <div class="dragon-card-bottom">
              <span class="dragon-reason" v-if="row.reason">{{ row.reason }}</span>
            </div>
          </div>
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="seatDetailPage"
            :page-size="PAGE_SIZE"
            :total="seatDetailList.length"
            :layout="paginationLayoutFixed"
            background
          />
        </div>
        </template>
      </el-tab-pane>

      <el-tab-pane label="原因分类" name="sector">
        <div class="table-toolbar">
          <span class="toolbar-info">按上榜原因分类统计</span>
        </div>
        <div v-loading="loadingSector" class="tab-content-fill">
        <el-empty v-if="!loadingSector && (!sectorList || !sectorList.length)"
          description="暂无板块归属数据" :image-size="80" />
        <el-row v-else :gutter="16" class="sector-row-scroll">
          <el-col :xs="24" :sm="12" v-for="sector in sectorList" :key="sector.category">
            <el-card shadow="hover" class="sector-card">
              <template #header>
                <div class="sector-header">
                  <span class="sector-title">{{ sector.category }}</span>
                  <el-tag size="small">{{ (sector.top_stocks || []).length }}/{{ sector.count }}只</el-tag>
                </div>
              </template>
              <div class="sector-stats-grid">
                <div class="sector-stat-item">
                  <span class="sector-stat-label">净买入</span>
                  <span :class="sector.net_buy >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(sector.net_buy) }}</span>
                </div>
                <div class="sector-stat-item">
                  <span class="sector-stat-label">平均涨跌</span>
                  <span :class="(sector.avg_change_pct || 0) >= 0 ? 'c-red' : 'c-green'">{{ formatPct(sector.avg_change_pct) }}</span>
                </div>
                <div class="sector-stat-item" v-if="sector.limit_up_count">
                  <span class="sector-stat-label">涨停数</span>
                  <span class="c-red">{{ sector.limit_up_count }}只</span>
                </div>
                <div class="sector-stat-item" v-if="sector.avg_turnover">
                  <span class="sector-stat-label">平均换手</span>
                  <span>{{ sector.avg_turnover.toFixed(2) }}%</span>
                </div>
                <div class="sector-stat-item" v-if="sector.total_amount">
                  <span class="sector-stat-label">龙虎买入</span>
                  <span>{{ formatMoney(sector.total_amount) }}</span>
                </div>
                <div class="sector-stat-item" v-if="sector.total_market_amount">
                  <span class="sector-stat-label">总成交</span>
                  <span>{{ formatMoney(sector.total_market_amount) }}</span>
                </div>
              </div>
              <div class="sector-stocks-scroll">
                <!-- 桌面端表格 -->
                <el-table v-if="!isMobile" :data="sector.top_stocks || []" size="small" stripe border style="width: 100%" max-height="300">
                  <el-table-column prop="code" label="代码" width="76" align="center" />
                  <el-table-column prop="name" label="名称" width="86" show-overflow-tooltip />
                  <el-table-column prop="price" label="最新价" width="82"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
                  <el-table-column prop="change_pct" label="涨跌幅" width="90"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                  <el-table-column prop="net_amount" label="净买入" width="105"><template #default="{ row }"><span :class="row.net_amount >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
                  <el-table-column prop="turnover" label="换手率" width="86"><template #default="{ row }">{{ row.turnover != null ? row.turnover.toFixed(2) + '%' : '--' }}</template></el-table-column>
                  <el-table-column label="操作" width="80" fixed="right" class-name="diag-col"><template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template></el-table-column>
                </el-table>
                <!-- 移动端卡片 -->
                <div class="dragon-mobile-list dragon-flow-mobile" v-else>
                  <div v-for="(row, ri) in (sector.top_stocks || [])" :key="'sec-'+row.code+ri" class="m-stock-row" @click="goDiag(row.code)">
                    <div class="info"><span class="sname">{{ row.name }}</span> <span class="scode">{{ row.code }}</span></div>
                    <div class="price-col"><span class="price">¥{{ row.price || '--' }}</span><br><span class="chg" :class="(row.change_pct ?? 0) >= 0 ? 'up' : 'down'">{{ formatPct(row.change_pct) }}</span></div>
                  </div>
                </div>
              </div>
            </el-card>
          </el-col>
        </el-row>
        </div>
      </el-tab-pane>


      <!-- 选股策略 -->
      <el-tab-pane label="选股策略" name="strategy">
        <div class="table-toolbar">
          <span class="toolbar-info">共 {{ dragonStrategyResults.length }} 只</span>
        </div>
        <div v-loading="loadingDragonStrategy" class="strategy-wrap">
          <el-empty v-if="dragonStrategyResults.length === 0" description="暂无选股策略数据，调整条件后重试" :image-size="80" />
          <template v-else>
            <el-tabs v-model="dragonStrategySubTab" type="card" class="rank-sub-tabs strategy-sub-tabs">
              <el-tab-pane name="institution">
                <template #label><span class="rank-tab-label">机构净买入TOP10</span></template>
                <div class="table-section" v-if="!isMobile">
                  <el-table :data="pagedStrategyList" stripe border height="100%">
                    <el-table-column type="index" width="50" label="#" fixed="left" />
                    <el-table-column prop="code" label="代码" width="80" sortable fixed="left" />
                    <el-table-column prop="name" label="名称" width="100" fixed="left" />
                    <el-table-column prop="price" label="最新价" width="90"><template #default="{ row }"><span class="c-red">¥{{ row.price || '--' }}</span></template></el-table-column>
                    <el-table-column prop="change_pct" label="涨跌幅" width="90" sortable><template #default="{ row }"><span :class="numColorClass(row.change_pct)">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                    <el-table-column prop="net_amount" label="净买入" width="120"><template #default="{ row }"><span :class="(row.net_amount || 0) >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
                    <el-table-column prop="score" label="得分" width="100"><template #default="{ row }"><el-progress :percentage="row.score || 0" :stroke-width="8" :format="scoreFormat" /></template></el-table-column>
                    <el-table-column prop="reasons" label="选股逻辑" min-width="200" show-overflow-tooltip />
                    <el-table-column label="操作" width="80" fixed="right" class-name="diag-col"><template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template></el-table-column>
                  </el-table>
                </div>
                <div class="dragon-mobile-list" v-else>
                  <div v-for="(row, idx) in pagedStrategyList" :key="'str-inst-'+row.code+idx" class="m-card dragon-stock-card" @click="goDiag(row.code)">
                    <div class="dragon-card-top">
                      <div class="dragon-card-rank">{{ idx + 1 }}</div>
                      <div class="dragon-card-info"><span class="dragon-card-name">{{ row.name }}</span><span class="dragon-card-code">{{ row.code }}</span></div>
                      <div class="dragon-card-price-col"><div class="dragon-card-price">¥{{ row.price || '--' }}</div><div class="dragon-card-chg" :class="(row.change_pct ?? 0) >= 0 ? 'up' : 'down'">{{ formatPct(row.change_pct) }}</div></div>
                    </div>
                    <div class="dragon-card-bottom"><span class="dragon-card-net" :class="(row.net_amount || 0) >= 0 ? 'm-text-up' : 'm-text-down'">净买 {{ formatMoney(row.net_amount) }}</span><el-progress :percentage="row.score || 0" :stroke-width="6" :format="scoreFormat" style="width:80px" /></div>
                  </div>
                </div>
                <div class="pagination-bar"><el-pagination v-model:current-page="strategyPage" :page-size="PAGE_SIZE" :total="dragonStrategyResults.length" :layout="paginationLayoutFixed" background /></div>
              </el-tab-pane>
              <el-tab-pane name="synergy">
                <template #label><span class="rank-tab-label">游资合力板</span></template>
                <div class="table-section" v-if="!isMobile">
                  <el-table :data="pagedStrategyList" stripe border height="100%">
                    <el-table-column type="index" width="50" label="#" fixed="left" />
                    <el-table-column prop="code" label="代码" width="80" sortable fixed="left" />
                    <el-table-column prop="name" label="名称" width="100" fixed="left" />
                    <el-table-column prop="price" label="最新价" width="90"><template #default="{ row }"><span class="c-red">¥{{ row.price || '--' }}</span></template></el-table-column>
                    <el-table-column prop="change_pct" label="涨跌幅" width="90" sortable><template #default="{ row }"><span :class="numColorClass(row.change_pct)">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                    <el-table-column prop="net_amount" label="净买入" width="120"><template #default="{ row }"><span :class="(row.net_amount || 0) >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
                    <el-table-column prop="score" label="得分" width="100"><template #default="{ row }"><el-progress :percentage="row.score || 0" :stroke-width="8" :format="scoreFormat" /></template></el-table-column>
                    <el-table-column prop="reasons" label="选股逻辑" min-width="200" show-overflow-tooltip />
                    <el-table-column label="操作" width="80" fixed="right" class-name="diag-col"><template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template></el-table-column>
                  </el-table>
                </div>
                <div class="dragon-mobile-list" v-else>
                  <div v-for="(row, idx) in pagedStrategyList" :key="'str-syn-'+row.code+idx" class="m-card dragon-stock-card" @click="goDiag(row.code)">
                    <div class="dragon-card-top">
                      <div class="dragon-card-rank">{{ idx + 1 }}</div>
                      <div class="dragon-card-info"><span class="dragon-card-name">{{ row.name }}</span><span class="dragon-card-code">{{ row.code }}</span></div>
                      <div class="dragon-card-price-col"><div class="dragon-card-price">¥{{ row.price || '--' }}</div><div class="dragon-card-chg" :class="(row.change_pct ?? 0) >= 0 ? 'up' : 'down'">{{ formatPct(row.change_pct) }}</div></div>
                    </div>
                    <div class="dragon-card-bottom"><span class="dragon-card-net" :class="(row.net_amount || 0) >= 0 ? 'm-text-up' : 'm-text-down'">净买 {{ formatMoney(row.net_amount) }}</span><el-progress :percentage="row.score || 0" :stroke-width="6" :format="scoreFormat" style="width:80px" /></div>
                  </div>
                </div>
                <div class="pagination-bar"><el-pagination v-model:current-page="strategyPage" :page-size="PAGE_SIZE" :total="dragonStrategyResults.length" :layout="paginationLayoutFixed" background /></div>
              </el-tab-pane>
              <el-tab-pane name="resonance">
                <template #label><span class="rank-tab-label">机构+游资共振</span></template>
                <div class="table-section" v-if="!isMobile">
                  <el-table :data="pagedStrategyList" stripe border height="100%">
                    <el-table-column type="index" width="50" label="#" fixed="left" />
                    <el-table-column prop="code" label="代码" width="80" sortable fixed="left" />
                    <el-table-column prop="name" label="名称" width="100" fixed="left" />
                    <el-table-column prop="price" label="最新价" width="90"><template #default="{ row }"><span class="c-red">¥{{ row.price || '--' }}</span></template></el-table-column>
                    <el-table-column prop="change_pct" label="涨跌幅" width="90" sortable><template #default="{ row }"><span :class="numColorClass(row.change_pct)">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                    <el-table-column prop="net_amount" label="净买入" width="120"><template #default="{ row }"><span :class="(row.net_amount || 0) >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
                    <el-table-column prop="score" label="得分" width="100"><template #default="{ row }"><el-progress :percentage="row.score || 0" :stroke-width="8" :format="scoreFormat" /></template></el-table-column>
                    <el-table-column prop="reasons" label="选股逻辑" min-width="200" show-overflow-tooltip />
                    <el-table-column label="操作" width="80" fixed="right" class-name="diag-col"><template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template></el-table-column>
                  </el-table>
                </div>
                <div class="dragon-mobile-list" v-else>
                  <div v-for="(row, idx) in pagedStrategyList" :key="'str-res-'+row.code+idx" class="m-card dragon-stock-card" @click="goDiag(row.code)">
                    <div class="dragon-card-top">
                      <div class="dragon-card-rank">{{ idx + 1 }}</div>
                      <div class="dragon-card-info"><span class="dragon-card-name">{{ row.name }}</span><span class="dragon-card-code">{{ row.code }}</span></div>
                      <div class="dragon-card-price-col"><div class="dragon-card-price">¥{{ row.price || '--' }}</div><div class="dragon-card-chg" :class="(row.change_pct ?? 0) >= 0 ? 'up' : 'down'">{{ formatPct(row.change_pct) }}</div></div>
                    </div>
                    <div class="dragon-card-bottom"><span class="dragon-card-net" :class="(row.net_amount || 0) >= 0 ? 'm-text-up' : 'm-text-down'">净买 {{ formatMoney(row.net_amount) }}</span><el-progress :percentage="row.score || 0" :stroke-width="6" :format="scoreFormat" style="width:80px" /></div>
                  </div>
                </div>
                <div class="pagination-bar"><el-pagination v-model:current-page="strategyPage" :page-size="PAGE_SIZE" :total="dragonStrategyResults.length" :layout="paginationLayoutFixed" background /></div>
              </el-tab-pane>
              <el-tab-pane name="premium">
                <template #label><span class="rank-tab-label">溢价策略</span></template>
                <div class="table-section" v-if="!isMobile">
                  <el-table :data="pagedStrategyList" stripe border height="100%">
                    <el-table-column type="index" width="50" label="#" fixed="left" />
                    <el-table-column prop="code" label="代码" width="80" sortable fixed="left" />
                    <el-table-column prop="name" label="名称" width="100" fixed="left" />
                    <el-table-column prop="price" label="最新价" width="90"><template #default="{ row }"><span class="c-red">¥{{ row.price || '--' }}</span></template></el-table-column>
                    <el-table-column prop="change_pct" label="涨跌幅" width="90" sortable><template #default="{ row }"><span :class="numColorClass(row.change_pct)">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                    <el-table-column prop="net_amount" label="净买入" width="120"><template #default="{ row }"><span :class="(row.net_amount || 0) >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
                    <el-table-column prop="score" label="得分" width="100"><template #default="{ row }"><el-progress :percentage="row.score || 0" :stroke-width="8" :format="scoreFormat" /></template></el-table-column>
                    <el-table-column prop="reasons" label="选股逻辑" min-width="200" show-overflow-tooltip />
                    <el-table-column label="操作" width="80" fixed="right" class-name="diag-col"><template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template></el-table-column>
                  </el-table>
                </div>
                <div class="dragon-mobile-list" v-else>
                  <div v-for="(row, idx) in pagedStrategyList" :key="'str-prem-'+row.code+idx" class="m-card dragon-stock-card" @click="goDiag(row.code)">
                    <div class="dragon-card-top">
                      <div class="dragon-card-rank">{{ idx + 1 }}</div>
                      <div class="dragon-card-info"><span class="dragon-card-name">{{ row.name }}</span><span class="dragon-card-code">{{ row.code }}</span></div>
                      <div class="dragon-card-price-col"><div class="dragon-card-price">¥{{ row.price || '--' }}</div><div class="dragon-card-chg" :class="(row.change_pct ?? 0) >= 0 ? 'up' : 'down'">{{ formatPct(row.change_pct) }}</div></div>
                    </div>
                    <div class="dragon-card-bottom"><span class="dragon-card-net" :class="(row.net_amount || 0) >= 0 ? 'm-text-up' : 'm-text-down'">净买 {{ formatMoney(row.net_amount) }}</span><el-progress :percentage="row.score || 0" :stroke-width="6" :format="scoreFormat" style="width:80px" /></div>
                  </div>
                </div>
                <div class="pagination-bar"><el-pagination v-model:current-page="strategyPage" :page-size="PAGE_SIZE" :total="dragonStrategyResults.length" :layout="paginationLayoutFixed" background /></div>
              </el-tab-pane>
            </el-tabs>
          </template>
        </div>
      </el-tab-pane>

      <!-- 游资追踪tab已移除：龙虎榜原始数据不包含具体游资名称，无法提供真实匹配 -->

      <el-tab-pane label="历史回查" name="history">
        <div class="history-toolbar">
          <el-date-picker v-model="historyDate" type="date" placeholder="选择日期" value-format="YYYY-MM-DD" @change="loadHistory" style="width: 200px;" />
          <span class="toolbar-info" v-if="historyList.length">{{ historyList.length }} 只上榜</span>
        </div>
        <el-empty v-if="!loadingHistory && historyDate && !historyList.length"
          description="该日期无龙虎榜数据（可能为非交易日）" :image-size="80" />
        <el-empty v-else-if="!loadingHistory && !historyDate"
          description="请选择日期查看历史龙虎榜" :image-size="80" />
        <template v-else>
        <!-- 桌面端表格 -->
        <div class="table-section" v-if="!isMobile">
        <el-table :data="pagedHistoryList" stripe border v-loading="loadingHistory" height="100%">
          <el-table-column type="index" width="40" label="#" fixed="left" />
          <el-table-column prop="code" label="代码" width="72" fixed="left" />
          <el-table-column prop="name" label="名称" min-width="80" show-overflow-tooltip fixed="left" />
          <el-table-column prop="price" label="收盘价" width="75"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
          <el-table-column prop="change_pct" label="涨跌幅" width="80"><template #default="{ row }"><span :class="numColorClass(row.change_pct)">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
          <el-table-column prop="buy_amount" label="买入额" width="90"><template #default="{ row }"><span class="c-red">{{ formatMoney(row.buy_amount) }}</span></template></el-table-column>
          <el-table-column prop="sell_amount" label="卖出额" width="90"><template #default="{ row }"><span class="c-green">{{ formatMoney(row.sell_amount) }}</span></template></el-table-column>
          <el-table-column prop="net_amount" label="净买入" width="90"><template #default="{ row }"><span :class="(row.net_amount || 0) >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
          <el-table-column prop="direction" label="资金方向" width="70"><template #default="{ row }"><el-tag :type="row.direction === '净买入' ? 'danger' : row.direction === '净卖出' ? 'success' : 'info'" size="small">{{ row.direction || '--' }}</el-tag></template></el-table-column>
          <el-table-column prop="reason" label="上榜原因" min-width="150" show-overflow-tooltip />
          <el-table-column label="操作" width="80" fixed="right" class-name="diag-col"><template #default="{ row }"><el-button type="primary" link size="small" @click="goDiag(row.code)">诊断</el-button></template></el-table-column>
        </el-table>
        </div>
        <!-- 移动端卡片列表 -->
        <div class="dragon-mobile-list" v-else v-loading="loadingHistory">
          <div v-for="(row, idx) in pagedHistoryList" :key="row.code + idx" class="m-card dragon-stock-card" @click="goDiag(row.code)">
            <div class="dragon-card-top">
              <div class="dragon-card-rank">{{ idx + 1 }}</div>
              <div class="dragon-card-info"><span class="dragon-card-name">{{ row.name }}</span><span class="dragon-card-code">{{ row.code }}</span></div>
              <div class="dragon-card-price-col"><div class="dragon-card-price">¥{{ row.price || '--' }}</div><div class="dragon-card-chg" :class="(row.change_pct ?? 0) >= 0 ? 'up' : 'down'">{{ formatPct(row.change_pct) }}</div></div>
            </div>
            <div class="dragon-card-mid">
              <span class="dragon-flow-item"><span class="flow-label">买入</span><span class="c-red">{{ formatMoney(row.buy_amount) }}</span></span>
              <span class="dragon-flow-item"><span class="flow-label">卖出</span><span class="c-green">{{ formatMoney(row.sell_amount) }}</span></span>
              <span class="dragon-flow-item"><span class="flow-label">净买</span><span :class="(row.net_amount || 0) >= 0 ? 'c-red' : 'c-green'" style="font-weight:600">{{ formatMoney(row.net_amount) }}</span></span>
            </div>
            <div class="dragon-card-bottom">
              <el-tag v-if="row.direction" :type="row.direction === '净买入' ? 'danger' : 'success'" size="small" round>{{ row.direction }}</el-tag>
              <span class="dragon-reason" v-if="row.reason">{{ row.reason }}</span>
            </div>
          </div>
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="historyPage"
            :page-size="PAGE_SIZE"
            :total="historyList.length"
            :layout="paginationLayoutFixed"
            background
          />
        </div>
        </template>
      </el-tab-pane>

    </el-tabs>

    <!-- 诊断抽屉 -->
    <StockDiagnosisDrawer
      v-model="diagDrawerVisible"
      :stock-code="diagStockCode"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onActivated, onBeforeUnmount, nextTick } from 'vue'
import { TrendCharts, Refresh, OfficeBuilding, User } from '@element-plus/icons-vue'
import { strategyApi } from '@/api'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'
import { ElMessage } from 'element-plus'
import StockDiagnosisDrawer from './components/StockDiagnosisDrawer.vue'
import RefreshingIndicator from '@/components/RefreshingIndicator.vue'

defineOptions({ name: 'DragonList' })
const activeTab = ref('today')
const isMobile = ref(window.innerWidth < 768)
const onResize = () => { isMobile.value = window.innerWidth < 768 }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))
const paginationLayout = computed(() => isMobile.value ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper')
// 固定 PAGE_SIZE 的 tab 使用此 layout（不含 sizes，避免 Element Plus assertValidUsage 校验失败导致分页不渲染）
const paginationLayoutFixed = computed(() => isMobile.value ? 'prev, pager, next' : 'total, prev, pager, next, jumper')
const tableHeight = computed(() => isMobile.value ? 350 : 600)
const historyDate = ref('')
const consecutiveDays = ref(5)

// 清掉旧格式缓存（在 useCachedFetch 创建之前执行，确保不会读到旧数据）
;['dragon:today', 'dragon:capital-flow',
  'dragon:seat-detail', 'dragon:sector-analysis', 'dragon:next-day',
].forEach(k => { try { localStorage.removeItem('gp_cache_v1:' + k) } catch {} })

// 各 tab 独立缓存（immediate=false，由 onMounted/onActivated/tab 切换统一调度）
const dragonToday = useCachedFetch({
  key: 'dragon:today:v6',
  fetcher: ({ signal, force } = {}) => strategyApi.getDragonToday(force ?? false, signal),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: parseTodayResponse,
  immediate: false,
})

// 游资追踪tab已移除：无真实席位匹配数据，不再请求
// const hotMoney = useCachedFetch({...})

const capitalFlowRaw = useCachedFetch({
  key: 'dragon:capital-flow',
  fetcher: ({ signal, force } = {}) => strategyApi.getDragonCapitalFlow(force ?? false, signal),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: (res) => {
    if (!res) return {}
    // 后端已返回完整结构（institution/hot_money），直接使用真实数据
    if (res?.flow_data?.institution || res?.institution) return res.flow_data || res
    // 若后端字段缺失，返回空结构（不估算）
    return {
      date: res.date,
      total_net_buy: res.total_net_buy ?? 0,
      stock_count: res.stock_count ?? 0,
      institution: { net_buy: 0, total_buy: 0, total_sell: 0, count: 0, top_stocks: [] },
      hot_money: { net_buy: 0, total_buy: 0, total_sell: 0, count: 0, top_stocks: [] },
      data_date: res.data_date,
      update_time: res.update_time,
    }
  },
  immediate: false,
})

const seatDetail = useCachedFetch({
  key: 'dragon:seat-detail',
  fetcher: ({ signal, force } = {}) => strategyApi.getDragonSeatDetail(force ?? false, signal),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: (res) => withMeta(res?.seats || [], res),
  immediate: false,
})

const sectorAnalysis = useCachedFetch({
  key: 'dragon:sector-analysis',
  fetcher: ({ signal, force } = {}) => strategyApi.getDragonSectorAnalysis(force ?? false, signal),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: (res) => withMeta(
    res?.sectors?.length ? res.sectors.map(s => ({ category: s.name || s.category, count: s.count ?? 1, net_buy: s.net_amount ?? s.net_buy ?? 0, top_stocks: s.top_stocks || [] })) : (res?.sectors || []),
    res
  ),
  immediate: false,
})

const consecutive = useCachedFetch({
  key: () => `dragon:consecutive:${consecutiveDays.value}`,
  fetcher: ({ signal }) => strategyApi.getDragonConsecutive(consecutiveDays.value, signal),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: (res) => {
    const raw = res?.consecutive || res?.consecutive_stocks || []
    if (!raw.length) return withMeta([], res)
    // 后端已按股票聚合好，直接使用（兼容旧格式：如果 item.dates 不存在则说明是原始记录）
    if (raw[0]?.dates) {
      return withMeta(raw, res)
    }
    const map = {}
    for (const item of raw) {
      const key = item.code
      if (!map[key]) map[key] = { code: item.code, name: item.name, price: item.price ?? null, count: 0, total_net: 0, dates: [], reasons: [] }
      map[key].count++
      map[key].total_net += (item.net_amount || 0)
      if (item.date) map[key].dates.push(item.date)
      if (item.reason) map[key].reasons.push(item.reason)
    }
    return withMeta(Object.values(map).sort((a, b) => b.count - a.count), res)
  },
  immediate: false,
})

const nextDay = useCachedFetch({
  key: 'dragon:next-day',
  fetcher: ({ signal, force } = {}) => strategyApi.getDragonNextDayPerformance(force ?? false, signal),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: (res) => {
    const list = res?.performance || res?.next_day_list || []
    const stats = res?.statistics || res?.stats || {}
    // 空数据不覆盖已有缓存
    if (list.length === 0 && nextDay.data.value?.list?.length) return null
    return { list, stats, data_date: res?.data_date, update_time: res?.update_time }
  },
  immediate: false,
})

const history = useCachedFetch({
  key: () => `dragon:history:${historyDate.value || 'none'}`,
  fetcher: ({ signal }) => strategyApi.getDragonHistory(historyDate.value, signal),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: (res) => withMeta(res?.history_list || res?.stocks || parseDragonOutput(extractText(res)), res),
  immediate: false,
})

const dragonStrategyType = ref('institution')
const dragonStrategySubTab = ref('institution')
const dragonStrategyCache = useCachedFetch({
  key: () => `dragon:strategy:${dragonStrategyType.value}`,
  fetcher: ({ signal, force } = {}) => strategyApi.getDragonStrategy(dragonStrategyType.value, force ?? false, 15, {}, signal),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: (res) => {
    const stocks = res?.stocks || []
    return withMeta(stocks.map(s => ({ ...s, score: s.score ?? Math.round(Math.max(0, Math.min(100, (s.net_amount || 0) / 1e6 * 50 + 50))), reasons: s.reasons ?? s.reason ?? '' })), res)
  },
  immediate: false,
})

function loadDragonStrategy() {
  dragonStrategyCache.refresh()
}

watch(dragonStrategySubTab, (v) => { dragonStrategyType.value = v; loadDragonStrategy() })

// tab → cache 映射（游资追踪tab已移除）
const cacheMap = {
  today: dragonToday,
  capitalflow: capitalFlowRaw,
  seatdetail: seatDetail,
  sector: sectorAnalysis,
  consecutive,
  nextday: nextDay,
  strategy: dragonStrategyCache,
  history,
}



// 派生数据 - 直接绑定到模板
const todayList = computed(() => dragonToday.data.value?.todayList || [])

// 今日汇总统计卡片数据（后端已返回原始金额/元）
const todaySummary = computed(() => {
  const raw = dragonToday.data.value?.summary || {}
  return {
    total_net: raw.total_net ?? 0,
    inst_buy_count: raw.inst_buy_count ?? 0,
    inst_sell_count: raw.inst_sell_count ?? 0,
    total_amount: raw.total_amount ?? 0,
  }
})
const capitalFlowData = computed(() => capitalFlowRaw.data.value || null)
// 资金流向（直接暴露对象给模板，避免嵌套 ?. 链）
const capitalFlow = computed(() => capitalFlowData.value || {})
const seatDetailList = computed(() => seatDetail.data.value || [])
const sectorList = computed(() => {
  const list = sectorAnalysis.data.value || []
  if (!list.length) return list
  // "其他" 放到最后
  return [...list].sort((a, b) => {
    const aOther = a.category === '其他' ? 1 : 0
    const bOther = b.category === '其他' ? 1 : 0
    return aOther - bOther
  })
})
const consecutiveList = computed(() => consecutive.data.value || [])
const nextDayList = computed(() => nextDay.data.value?.performance || nextDay.data.value?.list || [])
const nextDayStats = computed(() => nextDay.data.value?.statistics || nextDay.data.value?.stats || {})
const historyList = computed(() => history.data.value || [])
const dragonStrategyResults = computed(() => dragonStrategyCache.data.value || [])

// 加载状态 - 透传（包含 refreshing，tab 切换后台刷新时也显示 loading）
const loading = computed(() => dragonToday.loading.value || dragonToday.refreshing.value)
const loadingCapital = computed(() => capitalFlowRaw.loading.value || capitalFlowRaw.refreshing.value)
const loadingSeat = computed(() => seatDetail.loading.value || seatDetail.refreshing.value)
const loadingSector = computed(() => sectorAnalysis.loading.value || sectorAnalysis.refreshing.value)
const loadingConsecutive = computed(() => consecutive.loading.value || consecutive.refreshing.value)
const loadingNextDay = computed(() => nextDay.loading.value || nextDay.refreshing.value)
const loadingHistory = computed(() => history.loading.value || history.refreshing.value)
const loadingDragonStrategy = computed(() => dragonStrategyCache.loading.value || dragonStrategyCache.refreshing.value)

// ── 分页配置（今日龙虎榜）──────────────────────────────
const todayPage = ref(1)
const todayPageSize = ref(20)
const todayPageSizeOptions = [10, 20, 50, 100]

// 分页后的数据
const paginatedTodayList = computed(() => {
  const list = todayList.value || []
  const start = (todayPage.value - 1) * todayPageSize.value
  const end = start + todayPageSize.value
  return list.slice(start, end)
})

// 重置分页到第1页（数据变化时）
watch(todayList, () => { todayPage.value = 1 })

// ── 分页配置（次日表现/连续上榜/席位明细/历史回查/选股策略）──
const PAGE_SIZE = 20
const nextDayPage = ref(1)
const consecutivePage = ref(1)
const seatDetailPage = ref(1)
const historyPage = ref(1)
const strategyPage = ref(1)

const pagedNextDayList = computed(() => {
  const list = nextDayList.value || []
  const start = (nextDayPage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})
const pagedConsecutiveList = computed(() => {
  const list = consecutiveList.value || []
  const start = (consecutivePage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})
const pagedSeatDetailList = computed(() => {
  const list = seatDetailList.value || []
  const start = (seatDetailPage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})
const pagedHistoryList = computed(() => {
  const list = historyList.value || []
  const start = (historyPage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})
const pagedStrategyList = computed(() => {
  const list = dragonStrategyResults.value || []
  const start = (strategyPage.value - 1) * PAGE_SIZE
  return list.slice(start, start + PAGE_SIZE)
})

watch(nextDayList, () => { nextDayPage.value = 1 })
watch(consecutiveList, () => { consecutivePage.value = 1 })
watch(seatDetailList, () => { seatDetailPage.value = 1 })
watch(historyList, () => { historyPage.value = 1 })
watch(dragonStrategyResults, () => { strategyPage.value = 1 })

// 游资追踪tab已移除，不再需要refreshingHot
const refreshingCapital = computed(() => capitalFlowRaw.refreshing.value)
const refreshingSeat = computed(() => seatDetail.refreshing.value)
const refreshingSector = computed(() => sectorAnalysis.refreshing.value)
const refreshingConsecutive = computed(() => consecutive.refreshing.value)
const refreshingStrategy = computed(() => dragonStrategyCache.refreshing.value)
const refreshingHistory = computed(() => history.refreshing.value)
const refreshingNextDay = computed(() => nextDay.refreshing.value)

// 全局刷新状态：任何子缓存正在拉取都视为"后台刷新中"
const anyRefreshing = computed(() => {
  return [dragonToday.refreshing.value, refreshingCapital.value, refreshingSeat.value,
          refreshingSector.value, refreshingConsecutive.value, refreshingNextDay.value, refreshingStrategy.value, refreshingHistory.value]
    .some(Boolean)
})

// 手动刷新当前 tab：让 useCachedFetch 走 force=true 重新拉取
const refreshingAll = ref(false)
async function refreshActiveTab() {
  refreshingAll.value = true
  try {
    switch (activeTab.value) {
      case 'today': await dragonToday.refresh(); break
      case 'capitalflow': await capitalFlowRaw.refresh(); break
      case 'seatdetail': await seatDetail.refresh(); break
      case 'sector': await sectorAnalysis.refresh(); break
      case 'consecutive': await consecutive.refresh(); break
      case 'nextday': await nextDay.refresh(); break
      case 'strategy': await dragonStrategyCache.refresh(); break
      case 'history': if (historyDate.value) await history.refresh(); break
    }
    ElMessage.success('已刷新最新数据')
  } catch (e) {
    ElMessage.error(`刷新失败: ${e?.message || e}`)
  } finally {
    refreshingAll.value = false
  }
}

// ── 工具函数 ───────────────────────────────────────
function extractText(response) {
  if (!response) return ''
  if (response.raw_output) return response.raw_output
  if (typeof response === 'string') return response
  return ''
}

function parseNum(val) {
  if (val == null || val === '') return 0
  const s = String(val).replace(/[+%]/g, '')
  const n = parseFloat(s)
  return isNaN(n) ? 0 : n
}

function formatPct(val) {
  const n = parseNum(val)
  if (n === 0 && String(val).trim() === '') return '--'
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`
}

function numColorClass(val) {
  return parseNum(val) >= 0 ? 'c-red' : 'c-green'
}

// ── 解析函数 ───────────────────────────────────────
function parseDragonOutput(raw) {
  if (!raw) return []
  const lines = raw.split('\n')
  const result = []
  for (const line of lines) {
    const m = line.match(/^(\d{6})\s+(.+?)\s+([\d.]+)\s+([+-][\d.]+)%?\s+([\d.]+)%?\s*(.*)$/)
    if (!m) continue
    const [, code, name, price, changePct, amplitude, rest] = m
    const parts = rest.trim().split(/\s{2,}/)
    result.push({
      code,
      name: name.trim(),
      price: parseFloat(price),
      change_pct: parseNum(changePct),
      amplitude: parseFloat(amplitude),
      reason: parts[0]?.trim() || '',
      direction: parts[1]?.trim() || '',
    })
  }
  return result
}

function parseRankSection(text) {
  if (!text) return []
  const result = []
  for (const line of text.split('\n')) {
    const m = line.match(/^\s*\d+\.\s*(.+?)\((\d{6})\)\s*([+-]?\d+\.?\d*)%\s*(.*)/)
    if (m) {
      result.push({ name: m[1].trim(), code: m[2], change_pct: parseFloat(m[3]), reason: m[4].trim() })
    }
  }
  return result
}

// 把后端响应标准化为 { todayList, gainers, losers, limit_up, limit_down }
function parseTodayResponse(res) {
  if (!res) return { todayList: [], gainers: [], losers: [], limit_up: 0, limit_down: 0 }
  // 兼容后端字段：today_list (旧格式) / stocks (新格式)
  const todayList = res.today_list || res.stocks || parseDragonOutput(extractText(res))
  let gainers = res.gainers || []
  if (!gainers.length) {
    const text = extractText(res)
    const m = text.match(/涨幅榜\s*TOP\d+[\s\S]*?\n([\s\S]*?)(?=\n\s*跌幅榜|$)/i)
    gainers = parseRankSection(m ? m[1] : '')
  }
  let losers = res.losers || []
  if (!losers.length) {
    const text = extractText(res)
    const m = text.match(/跌幅榜\s*TOP\d+[\s\S]*?\n([\s\S]*?)(?=\n={3,}|$)/i)
    losers = parseRankSection(m ? m[1] : '')
  }
  return { todayList, gainers, losers, limit_up: res.limit_up ?? 0, limit_down: res.limit_down ?? 0, summary: res.summary || {}, data_date: res.data_date, dragon_data_date: res.dragon_data_date, update_time: res.update_time }
}

// 辅助：为数组结果附加元数据（不改变数组本身，通过 __meta 属性）
function withMeta(arr, res) {
  if (!Array.isArray(arr)) return arr
  const meta = { data_date: res?.data_date, update_time: res?.update_time }
  Object.defineProperty(arr, '__meta', { value: meta, enumerable: false, configurable: true, writable: true })
  return arr
}

// 诊断抽屉
const diagDrawerVisible = ref(false)
const diagStockCode = ref('')
function goDiag(code) {
  diagStockCode.value = code
  diagDrawerVisible.value = true
}

// 资金流向对比条宽度：取两值绝对值的最大值做基准，等比缩放
function instVsHotBar(val) {
  const a = Math.abs(Number(val) || 0)
  const base = Math.max(a, 1)  // 避免除零
  // 实际宽度比例：取绝对值映射到 [10, 100] 区间（保证负值也可见）
  // 使用机构和游资两值中的最大绝对值作为 100% 基准
  const inst = Math.abs(Number(capitalFlow.value?.institution?.net_buy) || 0)
  const hot = Math.abs(Number(capitalFlow.value?.hot_money?.net_buy) || 0)
  const max = Math.max(inst, hot, 1)
  return Math.max(8, Math.min(100, (a / max) * 100))
}

// 格式化数据更新时间
function formatUpdateTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// 当前 tab 数据最后更新时间 + 实际数据日期
const dragonTabs = ['today', 'nextday', 'consecutive', 'seatdetail', 'capitalflow', 'sector'] // 基于龙虎榜数据的tab

// 移动端胶囊导航列表
const dragonTabList = computed(() => [
  { name: 'today', label: '龙虎榜', icon: '📊', badge: todayList.value.length || undefined },
  { name: 'nextday', label: '次日表现', icon: '📈' },
  { name: 'consecutive', label: '连续上榜', icon: '🔁' },
  { name: 'capitalflow', label: '资金流向', icon: '💰' },
  { name: 'seatdetail', label: '席位明细', icon: '🏢' },
  { name: 'sector', label: '原因分类', icon: '📂' },
  { name: 'strategy', label: '选股策略', icon: '🎯' },
  { name: 'history', label: '历史回查', icon: '📅' },
])

const lastUpdateText = computed(() => {
  const map = {
    today: dragonToday.lastUpdate.value,
    capitalflow: capitalFlowRaw.lastUpdate.value,
    seatdetail: seatDetail.lastUpdate.value,
    sector: sectorAnalysis.lastUpdate.value,
    consecutive: consecutive.lastUpdate.value,
    nextday: nextDay.lastUpdate.value,
    strategy: dragonStrategyCache.lastUpdate.value,
    history: history.lastUpdate.value,
  }
  const ts = map[activeTab.value] || 0
  const timeStr = ts ? formatUpdateTime(ts) : '加载中...'

  // 从后端响应获取实际数据日期
  const todayData = dragonToday.data.value || {}
  const dragonDataDate = todayData.dragon_data_date || todayData.data_date
  const isDragonDelayed = todayData.dragon_data_date && todayData.data_date && todayData.dragon_data_date !== todayData.data_date

  // 各tab的数据日期
  const dataMap = {
    today: dragonDataDate,
    capitalflow: capitalFlowRaw.data.value?.date || capitalFlowRaw.data.value?.data_date || dragonDataDate,
    seatdetail: (seatDetail.data.value?.__meta || {})?.data_date || (seatDetail.data.value || {}).date || dragonDataDate,
    sector: (sectorAnalysis.data.value?.__meta || {})?.data_date || dragonDataDate,
    consecutive: (consecutive.data.value?.__meta || {})?.data_date || dragonDataDate,
    nextday: nextDay.data.value?.data_date || nextDay.data.value?.date || dragonDataDate,
    strategy: (dragonStrategyCache.data.value?.__meta || {})?.data_date || dragonDataDate,
    history: (history.data.value?.__meta || {})?.data_date,
  }
  const dataDate = dataMap[activeTab.value]

  if (dataDate) {
    const showDelayed = dragonTabs.includes(activeTab.value) && isDragonDelayed
    return `数据日期 ${dataDate}${showDelayed ? ' (龙虎榜为上一交易日)' : ''} | 更新于 ${timeStr}`
  }
  return `更新于 ${timeStr}`
})

function formatMoney(val) {
  if (val == null) return '--'
  const n = parseFloat(val)
  if (isNaN(n)) return '--'
  if (Math.abs(n) >= 100000000) return `${(n / 100000000).toFixed(2)}亿`
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(2)}万`
  return n.toFixed(2)
}

function formatDate(dateStr) {
  if (!dateStr || typeof dateStr !== 'string' || dateStr.length < 6) return dateStr
  const year = dateStr.slice(0, 4)
  const month = dateStr.slice(4, 6)
  const day = dateStr.slice(6, 8)
  if (month && day) {
    return `${year}-${month}-${day}`
  } else if (month) {
    return `${year}-${month}`
  }
  return dateStr
}

function loadHistory() {
  if (historyDate.value) history.refresh()
}

function loadConsecutive() {
  // key 已包含 consecutiveDays，handleKeyChange 会在 key 变化时自动 silentRefresh
}

function scoreFormat(val) {
  return val == null ? '--' : `${val}%`
}

// 页面初始化 - 加载当前tab数据（懒加载，其余在tab切换时按需加载）
onMounted(() => {
  // 走 silentRefresh 让后端 SWR 缓存命中（~20ms），避免 force=true 触发 8s 冷重建
  dragonToday.silentRefresh().catch(() => {})
})

// keep-alive 切回：确保数据加载
onActivated(() => {
  const current = cacheMap[activeTab.value]
  if (current) {
    const d = current.data.value
    let noData = false
    if (!d) {
      noData = true
    } else if (Array.isArray(d)) {
      noData = d.length === 0
    } else if (typeof d === 'object') {
      const arr = d.todayList || d.list || d.stocks || d.performance || []
      noData = Array.isArray(arr) && arr.length === 0
    }
    const stale = Date.now() - current.lastUpdate.value > 5 * 60 * 1000
    if (noData || stale) {
      current.silentRefresh().catch(() => {})
    }
  }
})

// 监听标签页切换 - 加载对应tab数据（nextTick 避免与 el-tabs DOM 更新冲突）
watch(activeTab, (newTab) => {
  nextTick(() => {
    const cache = cacheMap[newTab]
    if (cache) {
      const d = cache.data.value
      let noData = !d || (Array.isArray(d) && d.length === 0)
      // 对象类型检查：覆盖 dragonToday 返回的 todayList/gainers/losers 及其他 tab 字段
      if (!noData && typeof d === 'object') {
        const arr = d.todayList || d.list || d.stocks || d.performance || []
        noData = Array.isArray(arr) && arr.length === 0
      }
      cache.silentRefresh().catch(() => {})
    }
  })
})
</script>

<style scoped>
/* 页面填满 app-main，整页不滚动 */
.dragon-page {
  position: absolute; top: 0; left: 0; right: 0; bottom: 0;
  display: flex; flex-direction: column; overflow: hidden; padding: 12px;
}
.rank-sub-tabs { margin-top: 4px; }
.rank-sub-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
/* 选股策略外层占满 flex 空间 */
.strategy-wrap { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.strategy-wrap > .el-empty { flex: 1; }
.strategy-sub-tabs { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.strategy-sub-tabs :deep(.el-tabs__content) { flex: 1; min-height: 0; }
.strategy-sub-tabs :deep(.el-tabs__content > .el-tab-pane) {
  display: flex !important; flex-direction: column; height: 100%; min-height: 0;
}
.strategy-sub-tabs :deep(.el-tabs__content > .el-tab-pane[style*="display: none"]) {
  display: none !important;
}
.rank-tab-label { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; font-weight: 500; }
/* 移动端胶囊导航：桌面端隐藏 */
.mobile-tab-nav { display: none !important; }
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
.page-title { display: flex; align-items: center; gap: 8px; color: #303133; font-size: 20px; margin: 0; }
.header-right { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.update-time { color: #909399; font-size: 13px; }

/* ========== 移动端 Header：方案A渐变卡片风格 ========== */
.m-page-header {
  display: none;
}
.m-header-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 10px;
  background: linear-gradient(135deg, rgba(91,124,250,0.08), rgba(91,124,250,0.02));
  border-radius: 10px;
}
.m-header-left {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 1;
  min-width: 0;
}
.m-header-icon {
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(91,124,250,0.15);
  border-radius: 50%;
  font-size: 11px;
  flex-shrink: 0;
}
.m-header-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.m-header-title {
  font-size: 13px;
  font-weight: 600;
  color: #1a2332;
  line-height: 1.2;
}
.m-header-time {
  font-size: 9px;
  color: #5b7cfa;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.1;
}
.m-header-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.m-refresh-btn {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
}
.m-refresh-btn:active {
  transform: scale(0.9);
  background: rgba(91,124,250,0.1);
  border-color: #5b7cfa;
}
.m-refresh-btn .el-icon {
  font-size: 12px;
  color: #606266;
}
.m-refresh-spin {
  animation: m-spin 1s linear infinite;
  color: #5b7cfa !important;
}
@keyframes m-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 今日汇总卡 */
.summary-row { margin-bottom: 8px; flex-shrink: 0; display: flex !important; flex-wrap: nowrap !important; gap: 0; }
.summary-row :deep(.el-col) { flex: 1 1 0; min-width: 0; }
.summary-card { background: linear-gradient(135deg, #fafbfc, #f5f7fa); border-radius: 6px; padding: 8px 10px; text-align: center; border: 1px solid #ebeef5; }
.summary-num { font-size: 17px; font-weight: 700; line-height: 1.2; }
.summary-label { font-size: 11px; color: #909399; margin-top: 2px; }

/* 资金流向对比条（一行紧凑布局） */
.flow-compare-inline {
  display: flex; align-items: center; gap: 16px;
  background: #f5f7fa; border-radius: 6px;
  padding: 6px 12px; margin-bottom: 8px;
  flex-shrink: 0;
}
.cmp-item { display: flex; align-items: center; gap: 6px; flex: 1; min-width: 0; }
.cmp-label { font-size: 12px; color: #909399; white-space: nowrap; font-weight: 600; }
.cmp-item .bar-track { flex: 1; height: 6px; background: #ebeef5; border-radius: 3px; overflow: hidden; min-width: 40px; }
.bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s ease; }
.bar-fill.positive { background: linear-gradient(90deg, #f56c6c, #e6a23c); }
.bar-fill.negative { background: linear-gradient(90deg, #67c23a, #85ce61); }
.cmp-val { font-size: 12px; font-weight: 600; text-align: right; white-space: nowrap; }
.cmp-tag { font-size: 11px; padding: 1px 6px; border-radius: 8px; white-space: nowrap; }
.cmp-tag.inst-bg { background: rgba(245, 108, 108, 0.1); color: #f56c6c; }
.cmp-tag.hot-bg { background: rgba(64, 158, 255, 0.1); color: #409eff; }

/* 颜色 */
.c-red { color: #f56c6c !important; font-weight: 600; }
.c-green { color: #67c23a !important; font-weight: 600; }
.c-gray { color: #909399 !important; }
.change-big { font-size: 15px; }

/* 工具栏 */
.table-toolbar, .history-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; flex-shrink: 0; flex-wrap: wrap; gap: 6px; }
.toolbar-info { color: #909399; font-size: 13px; }
.toolbar-left { display: flex; align-items: center; }

/* 资金流向 */
.flow-row-flex { flex: 1 1 0 !important; min-height: 0; overflow: hidden; align-items: stretch; }
.flow-row-flex > .el-col { display: flex !important; flex-direction: column; min-height: 0; height: 100%; }
.flow-card { margin-bottom: 0; min-width: 0; flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; height: 100%; }
.flow-card :deep(.el-card__body) { flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; padding: 8px 12px; overflow: hidden; }
.flow-header { display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
.flow-title { font-weight: 600; font-size: 14px; display: flex; align-items: center; gap: 4px; }
.flow-stats { display: flex; gap: 12px; margin-bottom: 6px; padding: 4px 8px; background: #f5f7fa; border-radius: 4px; flex-shrink: 0; font-size: 12px; }
.fs-item { white-space: nowrap; }
.fs-item span { font-weight: 600; }
.flow-table-wrap { flex: 1 1 0; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
.flow-table-wrap :deep(.el-table) { flex: 1 1 0; min-height: 0; }

/* 席位明细 */
.seat-item { display: flex; justify-content: space-between; padding: 2px 0; font-size: 12px; }
.seat-name { color: #606266; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.text-muted { color: #c0c4cc; }

/* 板块分析 */
.sector-row-scroll { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; }
.sector-row-scroll::-webkit-scrollbar { width: 6px; }
.sector-row-scroll::-webkit-scrollbar-track { background: #f0f2f5; }
.sector-row-scroll::-webkit-scrollbar-thumb { background: #c0c4cc; border-radius: 3px; }
.sector-card { margin-bottom: 8px; }
.sector-header { display: flex; align-items: center; justify-content: space-between; }
.sector-title { font-weight: 600; font-size: 14px; }
.sector-stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; margin-bottom: 6px; padding: 4px 8px; background: #f5f7fa; border-radius: 4px; }
.sector-stat-item { display: flex; flex-direction: column; align-items: center; text-align: center; }
.sector-stat-label { font-size: 11px; color: #909399; margin-bottom: 2px; }
.sector-stat-item > span:last-child { font-size: 12px; font-weight: 600; }

/* 原因分类表格滚动容器：默认 10 行（10×32=320），超出滚动 */
.sector-stocks-scroll {
  max-height: 240px;
  overflow-y: auto;
  overflow-x: auto;
}
.sector-stocks-scroll::-webkit-scrollbar { width: 6px; height: 6px; }
.sector-stocks-scroll::-webkit-scrollbar-track { background: #f0f2f5; }
.sector-stocks-scroll::-webkit-scrollbar-thumb { background: #c0c4cc; border-radius: 3px; }
.sector-stocks-scroll::-webkit-scrollbar-thumb:hover { background: #909399; }

/* 连续上榜 */
.date-tag { margin: 2px; }
.reason-text {
  display: inline-block;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

/* 次日表现 */
.stats-row { margin-bottom: 8px; flex-shrink: 0; }
.stat-card { text-align: center; }
.stat-card :deep(.el-card__body) { padding: 8px 6px; }
.stat-number { font-size: 18px; font-weight: 700; }
.stat-desc { font-size: 11px; color: #909399; margin-top: 2px; }

/* ========== Tabs 增强 ========== */
:deep(.el-tabs--border-card) {
  border-radius: 6px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
  flex: 1; min-height: 0;
  display: flex; flex-direction: column;
}
:deep(.el-tabs--border-card > .el-tabs__header) {
  background-color: #fafafa;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
}
:deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item) {
  font-weight: 500;
  transition: all 0.2s;
}
:deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item.is-active) {
  color: #409eff;
  font-weight: 600;
  background-color: #fff;
}
:deep(.el-tabs--border-card > .el-tabs__content) {
  padding: 12px;
  flex: 1; min-height: 0;
  display: flex !important;
  flex-direction: column !important;
}
/* 激活的 tab-pane 占满 flex 空间，flex column 布局 */
:deep(.el-tabs__content > .el-tab-pane) {
  display: flex !important;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
:deep(.el-tabs__content > .el-tab-pane[style*="display: none"]) {
  display: none !important;
}

/* ========== 表格统一 ========== */
:deep(.el-table) {
  font-size: 13px;
  border-radius: 4px;
}
:deep(.el-table .cell) {
  padding-left: 8px;
  padding-right: 8px;
}
:deep(.el-table th.el-table__cell) {
  background-color: #fafbfc !important;
  font-weight: 600;
  color: #303133;
  padding: 10px 0;
  white-space: nowrap;
}
:deep(.el-table td.el-table__cell) {
  padding: 10px 0;
}
:deep(.el-table .el-table__row) {
  transition: background-color 0.2s;
}
:deep(.el-table .el-table__row:hover > td) {
  background-color: #f0f7ff !important;
}
/* 子表格（卡片内）也禁止换行 */
:deep(.el-card .el-table .cell) {
  white-space: nowrap;
}
:deep(.el-card .el-table th.el-table__cell .cell) {
  white-space: nowrap;
}
/* dragon-table 表头 */
/* 操作列统一窄宽度 */
.diag-col { width: 30px !important; min-width: 30px !important; max-width: 30px !important; }
.diag-col :deep(.el-button) { padding: 0 4px; font-size: 12px; }

.dragon-table :deep(.el-table__header th) {
  background-color: #fafafa;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
}

/* 分页组件 */
.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
  padding: 12px 0;
}
.pagination-wrapper :deep(.el-pagination) {
  font-size: 13px;
}
.pagination-wrapper :deep(.el-pagination.is-background .el-pager li:not(.is-disabled).is-active) {
  background-color: #409eff;
}

/* 表格区 flex:1 占满剩余空间，内部滚动 */
.table-section {
  flex: 1; min-height: 0; overflow: hidden;
  display: flex; flex-direction: column;
}
/* Tab 内容区填充，用于 v-loading 包裹 */
.tab-content-fill {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 分页栏固定底部 */
.pagination-bar {
  flex-shrink: 0;
  display: flex; justify-content: flex-end; align-items: center;
  padding: 8px 0;
  min-height: 40px;
  width: 100%;
}
.pagination-bar :deep(.el-pagination) {
  font-size: 13px;
  align-items: center;
}
.pagination-bar :deep(.el-pagination .el-pagination__total),
.pagination-bar :deep(.el-pagination .el-pagination__jump),
.pagination-bar :deep(.el-pagination .el-pagination__sizes) {
  height: 28px; line-height: 28px;
}
.pagination-bar :deep(.el-pagination.is-background .el-pager li:not(.is-disabled).is-active) {
  background-color: #409eff;
}

/* ========== 空状态统一 ========== */
:deep(.el-empty) {
  padding: 40px 0;
}

/* ========== 响应式断点 ========== */
@media (max-width: 768px) {
  .dragon-page { padding: 4px !important; top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important; }

  /* 移动端 Header：显示新样式，隐藏桌面端 */
  .page-header { display: none !important; }
  .m-page-header { display: block !important; margin-bottom: 6px; }

  /* Tabs 外层 overflow:hidden 会裁剪分页，移动端改为 visible */
  :deep(.el-tabs--border-card) {
    overflow: visible !important;
  }

  /* 隐藏原生 el-tabs 头部，用自定义胶囊导航替代 */
  :deep(.dragon-tabs > .el-tabs__header) {
    display: none !important;
  }

  /* 移动端 el-tabs 容器去掉边框和圆角（与胶囊导航融合） */
  :deep(.dragon-tabs.el-tabs--border-card) {
    border: none !important;
    border-radius: var(--m-card-radius, 16px) !important;
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06)) !important;
  }

  /* Tabs 内容区 padding 调整 */
  :deep(.dragon-tabs > .el-tabs__content) {
    padding: 0 !important;
  }

  :deep(.dragon-tabs > .el-tabs__content > .el-tab-pane) {
    padding: 8px 4px !important;
  }

  /* Tabs 水平滚动 + 隐藏滚动条 */
  :deep(.el-tabs--border-card > .el-tabs__header) {
    background-color: #f5f7fa !important;
  }
  :deep(.el-tabs__header) {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;

    &::-webkit-scrollbar { display: none; }
  }
  :deep(.el-tabs__nav-wrap) {
    scrollbar-width: none;

    &::-webkit-scrollbar { display: none; }
  }
  :deep(.el-tabs__item) {
    min-height: 42px;
    line-height: 42px;
    padding: 0 8px !important;
    font-size: 12px !important;
    flex-shrink: 0;
  }

  /* border-card 内容区缩减 + overflow:visible 让分页不被裁剪 */
  :deep(.el-tabs--border-card > .el-tabs__content) {
    padding: 8px 4px !important;
    overflow: visible !important;
  }
  /* tab-pane 不设 overflow:hidden，让子元素处理滚动 */
  :deep(.el-tabs__content > .el-tab-pane) {
    overflow: visible !important;
  }

  /* Radio button 紧凑 */
  :deep(.el-radio-button__inner) { padding: 5px 8px !important; min-height: 32px; line-height: 22px; font-size: 11px !important; border-radius: 4px !important; }

  /* 表格紧凑 + 横向滚动，所有列完整显示 */
  :deep(.el-table) { font-size: 12px !important; overflow-x: auto !important; }
  :deep(.el-table .cell) { padding-left: 4px !important; padding-right: 4px !important; }
  :deep(.el-table th.el-table__cell) { padding: 6px 0 !important; font-size: 12px !important; }
  :deep(.el-table td.el-table__cell) { padding: 6px 0 !important; }

  /* 诊断按钮列 */
  .diag-col :deep(.el-button) { min-height: 36px; line-height: 36px; font-size: 12px; }

  /* 隐藏 mob-hide-col 列 */
  .dragon-page .el-table .mob-hide-col,
  .dragon-page .el-table th.mob-hide-col { display: none !important; }

  /* 可点击行样式 */
  .clickable-row { cursor: pointer; }
  .clickable-row:hover > td { background-color: #f5f7fa !important; }
  .clickable-row:active > td { background-color: #f0f7ff !important; }

  /* 股票名称链接样式 */
  .stock-name-link {
    color: #409eff;
    cursor: pointer;
    text-decoration: none;
    font-weight: 500;
    transition: all 0.2s;
    -webkit-tap-highlight-color: transparent;
  }
  .stock-name-link:hover {
    text-decoration: underline;
  }
  .stock-name-link:active {
    opacity: 0.6;
    transform: scale(0.98);
  }

  /* 统计卡片一行4个（龙虎榜tab + 次日表现tab） */
  .stats-row { display: flex !important; flex-wrap: nowrap !important; gap: 4px !important; margin-bottom: 6px !important; }
  .stats-row :deep(.el-col) { flex: 0 0 auto !important; max-width: none !important; width: 25% !important; padding: 0 2px !important; }
  .stat-card { background: linear-gradient(135deg, #fafbfc, #f5f7fa) !important; border: 1px solid #ebeef5 !important; box-shadow: none !important; text-align: center !important; }
  .stat-card :deep(.el-card__body) { padding: 6px 4px !important; }
  .summary-row { display: flex !important; flex-wrap: nowrap !important; gap: 4px !important; margin-bottom: 6px !important; }
  .summary-row :deep(.el-col) { flex: 0 0 auto !important; max-width: none !important; width: 25% !important; padding: 0 2px !important; }
  .summary-card { padding: 6px 4px !important; }
  .summary-num, .stat-number { font-size: 12px !important; word-break: break-all; line-height: 1.3 !important; }
  .summary-label, .stat-desc { font-size: 9px !important; line-height: 1.2 !important; color: #909399 !important; }

  /* 移动端隐藏原有 summary-row（由胶囊导航摘要栏替代） */
  .summary-row { display: none !important; }

  /* ========== 移动端胶囊导航 + 数据摘要 ========== */
  .mobile-tab-nav {
    display: block !important;
    background: var(--m-surface, #fff);
    border-radius: var(--m-card-radius, 16px);
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06));
    margin-bottom: 8px;
    overflow: hidden;
  }

  /* 胶囊滚动容器 */
  .m-pill-scroll {
    display: flex;
    gap: 8px;
    padding: 10px 14px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    background: var(--m-surface, #fff);
    border-bottom: 1px solid var(--m-border, #e0e4ea);
  }

  .m-pill-scroll::-webkit-scrollbar { display: none; }

  /* 单个胶囊 */
  .m-pill {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 3px;
    padding: 7px 14px;
    border-radius: 16px;
    font-size: 12px;
    color: var(--m-text3, #8e99ab);
    background: var(--m-surface2, #f0f2f5);
    white-space: nowrap;
    cursor: pointer;
    transition: all 0.2s ease;
    -webkit-tap-highlight-color: transparent;
  }

  .m-pill--active {
    color: #fff !important;
    background: var(--m-accent, #5b7cfa) !important;
    font-weight: 600;
    box-shadow: 0 2px 6px rgba(91, 124, 250, 0.3);
  }

  .m-pill:active {
    transform: scale(0.96);
  }

  /* 胶囊上的数字徽标 */
  .m-pill-badge {
    background: rgba(255, 255, 255, 0.25);
    padding: 1px 6px;
    border-radius: 8px;
    font-size: 10px;
    margin-left: 2px;
  }

  .m-pill:not(.m-pill--active) .m-pill-badge {
    background: rgba(0, 0, 0, 0.06);
    color: var(--m-text3, #8e99ab);
  }

  /* 数据摘要栏 */
  .m-summary-bar {
    display: flex;
    gap: 0;
    background: var(--m-surface2, #fafbfc);
    border-bottom: 1px solid var(--m-border, #e0e4ea);
  }

  .m-summary-item {
    flex: 1;
    padding: 8px 6px;
    text-align: center;
    border-right: 1px solid var(--m-border, #e0e4ea);
  }

  .m-summary-item:last-child {
    border-right: none;
  }

  .m-summary-val {
    font-size: 13px;
    font-weight: 700;
    line-height: 1.2;
  }

  .m-summary-label {
    font-size: 9px;
    color: var(--m-text3, #8e99ab);
    margin-top: 1px;
  }

  /* 资金流向单列 + 对比条纵向 */
  .flow-row-flex { overflow-y: auto !important; overflow-x: hidden !important; display: block !important; }
  .flow-row-flex :deep(.el-col) { flex: 0 0 100% !important; max-width: 100% !important; height: auto !important; display: block !important; }
  .flow-row-flex :deep(.el-col .flow-card) { flex: none !important; height: auto !important; max-height: none !important; display: block !important; }
  .flow-row-flex :deep(.el-col .flow-card .el-card__body) { flex: none !important; height: auto !important; display: block !important; }
  .flow-row-flex :deep(.flow-table-wrap) { flex: none !important; height: 300px !important; max-height: 300px !important; display: block !important; }
  .flow-row-flex :deep(.flow-table-wrap .el-table) { height: 300px !important; }
  .flow-compare-inline { flex-wrap: wrap; gap: 8px; padding: 6px 8px; }
  .cmp-item { flex: 1 1 100%; }

  /* 板块卡片单列 */
  .sector-row-scroll :deep(.el-col) {
    flex: 0 0 100% !important;
    max-width: 100% !important;
  }

  /* radio按钮组换行 */
  .table-toolbar { flex-wrap: wrap !important; gap: 6px !important; align-items: flex-start; }
  .toolbar-info { font-size: 11px; width: 100%; }
  :deep(.el-radio-group) { flex-wrap: wrap !important; }

  /* 历史回查工具栏 */
  .history-toolbar { flex-direction: column; align-items: stretch; gap: 6px; }
  .history-toolbar :deep(.el-date-editor) { width: 100% !important; }

  /* 分页紧凑居中 */
  .pagination-wrapper { justify-content: center; padding: 1px 0 calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0)); margin-top: 1px; }
  .pagination-wrapper :deep(.el-pagination) { font-size: 11px !important; flex-wrap: wrap; justify-content: center; gap: 2px; }
  .pagination-wrapper :deep(.el-pager li) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; font-size: 11px !important; }
  .pagination-wrapper :deep(.el-pagination button) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; }

  /* el-empty 缩小 */
  :deep(.el-empty) { padding: 20px 0 !important; }

  /* 进度条紧凑 */
  :deep(.el-progress) { width: 80px !important; }
  :deep(.el-progress__text) { font-size: 11px !important; }

  /* ========== 移动端卡片列表 ========== */
  .dragon-mobile-list { 
    flex: 1 1 0 !important;
    min-height: 0 !important;
    overflow-y: auto !important;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 8px;
    display: block !important;
  }
  .dragon-mobile-list::-webkit-scrollbar { width: 4px; }
  .dragon-mobile-list::-webkit-scrollbar-thumb { background: #c0c4cc; border-radius: 2px; }

  /* 资金流向/板块内嵌卡片列表：不占满flex */
  .dragon-flow-mobile { 
    flex: none !important; 
    overflow-y: auto !important; 
    padding-bottom: 0; 
    max-height: 300px;
    display: block !important;
  }
  .dragon-flow-mobile::-webkit-scrollbar { width: 4px; }
  .dragon-flow-mobile::-webkit-scrollbar-thumb { background: #c0c4cc; border-radius: 2px; }

  /* 股票卡片 */
  .dragon-stock-card { padding: 12px 14px !important; margin-bottom: 8px !important; cursor: pointer; -webkit-tap-highlight-color: transparent; }
  .dragon-stock-card:active { transform: scale(0.98); }

  /* 卡片顶部：排名 + 信息 + 价格 */
  .dragon-card-top { display: flex; align-items: center; gap: 10px; }
  .dragon-card-rank { width: 22px; height: 22px; border-radius: 6px; background: var(--m-surface2, #f0f2f5); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: var(--m-text3, #8e99ab); flex-shrink: 0; }
  .dragon-card-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .dragon-card-name { font-size: 14px; font-weight: 600; color: var(--m-text, #1a2332); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dragon-card-code { font-size: 11px; color: var(--m-text3, #8e99ab); }

  /* 价格列 */
  .dragon-card-price-col { text-align: right; flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
  .dragon-card-price { font-size: 15px; font-weight: 700; color: var(--m-text, #1a2332); }
  .dragon-card-chg { font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 4px; display: inline-block; }
  .dragon-card-chg.up { background: var(--m-up-bg, rgba(231,76,60,0.08)); color: var(--m-up, #e74c3c); }
  .dragon-card-chg.down { background: var(--m-down-bg, rgba(46,204,113,0.08)); color: var(--m-down, #2ecc71); }

  /* 卡片中部：买入/卖出/净买 */
  .dragon-card-mid { display: flex; align-items: center; gap: 10px; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--m-border, #e0e4ea); }
  .dragon-flow-item { font-size: 11px; display: flex; flex-direction: column; align-items: center; gap: 2px; flex: 1; }
  .flow-label { color: var(--m-text3, #8e99ab); font-size: 10px; }

  /* 卡片底部：tag + 原因 */
  .dragon-card-bottom { display: flex; align-items: center; justify-content: space-between; margin-top: 6px; gap: 8px; }
  .dragon-reason { font-size: 10px; color: var(--m-text3, #8e99ab); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; text-align: right; }
  .dragon-card-net { font-size: 12px; font-weight: 600; }
  .dragon-card-pill { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: var(--m-surface2, #f0f2f5); color: var(--m-text2, #5a6577); white-space: nowrap; }
  .dragon-date-tag { margin-right: 4px !important; margin-bottom: 2px !important; font-size: 10px !important; padding: 1px 6px !important; }

  /* 分页固定在底部，紧靠导航栏 */
  .pagination-bar {
    background: #fff !important;
    box-shadow: 0 -2px 6px rgba(0,0,0,0.06) !important;
    padding: 1px 1px calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0)) !important;
    min-height: 24px !important;
    margin-top: 1px;
  }
  .pagination-bar :deep(.el-pagination) { font-size: 11px !important; }
  .pagination-bar :deep(.el-pager li) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; font-size: 11px !important; }
  .pagination-bar :deep(.el-pagination button) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; }
}

@media (max-width: 480px) {
  .dragon-page { top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important; }
  
  /* 确保tab内容区域正确布局，overflow:visible 让分页可见 */
  :deep(.el-tabs__content > .el-tab-pane) {
    display: flex !important;
    flex-direction: column !important;
    overflow: visible !important;
  }
  .page-title { font-size: 14px !important; }
  :deep(.el-tabs__item) { padding: 0 6px !important; font-size: 11px !important; min-height: 38px; line-height: 38px; }
  :deep(.el-table) { font-size: 11px !important; overflow-x: auto !important; }
  :deep(.el-radio-button__inner) { padding: 4px 6px !important; font-size: 10px !important; min-height: 28px !important; }

  /* 超小屏 header：刷新按钮与日期同一行 */
  .header-right { flex-direction: row; align-items: center; justify-content: space-between; gap: 6px; flex-wrap: nowrap; }
  .header-right .el-button { flex-shrink: 0; min-height: 28px; font-size: 12px; padding: 5px 8px; }
  .update-time { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: right; }

  /* 统计卡片更紧凑 */
  .stats-row :deep(.el-col) { padding: 0 4px !important; }
  .summary-row :deep(.el-col) { padding: 0 4px !important; }
  .stat-card { padding: 8px 4px !important; }
  .stat-number { font-size: 16px !important; }

  /* 进度条更紧凑 */
  :deep(.el-progress) { width: 60px !important; }
}
</style>

<!-- 非 scoped 样式：表格单元格不换行 + 横向滑动 -->
<style>
.dragon-page .el-card .el-table .cell,
.dragon-page .el-tab-pane .el-table .cell {
  white-space: nowrap;
}
.dragon-page .el-card .el-table th.el-table__cell .cell,
.dragon-page .el-tab-pane .el-table th.el-table__cell .cell {
  white-space: nowrap;
}

/* 操作列固定右侧，水平滚动时悬浮 */
.dragon-page .el-table .el-table__cell.is-right:not(.is-leaf) {
  position: sticky !important;
  right: 0 !important;
  z-index: 3 !important;
  background: inherit;
}
.dragon-page .el-table .el-table__cell.is-right.is-leaf {
  position: sticky !important;
  right: 0 !important;
  z-index: 3 !important;
}

/* 连续上榜日期列：允许 tag 换行 */
.dragon-page .el-tab-pane .el-table .dates-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  white-space: normal;
}

/* 原因分类/资金流向：卡片内表格表头-表体对齐修复 */
.dragon-page .flow-card .el-table,
.dragon-page .sector-card .el-table {
  width: 100% !important;
}
.dragon-page .flow-card .el-table__header-wrapper table,
.dragon-page .sector-card .el-table__header-wrapper table,
.dragon-page .flow-card .el-table__body-wrapper table,
.dragon-page .sector-card .el-table__body-wrapper table {
  width: 100% !important;
  table-layout: fixed !important;
}

/* 移动端表格样式 */
@media (max-width: 768px) {
  /* 表头与表体 <table> 同宽，保证列对齐且联动滚动 */
  .dragon-page .el-table__header,
  .dragon-page .el-table__body {
    width: auto !important;
    min-width: 1200px;
  }
  /* 阻止 body-wrapper 独立横向滚动，统一由 .el-table 控制 */
  .dragon-page .el-table__body-wrapper {
    overflow-x: hidden !important;
  }
  /* 卡片内子表格列少，不需要大 min-width，覆盖 scoped 中 overflow-x:auto */
  .dragon-page .flow-card .el-table,
  .dragon-page .sector-card .el-table {
    overflow-x: auto !important;
  }
  .dragon-page .flow-card .el-table__header,
  .dragon-page .flow-card .el-table__body,
  .dragon-page .sector-card .el-table__header,
  .dragon-page .sector-card .el-table__body {
    min-width: auto;
  }
  /* 覆盖卡片内 table-layout:fixed + width:100%，允许横向展开 */
  .dragon-page .flow-card .el-table__header-wrapper table,
  .dragon-page .sector-card .el-table__header-wrapper table,
  .dragon-page .flow-card .el-table__body-wrapper table,
  .dragon-page .sector-card .el-table__body-wrapper table {
    width: auto !important;
    table-layout: auto !important;
  }

  .dragon-page .el-table .el-table__column-resize-proxy {
    display: none !important;
  }

  /* 滚动条美化 */
  .dragon-page .el-table__header-wrapper::-webkit-scrollbar,
  .dragon-page .el-table__body-wrapper::-webkit-scrollbar {
    height: 4px;
  }
  .dragon-page .el-table__header-wrapper::-webkit-scrollbar-thumb,
  .dragon-page .el-table__body-wrapper::-webkit-scrollbar-thumb {
    background: rgba(0,0,0,0.12);
    border-radius: 2px;
  }
  .dragon-page .el-table__header-wrapper::-webkit-scrollbar-track,
  .dragon-page .el-table__body-wrapper::-webkit-scrollbar-track {
    background: transparent;
  }
}
</style>







