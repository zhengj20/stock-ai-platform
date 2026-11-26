<template>
  <transition name="slide-down">
    <div class="refresh-indicator" v-if="show">
      <span class="dot"></span>
      <span class="text">{{ text || '数据更新中' }}</span>
    </div>
  </transition>
</template>

<script setup>
defineProps({
  show: { type: Boolean, default: false },
  text: { type: String, default: '' },
})
</script>

<style scoped>
.refresh-indicator {
  position: fixed;
  top: 68px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 999;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 18px;
  background: rgba(64, 158, 255, 0.1);
  border: 1px solid rgba(64, 158, 255, 0.3);
  border-radius: 20px;
  box-shadow: 0 2px 12px rgba(64, 158, 255, 0.15);
  font-size: 13px;
  color: #409EFF;
  pointer-events: none;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #409EFF;
  flex-shrink: 0;
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.7); }
}

.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
}
.slide-down-enter-from {
  opacity: 0;
  transform: translateX(-50%) translateY(-10px);
}
.slide-down-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-10px);
}
</style>
