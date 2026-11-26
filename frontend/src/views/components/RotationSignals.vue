<template>
  <section class="card-section">
    <h3 class="section-title">🔄 板块轮动</h3>
    <div v-if="loading" class="rotation-grid skeleton-grid">
      <el-skeleton animated :count="1" v-for="i in 4" :key="'sk-' + i">
        <template #template>
          <div class="signal-card skeleton-signal-card">
            <el-skeleton-item variant="text" style="width: 80px; height: 14px;" />
            <el-skeleton-item variant="text" style="width: 100%; height: 12px; margin-top: 8px;" />
            <el-skeleton-item variant="text" style="width: 80%; height: 12px; margin-top: 6px;" />
            <el-skeleton-item variant="text" style="width: 90%; height: 12px; margin-top: 6px;" />
            <el-skeleton-item variant="text" style="width: 70%; height: 12px; margin-top: 6px;" />
          </div>
        </template>
      </el-skeleton>
    </div>
    <template v-else>
      <div v-if="!signals.leading_style && !signals.heat_score" class="empty-hint">暂无轮动信号数据</div>
      <div v-else class="rotation-grid">
        <!-- 风格与热度 -->
        <div class="signal-card">
          <div class="card-title">风格与热度</div>
          <div class="metric-row">
            <span class="metric-label">领涨风格</span>
            <el-tag :type="leadingStyleTagType" size="small">{{ signals.leading_style || '--' }}</el-tag>
          </div>
          <div class="metric-row" v-if="signals.flow_leading_style">
            <span class="metric-label">资金领涨</span>
            <el-tag type="success" size="small">{{ signals.flow_leading_style }}</el-tag>
          </div>
          <div class="metric-row" v-if="stylePerformanceDesc">
            <span class="metric-label">风格表现</span>
            <span class="metric-value text-gray">{{ stylePerformanceDesc }}</span>
          </div>
          <div class="metric-row" v-if="styleFlowDesc">
            <span class="metric-label">资金流向</span>
            <span class="metric-value text-gray">{{ styleFlowDesc }}</span>
          </div>
          <div class="divider"></div>
          <div class="gauge-row">
            <div class="gauge-item">
              <div class="gauge-wrap">
                <el-progress type="dashboard" :percentage="signals.heat_score || 0"
                  :color="heatGaugeColor" :width="56" />
                <span class="gauge-value">{{ signals.heat_score }}</span>
              </div>
              <span class="gauge-label">市场热度</span>
            </div>
            <div class="gauge-item">
              <div class="gauge-wrap">
                <el-progress type="dashboard" :percentage="signals.concentration_ratio || 0"
                  :color="concentrationColor" :width="56" />
                <span class="gauge-value">{{ signals.concentration_ratio?.toFixed(0) }}%</span>
              </div>
              <span class="gauge-label">资金集中度</span>
            </div>
          </div>
        </div>

        <!-- 逆势吸筹 -->
        <div class="signal-card">
          <div class="card-title opportunity">逆势吸筹</div>
          <template v-if="signals.accumulation_divergence && signals.accumulation_divergence.length">
            <div class="flow-list-scroll">
              <div v-for="(d, i) in signals.accumulation_divergence" :key="'acc-' + i"
                class="signal-item accumulation">
                <span class="item-name">{{ d.name }}</span>
                <span class="item-tag tag-blue">进场 +{{ d.flow_net?.toFixed(1) }}亿</span>
              </div>
            </div>
          </template>
          <div v-else class="empty-small">暂无数据</div>
        </div>

        <!-- 主力资金方向 -->
        <div class="signal-card">
          <div class="card-title">主力资金方向</div>
          <template v-if="signals.top_inflow_sectors && signals.top_inflow_sectors.length">
            <div class="flow-list-scroll">
              <div v-for="(s, i) in signals.top_inflow_sectors" :key="'top-' + i" class="rank-item">
                <span class="rank-num">{{ i + 1 }}</span>
                <span class="item-name">{{ s.name }} <small style="color:#909399;">{{ s.change_pct >= 0 ? '+' : '' }}{{ s.change_pct?.toFixed(2) }}%</small></span>
                <span class="rank-value">+{{ s.flow_net?.toFixed(1) }}亿</span>
              </div>
            </div>
          </template>
          <div v-else class="empty-small">暂无数据</div>
        </div>

        <!-- 量价背离 -->
        <div class="signal-card">
          <div class="card-title danger">量价背离</div>
          <template v-if="signals.warning_divergence && signals.warning_divergence.length">
            <div class="flow-list-scroll">
              <div v-for="(d, i) in signals.warning_divergence" :key="'warn-' + i"
                class="signal-item warning">
                <span class="item-name">{{ d.name }}</span>
                <span class="item-tag tag-orange">出逃 {{ d.flow_net?.toFixed(1) }}亿</span>
              </div>
            </div>
          </template>
          <div v-else class="empty-small">暂无数据</div>
        </div>
      </div>

      <!-- 综合操作建议 -->
      <div class="advice-section" v-if="adviceContent.length || signals.advice">
        <div class="advice-header">
          <el-icon><ChatDotRound /></el-icon>
          <span>综合研判</span>
        </div>
        <div class="advice-grid">
          <div class="advice-item" v-for="(item, idx) in adviceContent" :key="idx">
            <span class="advice-icon" :class="item.type">{{ item.icon }}</span>
            <div class="advice-text">
              <span class="advice-label">{{ item.label }}</span>
              <span class="advice-value">{{ item.value }}</span>
            </div>
          </div>
        </div>
        <div class="advice-custom" v-if="signals.advice">
          <strong>策略建议：</strong>{{ signals.advice }}
        </div>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { ChatDotRound } from '@element-plus/icons-vue'

const props = defineProps({
  signals: { type: Object, default: () => ({}) },
  loading: { type: Boolean, default: false }
})

// 综合操作建议：根据多维度数据生成结构化建议
const adviceContent = computed(() => {
  const s = props.signals || {}
  const items = []

  // 市场热度判断
  const heat = s.heat_score || 0
  if (heat >= 70) {
    items.push({ type: 'hot', icon: '🔴', label: '市场过热', value: '注意高位风险，控制仓位' })
  } else if (heat >= 45) {
    items.push({ type: 'normal', icon: '🟡', label: '热度适中', value: '可适度参与主线题材' })
  } else {
    items.push({ type: 'cold', icon: '🔵', label: '市场偏冷', value: '观望为主，等待信号明确' })
  }

  // 资金集中度判断
  const conc = s.concentration_ratio || 0
  if (conc >= 45) {
    items.push({ type: 'concentrated', icon: '📊', label: '资金集中', value: '聚焦龙头，避免跟风' })
  } else if (conc <= 20) {
    items.push({ type: 'scattered', icon: '🔀', label: '资金分散', value: '板块轮动快，快进快出' })
  }

  // 领涨风格判断
  if (s.leading_style) {
    const styleMap = { '大盘': '稳健配置蓝筹', '小盘': '关注弹性标的', '成长': '科技成长优先', '价值': '低估值防御为主', '周期': '资源品轮动' }
    items.push({ type: 'style', icon: '📈', label: `风格:${s.leading_style}`, value: styleMap[s.leading_style] || '跟随市场主线' })
  }

  // 量价背离警告
  if (s.warning_divergence?.length) {
    items.push({ type: 'warning', icon: '⚠️', label: '背离预警', value: `${s.warning_divergence.length}个板块资金出逃，注意回避` })
  }

  // 逆势吸筹机会
  if (s.accumulation_divergence?.length) {
    items.push({ type: 'opportunity', icon: '💡', label: '低吸机会', value: `${s.accumulation_divergence.length}个板块获资金进场，可关注` })
  }

  return items.slice(0, 5) // 最多显示5条
})

const leadingStyleTagType = computed(() => {
  const s = props.signals.leading_style
  if (s === '周期') return 'danger'
  if (s === '成长') return 'warning'
  return 'primary'
})

const stylePerformanceDesc = computed(() => {
  const sp = props.signals.style_performance
  if (!sp) return ''
  const parts = []
  for (const [name, val] of Object.entries(sp)) {
    parts.push(`${name}: ${val >= 0 ? '+' : ''}${val.toFixed(2)}%`)
  }
  return parts.join(' | ')
})

const styleFlowDesc = computed(() => {
  const sf = props.signals.style_flow
  if (!sf) return ''
  const parts = []
  for (const [name, val] of Object.entries(sf)) {
    parts.push(`${name}: ${val >= 0 ? '+' : ''}${val.toFixed(2)}亿`)
  }
  return parts.join(' | ')
})

const heatGaugeColor = computed(() => {
  const h = props.signals.heat_score || 0
  if (h > 70) return '#f56c6c'
  if (h > 40) return '#e6a23c'
  return '#409eff'
})

const concentrationColor = computed(() => {
  const r = props.signals.concentration_ratio || 0
  if (r > 40) return '#f56c6c'
  if (r > 25) return '#e6a23c'
  return '#409eff'
})
</script>

<style scoped>
.rotation-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  min-width: 0;
}

.signal-card {
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}

.card-title {
  font-size: 13px;
  color: #303133;
  margin-bottom: 8px;
  font-weight: 700;
}

/* 风格与热度 */
.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 3px 0;
  font-size: 11px;
}

.metric-label { color: #909399; }
.metric-value.text-gray { color: #606266; }

.divider {
  height: 1px;
  background: #f5f5f5;
  margin: 8px 0;
}

.gauge-row {
  display: flex;
  justify-content: space-around;
  align-items: center;
}

.gauge-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.gauge-label {
  font-size: 10px;
  color: #909399;
}

.gauge-wrap {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.gauge-item :deep(.el-progress--dashboard) {
  width: 48px !important;
  height: 48px !important;
}

.gauge-item :deep(.el-progress__text) {
  display: none !important;
}

.gauge-value {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 10px;
  font-weight: 700;
  color: #303133;
}

/* 异常信号 */
.sub-title {
  font-size: 12px;
  margin-bottom: 6px;
  font-weight: 500;
}
.sub-title.danger { color: #e6a23c; }
.sub-title.opportunity { color: #409eff; }

.flow-list-scroll {
  max-height: 240px;
  overflow-y: auto;
}

.flow-list-scroll::-webkit-scrollbar {
  width: 3px;
}

.flow-list-scroll::-webkit-scrollbar-thumb {
  background: #e0e0e0;
  border-radius: 2px;
}

.flow-list-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.signal-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  padding: 4px 6px;
  border-radius: 3px;
}

.signal-item.warning { background: #fff7e6; border-left: 2px solid #e6a23c; }
.signal-item.accumulation { background: #f0f9ff; border-left: 2px solid #409eff; }

.item-name {
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.item-tag {
  font-size: 9px;
  padding: 1px 4px;
  border-radius: 2px;
  white-space: nowrap;
  margin-left: 6px;
  flex-shrink: 0;
}

.tag-orange { background: #fdf6ec; color: #e6a23c; }
.tag-blue { background: #e8f4fd; color: #2196f3; }

/* 排名列表 */
.rank-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  font-size: 11px;
}

.rank-num {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #f0f2f5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  color: #909399;
  flex-shrink: 0;
}

.rank-item .item-name {
  flex: 1;
  min-width: 0;
  line-height: 1.3;
}

.rank-value {
  color: #f56c6c;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
  font-size: 10px;
}

/* 综合操作建议 */
.advice-section {
  margin-top: 14px;
  background: #fff;
  border-radius: 10px;
  padding: 16px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}

.advice-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: #303133;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #f0f2f5;
}

.advice-header .el-icon {
  font-size: 16px;
  color: #e6a23c;
}

.advice-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.advice-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #fafbfc;
  border: 1px solid #f0f2f5;
  transition: all 0.2s ease;
}

.advice-item:hover {
  background: #fff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  border-color: #e8ecf0;
}

.advice-icon {
  font-size: 18px;
  flex-shrink: 0;
  line-height: 1;
  margin-top: 2px;
}

.advice-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.advice-label {
  font-size: 11px;
  color: #909399;
  font-weight: 500;
}

.advice-value {
  font-size: 12.5px;
  color: #303133;
  line-height: 1.4;
  font-weight: 500;
}

/* 不同类型建议的颜色 */
.advice-item .advice-icon.hot { filter: hue-rotate(0deg); }
.advice-item .advice-icon.cold { filter: hue-rotate(180deg); }
.advice-item.warning { background: #fff7e6; border-color: #fde8c3; }
.advice-item.opportunity { background: #e8f4fd; border-color: #b3d8f2; }

.advice-custom {
  padding: 10px 14px;
  background: linear-gradient(135deg, #fff7e6, #fffbe6);
  border-radius: 8px;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  border-left: 3px solid #e6a23c;
}

.advice-custom strong {
  color: #e6a23c;
  font-weight: 700;
}

.empty-small {
  font-size: 12px;
  color: #c0c4cc;
  text-align: center;
  padding: 12px 0;
}

.loading-hint { text-align: center; padding: 20px; color: #909399; }
.empty-hint { text-align: center; padding: 20px; color: #c0c4cc; }

.skeleton-signal-card {
  display: flex;
  flex-direction: column;
}

@media (max-width: 1200px) {
  .rotation-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 768px) {
  .rotation-grid { grid-template-columns: 1fr !important; }
  .advice-grid { grid-template-columns: 1fr !important; }
}
</style>
