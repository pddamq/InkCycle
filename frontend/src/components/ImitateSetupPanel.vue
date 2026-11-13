<template>
  <div class="imitate-setup">
    <div class="imitate-progress-head">
      <span class="imitate-phase">{{ phase || '准备中…' }}</span>
      <span v-if="status" class="muted imitate-status">{{ status }}</span>
    </div>
    <t-progress :percentage="pctValue" theme="plump" />
    <div class="imitate-pct muted">{{ pctValue }}%</div>
    <div class="imitate-trace">
      <AgentTrace :items="itemList" :live="running" :status-hint="traceHint" />
    </div>
    <div v-if="err" class="imitate-err">{{ err }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import AgentTrace from './AgentTrace.vue'

const props = defineProps({
  running: { type: Boolean, default: false },
  pct: { type: Number, default: 0 },
  status: { type: String, default: '' },
  phase: { type: String, default: '' },
  err: { type: String, default: '' },
  items: { type: Array, default: () => [] },
})

const pctValue = computed(() => {
  const v = props.pct
  if (typeof v === 'number' && !Number.isNaN(v)) return Math.max(0, Math.min(100, v))
  if (v && typeof v === 'object' && 'value' in v) {
    const n = Number(v.value)
    return Number.isNaN(n) ? 0 : Math.max(0, Math.min(100, n))
  }
  return 0
})

/** 兼容父级误传未解包的 ref/computed */
const itemList = computed(() => {
  const v = props.items
  if (Array.isArray(v)) return v
  if (v && typeof v === 'object' && 'value' in v) {
    const inner = v.value
    return Array.isArray(inner) ? inner : []
  }
  return []
})

const traceHint = computed(() => {
  if (props.status) return props.status
  if (props.running) return props.phase ? `${props.phase}…` : '处理中…'
  return ''
})
</script>

<style scoped>
.imitate-setup { display: flex; flex-direction: column; gap: 12px; }
.imitate-progress-head {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
}
.imitate-phase { font-weight: 600; }
.imitate-pct { font-size: 12px; text-align: right; margin-top: -4px; }
.imitate-status { font-size: 12px; max-width: 55%; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.imitate-trace {
  max-height: 360px; overflow-y: auto;
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--td-radius-medium);
  padding: 12px 14px;
  background: var(--td-bg-color-container);
}
.imitate-err { color: var(--td-error-color); font-size: 13px; }
</style>
