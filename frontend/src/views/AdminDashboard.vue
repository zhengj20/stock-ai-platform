<template>
  <div class="admin-container">
    <!-- 统计卡片 -->
    <el-row :gutter="8" class="stats-row">
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ stats.total_users }}</div>
          <div class="stat-label">活跃用户</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ stats.total_sessions }}</div>
          <div class="stat-label">对话会话</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ stats.total_messages }}</div>
          <div class="stat-label">消息总数</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ stats.unused_invites }}</div>
          <div class="stat-label">可用邀请码</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 用户管理 -->
    <el-card class="section-card">
      <template #header>
        <div class="card-header admin-section-header">
          <span><el-icon><User /></el-icon> 用户管理</span>
          <div class="admin-header-actions">
            <el-button type="primary" size="small" @click="openCreateDialog">
              <el-icon><Plus /></el-icon> 创建用户
            </el-button>
            <el-input
              v-model="userSearch"
              placeholder="搜索用户名或邮箱..."
              clearable
              class="admin-search-input"
              @input="onUserSearchInput"
            />
          </div>
        </div>
      </template>

      <!-- 移动端：用户卡片列表 -->
      <template v-if="isMobile">
        <div class="mob-user-list">
          <div v-for="row in users" :key="row.id" class="mob-user-card">
            <div class="mob-uc-header">
              <span class="mob-uc-name">{{ row.username }}</span>
              <el-tag :type="row.role === 'admin' ? 'danger' : ''" size="small">{{ row.role === 'admin' ? '管理员' : '普通' }}</el-tag>
            </div>
            <div class="mob-uc-row"><span class="mob-label">邮箱</span><span>{{ row.email || '-' }}</span></div>
            <div v-if="row.invite_code" class="mob-uc-row"><span class="mob-label">邀请码</span><span>{{ row.invite_code }}</span></div>
            <div class="mob-uc-row">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">{{ row.status === 'active' ? '正常' : '已禁用' }}</el-tag>
              <span :class="row.is_online ? 'online-dot' : 'offline-dot'" class="status-dot"></span>
            </div>
            <div v-if="row.expiry_date" class="mob-uc-row">
              <span class="mob-label">有效期</span>
              <span>{{ formatDateShort(row.expiry_start_date || row.created_at) }} ~ {{ formatDateShort(row.expiry_date) }}</span>
              <el-tag :type="getExpiryTagType(row)" size="small">{{ getRemainingDays(row) }}天</el-tag>
            </div>
            <div v-else class="mob-uc-row"><span class="mob-label">有效期</span><span style="color:#909399;">永久</span></div>
            <div class="mob-uc-footer">
              <span style="font-size:11px;color:#c0c4cc;">注册 {{ formatDate(row.created_at) }}</span>
              <div class="action-btns mob-action-btns">
                <el-button link type="primary" size="small" @click="openEditUser(row)">编辑</el-button>
                <el-button link type="warning" size="small" @click="openResetPassword(row)">重置密码</el-button>
                <el-popconfirm v-if="row.id !== currentUserId" title="确定禁用该用户？" @confirm="toggleUserStatus(row)">
                  <template #reference>
                    <el-button link :type="row.status === 'active' ? 'danger' : 'success'" size="small">{{ row.status === 'active' ? '禁用' : '启用' }}</el-button>
                  </template>
                </el-popconfirm>
                <el-popconfirm v-if="row.id !== currentUserId" title="确定删除该用户？此操作不可恢复！" confirm-button-text="确定删除" confirm-button-type="danger" @confirm="deleteUser(row)">
                  <template #reference>
                    <el-button link type="danger" size="small">删除</el-button>
                  </template>
                </el-popconfirm>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 桌面端：用户表格 -->
      <el-table v-else :data="users" stripe style="width: 100%" border>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="username" label="用户名" min-width="120" show-overflow-tooltip />
        <el-table-column prop="invite_code" label="邀请码" min-width="120" show-overflow-tooltip />
        <el-table-column prop="email" label="邮箱" min-width="150" show-overflow-tooltip />
        <el-table-column prop="remark" label="备注" min-width="150" show-overflow-tooltip />
        <el-table-column prop="role" label="角色" width="85">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : ''" size="small">{{ row.role === 'admin' ? '管理员' : '普通用户' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="85">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">{{ row.status === 'active' ? '正常' : '已禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="在线" width="70" align="center">
          <template #default="{ row }"><span :class="row.is_online ? 'online-dot' : 'offline-dot'" class="status-dot"></span></template>
        </el-table-column>
        <el-table-column prop="created_at" label="注册时间" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="last_login" label="最后登录" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.last_login ? formatDate(row.last_login) : '从未登录' }}</template>
        </el-table-column>
        <el-table-column label="有效期" min-width="180">
          <template #default="{ row }">
            <template v-if="row.expiry_date">
              <div class="expiry-info">
                <span style="font-size: 12px; color: #606266;">{{ formatDateShort(row.expiry_start_date || row.created_at) }} ~ {{ formatDateShort(row.expiry_date) }}</span>
                <el-tag :type="getExpiryTagType(row)" size="small" style="margin-left: 4px;">{{ getRemainingDays(row) }}天</el-tag>
              </div>
            </template>
            <span v-else style="color: #909399; font-size: 12px;">永久</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" fixed="right" width="300">
          <template #default="{ row }">
            <div class="action-btns">
              <el-button link type="primary" size="small" @click="openEditUser(row)">编辑</el-button>
              <el-button link type="warning" size="small" @click="openResetPassword(row)">重置密码</el-button>
              <el-popconfirm v-if="row.id !== currentUserId" title="确定禁用该用户？" @confirm="toggleUserStatus(row)">
                <template #reference>
                  <el-button link :type="row.status === 'active' ? 'danger' : 'success'" size="small">{{ row.status === 'active' ? '禁用' : '启用' }}</el-button>
                </template>
              </el-popconfirm>
              <el-popconfirm v-if="row.id !== currentUserId" title="确定删除该用户？此操作不可恢复！" confirm-button-text="确定删除" confirm-button-type="danger" @confirm="deleteUser(row)">
                <template #reference>
                  <el-button link type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination v-model:current-page="userPage" :page-size="20" :total="userTotal" layout="prev, pager, next" small @change="onUserPageChange" />
      </div>
    </el-card>

    <!-- 模拟交易初始金额配置 -->
    <el-card class="section-card">
      <template #header>
        <div class="card-header admin-section-header">
          <span><el-icon><Money /></el-icon> 模拟交易资金管理</span>
          <div class="admin-header-actions">
            <el-button size="small" @click="loadInitialCapital" :loading="initialCapitalLoading"><el-icon><Refresh /></el-icon> 刷新</el-button>
            <template v-if="!initialCapitalEditing">
              <el-button type="primary" size="small" plain @click="startEditInitialCapital"><el-icon><Edit /></el-icon> 编辑初始金额</el-button>
              <el-button type="success" size="small" @click="openDepositDialog"><el-icon><Plus /></el-icon> 入金</el-button>
            </template>
            <template v-else>
              <el-button size="small" @click="cancelEditInitialCapital">取消</el-button>
              <el-button type="primary" size="small" @click="saveInitialCapital" :loading="initialCapitalSaving">保存</el-button>
            </template>
          </div>
        </div>
      </template>

      <el-form :model="initialCapitalForm" :label-width="isMobile ? '90px' : '140px'" class="admin-capital-form">
        <el-form-item label="初始金额（元）">
          <el-input-number v-model="initialCapitalForm.initial_capital" :min="1000" :max="100000000" :step="10000" :precision="2" :disabled="!initialCapitalEditing" class="admin-capital-input" />
        </el-form-item>
      </el-form>
      <div class="admin-hint">范围 1,000 ~ 100,000,000</div>
      <div v-if="!initialCapitalEditing" class="admin-info-box">
        <span class="admin-info-icon">ℹ️</span>
        <div class="admin-info-text">
          <strong>初始金额为账户盈亏计算基准</strong><br />
          默认 100,000 元。如需调整，请点击右上角「编辑初始金额」。修改后若账户已有交易/持仓，仅影响后续盈亏基准，建议重置账户以完整生效。
        </div>
      </div>
      <template v-if="initialCapitalEditing">
        <div v-if="initialCapitalHint" class="admin-info-box admin-warning-box">
          <span class="admin-info-icon">⚠️</span>
          <div class="admin-info-text">{{ initialCapitalHint }}</div>
        </div>
        <div class="admin-hint">说明：若账户已有持仓/交易，仅更新盈亏计算基准，不影响现有资金；需点「重置账户」后才能让新初始金额完整生效。</div>
      </template>
    </el-card>

    <!-- 入金对话框 -->
    <el-dialog v-model="depositDialogVisible" title="账户入金" width="420px">
      <el-form :model="depositForm" label-width="100px">
        <el-form-item label="入金金额" required>
          <el-input-number v-model="depositForm.amount" :min="100" :max="100000000" :step="10000" :precision="2" style="width: 100%;" placeholder="请输入入金金额" />
          <div class="admin-hint">范围 100 ~ 100,000,000 元；入金后账户可用资金将立即增加。</div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="depositForm.remark" type="textarea" :rows="2" placeholder="可选，如：月度加仓" maxlength="200" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="depositDialogVisible = false">取消</el-button>
        <el-button type="success" :loading="depositSaving" @click="confirmDeposit">确认入金</el-button>
      </template>
    </el-dialog>

    <!-- AI配额管理 -->
    <el-card class="section-card">
      <template #header>
        <div class="card-header admin-section-header">
          <span><el-icon><Ticket /></el-icon> 邀请码管理</span>
          <el-button type="primary" size="small" @click="openGenerateDialog"><el-icon><Plus /></el-icon> 生成邀请码</el-button>
        </div>
      </template>

      <!-- 移动端：邀请码卡片 -->
      <template v-if="isMobile">
        <div class="mob-invite-list">
          <div v-for="row in inviteCodes" :key="row.id" class="mob-invite-card">
            <div class="mob-ic-header">
              <code>{{ row.code }}</code>
              <el-tag :type="row.used_at ? 'info' : 'success'" size="small">{{ row.used_at ? '已使用' : '未使用' }}</el-tag>
            </div>
            <div class="mob-ic-row"><span class="mob-label">创建</span><span>{{ formatDate(row.created_at) }}</span></div>
            <div v-if="row.used_at" class="mob-ic-row"><span class="mob-label">使用</span><span>{{ formatDate(row.used_at) }}</span></div>
            <div class="mob-ic-footer">
              <el-button size="small" link @click="copyCode(row.code)">复制</el-button>
              <el-popconfirm v-if="!row.used_at" title="确定删除该邀请码？" @confirm="deleteInviteCode(row.id)">
                <template #reference><el-button size="small" type="danger" link>删除</el-button></template>
              </el-popconfirm>
            </div>
          </div>
        </div>
      </template>

      <!-- 桌面端：邀请码表格 -->
      <el-table v-else :data="inviteCodes" stripe style="width: 100%" border>
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="邀请码" min-width="240">
          <template #default="{ row }">
            <div class="code-cell"><code>{{ row.code }}</code><el-button size="small" link @click="copyCode(row.code)">复制</el-button></div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="row.used_at ? 'info' : 'success'" size="small">{{ row.used_at ? '已使用' : '未使用' }}</el-tag></template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="使用时间" min-width="180">
          <template #default="{ row }">{{ row.used_at ? formatDate(row.used_at) : '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" fixed="right" width="100">
          <template #default="{ row }">
            <el-popconfirm v-if="!row.used_at" title="确定删除该邀请码？" @confirm="deleteInviteCode(row.id)">
              <template #reference><el-button size="small" type="danger" plain>删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- LLM配置 -->
    <el-card class="section-card">
      <template #header>
        <div class="card-header">
          <span><el-icon><Setting /></el-icon> LLM配置</span>
          <div style="display: flex; gap: 8px;">
            <template v-if="!llmEditing">
              <el-button size="small" @click="loadLLMConfig" :loading="llmLoading">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
              <el-button type="warning" size="small" @click="testLLMConnection" :loading="llmTesting">测试连接</el-button>
              <el-button type="primary" size="small" plain @click="startEditLLM">编辑配置</el-button>
            </template>
            <template v-else>
              <el-button size="small" @click="cancelEditLLM">取消</el-button>
              <el-button type="primary" size="small" @click="saveLLMConfig" :loading="llmSaving">保存</el-button>
            </template>
          </div>
        </div>
      </template>

      <!-- 只读视图 -->
      <div v-if="!llmEditing" class="config-read-only">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="启用状态">
            <el-tag :type="llmForm.enabled ? 'success' : 'info'" size="small">{{ llmForm.enabled ? '已启用' : '已禁用' }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="服务类型">
            <el-tag size="small">{{ providerLabel(llmForm.provider) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="模型名称">{{ llmForm.model || '-' }}</el-descriptions-item>
          <el-descriptions-item label="API地址" :span="2">{{ llmForm.base_url || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Temperature">{{ llmForm.temperature?.toFixed(1) ?? '0.7' }}</el-descriptions-item>
          <el-descriptions-item label="Max Tokens">{{ llmForm.max_tokens ?? 8192 }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <!-- 编辑视图 -->
      <el-form v-else :model="llmForm" label-width="120px" style="max-width: 700px;">
        <el-form-item label="启用LLM服务">
          <el-switch v-model="llmForm.enabled" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px;">{{ llmForm.enabled ? '已启用' : '已禁用' }}</span>
        </el-form-item>
        <el-form-item label="服务类型">
          <el-select v-model="llmForm.provider" style="width:100%" @change="onLLMProviderChange">
            <el-option label="LM Studio（本地）" value="lm-studio" />
            <el-option label="vLLM（远程）" value="vllm" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="API地址">
          <el-input v-model="llmForm.base_url" placeholder="http://localhost:1234/v1" />
          <span style="margin-left: 8px; color: #909399; font-size: 12px;">OpenAI兼容API地址</span>
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="llmForm.model" placeholder="如 Qwen3.6-27B" />
        </el-form-item>
        <el-form-item label="Temperature">
          <el-slider v-model="llmForm.temperature" :min="0" :max="2" :step="0.1" :format-tooltip="(v) => v.toFixed(1)" style="width: 300px;" />
          <span style="margin-left: 8px; color: #909399;">{{ llmForm.temperature.toFixed(1) }}</span>
        </el-form-item>
        <el-form-item label="Max Tokens">
          <el-input-number v-model="llmForm.max_tokens" :min="1" :max="65536" style="width: 150px;" />
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 定时任务调度配置 -->
    <el-card class="section-card">
      <template #header>
        <div class="card-header">
          <span><el-icon><Clock /></el-icon> 定时任务调度配置</span>
          <div style="display: flex; gap: 8px;">
            <template v-if="!schedulerEditing">
              <el-button size="small" @click="loadSchedulerConfig" :loading="schedulerLoading">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
              <el-button type="primary" size="small" plain @click="startEditScheduler">编辑配置</el-button>
            </template>
            <template v-else>
              <el-button size="small" @click="cancelEditScheduler">取消</el-button>
              <el-button type="primary" size="small" @click="saveSchedulerConfig" :loading="schedulerSaving">保存</el-button>
            </template>
          </div>
        </div>
      </template>

      <!-- 只读视图 -->
      <div v-if="!schedulerEditing" class="config-read-only">
        <el-row :gutter="24">
          <el-col :xs="24" :sm="12">
            <div class="scheduler-block">
              <h4 style="margin: 0 0 16px 0; color: #303133;">
                <el-icon><Document /></el-icon> AI复盘报告定时生成
              </h4>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="启用状态">
                  <el-tag :type="schedulerForm.report_enabled ? 'success' : 'info'" size="small">{{ schedulerForm.report_enabled ? '已启用' : '已禁用' }}</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="执行时间">{{ schedulerForm.report_time || '15:30' }}</el-descriptions-item>
              </el-descriptions>
            </div>
          </el-col>
          <el-col :xs="24" :sm="12">
            <div class="scheduler-block">
              <h4 style="margin: 0 0 16px 0; color: #303133;">
                <el-icon><TrendCharts /></el-icon> AI股票推荐定时生成
              </h4>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="启用状态">
                  <el-tag :type="schedulerForm.pick_enabled ? 'success' : 'info'" size="small">{{ schedulerForm.pick_enabled ? '已启用' : '已禁用' }}</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="执行时间">{{ schedulerForm.pick_time || '15:15' }}</el-descriptions-item>
              </el-descriptions>
            </div>
          </el-col>
        </el-row>

        <el-row :gutter="24" style="margin-top: 16px;">
          <el-col :span="24">
            <div class="scheduler-block">
              <h4 style="margin: 0 0 16px 0; color: #303133;">
                <el-icon><Clock /></el-icon> 模拟交易 & 行情定时任务
              </h4>
              <el-descriptions :column="isMobile ? 1 : (screenWidth <= 768 ? 2 : 3)" border size="small">
                <el-descriptions-item label="上午 T+1 解锁">{{ schedulerForm.t1_unlock_morning_time }}</el-descriptions-item>
                <el-descriptions-item label="交易日判断时间">{{ schedulerForm.trading_day_check_time }}</el-descriptions-item>
                <el-descriptions-item label="策略执行间隔">{{ schedulerForm.strategy_exec_interval_min }} 分钟</el-descriptions-item>
                <el-descriptions-item label="午间策略调整">{{ schedulerForm.midday_strategy_time }}</el-descriptions-item>
                <el-descriptions-item label="盘中策略-上午">{{ schedulerForm.intraday_strategy_time_1 }}</el-descriptions-item>
                <el-descriptions-item label="盘中策略-下午">{{ schedulerForm.intraday_strategy_time_2 }}</el-descriptions-item>
                <el-descriptions-item label="收盘前平短仓">
                  <el-tag :type="schedulerForm.auto_close_short_enabled ? 'success' : 'info'" size="small" style="margin-right:6px;">{{ schedulerForm.auto_close_short_enabled ? '已启用' : '已禁用' }}</el-tag>
                  <span v-if="schedulerForm.auto_close_short_enabled">{{ schedulerForm.auto_close_short_time }}</span>
                </el-descriptions-item>
                <el-descriptions-item label="收盘缓存时间">{{ schedulerForm.closing_cache_time }}</el-descriptions-item>
                <el-descriptions-item label="复盘+次日策略">{{ schedulerForm.review_strategy_time }}</el-descriptions-item>
                <el-descriptions-item label="清理报告时间">{{ schedulerForm.cleanup_report_time }}</el-descriptions-item>
                <el-descriptions-item label="清理对话时间">{{ schedulerForm.cleanup_conversation_time }}</el-descriptions-item>
              </el-descriptions>
            </div>
          </el-col>
        </el-row>

        <el-row :gutter="24" style="margin-top: 16px;">
          <el-col :span="24">
            <div class="scheduler-block">
              <h4 style="margin: 0 0 16px 0; color: #303133;">
                <el-icon><Cpu /></el-icon> ML模型训练管理
              </h4>

              <!-- V1 模型状态 -->
              <div class="model-status-card" style="margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                  <span style="font-weight: bold; font-size: 14px;">📊 ML模型 - 智能选股技术评分</span>
                  <el-button size="small" type="primary" @click="triggerMLTrain()" :loading="mlTraining">手动训练</el-button>
                </div>
                <el-descriptions :column="isMobile ? 1 : 3" border size="small">
                  <el-descriptions-item label="模型状态">
                    <el-tag :type="(mlModelStatus.classifier_exists || mlModelStatus.regressor_exists) ? 'success' : 'info'" size="small">
                      {{ (mlModelStatus.classifier_exists || mlModelStatus.regressor_exists) ? '已训练' : '未训练' }}
                    </el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="最后训练">{{ mlModelStatus.last_train_time ? new Date(mlModelStatus.last_train_time).toLocaleString('zh-CN') : '-' }}</el-descriptions-item>
                  <el-descriptions-item label="样本数">{{ mlModelStatus.sample_count || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="特征数">{{ mlModelStatus.feature_count || '-' }}</el-descriptions-item>
                  <el-descriptions-item label="股票数">{{ mlModelStatus.stock_count || '-' }}</el-descriptions-item>
                </el-descriptions>
              </div>

              <!-- 定时训练配置 -->
              <div style="margin-top: 16px;">
                <h5 style="margin: 0 0 12px 0; color: #606266; font-size: 13px;">⏰ 定时训练配置</h5>
                <el-descriptions :column="isMobile ? 1 : 2" border size="small">
                  <el-descriptions-item label="启用"><el-tag :type="schedulerForm.ml_train_enabled ? 'success' : 'info'" size="small">{{ schedulerForm.ml_train_enabled ? '已启用' : '已禁用' }}</el-tag></el-descriptions-item>
                  <el-descriptions-item label="训练日">{{ ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][schedulerForm.ml_train_day_of_week] || '周一' }} {{ schedulerForm.ml_train_time || '20:00' }}</el-descriptions-item>
                  <el-descriptions-item label="数据天数">{{ schedulerForm.ml_train_days || 250 }} 天</el-descriptions-item>
                  <el-descriptions-item label="股票数量">{{ schedulerForm.ml_train_stocks || 100 }} 只</el-descriptions-item>
                </el-descriptions>
              </div>
            </div>
          </el-col>
        </el-row>
      </div>

      <!-- 编辑视图 -->
      <el-row v-else :gutter="24">
        <el-col :xs="24" :sm="12">
          <div class="scheduler-block">
            <h4 style="margin: 0 0 16px 0; color: #303133;">
              <el-icon><Document /></el-icon> AI复盘报告定时生成
            </h4>
            <el-form :model="schedulerForm" label-width="100px">
              <el-form-item label="启用任务">
                <el-switch v-model="schedulerForm.report_enabled" />
              </el-form-item>
              <el-form-item label="执行时间">
                <el-time-picker
                  v-model="schedulerForm.report_time"
                  format="HH:mm"
                  value-format="HH:mm"
                  placeholder="选择时间"
                  style="width: 150px;"
                />
              </el-form-item>
            </el-form>
          </div>
        </el-col>

        <el-col :xs="24" :sm="12">
          <div class="scheduler-block">
            <h4 style="margin: 0 0 16px 0; color: #303133;">
              <el-icon><TrendCharts /></el-icon> AI股票推荐定时生成
            </h4>
            <el-form :model="schedulerForm" label-width="100px">
              <el-form-item label="启用任务">
                <el-switch v-model="schedulerForm.pick_enabled" />
              </el-form-item>
              <el-form-item label="执行时间">
                <el-time-picker
                  v-model="schedulerForm.pick_time"
                  format="HH:mm"
                  value-format="HH:mm"
                  placeholder="选择时间"
                  style="width: 150px;"
                />
              </el-form-item>
            </el-form>
          </div>
        </el-col>
      </el-row>

      <el-row v-if="schedulerEditing" :gutter="24" style="margin-top: 16px;">
        <el-col :span="24">
          <div class="scheduler-block">
            <h4 style="margin: 0 0 16px 0; color: #303133;">
              <el-icon><Clock /></el-icon> 模拟交易 & 行情定时任务
            </h4>
            <el-form :model="schedulerForm" label-width="160px" inline>
              <el-form-item label="上午 T+1 解锁">
                <el-time-picker v-model="schedulerForm.t1_unlock_morning_time" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" />
              </el-form-item>
              <el-form-item label="交易日判断">
                <el-time-picker v-model="schedulerForm.trading_day_check_time" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" />
              </el-form-item>
              <el-form-item label="策略执行间隔(分钟)">
                <el-input-number v-model="schedulerForm.strategy_exec_interval_min" :min="1" :max="60" size="small" style="width: 110px;" />
              </el-form-item>
              <el-form-item label="午间策略调整">
                <el-time-picker v-model="schedulerForm.midday_strategy_time" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" />
              </el-form-item>
              <el-form-item label="盘中策略-上午">
                <el-time-picker v-model="schedulerForm.intraday_strategy_time_1" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" />
              </el-form-item>
              <el-form-item label="盘中策略-下午">
                <el-time-picker v-model="schedulerForm.intraday_strategy_time_2" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" />
              </el-form-item>
              <el-form-item label="收盘前平短仓">
                <el-switch v-model="schedulerForm.auto_close_short_enabled" style="margin-right:8px;" />
                <el-time-picker
                  v-model="schedulerForm.auto_close_short_time"
                  format="HH:mm"
                  value-format="HH:mm"
                  placeholder="13:30-14:55"
                  style="width: 130px;"
                  :disabled="!schedulerForm.auto_close_short_enabled"
                />
              </el-form-item>
              <el-form-item label="收盘缓存">
                <el-time-picker v-model="schedulerForm.closing_cache_time" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" />
              </el-form-item>
              <el-form-item label="复盘+次日策略">
                <el-time-picker v-model="schedulerForm.review_strategy_time" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" />
              </el-form-item>
              <el-form-item label="清理报告">
                <el-time-picker v-model="schedulerForm.cleanup_report_time" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" />
              </el-form-item>
              <el-form-item label="清理对话">
                <el-time-picker v-model="schedulerForm.cleanup_conversation_time" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" />
              </el-form-item>
            </el-form>
          </div>
        </el-col>
      </el-row>

      <el-row v-if="schedulerEditing" :gutter="24" style="margin-top: 16px;">
        <el-col :span="24">
          <div class="scheduler-block">
            <h4 style="margin: 0 0 16px 0; color: #303133;">
              <el-icon><Cpu /></el-icon> ML模型训练管理
            </h4>

            <!-- V1 定时训练配置 -->
            <div style="margin-bottom: 20px; padding: 16px; background: #f5f7fa; border-radius: 8px;">
              <h5 style="margin: 0 0 12px 0; color: #303133;">📊 V1 - 智能选股技术评分</h5>
              <el-form :model="schedulerForm" label-width="140px" inline>
                <el-form-item label="启用自动训练">
                  <el-switch v-model="schedulerForm.ml_train_enabled" />
                </el-form-item>
                <el-form-item label="训练日期">
                  <el-select v-model="schedulerForm.ml_train_day_of_week" placeholder="选择星期" style="width: 120px;" :disabled="!schedulerForm.ml_train_enabled">
                    <el-option :value="0" label="周日" /><el-option :value="1" label="周一" /><el-option :value="2" label="周二" />
                    <el-option :value="3" label="周三" /><el-option :value="4" label="周四" /><el-option :value="5" label="周五" /><el-option :value="6" label="周六" />
                  </el-select>
                </el-form-item>
                <el-form-item label="执行时间">
                  <el-time-picker v-model="schedulerForm.ml_train_time" format="HH:mm" value-format="HH:mm" placeholder="时间" style="width: 130px;" :disabled="!schedulerForm.ml_train_enabled" />
                </el-form-item>
                <el-form-item label="训练数据天数">
                  <el-input-number v-model="schedulerForm.ml_train_days" :min="50" :max="1000" :step="10" size="small" style="width: 120px;" :disabled="!schedulerForm.ml_train_enabled" />
                </el-form-item>
                <el-form-item label="股票数量">
                  <el-input-number v-model="schedulerForm.ml_train_stocks" :min="10" :max="200" :step="10" size="small" style="width: 120px;" :disabled="!schedulerForm.ml_train_enabled" />
                </el-form-item>
              </el-form>
            </div>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- AI配额管理 -->
    <el-card class="section-card">
      <template #header>
        <div class="card-header">
          <span><el-icon><Monitor /></el-icon> AI对话配额管理</span>
          <div style="display: flex; gap: 8px;">
            <template v-if="!quotaEditing">
              <el-button size="small" @click="quotasCache.clear(); quotasCache.refresh()">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
              <el-button type="primary" size="small" plain @click="startEditQuota">编辑配置</el-button>
            </template>
            <template v-else>
              <el-button size="small" @click="cancelEditQuota">取消</el-button>
              <el-button type="primary" size="small" @click="saveAllQuotas" :loading="quotaSaving">保存全部</el-button>
            </template>
          </div>
        </div>
      </template>

      <div class="quota-section">
        <h4 style="margin: 0 0 12px 0; color: #303133;">配额配置</h4>
        <el-table :data="quotas" stripe style="width: 100%; margin-bottom: 20px;" border>
          <el-table-column label="角色" min-width="150">
            <template #default="{ row }">
              <el-tag :type="row.role === 'admin' ? 'danger' : row.role === 'vip' ? 'warning' : 'info'" size="small">
                {{ row.role === 'admin' ? '管理员' : row.role === 'vip' ? 'VIP用户' : '普通用户' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="每日配额" min-width="200">
            <template #default="{ row }">
              <template v-if="quotaEditing">
                <el-input-number
                  v-model="row.max_daily"
                  :min="1"
                  :max="99999"
                  size="small"
                  style="width: 120px"
                  :disabled="row.role === 'admin'"
                />
                <span style="margin-left: 8px; color: #909399; font-size: 12px;">{{ row.max_daily >= 9999 ? '不限' : '次/天' }}</span>
              </template>
              <template v-else>
                <span style="font-weight: 500;">{{ row.max_daily >= 9999 ? '∞ 不限' : row.max_daily + ' 次/天' }}</span>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <h4 style="margin: 0 0 12px 0; color: #303133;">今日用量</h4>
        <el-table :data="quotaUsage" stripe style="width: 100%;" border>
          <el-table-column prop="username" label="用户" min-width="150" />
          <el-table-column label="角色" width="100">
            <template #default="{ row }">
              <el-tag :type="row.role === 'admin' ? 'danger' : row.role === 'vip' ? 'warning' : 'info'" size="small">
                {{ row.role === 'admin' ? '管理员' : row.role === 'vip' ? 'VIP' : '普通' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="已用/上限" min-width="150">
            <template #default="{ row }">
              <span :style="{ color: row.remaining <= 5 ? '#f56c6c' : '#67c23a' }">
                {{ row.used }} / {{ row.limit >= 9999 ? '∞' : row.limit }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="剩余" width="100">
            <template #default="{ row }">
              {{ row.limit >= 9999 ? '∞' : row.remaining }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button
                size="small"
                type="warning"
                plain
                @click="resetQuotaUsage(row.user_id)"
                :disabled="row.role === 'admin'"
              >
                重置
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- 日志查看（默认折叠） -->
    <el-collapse v-model="activeLogSection">
      <el-collapse-item name="log" title="系统日志查看">
        <template #title>
          <div style="display: flex; align-items: center; gap: 8px;">
            <el-icon><View /></el-icon>
            <span>系统日志查看</span>
          </div>
        </template>
        <div style="padding-top: 12px;">
          <el-button size="small" @click="loadLogFiles" :loading="logLoading">
            <el-icon><Refresh /></el-icon> 刷新列表
          </el-button>

          <!-- 分类标签 -->
          <el-tabs v-model="activeLogCategory" type="card" @tab-click="onLogTabClick" style="margin-top: 12px;">
            <el-tab-pane
              v-for="cat in logCategories"
              :key="cat.key"
              :label="cat.label"
              :name="cat.key"
            >
              <!-- 该分类下的文件列表 -->
              <div class="log-file-tabs">
                <el-radio-group v-model="selectedLog" size="small">
                  <el-radio-button
                    v-for="lf in cat.files"
                    :key="lf.path_key"
                    :value="lf.path_key"
                  >
                    {{ lf.name }} ({{ lf.size_mb }}MB)
                  </el-radio-button>
                </el-radio-group>
              </div>

              <!-- 日志内容 -->
              <div v-if="logContent.length > 0" class="log-viewer">
                <div class="log-toolbar">
                  <span style="font-size: 12px; color: #909399;">共 {{ logContentLines }} 行 | 文件: {{ selectedLog }}</span>
                  <div style="display: flex; gap: 8px; align-items: center;">
                    <el-date-picker
                      v-model="logSelectedDate"
                      type="date"
                      placeholder="选择日期筛选日志"
                      format="YYYY-MM-DD"
                      value-format="YYYY-MM-DD"
                      clearable
                      style="width: 160px;"
                      size="small"
                      @change="onLogDateChange"
                    />
                    <el-input
                      v-model="logSearchText"
                      placeholder="过滤日志内容..."
                      clearable
                      style="width: 250px;"
                      size="small"
                    />
                    <el-checkbox v-model="autoScrollLog" size="small">自动滚动</el-checkbox>
                  </div>
                </div>
                <div class="log-content" ref="logContentRef">
                  <div
                    v-for="(line, idx) in filteredLogContent"
                    :key="idx"
                    class="log-line"
                    :class="getLogLevelClass(line)"
                  >
                    <span class="log-line-num">{{ idx + 1 }}</span>
                    <span class="log-line-text">{{ line }}</span>
                  </div>
                </div>
              </div>
              <div v-else class="log-empty">
                <el-empty description="选择文件后自动加载日志" :image-size="60" />
              </div>
            </el-tab-pane>
          </el-tabs>

          <!-- 无日志时的提示 -->
          <div v-if="logCategories.length === 0" class="log-empty">
            <el-empty description="暂无日志文件，请先启动服务" :image-size="80" />
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- 编辑用户对话框 -->
    <el-dialog v-model="editDialogVisible" title="编辑用户信息" width="450px">
      <el-form :model="editForm" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="editForm.username" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="editForm.email" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editForm.role" style="width: 100%">
            <el-option label="普通用户" value="normal" />
            <el-option label="VIP用户" value="vip" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="editForm.status" style="width: 100%">
            <el-option label="正常" value="active" />
            <el-option label="禁用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.remark" type="textarea" :rows="2" placeholder="添加备注信息" />
        </el-form-item>
        <el-form-item label="有效期">
          <div style="display: flex; align-items: center; gap: 12px; width: 100%;">
            <el-input-number v-model="editForm.expiry_days" :min="0" :max="3650" placeholder="0表示永不过期" style="flex: 1;" />
          </div>
          <div style="display: flex; align-items: center; gap: 8px; margin-top: 8px;">
            <span style="font-size: 13px; color: #606266; white-space: nowrap;">开始日期:</span>
            <el-date-picker v-model="editForm.expiry_start_date" type="date" value-format="YYYY-MM-DD" placeholder="选择开始日期，默认今天" style="flex: 1;" />
          </div>
          <div style="font-size: 12px; color: #909399; margin-top: 4px;">
            <span v-if="editForm.expiry_days > 0">到期日将自动计算</span>
            <span v-else>设置为0则永不过期</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingUser" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>

    <!-- 创建用户对话框 -->
    <el-dialog v-model="createDialogVisible" title="创建用户" width="450px">
      <el-form :model="createForm" label-width="80px">
        <el-form-item label="用户名" required>
          <el-input v-model="createForm.username" placeholder="2-50个字符" />
        </el-form-item>
        <el-form-item label="密码" required>
          <el-input v-model="createForm.password" type="password" show-password placeholder="至少6个字符" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="createForm.email" placeholder="可选" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="createForm.role" style="width: 100%">
            <el-option label="普通用户" value="normal" />
            <el-option label="VIP用户" value="vip" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.remark" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creatingUser" @click="handleCreateUser">创建</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码对话框 -->
    <el-dialog v-model="resetPwdDialogVisible" title="重置用户密码" width="400px">
      <p style="margin-bottom: 16px; color: #909399;">正在为用户 <strong>{{ resetForm.username }}</strong> 重置密码</p>
      <el-form :model="resetForm" label-width="100px">
        <el-form-item label="新密码">
          <el-input v-model="resetForm.new_password" type="password" show-password placeholder="至少6个字符" />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input v-model="resetForm.confirm_password" type="password" show-password placeholder="再次输入新密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetPwdDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="resettingPwd" @click="confirmResetPassword">确认重置</el-button>
      </template>
    </el-dialog>

    <!-- 生成邀请码对话框 -->
    <el-dialog v-model="generateDialogVisible" title="生成邀请码" width="400px">
      <el-form label-width="80px">
        <el-form-item label="数量">
          <el-input-number v-model="generateCount" :min="1" :max="50" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="generateDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="generateCodes">生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
defineOptions({ name: 'AdminDashboard' })
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Setting, Clock, Document, TrendCharts, Monitor, Refresh, View, Money, Edit, Plus, Cpu } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { useCachedFetch, CACHE_TIERS } from '@/composables/useCachedFetch'

const authStore = useAuthStore()
const currentUserId = ref(authStore.user?.id || 0)

// 移动端检测
const isMobile = ref(false)
const screenWidth = ref(window.innerWidth)
function _updateScreen() {
  const w = window.innerWidth
  screenWidth.value = w
  isMobile.value = w <= 768
}
window.addEventListener('resize', _updateScreen)

// API helper
async function adminApi(url, method = 'GET', body = null) {
  const token = localStorage.getItem('gp_access_token')
  const fullUrl = `/api/v1${url}`
  try {
    const res = await axios({
      url: fullUrl,
      method,
      data: body,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    })
    return res.data
  } catch (e) {
    const status = e?.response?.status
    if (status === 401 || status === 403) {
      ElMessage.error('未登录或会话已过期，请重新登录')
    } else if (status >= 500) {
      ElMessage.error('后端服务异常')
    } else {
      const detail = e?.response?.data?.detail
      const msg = detail ? `${e.message} | ${detail}` : (e.message || '未知错误')
      ElMessage.error(`请求失败: ${msg}`)
      console.error('[adminApi]', method, fullUrl, '→', status, e?.response?.data)
    }
    throw e
  }
}

// ===== 统计（5分钟缓存）=====
const statsCache = useCachedFetch({
  key: () => 'admin:stats',
  fetcher: () => adminApi('/admin/stats'),
  tier: CACHE_TIERS.USER,
})

const stats = computed(() => statsCache.data.value || { total_users: 0, total_sessions: 0, total_messages: 0, unused_invites: 0 })

// ===== 用户管理（动态 key：搜索词+分页）=====
// 必须先声明 ref，再 useCachedFetch（resolveKey 会立即调用 key()）
const userSearch = ref('')
const userPage = ref(1)

const usersCache = useCachedFetch({
  key: () => `admin:users:p${userPage.value}:s${userSearch.value.trim()}`,
  fetcher: () => adminApi(`/admin/users?skip=${(userPage.value - 1) * 20}&limit=20&search=${encodeURIComponent(userSearch.value)}`),
  tier: CACHE_TIERS.USER,
  onSuccess: (data) => ({ users: data?.users || [], total: data?.total || 0 }),
})

const users = computed(() => usersCache.data.value?.users || [])
const userTotal = computed(() => usersCache.data.value?.total || 0)

const editDialogVisible = ref(false)
const savingUser = ref(false)
const editForm = ref({ id: null, username: '', email: '', role: 'normal', status: 'active', remark: '', expiry_days: 0, currentExpiry: '' })

function openEditUser(row) {
  const now = new Date()
  let expiryDays = 0
  let currentExpiry = '永不过期'
  if (row.expiry_date) {
    const expiryDate = new Date(row.expiry_date)
    const diff = expiryDate - now
    expiryDays = Math.ceil(diff / (1000 * 60 * 60 * 24))
    currentExpiry = expiryDate.toLocaleDateString('zh-CN')
    if (expiryDays < 0) expiryDays = 0
  }
  let startDateStr = ''
  if (row.expiry_start_date) {
    const sd = new Date(row.expiry_start_date)
    startDateStr = `${sd.getFullYear()}-${String(sd.getMonth() + 1).padStart(2, '0')}-${String(sd.getDate()).padStart(2, '0')}`
  }
  editForm.value = { id: row.id, username: row.username, email: row.email || '', role: row.role, status: row.status, remark: row.remark || '', expiry_days: expiryDays, currentExpiry, startDate: startDateStr, expiry_start_date: startDateStr }
  editDialogVisible.value = true
}

async function saveUser() {
  savingUser.value = true
  try {
    await adminApi(`/admin/users/${editForm.value.id}`, 'PUT', {
      username: editForm.value.username,
      email: editForm.value.email,
      role: editForm.value.role,
      status: editForm.value.status,
      remark: editForm.value.remark,
      expiry_days: editForm.value.expiry_days,
      expiry_start_date: editForm.value.expiry_start_date || null,
    })
    ElMessage.success('用户已更新')
    editDialogVisible.value = false
    usersCache.clear()
    await usersCache.refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingUser.value = false
  }
}

// ===== 创建用户 =====
const createDialogVisible = ref(false)
const creatingUser = ref(false)
const createForm = ref({ username: '', password: '', email: '', role: 'normal', remark: '' })

function openCreateDialog() {
  createForm.value = { username: '', password: '', email: '', role: 'normal', remark: '' }
  createDialogVisible.value = true
}

async function handleCreateUser() {
  if (createForm.value.username.length < 2) {
    ElMessage.error('用户名至少2个字符')
    return
  }
  if (createForm.value.password.length < 6) {
    ElMessage.error('密码至少6个字符')
    return
  }
  creatingUser.value = true
  try {
    await adminApi('/admin/users', 'POST', {
      username: createForm.value.username,
      password: createForm.value.password,
      email: createForm.value.email || null,
      role: createForm.value.role,
      remark: createForm.value.remark || null,
    })
    ElMessage.success(`用户 ${createForm.value.username} 已创建`)
    createDialogVisible.value = false
    usersCache.clear()
    await usersCache.refresh()
    statsCache.clear()
    await statsCache.refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    creatingUser.value = false
  }
}

// ===== 重置密码 =====
const resetPwdDialogVisible = ref(false)
const resettingPwd = ref(false)
const resetForm = ref({ id: null, username: '', new_password: '', confirm_password: '' })

function openResetPassword(row) {
  resetForm.value = { id: row.id, username: row.username, new_password: '', confirm_password: '' }
  resetPwdDialogVisible.value = true
}

async function confirmResetPassword() {
  if (resetForm.value.new_password.length < 6) {
    ElMessage.error('新密码至少6个字符')
    return
  }
  if (resetForm.value.new_password !== resetForm.value.confirm_password) {
    ElMessage.error('两次输入的密码不一致')
    return
  }
  resettingPwd.value = true
  try {
    await adminApi(`/admin/users/${resetForm.value.id}/reset-password`, 'POST', {
      new_password: resetForm.value.new_password,
    })
    ElMessage.success(`用户 ${resetForm.value.username} 的密码已重置`)
    resetPwdDialogVisible.value = false
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '重置失败')
  } finally {
    resettingPwd.value = false
  }
}

async function toggleUserStatus(row) {
  try {
    const newStatus = row.status === 'active' ? 'disabled' : 'active'
    await adminApi(`/admin/users/${row.id}`, 'PUT', { status: newStatus })
    ElMessage.success(`用户已${newStatus === 'active' ? '启用' : '禁用'}`)
    usersCache.clear()
    await usersCache.refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

async function deleteUser(row) {
  try {
    await adminApi(`/admin/users/${row.id}`, 'DELETE')
    ElMessage.success(`用户 ${row.username} 及其所有数据已删除`)
    usersCache.clear()
    await usersCache.refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

// ===== 邀请码管理 =====
const inviteCodesCache = useCachedFetch({
  key: () => 'admin:invite-codes',
  fetcher: () => adminApi('/admin/invite-codes'),
  tier: CACHE_TIERS.USER,
  onSuccess: (data) => data?.codes || [],
})

const inviteCodes = computed(() => inviteCodesCache.data.value || [])

const generateDialogVisible = ref(false)
const generating = ref(false)
const generateCount = ref(5)

function openGenerateDialog() {
  generateCount.value = 5
  generateDialogVisible.value = true
}

async function generateCodes() {
  generating.value = true
  try {
    await adminApi(`/admin/invite-codes/generate?count=${generateCount.value}`, 'POST')
    ElMessage.success(`已生成 ${generateCount.value} 个邀请码`)
    generateDialogVisible.value = false
    inviteCodesCache.clear()
    await inviteCodesCache.refresh()
    statsCache.clear()
    await statsCache.refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '生成失败')
  } finally {
    generating.value = false
  }
}

async function deleteInviteCode(id) {
  try {
    await adminApi(`/admin/invite-codes/${id}`, 'DELETE')
    ElMessage.success('邀请码已删除')
    inviteCodesCache.clear()
    await inviteCodesCache.refresh()
    statsCache.clear()
    await statsCache.refresh()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

function copyCode(code) {
  navigator.clipboard.writeText(code).then(() => {
    ElMessage.success('邀请码已复制到剪贴板')
  }).catch(() => {
    ElMessage.warning('复制失败，请手动复制')
  })
}

// ===== 工具函数 =====
function formatDate(dateStr) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatDateShort(dateStr) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function getRemainingDays(row) {
  if (!row.expiry_date) return null
  const now = new Date()
  const expiry = new Date(row.expiry_date)
  const diff = expiry - now
  const days = Math.ceil(diff / (1000 * 60 * 60 * 24))
  return days > 0 ? days : 0
}

function getExpiryTagType(row) {
  const days = getRemainingDays(row)
  if (days === null) return 'info'
  if (days <= 0) return 'danger'
  if (days <= 7) return 'warning'
  return 'success'
}

// ===== 配额管理 =====
const quotasCache = useCachedFetch({
  key: () => 'admin:quotas',
  fetcher: () => adminApi('/admin/quotas'),
  tier: CACHE_TIERS.USER,
})

const quotaUsageCache = useCachedFetch({
  key: () => 'admin:quotas-usage',
  fetcher: () => adminApi('/admin/quotas/usage'),
  tier: CACHE_TIERS.USER,
})

const quotas = computed(() => quotasCache.data.value || [])
const quotaUsage = computed(() => quotaUsageCache.data.value || [])
const quotaEditing = ref(false)
const quotaSaving = ref(false)
const quotaSnapshot = ref(null)

function startEditQuota() {
  quotaSnapshot.value = JSON.parse(JSON.stringify(quotas.value))
  quotaEditing.value = true
}

function cancelEditQuota() {
  if (quotaSnapshot.value) {
    quotasCache.data.value = quotaSnapshot.value
  }
  quotaEditing.value = false
  quotaSnapshot.value = null
}

async function saveAllQuotas() {
  quotaSaving.value = true
  try {
    for (const row of quotas.value) {
      if (row.role === 'admin') continue
      await adminApi('/admin/quotas', 'PUT', { role: row.role, max_daily: row.max_daily })
    }
    ElMessage.success('配额已全部保存')
    quotaEditing.value = false
    quotasCache.clear()
    await quotasCache.refresh()
  } catch (e) {
    ElMessage.error('更新失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    quotaSaving.value = false
  }
}

async function resetQuotaUsage(userId) {
  try {
    await adminApi(`/admin/quotas/usage/${userId}`, 'PUT')
    ElMessage.success('用量已重置')
    quotaUsageCache.clear()
    await quotaUsageCache.refresh()
  } catch (e) {
    ElMessage.error('重置失败: ' + (e.response?.data?.detail || e.message))
  }
}

const LLM_PROVIDER_URLS = {
  'lm-studio': 'http://localhost:1234/v1',
  'vllm': 'http://172.24.15.148:8000/v1',
}
const LLM_PROVIDER_LABELS = {
  'lm-studio': 'LM Studio（本地）',
  'vllm': 'vLLM（远程）',
  'custom': '自定义',
}
function providerLabel(provider) {
  return LLM_PROVIDER_LABELS[provider] || provider || '自定义'
}

function onLLMProviderChange(provider) {
  if (provider !== 'custom') {
    llmForm.value.base_url = LLM_PROVIDER_URLS[provider]
  }
}

// ===== LLM配置 =====
const llmForm = ref({ base_url: '', model: '', temperature: 0.7, max_tokens: 8192, enabled: false, provider: 'custom' })
const llmLoading = ref(false)
const llmSaving = ref(false)
const llmTesting = ref(false)
const llmEditing = ref(false)
const llmSnapshot = ref(null)

async function loadLLMConfig() {
  llmLoading.value = true
  try {
    const data = await adminApi('/admin/llm-config')
    llmForm.value = { base_url: data.base_url || '', model: data.model || '', temperature: data.temperature ?? 0.7, max_tokens: data.max_tokens ?? 8192, enabled: !!data.enabled, provider: data.provider || 'custom' }
  } catch (e) {
    ElMessage.error('获取LLM配置失败')
  } finally {
    llmLoading.value = false
  }
}

function startEditLLM() {
  llmSnapshot.value = { ...llmForm.value }
  llmEditing.value = true
}

function cancelEditLLM() {
  if (llmSnapshot.value) {
    llmForm.value = { ...llmSnapshot.value }
  }
  llmEditing.value = false
  llmSnapshot.value = null
}

async function saveLLMConfig() {
  llmSaving.value = true
  try {
    await adminApi('/admin/llm-config', 'PUT', llmForm.value)
    ElMessage.success('LLM配置已保存')
    llmEditing.value = false
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    llmSaving.value = false
  }
}

async function testLLMConnection() {
  llmTesting.value = true
  try {
    const result = await adminApi('/admin/llm-config/test', 'POST')
    if (result.connected) {
      ElMessage.success(`连接成功！可用模型: ${result.models.join(', ') || '无'}`)
    } else {
      ElMessage.error(`连接失败: ${result.error || '未知错误'}`)
    }
  } catch (e) {
    ElMessage.error('测试连接失败')
  } finally {
    llmTesting.value = false
  }
}

// ===== 定时任务调度配置 =====
const schedulerForm = ref({
  report_enabled: true, report_time: '16:30',
  pick_enabled: true, pick_time: '15:15',
  // 模拟交易 T+1 解锁（仅上午，A 股 T+1 规则）
  t1_unlock_morning_time: '09:25',
  // 交易日判断
  trading_day_check_time: '09:30',
  // 收盘缓存 / 复盘+次日策略合并
  closing_cache_time: '15:05',
  review_strategy_time: '15:06',
  midday_strategy_time: '11:30',
  // 盘中策略生成时间（交易时段内自动生成 intraday 模式策略）
  intraday_strategy_time_1: '10:30',
  intraday_strategy_time_2: '13:30',
  // 收盘前自动平短仓配置
  auto_close_short_enabled: true,
  auto_close_short_time: '14:50',
  // 策略执行间隔（分钟，盘中AI策略自动执行频率）
  strategy_exec_interval_min: 5,
  // 凌晨清理
  cleanup_report_time: '02:00',
  cleanup_conversation_time: '03:00',
  // ML模型定时训练配置（智能选股技术评分）
  ml_train_enabled: false,
  ml_train_day_of_week: 1,
  ml_train_time: '20:00',
  ml_train_days: 250,
  ml_train_stocks: 100,
})
const schedulerLoading = ref(false)
const schedulerSaving = ref(false)
const schedulerEditing = ref(false)
const schedulerSnapshot = ref(null)

// ===== ML模型训练管理 =====
const mlModelStatus = ref({})
const mlTraining = ref(false)

async function loadMLModelStatus() {
  try {
    const data = await adminApi('/admin/ml-model-status')
    if (data.status === 'success') mlModelStatus.value = data.data
  } catch (e) { console.error('获取模型状态失败:', e) }
}

async function triggerMLTrain() {
  if (mlTraining.value) {
    ElMessage.warning('已有训练任务在执行中')
    return
  }
  try {
    await ElMessageBox.confirm('确定要手动触发ML模型重新训练吗？训练可能需要5-30分钟。', '确认训练', { type: 'warning' })
  } catch { return }

  mlTraining.value = true
  try {
    const payload = {
      days: schedulerForm.value.ml_train_days,
      stocks: schedulerForm.value.ml_train_stocks
    }
    const result = await adminApi('/admin/train-ml-model', 'POST', payload)
    if (result.status === 'success') {
      ElMessage.success(result.message || 'ML模型训练完成')
      loadMLModelStatus()
    } else {
      ElMessage.error(result.message || 'ML模型训练失败')
    }
  } catch (e) {
    ElMessage.error('训练失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    mlTraining.value = false
  }
}

async function loadSchedulerConfig() {
  schedulerLoading.value = true
  try {
    const data = await adminApi('/admin/scheduler-config')
    schedulerForm.value = {
      report_enabled: !!data.report_enabled,
      report_time: data.report_time || '16:30',
      pick_enabled: !!data.pick_enabled,
      pick_time: data.pick_time || '15:15',
      t1_unlock_morning_time: data.t1_unlock_morning_time || '09:25',
      trading_day_check_time: data.trading_day_check_time || '09:30',
      closing_cache_time: data.closing_cache_time || '15:05',
      review_strategy_time: data.review_strategy_time || '15:06',
      midday_strategy_time: data.midday_strategy_time || '11:30',
      intraday_strategy_time_1: data.intraday_strategy_time_1 || '10:30',
      intraday_strategy_time_2: data.intraday_strategy_time_2 || '13:30',
      auto_close_short_enabled: data.auto_close_short_enabled !== false,
      auto_close_short_time: data.auto_close_short_time || '14:50',
      strategy_exec_interval_min: data.strategy_exec_interval_min || 5,
      cleanup_report_time: data.cleanup_report_time || '02:00',
      cleanup_conversation_time: data.cleanup_conversation_time || '03:00',
      ml_train_enabled: !!data.ml_train_enabled,
      ml_train_day_of_week: data.ml_train_day_of_week ?? 1,
      ml_train_time: data.ml_train_time || '20:00',
      ml_train_days: data.ml_train_days ?? 250,
      ml_train_stocks: data.ml_train_stocks ?? 100,
    }
  } catch (e) {
    ElMessage.error('获取调度配置失败')
  } finally {
    schedulerLoading.value = false
  }
}

function startEditScheduler() {
  schedulerSnapshot.value = { ...schedulerForm.value }
  schedulerEditing.value = true
}

function cancelEditScheduler() {
  if (schedulerSnapshot.value) {
    schedulerForm.value = { ...schedulerSnapshot.value }
  }
  schedulerEditing.value = false
  schedulerSnapshot.value = null
}

async function saveSchedulerConfig() {
  const f = schedulerForm.value
  // 验证所有时间字段
  const timeFields = [
    'report_time', 'pick_time',
    't1_unlock_morning_time',
    'trading_day_check_time', 'closing_cache_time',
    'review_strategy_time', 'midday_strategy_time',
    'intraday_strategy_time_1', 'intraday_strategy_time_2',
    'auto_close_short_time',
    'cleanup_report_time', 'cleanup_conversation_time',
    'ml_train_time',
  ]
  for (const field of timeFields) {
    if (!f[field]) {
      ElMessage.error(`请设置 ${field} 时间`)
      return
    }
    if (!/^\d{2}:\d{2}$/.test(f[field])) {
      ElMessage.error(`${field} 格式错误，应为 HH:mm`)
      return
    }
  }
  if (!f.strategy_exec_interval_min || f.strategy_exec_interval_min < 1 || f.strategy_exec_interval_min > 60) {
    ElMessage.error('策略执行间隔必须在 1-60 分钟之间')
    return
  }
  schedulerSaving.value = true
  try {
    await adminApi('/admin/scheduler-config', 'PUT', f)
    ElMessage.success('调度配置已保存')
    schedulerEditing.value = false
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    schedulerSaving.value = false
  }
}

// ===== 模拟交易初始金额配置 =====
const initialCapitalForm = ref({ initial_capital: 100000 })
const initialCapitalLoading = ref(false)
const initialCapitalSaving = ref(false)
const initialCapitalHint = ref('')
const initialCapitalHintType = ref('info')
const initialCapitalEditing = ref(false)
const initialCapitalSnapshot = ref(null)

const loadInitialCapital = async () => {
  initialCapitalLoading.value = true
  try {
    const data = await adminApi('/sim-trading/admin/initial-capital', 'GET')
    initialCapitalForm.value.initial_capital = Number(data.initial_capital || 100000)
    initialCapitalHint.value = ''
  } catch (e) {
    ElMessage.error('获取初始金额配置失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    initialCapitalLoading.value = false
  }
}

const startEditInitialCapital = () => {
  initialCapitalSnapshot.value = { initial_capital: initialCapitalForm.value.initial_capital }
  initialCapitalHint.value = ''
  initialCapitalEditing.value = true
}

const cancelEditInitialCapital = () => {
  if (initialCapitalSnapshot.value) {
    initialCapitalForm.value.initial_capital = initialCapitalSnapshot.value.initial_capital
  }
  initialCapitalHint.value = ''
  initialCapitalEditing.value = false
  initialCapitalSnapshot.value = null
}

const saveInitialCapital = async () => {
  const value = Number(initialCapitalForm.value.initial_capital)
  if (!value || value < 1000 || value > 100000000) {
    ElMessage.warning('初始金额必须在 1,000 ~ 100,000,000 之间')
    return
  }
  initialCapitalSaving.value = true
  try {
    const data = await adminApi('/sim-trading/admin/initial-capital', 'PUT', { initial_capital: value })
    initialCapitalHint.value = data.message || '保存成功'
    initialCapitalHintType.value = data.applied_today ? 'success' : 'warning'
    ElMessage.success(data.applied_today ? '初始金额已更新并生效' : '初始金额已更新（建议重置账户）')
    initialCapitalEditing.value = false
    initialCapitalSnapshot.value = null
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
    initialCapitalHint.value = '保存失败: ' + (e.response?.data?.detail || e.message)
    initialCapitalHintType.value = 'error'
  } finally {
    initialCapitalSaving.value = false
  }
}

// ===== 入金 =====
const depositDialogVisible = ref(false)
const depositSaving = ref(false)
const depositForm = ref({ amount: 50000, remark: '' })

const openDepositDialog = () => {
  depositForm.value = { amount: 50000, remark: '' }
  depositDialogVisible.value = true
}

const confirmDeposit = async () => {
  const amount = Number(depositForm.value.amount)
  if (!amount || amount < 100) {
    ElMessage.warning('入金金额不能小于 100 元')
    return
  }
  if (amount > 100000000) {
    ElMessage.warning('单次入金金额不能大于 1 亿')
    return
  }
  depositSaving.value = true
  try {
    const data = await adminApi('/sim-trading/admin/deposit', 'POST', {
      amount,
      remark: depositForm.value.remark || '',
    })
    ElMessage.success(data.message || `已成功入金 ¥${amount.toLocaleString()}`)
    depositDialogVisible.value = false
  } catch (e) {
    ElMessage.error('入金失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    depositSaving.value = false
  }
}

// ===== 日志查看 =====
const activeLogSection = ref([]) // el-collapse 默认折叠
const logFiles = ref([])
const selectedLog = ref('')
const activeLogCategory = ref('应用日志')
const logContent = ref([])
const logLoading = ref(false)
const logContentLoading = ref(false)
const logSelectedDate = ref('')
const logSearchText = ref('')
const autoScrollLog = ref(true)
const logContentRef = ref(null)

// 分类映射
const CATEGORY_MAP = {
  '应用日志': { key: '应用日志', label: '应用日志' },
  '错误日志': { key: '错误日志', label: '错误日志' },
  '服务器日志': { key: '服务器日志', label: '服务器日志' },
}

const logCategories = computed(() => {
  const grouped = {}
  for (const lf of logFiles.value) {
    const cat = lf.category || '其他'
    if (!grouped[cat]) grouped[cat] = []
    grouped[cat].push(lf)
  }
  // 固定顺序：应用、错误、服务器、其他
  const order = ['应用日志', '错误日志', '服务器日志', '其他']
  return order.map(key => ({
    key,
    label: CATEGORY_MAP[key]?.label || key,
    files: grouped[key] || [],
  })).filter(c => c.files.length > 0)
})

const logContentLines = computed(() => logContent.value.length)

const filteredLogContent = computed(() => {
  if (!logSearchText.value.trim()) return logContent.value
  const keyword = logSearchText.value.toLowerCase()
  return logContent.value.filter(line => line.toLowerCase().includes(keyword))
})

function getLogLevelClass(line) {
  const lower = line.toLowerCase()
  if (lower.includes('error') || lower.includes('critical') || lower.includes('exception')) return 'log-error'
  if (lower.includes('warning') || lower.includes('warn')) return 'log-warn'
  if (lower.includes('info')) return 'log-info'
  if (lower.includes('debug')) return 'log-debug'
  return ''
}

async function loadLogFiles() {
  logLoading.value = true
  try {
    const data = await adminApi('/admin/logs/list')
    logFiles.value = data || []
    // 自动选中第一个文件（watch会自动触发加载）
    if (logFiles.value.length > 0 && !selectedLog.value) {
      selectedLog.value = logFiles.value[0].path_key
    }
  } catch (e) {
    ElMessage.error('获取日志列表失败')
  } finally {
    logLoading.value = false
  }
}

async function loadLogContent() {
  if (!selectedLog.value) return
  logContentLoading.value = true
  try {
    let data
    if (logSelectedDate.value) {
      // 按日期筛选
      data = await adminApi(`/admin/logs/by-date?file=${encodeURIComponent(selectedLog.value)}&date=${logSelectedDate.value}&lines=2000`)
    } else {
      // 默认最新日志
      data = await adminApi(`/admin/logs/content?file=${encodeURIComponent(selectedLog.value)}&lines=2000`)
    }
    logContent.value = data?.content || []
    nextTick(() => scrollToBottom())
  } catch (e) {
    ElMessage.error('读取日志失败')
  } finally {
    logContentLoading.value = false
  }
}

function onLogDateChange() {
  loadLogContent()
}

function onLogTabClick() {
  // 切换分类时，选中该分类下第一个文件（watch会自动触发加载）
  const cat = logCategories.value.find(c => c.key === activeLogCategory.value)
  if (cat && cat.files.length > 0) {
    // 判断当前选中的文件是否属于这个分类
    const belongsToCurrentCat = cat.files.some(f => f.path_key === selectedLog.value)
    if (!belongsToCurrentCat) {
      selectedLog.value = cat.files[0].path_key
    }
  }
}

// watch selectedLog 变化自动加载日志内容，重置日期选择
watch(selectedLog, (newVal) => {
  logSelectedDate.value = ''
  if (newVal) loadLogContent()
})

// watch activeLogCategory 切换时，自动选中当前分类的第一个文件并加载
watch(activeLogCategory, (newCat) => {
  const cat = logCategories.value.find(c => c.key === newCat)
  if (cat && cat.files.length > 0) {
    const belongsToCurrentCat = cat.files.some(f => f.path_key === selectedLog.value)
    if (!belongsToCurrentCat) {
      selectedLog.value = cat.files[0].path_key
    }
  }
})

function scrollToBottom() {
  if (!autoScrollLog.value || !logContentRef.value) return
  logContentRef.value.scrollTop = logContentRef.value.scrollHeight
}

watch(logSearchText, () => nextTick(() => scrollToBottom()))
watch(logContent, () => nextTick(() => scrollToBottom()), { flush: 'post' })

function onUserSearchInput() {
  userPage.value = 1
  // key 变化后 handleKeyChange 已自动 silentRefresh，无需手动调用
}

function onUserPageChange() {
  // key 变化后 handleKeyChange 已自动 silentRefresh，无需手动调用
}

// useCachedFetch 内部已自动在 onMounted 读 localStorage + 后台静默刷新
onMounted(() => {
  _updateScreen()
  loadLLMConfig()
  loadSchedulerConfig()
  loadLogFiles()
  loadInitialCapital()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', _updateScreen)
})
</script>

<style scoped>
.admin-container {
  height: 100%;
  overflow-y: auto;
  max-width: 1400px;
  margin: 0 auto;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card .stat-value {
  font-size: 32px;
  font-weight: bold;
  color: #409EFF;
}

.stat-card .stat-label {
  color: #999;
  font-size: 14px;
  margin-top: 4px;
}

.section-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.card-header span {
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.code-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.code-cell code {
  background: #f0f2f5;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
}

/* 操作列按钮一行显示 */
.action-btns { display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; gap: 8px; align-items: center; justify-content: flex-start; width: 100%; }

.config-read-only .scheduler-block { margin-bottom: 16px; }

.expiry-info { display: flex; align-items: center; gap: 4px; }

/* 在线状态点 */
.status-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.online-dot {
  background-color: #67c23a;
  box-shadow: 0 0 4px rgba(103, 194, 58, 0.6);
}

.offline-dot {
  background-color: #c0c4cc;
}

/* ===== 日志查看器 ===== */
.log-file-tabs { margin-bottom: 12px; }

.log-viewer { margin-top: 8px; }

.log-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 4px;
}

.log-content {
  height: 500px;
  overflow-y: auto;
  overflow-x: auto;
  background: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  padding: 8px 12px;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
}

.log-line { display: flex; white-space: pre; }
.log-line-num { min-width: 50px; color: #858585; text-align: right; padding-right: 12px; user-select: none; flex-shrink: 0; }
.log-line-text { flex: 1; }

.log-error .log-line-text { color: #f44747; }
.log-warn .log-line-text { color: #dcdcaa; }
.log-info .log-line-text { color: #569cd6; }
.log-debug .log-line-text { color: #6a9955; }

.log-empty { padding: 40px 0; text-align: center; }

/* ===== 通用辅助样式 ===== */
.admin-section-header {
  flex-wrap: wrap;
  gap: 8px;
}

.admin-header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.admin-search-input {
  width: 250px;
}

.admin-capital-form {
  max-width: 100%;
}

.admin-capital-input {
  width: 220px;
}

.admin-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.6;
}

.admin-capital-hint-alert {
  margin-bottom: 12px;
}

.admin-capital-alert {
  margin-top: 12px;
}

/* 自定义信息提示框 */
.admin-info-box {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  margin-top: 12px;
  background: #ecf5ff;
  border-radius: 6px;
  border-left: 3px solid #409eff;
}

.admin-info-icon {
  font-size: 16px;
  flex-shrink: 0;
  line-height: 1.8;
}

.admin-info-text {
  font-size: 12px;
  color: #606266;
  line-height: 1.7;
  overflow-wrap: break-word;
}

.admin-warning-box {
  background: #fdf6ec;
  border-left-color: #e6a817;
}

/* ===== 移动端用户卡片 ===== */
.mob-user-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mob-user-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
}

.mob-uc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.mob-uc-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.mob-uc-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #606266;
  margin-bottom: 3px;
}

.mob-uc-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid #f5f7fa;
}

/* ===== 移动端邀请码卡片 ===== */
.mob-invite-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mob-invite-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
}

.mob-ic-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;

  code {
    background: #f0f2f5;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 13px;
    word-break: break-all;
  }
}

.mob-ic-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #606266;
  margin-bottom: 3px;
}

.mob-ic-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid #f5f7fa;
}

/* ===== 通用移动端标签 ===== */
.mob-label {
  color: #909399;
  min-width: 48px;
  flex-shrink: 0;
}

/* ===== 768px 及以下：平板/手机 ===== */
@media (max-width: 768px) {
.admin-container {
  height: 100%; overflow-y: auto;
    max-width: 100%;
    padding: 0 4px;
  }

  /* 统计卡片保持一行4个 */
  .stats-row :deep(.el-col) {
    flex: 0 0 25% !important;
    max-width: 25% !important;
  }

  .stat-card .stat-value { font-size: 18px; }
  .stat-card .stat-label { font-size: 11px; }

  /* 卡片头部 */
  .admin-section-header {
    flex-direction: column;
    align-items: stretch !important;
  }

  .admin-header-actions {
    width: 100%;
    justify-content: flex-start;

    :deep(.el-button) { flex: 1; min-width: 0; font-size: 12px; padding: 6px 8px; }
  }

  .admin-search-input { width: 100% !important; }

  /* 操作列按钮 */
  .action-btns { flex-wrap: wrap !important; gap: 4px !important; }
  .mob-action-btns { flex: 1; justify-content: flex-end; }

  /* Scheduler descriptions */
  :deep(.el-descriptions) { font-size: 12px; }
  :deep(.el-descriptions__content),
  :deep(.el-descriptions__label) { padding: 6px 8px !important; }

  /* 表单全宽 */
  :deep(.el-form) { max-width: 100% !important; }
  :deep(.el-input-number), :deep(.el-slider) { width: 100% !important; }
  .admin-capital-input { width: 100% !important; }

  /* Scheduler编辑表单：inline → block */
  .scheduler-block :deep(.el-form--inline) {
    display: block !important;

    .el-form-item { margin-right: 0 !important; display: block; margin-bottom: 12px; }
    .el-form-item__content { margin-left: 0 !important; }
  }

  :deep(.el-time-picker), :deep(.el-date-picker) { width: 100% !important; }

  /* 分页居中 */
  .pagination-wrap { justify-content: center; }

  /* 对话框底部弹出 */
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
    .el-dialog__footer { padding: 10px 16px 18px; }

    :deep(.el-form-item) { margin-bottom: 14px; }
    :deep(.el-input-number), :deep(.el-input) { width: 100%; }
  }

  /* 日志查看器 */
  .log-content { height: 350px; font-size: 11px; }
  .log-toolbar { flex-direction: column; align-items: stretch; gap: 8px; }
  .log-file-tabs :deep(.el-radio-group) { display: flex; flex-wrap: wrap; gap: 4px; }

  /* 配额表格 */
  .quota-section h4 { font-size: 13px; }
}

/* ===== 480px 及以下：小屏手机 ===== */
@media (max-width: 480px) {
  .admin-container { height: 100%; overflow-y: auto; padding: 0 2px; }

  /* 统计卡片保持一行4个，缩小字号 */
  .stats-row :deep(.el-col) {
    flex: 0 0 25% !important;
    max-width: 25% !important;
  }

  .stat-card .stat-value { font-size: 16px; }
  .stat-card .stat-label { font-size: 10px; }

  /* 卡片标题缩小 */
  .card-header span { font-size: 14px !important; }

  :deep(.el-button--small) { padding: 5px 8px; font-size: 12px; }

  .mob-user-card, .mob-invite-card { padding: 8px 10px; }
  .mob-uc-name { font-size: 13px; }
  .mob-uc-row, .mob-ic-row { font-size: 11px; }

  .log-content { height: 280px; font-size: 10px; }
}
</style>
