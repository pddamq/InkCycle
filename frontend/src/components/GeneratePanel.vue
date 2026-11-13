<template>
  <div v-if="active" class="gen-panel">
    <div class="gen-head">
      <t-icon name="loading" class="gen-spin" />
      <span class="gen-title">{{ title }}</span>
      <span v-if="status" class="gen-status muted">{{ status }}</span>
    </div>
    <div ref="scrollEl" class="gen-body">
      <AgentTrace :items="items" :live="active" :status-hint="status" />
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import AgentTrace from './AgentTrace.vue'

const props = defineProps({
  active: { type: Boolean, default: false },
  title: { type: String, default: 'AI 生成中' },
  status: { type: String, default: '' },
  items: { type: Array, default: () => [] },
})

const scrollEl = ref(null)

watch(() => props.items.length, () => {
  if (!props.active) return
  requestAnimationFrame(() => {
    const el = scrollEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
})

onMounted(() => {
  watch(() => props.active, (v) => {
    if (v) requestAnimationFrame(() => { if (scrollEl.value) scrollEl.value.scrollTop = 0 })
  })
})
</script>

<style scoped>
.gen-panel {
  border: 1px solid var(--td-brand-color-light);
  border-radius: var(--td-radius-medium);
  background: var(--td-bg-color-container);
  overflow: hidden;
  margin-top: 12px;
}
.gen-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: var(--td-bg-color-secondarycontainer);
  border-bottom: 1px solid var(--td-component-stroke);
}
.gen-title { font-weight: 600; }
.gen-status { margin-left: auto; font-size: 12px; max-width: 50%; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gen-body {
  min-height: 120px;
  max-height: 320px;
  overflow-y: auto;
  padding: 12px 14px;
}
.gen-spin { color: var(--td-brand-color); animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
