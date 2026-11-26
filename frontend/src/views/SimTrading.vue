<template>
  <div class="sim-trading">
    <div class="page-header">
      <h2 class="page-title"><el-icon><Money /></el-icon> AI模拟交易</h2>
      <div class="header-right">
        <el-tooltip :content="authStore.isAdmin ? '清空所有数据并重置账户' : '仅管理员可操作'" placement="bottom">
          <el-button type="danger" :disabled="!authStore.isAdmin" @click="resetAccount" :loading="resetting">
            <el-icon><RefreshRight /></el-icon> 重置账户
          </el-button>
        </el-tooltip>
        <el-dropdown trigger="click" v-if="authStore.isAdmin" @command="handleStrategyCommand">
          <el-button type="primary" :loading="generating">
            <el-icon><MagicStick /></el-icon> AI策略生成 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="intraday" :disabled="!isTradingTime">
                <span style="color: #409eff;">盘中即时策略</span>
                <el-tag size="small" type="info" style="margin-left: 8px;">实时行情</el-tag>
              </el-dropdown-item>
              <el-dropdown-item command="midday">
                <span style="color: #67c23a;">午间策略调整</span>
                <el-tag size="small" type="success" style="margin-left: 8px;">总结上午</el-tag>
              </el-dropdown-item>
              <el-dropdown-item command="next_day">
                <span style="color: #e6a23c;">收盘次日策略</span>
                <el-tag size="small" type="warning" style="margin-left: 8px;">收盘数据</el-tag>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-tooltip v-else :content="'仅管理员可操作'" placement="bottom">
          <el-button type="primary" disabled>
            <el-icon><MagicStick /></el-icon> AI策略生成
          </el-button>
        </el-tooltip>
        <el-button @click="refreshData" :loading="refreshing">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <!-- 账户概览 + 统计卡片 -->
    <!-- 移动端：m-stats-row 设计系统布局（2行3列）-->
    <template v-if="isMobile">
      <div class="m-stats-row" style="grid-template-columns: repeat(3, 1fr);">
        <div class="m-stat-card"><div class="val accent">¥{{ formatMoney(account.total_assets) }}</div><div class="lbl">总资产</div></div>
        <div class="m-stat-card"><div class="val">¥{{ formatMoney(account.current_capital) }}</div><div class="lbl">可用资金</div></div>
        <div class="m-stat-card"><div class="val" :class="account.total_profit >= 0 ? 'up' : 'down'">{{ account.total_profit >= 0 ? '+' : '' }}¥{{ formatMoney(account.total_profit) }}</div><div class="lbl">总盈亏</div></div>
      </div>
      <div class="m-stats-row" style="grid-template-columns: repeat(3, 1fr); margin-top: -6px;">
        <div class="m-stat-card"><div class="val" :class="account.total_profit_ratio >= 0 ? 'up' : 'down'">{{ account.total_profit_ratio >= 0 ? '+' : '' }}{{ (account.total_profit_ratio || 0).toFixed(2) }}%</div><div class="lbl">收益率</div></div>
        <div class="m-stat-card"><div class="val accent">{{ stats.win_rate != null ? stats.win_rate.toFixed(1) + '%' : '--' }}</div><div class="lbl">胜率</div></div>
        <div class="m-stat-card"><div class="val down">{{ (stats.max_drawdown || 0).toFixed(2) }}%</div><div class="lbl">最大回撤</div></div>
      </div>
    </template>
    <!-- 桌面端：el-row + el-col 布局 -->
    <template v-else>
    <el-row :gutter="8" class="stats-row">
      <el-col :xs="8" :sm="8" :md="6" :lg="4" :xl="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <div class="stat-label">总资产</div>
            <div class="stat-value">¥{{ formatMoney(account.total_assets) }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="8" :sm="8" :md="6" :lg="4" :xl="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <div class="stat-label">可用资金</div>
            <div class="stat-value">¥{{ formatMoney(account.current_capital) }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="8" :sm="8" :md="6" :lg="4" :xl="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <div class="stat-label">总盈亏</div>
            <div class="stat-value" :class="account.total_profit >= 0 ? 'profit' : 'loss'">
              {{ account.total_profit >= 0 ? '+' : '' }}¥{{ formatMoney(account.total_profit) }}
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="8" :sm="8" :md="6" :lg="4" :xl="4">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <div class="stat-label">收益率</div>
            <div class="stat-value" :class="account.total_profit_ratio >= 0 ? 'profit' : 'loss'">
              {{ account.total_profit_ratio >= 0 ? '+' : '' }}{{ (account.total_profit_ratio || 0).toFixed(2) }}%
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="8" :sm="8" :md="8" :lg="4" :xl="4">
        <el-card shadow="hover" class="stat-card small">
          <div class="stat-content">
            <div class="stat-label">胜率</div>
            <div class="stat-value">{{ stats.win_rate != null ? stats.win_rate.toFixed(1) + '%' : '--' }}</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="8" :sm="8" :md="8" :lg="4" :xl="4">
        <el-card shadow="hover" class="stat-card small">
          <div class="stat-content">
            <div class="stat-label">最大回撤</div>
            <div class="stat-value loss">{{ (stats.max_drawdown || 0).toFixed(2) }}%</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
    </template>

    <!-- 主要内容区 -->
    <el-tabs v-model="activeTab" type="border-card" class="main-tabs">
      
      <!-- 持仓管理 -->
      <el-tab-pane label="持仓管理" name="positions">
        <div class="tab-pane-content">
        <div class="tab-toolbar">
          <el-tooltip :content="authStore.isAdmin ? '手动买入股票' : '仅管理员可操作'" placement="top">
            <el-button size="small" type="primary" :disabled="!authStore.isAdmin" @click="showBuyDialog">买入</el-button>
          </el-tooltip>
          <el-tooltip :content="authStore.isAdmin ? '手动卖出股票' : '仅管理员可操作'" placement="top">
            <el-button size="small" type="danger" :disabled="!authStore.isAdmin" @click="showSellDialog">卖出</el-button>
          </el-tooltip>
        </div>

        <!-- 移动端卡片布局：m-card + m-stock-row 设计系统 -->
        <template v-if="isMobile">
          <div class="mobile-card-list" v-loading="loading">
            <div v-for="(row, idx) in pagedPositions" :key="idx" class="m-card sim-m-pos-card">
              <div class="m-stock-row" style="padding: 8px 0 6px; border-bottom: 1px solid var(--m-border);">
                <div class="info">
                  <div class="sname">{{ row.stock_name }}</div>
                  <div class="scode">{{ row.stock_code }} · {{ getPositionLabel(row.position_type) }}</div>
                </div>
                <el-tag :type="getPositionType(row.position_type)" size="small">{{ getPositionLabel(row.position_type) }}</el-tag>
              </div>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; padding:8px 0; font-size:12px;">
                <div><span class="m-text-muted">现价</span> <span style="font-weight:600;">¥{{ (row.current_price || 0).toFixed(2) }}</span></div>
                <div><span class="m-text-muted">成本</span> <span style="font-weight:600;">¥{{ (row.cost_price || 0).toFixed(2) }}</span></div>
                <div><span class="m-text-muted">持仓</span> <span>{{ row.total_quantity }}</span></div>
                <div><span class="m-text-muted">可卖</span> <span>{{ row.available_quantity }}</span></div>
              </div>
              <div style="display:flex; justify-content:center; gap:16px; padding:8px 0 4px; border-top:1px dashed var(--m-border); font-size:13px;">
                <span :class="row.profit >= 0 ? 'm-text-up' : 'm-text-down'" style="font-weight:700;">{{ row.profit >= 0 ? '+' : '' }}¥{{ formatMoney(row.profit) }}</span>
                <span :class="row.profit_ratio >= 0 ? 'm-text-up' : 'm-text-down'" style="font-weight:600;">({{ row.profit_ratio >= 0 ? '+' : '' }}{{ (row.profit_ratio || 0).toFixed(2) }}%)</span>
              </div>
              <div class="m-status-bar" style="padding:4px 0 0;"><span>{{ row.buy_date }}</span></div>
            </div>
          </div>
        </template>

        <!-- 桌面端表格 -->
        <div class="table-section" v-else>
        <el-table :data="pagedPositions" size="small" height="100%" border v-loading="loading" class="nowrap-table">
          <el-table-column prop="stock_code" label="代码" width="90" />
          <el-table-column prop="stock_name" label="名称" min-width="85" show-overflow-tooltip />
          <el-table-column prop="total_quantity" label="持仓数量" width="100" align="right" />
          <el-table-column prop="available_quantity" label="可卖数量" width="100" align="right" />
          <el-table-column prop="cost_price" label="成本价" width="95" align="right">
            <template #default="{ row }">¥{{ (row.cost_price || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="current_price" label="现价" width="95" align="right">
            <template #default="{ row }">¥{{ (row.current_price || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="market_value" label="市值" width="130" align="right">
            <template #default="{ row }">¥{{ formatMoney(row.market_value) }}</template>
          </el-table-column>
          <el-table-column prop="profit" label="盈亏" width="135" align="right">
            <template #default="{ row }">
              <span :class="row.profit >= 0 ? 'profit' : 'loss'">
                {{ row.profit >= 0 ? '+' : '' }}¥{{ formatMoney(row.profit) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="profit_ratio" label="盈亏率" width="95" align="right">
            <template #default="{ row }">
              <span :class="row.profit_ratio >= 0 ? 'profit' : 'loss'">
                {{ row.profit_ratio >= 0 ? '+' : '' }}{{ (row.profit_ratio || 0).toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="position_type" label="类型" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="getPositionType(row.position_type)" size="small">
                {{ getPositionLabel(row.position_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="buy_date" label="买入日期" width="110" />
        </el-table>
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="positionsPage"
            :page-size="PAGE_SIZE"
            :total="positions.length"
            layout="total, prev, pager, next"
            small
            background
          />
        </div>
        </div>
      </el-tab-pane>

      <!-- 委托管理 -->
      <el-tab-pane label="委托管理" name="orders">
        <div class="tab-pane-content">
        <div class="tab-toolbar">
          <el-tooltip :content="authStore.isAdmin ? '创建新的买卖委托' : '仅管理员可操作'" placement="top">
            <el-button size="small" type="primary" :disabled="!authStore.isAdmin" @click="showOrderDialog">创建委托</el-button>
          </el-tooltip>
          <el-tooltip :content="authStore.isAdmin ? '按当前行情立即撮合所有待成交委托（含非交易时段）' : '仅管理员可操作'" placement="top">
            <el-button size="small" type="success" :disabled="!authStore.isAdmin" :loading="matching" @click="matchOrders">立即撮合</el-button>
          </el-tooltip>
          <el-checkbox v-model="ordersTodayOnly" @change="loadOrders" style="margin-left: 12px;">
            仅显示今日
          </el-checkbox>
          <el-button size="small" @click="loadOrders" style="margin-left: auto;">刷新</el-button>
        </div>

        <!-- 移动端卡片布局：m-card + m-stock-row 设计系统 -->
        <template v-if="isMobile">
          <div class="mobile-card-list" v-loading="loading">
            <div v-for="(row, idx) in pagedOrders" :key="idx" class="m-card sim-m-order-card">
              <div class="m-stock-row" style="padding: 8px 0 6px; border-bottom: 1px solid var(--m-border);">
                <div class="info">
                  <div class="sname">{{ row.stock_name }}</div>
                  <div class="scode">{{ row.stock_code }}</div>
                </div>
                <el-tag :type="row.order_type === 'buy' ? 'primary' : 'danger'" size="small">{{ row.order_type === 'buy' ? '买入' : '卖出' }}</el-tag>
              </div>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; padding:8px 0; font-size:12px;">
                <div><span class="m-text-muted">委托价</span> <span style="font-weight:600;">¥{{ (row.order_price || 0).toFixed(2) }}</span></div>
                <div><span class="m-text-muted">现价</span> <span :style="{ fontWeight: 600, color: priceHintColor(row) }">{{ row.current_price != null ? '¥' + row.current_price.toFixed(2) : '-' }}</span></div>
                <div><span class="m-text-muted">数量</span> <span>{{ row.order_quantity }}</span></div>
                <div><span class="m-text-muted">已成交</span> <span>{{ row.filled_quantity }}/{{ row.order_quantity }}</span></div>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; padding-top:6px; border-top:1px solid var(--m-surface2);">
                <el-tag :type="getOrderStatusType(row.order_status)" size="small">{{ getOrderStatusLabel(row.order_status) }}</el-tag>
                <template v-if="row.order_status === 'pending' && authStore.isAdmin">
                  <el-button type="danger" size="small" link @click="cancelOrder(row.order_id)">撤单</el-button>
                </template>
              </div>
              <div class="m-status-bar" style="padding:4px 0 0;"><span>{{ row.create_time }}</span></div>
            </div>
          </div>
        </template>

        <!-- 桌面端表格 -->
        <div class="table-section" v-else>
        <el-table :data="pagedOrders" size="small" height="100%" border v-loading="loading" class="nowrap-table">
          <el-table-column prop="order_id" label="委托ID" width="85" />
          <el-table-column prop="stock_code" label="股票代码" width="90" />
          <el-table-column prop="stock_name" label="股票名称" min-width="85" show-overflow-tooltip />
          <el-table-column prop="order_type" label="委托类型" width="85" align="center">
            <template #default="{ row }">
              <el-tag :type="row.order_type === 'buy' ? 'primary' : 'danger'" size="small">
                {{ row.order_type === 'buy' ? '买入' : '卖出' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="order_price" label="委托价格" width="95" align="right">
            <template #default="{ row }">¥{{ (row.order_price || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="现价" width="95" align="right">
            <template #default="{ row }">
              <span :style="{ color: priceHintColor(row) }">¥{{ (row.current_price || 0).toFixed(2) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="order_quantity" label="委托数量" width="95" align="right" />
          <el-table-column prop="filled_quantity" label="已成交数量" width="110" align="right" />
          <el-table-column prop="order_status" label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="getOrderStatusType(row.order_status)" size="small">
                {{ getOrderStatusLabel(row.order_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="create_time" label="创建时间" min-width="150" align="center">
            <template #default="{ row }">
              <span style="white-space: nowrap;">{{ row.create_time }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center" fixed="right">
            <template #default="{ row }">
              <div style="white-space: nowrap; display: flex; align-items: center; justify-content: center; gap: 4px;">
                <el-tooltip v-if="row.order_status === 'pending'" :content="authStore.isAdmin ? '撤销该委托单' : '仅管理员可操作'" placement="top">
                  <el-button
                    type="danger"
                    size="small"
                    link
                    :disabled="!authStore.isAdmin"
                    @click="cancelOrder(row.order_id)"
                  >
                    撤单
                  </el-button>
                </el-tooltip>
                <el-popconfirm v-if="authStore.isAdmin" title="确定删除该委托记录？此操作不可恢复。" @confirm="deleteOrder(row.order_id)">
                  <template #reference>
                    <el-button type="info" size="small" link>删除</el-button>
                  </template>
                </el-popconfirm>
              </div>
            </template>
          </el-table-column>
        </el-table>
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="ordersPage"
            :page-size="PAGE_SIZE"
            :total="orders.length"
            layout="total, prev, pager, next"
            small
            background
          />
        </div>
        </div>
      </el-tab-pane>

      <!-- 交易记录 -->
      <el-tab-pane label="交易记录" name="trades">
        <div class="tab-pane-content">
        <div class="tab-toolbar">
          <el-radio-group v-model="tradeFilter" size="small">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="buy">买入</el-radio-button>
            <el-radio-button label="sell">卖出</el-radio-button>
          </el-radio-group>
        </div>

        <!-- 移动端卡片布局：m-card + m-stock-row 设计系统 -->
        <template v-if="isMobile">
          <div class="mobile-card-list" v-loading="loading">
            <div v-for="(row, idx) in pagedTrades" :key="idx" class="m-card sim-m-trade-card">
              <div class="m-stock-row" style="padding: 8px 0 6px; border-bottom: 1px solid var(--m-border);">
                <div class="info">
                  <div class="sname">{{ row.stock_name }}</div>
                  <div class="scode">{{ row.stock_code }} · {{ row.trade_date }} {{ row.trade_time }}</div>
                </div>
                <el-tag :type="row.trade_type === 'buy' ? 'primary' : 'danger'" size="small">{{ row.trade_type === 'buy' ? '买入' : '卖出' }}</el-tag>
              </div>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; padding:8px 0; font-size:12px;">
                <div><span class="m-text-muted">价格</span> <span style="font-weight:600;">¥{{ (row.trade_price || 0).toFixed(2) }}</span></div>
                <div><span class="m-text-muted">数量</span> <span>{{ row.trade_quantity }}</span></div>
                <div><span class="m-text-muted">金额</span> <span>¥{{ formatMoney(row.trade_amount) }}</span></div>
                <div style="text-align:right;">
                  <template v-if="row.profit !== null">
                    <span :class="row.profit >= 0 ? 'm-text-up' : 'm-text-down'" style="font-weight:700;">{{ row.profit >= 0 ? '+' : '' }}¥{{ formatMoney(row.profit) }}</span>
                  </template>
                  <span v-else class="m-text-muted">-</span>
                </div>
              </div>
              <div style="display:flex; gap:4px; padding-top:6px; border-top:1px solid var(--m-surface2); flex-wrap:wrap;">
                <el-tag v-if="row.strategy_name === 'auto_close_short'" type="warning" size="small" effect="dark">平短仓</el-tag>
                <el-tag v-if="row.position_type" :type="getPositionType(row.position_type)" size="small">{{ getPositionLabel(row.position_type) }}</el-tag>
              </div>
            </div>
          </div>
        </template>

        <!-- 桌面端表格 -->
        <div class="table-section" v-else>
        <el-table :data="pagedTrades" size="small" height="100%" border v-loading="loading" class="nowrap-table">
          <el-table-column prop="trade_date" label="日期" width="110" />
          <el-table-column prop="trade_time" label="时间" width="90" />
          <el-table-column prop="stock_code" label="代码" width="90" />
          <el-table-column prop="stock_name" label="名称" min-width="85" show-overflow-tooltip />
          <el-table-column prop="trade_type" label="类型" width="75" align="center">
            <template #default="{ row }">
              <el-tag :type="row.trade_type === 'buy' ? 'primary' : 'danger'" size="small">
                {{ row.trade_type === 'buy' ? '买入' : '卖出' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="trade_price" label="价格" width="95" align="right">
            <template #default="{ row }">¥{{ (row.trade_price || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="trade_quantity" label="数量" width="85" align="right" />
          <el-table-column prop="trade_amount" label="金额" width="130" align="right">
            <template #default="{ row }">¥{{ formatMoney(row.trade_amount) }}</template>
          </el-table-column>
          <el-table-column prop="profit" label="盈亏" width="85" align="right">
            <template #default="{ row }">
              <span v-if="row.profit !== null" :class="row.profit >= 0 ? 'profit' : 'loss'">
                {{ row.profit >= 0 ? '+' : '' }}¥{{ formatMoney(row.profit) }}
              </span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="strategy_name" label="策略" min-width="120" show-overflow-tooltip>
            <template #default="{ row }">
              <el-tag v-if="row.strategy_name === 'auto_close_short'" type="warning" size="small" effect="dark" style="margin-right:4px;">平短仓</el-tag>
              <span>{{ row.strategy_name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="position_type" label="仓位类型" width="85" align="center">
            <template #default="{ row }">
              <el-tag :type="getPositionType(row.position_type)" size="small">
                {{ getPositionLabel(row.position_type) }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="tradesPage"
            :page-size="PAGE_SIZE"
            :total="trades.length"
            layout="total, prev, pager, next"
            small
            background
          />
        </div>
        </div>
      </el-tab-pane>

      <!-- 做T记录 -->
      <el-tab-pane label="做T记录" name="tTrades">
        <div class="tab-pane-content">
        <!-- 做T统计卡片：移动端用 m-stats-row，桌面端用 ttrade-stats-bar -->
        <template v-if="isMobile">
          <div class="m-stats-row" style="grid-template-columns: repeat(3, 1fr);" v-loading="tTradeStatsLoading">
            <div class="m-stat-card"><div class="val accent">{{ tTradeStats.total || 0 }}</div><div class="lbl">累计做T</div></div>
            <div class="m-stat-card"><div class="val" :class="(tTradeStats.win_rate || 0) >= 50 ? 'up' : 'down'">{{ tTradeStats.win_rate || 0 }}%</div><div class="lbl">胜率</div></div>
            <div class="m-stat-card"><div class="val" :class="(tTradeStats.total_profit || 0) >= 0 ? 'up' : 'down'">{{ (tTradeStats.total_profit || 0) >= 0 ? '+' : '' }}¥{{ formatMoney(tTradeStats.total_profit || 0) }}</div><div class="lbl">累计降本</div></div>
          </div>
          <div class="m-stats-row" style="grid-template-columns: repeat(2, 1fr); margin-top:-4px;" v-loading="tTradeStatsLoading">
            <div class="m-stat-card"><div class="val" :class="(tTradeStats.avg_profit || 0) >= 0 ? 'up' : 'down'">{{ (tTradeStats.avg_profit || 0) >= 0 ? '+' : '' }}¥{{ formatMoney(tTradeStats.avg_profit || 0) }}</div><div class="lbl">单笔均值</div></div>
            <div class="m-stat-card"><div class="val accent">{{ tTradeStats.today_count || 0 }}次<span :class="(tTradeStats.today_profit || 0) >= 0 ? 'up' : 'down'" style="font-size:11px;margin-left:4px;">{{ (tTradeStats.today_profit || 0) >= 0 ? '+' : '' }}¥{{ formatMoney(tTradeStats.today_profit || 0) }}</span></div><div class="lbl">今日做T</div></div>
          </div>
        </template>
        <template v-else>
        <div class="ttrade-stats-bar" v-loading="tTradeStatsLoading">
          <div class="ttrade-stat-item">
            <div class="ttrade-stat-label">累计做T</div>
            <div class="ttrade-stat-value">{{ tTradeStats.total || 0 }} 次</div>
          </div>
          <div class="ttrade-stat-item">
            <div class="ttrade-stat-label">胜率</div>
            <div class="ttrade-stat-value" :class="(tTradeStats.win_rate || 0) >= 50 ? 'profit' : 'loss'">{{ tTradeStats.win_rate || 0 }}%</div>
          </div>
          <div class="ttrade-stat-item">
            <div class="ttrade-stat-label">累计降本</div>
            <div class="ttrade-stat-value" :class="(tTradeStats.total_profit || 0) >= 0 ? 'profit' : 'loss'">{{ (tTradeStats.total_profit || 0) >= 0 ? '+' : '' }}¥{{ formatMoney(tTradeStats.total_profit || 0) }}</div>
          </div>
          <div class="ttrade-stat-item">
            <div class="ttrade-stat-label">单笔均值</div>
            <div class="ttrade-stat-value" :class="(tTradeStats.avg_profit || 0) >= 0 ? 'profit' : 'loss'">{{ (tTradeStats.avg_profit || 0) >= 0 ? '+' : '' }}¥{{ formatMoney(tTradeStats.avg_profit || 0) }}</div>
          </div>
          <div class="ttrade-stat-item">
            <div class="ttrade-stat-label">今日做T</div>
            <div class="ttrade-stat-value">{{ tTradeStats.today_count || 0 }} 次 / <span :class="(tTradeStats.today_profit || 0) >= 0 ? 'profit' : 'loss'">{{ (tTradeStats.today_profit || 0) >= 0 ? '+' : '' }}¥{{ formatMoney(tTradeStats.today_profit || 0) }}</span></div>
          </div>
        </div>
        </template>

        <!-- 移动端卡片布局：m-card + m-stock-row 设计系统 -->
        <template v-if="isMobile">
          <div class="mobile-card-list" v-loading="loading">
            <div v-for="(row, idx) in pagedTTrades" :key="idx" class="m-card sim-m-ttrade-card">
              <div class="m-stock-row" style="padding: 8px 0 6px; border-bottom: 1px solid var(--m-border);">
                <div class="info">
                  <div class="sname">{{ row.stock_name }}</div>
                  <div class="scode">{{ row.stock_code }} · {{ row.create_time }}</div>
                </div>
                <el-tag :type="getTTradeStatusType(row.trade_status)" size="small">{{ getTTradeStatusLabel(row.trade_status) }}</el-tag>
              </div>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; padding:8px 0; font-size:12px;">
                <div><span class="m-text-muted">买入</span> <span style="font-weight:600;">¥{{ (row.buy_price || 0).toFixed(2) }}</span></div>
                <div><span class="m-text-muted">卖出</span> <span style="font-weight:600;">¥{{ (row.sell_price || 0).toFixed(2) }}</span></div>
                <div><span class="m-text-muted">数量</span> <span>{{ row.quantity }}</span></div>
                <div style="text-align:right;">
                  <template v-if="row.profit !== null">
                    <span :class="row.profit >= 0 ? 'm-text-up' : 'm-text-down'" style="font-weight:700;">{{ row.profit >= 0 ? '+' : '' }}¥{{ formatMoney(row.profit) }}</span>
                  </template>
                  <span v-else class="m-text-muted">-</span>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- 桌面端表格 -->
        <div class="table-section" v-else>
        <el-table :data="pagedTTrades" size="small" height="100%" border v-loading="loading">
          <el-table-column prop="trade_id" label="交易ID" width="100" />
          <el-table-column prop="stock_code" label="股票代码" width="100" />
          <el-table-column prop="stock_name" label="股票名称" min-width="100" show-overflow-tooltip />
          <el-table-column prop="buy_price" label="买入价格" width="90" align="right">
            <template #default="{ row }">¥{{ (row.buy_price || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="sell_price" label="卖出价格" width="90" align="right">
            <template #default="{ row }">¥{{ (row.sell_price || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="80" align="right" />
          <el-table-column prop="profit" label="盈亏" width="100" align="right">
            <template #default="{ row }">
              <span v-if="row.profit !== null" :class="row.profit >= 0 ? 'profit' : 'loss'">
                {{ row.profit >= 0 ? '+' : '' }}¥{{ formatMoney(row.profit) }}
              </span>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column prop="trade_status" label="状态" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="getTTradeStatusType(row.trade_status)" size="small">
                {{ getTTradeStatusLabel(row.trade_status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="create_time" label="创建时间" width="140" />
        </el-table>
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="tTradesPage"
            :page-size="PAGE_SIZE"
            :total="tTrades.length"
            layout="total, prev, pager, next"
            small
            background
          />
        </div>
        </div>
      </el-tab-pane>

      <!-- AI策略 -->
      <el-tab-pane label="AI策略" name="strategy">
        <div class="tab-pane-content strategy-panel" v-loading="generating">

          <!-- 移动端：策略配置 -->
          <template v-if="isMobile">
            <div class="strategy-scroll">
            <el-card class="config-card mob-config-card" shadow="never">
              <template #header>
                <div class="card-header">
                  <span style="font-size:14px;">策略配置参数</span>
                  <el-button text size="small" @click="configExpanded = !configExpanded">
                    {{ configExpanded ? '收起' : '展开' }}
                    <el-icon style="margin-left:2px;"><ArrowUp v-if="configExpanded" /><ArrowDown v-else /></el-icon>
                  </el-button>
                </div>
              </template>
              <div v-show="configExpanded" class="mob-config-list">
                <div class="mob-config-item mob-config-switch">
                  <span class="mob-config-label">参数限制</span>
                  <el-switch
                    v-model="strategyConfig.enforce_params"
                    active-text="按参数限制"
                    inactive-text="AI 自主"
                    inline-prompt
                    size="small"
                    :disabled="!authStore.isAdmin"
                  />
                </div>
                <div class="mob-config-grid">
                  <div class="mob-config-sub">
                    <span class="mob-config-label">单只最大仓位</span>
                    <el-input-number v-model="strategyConfig.max_single_position_ratio" :min="0.05" :max="0.5" :step="0.05" :precision="2" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" size="small" controls-position="right" />
                  </div>
                  <div class="mob-config-sub">
                    <span class="mob-config-label">总仓位上限</span>
                    <el-input-number v-model="strategyConfig.total_position_ratio" :min="0.1" :max="1.0" :step="0.05" :precision="2" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" size="small" controls-position="right" />
                  </div>
                  <div class="mob-config-sub">
                    <span class="mob-config-label">最小买入金额</span>
                    <el-input-number v-model="strategyConfig.min_buy_amount" :min="1000" :max="100000" :step="1000" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" size="small" controls-position="right" />
                  </div>
                  <div class="mob-config-sub">
                    <span class="mob-config-label">止损比例%</span>
                    <el-input-number v-model="strategyConfig.stop_loss_ratio" :min="1" :max="20" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" size="small" controls-position="right" />
                  </div>
                  <div class="mob-config-sub">
                    <span class="mob-config-label">止盈比例%</span>
                    <el-input-number v-model="strategyConfig.take_profit_ratio" :min="1" :max="50" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" size="small" controls-position="right" />
                  </div>
                </div>
              </div>
            </el-card>

            <!-- 移动端：最新策略摘要 -->
            <el-card v-if="currentStrategy && !currentStrategy.isFromHistory" class="strategy-summary-card mob-strategy-result" shadow="never">
              <div class="mob-summary-row">
                <div style="display:flex;align-items:center;gap:6px;">
                  <el-tag :type="getStrategyModeType(currentStrategy.mode)" size="small">
                    {{ getStrategyModeLabel(currentStrategy.mode) }}
                  </el-tag>
                  <span style="font-size:13px;font-weight:bold;">{{ currentStrategy.decision_date }}</span>
                </div>
                <div style="display:flex;gap:4px;">
                  <el-button size="small" type="primary" @click="viewCurrentStrategy">查看详情</el-button>
                  <template v-if="authStore.isAdmin && currentStrategy.mode !== 'next_day'">
                    <el-button type="success" size="small" @click="executeStrategy" :loading="executing">创建委托</el-button>
                  </template>
                </div>
              </div>
            </el-card>

            <!-- 移动端：策略历史卡片 -->
            <div class="m-section-header">策略历史</div>
            <div v-for="(row, idx) in strategyHistory" :key="'hist-'+idx" class="m-card sim-m-hist-card">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-size:13px;font-weight:600;color:var(--m-text);">{{ row.decision_date }}</span>
                <el-tag :type="getStrategyModeType(row.strategy_mode)" size="small">{{ getStrategyModeLabel(row.strategy_mode) }}</el-tag>
              </div>
              <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; color:var(--m-text2); margin-bottom:4px;">
                <el-tag :type="getStatusType(row.execution_status)" size="small">{{ getStatusLabel(row.execution_status) }}</el-tag>
                <span>买{{ row.buy_count }} / 卖{{ row.sell_count }}<template v-if="row.t_trade_count > 0"> / T<span style="color:var(--m-gold);font-weight:bold;">{{ row.t_trade_count }}</span></template></span>
              </div>
              <div style="display:flex; justify-content:space-between; font-size:11px; color:var(--m-text3); margin-bottom:2px;">
                <span>生成: {{ row.created_at || '-' }}</span>
              </div>
              <div style="font-size:11px; color:#67c23a; margin-bottom:6px;">
                <span v-if="row.executed_at">执行: {{ row.executed_at }}</span>
                <span v-else class="m-text-muted">尚未执行</span>
              </div>
              <div style="display:flex; justify-content:flex-end; gap:8px; padding-top:6px; border-top:1px solid var(--m-surface2);">
                <el-button size="small" link @click="viewStrategyHistory(row)">详情</el-button>
                <el-button v-if="authStore.isAdmin && (row.execution_status === 'pending' || row.execution_status === 'manual')" size="small" type="primary" link @click="executeHistoryStrategy(row)">执行</el-button>
                <el-button v-if="authStore.isAdmin" size="small" type="danger" link @click="confirmDeleteStrategy(row)">删除</el-button>
              </div>
            </div>
            </div>
          </template>

          <!-- 桌面端：策略配置 -->
            <template v-else>
              <div class="strategy-fixed">
              <el-card class="config-card" shadow="never">
                <template #header>
                  <div class="card-header">
                    <span>策略配置参数</span>
                    <el-button text size="small" @click="configExpanded = !configExpanded">
                      {{ configExpanded ? '收起' : '展开' }}
                      <el-icon style="margin-left:2px;"><ArrowUp v-if="configExpanded" /><ArrowDown v-else /></el-icon>
                    </el-button>
                  </div>
                </template>
                <el-form v-show="configExpanded" :model="strategyConfig" label-width="100px" size="small" class="strategy-form">
                  <el-row :gutter="16">
                    <el-col :xs="24" :sm="24" :md="24" :lg="24" :xl="24">
                      <el-form-item label="参数限制">
                        <el-switch
                          v-model="strategyConfig.enforce_params"
                          active-text="按参数限制"
                          inactive-text="AI 自主决策"
                          inline-prompt
                          :disabled="!authStore.isAdmin"
                          style="--el-switch-on-color: #409EFF; --el-switch-off-color: #67C23A;"
                        />
                        <el-tag v-if="strategyConfig.enforce_params" type="primary" size="small" effect="plain" style="margin-left: 8px;">
                          单只/总仓位/止损止盈/最小金额均受配置参数约束
                        </el-tag>
                        <el-tag v-else type="success" size="small" effect="plain" style="margin-left: 8px;">
                          AI 自主决定所有仓位/止损/止盈/单笔金额（仅受可用资金上限约束）
                        </el-tag>
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-row :gutter="16">
                    <el-col :xs="24" :sm="12" :md="6" :lg="6" :xl="6">
                      <el-form-item label="单只最大仓位">
                        <el-input-number v-model="strategyConfig.max_single_position_ratio" :min="0.05" :max="0.5" :step="0.05" :precision="2" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" style="width: 100%;" />
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :sm="12" :md="6" :lg="6" :xl="6">
                      <el-form-item label="总仓位上限">
                        <el-input-number v-model="strategyConfig.total_position_ratio" :min="0.1" :max="1.0" :step="0.05" :precision="2" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" style="width: 100%;" />
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :sm="12" :md="6" :lg="6" :xl="6">
                      <el-form-item label="止损比例(%)">
                        <el-input-number v-model="strategyConfig.stop_loss_ratio" :min="1" :max="20" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" style="width: 100%;" />
                      </el-form-item>
                    </el-col>
                    <el-col :xs="24" :sm="12" :md="6" :lg="6" :xl="6">
                      <el-form-item label="止盈比例(%)">
                        <el-input-number v-model="strategyConfig.take_profit_ratio" :min="1" :max="50" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" style="width: 100%;" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-row :gutter="16">
                    <el-col :xs="24" :sm="12" :md="12" :lg="12" :xl="12">
                      <el-form-item label="最小买入金额">
                        <el-input-number v-model="strategyConfig.min_buy_amount" :min="1000" :max="100000" :step="1000" :disabled="!strategyConfig.enforce_params || !authStore.isAdmin" style="width: 100%;" />
                      </el-form-item>
                    </el-col>
                  </el-row>
                </el-form>
              </el-card>

            <!-- 桌面端：最新策略摘要 -->
            <el-card v-if="currentStrategy && !currentStrategy.isFromHistory" class="strategy-summary-card" shadow="never">
              <div class="desktop-summary-row">
                <div style="display:flex;align-items:center;gap:10px;">
                  <el-tag :type="getStrategyModeType(currentStrategy.mode)" size="small">
                    {{ getStrategyModeLabel(currentStrategy.mode) }}
                  </el-tag>
                  <span style="font-weight:bold;">{{ currentStrategy.decision_date }}</span>
                  <el-tag :type="getSentimentType(currentStrategy.market_analysis?.sentiment)" size="small">
                    情绪: {{ getSentimentLabel(currentStrategy.market_analysis?.sentiment) }}
                  </el-tag>
                </div>
                <div style="display:flex;gap:8px;">
                  <el-button size="small" type="primary" @click="viewCurrentStrategy">查看详情</el-button>
                  <template v-if="authStore.isAdmin && currentStrategy.mode !== 'next_day'">
                    <el-tooltip content="执行 AI 策略：按买入/卖出列表市价单成交" placement="top">
                      <el-button type="success" size="small" :disabled="currentStrategy.execution_result?.skipped === 'non_trading_hours'" @click="executeStrategy" :loading="executing">
                        创建委托
                      </el-button>
                    </el-tooltip>
                  </template>
                </div>
              </div>
            </el-card>
            </div>

            <!-- 桌面端：策略历史 -->
            <div class="strategy-history-section">
              <div class="section-title">策略历史</div>
              <div class="table-section">
              <el-table :data="pagedStrategyHistory" size="small" height="100%" border :default-sort="{ prop: 'created_at', order: 'descending' }" @sort-change="handleStrategySort">
                <el-table-column prop="decision_date" label="日期" width="110">
                  <template #default="{ row }">
                    <span style="font-size: 12px; white-space: nowrap;">{{ row.decision_date }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="strategy_mode" label="类型" width="100" align="center">
                  <template #default="{ row }">
                    <el-tag :type="getStrategyModeType(row.strategy_mode)" size="small">
                      {{ getStrategyModeLabel(row.strategy_mode) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="market_sentiment" label="市场情绪" width="90" align="center">
                  <template #default="{ row }">
                    <el-tag :type="getSentimentType(row.market_sentiment)" size="small">
                      {{ getSentimentLabel(row.market_sentiment) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="仓位布局" width="140" align="center">
                  <template #default="{ row }">
                    <div v-if="row.short_term_ratio != null || row.mid_term_ratio != null || row.long_term_ratio != null" class="pos-layout-cell">
                      <span class="pos-chip pos-short" :title="`短线 ${row.short_term_ratio || 0}%`">短{{ row.short_term_ratio || 0 }}</span>
                      <span class="pos-chip pos-mid" :title="`中线 ${row.mid_term_ratio || 0}%`">中{{ row.mid_term_ratio || 0 }}</span>
                      <span class="pos-chip pos-long" :title="`长线 ${row.long_term_ratio || 0}%`">长{{ row.long_term_ratio || 0 }}</span>
                    </div>
                    <span v-else style="color:#909399;">—</span>
                  </template>
                </el-table-column>
                <el-table-column prop="buy_count" label="买入" width="70" align="center" />
                <el-table-column prop="sell_count" label="卖出" width="70" align="center" />
                <el-table-column prop="t_trade_count" label="做T" width="70" align="center">
                  <template #default="{ row }">
                    <el-tag v-if="row.t_trade_count > 0" type="warning" size="small">{{ row.t_trade_count }}</el-tag>
                    <span v-else style="color:#909399;">0</span>
                  </template>
                </el-table-column>
                <el-table-column prop="created_at" label="生成时间" width="160" align="center" sortable="custom">
                  <template #default="{ row }">
                    <span style="font-size: 12px; white-space: nowrap;">{{ row.created_at || '-' }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="executed_at" label="执行时间" width="160" align="center">
                  <template #default="{ row }">
                    <span style="font-size: 12px; color: #67c23a; white-space: nowrap;" v-if="row.executed_at">{{ row.executed_at }}</span>
                    <span style="color: #909399;" v-else>—</span>
                  </template>
                </el-table-column>
                <el-table-column prop="execution_status" label="状态" width="90" align="center">
                  <template #default="{ row }">
                    <el-tag :type="getStatusType(row.execution_status)" size="small">
                      {{ getStatusLabel(row.execution_status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="strategy_summary" label="摘要" min-width="200" show-overflow-tooltip />
                <el-table-column label="操作" width="180" align="center" fixed="right">
                  <template #default="{ row }">
                    <el-button size="small" link @click="viewStrategyHistory(row)">查看</el-button>
                    <el-button v-if="authStore.isAdmin && (row.execution_status === 'pending' || row.execution_status === 'manual')" size="small" type="primary" link @click="executeHistoryStrategy(row)">执行</el-button>
                    <el-popconfirm v-if="authStore.isAdmin" :title="`确定删除该策略？\n日期: ${row.decision_date}\n类型: ${getStrategyModeLabel(row.strategy_mode)}`" @confirm="deleteStrategy(row)">
                      <template #reference>
                        <el-button size="small" type="danger" link>删除</el-button>
                      </template>
                    </el-popconfirm>
                  </template>
                </el-table-column>
              </el-table>
              </div>
              <div class="pagination-bar">
                <el-pagination
                  v-model:current-page="strategyHistoryPage"
                  :page-size="PAGE_SIZE"
                  :total="strategyHistory.length"
                  layout="total, prev, pager, next"
                  small
                  background
                />
              </div>
            </div>
          </template>

        <!-- 策略详情抽屉（共用，移动端全屏/桌面端65%） -->
        <el-drawer v-model="strategyDrawerVisible" :title="drawerTitle" :size="simDrawerSize" destroy-on-close class="sim-strategy-drawer">
          <template v-if="drawerStrategyData">
            <div class="market-analysis">
              <el-tag :type="getSentimentType(drawerStrategyData.market_analysis?.sentiment)" size="large">
                市场情绪: {{ getSentimentLabel(drawerStrategyData.market_analysis?.sentiment) }}
              </el-tag>
              <el-tag v-if="drawerStrategyData.mode === 'next_day'" type="warning" size="small" style="margin-left:8px;">基于收盘数据生成</el-tag>
              <el-tag v-else type="success" size="small" style="margin-left:8px;">基于实时行情生成</el-tag>
            </div>

            <el-row :gutter="12" class="strategy-summary">
              <el-col :span="8"><div class="summary-item"><div class="summary-label">建议买入</div><div class="summary-value">{{ drawerStrategyData.buy_list?.length || 0 }} 只</div></div></el-col>
              <el-col :span="8"><div class="summary-item"><div class="summary-label">建议卖出</div><div class="summary-value">{{ drawerStrategyData.sell_signals?.length || 0 }} 只</div></div></el-col>
              <el-col :span="8"><div class="summary-item"><div class="summary-label">建议仓位</div><div class="summary-value">{{ drawerStrategyData.position_ratio || 70 }}%</div></div></el-col>
            </el-row>

            <!-- 买入列表 -->
            <div class="stock-list drawer-stock-list" v-if="drawerStrategyData.buy_list?.length">
              <h4>买入计划</h4>
              <el-table :data="drawerStrategyData.buy_list" size="small" border>
                <el-table-column prop="code" label="代码" width="100" />
                <el-table-column prop="name" label="名称" min-width="100" />
                <el-table-column prop="price" label="价格" width="90" align="right">
                  <template #default="{ row }">¥{{ row.price?.toFixed(2) || '--' }}</template>
                </el-table-column>
                <el-table-column prop="quantity" label="数量" width="80" align="center">
                  <template #default="{ row }">{{ row.quantity || '--' }}股</template>
                </el-table-column>
                <el-table-column prop="amount" label="金额" width="110" align="right">
                  <template #default="{ row }">¥{{ formatMoney(row.amount) }}</template>
                </el-table-column>
                <el-table-column prop="score" label="得分" width="80" align="center" />
                <el-table-column prop="position_type" label="类型" width="80" align="center">
                  <template #default="{ row }"><el-tag :type="getPositionType(row.position_type)" size="small">{{ getPositionLabel(row.position_type) }}</el-tag></template>
                </el-table-column>
                <el-table-column prop="reason" label="理由" min-width="150" show-overflow-tooltip />
              </el-table>
            </div>

            <!-- 卖出列表 -->
            <div class="stock-list drawer-stock-list" v-if="drawerStrategyData.sell_signals?.length">
              <h4>卖出计划</h4>
              <el-table :data="drawerStrategyData.sell_signals" size="small" border>
                <el-table-column prop="stock_code" label="代码" width="100" />
                <el-table-column prop="stock_name" label="名称" min-width="100" />
                <el-table-column prop="current_price" label="现价" width="90" align="right">
                  <template #default="{ row }">¥{{ (row.current_price || 0).toFixed(2) }}</template>
                </el-table-column>
                <el-table-column prop="profit_ratio" label="盈亏率" width="90" align="right">
                  <template #default="{ row }"><span :class="row.profit_ratio >= 0 ? 'profit' : 'loss'">{{ row.profit_ratio >= 0 ? '+' : '' }}{{ (row.profit_ratio || 0).toFixed(2) }}%</span></template>
                </el-table-column>
                <el-table-column prop="sell_reason" label="理由" min-width="150" show-overflow-tooltip />
              </el-table>
            </div>

            <!-- 策略报告 -->
            <el-card v-if="drawerStrategyData.strategy_summary" class="strategy-report" shadow="never">
              <template #header><span>策略报告</span></template>
              <pre class="report-content">{{ drawerStrategyData.strategy_summary }}</pre>
            </el-card>

            <!-- 操作按钮 -->
            <div v-if="!drawerStrategyData.isFromHistory && authStore.isAdmin && drawerStrategyData.mode !== 'next_day'" style="text-align:center;margin-top:16px;">
              <el-button type="success" @click="executeStrategy" :loading="executing">创建委托</el-button>
            </div>
          </template>
        </el-drawer>
      </div>
      </el-tab-pane>

      <!-- 盈亏分析 -->
      <el-tab-pane label="盈亏分析" name="analysis" v-loading="loading">
        <div class="tab-pane-content analysis-panel">
        <el-row :gutter="16">
          <!-- 胜率统计 -->
          <el-col :xs="24" :sm="24" :md="12" :lg="12" :xl="12">
            <el-card shadow="never" style="margin-bottom: 8px;">
              <template #header>
                <span>胜率统计</span>
              </template>
              <div class="win-loss-stats">
                <div class="stat-item">
                  <div class="stat-label">总交易次数</div>
                  <div class="stat-value">{{ winLossStats.total_trades || 0 }}</div>
                </div>
                <div class="stat-item">
                  <div class="stat-label">盈利次数</div>
                  <div class="stat-value profit">{{ winLossStats.win_trades || 0 }}</div>
                </div>
                <div class="stat-item">
                  <div class="stat-label">亏损次数</div>
                  <div class="stat-value loss">{{ winLossStats.loss_trades || 0 }}</div>
                </div>
                <div class="stat-item">
                  <div class="stat-label">胜率</div>
                  <div class="stat-value">{{ (winLossStats.win_rate || 0).toFixed(1) }}%</div>
                </div>
                <div class="stat-item">
                  <div class="stat-label">盈亏比</div>
                  <div class="stat-value">{{ (winLossStats.profit_loss_ratio || 0).toFixed(2) }}</div>
                </div>
              </div>
            </el-card>
          </el-col>

          <!-- 月度盈亏 -->
          <el-col :xs="24" :sm="24" :md="12" :lg="12" :xl="12">
            <el-card shadow="never" style="margin-bottom: 8px;">
              <template #header>
                <span>月度盈亏</span>
              </template>
              <!-- 移动端卡片布局：m-card + m-stock-row -->
              <div v-if="isMobile" class="mobile-card-list">
                <div v-for="row in monthlyPnl" :key="row.month" class="m-card sim-m-pnl-card">
                  <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:15px;font-weight:600;color:var(--m-text);">{{ row.month }}月</span>
                    <el-tag :type="row.win_rate != null && row.win_rate >= 50 ? 'success' : 'danger'" size="small" effect="plain">胜率 {{ row.win_rate != null ? row.win_rate.toFixed(1) + '%' : '--' }}</el-tag>
                  </div>
                  <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; padding:8px 0; font-size:13px;">
                    <div><span class="m-text-muted">收益率</span></div>
                    <div style="text-align:right;"><span :class="row.monthly_return >= 0 ? 'm-text-up' : 'm-text-down'" style="font-weight:700;">{{ row.monthly_return >= 0 ? '+' : '' }}{{ (row.monthly_return || 0).toFixed(2) }}%</span></div>
                    <div><span class="m-text-muted">盈亏</span></div>
                    <div style="text-align:right;"><span :class="row.total_daily_profit >= 0 ? 'm-text-up' : 'm-text-down'" style="font-weight:700;">{{ row.total_daily_profit >= 0 ? '+' : '' }}¥{{ formatMoney(row.total_daily_profit) }}</span></div>
                  </div>
                </div>
              </div>
              <!-- 桌面端表格 -->
              <el-table v-else :data="monthlyPnl" size="small" border style="width: 100%;">
                <el-table-column label="月份" min-width="80">
                  <template #default="{ row }">{{ row.month }}月</template>
                </el-table-column>
                <el-table-column prop="monthly_return" label="收益率" min-width="90" align="right">
                  <template #default="{ row }">
                    <span :class="row.monthly_return >= 0 ? 'profit' : 'loss'">
                      {{ row.monthly_return >= 0 ? '+' : '' }}{{ (row.monthly_return || 0).toFixed(2) }}%
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="total_daily_profit" label="盈亏金额" min-width="100" align="right">
                  <template #default="{ row }">
                    <span :class="row.total_daily_profit >= 0 ? 'profit' : 'loss'">
                      {{ row.total_daily_profit >= 0 ? '+' : '' }}¥{{ formatMoney(row.total_daily_profit) }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column prop="win_rate" label="胜率" min-width="80" align="right">
                  <template #default="{ row }">{{ row.win_rate != null ? row.win_rate.toFixed(1) + '%' : '--' }}</template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>

        <!-- 盈亏分布 -->
        <el-card shadow="never" class="distribution-card">
          <template #header>
            <span>盈亏分布</span>
          </template>
          <div class="distribution-chart">
            <div v-for="item in winLossDistribution.distribution || []" :key="item.range" class="distribution-item">
              <div class="distribution-label">{{ item.range }}</div>
              <div class="distribution-bar">
                <div class="distribution-fill" :style="{ width: (item.percentage || 0) + '%' }" />
              </div>
              <div class="distribution-value">{{ item.count }} ({{ (item.percentage || 0).toFixed(1) }}%)</div>
            </div>
          </div>
        </el-card>
        </div>
      </el-tab-pane>

      <!-- 风险管理 -->
      <el-tab-pane label="风险管理" name="risk">
        <div class="tab-pane-content">
        <div class="tab-toolbar">
          <el-tooltip :content="authStore.isAdmin ? '检查风险持仓' : '仅管理员可操作'" placement="top">
            <el-button size="small" type="warning" :disabled="!authStore.isAdmin" @click="checkRisk">检查风险</el-button>
          </el-tooltip>
          <el-tooltip :content="authStore.isAdmin ? '执行风控操作' : '仅管理员可操作'" placement="top">
            <el-button size="small" type="danger" :disabled="!authStore.isAdmin" @click="executeRiskControl">执行风控</el-button>
          </el-tooltip>
        </div>

        <!-- 移动端卡片布局：m-card + m-stock-row 设计系统 -->
        <template v-if="isMobile">
          <div class="mobile-card-list" v-loading="loading">
            <div v-for="(row, idx) in pagedRiskPositions" :key="idx" class="m-card sim-m-risk-card">
              <div class="m-stock-row" style="padding: 8px 0 6px; border-bottom: 1px solid var(--m-border);">
                <div class="info">
                  <div class="sname">{{ row.stock_name }}</div>
                  <div class="scode">{{ row.stock_code }}</div>
                </div>
                <el-tag :type="getRiskLevelType(row.risk_level)" size="small">{{ getRiskLevelLabel(row.risk_level) }}</el-tag>
              </div>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; padding:8px 0; font-size:12px;">
                <div><span class="m-text-muted">现价</span> <span style="font-weight:600;">¥{{ (row.current_price || 0).toFixed(2) }}</span></div>
                <div><span class="m-text-muted">成本</span> <span style="font-weight:600;">¥{{ (row.cost_price || 0).toFixed(2) }}</span></div>
              </div>
              <div style="display:flex; justify-content:center; padding:8px 0 4px; border-top:1px dashed var(--m-border); font-size:13px;">
                <span class="m-text-down" style="font-weight:700;">亏损 {{ (row.loss_ratio || 0).toFixed(2) }}%</span>
              </div>
              <div style="padding-top:6px; border-top:1px solid var(--m-surface2); font-size:12px;">
                <div style="display:flex; gap:4px; margin-bottom:3px;"><span class="m-text-muted" style="flex-shrink:0; min-width:32px;">原因</span><span>{{ row.risk_reason }}</span></div>
                <div style="display:flex; gap:4px;"><span class="m-text-muted" style="flex-shrink:0; min-width:32px;">建议</span><span>{{ row.suggestion }}</span></div>
              </div>
            </div>
          </div>
        </template>

        <!-- 桌面端表格 -->
        <div class="table-section" v-else>
        <el-table :data="pagedRiskPositions" size="small" height="100%" border v-loading="loading">
          <el-table-column prop="stock_code" label="股票代码" width="100" />
          <el-table-column prop="stock_name" label="股票名称" min-width="100" show-overflow-tooltip />
          <el-table-column prop="current_price" label="现价" width="90" align="right">
            <template #default="{ row }">¥{{ (row.current_price || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="cost_price" label="成本价" width="90" align="right">
            <template #default="{ row }">¥{{ (row.cost_price || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="loss_ratio" label="亏损比例" width="90" align="right">
            <template #default="{ row }">
              <span :class="row.loss_ratio <= -5 ? 'loss' : ''">
                {{ (row.loss_ratio || 0).toFixed(2) }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="risk_level" label="风险等级" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="getRiskLevelType(row.risk_level)" size="small">
                {{ getRiskLevelLabel(row.risk_level) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="risk_reason" label="风险原因" min-width="150" show-overflow-tooltip />
          <el-table-column prop="suggestion" label="建议操作" min-width="120" show-overflow-tooltip />
        </el-table>
        </div>
        <div class="pagination-bar">
          <el-pagination
            v-model:current-page="riskPage"
            :page-size="PAGE_SIZE"
            :total="riskPositions.length"
            layout="total, prev, pager, next"
            small
            background
          />
        </div>
        </div>
      </el-tab-pane>

    </el-tabs>

    <!-- 买入对话框 -->
    <el-dialog v-model="buyDialogVisible" title="买入股票" width="500px">
      <el-form :model="buyForm" label-width="100px">
        <el-form-item label="股票代码" required>
          <el-input v-model="buyForm.stock_code" placeholder="请输入股票代码" />
        </el-form-item>
        <el-form-item label="股票名称">
          <el-input v-model="buyForm.stock_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="买入价格" required>
          <el-input-number v-model="buyForm.price" :min="0.01" :step="0.01" :precision="2" />
        </el-form-item>
        <el-form-item label="买入数量" required>
          <el-input-number v-model="buyForm.quantity" :min="100" :step="100" />
        </el-form-item>
        <el-form-item label="持仓类型">
          <el-radio-group v-model="buyForm.position_type">
            <el-radio label="short">短线</el-radio>
            <el-radio label="mid">中线</el-radio>
            <el-radio label="long">长线</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="买入理由">
          <el-input v-model="buyForm.strategy_reason" type="textarea" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="buyDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="executeBuy" :loading="trading">确认买入</el-button>
      </template>
    </el-dialog>

    <!-- 卖出对话框 -->
    <el-dialog v-model="sellDialogVisible" title="卖出股票" width="500px">
      <el-form :model="sellForm" label-width="100px">
        <el-form-item label="股票代码" required>
          <el-select v-model="sellForm.stock_code" filterable placeholder="选择持仓股票" @change="onStockSelect">
            <el-option
              v-for="pos in positions"
              :key="pos.stock_code"
              :label="`${pos.stock_code} ${pos.stock_name}`"
              :value="pos.stock_code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="可卖数量">
          <span>{{ selectedPosition?.available_quantity || 0 }}</span>
        </el-form-item>
        <el-form-item label="卖出价格" required>
          <el-input-number v-model="sellForm.price" :min="0.01" :step="0.01" :precision="2" />
        </el-form-item>
        <el-form-item label="卖出数量" required>
          <el-input-number v-model="sellForm.quantity" :min="100" :step="100" :max="selectedPosition?.available_quantity || 0" />
        </el-form-item>
        <el-form-item label="卖出理由">
          <el-input v-model="sellForm.strategy_reason" type="textarea" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sellDialogVisible = false">取消</el-button>
        <el-button type="danger" @click="executeSell" :loading="trading">确认卖出</el-button>
      </template>
    </el-dialog>

    <!-- 创建委托对话框 -->
    <el-dialog v-model="orderDialogVisible" title="创建委托" width="500px">
      <el-form :model="orderForm" label-width="100px">
        <el-form-item label="股票代码" required>
          <el-input v-model="orderForm.stock_code" placeholder="请输入股票代码" />
        </el-form-item>
        <el-form-item label="股票名称">
          <el-input v-model="orderForm.stock_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="委托类型" required>
          <el-radio-group v-model="orderForm.order_type">
            <el-radio label="buy">买入</el-radio>
            <el-radio label="sell">卖出</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="委托价格" required>
          <el-input-number v-model="orderForm.order_price" :min="0.01" :step="0.01" :precision="2" />
        </el-form-item>
        <el-form-item label="委托数量" required>
          <el-input-number v-model="orderForm.order_quantity" :min="100" :step="100" />
        </el-form-item>
        <el-form-item label="持仓类型">
          <el-radio-group v-model="orderForm.position_type">
            <el-radio label="short">短线</el-radio>
            <el-radio label="mid">中线</el-radio>
            <el-radio label="long">长线</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="orderForm.strategy_reason" type="textarea" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="orderDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitOrder" :loading="trading">确认创建</el-button>
      </template>
    </el-dialog>

    <!-- 做T执行对话框 -->
    <el-dialog v-model="tTradeDialogVisible" title="执行做T" width="500px">
      <el-form :model="tTradeForm" label-width="100px">
        <el-form-item label="股票代码">
          <el-input v-model="tTradeForm.stock_code" disabled />
        </el-form-item>
        <el-form-item label="股票名称">
          <el-input v-model="tTradeForm.stock_name" disabled />
        </el-form-item>
        <el-form-item label="买入价格">
          <el-input-number v-model="tTradeForm.buy_price" :min="0.01" :step="0.01" :precision="2" disabled />
        </el-form-item>
        <el-form-item label="卖出价格" required>
          <el-input-number v-model="tTradeForm.sell_price" :min="0.01" :step="0.01" :precision="2" />
        </el-form-item>
        <el-form-item label="交易数量" required>
          <el-input-number v-model="tTradeForm.quantity" :min="100" :step="100" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tTradeDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitTTrade" :loading="trading">确认执行</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Money, Refresh, RefreshRight, MagicStick, ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const authStore = useAuthStore()

let _autoRefreshTimer = null

const API_BASE = '/sim-trading'

// 状态
const activeTab = ref('positions')
const loading = ref(false)
const refreshing = ref(false)
const generating = ref(false)
const executing = ref(false)
const trading = ref(false)
const resetting = ref(false)
const tradeFilter = ref('')
const ordersTodayOnly = ref(true)  // 默认仅显示当日委托（当日以外的由 15:30 清理任务处理）

// 非管理员提示：拦截需要管理员权限的操作
const requireAdmin = (actionName) => {
  if (!authStore.isAdmin) {
    ElMessage.warning(`「${actionName}」仅限管理员操作`)
    return false
  }
  return true
}

// 数据
const account = ref({
  total_assets: 100000,
  current_capital: 100000,
  total_profit: 0,
  total_profit_ratio: 0
})
const stats = ref({
  position_count: 0,
  win_rate: 0,
  profit_loss_ratio: 0,
  max_drawdown: 0
})
const positions = ref([])
const trades = ref([])
const currentStrategy = ref(null)  // 当前最新策略摘要（用于生成后展示）
const strategyDrawerVisible = ref(false)  // 抽屉可见性
const drawerStrategyData = ref(null)  // 抽屉中展示的完整策略数据
const simDrawerSize = computed(() => isMobile.value ? '100%' : '65%')
const strategyHistory = ref([])
const monthlyPnl = ref([])
const winLossStats = ref({})
const winLossDistribution = ref({})

// 分页
const PAGE_SIZE = 20
const tradesPage = ref(1)
const strategyHistoryPage = ref(1)
const positionsPage = ref(1)
const ordersPage = ref(1)
const tTradesPage = ref(1)
const riskPage = ref(1)
const pagedTrades = computed(() => {
  const start = (tradesPage.value - 1) * PAGE_SIZE
  return trades.value.slice(start, start + PAGE_SIZE)
})
const pagedStrategyHistory = computed(() => {
  const start = (strategyHistoryPage.value - 1) * PAGE_SIZE
  return strategyHistory.value.slice(start, start + PAGE_SIZE)
})
const pagedPositions = computed(() => {
  const start = (positionsPage.value - 1) * PAGE_SIZE
  return positions.value.slice(start, start + PAGE_SIZE)
})
const pagedOrders = computed(() => {
  const start = (ordersPage.value - 1) * PAGE_SIZE
  return orders.value.slice(start, start + PAGE_SIZE)
})
const pagedTTrades = computed(() => {
  const start = (tTradesPage.value - 1) * PAGE_SIZE
  return tTrades.value.slice(start, start + PAGE_SIZE)
})
const pagedRiskPositions = computed(() => {
  const start = (riskPage.value - 1) * PAGE_SIZE
  return riskPositions.value.slice(start, start + PAGE_SIZE)
})

// 策略配置
const strategyConfig = ref({
  max_single_position_ratio: 0.20,
  total_position_ratio: 0.80,
  stop_loss_ratio: 8,
  take_profit_ratio: 15,
  min_buy_amount: 5000,
  enforce_params: false
})
// 策略配置参数默认收起（减少占用区域）
const configExpanded = ref(false)

// 买入表单
const buyDialogVisible = ref(false)
const buyForm = ref({
  stock_code: '',
  stock_name: '',
  price: 0,
  quantity: 100,
  position_type: 'short',
  strategy_reason: ''
})

// 卖出表单
const sellDialogVisible = ref(false)
const sellForm = ref({
  stock_code: '',
  price: 0,
  quantity: 100,
  strategy_reason: ''
})
const selectedPosition = ref(null)

// 委托管理数据
const orders = ref([])
const orderDialogVisible = ref(false)
const orderForm = ref({
  stock_code: '',
  stock_name: '',
  order_type: 'buy',
  order_price: 0,
  order_quantity: 100,
  position_type: 'short',
  strategy_reason: ''
})

// 做T记录数据
const tTrades = ref([])
const tTradeStats = ref({})
const tTradeStatsLoading = ref(false)
const tTradeDialogVisible = ref(false)
const tTradeForm = ref({
  trade_id: '',
  stock_code: '',
  stock_name: '',
  buy_price: 0,
  sell_price: 0,
  quantity: 100
})

// 风险管理数据
const riskPositions = ref([])

// 判断当前是否在交易时段（9:30-11:30, 13:00-15:00）
const isTradingTime = computed(() => {
  const now = new Date()
  const weekday = now.getDay() // 0=周日, 6=周六
  if (weekday === 0 || weekday === 6) return false
  const hours = now.getHours()
  const minutes = now.getMinutes()
  const timeVal = hours * 60 + minutes
  return (timeVal >= 570 && timeVal <= 690) || (timeVal >= 780 && timeVal <= 900) // 9:30-11:30, 13:00-15:00
})

// 移动端检测（≤768px）
const isMobile = ref(false)
function _updateIsMobile() {
  isMobile.value = window.innerWidth <= 768
}
window.addEventListener('resize', _updateIsMobile)
onMounted(() => _updateIsMobile())

// 格式化函数
const formatMoney = (value) => {
  if (value === null || value === undefined) return '0.00'
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}


const getPositionType = (type) => {
  const types = { short: 'warning', mid: 'primary', long: 'success' }
  return types[type] || 'info'
}

const getPositionLabel = (type) => {
  const labels = { short: '短线', mid: '中线', long: '长线' }
  return labels[type] || type
}

const getSentimentType = (sentiment) => {
  const types = { bullish: 'danger', bearish: 'success', neutral: 'warning' }
  return types[sentiment] || 'info'
}

const getSentimentLabel = (sentiment) => {
  const labels = { bullish: '看涨', bearish: '看跌', neutral: '震荡' }
  return labels[sentiment] || '未知'
}

const getStatusType = (status) => {
  const types = { pending: 'warning', executed: 'success', completed: 'success', failed: 'danger', manual: 'info' }
  return types[status] || 'info'
}

const getStatusLabel = (status) => {
  const labels = { pending: '待执行', executed: '已执行', completed: '已完成', failed: '失败', manual: '手动生成' }
  return labels[status] || status
}

// 策略模式（盘中即时/午间调整/收盘次日）
const getStrategyModeType = (mode) => {
  const types = { intraday: 'success', intraday_afternoon: 'success', midday: 'warning', next_day: 'primary' }
  return types[mode] || 'info'
}

const getStrategyModeLabel = (mode) => {
  const labels = { intraday: '⚡上午盘中', intraday_afternoon: '⚡下午盘中', midday: '☀️午间调整', next_day: '🌙收盘次日' }
  return labels[mode] || mode
}

// 委托状态辅助函数
const getOrderStatusType = (status) => {
  const types = { pending: 'warning', filled: 'success', partial: 'primary', cancelled: 'info', rejected: 'danger' }
  return types[status] || 'info'
}

const getOrderStatusLabel = (status) => {
  const labels = { pending: '待成交', filled: '已成交', partial: '部分成交', cancelled: '已撤销', rejected: '已拒绝' }
  return labels[status] || status
}

// 委托现价提示色：买入时现价<=委托价（可成交）显示绿色，卖出时现价>=委托价显示绿色
const priceHintColor = (row) => {
  if (row.current_price == null || row.order_price == null) return ''
  if (row.order_status !== 'pending') return ''
  const cur = Number(row.current_price)
  const ord = Number(row.order_price)
  if (Number.isNaN(cur) || Number.isNaN(ord)) return ''
  if (row.order_type === 'buy') return cur <= ord ? '#67c23a' : '#f56c6c'
  if (row.order_type === 'sell') return cur >= ord ? '#67c23a' : '#f56c6c'
  return ''
}

// 做T状态辅助函数
const getTTradeStatusType = (status) => {
  const types = { pending: 'warning', executed: 'success', completed: 'success', failed: 'danger', manual: 'info' }
  return types[status] || 'info'
}

const getTTradeStatusLabel = (status) => {
  const labels = { pending: '待执行', executed: '已执行', completed: '已完成', failed: '失败', manual: '手动生成' }
  return labels[status] || status
}

// 风险等级辅助函数
const getRiskLevelType = (level) => {
  const types = { low: 'success', medium: 'warning', high: 'danger', critical: 'danger' }
  return types[level] || 'info'
}

const getRiskLevelLabel = (level) => {
  const labels = { low: '低风险', medium: '中风险', high: '高风险', critical: '极高风险' }
  return labels[level] || level
}

// API调用
const fetchAccount = async (forceRefresh = false) => {
  try {
    const data = await api.get(`${API_BASE}/account`, { params: forceRefresh ? { refresh: true } : {} })
    account.value = data.account
    stats.value = data.stats || {}
    positions.value = data.positions || []
    positionsPage.value = 1
  } catch (error) {
    console.error('获取账户信息失败:', error)
  }
}

const fetchTrades = async () => {
  try {
    const data = await api.get(`${API_BASE}/trades`, { params: { trade_type: tradeFilter.value || undefined } })
    trades.value = data.trades || []
    tradesPage.value = 1
  } catch (error) {
    console.error('获取交易记录失败:', error)
  }
}

// 策略历史排序处理
const handleStrategySort = ({ prop, order }) => {
  if (!order) {
    // 恢复默认排序（按生成时间倒序）
    strategyHistory.value.sort((a, b) => {
      const timeA = a.created_at || ''
      const timeB = b.created_at || ''
      return timeB.localeCompare(timeA)
    })
    return
  }
  strategyHistory.value.sort((a, b) => {
    const valA = a[prop] || ''
    const valB = b[prop] || ''
    if (order === 'ascending') {
      return valA.localeCompare(valB)
    } else {
      return valB.localeCompare(valA)
    }
  })
}

const fetchStrategyHistory = async () => {
  try {
    const data = await api.get(`${API_BASE}/strategy/history`)
    const history = data.history || []
    // 默认按生成时间倒序排序
    history.sort((a, b) => {
      const timeA = a.created_at || ''
      const timeB = b.created_at || ''
      return timeB.localeCompare(timeA)
    })
    strategyHistory.value = history
    strategyHistoryPage.value = 1
  } catch (error) {
    console.error('获取策略历史失败:', error)
  }
}

// 查看当前最新策略详情（打开抽屉）
const viewCurrentStrategy = () => {
  if (!currentStrategy.value) return
  drawerStrategyData.value = currentStrategy.value
  strategyDrawerVisible.value = true
}

// 抽屉标题计算
const drawerTitle = computed(() => {
  if (!drawerStrategyData.value) return '策略详情'
  const d = drawerStrategyData.value
  return `AI策略 (${d.decision_date} - ${getStrategyModeLabel(d.mode)})`
})

// 查看历史策略详情（抽屉模式）
const viewStrategyHistory = async (row) => {
  try {
    const data = await api.get(`${API_BASE}/strategy/detail/${row.id}`)
    drawerStrategyData.value = {
      ...data,
      mode: data.mode || 'intraday',
      market_analysis: data.market_analysis || { sentiment: data.market_sentiment || 'neutral', analysis: data.ai_analysis || '' },
      isFromHistory: true
    }
    strategyDrawerVisible.value = true
  } catch (error) {
    ElMessage.error('加载策略详情失败')
  }
}

// 删除指定策略（从历史表格触发）
const deleteStrategy = async (row) => {
  if (!requireAdmin('删除策略')) return
  try {
    await api.delete(`${API_BASE}/strategy/${row.id}`)
    ElMessage.success(`已删除 ${row.decision_date} 的策略`)
    // 如果删除的是当前展示的策略，清空
    if (currentStrategy.value?.decision_id === row.id) {
      currentStrategy.value = null
    }
    await fetchStrategyHistory()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '删除失败')
  }
}

// 删除当前展示的策略（从 currentStrategy 卡片触发）
const deleteCurrentStrategy = async () => {
  if (!currentStrategy.value?.decision_id) {
    // 来自历史但未持久化的策略仅清空展示
    currentStrategy.value = null
    return
  }
  await deleteStrategy({ id: currentStrategy.value.decision_id, decision_date: currentStrategy.value.decision_date })
}

// 移动端用：带 ElMessageBox 确认的删除（避免 popconfirm 在小屏体验差）
const confirmDeleteStrategy = async (row) => {
  if (!requireAdmin('删除策略')) return
  try {
    await ElMessageBox.confirm(
      `确定删除 ${row.decision_date} 的策略？\n类型: ${getStrategyModeLabel(row.strategy_mode)}`,
      '删除策略',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await deleteStrategy(row)
}

// 执行历史中的 pending 策略
const executeHistoryStrategy = async (row) => {
  if (!requireAdmin('执行策略')) return
  try {
    await ElMessageBox.confirm(
      `将执行 ${row.decision_date} 的策略（买入${row.buy_count}只，卖出${row.sell_count}只）。\n\n是否继续？`,
      '执行策略'
    )
    executing.value = true
    const data = await api.post(`${API_BASE}/strategy/execute/${row.id}`, null, { timeout: 60000 })
    if (data.success) {
      ElMessage.success('策略已执行')
      await refreshData()
    } else {
      ElMessage.error(data.error || '执行失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '执行失败')
    }
  } finally {
    executing.value = false
  }
}

const fetchPerformance = async () => {
  try {
    const data = await api.get(`${API_BASE}/stats/performance`)
    monthlyPnl.value = data.monthly_pnl || []
    winLossStats.value = data.overall_stats || {}
  } catch (error) {
    console.error('获取业绩报告失败:', error)
  }
}

const fetchWinLoss = async () => {
  try {
    const data = await api.get(`${API_BASE}/stats/win-loss`)
    winLossDistribution.value = data || {}
  } catch (error) {
    console.error('获取盈亏分布失败:', error)
  }
}

// 委托管理API
const fetchOrders = async (todayOnly = null) => {
  // null 表示沿用 ordersTodayOnly 当前值；显式传值则强制使用
  const useTodayOnly = todayOnly === null ? ordersTodayOnly.value : todayOnly
  try {
    const params = useTodayOnly ? '?today_only=true' : ''
    const data = await api.get(`${API_BASE}/orders${params}`)
    orders.value = data.orders || []
    ordersPage.value = 1
  } catch (error) {
    console.error('获取委托列表失败:', error)
  }
}

const loadOrders = () => fetchOrders()

const showOrderDialog = () => {
  orderForm.value = {
    stock_code: '',
    stock_name: '',
    order_type: 'buy',
    order_price: 0,
    order_quantity: 100,
    position_type: 'short',
    strategy_reason: ''
  }
  orderDialogVisible.value = true
}

const submitOrder = async () => {
  if (!orderForm.value.stock_code || orderForm.value.order_price <= 0) {
    ElMessage.warning('请填写完整的委托信息')
    return
  }
  trading.value = true
  try {
    await createOrder(orderForm.value)
    ElMessage.success('委托创建成功')
    orderDialogVisible.value = false
    await loadOrders()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '创建委托失败')
  } finally {
    trading.value = false
  }
}

const createOrder = async (form) => {
  const data = await api.post(`${API_BASE}/orders`, form)
  return data
}

const cancelOrder = async (orderId) => {
  try {
    await ElMessageBox.confirm('确定撤销该委托？', '确认撤单')
    await api.post(`${API_BASE}/orders/${orderId}/cancel`)
    ElMessage.success('委托已撤销')
    await loadOrders()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '撤销委托失败')
    }
  }
}

const deleteOrder = async (orderId) => {
  try {
    await api.delete(`${API_BASE}/orders/${orderId}`)
    ElMessage.success('委托记录已删除')
    await loadOrders()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '删除失败')
  }
}

// 手动撮合：管理员触发，force=true 跳过交易时段限制
const matching = ref(false)
const matchOrders = async () => {
  if (!authStore.isAdmin) {
    ElMessage.warning('仅管理员可操作')
    return
  }
  try {
    await ElMessageBox.confirm(
      '将立即撮合所有待成交委托单（按当前行情判断是否成交）。\n非交易时段将强制撮合，是否继续？',
      '立即撮合',
      { type: 'warning', confirmButtonText: '立即撮合', cancelButtonText: '取消' }
    )
    matching.value = true
    const data = await api.post(`${API_BASE}/orders/match?force=true`)
    const matched = data.matched_count || 0
    const total = data.total_pending || 0
    if (matched > 0) {
      ElMessage.success(`撮合完成：成交 ${matched} 笔${total > matched ? `（共 ${total} 笔待成交）` : ''}`)
    } else if (data.skipped) {
      ElMessage.info(data.skipped)
    } else {
      ElMessage.info(`暂无可成交委托（共 ${total} 笔待成交，委托价未触达现价）`)
    }
    await loadOrders()
    // 成交后刷新账户/持仓
    await fetchAccount(true)
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '撮合失败')
    }
  } finally {
    matching.value = false
  }
}

const fetchReviews = async () => {
  try {
    const data = await api.get(`${API_BASE}/reviews`, { params: { limit: 10 } })
    reviewList.value = data.reviews || []
  } catch (error) {
    console.error('获取复盘列表失败:', error)
  }
}

const reviewList = ref([])

// 做T记录API
const fetchTTrades = async () => {
  try {
    const data = await api.get(`${API_BASE}/t-trades`)
    tTrades.value = data.t_trades || []
    tTradesPage.value = 1
  } catch (error) {
    console.error('获取做T记录失败:', error)
  }
  // 同步加载统计（非阻塞，独立 try）
  fetchTTradeStats()
}

const fetchTTradeStats = async () => {
  tTradeStatsLoading.value = true
  try {
    const data = await api.get(`${API_BASE}/t-trades/stats`)
    tTradeStats.value = data || {}
  } catch (error) {
    console.error('获取做T统计失败:', error)
  } finally {
    tTradeStatsLoading.value = false
  }
}

const detectTTrade = async () => {
  try {
    const data = await api.post(`${API_BASE}/t-trades/detect`)
    ElMessage.success(`检测到${data.opportunities || 0}个做T机会`)
    await fetchTTrades()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '检测做T机会失败')
  }
}

const showTTradeDialog = (row) => {
  tTradeForm.value = {
    trade_id: row.trade_id,
    stock_code: row.stock_code,
    stock_name: row.stock_name,
    buy_price: row.buy_price,
    sell_price: row.sell_price || row.buy_price,
    quantity: row.quantity
  }
  tTradeDialogVisible.value = true
}

const submitTTrade = async () => {
  if (tTradeForm.value.sell_price <= 0) {
    ElMessage.warning('请填写卖出价格')
    return
  }
  trading.value = true
  try {
    await executeTTrade(tTradeForm.value)
    ElMessage.success('做T执行成功')
    tTradeDialogVisible.value = false
    await fetchTTrades()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '执行做T失败')
  } finally {
    trading.value = false
  }
}

const executeTTrade = async (form) => {
  const data = await api.post(`${API_BASE}/t-trades/execute`, form)
  return data
}

// 风险管理API
const checkRisk = async () => {
  if (!requireAdmin('检查风险')) return
  try {
    const data = await api.post(`${API_BASE}/risk/check`)
    riskPositions.value = data.risk_positions || []
    riskPage.value = 1
    if (riskPositions.value.length === 0) {
      ElMessage.success('未发现风险持仓')
    } else {
      ElMessage.warning(`发现${riskPositions.value.length}个风险持仓`)
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '风险检查失败')
  }
}

const executeRiskControl = async () => {
  if (riskPositions.value.length === 0) {
    ElMessage.warning('请先执行风险检查')
    return
  }
  try {
    await ElMessageBox.confirm('确定执行风控操作？将对风险持仓执行建议操作。', '确认执行风控')
    const data = await api.post(`${API_BASE}/risk/execute`)
    ElMessage.success(`风控执行完成，处理${data.handled_count || 0}个持仓`)
    riskPositions.value = []
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '执行风控失败')
    }
  }
}

const refreshData = async () => {
  refreshing.value = true
  try {
    await Promise.all([
      fetchAccount(true), fetchTrades(), fetchStrategyHistory(), fetchPerformance(), fetchWinLoss(),
      fetchOrders(), fetchTTrades(), fetchReviews()
    ])
    ElMessage.success('数据已刷新')
  } catch (e) {
    ElMessage.error('刷新失败：' + (e.response?.data?.detail || e.message))
  } finally {
    refreshing.value = false
  }
}

// AI策略生成命令处理（盘中/午间/收盘）
const handleStrategyCommand = async (command) => {
  if (!requireAdmin('生成AI策略')) return

  const isNextDay = command === 'next_day'
  const isMidday = command === 'midday'
  const isIntraday = command === 'intraday'
  const targetMode = isNextDay ? 'next_day' : (isMidday ? 'midday' : 'intraday')
  const modeLabel = getStrategyModeLabel(targetMode)
  const today = new Date().toISOString().slice(0, 10)

  // 检查是否已有同类型待执行策略
  const sameModePending = strategyHistory.value.find(
    s => s.execution_status === 'pending' && s.strategy_mode === targetMode &&
         (targetMode === 'next_day' ? s.decision_date !== today : s.decision_date === today)
  )

  let confirmMsg = ''
  if (isNextDay) {
    confirmMsg = '生成收盘次日策略：基于今日收盘数据和持仓分析，生成明日交易计划。\n\n该策略将在下一个交易日盘中自动执行。'
  } else if (isMidday) {
    confirmMsg = '生成午间策略调整：总结上午交易执行情况和市场走势，AI 调整下午交易策略。\n\n将覆盖当日待执行的盘中策略。'
  } else {
    confirmMsg = '生成盘中即时策略：基于实时行情数据，生成今日立即执行的交易计划。\n\n生成后需要确认是否执行。'
  }

  if (sameModePending) {
    const detail = `日期: ${sameModePending.decision_date}\n类型: ${getStrategyModeLabel(sameModePending.strategy_mode)}\n买入: ${sameModePending.buy_count} / 卖出: ${sameModePending.sell_count}`
    try {
      await ElMessageBox.confirm(
        `已存在待执行的 ${modeLabel}：\n\n${detail}\n\n` +
        `生成新策略会覆盖现有记录（同一日期+同一类型仅保留一条）。是否继续？\n\n${confirmMsg}`,
        `${modeLabel} - 已存在待执行策略`,
        {
          confirmButtonText: '覆盖生成',
          cancelButtonText: '取消',
          type: 'warning',
        }
      )
    } catch {
      return
    }
  } else {
    try {
      await ElMessageBox.confirm(
        confirmMsg,
        modeLabel,
        {
          confirmButtonText: '确定生成',
          cancelButtonText: '取消',
          type: 'info',
        }
      )
    } catch {
      return
    }
  }

  generating.value = true
  // 显示长时间加载提示（LLM 调用可能持续 1-10 分钟）
  const loadingHint = ElMessage({
    message: '正在调用 AI 生成策略，AI 分析 + LLM 推理可能需要 1-10 分钟，请耐心等待...',
    type: 'info',
    duration: 0,  // 不自动关闭
    showClose: false,
  })
  try {
    let endpoint
    if (isNextDay) {
      endpoint = `${API_BASE}/strategy/next-day`
    } else if (isMidday) {
      endpoint = `${API_BASE}/strategy/midday`
    } else {
      endpoint = `${API_BASE}/strategy/generate`
    }
    // 超时设为 580s（后端 600s 上限），比后端稍短以保证能收到明确的错误响应
    const data = await api.post(endpoint, strategyConfig.value, { timeout: 580000 })
    loadingHint.close()

    currentStrategy.value = {
      ...data,
      mode: data.mode || (isNextDay ? 'next_day' : (isMidday ? 'midday' : 'intraday')),
      market_analysis: data.market_analysis || { sentiment: data.market_sentiment || 'neutral', analysis: '' }
    }
    drawerStrategyData.value = currentStrategy.value
    strategyDrawerVisible.value = true

    if (isNextDay) {
      const buyCount = (data.buy_list || []).length
      const sellCount = (data.sell_signals || []).length
      ElMessage.success(`次日策略生成成功：建议买入${buyCount}只，卖出${sellCount}只（明日盘中自动执行）`)
    } else if (data.executed) {
      const execResult = data.execution_result || {}
      const buyOk = (execResult.buy_orders || []).filter(r => r.success).length
      const sellOk = (execResult.sell_orders || []).filter(r => r.success).length
      ElMessage.success(`盘中策略已创建委托：买入${buyOk}只，卖出${sellOk}只（可在「委托管理」查看进度）`)
      activeTab.value = 'orders'
    } else {
      // 盘中策略生成成功但未自动执行（非交易时段），提示用户手动确认
      const buyCount = (data.buy_list || []).length
      const sellCount = (data.sell_signals || []).length
      ElMessage.warning(`盘中策略已生成：买入${buyCount}只，卖出${sellCount}只。请确认是否创建委托。`)
    }

    await refreshData()
  } catch (error) {
    loadingHint.close()
    if (error.code === 'ECONNABORTED' || error.message?.includes('timeout')) {
      ElMessage.error('AI 策略生成超时（580s）。后端可能仍在处理，请稍后到「AI策略」页查看历史或重新生成。')
    } else {
      ElMessage.error(error.response?.data?.detail || '策略生成失败')
    }
  } finally {
    generating.value = false
  }
}

// 执行策略：按买入/卖出列表下市价单立即成交
const executeStrategy = async () => {
  if (!currentStrategy.value) return
  if (!requireAdmin('创建委托')) return

  try {
    const buyCount = currentStrategy.value.buy_list?.length || 0
    const sellCount = currentStrategy.value.sell_signals?.length || 0
    await ElMessageBox.confirm(
      `将为该策略创建委托单（买入 ${buyCount} 只、卖出 ${sellCount} 只），\n委托单会在盘中行情达到条件时自动成交，可在「委托管理」中查看进度。\n\n是否继续？`,
      '创建委托单'
    )

    executing.value = true
    const data = await api.post(`${API_BASE}/strategy/execute/${currentStrategy.value.decision_id}`, null, { timeout: 60000 })

    if (data.success) {
      const buyOk = (data.buy_orders || []).filter(o => o.success).length
      const sellOk = (data.sell_orders || []).filter(o => o.success).length
      const total = buyCount + sellCount
      const ok = buyOk + sellOk
      ElMessage.success(
        `委托创建完成：共 ${total} 笔，成功 ${ok} 笔，失败 ${total - ok} 笔。可在「委托管理」查看`
      )
      currentStrategy.value.execution_result = data
      activeTab.value = 'orders'  // 跳转到委托管理
      await refreshData()
    } else {
      ElMessage.error(data.error || '委托创建失败')
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '委托创建失败')
    }
  } finally {
    executing.value = false
  }
}

// 重置模拟交易（管理员）
const resetAccount = async () => {
  try {
    await ElMessageBox.confirm(
      '此操作将清空所有持仓、交易记录、委托单、AI 策略、盈亏、复盘、做T、监控列表，并将账户资金恢复至初始值。\n\n该操作不可恢复，是否继续？',
      '重置模拟交易',
      { type: 'warning', confirmButtonText: '确认重置', cancelButtonText: '取消' }
    )
  } catch {
    return
  }

  resetting.value = true
  try {
    const data = await api.post(`${API_BASE}/admin/reset`, null, { timeout: 30000 })
    if (data.success) {
      ElMessage.success(data.message || '模拟交易已重置')
      currentStrategy.value = null
      activeTab.value = 'positions'
      await refreshData()
    } else {
      ElMessage.error(data.error || '重置失败')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重置失败')
  } finally {
    resetting.value = false
  }
}

// 买入相关
const showBuyDialog = () => {
  buyForm.value = {
    stock_code: '',
    stock_name: '',
    price: 0,
    quantity: 100,
    position_type: 'short',
    strategy_reason: ''
  }
  buyDialogVisible.value = true
}

const executeBuy = async () => {
  if (!buyForm.value.stock_code || buyForm.value.price <= 0) {
    ElMessage.warning('请填写完整的买入信息')
    return
  }
  
  trading.value = true
  try {
    const data = await api.post(`${API_BASE}/buy`, buyForm.value)
    if (data.success) {
      ElMessage.success('买入成功')
      buyDialogVisible.value = false
      await refreshData()
    } else {
      ElMessage.error(data.error || '买入失败')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '买入失败')
  } finally {
    trading.value = false
  }
}

// 卖出相关
const showSellDialog = () => {
  sellForm.value = {
    stock_code: '',
    price: 0,
    quantity: 100,
    strategy_reason: ''
  }
  selectedPosition.value = null
  sellDialogVisible.value = true
}

const onStockSelect = (code) => {
  selectedPosition.value = positions.value.find(p => p.stock_code === code)
  if (selectedPosition.value) {
    sellForm.value.price = selectedPosition.value.current_price
    sellForm.value.quantity = selectedPosition.value.available_quantity
  }
}

const executeSell = async () => {
  if (!sellForm.value.stock_code || sellForm.value.price <= 0 || sellForm.value.quantity <= 0) {
    ElMessage.warning('请填写完整的卖出信息')
    return
  }
  
  trading.value = true
  try {
    const data = await api.post(`${API_BASE}/sell`, sellForm.value)
    if (data.success) {
      ElMessage.success('卖出成功')
      sellDialogVisible.value = false
      await refreshData()
    } else {
      ElMessage.error(data.error || '卖出失败')
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '卖出失败')
  } finally {
    trading.value = false
  }
}

// 监听交易记录筛选
watch(tradeFilter, () => {
  fetchTrades()
})

// 切换到盈亏分析tab时自动刷新数据
watch(activeTab, (newTab) => {
  if (newTab === 'performance') {
    Promise.all([fetchPerformance(), fetchWinLoss()])
  }
})

// 切换到盈亏分析tab时自动刷新数据
watch(activeTab, (newTab) => {
  if (newTab === 'performance') {
    Promise.all([fetchPerformance(), fetchWinLoss()])
  }
})

// 初始化
onMounted(async () => {
  loading.value = true
  try {
    await refreshData()
  } finally {
    loading.value = false
  }

  // 持仓现价/盈亏自动刷新：每 30 秒拉取最新数据（后端 _intraday_monitor 每 5 分钟更新行情）
    // 仅在页面可见时刷新，避免后台 tab 浪费资源
    _autoRefreshTimer = setInterval(() => {
      if (document.visibilityState === 'visible' && !loading.value && !refreshing.value && !generating.value) {
        fetchAccount(true)
        // 当前在盈亏分析tab时也刷新月度数据
        if (activeTab.value === 'performance') {
          Promise.all([fetchPerformance(), fetchWinLoss()])
        }
      }
    }, 30000)
})

onBeforeUnmount(() => {
  if (_autoRefreshTimer) clearInterval(_autoRefreshTimer)
  window.removeEventListener('resize', _updateIsMobile)
})
</script>

<style lang="scss" scoped>
.sim-trading {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  padding: 12px;

  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    flex-shrink: 0;
    gap: 8px;

    .page-title {
      margin: 0;
      font-size: 18px;
      display: flex;
      align-items: center;
      gap: 8px;
      white-space: nowrap;
    }

    .header-right {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
  }

  .stats-row {
    margin-bottom: 8px;
    flex-shrink: 0;
  }

  .stat-card {
    :deep(.el-card__body) {
      padding: 8px 6px;
    }

    .stat-content {
      text-align: center;

      .stat-label {
        font-size: 12px;
        color: #909399;
        margin-bottom: 2px;
      }

      .stat-value {
        font-size: 18px;
        font-weight: bold;
        color: #303133;

        &.profit { color: #f56c6c; }
        &.loss { color: #67c23a; }
      }

      &.small .stat-value {
        font-size: 16px;
      }
    }
  }

  /* 主 tabs：flex:1 占满剩余空间，min-height:0 允许内部滚动 */
  .main-tabs {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;

    :deep(.el-tabs__header) { flex-shrink: 0; margin-bottom: 0; }
    :deep(.el-tabs__content) {
      flex: 1;
      display: flex !important;
      flex-direction: column !important;
      overflow: hidden !important;
      min-height: 0;
      padding: 8px !important;
    }
    /* 激活 pane 占满，非激活隐藏（Element Plus 用 inline style display:none 隐藏） */
    :deep(.el-tabs__content > .el-tab-pane) {
      display: none !important;
    }
    :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) {
      display: flex !important;
      flex-direction: column !important;
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }

    .tab-toolbar {
      margin-bottom: 8px;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      flex-shrink: 0;
    }
  }

  /* Tab 内容容器：flex column，工具栏固定，列表区 flex:1 滚动 */
  .tab-pane-content {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }
  /* 多卡片布局的 tab（AI策略、盈亏分析）：整块内容垂直滚动 */
  .tab-pane-content.analysis-panel {
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }
  /* AI策略 tab：配置区固定 + 历史区滚动 */
  .tab-pane-content.strategy-panel {
    overflow: hidden;
  }
  .strategy-fixed {
    flex-shrink: 0;
  }
  .strategy-scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }
  .strategy-history-section {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid #ebeef5;
    border-radius: 4px;
    background: #fff;
  }
  .section-title {
    flex-shrink: 0;
    padding: 8px 12px;
    font-size: 14px;
    font-weight: bold;
    border-bottom: 1px solid #ebeef5;
    background: #fafafa;
  }
  .pagination-bar {
    flex-shrink: 0;
    display: flex;
    justify-content: flex-end;
    padding: 6px 8px;
    border-top: 1px solid #ebeef5;
    background: #fff;
  }

  /* 表格区：flex:1 占满，内部表格 height:100% 自带滚动 */
  .table-section {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;

    :deep(.el-table) {
      width: 100% !important;
      height: 100% !important;
    }
  }
  
  .strategy-panel {
    .config-card {
      margin-bottom: 16px;
      
      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
      }
    }
    
    .strategy-result {
      margin-bottom: 16px;
      
      .market-analysis {
        margin-bottom: 16px;
        text-align: center;
        
        .el-tag {
          font-size: 16px;
          padding: 8px 16px;
        }
      }
      
      .strategy-summary {
        margin-bottom: 20px;
        
        .summary-item {
          text-align: center;
          padding: 12px;
          background: #f5f7fa;
          border-radius: 4px;
          
          .summary-label {
            font-size: 14px;
            color: #909399;
            margin-bottom: 4px;
          }
          
          .summary-value {
            font-size: 24px;
            font-weight: bold;
            color: #303133;
          }
        }
      }
      
      .stock-list {
        margin-bottom: 20px;
        
        h4 {
          margin: 0 0 12px 0;
          font-size: 16px;
          color: #303133;
        }
      }
      
      .strategy-report {
        overflow: hidden;
        max-width: 100%;

        pre.report-content {
          display: block;
          width: 100%;
          min-width: 0;
          max-width: 100%;
          margin: 0;
          white-space: pre-wrap;
          word-break: break-all;
          overflow-wrap: break-word;
          font-family: monospace;
          font-size: 13px;
          line-height: 1.6;
          color: #303133;
          background: #f5f7fa;
          padding: 12px;
          border-radius: 4px;
          overflow-x: hidden;
          box-sizing: border-box;
        }
      }
    }
    
    .history-card {
      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
    }

    // 策略抽屉中的内容：防止横向滚动
    :deep(.sim-strategy-drawer) {
      .drawer-stock-list {
        overflow-x: auto;
        margin-bottom: 20px;

        h4 {
          margin: 0 0 12px 0;
          font-size: 16px;
          color: #303133;
        }

        .el-table {
          min-width: 0;
        }
      }

      .strategy-report {
        overflow: hidden;
        max-width: 100%;

        pre.report-content {
          display: block;
          width: 100%;
          min-width: 0;
          max-width: 100%;
          margin: 0;
          white-space: pre-wrap;
          word-break: break-all;
          overflow-wrap: break-word;
          font-family: monospace;
          font-size: 13px;
          line-height: 1.6;
          color: #303133;
          background: #f5f7fa;
          padding: 12px;
          border-radius: 4px;
          overflow-x: hidden;
          box-sizing: border-box;
        }
      }
    }
  }
  
  .distribution-card {
    margin-top: 16px;
    
    .distribution-chart {
      .distribution-item {
        display: flex;
        align-items: center;
        margin-bottom: 8px;
        
        .distribution-label {
          width: 60px;
          font-size: 13px;
          color: #606266;
          flex-shrink: 0;
        }
        
        .distribution-bar {
          flex: 1;
          height: 20px;
          background: #ebeef5;
          border-radius: 4px;
          overflow: hidden;
          margin: 0 12px;
          min-width: 0;
          
          .distribution-fill {
            height: 100%;
            background: #409eff;
            transition: width 0.3s;
          }
        }
        
        .distribution-value {
          width: 100px;
          font-size: 13px;
          color: #909399;
          text-align: right;
          flex-shrink: 0;
        }
      }
    }
  }
  
  .profit { color: #f56c6c; }
  .loss { color: #67c23a; }

  // 表格单元格内容不换行
  :deep(.nowrap-table) {
    .el-table__header th,
    .el-table__body td {
      white-space: nowrap;
    }
  }
  
  .win-loss-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    
    .stat-item {
      flex: 1;
      min-width: 100px;
      text-align: center;
      padding: 12px;
      background: #f5f7fa;
      border-radius: 4px;
      
      .stat-label {
        font-size: 13px;
        color: #909399;
        margin-bottom: 6px;
      }
      
      .stat-value {
        font-size: 20px;
        font-weight: bold;
        color: #303133;
        
        &.profit { color: #f56c6c; }
        &.loss { color: #67c23a; }
      }
    }
  }
}

/* ===== 移动端卡片列表容器（m-card 设计系统）===== */
.mobile-card-list {
  display: flex;
  flex-direction: column;
  gap: 0;

  /* sim-m-* 类配合 m-card 使用，覆盖 padding/margin 使间距更紧凑 */
  .sim-m-pos-card,
  .sim-m-order-card,
  .sim-m-trade-card,
  .sim-m-ttrade-card,
  .sim-m-risk-card,
  .sim-m-hist-card,
  .sim-m-pnl-card {
    padding: 12px 14px;
    margin-bottom: 8px;
  }
}

@media screen and (max-width: 768px) {
  .sim-trading {
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    padding: 0 !important;
    background: var(--m-bg, #f5f7fa) !important;

    .page-header {
      display: none !important;
    }

    .account-overview, .stats-row {
      :deep(.el-col) { margin-bottom: 4px; }
    }

    .stat-card {
      :deep(.el-card__body) { padding: 6px 4px; }

      .stat-content {
        .stat-label { font-size: 11px; margin-bottom: 2px; }
        .stat-value { font-size: 14px; }
        &.small .stat-value { font-size: 13px; }
      }
    }

    /* Tabs — 去除 border-card 样式，节省垂直空间 */
    .main-tabs {
      :deep(.el-tabs--border-card) { border: none !important; }
      :deep(.el-tabs--border-card > .el-tabs__header) { background: var(--m-surface, #fff) !important; border: none !important; margin-bottom: 0; box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important; }
      :deep(.el-tabs__nav-wrap) { overflow-x: auto; -webkit-overflow-scrolling: touch; white-space: nowrap; scrollbar-width: none; clear: none !important; }
      :deep(.el-tabs__nav-wrap::-webkit-scrollbar) { display: none; }
      :deep(.el-tabs__nav-wrap::after) { height: 0 !important; }
      :deep(.el-tabs__nav-scroll) { padding: 0 8px; overflow: visible; }
      :deep(.el-tabs__item) { padding: 0 12px !important; font-size: 13px !important; height: 40px !important; line-height: 40px !important; flex-shrink: 0; border-bottom-color: transparent !important; color: var(--m-text3, #8e99ab) !important; white-space: nowrap; }
      :deep(.el-tabs__item.is-active) { color: var(--m-accent, #409eff) !important; font-weight: 600; }
      :deep(.el-tabs__active-bar) { height: 3px !important; border-radius: 3px 3px 0 0; background: var(--m-accent, #409eff) !important; }
      :deep(.el-tabs--border-card > .el-tabs__content) { padding: 6px 10px 8px !important; border: none !important; overflow: visible !important; }
      :deep(.el-tabs__content > .el-tab-pane:not([style*="display: none"])) { overflow: visible !important; }

      .tab-toolbar { margin-bottom: 6px; flex-wrap: wrap; gap: 6px; }
    }

    /* 移动端卡片列表：flex:1 占满 tab 内容区并自身滚动 */
    .mobile-card-list {
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      -webkit-overflow-scrolling: touch;
      padding-bottom: 8px;

      /* m-card 设计系统覆盖：紧凑间距 */
      .sim-m-pos-card,
      .sim-m-order-card,
      .sim-m-trade-card,
      .sim-m-ttrade-card,
      .sim-m-risk-card,
      .sim-m-hist-card,
      .sim-m-pnl-card {
        padding: 10px 12px;
        margin-bottom: 6px;
        border-radius: 10px !important;
      }

      /* m-stock-row 内部字体适配 */
      .sname { font-size: 13px !important; }
      .scode { font-size: 10px !important; }
    }

    /* Pagination — 紧靠底部导航栏 */
    .pagination-bar {
      background: var(--m-surface, #fff) !important;
      box-shadow: 0 -2px 6px rgba(0,0,0,0.06) !important;
      justify-content: center !important;
      padding: 4px 4px var(--m-tab, 60px) 16px !important;
      flex-shrink: 0;
      margin-top: 4px;
      min-height: 28px !important;
      border-radius: 10px 10px 0 0;
    }
    .pagination-bar :deep(.el-pagination) { font-size: 11px !important; flex-wrap: wrap; justify-content: center; gap: 2px; }
    .pagination-bar :deep(.el-pager li) { min-width: 24px !important; height: 24px !important; line-height: 24px !important; font-size: 11px !important; margin: 0 1px !important; border-radius: 4px !important; }
    .pagination-bar :deep(.el-pagination button) { min-width: 24px !important; height: 24px !important; line-height: 24px !important; border-radius: 4px !important; }
    .pagination-bar :deep(.el-pagination__sizes) { display: none !important; }
    .pagination-bar :deep(.el-pagination__jump) { display: none !important; }

    /* Strategy panel — 移动端策略配置 */
    .strategy-panel {
      .mob-config-card {
        margin-bottom: 6px !important;
        border-radius: 10px !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;

        :deep(.el-card__header) { padding: 6px 12px !important; font-size: 13px !important; border-bottom: 1px solid var(--m-border, #e0e4ea) !important; }
        :deep(.el-card__body) { padding: 8px 10px !important; overflow: hidden; }

        .mob-config-list {
          .mob-config-item {
            margin-bottom: 10px;

            &:last-child { margin-bottom: 6px; }

            .mob-config-label {
              display: block;
              font-size: 12px;
              color: var(--m-text3, #8e99ab) !important;
              margin-bottom: 4px;
            }

            :deep(.el-slider) { margin-top: 2px; }
          }

          .mob-config-switch {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 6px 0;
            border-bottom: 1px dashed var(--m-border, #e0e4ea);

            .mob-config-label {
              display: inline;
              margin-bottom: 0;
              font-size: 13px;
              color: var(--m-text, #1a2332) !important;
            }
          }

          .mob-config-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px 6px;
            margin-top: 10px;

            .mob-config-sub {
              display: flex;
              flex-direction: column;
              align-items: center;
              min-width: 0;

              .mob-config-label {
                margin-bottom: 4px;
                font-size: 11px;
                white-space: nowrap;
              }

              :deep(.el-input-number) { width: 100%; }
            }
          }
        }
      }

      /* 移动端策略结果 */
      .mob-strategy-result {
        margin-bottom: 6px !important;
        border-radius: 10px !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;

        :deep(.el-card__header) { padding: 6px 12px !important; font-size: 13px !important; border-bottom: 1px solid var(--m-border, #e0e4ea) !important; }
        :deep(.el-card__body) { padding: 8px 10px !important; overflow: hidden; }

        .mob-strat-header {
          flex-direction: column;
          align-items: flex-start;
          gap: 6px;

          .el-button { width: 100%; border-radius: 6px !important; min-height: 30px !important; font-size: 12px !important; }
        }

        .mob-market-analysis {
          display: flex;
          justify-content: center;
          gap: 6px;
          margin-bottom: 10px;
          flex-wrap: wrap;
        }

        .mob-strat-summary {
          display: flex;
          gap: 8px;
          margin-bottom: 10px;

          .mob-summary-item {
            flex: 1;
            text-align: center;
            padding: 8px 4px;
            background: var(--m-surface2, #f0f2f5);
            border-radius: 6px;

            .mob-summary-label {
              display: block;
              font-size: 11px;
              color: var(--m-text3, #8e99ab) !important;
              margin-bottom: 2px;
            }

            .mob-summary-value {
              display: block;
              font-size: 15px;
              font-weight: 700;
              color: var(--m-text, #1a2332) !important;
            }
          }
        }

        .mob-buy-signal-card,
        .mob-sell-signal-card {
          background: var(--m-surface, #fff);
          border: 1px solid var(--m-border, #e0e4ea);
          border-radius: 8px;
          padding: 8px 10px;
          margin-bottom: 6px;
          overflow: hidden;

          .mob-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4px;
            min-width: 0;

            .mob-stock-name {
              font-size: 13px;
              font-weight: 600;
              color: var(--m-text, #1a2332) !important;
              overflow: hidden;
              text-overflow: ellipsis;
              white-space: nowrap;
              min-width: 0;

              .mob-stock-code {
                font-weight: 400;
                font-size: 11px;
                color: var(--m-text3, #8e99ab) !important;
                margin-left: 4px;
              }
            }
          }

          .mob-card-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: var(--m-text2, #5c6b7f) !important;
            min-width: 0;

            .mob-label { color: var(--m-text3, #8e99ab) !important; min-width: 36px; flex-shrink: 0; }
          }

          .mob-reason-text {
            display: flex;
            align-items: flex-start;
            font-size: 11px;
            color: var(--m-text3, #8e99ab) !important;
            margin-top: 4px;
            gap: 4px;
            overflow: hidden;

            .mob-label { flex-shrink: 0; min-width: 32px; }
            span:last-child {
              flex: 1;
              min-width: 0;
              word-break: break-all;
              overflow: hidden;
              text-overflow: ellipsis;
              display: -webkit-box;
              -webkit-line-clamp: 3;
              -webkit-box-orient: vertical;
            }
          }
        }

        .mob-strat-report {
          :deep(.el-card__body) { padding: 8px 10px !important; overflow: hidden; }
          :deep(.el-card__header) { padding: 6px 10px !important; font-size: 13px !important; border-bottom: 1px solid var(--m-border, #e0e4ea) !important; }

          .report-content {
            font-size: 12px;
            line-height: 1.5;
            padding: 8px;
            background: var(--m-surface2, #f0f2f5);
            border-radius: 4px;
            max-height: 300px;
            overflow-y: auto;
            overflow-x: hidden;
            word-break: break-all;
          }
        }
      }

      /* 移动端策略历史 */
      .mob-history-card {
        :deep(.el-card__body) { padding: 10px 12px !important; }

        .mob-history-item {
          background: var(--m-surface, #fff);
          border: 1px solid var(--m-border, #e0e4ea);
          border-radius: 8px;
          padding: 8px 10px;
          margin-bottom: 6px;

          &:last-child { margin-bottom: 0; }

          .mob-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 4px;
          }

          .mob-card-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: var(--m-text2, #5c6b7f) !important;
            margin-bottom: 4px;
          }

          .mob-reason-text {
            display: flex;
            align-items: flex-start;
            font-size: 11px;
            color: var(--m-text3, #8e99ab) !important;
            gap: 4px;
            margin-bottom: 4px;
            overflow: hidden;

            .mob-label { flex-shrink: 0; min-width: 32px; }
            span:last-child {
              flex: 1;
              min-width: 0;
              word-break: break-all;
              overflow: hidden;
              text-overflow: ellipsis;
              display: -webkit-box;
              -webkit-line-clamp: 3;
              -webkit-box-orient: vertical;
            }
          }

          .mob-card-footer {
            display: flex;
            justify-content: flex-end;
            gap: 8px;
            padding-top: 4px;
            border-top: 1px solid var(--m-surface2, #f0f2f5);
          }
        }
      }
    }

    .distribution-card {
      margin-bottom: 6px !important;
      border-radius: 10px !important;
      box-shadow: 0 1px 4px rgba(0,0,0,0.04) !important;

      :deep(.el-card__header) { padding: 6px 12px !important; font-size: 13px !important; border-bottom: 1px solid var(--m-border, #e0e4ea) !important; }
    }

    .distribution-card .distribution-chart .distribution-item {
      flex-wrap: wrap; gap: 4px;

      .distribution-label { width: auto; font-size: 12px; color: var(--m-text2, #5c6b7f) !important; }
      .distribution-bar { order: 3; width: 100%; margin: 4px 0 0 0; }
      .distribution-value { width: auto; flex: 1; text-align: right; font-size: 12px; color: var(--m-text3, #8e99ab) !important; }
    }

    .win-loss-stats .stat-item {
      min-width: calc(33.33% - 6px); padding: 8px;
      background: var(--m-surface2, #f0f2f5);

      .stat-label { font-size: 11px; color: var(--m-text3, #8e99ab) !important; }
      .stat-value { font-size: 15px; color: var(--m-text, #1a2332) !important; }
    }

    /* 按钮样式统一 */
    :deep(.el-button) { min-height: 30px !important; padding: 4px 12px !important; font-size: 12px !important; border-radius: 6px !important; }
    :deep(.el-button--small) { min-height: 26px !important; padding: 3px 10px !important; font-size: 11px !important; border-radius: 6px !important; }

    /* Radio group */
    :deep(.el-radio-group) .el-radio-button__inner { padding: 4px 10px !important; font-size: 12px !important; border-radius: 12px !important; min-height: 26px !important; }

    /* Checkbox group */
    :deep(.el-checkbox-group) .el-checkbox-button__inner { padding: 4px 10px !important; font-size: 12px !important; border-radius: 12px !important; min-height: 26px !important; }

    /* Date picker */
    :deep(.el-date-editor) { height: 30px !important; }
    :deep(.el-date-editor .el-input__wrapper) { padding: 2px 6px !important; height: 30px !important; border-radius: 6px !important; }

    /* Input/Select */
    :deep(.el-input__wrapper),
    :deep(.el-select .el-input__wrapper) { border-radius: 6px !important; box-shadow: none !important; border: 1px solid var(--m-border, #e0e4ea) !important; height: 30px !important; }

    /* Tag */
    :deep(.el-tag) { border-radius: 6px !important; font-size: 11px !important; padding: 2px 8px !important; height: 20px !important; line-height: 16px !important; }
  }

  /* 移动端对话框底部弹出 */
  :deep(.el-dialog) {
    position: fixed !important;
    top: auto !important;
    bottom: 0 !important;
    left: 0 !important;
    right: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    margin: 0 !important;
    border-radius: 12px 12px 0 0;
    max-height: 85vh;
    overflow-y: auto;

    .el-dialog__header { padding: 14px 16px 10px; }
    .el-dialog__body { padding: 10px 16px; }
    .el-dialog__footer { padding: 10px 16px var(--m-tab-h, 60px) 18px; }

    .el-form-item { margin-bottom: 14px; }
    .el-input-number, .el-input { width: 100%; }
    :deep(.el-input__wrapper) { border-radius: 6px !important; height: 30px !important; }
  }

  /* 策略报告：移动端紧凑显示，确保单页可见更多内容 */
  .sim-strategy-drawer .strategy-report {
    overflow: hidden;
    max-width: 100%;

    :deep(.el-card__header) { padding: 6px 12px !important; font-size: 13px !important; border-bottom: 1px solid var(--m-border, #e0e4ea) !important; }
    :deep(.el-card__body) { padding: 8px 12px !important; }

    pre.report-content {
      padding: 10px 12px;
      font-size: 12.5px;
      line-height: 1.65;
      max-height: 50vh;
      overflow-y: auto;
      overflow-x: hidden;
      white-space: pre-wrap;
      word-break: break-all;
      overflow-wrap: break-word;
      width: 100%;
      min-width: 0;
      max-width: 100%;
      box-sizing: border-box;
    }
  }

  /* m-card 设计系统覆盖：紧凑间距 */
  .mobile-card-list {
    .sim-m-pos-card,
    .sim-m-order-card,
    .sim-m-trade-card,
    .sim-m-ttrade-card,
    .sim-m-risk-card,
    .sim-m-hist-card,
    .sim-m-pnl-card {
      padding: 10px 12px;
      margin-bottom: 6px;
    }

    /* m-stock-row 内部字体适配 */
    .sname { font-size: 13px !important; }
    .scode { font-size: 10px !important; }
  }
}

@media screen and (max-width: 480px) {
  .sim-trading {
    top: 0 !important;
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    padding: 4px;

    /* 移动端 header 已有标题，隐藏页面内部重复标题 */
    .page-header { margin-bottom: 0 !important; justify-content: flex-end !important; }
    .page-title { display: none !important; }

    .stat-card :deep(.el-card__body) { padding: 5px 3px; }
    .stat-content .stat-label { font-size: 10px !important; }
    .stat-content .stat-value { font-size: 13px !important; }
    .stat-content.small .stat-value { font-size: 13px !important; }

    .main-tabs :deep(.el-tabs__item) { padding: 0 6px !important; font-size: 12px !important; height: 34px; line-height: 34px; }

    /* 超小屏策略配置改为纵向 */
    .strategy-panel .mob-config-card .mob-config-list .mob-config-grid {
      grid-template-columns: 1fr 1fr;
    }

    /* 超小屏盈亏统计改为2列 */
    .win-loss-stats .stat-item {
      min-width: calc(50% - 6px) !important;
    }

    /* 超小屏策略报告：更紧凑 */
    .sim-strategy-drawer .strategy-report pre.report-content {
      padding: 8px 10px;
      font-size: 12px;
      line-height: 1.6;
      max-height: 45vh;
      overflow-x: hidden;
    }

    /* m-stats-row 超小屏改为2列 */
    .m-stat-card { padding: 8px 4px; }
    .m-stat-card .val { font-size: 13px !important; }
    .m-stat-card .lbl { font-size: 8px !important; }
  }

  /* m-card 超小屏紧凑 */
  .mobile-card-list .sim-m-pos-card,
  .mobile-card-list .sim-m-order-card,
  .mobile-card-list .sim-m-trade-card,
  .mobile-card-list .sim-m-ttrade-card,
  .mobile-card-list .sim-m-risk-card,
  .mobile-card-list .sim-m-hist-card,
  .mobile-card-list .sim-m-pnl-card {
    padding: 8px 10px;
  }

  :deep(.el-dialog) { max-height: 90vh; }
}

/* 策略摘要卡片 */
.strategy-summary-card {
  margin-bottom: 16px;
}
.desktop-summary-row,
.mob-summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
/* 仓位布局列：短/中/长三色块 */
.pos-layout-cell {
  display: inline-flex;
  gap: 2px;
  font-size: 11px;
  line-height: 1;
}
.pos-chip {
  display: inline-block;
  padding: 2px 4px;
  border-radius: 3px;
  color: #fff;
  font-weight: 600;
  min-width: 28px;
  text-align: center;
}
.pos-short { background: #f56c6c; }
.pos-mid   { background: #e6a23c; }
.pos-long  { background: #67c23a; }

/* 做T统计卡片条 */
.ttrade-stats-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
}
.ttrade-stat-item {
  flex: 1 1 18%;
  min-width: 130px;
  padding: 6px 10px;
  background: #fff;
  border-radius: 4px;
  border: 1px solid #f0f0f0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ttrade-stat-label {
  font-size: 12px;
  color: #909399;
}
.ttrade-stat-value {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.ttrade-stat-value.profit { color: #f56c6c; }
.ttrade-stat-value.loss { color: #67c23a; }

/* ── SimTrading 页面移动端覆盖 (max-width: 768px) ─────────── */
@media (max-width: 768px) {
  .sim-trading { padding: 0; background: var(--m-bg, #f5f7fa); }
  .sim-trading :deep(.el-card) { border-radius: var(--m-card-radius, 16px); box-shadow: var(--m-card-shadow, 0 2px 8px rgba(0,0,0,0.06)); }
  .sim-trading :deep(.el-table) { min-width: 600px; }
  .sim-trading :deep(.el-button) { min-height: 36px; font-size: 12px; border-radius: 8px; }
  .sim-trading .section-title { font-size: 14px; padding: 10px 0 6px; }

  /* m-stats-row 移动端统计卡片紧凑 */
  .sim-trading > .m-stats-row { gap: 4px; margin-bottom: 6px; }
  .m-stat-card { padding: 6px 4px; }
  .m-stat-card .val { font-size: 12px !important; }
  .m-stat-card .lbl { font-size: 8px !important; }

  /* m-section-header 紧凑 */
  .m-section-header { padding: 8px 0 4px; font-size: 14px; }

  /* 做T统计桌面端在移动端隐藏（已用 m-stats-row 替代）*/
  .ttrade-stats-bar { display: none !important; }
}

</style>