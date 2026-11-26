<template>
  <div class="smart-pick">
    <!-- 桌面端 Header -->
    <div class="page-header" v-if="!isMobile">
      <h2 class="page-title"><el-icon><Aim /></el-icon> 智能选股</h2>
      <div class="header-right">
        <RefreshingIndicator :show="currentTabRefreshing" text="数据更新中" />
        <el-button size="small" :icon="Refresh" @click="refreshActiveTab">刷新当前</el-button>
        <el-tag size="small" type="info" effect="plain" round v-if="anyFromCache" class="cache-badge">缓存</el-tag>
        <span class="update-time" v-if="headerInfoText">{{ headerInfoText }}</span>
        <span class="update-time placeholder" v-else>加载中…</span>
      </div>
    </div>

    <!-- 移动端 Header：方案A渐变卡片风格 -->
    <div class="m-page-header" v-else>
      <div class="m-header-card">
        <div class="m-header-left">
          <div class="m-header-icon">🎯</div>
          <div class="m-header-info">
            <div class="m-header-title">智能选股</div>
            <div class="m-header-time">{{ headerInfoText || '加载中...' }}</div>
          </div>
        </div>
        <div class="m-header-right">
          <RefreshingIndicator :show="currentTabRefreshing" text="" />
          <div class="m-refresh-btn" @click="refreshActiveTab">
            <el-icon :class="{ 'm-refresh-spin': currentTabRefreshing }"><Refresh /></el-icon>
          </div>
        </div>
      </div>
    </div>

    <!-- 移动端胶囊导航（仅手机端显示） -->
    <div class="mobile-tab-nav">
      <div class="m-pill-scroll">
        <span v-for="tab in smartPickTabList" :key="tab.name" class="m-pill" :class="{ 'm-pill--active': activeTab === tab.name }" @click="activeTab = tab.name">
          {{ tab.icon }} {{ tab.label }}
          <span v-if="tab.badge" class="m-pill-badge">{{ tab.badge }}</span>
        </span>
      </div>
    </div>

    <el-tabs v-model="activeTab" type="border-card" class="main-tabs dragon-tabs" @tab-change="onTabChange">
      <el-tab-pane label="涨跌榜" name="rank">
        <div class="tab-pane-content">
          <div class="table-toolbar" v-if="!(rankLimitUp.loading.value || rankLimitDown.loading.value) && (rankGainers.length || rankLosers.length)">
            <span class="toolbar-info">今日涨跌停：{{ rankGainers.length }} : {{ rankLosers.length }}</span>
          </div>
          <el-empty v-if="!rankLimitUp.loading.value && !rankLimitDown.loading.value && (!rankGainers.length && !rankLosers.length)" description="暂无全市场涨跌数据，请稍后刷新重试" :image-size="80" />
          <template v-else>
            <el-tabs v-model="rankSubTab" type="card" class="rank-sub-tabs">
              <el-tab-pane name="limit_up">
                <template #label><span class="rank-tab-label"><el-icon><Top /></el-icon> 涨停榜 <el-tag type="danger" size="small" round>{{ rankGainers.length }}</el-tag></span></template>
                <div v-if="isMobile" v-loading="rankLimitUp.loading.value" class="mobile-card-list">
                  <div v-for="(row, idx) in paginatedRankGainers" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
                    <div class="top-row">
                      <div>
                        <div style="display:flex;align-items:center;gap:6px">
                          <span class="rank-badge" :class="(pagination.rankGainer.page - 1) * pagination.rankGainer.size + idx < 2 ? 'top3' : ''" style="width:20px;height:20px;font-size:10px">{{ (pagination.rankGainer.page - 1) * pagination.rankGainer.size + idx + 1 }}</span>
                          <span class="sname">{{ row.name }}</span>
                        </div>
                        <div class="scode">{{ row.code }} · {{ row.pattern || '换手' }}</div>
                      </div>
                      <div style="text-align:right">
                        <div class="price-big up">{{ row.price && row.price !== '--' ? Number(row.price).toFixed(2) : '--' }}</div>
                        <div class="chg-label up">{{ formatPct(row.change_pct) }}</div>
                      </div>
                    </div>
                    <div class="meta">
                      <span>成交{{ row.amount_billion && row.amount_billion > 0 ? Number(row.amount_billion).toFixed(2) + '亿' : '--' }}</span>
                      <span>换手{{ row.turnover_pct && row.turnover_pct > 0 ? Number(row.turnover_pct).toFixed(1) + '%' : '--' }}</span>
                    </div>
                    <div class="tech-strip">
                      <span class="sig up">{{ row.continuous_limit_num > 1 ? row.continuous_limit_num + '连板' : '首板' }}</span>
                      <span v-if="row.reason" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ row.reason }}</span>
                    </div>
                  </div>
                </div>
                <div v-else v-loading="rankLimitUp.loading.value" class="table-section">
                  <div class="table-scroll-wrapper">
                    <el-table :data="paginatedRankGainers" size="small" class="data-table" border height="100%" data-no-fit>
                      <el-table-column label="#" width="50" align="center"><template #default="{ $index }"><span class="rank-badge" :class="$index < 3 ? 'top3' : ''">{{ (pagination.rankGainer.page - 1) * pagination.rankGainer.size + $index + 1 }}</span></template></el-table-column>
                      <el-table-column prop="code" label="代码" min-width="75" align="center" />
                      <el-table-column prop="name" label="名称" width="100" show-overflow-tooltip><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
                      <el-table-column prop="price" label="最新价" min-width="80"><template #default="{ row }">{{ row.price && row.price !== '--' ? Number(row.price).toFixed(2) : '--' }}</template></el-table-column>
                      <el-table-column prop="change_pct" label="涨跌幅" width="100"><template #default="{ row }"><span class="c-red change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                      <el-table-column prop="amount_billion" label="成交额(亿)" min-width="90"><template #default="{ row }">{{ row.amount_billion && row.amount_billion > 0 ? Number(row.amount_billion).toFixed(2) : '--' }}</template></el-table-column>
                      <el-table-column prop="turnover_pct" label="换手率" min-width="75" align="center"><template #default="{ row }">{{ row.turnover_pct && row.turnover_pct > 0 ? Number(row.turnover_pct).toFixed(1) + '%' : '--' }}</template></el-table-column>
                      <el-table-column prop="continuous_limit_num" label="连板" min-width="65" align="center"><template #default="{ row }"><el-tag v-if="row.continuous_limit_num > 1" type="danger" size="small" effect="dark">{{ row.continuous_limit_num }}板</el-tag><span v-else class="text-muted">首板</span></template></el-table-column>
                      <el-table-column prop="pattern" label="板型" min-width="65" align="center" />
                      <el-table-column prop="reason" label="涨停原因" min-width="120" show-overflow-tooltip />
                      <el-table-column label="操作" width="60" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
                    </el-table>
                  </div>
                </div>
                <div class="pagination-wrapper">
                  <el-pagination v-model:current-page="pagination.rankGainer.page" v-model:page-size="pagination.rankGainer.size" :page-sizes="[10, 20, 50, 100]" :total="rankGainers.length" layout="total, sizes, prev, pager, next, jumper" background />
                </div>
              </el-tab-pane>
              <el-tab-pane name="limit_down">
                <template #label><span class="rank-tab-label"><el-icon><Bottom /></el-icon> 跌停榜 <el-tag type="success" size="small" round>{{ rankLosers.length }}</el-tag></span></template>
                <div v-if="isMobile" v-loading="rankLimitDown.loading.value" class="mobile-card-list">
                  <div v-for="(row, idx) in paginatedRankLosers" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
                    <div class="top-row">
                      <div>
                        <div style="display:flex;align-items:center;gap:6px">
                          <span class="rank-badge" style="width:20px;height:20px;font-size:10px">{{ (pagination.rankLoser.page - 1) * pagination.rankLoser.size + idx + 1 }}</span>
                          <span class="sname">{{ row.name }}</span>
                        </div>
                        <div class="scode">{{ row.code }}</div>
                      </div>
                      <div style="text-align:right">
                        <div class="price-big down">{{ row.price && row.price !== '--' ? Number(row.price).toFixed(2) : '--' }}</div>
                        <div class="chg-label down">{{ formatPct(row.change_pct) }}</div>
                      </div>
                    </div>
                    <div class="meta">
                      <span>成交{{ row.amount_billion && row.amount_billion > 0 ? Number(row.amount_billion).toFixed(2) + '亿' : '--' }}</span>
                      <span>换手{{ row.turnover_pct && row.turnover_pct > 0 ? Number(row.turnover_pct).toFixed(1) + '%' : '--' }}</span>
                      <span>量比{{ row.vol_ratio && row.vol_ratio > 0 ? Number(row.vol_ratio).toFixed(2) : '--' }}</span>
                    </div>
                  </div>
                </div>
                <div v-else v-loading="rankLimitDown.loading.value" class="table-section">
                  <div class="table-scroll-wrapper">
                    <el-table :data="paginatedRankLosers" size="small" class="data-table" border height="100%" data-no-fit>
                      <el-table-column label="#" width="50" align="center"><template #default="{ $index }"><span class="rank-badge">{{ (pagination.rankLoser.page - 1) * pagination.rankLoser.size + $index + 1 }}</span></template></el-table-column>
                      <el-table-column prop="code" label="代码" min-width="75" align="center" />
                      <el-table-column prop="name" label="名称" width="100" show-overflow-tooltip><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
                      <el-table-column prop="price" label="最新价" min-width="80"><template #default="{ row }">{{ row.price && row.price !== '--' ? Number(row.price).toFixed(2) : '--' }}</template></el-table-column>
                      <el-table-column prop="change_pct" label="涨跌幅" width="100"><template #default="{ row }"><span class="c-green change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                      <el-table-column prop="amount_billion" label="成交额(亿)" min-width="90"><template #default="{ row }">{{ row.amount_billion && row.amount_billion > 0 ? Number(row.amount_billion).toFixed(2) : '--' }}</template></el-table-column>
                      <el-table-column prop="turnover_pct" label="换手率" min-width="75" align="center"><template #default="{ row }">{{ row.turnover_pct && row.turnover_pct > 0 ? Number(row.turnover_pct).toFixed(1) + '%' : '--' }}</template></el-table-column>
                      <el-table-column prop="vol_ratio" label="量比" min-width="70" align="center"><template #default="{ row }">{{ row.vol_ratio && row.vol_ratio > 0 ? Number(row.vol_ratio).toFixed(2) : '--' }}</template></el-table-column>
                      <el-table-column prop="amplitude_pct" label="振幅" min-width="70" align="center"><template #default="{ row }">{{ row.amplitude_pct && row.amplitude_pct > 0 ? Number(row.amplitude_pct).toFixed(2) + '%' : '--' }}</template></el-table-column>
                      <el-table-column label="操作" width="60" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
                    </el-table>
                  </div>
                </div>
                <div class="pagination-wrapper">
                  <el-pagination v-model:current-page="pagination.rankLoser.page" v-model:page-size="pagination.rankLoser.size" :page-sizes="[10, 20, 50, 100]" :total="rankLosers.length" layout="total, sizes, prev, pager, next, jumper" background />
                </div>
              </el-tab-pane>
            </el-tabs>
          </template>
        </div>
      </el-tab-pane>

      <el-tab-pane label="龙虎榜策略" name="strategy">
        <div class="tab-pane-content">
          <el-empty v-if="!currentTabLoading && !strategySignals.length" description="暂无龙虎榜策略信号，请稍后刷新" :image-size="80" />
          <template v-else>
          <div class="table-toolbar"><span class="toolbar-info">共 {{ strategySignals.length }} 条信号<span v-if="dragonDateHint(strategyDragonDate)" class="dragon-date-hint">{{ dragonDateHint(strategyDragonDate) }}</span></span></div>
          <div v-if="isMobile" v-loading="currentTabLoading" class="mobile-card-list">
            <div v-for="(row, idx) in paginatedStrategySignals" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
              <div class="top-row">
                <div>
                  <span class="sname">{{ row.name }}</span>
                  <div class="scode">{{ row.code }} · {{ row.signal_type }}</div>
                </div>
                <div style="text-align:right">
                  <div :class="'price-big ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ row.price && row.price !== '--' ? Number(row.price).toFixed(2) : '--' }}</div>
                  <div :class="'chg-label ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ formatPct(row.change_pct) }}</div>
                </div>
              </div>
              <div class="meta">
                <span>买入<span class="c-red">{{ formatMoney(row.buy_amount) }}万</span></span>
                <span>卖出<span class="c-green">{{ formatMoney(row.sell_amount) }}万</span></span>
                <span>净买<span :class="row.net_amount >= 0 ? 'm-text-up' : 'm-text-down'">{{ formatMoney(row.net_amount) }}万</span></span>
              </div>
              <div class="tech-strip">
                <span class="sig" :class="row.score >= 70 ? 'up' : row.score >= 50 ? '' : 'down'" style="font-weight:600;">评分 {{ row.score }}</span>
                <span>{{ row.strategy_name }}</span>
                <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" v-if="row.reason">{{ row.reason }}</span>
              </div>
            </div>
          </div>
          <div v-else v-loading="currentTabLoading" class="table-section">
            <el-table :data="paginatedStrategySignals" size="small" border class="data-table" height="100%" data-no-fit>
              <el-table-column type="index" label="#" width="50" align="center" />
              <el-table-column prop="code" label="代码" min-width="80" align="center" />
              <el-table-column prop="name" label="名称" min-width="100"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
              <el-table-column prop="price" label="最新价" min-width="80" align="right"><template #default="{ row }">{{ row.price && row.price !== '--' ? Number(row.price).toFixed(2) : '--' }}</template></el-table-column>
              <el-table-column prop="change_pct" label="涨跌幅" min-width="100" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'" class="change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
              <el-table-column prop="net_amount" label="净买入(万)" min-width="100" align="right"><template #default="{ row }"><span :class="row.net_amount >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_amount) }}</span></template></el-table-column>
              <el-table-column prop="buy_amount" label="买入额(万)" min-width="95" align="right"><template #default="{ row }">{{ row.buy_amount ? formatMoney(row.buy_amount) : '--' }}</template></el-table-column>
              <el-table-column prop="sell_amount" label="卖出额(万)" min-width="95" align="right"><template #default="{ row }">{{ row.sell_amount ? formatMoney(row.sell_amount) : '--' }}</template></el-table-column>
              <el-table-column prop="signal_type" label="信号类型" min-width="90" align="center" />
              <el-table-column prop="strategy_name" label="策略名称" min-width="120" show-overflow-tooltip />
              <el-table-column prop="reason" label="上榜原因" min-width="120" show-overflow-tooltip><template #default="{ row }">{{ row.reason || '--' }}</template></el-table-column>
              <el-table-column prop="score" label="评分" min-width="70" align="center"><template #default="{ row }"><span :class="row.score >= 70 ? 'c-red' : row.score >= 50 ? '' : 'c-green'" style="font-weight:600">{{ row.score }}</span></template></el-table-column>
              <el-table-column label="操作" width="70" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
            </el-table>
          </div>
          <div class="pagination-wrapper">
            <el-pagination v-model:current-page="pagination.strategy.page" v-model:page-size="pagination.strategy.size" :page-sizes="[10, 20, 50]" :total="strategySignals.length" layout="total, sizes, prev, pager, next, jumper" background />
          </div>
          </template>
        </div>
      </el-tab-pane>

      <el-tab-pane label="资金流向" name="flow">
        <div class="tab-pane-content">
          <el-tabs v-model="flowSubTab" type="card" class="rank-sub-tabs">
            <el-tab-pane label="主力资金排名" name="main">
              <transition name="tab-fade" mode="out-in">
                <div :key="'flow-main'" class="sub-tab-content">
                  <el-empty v-if="!currentTabLoading && !flowResults.length" description="暂无资金流向数据，请稍后刷新" :image-size="80" />
                  <template v-else>
                  <div class="table-toolbar"><span class="toolbar-info">共 {{ flowResults.length }} 只<span v-if="dragonDateHint(flowDragonDate)" class="dragon-date-hint">{{ dragonDateHint(flowDragonDate) }}</span></span></div>
                  <div v-if="isMobile" v-loading="currentTabLoading" class="mobile-card-list">
                    <div v-for="(row, idx) in paginatedFlowMain" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
                      <div class="top-row">
                        <div>
                          <span class="sname">{{ row.name }}</span>
                          <div class="scode">{{ row.code }} · {{ row.vol_price_rel || '' }}</div>
                        </div>
                        <div style="text-align:right">
                          <div :class="'price-big ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ row.price || '--' }}</div>
                          <div :class="'chg-label ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ formatPct(row.change_pct) }}</div>
                        </div>
                      </div>
                      <div class="meta">
                        <span>主力<span :class="row.net_inflow >= 0 ? 'm-text-up' : 'm-text-down'">{{ formatMoney(row.net_inflow) }}万</span></span>
                        <span>量比{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</span>
                      </div>
                      <div class="tech-strip">
                        <span>强度<b>{{ row.fund_strength }}分</b></span>
                        <template v-if="row.backtest_score != null"><span>回测{{ row.backtest_score }}分 胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}% 夏普{{ row.backtest_sharpe != null ? row.backtest_sharpe.toFixed(2) : '--' }}</span></template>
                      </div>
                    </div>
                  </div>
                  <div v-else v-loading="currentTabLoading" class="table-section">
                    <el-table :data="paginatedFlowMain" size="small" border class="data-table" height="100%" data-no-fit>
                      <el-table-column type="index" label="#" width="50" align="center" />
                      <el-table-column prop="code" label="代码" min-width="80" align="center" />
                      <el-table-column prop="name" label="名称" min-width="100"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
                      <el-table-column prop="price" label="最新价" min-width="80" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
                      <el-table-column prop="change_pct" label="涨跌幅" min-width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'" class="change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                      <el-table-column prop="net_inflow" label="主力净流入(万)" min-width="120" align="right"><template #default="{ row }"><span :class="row.net_inflow >= 0 ? 'c-red' : 'c-green'">{{ formatMoney(row.net_inflow) }}</span></template></el-table-column>
                      <el-table-column prop="vol_ratio" label="量比" min-width="70" align="right"><template #default="{ row }">{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</template></el-table-column>
                      <el-table-column prop="vol_price_rel" label="量价关系" min-width="100" show-overflow-tooltip />
                      <el-table-column prop="fund_strength" label="资金强度" min-width="100" align="center"><template #default="{ row }"><div class="score-cell"><el-progress :percentage="row.fund_strength || 0" :stroke-width="4" :show-text="false" class="score-bar" /><span class="score-text">{{ row.fund_strength }}分</span></div></template></el-table-column>
                      <el-table-column label="回测验证" min-width="160" align="center"><template #default="{ row }">
                        <template v-if="row.backtest_score != null">
                          <span class="bt-inline-tag" :class="row.backtest_score >= 70 ? 'bt-good' : row.backtest_score >= 50 ? 'bt-mid' : 'bt-bad'">{{ row.backtest_score }}分</span>
                          <span class="bt-inline-text">胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span>
                          <span class="bt-inline-text">夏普{{ row.backtest_sharpe != null ? row.backtest_sharpe.toFixed(2) : '--' }}</span>
                        </template>
                        <span v-else class="text-muted">--</span>
                      </template></el-table-column>
                      <el-table-column label="操作" width="70" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
                    </el-table>
                  </div>
                  <div class="pagination-wrapper">
                    <el-pagination v-model:current-page="pagination.flowMain.page" v-model:page-size="pagination.flowMain.size" :page-sizes="[10, 20, 50]" :total="flowResults.length" layout="total, sizes, prev, pager, next, jumper" background />
                  </div>
                  </template>
                </div>
              </transition>
            </el-tab-pane>
            <el-tab-pane label="量价配合分析" name="volprice">
              <transition name="tab-fade" mode="out-in">
                <div :key="'flow-volprice'" class="sub-tab-content">
                  <div class="table-toolbar"><span class="toolbar-info">共 {{ volPriceData.length }} 只</span></div>
                  <div v-if="isMobile" v-loading="currentTabLoading" class="mobile-card-list">
                    <div v-for="(row, idx) in paginatedFlowVolPrice" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
                      <div class="top-row">
                        <div>
                          <span class="sname">{{ row.name }}</span>
                          <div class="scode">{{ row.code }} · {{ row.vol_price_rel || '' }}</div>
                        </div>
                        <div style="text-align:right">
                          <div :class="'price-big ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ row.price || '--' }}</div>
                          <div :class="'chg-label ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ formatPct(row.change_pct) }}</div>
                        </div>
                      </div>
                      <div class="meta">
                        <span>量比{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</span>
                        <span>量额比{{ row.amount_ratio ? Number(row.amount_ratio).toFixed(2) : '--' }}</span>
                        <span>换手{{ row.hs || '--' }}</span>
                      </div>
                      <div class="tech-strip">
                        <template v-if="row.backtest_score != null"><span>回测{{ row.backtest_score }}分 胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span></template>
                      </div>
                    </div>
                  </div>
                  <div v-else v-loading="currentTabLoading" class="table-section">
                    <el-table :data="paginatedFlowVolPrice" size="small" border class="data-table" height="100%" data-no-fit>
                      <el-table-column type="index" label="#" width="50" align="center" />
                      <el-table-column prop="code" label="代码" min-width="80" align="center" />
                      <el-table-column prop="name" label="名称" min-width="100"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
                      <el-table-column prop="price" label="最新价" min-width="80" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
                      <el-table-column prop="vol_price_rel" label="量价关系" min-width="100" />
                      <el-table-column prop="change_pct" label="涨跌幅" min-width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'" class="change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                      <el-table-column prop="vol_ratio" label="量比" min-width="65" align="right"><template #default="{ row }">{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</template></el-table-column>
                      <el-table-column prop="amount_ratio" label="量额比" min-width="70" align="right"><template #default="{ row }">{{ row.amount_ratio ? Number(row.amount_ratio).toFixed(2) : '--' }}</template></el-table-column>
                      <el-table-column prop="hs" label="换手率" min-width="80" align="right"><template #default="{ row }">{{ row.hs ? row.hs + '%' : '--' }}</template></el-table-column>
                      <el-table-column label="回测验证" min-width="160" align="center"><template #default="{ row }">
                        <template v-if="row.backtest_score != null">
                          <span class="bt-inline-tag" :class="row.backtest_score >= 70 ? 'bt-good' : row.backtest_score >= 50 ? 'bt-mid' : 'bt-bad'">{{ row.backtest_score }}分</span>
                          <span class="bt-inline-text">胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span>
                          <span class="bt-inline-text">夏普{{ row.backtest_sharpe != null ? row.backtest_sharpe.toFixed(2) : '--' }}</span>
                        </template>
                        <span v-else class="text-muted">--</span>
                      </template></el-table-column>
                      <el-table-column label="操作" width="70" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
                    </el-table>
                  </div>
                  <div class="pagination-wrapper">
                    <el-pagination v-model:current-page="pagination.flowVolPrice.page" v-model:page-size="pagination.flowVolPrice.size" :page-sizes="[10, 20, 50]" :total="volPriceData.length" layout="total, sizes, prev, pager, next, jumper" background />
                  </div>
                </div>
              </transition>
            </el-tab-pane>
          </el-tabs>
        </div>
      </el-tab-pane>

      <!-- 龙头选股：板块内综合评分最高的N只龙头股 -->
      <el-tab-pane label="龙头选股" name="leader">
        <div class="tab-pane-content">
          <div class="stock-filter-bar"><div class="filter-row">
            <span class="filter-label">每板块龙头数</span>
            <el-input-number v-model="leaderForm.top_n" :min="1" :max="10" :step="1" size="small" style="width:100px;margin-right:8px" />
            <span class="filter-label">板块数量</span>
            <el-input-number v-model="leaderForm.sector_count" :min="3" :max="30" :step="1" size="small" style="width:100px;margin-right:8px" />
            <span class="filter-label">市值</span>
            <el-select v-model="leaderForm.market_cap" size="small" clearable style="width:120px;margin-right:8px"><el-option label="全部" value="" /><el-option label="大盘股" value="large" /><el-option label="中盘股" value="mid" /><el-option label="小盘股" value="small" /></el-select>
            <span class="filter-label">成交额</span>
            <el-select v-model="leaderForm.amount_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于5亿" value="5e8" /><el-option label="大于10亿" value="1e9" /></el-select>
            <el-checkbox v-model="leaderForm.exclude_st" size="small" style="margin-right:12px">排除ST</el-checkbox>
            <el-button type="primary" size="small" :loading="leaderSubTabLoading" @click="fetchLeader">开始筛选</el-button>
          </div></div>
          <el-tabs v-model="leaderSubTab" type="card" class="rank-sub-tabs">
            <el-tab-pane label="行业龙头" name="industry">
              <transition name="tab-fade" mode="out-in">
                <div :key="'leader-industry'" class="sub-tab-content">
                  <div class="table-toolbar"><span class="toolbar-info">共 {{ leaderSectors.length }} 个板块 / {{ leaderAllStocks.length }} 只龙头</span></div>
                  <div v-loading="currentTabLoading || leaderSubTabLoading" class="leader-cards-wrap">
                    <div class="leader-cards-grid">
                      <div v-for="sec in leaderSectors" :key="sec.sector_name" class="leader-card">
                        <div class="leader-card-header">
                          <div class="sector-title">
                            <span class="sector-rank">#{{ sec.sector_rank }}</span>
                            <span class="sector-name-text">{{ sec.sector_name }}</span>
                            <el-tag v-if="sec.is_sustainable" type="success" size="small" effect="plain">5日强</el-tag>
                          </div>
                          <div class="sector-meta">
                            <span :class="sec.sector_change_pct >= 0 ? 'c-red' : 'c-green'">{{ formatPct(sec.sector_change_pct) }}</span>
                            <span class="sector-flow" :class="sec.sector_flow_net_yi >= 0 ? 'c-red' : 'c-green'">主力{{ sec.sector_flow_net_yi >= 0 ? '+' : '' }}{{ sec.sector_flow_net_yi != null ? Number(sec.sector_flow_net_yi).toFixed(2) : '--' }}亿</span>
                            <span class="sector-strength">5日{{ sec.sector_strength_5d_days > 0 ? '+' + Number(sec.sector_strength_5d_avg || 0).toFixed(2) + '%' : '--' }}</span>
                            <span class="sector-breadth">{{ sec.sector_up_count }}/{{ sec.sector_down_count }}</span>
                          </div>
                        </div>
                        <el-table :data="sec.leaders" size="small" border class="data-table leader-table" data-no-fit :row-class-name="isMobile ? 'clickable-row' : ''" @row-click="(row) => isMobile && goDiag(row.code)">
                          <el-table-column type="index" label="#" width="40" align="center" />
                          <el-table-column prop="code" label="代码" width="70" align="center" v-if="!isMobile" />
                          <el-table-column prop="name" label="名称" min-width="80"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
                          <el-table-column prop="price" label="最新价" width="75" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
                          <el-table-column prop="change_pct" label="涨跌幅" width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                          <el-table-column prop="limit_days" label="连板" width="55" align="center"><template #default="{ row }"><el-tag v-if="row.limit_days > 0" :type="row.limit_days >= 2 ? 'danger' : 'warning'" size="small" effect="dark">{{ row.limit_days }}</el-tag><span v-else class="text-muted">-</span></template></el-table-column>
                          <el-table-column prop="leader_score" label="龙头分" width="90" align="center"><template #default="{ row }"><div class="score-cell"><el-progress :percentage="row.leader_score || 0" :stroke-width="4" :show-text="false" class="score-bar" /><span class="score-text">{{ row.leader_score }}</span></div></template></el-table-column>
                          <el-table-column v-if="!isMobile" prop="market_cap_yi" label="市值(亿)" width="80" align="right"><template #default="{ row }">{{ row.market_cap_yi != null ? Number(row.market_cap_yi).toFixed(1) : '--' }}</template></el-table-column>
                          <el-table-column v-if="!isMobile" prop="technical_score" label="技术分" width="65" align="center"><template #default="{ row }">{{ row.technical_score != null ? Number(row.technical_score).toFixed(0) : '--' }}</template></el-table-column>
                          <el-table-column v-if="!isMobile" prop="fundamental_score" label="基本面" width="65" align="center"><template #default="{ row }">{{ row.fundamental_score != null ? Number(row.fundamental_score).toFixed(0) : '--' }}</template></el-table-column>
                          <el-table-column label="操作" width="60" align="center"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
                        </el-table>
                        <div v-if="sec.leaders && sec.leaders[0]?.reason" class="leader-card-reason">{{ sec.leaders[0].reason }}</div>
                      </div>
                    </div>
                    <el-empty v-if="!leaderSectors.length && !currentTabLoading && !leaderSubTabLoading" description="暂无龙头股数据" />
                  </div>
                </div>
              </transition>
            </el-tab-pane>
            <el-tab-pane label="概念龙头" name="concept">
              <transition name="tab-fade" mode="out-in">
                <div :key="'leader-concept'" class="sub-tab-content">
                  <div class="table-toolbar"><span class="toolbar-info">共 {{ leaderSectors.length }} 个板块 / {{ leaderAllStocks.length }} 只龙头</span></div>
                  <div v-loading="currentTabLoading || leaderSubTabLoading" class="leader-cards-wrap">
                    <div class="leader-cards-grid">
                      <div v-for="sec in leaderSectors" :key="sec.sector_name" class="leader-card">
                        <div class="leader-card-header">
                          <div class="sector-title">
                            <span class="sector-rank">#{{ sec.sector_rank }}</span>
                            <span class="sector-name-text">{{ sec.sector_name }}</span>
                            <el-tag v-if="sec.is_sustainable" type="success" size="small" effect="plain">5日强</el-tag>
                          </div>
                          <div class="sector-meta">
                            <span :class="sec.sector_change_pct >= 0 ? 'c-red' : 'c-green'">{{ formatPct(sec.sector_change_pct) }}</span>
                            <span class="sector-flow" :class="sec.sector_flow_net_yi >= 0 ? 'c-red' : 'c-green'">主力{{ sec.sector_flow_net_yi >= 0 ? '+' : '' }}{{ sec.sector_flow_net_yi != null ? Number(sec.sector_flow_net_yi).toFixed(2) : '--' }}亿</span>
                            <span class="sector-strength">5日{{ sec.sector_strength_5d_days > 0 ? '+' + Number(sec.sector_strength_5d_avg || 0).toFixed(2) + '%' : '--' }}</span>
                            <span class="sector-breadth">{{ sec.sector_up_count }}/{{ sec.sector_down_count }}</span>
                          </div>
                        </div>
                        <el-table :data="sec.leaders" size="small" border class="data-table leader-table" data-no-fit :row-class-name="isMobile ? 'clickable-row' : ''" @row-click="(row) => isMobile && goDiag(row.code)">
                          <el-table-column type="index" label="#" width="40" align="center" />
                          <el-table-column prop="code" label="代码" width="70" align="center" v-if="!isMobile" />
                          <el-table-column prop="name" label="名称" min-width="80"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
                          <el-table-column prop="price" label="最新价" width="75" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
                          <el-table-column prop="change_pct" label="涨跌幅" width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                          <el-table-column prop="limit_days" label="连板" width="55" align="center"><template #default="{ row }"><el-tag v-if="row.limit_days > 0" :type="row.limit_days >= 2 ? 'danger' : 'warning'" size="small" effect="dark">{{ row.limit_days }}</el-tag><span v-else class="text-muted">-</span></template></el-table-column>
                          <el-table-column prop="leader_score" label="龙头分" width="90" align="center"><template #default="{ row }"><div class="score-cell"><el-progress :percentage="row.leader_score || 0" :stroke-width="4" :show-text="false" class="score-bar" /><span class="score-text">{{ row.leader_score }}</span></div></template></el-table-column>
                          <el-table-column v-if="!isMobile" prop="market_cap_yi" label="市值(亿)" width="80" align="right"><template #default="{ row }">{{ row.market_cap_yi != null ? Number(row.market_cap_yi).toFixed(1) : '--' }}</template></el-table-column>
                          <el-table-column v-if="!isMobile" prop="technical_score" label="技术分" width="65" align="center"><template #default="{ row }">{{ row.technical_score != null ? Number(row.technical_score).toFixed(0) : '--' }}</template></el-table-column>
                          <el-table-column v-if="!isMobile" prop="fundamental_score" label="基本面" width="65" align="center"><template #default="{ row }">{{ row.fundamental_score != null ? Number(row.fundamental_score).toFixed(0) : '--' }}</template></el-table-column>
                          <el-table-column label="操作" width="60" align="center"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
                        </el-table>
                        <div v-if="sec.leaders && sec.leaders[0]?.reason" class="leader-card-reason">{{ sec.leaders[0].reason }}</div>
                      </div>
                    </div>
                    <el-empty v-if="!leaderSectors.length && !currentTabLoading && !leaderSubTabLoading" description="暂无龙头股数据" />
                  </div>
                </div>
              </transition>
            </el-tab-pane>
          </el-tabs>
        </div>
      </el-tab-pane>

      <el-tab-pane label="趋势突破" name="multi">
        <div class="tab-pane-content">
          <div class="stock-filter-bar"><div class="filter-row">
            <span class="filter-label">数量</span>
            <el-input-number v-model="multiFactorForm.count" :min="10" :max="100" :step="10" size="small" style="width:100px;margin-right:8px" />
            <span class="filter-label">市值</span>
            <el-select v-model="multiFactorForm.market_cap" size="small" clearable style="width:120px;margin-right:8px"><el-option label="全部" value="" /><el-option label="大盘股" value="large" /><el-option label="中盘股" value="mid" /><el-option label="小盘股" value="small" /></el-select>
            <span class="filter-label">成交额</span>
            <el-select v-model="multiFactorForm.amount_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于5亿" value="5e8" /><el-option label="大于10亿" value="1e9" /></el-select>
            <span class="filter-label">涨跌幅</span>
            <el-select v-model="multiFactorForm.change_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于3%" value="3" /><el-option label="大于5%" value="5" /></el-select>
            <el-checkbox v-model="multiFactorForm.exclude_st" size="small" style="margin-right:12px">排除ST</el-checkbox>
            <el-button type="primary" size="small" :loading="currentTabLoading" @click="fetchMultiFactor">开始筛选</el-button>
            <el-button size="small" @click="resetMultiFactorForm">重置</el-button>
          </div></div>
          <div v-if="!isMobile" class="strategy-info-banner" style="background:linear-gradient(135deg,#ecf5ff,#e8f4fd);border:1px solid #d9ecff;border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:12px;color:#409eff;display:flex;align-items:center;gap:8px">
            <el-icon><TrendCharts /></el-icon>
            <span style="flex:1"><b>趋势突破策略</b> — 全市场扫描，筛选均线多头排列+放量突破的活跃标的。<b>综合评分=技术面(60%)+基本面(40%)</b>（PE/PB/ROE/毛利率等）。</span>
          </div>
          <div class="table-toolbar"><span class="toolbar-info">共 {{ multiFactorResults.length }} 只</span></div>
          <el-empty v-if="!currentTabLoading && !multiFactorResults.length" description="暂无趋势突破信号，请调整筛选条件或稍后刷新" :image-size="80" />
          <template v-else>
          <div v-if="isMobile" v-loading="currentTabLoading" class="mobile-card-list">
            <div v-for="(row, idx) in paginatedMultiFactor" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
              <div class="top-row">
                <div>
                  <span class="sname">{{ row.name }}</span>
                  <div class="scode">{{ row.code }}</div>
                </div>
                <div style="text-align:right">
                  <div :class="'price-big ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ row.price || '--' }}</div>
                  <div :class="'chg-label ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ formatPct(row.change_pct) }}</div>
                </div>
              </div>
              <div class="meta">
                <span>综合<b>{{ row.composite_score }}分</b></span>
                <span>动量{{ row.momentum_score || '--' }}</span>
                <span>RSI{{ row.rsi6 || '--' }}</span>
              </div>
              <div class="tech-strip">
                <span>KDJ-J: {{ row.kdj_j || '--' }}</span>
                <span>量比{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</span>
                <template v-if="row.backtest_score != null"><span>回测{{ row.backtest_score }}分 胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span></template>
              </div>
            </div>
          </div>
          <div v-else v-loading="currentTabLoading" class="table-section">
            <el-table :data="paginatedMultiFactor" size="small" border class="data-table" height="100%" data-no-fit>
              <el-table-column type="index" label="#" width="50" align="center" />
              <el-table-column prop="code" label="代码" min-width="80" align="center" />
              <el-table-column prop="name" label="名称" min-width="100"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
              <el-table-column prop="price" label="最新价" min-width="80" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
              <el-table-column prop="change_pct" label="涨跌幅" min-width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'" class="change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
              <el-table-column prop="momentum_score" label="动量分" min-width="70" align="right" />
              <el-table-column prop="liquidity_score" label="量比分" min-width="70" align="right" />
              <el-table-column prop="technical_score" label="RSI/KDJ" min-width="75" align="right" />
              <el-table-column prop="vol_ratio" label="量比" min-width="65" align="right"><template #default="{ row }">{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</template></el-table-column>
              <el-table-column prop="rsi6" label="RSI6" min-width="65" align="right"><template #default="{ row }">{{ row.rsi6 !== '--' ? row.rsi6 : '--' }}</template></el-table-column>
              <el-table-column prop="kdj_j" label="KDJ-J" min-width="70" align="right"><template #default="{ row }">{{ row.kdj_j !== '--' ? row.kdj_j : '--' }}</template></el-table-column>
              <el-table-column prop="decline_20d" label="20日跌幅" min-width="85" align="right"><template #default="{ row }">{{ row.decline_20d !== '--' ? row.decline_20d : '--' }}</template></el-table-column>
              <el-table-column prop="pe_score" label="PE分" min-width="65" align="right"><template #default="{ row }">{{ row.pe_score !== '--' ? row.pe_score : '--' }}</template></el-table-column>
              <el-table-column prop="pb_score" label="PB分" min-width="65" align="right"><template #default="{ row }">{{ row.pb_score !== '--' ? row.pb_score : '--' }}</template></el-table-column>
              <el-table-column prop="roe_score" label="ROE分" min-width="70" align="right"><template #default="{ row }">{{ row.roe_score !== '--' ? row.roe_score : '--' }}</template></el-table-column>
              <el-table-column prop="composite_score" label="综合得分" min-width="120" align="center"><template #default="{ row }"><div class="score-cell"><el-progress :percentage="row.composite_score || 0" :stroke-width="4" :show-text="false" class="score-bar" /><span class="score-text">{{ row.composite_score }}分</span></div></template></el-table-column>
              <el-table-column label="回测验证" min-width="160" align="center"><template #default="{ row }">
                <template v-if="row.backtest_score != null">
                  <span class="bt-inline-tag" :class="row.backtest_score >= 70 ? 'bt-good' : row.backtest_score >= 50 ? 'bt-mid' : 'bt-bad'">{{ row.backtest_score }}分</span>
                  <span class="bt-inline-text">胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span>
                  <span class="bt-inline-text">夏普{{ row.backtest_sharpe != null ? row.backtest_sharpe.toFixed(2) : '--' }}</span>
                </template>
                <span v-else class="text-muted">--</span>
              </template></el-table-column>
              <el-table-column label="操作" width="70" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
            </el-table>
          </div>
          <div class="pagination-wrapper">
            <el-pagination v-model:current-page="pagination.multiFactor.page" v-model:page-size="pagination.multiFactor.size" :page-sizes="[10, 20, 50]" :total="multiFactorResults.length" layout="total, sizes, prev, pager, next, jumper" background />
          </div>
          </template>
        </div>
      </el-tab-pane>

      <el-tab-pane label="低吸企稳" name="lowabs">
        <div class="tab-pane-content">
          <div class="stock-filter-bar"><div class="filter-row">
            <span class="filter-label">数量</span>
            <el-input-number v-model="lowAbsForm.count" :min="10" :max="100" :step="10" size="small" style="width:100px;margin-right:8px" />
            <span class="filter-label">市值</span>
            <el-select v-model="lowAbsForm.market_cap" size="small" clearable style="width:120px;margin-right:8px"><el-option label="全部" value="" /><el-option label="大盘股" value="large" /><el-option label="中盘股" value="mid" /><el-option label="小盘股" value="small" /></el-select>
            <span class="filter-label">成交额</span>
            <el-select v-model="lowAbsForm.amount_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于5亿" value="5e8" /><el-option label="大于10亿" value="1e9" /></el-select>
            <span class="filter-label">涨跌幅</span>
            <el-select v-model="lowAbsForm.change_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于3%" value="3" /><el-option label="大于5%" value="5" /></el-select>
            <el-checkbox v-model="lowAbsForm.exclude_st" size="small" style="margin-right:12px">排除ST</el-checkbox>
            <el-button type="primary" size="small" :loading="currentTabLoading" @click="fetchLowAbsorption">开始筛选</el-button>
            <el-button size="small" @click="resetLowAbsForm">重置</el-button>
          </div></div>
          <div v-if="!isMobile" class="strategy-info-banner" style="background:linear-gradient(135deg,#fdf6ec,#faf0e4);border:1px solid #fde2c2;border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:12px;color:#e6a23c;display:flex;align-items:center;gap:8px">
            <el-icon><Bottom /></el-icon>
            <span style="flex:1"><b>低吸企稳策略</b> — 筛选跌幅3%-10%+超卖信号(RSI&lt;35或KDJ-J&lt;25)的股票。缩量筑底和20日跌幅&gt;5%额外加分。</span>
          </div>
          <div class="table-toolbar"><span class="toolbar-info">共 {{ lowAbsResults.length }} 只</span></div>
          <el-empty v-if="!currentTabLoading && !lowAbsResults.length" description="暂无低吸企稳信号，请调整筛选条件或稍后刷新" :image-size="80" />
          <template v-else>
          <div v-if="isMobile" v-loading="currentTabLoading" class="mobile-card-list">
            <div v-for="(row, idx) in paginatedLowAbs" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
              <div class="top-row">
                <div>
                  <span class="sname">{{ row.name }}</span>
                  <div class="scode">{{ row.code }}</div>
                </div>
                <div style="text-align:right">
                  <div :class="'price-big ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ row.price || '--' }}</div>
                  <div :class="'chg-label ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ formatPct(row.change_pct) }}</div>
                </div>
              </div>
              <div class="meta">
                <span>综合<b>{{ row.composite_score }}分</b></span>
                <span>RSI{{ row.rsi6 || '--' }}</span>
                <span>KDJ-J{{ row.kdj_j || '--' }}</span>
                <span>量比{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</span>
              </div>
              <div class="tech-strip">
                <template v-if="row.backtest_score != null"><span>回测{{ row.backtest_score }}分 胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span></template>
                <span v-if="row.reason" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ row.reason }}</span>
              </div>
            </div>
          </div>
          <div v-else v-loading="currentTabLoading" class="table-section">
            <el-table :data="paginatedLowAbs" size="small" border class="data-table" height="100%" data-no-fit>
              <el-table-column type="index" label="#" width="50" align="center" />
              <el-table-column prop="code" label="代码" min-width="80" align="center" />
              <el-table-column prop="name" label="名称" min-width="100"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
              <el-table-column prop="price" label="最新价" min-width="80" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
              <el-table-column prop="change_pct" label="涨跌幅" min-width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'" class="change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
              <el-table-column prop="vol_ratio" label="量比" min-width="65" align="right"><template #default="{ row }">{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</template></el-table-column>
              <el-table-column prop="rsi6" label="RSI6" min-width="65" align="right"><template #default="{ row }">{{ row.rsi6 !== '--' ? row.rsi6 : '--' }}</template></el-table-column>
              <el-table-column prop="kdj_j" label="KDJ-J" min-width="70" align="right"><template #default="{ row }">{{ row.kdj_j !== '--' ? row.kdj_j : '--' }}</template></el-table-column>
              <el-table-column prop="decline_20d" label="20日跌幅" min-width="85" align="right"><template #default="{ row }">{{ row.decline_20d !== '--' ? row.decline_20d : '--' }}</template></el-table-column>
              <el-table-column prop="absorption_score" label="吸分数" min-width="75" align="right" />
              <el-table-column prop="stability_score" label="企稳分" min-width="75" align="right" />
              <el-table-column prop="reason" label="选股理由" min-width="140" show-overflow-tooltip />
              <el-table-column prop="composite_score" label="综合得分" min-width="120" align="center"><template #default="{ row }"><div class="score-cell"><el-progress :percentage="row.composite_score || 0" :stroke-width="4" :show-text="false" class="score-bar" /><span class="score-text">{{ row.composite_score }}分</span></div></template></el-table-column>
              <el-table-column label="回测验证" min-width="160" align="center"><template #default="{ row }">
                <template v-if="row.backtest_score != null">
                  <span class="bt-inline-tag" :class="row.backtest_score >= 70 ? 'bt-good' : row.backtest_score >= 50 ? 'bt-mid' : 'bt-bad'">{{ row.backtest_score }}分</span>
                  <span class="bt-inline-text">胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span>
                  <span class="bt-inline-text">夏普{{ row.backtest_sharpe != null ? row.backtest_sharpe.toFixed(2) : '--' }}</span>
                </template>
                <span v-else class="text-muted">--</span>
              </template></el-table-column>
              <el-table-column label="操作" width="70" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
            </el-table>
          </div>
          <div class="pagination-wrapper">
            <el-pagination v-model:current-page="pagination.lowAbs.page" v-model:page-size="pagination.lowAbs.size" :page-sizes="[10, 20, 50]" :total="lowAbsResults.length" layout="total, sizes, prev, pager, next, jumper" background />
          </div>
          </template>
        </div>
      </el-tab-pane>

      <el-tab-pane label="技术评分" name="ml">
        <div class="tab-pane-content">
          <div class="stock-filter-bar"><div class="filter-row">
            <span class="filter-label">数量</span>
            <el-input-number v-model="mlForm.count" :min="10" :max="100" :step="10" size="small" style="width:100px;margin-right:8px" />
            <span class="filter-label">市值</span>
            <el-select v-model="mlForm.market_cap" size="small" clearable style="width:120px;margin-right:8px"><el-option label="全部" value="" /><el-option label="大盘股" value="large" /><el-option label="中盘股" value="mid" /><el-option label="小盘股" value="small" /></el-select>
            <span class="filter-label">成交额</span>
            <el-select v-model="mlForm.amount_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于5亿" value="5e8" /><el-option label="大于10亿" value="1e9" /></el-select>
            <span class="filter-label">涨跌幅</span>
            <el-select v-model="mlForm.change_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于3%" value="3" /><el-option label="大于5%" value="5" /></el-select>
            <el-checkbox v-model="mlForm.exclude_st" size="small" style="margin-right:12px">排除ST</el-checkbox>
            <el-button type="primary" size="small" :loading="currentTabLoading" @click="fetchMLStockPick">开始筛选</el-button>
            <el-button size="small" @click="resetMLForm">重置</el-button>
          </div></div>

          <!-- ML 模型状态栏 -->
          <div class="ml-status-banner" :class="mlModelStatus.loaded ? 'status-loaded' : 'status-not-loaded'" style="margin-bottom:8px;padding:10px 14px;border-radius:6px;font-size:12px;display:flex;align-items:center;gap:10px">
            <el-icon size="16"><DataAnalysis /></el-icon>
            <span style="flex:1">
              <b>技术评分</b> — 全市场TOP300活跃股，基于RSI+KDJ+MACD+布林带综合评分。
              <template v-if="mlModelStatus.loaded">
                ✅ LightGBM模型已加载 ({{ mlModelStatus.features }}个特征) | 最后训练: {{ mlModelStatus.last_trained || '未知' }}
              </template>
              <span v-else style="color:#e6a23c">⚠️ 使用因子引擎评分（模型未训练）</span>
            </span>
            <el-button v-if="isAdmin" size="small" type="primary" :loading="trainingLoading" @click="showTrainDialog = true">
              {{ mlModelStatus.loaded ? '重新训练' : '开始训练' }}
            </el-button>
          </div>

          <!-- 训练对话框（仅管理员可见） -->
          <el-dialog v-model="showTrainDialog" title="ML模型训练" width="500px" destroy-on-close>
            <el-form label-width="100px">
              <el-form-item label="训练天数">
                <el-input-number v-model="trainForm.days" :min="60" :max="500" :step="30" />
                <span style="margin-left:8px;color:#909399;font-size:12px">建议使用 250 天（约1年交易日）</span>
              </el-form-item>
              <el-form-item label="模型类型">
                <el-radio-group v-model="trainForm.model">
                  <el-radio value="lightgbm">LightGBM (推荐)</el-radio>
                  <el-radio value="xgboost">XGBoost</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-form>
            <template #footer>
              <el-button @click="showTrainDialog = false">取消</el-button>
              <el-button type="primary" :loading="trainingLoading" @click="startTraining">开始训练</el-button>
            </template>
          </el-dialog>

          <!-- 训练进度提示 -->
          <div v-if="trainingProgress" class="training-progress-banner" style="margin-bottom:8px;padding:10px 14px;border-radius:6px;background:#ecf5ff;border:1px solid #d9ecff;font-size:12px;display:flex;align-items:center;gap:10px">
            <el-icon class="is-loading"><Loading /></el-icon>
            <span style="flex:1">{{ trainingProgress }}</span>
          </div>

          <div class="table-toolbar"><span class="toolbar-info">共 {{ mlResults.length }} 只</span></div>
          <el-empty v-if="!currentTabLoading && !mlResults.length" description="暂无技术评分数据，请调整筛选条件或稍后刷新" :image-size="80" />
          <template v-else>
          <div v-if="isMobile" v-loading="currentTabLoading" class="mobile-card-list">
            <div v-for="(row, idx) in paginatedML" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
              <div class="top-row">
                <div>
                  <span class="sname">{{ row.name }}</span>
                  <div class="scode">{{ row.code }} · {{ row.prediction || '--' }}</div>
                </div>
                <div style="text-align:right">
                  <div :class="'price-big ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ row.price || '--' }}</div>
                  <div :class="'chg-label ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ formatPct(row.change_pct) }}</div>
                </div>
              </div>
              <div class="meta">
                <span>ML评分<b>{{ row.ml_score }}分</b></span>
                <span>置信{{ row.confidence ? (row.confidence * 100).toFixed(1) + '%' : '--' }}</span>
                <span>量比{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</span>
              </div>
              <div class="tech-strip">
                <span>RSI{{ row.rsi6 || '--' }}</span>
                <span>KDJ-J{{ row.kdj_j || '--' }}</span>
                <template v-if="row.backtest_score != null"><span>回测{{ row.backtest_score }}分 胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span></template>
              </div>
            </div>
          </div>
          <div v-else v-loading="currentTabLoading" class="table-section">
            <el-table :data="paginatedML" size="small" border class="data-table" height="100%" data-no-fit>
              <el-table-column type="index" label="#" width="50" align="center" />
              <el-table-column prop="code" label="代码" min-width="80" align="center" />
              <el-table-column prop="name" label="名称" min-width="100"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
              <el-table-column prop="price" label="最新价" min-width="80" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
              <el-table-column prop="change_pct" label="涨跌幅" min-width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'" class="change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
              <el-table-column prop="vol_ratio" label="量比" min-width="65" align="right"><template #default="{ row }">{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</template></el-table-column>
              <el-table-column prop="rsi6" label="RSI6" min-width="65" align="right"><template #default="{ row }">{{ row.rsi6 !== '--' ? row.rsi6 : '--' }}</template></el-table-column>
              <el-table-column prop="kdj_j" label="KDJ-J" min-width="70" align="right"><template #default="{ row }">{{ row.kdj_j !== '--' ? row.kdj_j : '--' }}</template></el-table-column>
              <el-table-column prop="ml_score" label="ML评分" min-width="100" align="center"><template #default="{ row }"><div class="score-cell"><el-progress :percentage="row.ml_score || 0" :stroke-width="4" :show-text="false" class="score-bar" /><span class="score-text">{{ row.ml_score }}分</span></div></template></el-table-column>
              <el-table-column prop="prediction" label="评分等级" min-width="90" align="center"><template #default="{ row }">
                <el-tag v-if="row.prediction === '强势'" type="danger" size="small">{{ row.prediction }}</el-tag>
                <el-tag v-else-if="row.prediction === '偏强'" type="warning" size="small">{{ row.prediction }}</el-tag>
                <el-tag v-else-if="row.prediction === '中性'" type="info" size="small">{{ row.prediction }}</el-tag>
                <el-tag v-else type="success" size="small">{{ row.prediction || '--' }}</el-tag>
              </template></el-table-column>
              <el-table-column prop="confidence" label="置信度" min-width="90" align="right"><template #default="{ row }">{{ row.confidence ? (row.confidence * 100).toFixed(1) + '%' : '--' }}</template></el-table-column>
              <el-table-column prop="features" label="特征" min-width="160" show-overflow-tooltip />
              <el-table-column label="回测验证" min-width="160" align="center"><template #default="{ row }">
                <template v-if="row.backtest_score != null">
                  <span class="bt-inline-tag" :class="row.backtest_score >= 70 ? 'bt-good' : row.backtest_score >= 50 ? 'bt-mid' : 'bt-bad'">{{ row.backtest_score }}分</span>
                  <span class="bt-inline-text">胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span>
                  <span class="bt-inline-text">夏普{{ row.backtest_sharpe != null ? row.backtest_sharpe.toFixed(2) : '--' }}</span>
                </template>
                <span v-else class="text-muted">--</span>
              </template></el-table-column>
              <el-table-column label="操作" width="70" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
            </el-table>
          </div>
          <div class="pagination-wrapper">
            <el-pagination v-model:current-page="pagination.ml.page" v-model:page-size="pagination.ml.size" :page-sizes="[10, 20, 50]" :total="mlResults.length" layout="total, sizes, prev, pager, next, jumper" background />
          </div>
          </template>
        </div>
      </el-tab-pane>

      <el-tab-pane label="量价关系" name="volprice_div">
        <div class="tab-pane-content">
          <div class="stock-filter-bar"><div class="filter-row">
            <span class="filter-label">数量</span>
            <el-input-number v-model="volPriceDivForm.count" :min="10" :max="100" :step="10" size="small" style="width:100px;margin-right:8px" />
            <span class="filter-label">市值</span>
            <el-select v-model="volPriceDivForm.market_cap" size="small" clearable style="width:120px;margin-right:8px"><el-option label="全部" value="" /><el-option label="大盘股" value="large" /><el-option label="中盘股" value="mid" /><el-option label="小盘股" value="small" /></el-select>
            <span class="filter-label">成交额</span>
            <el-select v-model="volPriceDivForm.amount_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于5亿" value="5e8" /><el-option label="大于10亿" value="1e9" /></el-select>
            <span class="filter-label">涨跌幅</span>
            <el-select v-model="volPriceDivForm.change_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于3%" value="3" /><el-option label="大于5%" value="5" /></el-select>
            <el-checkbox v-model="volPriceDivForm.exclude_st" size="small" style="margin-right:12px">排除ST</el-checkbox>
            <el-button type="primary" size="small" :loading="currentTabLoading" @click="fetchVolPriceDiv">开始筛选</el-button>
            <el-button size="small" @click="resetVolPriceDivForm">重置</el-button>
          </div></div>
          <div v-if="!isMobile" class="strategy-info-banner" style="background:linear-gradient(135deg,#f4ecf6,#f0e4fa);border:1px solid #d9b3ff;border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:12px;color:#9c27b0;display:flex;align-items:center;gap:8px">
            <el-icon><Connection /></el-icon>
            <span style="flex:1"><b>量价关系策略</b> — 识别底背离(看涨)&gt;温和放量&gt;量价齐升&gt;缩量回调等6种模式。候选池来自龙虎榜+涨停池。</span>
          </div>
          <div class="table-toolbar"><span class="toolbar-info">共 {{ volPriceDivResults.length }} 只<span v-if="dragonDateHint(volPriceDivDragonDate)" class="dragon-date-hint">{{ dragonDateHint(volPriceDivDragonDate) }}</span></span></div>
          <div v-if="isMobile" v-loading="currentTabLoading" class="mobile-card-list">
            <div v-for="(row, idx) in paginatedVolPriceDiv" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
              <div class="top-row">
                <div>
                  <span class="sname">{{ row.name }}</span>
                  <div class="scode">{{ row.code }} · {{ row.vol_price_rel || '' }}</div>
                </div>
                <div style="text-align:right">
                  <div :class="'price-big ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ row.price || '--' }}</div>
                  <div :class="'chg-label ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ formatPct(row.change_pct) }}</div>
                </div>
              </div>
              <div class="meta">
                <span>评分<b :class="row.score >= 70 ? 'm-text-up' : row.score >= 50 ? '' : 'm-text-down'">{{ row.score }}</b></span>
                <span>量比{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</span>
                <span>换手{{ row.hs || '--' }}</span>
              </div>
              <div class="tech-strip">
                <span>趋势<span :class="parseFloat(row.price_trend) >= 0 ? 'm-text-up' : 'm-text-down'">{{ row.price_trend || '--' }}</span></span>
                <template v-if="row.backtest_score != null"><span>回测{{ row.backtest_score }}分 胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span></template>
              </div>
            </div>
          </div>
          <div v-else v-loading="currentTabLoading" class="table-section">
            <el-table :data="paginatedVolPriceDiv" size="small" border class="data-table" height="100%" data-no-fit>
              <el-table-column type="index" label="#" width="50" align="center" />
              <el-table-column prop="code" label="代码" min-width="80" align="center" />
              <el-table-column prop="name" label="名称" min-width="100"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
              <el-table-column prop="price" label="最新价" min-width="80" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
              <el-table-column prop="change_pct" label="涨跌幅" min-width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'" class="change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
              <el-table-column prop="vol_price_rel" label="量价关系" min-width="100" />
              <el-table-column prop="vol_ratio" label="量比" min-width="65" align="right"><template #default="{ row }">{{ row.vol_ratio !== '--' ? row.vol_ratio : '--' }}</template></el-table-column>
              <el-table-column prop="amount_ratio" label="量额比" min-width="70" align="right" />
              <el-table-column prop="price_trend" label="价格趋势" min-width="85" align="right"><template #default="{ row }"><span :class="parseFloat(row.price_trend) >= 0 ? 'c-red' : 'c-green'">{{ row.price_trend !== '--' ? row.price_trend : '--' }}</span></template></el-table-column>
              <el-table-column prop="hs" label="换手率" min-width="80" align="right"><template #default="{ row }">{{ row.hs ? row.hs + '%' : '--' }}</template></el-table-column>
              <el-table-column prop="score" label="评分" min-width="65" align="center"><template #default="{ row }"><span :class="row.score >= 70 ? 'c-red' : row.score >= 50 ? '' : 'c-green'" style="font-weight:600">{{ row.score }}</span></template></el-table-column>
              <el-table-column label="回测验证" min-width="160" align="center"><template #default="{ row }">
                <template v-if="row.backtest_score != null">
                  <span class="bt-inline-tag" :class="row.backtest_score >= 70 ? 'bt-good' : row.backtest_score >= 50 ? 'bt-mid' : 'bt-bad'">{{ row.backtest_score }}分</span>
                  <span class="bt-inline-text">胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span>
                  <span class="bt-inline-text">夏普{{ row.backtest_sharpe != null ? row.backtest_sharpe.toFixed(2) : '--' }}</span>
                </template>
                <span v-else class="text-muted">--</span>
              </template></el-table-column>
              <el-table-column label="操作" width="70" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
            </el-table>
          </div>
          <div class="pagination-wrapper">
            <el-pagination v-model:current-page="pagination.volPriceDiv.page" v-model:page-size="pagination.volPriceDiv.size" :page-sizes="[10, 20, 50]" :total="volPriceDivResults.length" layout="total, sizes, prev, pager, next, jumper" background />
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="组合选股" name="combo">
        <div class="tab-pane-content">
          <div class="stock-filter-bar"><div class="filter-row">
            <span class="filter-label">数量</span>
            <el-input-number v-model="comboForm.count" :min="10" :max="100" :step="10" size="small" style="width:100px;margin-right:8px" />
            <span class="filter-label">市值</span>
            <el-select v-model="comboForm.market_cap" size="small" clearable style="width:120px;margin-right:8px"><el-option label="全部" value="" /><el-option label="大盘股" value="large" /><el-option label="中盘股" value="mid" /><el-option label="小盘股" value="small" /></el-select>
            <span class="filter-label">成交额</span>
            <el-select v-model="comboForm.amount_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于5亿" value="5e8" /><el-option label="大于10亿" value="1e9" /></el-select>
            <span class="filter-label">涨跌幅</span>
            <el-select v-model="comboForm.change_filter" size="small" clearable style="width:120px;margin-right:8px"><el-option label="不限" value="" /><el-option label="大于3%" value="3" /><el-option label="大于5%" value="5" /></el-select>
            <el-checkbox v-model="comboForm.exclude_st" size="small" style="margin-right:12px">排除ST</el-checkbox>
            <el-button type="primary" size="small" :loading="comboSubTabLoading" @click="fetchComboVote">开始筛选</el-button>
            <el-button size="small" @click="resetComboForm">重置</el-button>
          </div></div>
          <el-tabs v-model="comboSubTab" type="card" class="rank-sub-tabs">
            <el-tab-pane label="投票融合" name="vote">
              <transition name="tab-fade" mode="out-in">
                <div :key="'combo-vote'" class="sub-tab-content">
                  <div class="table-toolbar"><span class="toolbar-info">共 {{ comboResults.length }} 只</span></div>
                  <div v-if="isMobile" v-loading="currentTabLoading || comboSubTabLoading" class="mobile-card-list">
                    <div v-for="(row, idx) in paginatedComboVote" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
                      <div class="top-row">
                        <div>
                          <span class="sname">{{ row.name }}</span>
                          <div class="scode">{{ row.code }} · {{ row.strategy_count || 0 }}策略命中</div>
                        </div>
                        <div style="text-align:right">
                          <div :class="'price-big ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ row.price || '--' }}</div>
                          <div :class="'chg-label ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ formatPct(row.change_pct) }}</div>
                        </div>
                      </div>
                      <div class="meta">
                        <span>投票<b>{{ row.vote_score }}分</b></span>
                        <span>置信{{ row.confidence != null ? row.confidence + '%' : '--' }}</span>
                      </div>
                      <div class="tech-strip">
                        <template v-if="row.backtest_score != null"><span>回测{{ row.backtest_score }}分 胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span></template>
                        <span v-if="row.strategies" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ row.strategies }}</span>
                      </div>
                    </div>
                  </div>
                  <div v-else v-loading="currentTabLoading || comboSubTabLoading" class="table-section">
                    <el-table :data="paginatedComboVote" size="small" border class="data-table" height="100%" data-no-fit>
                      <el-table-column type="index" label="#" width="50" align="center" />
                      <el-table-column prop="code" label="代码" min-width="80" align="center" />
                      <el-table-column prop="name" label="名称" min-width="100"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
                      <el-table-column prop="price" label="最新价" min-width="80" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
                      <el-table-column prop="change_pct" label="涨跌幅" min-width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'" class="change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                      <el-table-column prop="strategy_count" label="命中数" min-width="70" align="center"><template #default="{ row }"><el-tag type="danger" size="small" effect="dark">{{ row.strategy_count || 0 }}</el-tag></template></el-table-column>
                      <el-table-column prop="vote_score" label="投票得分" min-width="100" align="center"><template #default="{ row }"><div class="score-cell"><el-progress :percentage="row.vote_score || 0" :stroke-width="4" :show-text="false" class="score-bar" /><span class="score-text">{{ row.vote_score }}分</span></div></template></el-table-column>
                      <el-table-column prop="confidence" label="置信度" min-width="80" align="right"><template #default="{ row }">{{ row.confidence != null ? row.confidence + '%' : '--' }}</template></el-table-column>
                      <el-table-column prop="strategies" label="命中策略" min-width="120" show-overflow-tooltip />
                      <el-table-column label="回测验证" min-width="160" align="center"><template #default="{ row }">
                        <template v-if="row.backtest_score != null">
                          <span class="bt-inline-tag" :class="row.backtest_score >= 70 ? 'bt-good' : row.backtest_score >= 50 ? 'bt-mid' : 'bt-bad'">{{ row.backtest_score }}分</span>
                          <span class="bt-inline-text">胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span>
                          <span class="bt-inline-text">夏普{{ row.backtest_sharpe != null ? row.backtest_sharpe.toFixed(2) : '--' }}</span>
                        </template>
                        <span v-else class="text-muted">--</span>
                      </template></el-table-column>
                      <el-table-column label="操作" width="70" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
                    </el-table>
                  </div>
                  <div class="pagination-wrapper">
                    <el-pagination v-model:current-page="pagination.comboVote.page" v-model:page-size="pagination.comboVote.size" :page-sizes="[10, 20, 50]" :total="comboResults.length" layout="total, sizes, prev, pager, next, jumper" background />
                  </div>
                </div>
              </transition>
            </el-tab-pane>
            <el-tab-pane label="加权融合" name="weight">
              <transition name="tab-fade" mode="out-in">
                <div :key="'combo-weight'" class="sub-tab-content">
                  <div class="table-toolbar"><span class="toolbar-info">共 {{ comboResults.length }} 只</span></div>
                  <div v-if="isMobile" v-loading="currentTabLoading || comboSubTabLoading" class="mobile-card-list">
                    <div v-for="(row, idx) in paginatedComboWeight" :key="row.code + '-' + idx" class="m-stock-card" @click="goDiag(row.code)">
                      <div class="top-row">
                        <div>
                          <span class="sname">{{ row.name }}</span>
                          <div class="scode">{{ row.code }} · {{ row.strategy_count || 0 }}策略命中</div>
                        </div>
                        <div style="text-align:right">
                          <div :class="'price-big ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ row.price || '--' }}</div>
                          <div :class="'chg-label ' + (row.change_pct >= 0 ? 'up' : 'down')">{{ formatPct(row.change_pct) }}</div>
                        </div>
                      </div>
                      <div class="meta">
                        <span>加权<b>{{ row.weight_score }}分</b></span>
                        <span>置信{{ row.confidence != null ? row.confidence + '%' : '--' }}</span>
                      </div>
                      <div class="tech-strip">
                        <template v-if="row.backtest_score != null"><span>回测{{ row.backtest_score }}分 胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span></template>
                        <span v-if="row.strategies" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ row.strategies }}</span>
                      </div>
                    </div>
                  </div>
                  <div v-else v-loading="currentTabLoading || comboSubTabLoading" class="table-section">
                    <el-table :data="paginatedComboWeight" size="small" border class="data-table" height="100%" data-no-fit>
                      <el-table-column type="index" label="#" width="50" align="center" />
                      <el-table-column prop="code" label="代码" min-width="80" align="center" />
                      <el-table-column prop="name" label="名称" min-width="100"><template #default="{ row }"><span class="stock-name-link" @click.stop="goDiag(row.code)">{{ row.name }}</span></template></el-table-column>
                      <el-table-column prop="price" label="最新价" min-width="80" align="right"><template #default="{ row }">¥{{ row.price || '--' }}</template></el-table-column>
                      <el-table-column prop="change_pct" label="涨跌幅" min-width="80" align="right"><template #default="{ row }"><span :class="row.change_pct >= 0 ? 'c-red' : 'c-green'" class="change-big">{{ formatPct(row.change_pct) }}</span></template></el-table-column>
                      <el-table-column prop="strategy_count" label="命中数" min-width="70" align="center"><template #default="{ row }"><el-tag type="danger" size="small" effect="dark">{{ row.strategy_count || 0 }}</el-tag></template></el-table-column>
                      <el-table-column prop="weight_score" label="加权得分" min-width="100" align="center"><template #default="{ row }"><div class="score-cell"><el-progress :percentage="row.weight_score || 0" :stroke-width="4" :show-text="false" class="score-bar" /><span class="score-text">{{ row.weight_score }}分</span></div></template></el-table-column>
                      <el-table-column prop="confidence" label="置信度" min-width="80" align="right"><template #default="{ row }">{{ row.confidence != null ? row.confidence + '%' : '--' }}</template></el-table-column>
                      <el-table-column prop="strategies" label="命中策略" min-width="120" show-overflow-tooltip />
                      <el-table-column label="回测验证" min-width="160" align="center"><template #default="{ row }">
                        <template v-if="row.backtest_score != null">
                          <span class="bt-inline-tag" :class="row.backtest_score >= 70 ? 'bt-good' : row.backtest_score >= 50 ? 'bt-mid' : 'bt-bad'">{{ row.backtest_score }}分</span>
                          <span class="bt-inline-text">胜率{{ row.backtest_win_rate?.toFixed(1) || '--' }}%</span>
                          <span class="bt-inline-text">夏普{{ row.backtest_sharpe != null ? row.backtest_sharpe.toFixed(2) : '--' }}</span>
                        </template>
                        <span v-else class="text-muted">--</span>
                      </template></el-table-column>
                      <el-table-column label="操作" width="70" align="center" fixed="right"><template #default="{ row }"><el-button type="primary" link size="small" @click.stop="goDiag(row.code)">诊断</el-button></template></el-table-column>
                    </el-table>
                  </div>
                  <div class="pagination-wrapper">
                    <el-pagination v-model:current-page="pagination.comboWeight.page" v-model:page-size="pagination.comboWeight.size" :page-sizes="[10, 20, 50]" :total="comboResults.length" layout="total, sizes, prev, pager, next, jumper" background />
                  </div>
                </div>
              </transition>
            </el-tab-pane>
          </el-tabs>
        </div>
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
import { ref, reactive, computed, onMounted, onBeforeUnmount, onActivated, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'

const route = useRoute()

// 从路由参数同步 tab 状态（支持从市场看板等页面直接跳转到指定tab）
function syncTabFromRoute() {
  const tab = route.query.tab
  const subTab = route.query.subTab
  if (tab) activeTab.value = tab
  if (subTab && activeTab.value === 'rank') rankSubTab.value = subTab
}
import { Refresh, Aim, Top, Bottom, TrendCharts, DataAnalysis, Connection, Collection, Loading } from '@element-plus/icons-vue'
import { strategyApi, marketApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'
import RefreshingIndicator from '@/components/RefreshingIndicator.vue'
import StockDiagnosisDrawer from './components/StockDiagnosisDrawer.vue'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.isAdmin)

const isMobile = ref(window.innerWidth <= 768)
const strategyInfo = ref({})

async function loadStrategyInfo() {
  try {
    const res = await strategyApi.getStrategyInfo().catch(() => ({}))
    if (res.strategies) {
      const infoMap = {}
      res.strategies.forEach(s => { infoMap[s.key] = s })
      strategyInfo.value = infoMap
    }
  } catch (e) {
    console.error('Failed to load strategy info:', e)
  }
}

const activeTab = ref('rank')

// 移动端胶囊导航列表
const smartPickTabList = computed(() => [
  { name: 'rank', label: '涨跌榜', icon: '📊', badge: (rankGainers.value.length + rankLosers.value.length) || undefined },
  { name: 'strategy', label: '龙虎榜策略', icon: '🐉' },
  { name: 'flow', label: '资金流向', icon: '💰' },
  { name: 'leader', label: '龙头选股', icon: '👑' },
  { name: 'multi', label: '趋势突破', icon: '📈' },
  { name: 'lowabs', label: '低吸企稳', icon: '🔻' },
  { name: 'ml', label: '技术评分', icon: '🤖' },
  { name: 'volprice_div', label: '量价关系', icon: '📉' },
  { name: 'combo', label: '组合选股', icon: '🧩' },
])

const rankSubTab = ref('limit_up')
const flowSubTab = ref('main')
const comboSubTab = ref('vote')
const leaderSubTab = ref('industry')

const pagination = reactive({
  rankGainer: { page: 1, size: 20 },
  rankLoser: { page: 1, size: 20 },
  strategy: { page: 1, size: 20 },
  flowMain: { page: 1, size: 20 },
  flowVolPrice: { page: 1, size: 20 },
  multiFactor: { page: 1, size: 20 },
  lowAbs: { page: 1, size: 20 },
  ml: { page: 1, size: 20 },
  volPriceDiv: { page: 1, size: 20 },
  comboVote: { page: 1, size: 20 },
  comboWeight: { page: 1, size: 20 }
})

const diagDrawerVisible = ref(false)
const diagStockCode = ref('')

// ═══ 表单状态 ════════════════════════════════════════
const multiFactorForm = ref({ count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true })
const lowAbsForm = ref({ count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true })
const mlForm = ref({ count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true })
const volPriceDivForm = ref({ count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true })
const comboForm = ref({ count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true })
const leaderForm = ref({ top_n: 5, sector_count: 12, market_cap: '', amount_filter: '', exclude_st: true })

// ═══ ML模型训练状态 ════════════════════════════════════════
const showTrainDialog = ref(false)
const trainingLoading = ref(false)
const trainingProgress = ref('')
const trainForm = reactive({ days: 250, model: 'lightgbm' })
const mlModelStatus = ref({ loaded: false, features: 0, last_trained: '' })

async function loadMLModelStatus() {
  try {
    const res = await strategyApi.getModelStatus()
    if (res) {
      mlModelStatus.value = res
    }
  } catch (e) {
    console.error('Failed to load ML model status:', e)
  }
}

async function startTraining() {
  trainingLoading.value = true
  trainingProgress.value = '正在准备训练数据...'
  showTrainDialog.value = false

  try {
    const res = await strategyApi.trainModel(trainForm.days, trainForm.model)
    if (res.status === 'success') {
      trainingProgress.value = `✅ ${res.message} | 准确率: ${(res.metrics.accuracy * 100).toFixed(1)}%`
      // 刷新模型状态
      await loadMLModelStatus()
      ElMessage.success('训练完成！')
    } else {
      trainingProgress.value = ''
      ElMessage.error(res.message || '训练失败')
    }
  } catch (e) {
    trainingProgress.value = ''
    console.error('Training failed:', e)
    ElMessage.error(`训练异常: ${e.message}`)
  } finally {
    trainingLoading.value = false
    // 3秒后清除进度提示
    setTimeout(() => { trainingProgress.value = '' }, 3000)
  }
}

// ═══ 筛选条件映射函数 ════════════════════════════════════════
function mapFilters(form) {
  const params = {}
  if (form.market_cap) params.market_cap = form.market_cap
  if (form.amount_filter) {
    try { params.min_amount = Math.floor(parseFloat(form.amount_filter) / 10000) } catch(e) {}
  }
  if (form.change_filter) {
    const v = parseFloat(form.change_filter)
    if (!isNaN(v)) params.change_range = 'up'
  }
  if (typeof form.exclude_st === 'boolean') {
    params.exclude_st = form.exclude_st ? 'true' : 'false'
  }
  return params
}

// ═══ useCachedFetch 模块（与市场看板一致的缓存机制）═════════════════════════════

// 涨跌榜 - 涨停/跌停（MARKET tier，4分钟刷新）
const rankLimitUp = useCachedFetch({
  key: 'smart:rank:limit_up',
  fetcher: () => marketApi.getLimitUpPool(),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
})
const rankLimitDown = useCachedFetch({
  key: 'smart:rank:limit_down',
  fetcher: () => marketApi.getLimitDownPool(),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
})

// 龙虎榜策略（MARKET tier）
const strategySignalsData = useCachedFetch({
  key: 'smart:strategy:signals',
  fetcher: () => strategyApi.getComparison(),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: (result) => {
    if (!result || result.error) return null
    const strategies = Array.isArray(result.strategies) ? result.strategies : []
    const flat = []
    for (const s of strategies) {
      for (const stock of (s.top_stocks || [])) {
        flat.push({
          code: stock.code || '', name: stock.name || '', signal_type: s.category || '信号',
          strategy_name: s.name || '--', score: parseInt(stock.score) || 0,
          net_amount: parseFloat(stock.net_amount) || 0, buy_amount: parseFloat(stock.buy_amount) || 0,
          sell_amount: parseFloat(stock.sell_amount) || 0, total_amount: parseFloat(stock.total_amount) || 0,
          reason: stock.reason || '--', change_pct: parseFloat(stock.change_pct) || 0,
          price: stock.price != null ? Number(stock.price).toFixed(2) : '--',
        })
      }
    }
    return { ...result, signals: flat.sort((a, b) => b.score - a.score) }
  },
})

// 资金流向（MARKET tier）
const flowData = useCachedFetch({
  key: 'smart:flow:main',
  fetcher: () => strategyApi.getCapitalFlowPicks(20),
  tier: CACHE_TIERS.MARKET,
  tradingAware: true,
  onSuccess: (result) => {
    if (!result || result.error) return null
    return {
      ...result,
      stocks: (Array.isArray(result.stocks) ? result.stocks : []).map(s => ({
        code: s.code || '', name: s.name || '', price: s.price != null ? Number(s.price).toFixed(2) : '--',
        change_pct: parseFloat(s.change_pct) || 0, net_inflow: parseFloat(s.main_net_inflow) || 0,
        vol_price_rel: s.divergence || '无明显特征', fund_strength: parseInt(s.score) || 50,
        vol_ratio: parseFloat(s.vol_ratio) != null ? parseFloat(s.vol_ratio).toFixed(2) : '--',
        backtest_score: s.backtest_score != null ? parseInt(s.backtest_score) : null,
        backtest_win_rate: s.backtest_win_rate != null ? parseFloat(s.backtest_win_rate) : null,
        backtest_sharpe: s.backtest_sharpe != null ? parseFloat(s.backtest_sharpe) : null,
      })),
      volume_price: (Array.isArray(result.volume_price) ? result.volume_price : []).map(s => ({
        code: s.code || '', name: s.name || '', price: s.price != null ? Number(s.price).toFixed(2) : '--',
        vol_price_rel: s.divergence || (s.volume_ratio > 1.5 ? '放量' : s.volume_ratio < 0.7 ? '缩量' : '正常'),
        change_pct: parseFloat(s.change_pct) || 0, vol_ratio: parseFloat(s.volume_ratio) != null ? parseFloat(s.volume_ratio).toFixed(2) : '--',
        amount_ratio: parseFloat(s.amount_ratio) || parseFloat(s.volume_ratio) || 0,
        hs: s.turnover_pct != null ? Number(s.turnover_pct).toFixed(1) + '%' : '--',
        backtest_score: s.backtest_score != null ? parseInt(s.backtest_score) : null,
        backtest_win_rate: s.backtest_win_rate != null ? parseFloat(s.backtest_win_rate) : null,
        backtest_sharpe: s.backtest_sharpe != null ? parseFloat(s.backtest_sharpe) : null,
      })),
    }
  },
})

// 趋势突破 - 多因子（STRATEGY tier，2小时存储/4分钟刷新）- key 与 preload 一致
const multiFactorKey = computed(() => `smart:multi:${JSON.stringify(multiFactorForm.value)}`)
const multiFactorData = useCachedFetch({
  key: multiFactorKey,
  fetcher: () => strategyApi.getMultiFactorPicks(multiFactorForm.value.count, 0, mapFilters(multiFactorForm.value)),
  tier: CACHE_TIERS.STRATEGY,
  tradingAware: true,
  onSuccess: (result) => {
    if (!result || result.error) return null
    return {
      ...result,
      stocks: (Array.isArray(result.stocks) ? result.stocks : []).map(s => ({
        code: s.code || '', name: s.name || '--', price: s.price != null ? Number(s.price).toFixed(2) : '--',
        change_pct: parseFloat(s.change_pct) || 0, momentum_score: parseInt(s.momentum) || parseInt(s.score) || 50,
        liquidity_score: parseInt(s.liquidity) || 50, technical_score: parseInt(s.tech) || parseInt(s.score) || 50,
        composite_score: parseInt(s.score) || 50,
        kdj_j: parseFloat(s.kdj_j) != null ? parseFloat(s.kdj_j).toFixed(1) : '--',
        rsi6: parseFloat(s.rsi6) != null ? parseFloat(s.rsi6).toFixed(1) : '--',
        vol_ratio: parseFloat(s.vol_ratio) != null ? parseFloat(s.vol_ratio).toFixed(2) : '--',
        decline_20d: parseFloat(s.decline_20d) != null ? parseFloat(s.decline_20d).toFixed(1) + '%' : '--',
        pe_score: s.pe_score != null ? Number(s.pe_score).toFixed(0) : '--',
        pb_score: s.pb_score != null ? Number(s.pb_score).toFixed(0) : '--',
        roe_score: s.roe_score != null ? Number(s.roe_score).toFixed(0) : '--',
        backtest_score: s.backtest_score != null ? parseInt(s.backtest_score) : null,
        backtest_win_rate: s.backtest_win_rate != null ? parseFloat(s.backtest_win_rate) : null,
        backtest_sharpe: s.backtest_sharpe != null ? parseFloat(s.backtest_sharpe) : null,
      })),
    }
  },
})

// 低吸企稳（STRATEGY tier）
const lowAbsKey = computed(() => `smart:lowabs:${JSON.stringify(lowAbsForm.value)}`)
const lowAbsData = useCachedFetch({
  key: lowAbsKey,
  fetcher: () => strategyApi.getLowAbsorptionPicks(lowAbsForm.value.count, 0, mapFilters(lowAbsForm.value)),
  tier: CACHE_TIERS.STRATEGY,
  tradingAware: true,
  onSuccess: (result) => {
    if (!result || result.error) return null
    return {
      ...result,
      stocks: (Array.isArray(result.stocks) ? result.stocks : []).map(s => ({
        code: s.code || '', name: s.name || '--', price: s.price != null ? Number(s.price).toFixed(2) : '--',
        change_pct: parseFloat(s.change_pct) || 0, absorption_score: parseInt(s.absorption_score) || 0,
        stability_score: parseInt(s.stability_score) || 0, composite_score: parseInt(s.score) || 50,
        reason: s.reason || s.reasons || '超卖反弹',
        kdj_j: parseFloat(s.kdj_j) != null ? parseFloat(s.kdj_j).toFixed(1) : '--',
        rsi6: parseFloat(s.rsi6) != null ? parseFloat(s.rsi6).toFixed(1) : '--',
        vol_ratio: parseFloat(s.vol_ratio || s.volume_ratio) != null ? parseFloat(s.vol_ratio || s.volume_ratio).toFixed(2) : '--',
        decline_20d: parseFloat(s.decline_20d) != null ? parseFloat(s.decline_20d).toFixed(1) + '%' : '--',
        backtest_score: s.backtest_score != null ? parseInt(s.backtest_score) : null,
        backtest_win_rate: s.backtest_win_rate != null ? parseFloat(s.backtest_win_rate) : null,
        backtest_sharpe: s.backtest_sharpe != null ? parseFloat(s.backtest_sharpe) : null,
      })),
    }
  },
})

// 技术评分 - ML（STRATEGY tier）
const mlKey = computed(() => `smart:ml:${JSON.stringify(mlForm.value)}`)
const mlData = useCachedFetch({
  key: mlKey,
  fetcher: () => strategyApi.predictStocks(mlForm.value.count, 0, mapFilters(mlForm.value)),
  tier: CACHE_TIERS.STRATEGY,
  tradingAware: true,
  onSuccess: (result) => {
    if (!result || result.error) return null
    return {
      ...result,
      stocks: (Array.isArray(result.stocks) ? result.stocks : []).map(s => ({
        code: s.code || '', name: s.name || '--', price: s.price != null ? Number(s.price).toFixed(2) : '--',
        change_pct: parseFloat(s.change_pct) || 0, ml_score: parseInt(s.ml_score || s.score) || 50,
        prediction: s.prediction || ((s.score || 0) >= 75 ? '强势' : (s.score || 0) >= 60 ? '偏强' : (s.score || 0) >= 45 ? '中性' : '偏弱'),
        confidence: s.confidence != null ? s.confidence : Math.min(98, Math.max(10, s.score || 50)) / 100,
        features: s.features || '--',
        vol_ratio: parseFloat(s.vol_ratio) != null ? parseFloat(s.vol_ratio).toFixed(2) : '--',
        rsi6: parseFloat(s.rsi6) != null ? parseFloat(s.rsi6).toFixed(1) : '--',
        kdj_j: parseFloat(s.kdj_j) != null ? parseFloat(s.kdj_j).toFixed(1) : '--',
        backtest_score: s.backtest_score != null ? parseInt(s.backtest_score) : null,
        backtest_win_rate: s.backtest_win_rate != null ? parseFloat(s.backtest_win_rate) : null,
        backtest_sharpe: s.backtest_sharpe != null ? parseFloat(s.backtest_sharpe) : null,
      })),
    }
  },
})

// 量价关系（STRATEGY tier）
const volPriceDivKey = computed(() => `smart:volprice_div:${JSON.stringify(volPriceDivForm.value)}`)
const volPriceDivData = useCachedFetch({
  key: volPriceDivKey,
  fetcher: () => strategyApi.getVolumePriceDivergence(volPriceDivForm.value.count, 0, mapFilters(volPriceDivForm.value)),
  tier: CACHE_TIERS.STRATEGY,
  tradingAware: true,
  onSuccess: (result) => {
    if (!result || result.error) return null
    return {
      ...result,
      stocks: (Array.isArray(result.stocks) ? result.stocks : []).map(s => ({
        code: s.code, name: s.name, price: s.price, change_pct: s.change_pct,
        vol_price_rel: s.vol_price_rel || s.divergence_type, amount_ratio: s.amount_ratio,
        vol_ratio: s.vol_ratio != null ? Number(s.vol_ratio).toFixed(2) : '--',
        price_trend: s.price_trend != null ? Number(s.price_trend).toFixed(2) + '%' : '--',
        score: parseInt(s.score) || 0, hs: s.hs && s.hs > 0 ? Number(s.hs).toFixed(1) + '%' : '--',
        backtest_score: s.backtest_score != null ? parseInt(s.backtest_score) : null,
        backtest_win_rate: s.backtest_win_rate != null ? parseFloat(s.backtest_win_rate) : null,
        backtest_sharpe: s.backtest_sharpe != null ? parseFloat(s.backtest_sharpe) : null,
      })),
    }
  },
})

// 组合选股 - cache key 包含 subTab，确保 vote/weight 各自独立缓存
const comboVoteKey = computed(() => `smart:combo:${comboSubTab.value}:${JSON.stringify(comboForm.value)}`)
const comboData = useCachedFetch({
  key: comboVoteKey,
  fetcher: () => {
    const mode = comboSubTab.value === 'weight' ? 'weight' : 'vote'
    return strategyApi.getStrategyCombo(comboForm.value.count || 20, mode, 0, mapFilters(comboForm.value))
  },
  tier: CACHE_TIERS.STRATEGY,
  tradingAware: true,
  onSuccess: (result) => {
    if (!result || result.error) return null
    return {
      ...result,
      stocks: (Array.isArray(result.stocks || result.combined_stocks) ? (result.stocks || result.combined_stocks) : []).map(s => ({
        code: s.code, name: s.name, price: s.price, change_pct: s.change_pct,
        vote_score: s.vote_score != null ? s.vote_score : s.score,
        weight_score: s.weight_score != null ? s.weight_score : s.score,
        strategies: s.strategies, strategy_count: s.strategy_count || 0, confidence: s.confidence,
        backtest_score: s.backtest_score != null ? parseInt(s.backtest_score) : null,
        backtest_win_rate: s.backtest_win_rate != null ? parseFloat(s.backtest_win_rate) : null,
        backtest_sharpe: s.backtest_sharpe != null ? parseFloat(s.backtest_sharpe) : null,
      })),
    }
  },
})

// 龙头选股 - cache key 包含 subTab(industry/concept)，确保两类板块各自独立缓存
const leaderKey = computed(() => `smart:leader:${leaderSubTab.value}:${JSON.stringify(leaderForm.value)}`)
const leaderData = useCachedFetch({
  key: leaderKey,
  fetcher: () => strategyApi.getLeaderPicks(leaderSubTab.value, leaderForm.value.top_n || 3, leaderForm.value.sector_count || 10, 0, mapFilters(leaderForm.value)),
  tier: CACHE_TIERS.STRATEGY,
  tradingAware: true,
  onSuccess: (result) => {
    if (!result || result.error) return null
    return {
      ...result,
      sectors: (Array.isArray(result.sectors) ? result.sectors : []).map(sec => ({
        sector_name: sec.sector_name,
        sector_rank: sec.sector_rank,
        sector_change_pct: parseFloat(sec.sector_change_pct) || 0,
        sector_flow_net_yi: sec.sector_flow_net_yi != null ? parseFloat(sec.sector_flow_net_yi) : null,
        sector_amount_yi: sec.sector_amount_yi != null ? parseFloat(sec.sector_amount_yi) : null,
        sector_up_count: sec.sector_up_count || 0,
        sector_down_count: sec.sector_down_count || 0,
        sector_strength_5d_avg: parseFloat(sec.sector_strength_5d_avg) || 0,
        sector_strength_5d_days: sec.sector_strength_5d_days || 0,
        is_sustainable: !!sec.is_sustainable,
        sector_strength_score: sec.sector_strength_score || 0,
        leaders: (Array.isArray(sec.leaders) ? sec.leaders : []).map(l => ({
          code: String(l.code || ''),
          name: l.name || '--',
          price: l.price != null ? Number(l.price).toFixed(2) : '--',
          change_pct: parseFloat(l.change_pct) || 0,
          amount_wan: parseFloat(l.amount_wan) || 0,
          market_cap_yi: l.market_cap_yi != null ? parseFloat(l.market_cap_yi) : null,
          limit_days: parseInt(l.limit_days) || 0,
          leader_score: parseInt(l.leader_score) || 0,
          technical_score: l.technical_score != null ? parseFloat(l.technical_score) : null,
          fundamental_score: l.fundamental_score != null ? parseFloat(l.fundamental_score) : null,
          reason: l.reason || '',
        })),
      })),
    }
  },
})

// ═══ 模块列表（用于聚合状态）═══════════════════════════════════════
const allModules = [
  rankLimitUp, rankLimitDown, strategySignalsData, flowData,
  multiFactorData, lowAbsData, mlData, volPriceDivData, comboData, leaderData,
]

// ═══ 聚合加载状态 ════════════════════════════════════════
const currentTabLoading = computed(() => {
  const tabModules = getTabModules(activeTab.value)
  return tabModules.some(m => m.loading.value)
})
const comboSubTabLoading = computed(() => comboData.loading.value)
const leaderSubTabLoading = computed(() => leaderData.loading.value)
// 只检查当前 tab 模块的刷新状态，避免后台其他模块刷新时一直显示"数据更新中"
const currentTabRefreshing = computed(() => {
  const tabModules = getTabModules(activeTab.value)
  return tabModules.some(m => m.refreshing.value || m.loading.value)
})
// 全局刷新状态（用于按钮等场景）
const anyRefreshing = computed(() => allModules.some(m => m.refreshing.value || m.loading.value))

// 当前是否有缓存数据展示
const anyFromCache = computed(() => allModules.some(m => m.fromCache.value))

function getTabModules(tab) {
  switch (tab) {
    case 'rank': return [rankLimitUp, rankLimitDown]
    case 'strategy': return [strategySignalsData]
    case 'flow': return [flowData]
    case 'multi': return [multiFactorData]
    case 'lowabs': return [lowAbsData]
    case 'ml': return [mlData]
    case 'volprice_div': return [volPriceDivData]
    case 'combo': return [comboData]
    case 'leader': return [leaderData]
    default: return []
  }
}

// ═══ 最后更新时间（取当前 tab 模块的最新时间）═════════════════════════════
const lastUpdate = computed(() => {
  const tabModules = getTabModules(activeTab.value)
  const updates = tabModules.map(m => m.lastUpdate.value).filter(t => t > 0)
  return updates.length ? Math.max(...updates) : 0
})

// 后端返回的数据日期（优先用当前tab模块的 data_date）
const dataDateStr = computed(() => {
  const tabModules = getTabModules(activeTab.value)
  for (const m of tabModules) {
    if (m.data.value?.data_date) return m.data.value.data_date
  }
  const d = new Date()
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mo}-${day}`
})

const lastUpdateStr = computed(() => {
  if (!lastUpdate.value) return ''
  return new Date(lastUpdate.value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
})

const headerInfoText = computed(() => {
  if (!lastUpdate.value) return ''
  return `数据日期 ${dataDateStr.value} | 更新于 ${lastUpdateStr.value}`
})

// ═══ 计算属性 - 从 useCachedFetch 模块提取数据 ══════════════════════════════
const rankGainers = computed(() => {
  const d = rankLimitUp.data.value || {}
  return (Array.isArray(d.stocks) ? d.stocks : []).map(s => ({
    code: String(s.code || ''), name: s.name || '--', price: s.price != null ? Number(s.price).toFixed(2) : '--',
    change_pct: parseFloat(s.change_pct) || 0, amount_billion: parseFloat(s.amount_billion) || 0,
    turnover_pct: parseFloat(s.turnover_pct) || 0, continuous_limit_num: parseInt(s.continuous_limit_num) || 1,
    reason: s.reason || '--', pattern: s.pattern || '换手', vol_ratio: parseFloat(s.vol_ratio) || 0,
    amplitude_pct: parseFloat(s.amplitude_pct) || 0,
  }))
})
const rankLosers = computed(() => {
  const d = rankLimitDown.data.value || {}
  return (Array.isArray(d.stocks) ? d.stocks : []).map(s => ({
    code: String(s.code || ''), name: s.name || '--', price: s.price != null ? Number(s.price).toFixed(2) : '--',
    change_pct: parseFloat(s.change_pct) || 0, amount_billion: parseFloat(s.amount_billion) || 0,
    turnover_pct: parseFloat(s.turnover_pct) || 0, vol_ratio: parseFloat(s.vol_ratio) || 0,
    amplitude_pct: parseFloat(s.amplitude_pct) || 0,
  }))
})
const strategySignals = computed(() => (strategySignalsData.data.value?.signals) || [])
const flowResults = computed(() => (flowData.data.value?.stocks) || [])
const volPriceData = computed(() => (flowData.data.value?.volume_price) || [])
const multiFactorResults = computed(() => (multiFactorData.data.value?.stocks) || [])
const lowAbsResults = computed(() => (lowAbsData.data.value?.stocks) || [])
const mlResults = computed(() => (mlData.data.value?.stocks) || [])
const volPriceDivResults = computed(() => (volPriceDivData.data.value?.stocks) || [])
const comboResults = computed(() => (comboData.data.value?.stocks) || [])
const leaderSectors = computed(() => (leaderData.data.value?.sectors) || [])
const leaderAllStocks = computed(() => {
  const all = []
  for (const sec of leaderSectors.value) {
    if (Array.isArray(sec.leaders)) all.push(...sec.leaders)
  }
  return all
})

// 龙虎榜数据日期提示
const strategyDragonDate = computed(() => strategySignalsData.data.value?.dragon_data_date || '')
const flowDragonDate = computed(() => flowData.data.value?.dragon_data_date || '')
const volPriceDivDragonDate = computed(() => volPriceDivData.data.value?.dragon_data_date || '')

function paginate(data, key) {
  const p = pagination[key]
  return data.slice((p.page - 1) * p.size, p.page * p.size)
}
const paginatedRankGainers = computed(() => paginate(rankGainers.value, 'rankGainer'))
const paginatedRankLosers = computed(() => paginate(rankLosers.value, 'rankLoser'))
const paginatedStrategySignals = computed(() => paginate(strategySignals.value, 'strategy'))
const paginatedFlowMain = computed(() => paginate(flowResults.value, 'flowMain'))
const paginatedFlowVolPrice = computed(() => paginate(volPriceData.value, 'flowVolPrice'))
const paginatedMultiFactor = computed(() => paginate(multiFactorResults.value, 'multiFactor'))
const paginatedLowAbs = computed(() => paginate(lowAbsResults.value, 'lowAbs'))
const paginatedML = computed(() => paginate(mlResults.value, 'ml'))
const paginatedVolPriceDiv = computed(() => paginate(volPriceDivResults.value, 'volPriceDiv'))
const paginatedComboVote = computed(() => paginate(comboResults.value, 'comboVote'))
const paginatedComboWeight = computed(() => { const sorted = [...comboResults.value].sort((a, b) => (b.weight_score || 0) - (a.weight_score || 0)); return paginate(sorted, 'comboWeight') })

function formatPct(v) { if (v == null) return '--'; const n = Number(v); return isNaN(n) ? '--' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%' }
function formatMoney(v) { if (v == null || v === '--') return '--'; const n = Number(v); if (isNaN(n)) return String(v); if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'; if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + '万'; return n.toFixed(2) }

function dragonDateHint(date) {
  if (!date) return ''
  const today = new Date()
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  return date === todayStr ? '' : `（龙虎榜数据为${date}）`
}

function limitUpRowClass({ row, rowIndex }) { return rowIndex < 3 ? 'limit-up-row' : '' }
function limitDownRowClass() { return 'limit-down-row' }

function goDiag(code) {
  diagStockCode.value = code
  diagDrawerVisible.value = true
}

// ═══ Tab 切换时触发对应模块刷新（useCachedFetch 自动处理缓存）═════════════════════════════
async function onTabChange(tab) {
  const tabModules = getTabModules(tab)
  if (tabModules.length > 0) {
    await Promise.allSettled(tabModules.map(m => m.silentRefresh()))
  }
}

// flowSubTab 切换：刷新资金流向数据
watch(flowSubTab, () => {
  flowData.silentRefresh()
})

// comboSubTab 切换：cache key 已包含 subTab，useCachedFetch handleKeyChange 自动处理
// clear 旧数据避免显示上一个页签内容，然后重新加载
watch(comboSubTab, () => {
  comboData.clear()
})

// leaderSubTab 切换：cache key 包含 subTab，clear 旧数据后重新加载
watch(leaderSubTab, () => {
  leaderData.clear()
})

async function refreshActiveTab() {
  const tabModules = getTabModules(activeTab.value)
  await Promise.allSettled(tabModules.map(m => m.refresh()))
}

// ═══ 手动筛选按钮（带 filter 参数的策略）═════════════════════════════
async function fetchMultiFactor() {
  multiFactorData.clear()
  // 通过 silentRefresh 触发，useCachedFetch 会重新拉取
  await multiFactorData.silentRefresh()
}

async function fetchLowAbsorption() {
  lowAbsData.clear()
  await lowAbsData.silentRefresh()
}

async function fetchMLStockPick() {
  mlData.clear()
  await mlData.silentRefresh()
}

async function fetchVolPriceDiv() {
  volPriceDivData.clear()
  await volPriceDivData.silentRefresh()
}

async function fetchComboVote() {
  comboData.clear()
  await comboData.silentRefresh()
}

async function fetchLeader() {
  leaderData.clear()
  await leaderData.silentRefresh()
}

function resetMultiFactorForm() { multiFactorForm.value = { count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true } }
function resetLowAbsForm() { lowAbsForm.value = { count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true } }
function resetMLForm() { mlForm.value = { count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true } }
function resetVolPriceDivForm() { volPriceDivForm.value = { count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true } }
function resetComboForm() { comboForm.value = { count: 20, market_cap: '', amount_filter: '', change_filter: '', exclude_st: true } }
function resetLeaderForm() { leaderForm.value = { top_n: 5, sector_count: 12, market_cap: '', amount_filter: '', exclude_st: true } }

function checkMobile() { isMobile.value = window.innerWidth <= 768 }
window.addEventListener('resize', checkMobile)

onMounted(() => {
  syncTabFromRoute()
  loadStrategyInfo()
  loadMLModelStatus()
  // useCachedFetch 模块自动处理初始加载和后台刷新，无需手动 timer
})
onBeforeUnmount(() => { window.removeEventListener('resize', checkMobile) })
onActivated(() => {
  syncTabFromRoute()
  // keep-alive 切回时触发当前 tab 模块刷新（useCachedFetch 内部也有 onActivated 处理）
  refreshActiveTab()
  loadMLModelStatus()
})


function formatReturn(val) {
  if (val == null) return '--'
  const num = parseFloat(val)
  const sign = num >= 0 ? '+' : ''
  return sign + num.toFixed(2) + '%'
}

</script>

<style scoped>
.smart-pick {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  padding: 12px;
  background: #f0f2f5;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  z-index: 1;
}

/* 移动端胶囊导航：桌面端隐藏 */
.mobile-tab-nav { display: none !important; }

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

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  flex-wrap: wrap;
  gap: 8px;
  flex-shrink: 0;
}
.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #303133;
  font-size: 20px;
  margin: 0;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.update-time { color: #909399; font-size: 13px; }
.header-divider { color: #dcdfe6; margin: 0 8px; }
.cache-badge { margin-left: 4px; }

/* Tabs layout — flex:1 填满剩余空间，min-height:0 允许子元素收缩 */
.smart-pick .el-tabs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.smart-pick :deep(.el-tabs__header) { flex-shrink: 0; }
.smart-pick :deep(.el-tabs__content) {
  flex: 1;
  display: flex !important;
  flex-direction: column !important;
  min-height: 0;
  padding: 0 !important;
}

/* 主 tabs 的 pane：非激活隐藏，激活占满。
   Element Plus 用 style="display: none;" 隐藏非激活 pane，激活 pane 无 inline style。 */
.smart-pick :deep(.el-tabs__content > .el-tab-pane) {
  display: none !important;
}
.smart-pick :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) {
  display: flex !important;
  flex-direction: column !important;
  flex: 1;
  min-height: 0;
}

/* Tab pane content — flex column，让 table-section 能 flex:1 自适应 */
.tab-pane-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

/* Sub tabs (rank, flow, combo) */
.rank-sub-tabs {
  margin-top: 4px;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.rank-sub-tabs :deep(.el-tabs) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.rank-sub-tabs :deep(.el-tabs__header) { margin-bottom: 0; flex-shrink: 0; }
.rank-sub-tabs :deep(.el-tabs__header .el-tabs__nav) { border-bottom: none; }
.rank-sub-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.rank-sub-tabs :deep(.el-tabs__content > .el-tab-pane) {
  display: none !important;
}
.rank-sub-tabs :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) {
  display: flex !important;
  flex-direction: column !important;
  flex: 1;
  min-height: 0;
}
.rank-tab-label { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; font-weight: 500; }
.rank-tab-label .el-tag { font-size: 11px; }

/* Toolbar */
.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  flex-shrink: 0;
}
.toolbar-info { color: #909399; font-size: 13px; }
.dragon-date-hint { color: #e6a23c; font-size: 12px; margin-left: 6px; }

/* Filter bar */
.stock-filter-bar {
  margin-top: 8px;
  margin-bottom: 10px;
  padding: 10px 14px;
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  flex-shrink: 0;
}
.filter-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.filter-label { font-size: 13px; color: #606266; white-space: nowrap; }

/* Table section — flex:1 自适应高度，overflow:hidden，分页在下方固定 */
.table-section {
  width: 100%;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
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

/* 表头背景色 */
.table-section :deep(.el-table__header-wrapper th.el-table__cell),
.table-scroll-wrapper :deep(.el-table__header-wrapper th.el-table__cell) {
  background-color: #f5f7fa !important;
}

/* Table cell styles — 内容不换行 */
:deep(.el-table) { --el-table-header-bg-color: #f5f7fa; --el-table-header-text-color: #303133; }
:deep(.el-table .cell) { white-space: nowrap !important; overflow: hidden; text-overflow: ellipsis; }
:deep(.el-table th.el-table__cell) { font-weight: 600; background-color: #f5f7fa; white-space: nowrap !important; }
:deep(.el-table td.el-table__cell) { vertical-align: middle; }

/* Row colors */
:deep(.limit-up-row td.el-table__cell) { background-color: #fef0f0 !important; }
:deep(.limit-down-row td.el-table__cell) { background-color: #f0f9eb !important; }
:deep(.clickable-row) { cursor: pointer; }
:deep(.clickable-row):active td { background-color: #f0f7ff !important; }

/* Progress bar + score in table cells */
.score-cell { display: flex; align-items: center; gap: 6px; justify-content: center; }
.score-cell .score-bar { width: 44px; flex-shrink: 0; }
.score-cell .score-text { font-size: 12px; white-space: nowrap; color: #606266; font-weight: 600; }
:deep(.el-table .el-button) { padding: 0 4px; font-size: 12px; }

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

/* ===== 龙头选股卡片网格 ===== */
.leader-cards-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 4px 2px 8px;
}
.leader-cards-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.leader-card {
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  overflow: hidden;
  min-width: 0;
}
.leader-card-header {
  padding: 8px 10px;
  background: linear-gradient(135deg, #f5f7fa 0%, #fafafa 100%);
  border-bottom: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sector-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.sector-rank {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 20px;
  padding: 0 4px;
  border-radius: 10px;
  background: linear-gradient(135deg, #409eff, #67c23a);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.sector-name-text {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}
.sector-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #606266;
  flex-wrap: wrap;
}
.sector-flow { font-weight: 500; }
.sector-strength { color: #67c23a; font-weight: 500; }
.sector-breadth { color: #909399; }
.leader-card .leader-table { width: 100% !important; }
.leader-card :deep(.el-table__inner-wrapper) { display: flex; flex-direction: column; }
.leader-card-reason {
  padding: 6px 10px;
  font-size: 12px;
  color: #909399;
  background: #fafafa;
  border-top: 1px dashed #ebeef5;
  line-height: 1.4;
  white-space: normal !important;
}

/* 平板两列 */
@media (max-width: 1279px) and (min-width: 769px) {
  .leader-cards-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
/* 手机单列堆叠 */
@media (max-width: 768px) {
  .leader-cards-grid { grid-template-columns: 1fr; gap: 8px; }
  .leader-card-header { padding: 6px 8px; gap: 2px; }
  .sector-title { gap: 4px; }
  .sector-rank { min-width: 22px; height: 18px; font-size: 10px; padding: 0 3px; }
  .sector-name-text { font-size: 13px; }
  .sector-meta { gap: 4px 6px; font-size: 11px; row-gap: 2px; }
  .leader-cards-wrap { padding: 2px 0 6px; }
  .leader-card :deep(.el-table th.el-table__cell),
  .leader-card :deep(.el-table td.el-table__cell) { padding: 4px 2px !important; font-size: 12px !important; }
  .leader-card :deep(.el-table th.el-table__cell .cell),
  .leader-card :deep(.el-table td.el-table__cell .cell) { padding: 0 2px !important; }
  .leader-card-reason { padding: 4px 8px; font-size: 11px; }
  /* 手机端表格列宽更紧凑 */
  .leader-card :deep(.el-table) { min-width: 0 !important; }
  /* 龙头分进度条在手机端缩小 */
  .leader-card .score-cell .score-bar { width: 30px; }
  .leader-card .score-cell .score-text { font-size: 11px; }
}

/* Color classes */
.c-red { color: #f56c6c !important; font-weight: 600; }
.c-green { color: #67c23a !important; font-weight: 600; }
.change-big { font-size: 14px; white-space: nowrap !important; }
.text-muted { color: #909399; }

/* Backtest inline display */
.bt-inline-tag {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  margin-right: 4px;
}
.bt-good { background: #fde2e2; color: #f56c6c; }
.bt-mid { background: #fdf6ec; color: #e6a23c; }
.bt-bad { background: #e8f8e5; color: #67c23a; }
.bt-inline-text {
  font-size: 11px;
  color: #909399;
  margin-left: 4px;
}

.rank-badge {
  width: 24px; height: 24px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 12px; background: #f0f2f5; color: #909399;
}
.rank-badge.top3 { background: linear-gradient(135deg, #f56c6c, #e6a23c); color: #fff; }

.stock-name-link { color: #409eff; cursor: pointer; text-decoration: none; font-weight: 500; white-space: nowrap !important; transition: all 0.2s; -webkit-tap-highlight-color: transparent; }
.stock-name-link:hover { text-decoration: underline; }
.stock-name-link:active { opacity: 0.6; transform: scale(0.98); }

/* Mobile responsive */
@media (max-width: 768px) {
  /* app-main padding accounts for header height + safe area */
  .smart-pick { top: 0; left: 0; right: 0; bottom: 0; padding: 4px !important; }

  /* 移动端 Header：显示新样式，隐藏桌面端 */
  .page-header { display: none !important; }
  .m-page-header { display: block !important; margin-bottom: 6px; }

  /* Tabs 外层 overflow:hidden 会裁剪分页，移动端改为 visible */
  :deep(.el-tabs--border-card) { overflow: visible !important; }

  /* 隐藏原生 el-tabs 头部，用自定义胶囊导航替代 */
  :deep(.dragon-tabs > .el-tabs__header) { display: none !important; }

  /* 移动端 el-tabs 容器去掉边框（与胶囊导航融合） */
  :deep(.dragon-tabs.el-tabs--border-card) {
    border: none !important;
    border-radius: var(--m-card-radius, 16px) !important;
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06)) !important;
  }

  :deep(.dragon-tabs > .el-tabs__content) { padding: 0 !important; }
  :deep(.dragon-tabs > .el-tabs__content > .el-tab-pane) { padding: 12px !important; }

  /* ========== 移动端胶囊导航 ========== */
  .mobile-tab-nav {
    display: block !important;
    background: var(--m-surface, #fff);
    border-radius: var(--m-card-radius, 16px);
    box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06));
    margin-bottom: 8px;
    overflow: hidden;
  }

  .m-pill-scroll {
    display: flex;
    gap: 8px;
    padding: 10px 14px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    background: var(--m-surface, #fff);
  }

  .m-pill-scroll::-webkit-scrollbar { display: none; }

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

  .m-pill:active { transform: scale(0.96); }

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

  :deep(.el-tabs--border-card > .el-tabs__header) { background-color: #f5f7fa !important; }
  :deep(.el-tabs__header) { margin-bottom: 0; overflow-x: auto; -webkit-overflow-scrolling: touch; white-space: nowrap; scrollbar-width: none; }
  :deep(.el-tabs__header::-webkit-scrollbar) { display: none; }
  :deep(.el-tabs__nav-wrap) { scrollbar-width: none; }
  :deep(.el-tabs__nav-wrap::-webkit-scrollbar) { display: none; }
  :deep(.el-tabs__nav-wrap::after) { height: 1px !important; }
  :deep(.el-tabs__item) { padding: 0 8px !important; font-size: 12px !important; height: 42px !important; line-height: 42px !important; flex-shrink: 0; }
  :deep(.el-tabs__active-bar) { height: 2px !important; }
  :deep(.el-tabs--border-card > .el-tabs__content) { padding: 8px 4px !important; overflow: visible !important; }

  /* Override desktop overflow:hidden on tabs content and active panes */
  .smart-pick :deep(.el-tabs__content) { overflow: visible !important; }
  .smart-pick :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) { overflow: visible !important; }

  .rank-tab-label { font-size: 12px !important; }
  .rank-sub-tabs :deep(.el-tabs__header) { margin-bottom: 0; }
  .rank-sub-tabs :deep(.el-tabs__content) { padding: 6px 0 !important; overflow: visible !important; }
  .rank-sub-tabs :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) { overflow: visible !important; }

  /* 策略说明横幅紧凑显示 */
  .strategy-info-banner { font-size: 11px !important; padding: 6px 8px !important; }
  .strategy-info-banner :deep(.el-tag) { font-size: 10px !important; }

  /* 筛选栏输入框缩小，避免过多换行 */
  .stock-filter-bar :deep(.el-input-number) { width: 85px !important; }
  .stock-filter-bar :deep(.el-select) { width: 95px !important; }
  .stock-filter-bar :deep(.el-button) { padding: 0 8px !important; font-size: 12px !important; }
  .stock-filter-bar :deep(.el-checkbox__label) { font-size: 12px !important; }
  .filter-row { gap: 6px; }
  .filter-label { font-size: 12px !important; }

  :deep(.el-table th.el-table__cell),
  :deep(.el-table td.el-table__cell) { padding: 6px 2px !important; font-size: 12px !important; }

  .table-toolbar { flex-wrap: wrap; gap: 4px; margin-bottom: 6px; align-items: flex-start; }
  .toolbar-info { font-size: 11px; width: 100%; }
  .table-toolbar :deep(.el-button) { padding: 0 8px !important; font-size: 12px !important; }

  /* Pagination — 紧靠底部导航栏，右对齐 */
  .pagination-wrapper {
    background: #fff !important;
    z-index: 10 !important;
    box-shadow: 0 -2px 6px rgba(0,0,0,0.06) !important;
    justify-content: flex-end;
    padding: 1px 4px calc(var(--m-tab-h, 52px) + env(safe-area-inset-bottom, 0)) !important;
    flex-shrink: 0;
    margin-top: 1px;
    min-height: 24px !important;
  }
  .pagination-wrapper :deep(.el-pagination) { font-size: 11px !important; flex-wrap: wrap; justify-content: flex-end; gap: 2px; }
  .pagination-wrapper :deep(.el-pager li) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; font-size: 11px !important; }
  .pagination-wrapper :deep(.el-pagination button) { min-width: 22px !important; height: 22px !important; line-height: 22px !important; }

  .rank-badge { width: 18px; height: 18px; font-size: 10px; }
  .change-big { font-size: 12px !important; }

  :deep(.el-button) { min-height: 34px; }
  :deep(.el-button--small) { min-height: 30px; }
  :deep(.el-empty) { padding: 20px 0 !important; }
  :deep(.el-empty__image) { height: 60px !important; }

  /* ===== 表格横向滚动优化 ===== */
  /* 表格容器占满视口宽度；内部 table 按列宽展开，超出 body-wrapper 时产生横向滚动 */
  .table-section :deep(.el-table),
  .table-scroll-wrapper :deep(.el-table) {
    min-width: 0 !important;
    width: 100% !important;
    max-width: none !important;
  }

  /* 内部 table 使用固定布局并按内容撑开，保证表头表体列对齐 */
  .table-section :deep(.el-table__header-wrapper > table),
  .table-section :deep(.el-table__body-wrapper > table),
  .table-section :deep(.el-table__footer-wrapper > table),
  .table-section :deep(.el-scrollbar__wrap > table),
  .table-section :deep(.el-scrollbar__view > table),
  .table-section :deep(.el-table__inner-wrapper > table),
  .table-scroll-wrapper :deep(.el-table__header-wrapper > table),
  .table-scroll-wrapper :deep(.el-table__body-wrapper > table),
  .table-scroll-wrapper :deep(.el-table__footer-wrapper > table),
  .table-scroll-wrapper :deep(.el-scrollbar__wrap > table),
  .table-scroll-wrapper :deep(.el-scrollbar__view > table),
  .table-scroll-wrapper :deep(.el-table__inner-wrapper > table) {
    width: max-content !important;
    min-width: 100% !important;
    max-width: none !important;
    table-layout: fixed !important;
    flex-shrink: 0 !important;
  }

  /* 表格内部横向滚动容器开启触摸滑动 */
  .table-section :deep(.el-table__body-wrapper),
  .table-section :deep(.el-scrollbar__wrap),
  .table-scroll-wrapper :deep(.el-table__body-wrapper),
  .table-scroll-wrapper :deep(.el-scrollbar__wrap) {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch !important;
  }

  /* 单元格紧凑显示，提升小屏信息密度 */
  :deep(.el-table .cell) { font-size: 11px !important; padding: 0 2px !important; }
  :deep(.el-table th.el-table__cell) { font-size: 11px !important; padding: 5px 2px !important; }
  :deep(.el-table td.el-table__cell) { padding: 4px 2px !important; }

  /* 固定列层级与阴影，确保左右滑动时固定列可见 */
  :deep(.el-table__fixed),
  :deep(.el-table__fixed-right) { z-index: 10 !important; }
  :deep(.el-table__fixed) { box-shadow: 2px 0 6px rgba(0,0,0,0.08) !important; }
  :deep(.el-table__fixed-right) { box-shadow: -2px 0 6px rgba(0,0,0,0.08) !important; }
}

@media (max-width: 480px) {
  .smart-pick { top: 0; left: 0; right: 0; bottom: 0; }
  .page-title { font-size: 14px !important; }
  :deep(.el-tabs__item) { padding: 0 6px !important; font-size: 11px !important; height: 38px !important; line-height: 38px !important; }
  .header-right { flex-direction: row; justify-content: flex-end; align-items: center; flex-wrap: nowrap; }
  .update-time { text-align: right; flex-shrink: 1; min-width: 0; }

  /* 超小屏进一步简化分页 */
  .pagination-wrapper :deep(.el-pagination__total),
  .pagination-wrapper :deep(.el-pagination__sizes),
  .pagination-wrapper :deep(.el-pagination__jump) { display: none !important; }

  /* 超小屏筛选栏更紧凑 */
  .stock-filter-bar :deep(.el-input-number) { width: 75px !important; }
  .stock-filter-bar :deep(.el-select) { width: 86px !important; }
  .stock-filter-bar :deep(.el-button) { padding: 0 6px !important; font-size: 11px !important; }
  .filter-label { font-size: 11px !important; }

  :deep(.el-table .cell) { font-size: 10px !important; }
  :deep(.el-table th.el-table__cell),
  :deep(.el-table td.el-table__cell) { padding: 4px 1px !important; font-size: 10px !important; }

  .ml-status-banner { font-size: 11px !important; padding: 6px 8px !important; flex-wrap: wrap; }
}

/* ML模型状态栏 */
.ml-status-banner.status-loaded {
  background: linear-gradient(135deg, #f0f9eb, #e8f8e5);
  border: 1px solid #d9f7be;
  color: #67c23a;
}

.ml-status-banner.status-not-loaded {
  background: linear-gradient(135deg, #fdf6ec, #faecd8);
  border: 1px solid #f5dab1;
  color: #e6a23c;
}

.training-progress-banner {
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

/* Sub-tab switch fade animation */
.tab-fade-enter-active,
.tab-fade-leave-active {
  transition: opacity 0.2s ease;
}
.tab-fade-enter-from,
.tab-fade-leave-to {
  opacity: 0;
}

/* Sub-tab content flex layout — ensures table fills space and pagination shows */
.sub-tab-content {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

/* ═══ Mobile Card List Container ══════════════════════════════════ */
.mobile-card-list {
  display: none;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 8px;
}

@media (max-width: 768px) {
  /* Show mobile card list, hide desktop table sections */
  .mobile-card-list { display: flex !important; flex-direction: column !important; }
  .table-section { display: none !important; }

  /* Hide desktop-only filter bar, show compact version */
  .stock-filter-bar { display: none !important; }

  /* Mobile card list scrollable within tab pane — overflow visible to let pagination show */
  .tab-pane-content {
    overflow: visible !important;
    display: flex !important;
    flex-direction: column !important;
  }

  /* m-stock-card overrides for page-specific needs */
  .mobile-card-list .m-stock-card { margin-bottom: 8px; padding: 12px; }
  .mobile-card-list .m-stock-card .top-row { gap: 10px; }
  .mobile-card-list .m-stock-card .sname { font-size: 14px; }
  .mobile-card-list .m-stock-card .price-big { font-size: 16px; }
  .mobile-card-list .m-stock-card .meta { gap: 8px; margin-top: 4px; font-size: 11px; }
  .mobile-card-list .m-stock-card .tech-strip { gap: 8px; padding-top: 6px; margin-top: 6px; font-size: 10px; }

  /* Hide desktop strategy info banners on mobile */
  .strategy-info-banner { display: none !important; }

  /* ML status banner compact on mobile */
  .ml-status-banner { font-size: 11px !important; padding: 6px 8px !important; flex-wrap: wrap; gap: 4px; }
  .ml-status-banner :deep(.el-button) { margin-left: auto; flex-shrink: 0; }

  /* Training progress banner compact */
  .training-progress-banner { font-size: 11px !important; padding: 6px 8px !important; }

  /* Leader cards grid single column on mobile */
  .leader-cards-grid { grid-template-columns: 1fr !important; gap: 8px !important; }

  /* Leader card inner table compact on mobile */
  .leader-card :deep(.el-table th.el-table__cell),
  .leader-card :deep(.el-table td.el-table__cell) { padding: 4px 2px !important; font-size: 11px !important; }
  .leader-card :deep(.el-table th.el-table__cell .cell),
  .leader-card :deep(.el-table td.el-table__cell .cell) { padding: 0 2px !important; }

  /* Pagination compact on mobile */
  .pagination-wrapper :deep(.el-pagination__total),
  .pagination-wrapper :deep(.el-pagination__sizes) { display: none !important; }
}

@media (max-width: 480px) {
  .mobile-card-list .m-stock-card { padding: 10px; margin-bottom: 6px; }
  .mobile-card-list .m-stock-card .sname { font-size: 13px; }
  .mobile-card-list .m-stock-card .price-big { font-size: 15px; }
}

</style>
