<template>
  <div ref="rootEl" class="agent-trace">
    <div v-if="!items.length && (emptyText || statusHint || live)" class="trace-empty">
      <t-icon v-if="live && !emptyText" name="loading" class="trace-spin" />
      <span v-if="statusHint || emptyText" class="trace-status">{{ statusHint || emptyText }}</span>
    </div>
    <div v-for="(it, i) in items" :key="i" :class="['trace-item', 'trace-' + it.type]">
      <template v-if="it.type === 'phase'">
        <div class="trace-label">▶ {{ it.text }}</div>
      </template>
      <template v-else-if="it.type === 'status'">
        <div class="trace-status">▸ {{ it.text }}</div>
      </template>
      <template v-else-if="it.type === 'progress'">
        <div class="trace-progress">
          <t-icon v-if="live" name="loading" class="trace-spin trace-progress-spin" />
          {{ it.text }}
        </div>
      </template>
      <template v-else-if="it.type === 'reasoning'">
        <details :open="reasoningOpen(i)" class="trace-block thinking">
          <summary>{{ reasoningSummary(it, i) }}</summary>
          <pre v-if="reasoningVisible(i)">{{ reasoningDisplay(it, i) }}</pre>
          <div v-else class="trace-muted">思考内容已折叠（{{ (it.text || '').length }} 字）</div>
        </details>
      </template>
      <template v-else-if="it.type === 'tool_call'">
        <div class="trace-block tool">
          <div class="trace-label">🔧 {{ it.name || '调用工具…' }}</div>
          <pre v-if="it.argsText">{{ it.argsText }}</pre>
        </div>
      </template>
      <template v-else-if="it.type === 'tool_result'">
        <div class="trace-block result">
          <div class="trace-label">↳ {{ it.name || '工具结果' }}</div>
          <pre>{{ it.text }}</pre>
        </div>
      </template>
      <template v-else-if="it.type === 'output'">
        <details class="trace-block output">
          <summary>模型输出</summary>
          <pre>{{ it.text }}</pre>
        </details>
      </template>
      <template v-else-if="it.type === 'error'">
        <div class="trace-error">✗ {{ it.text }}</div>
      </template>
      <template v-else>
        <div class="trace-muted">{{ it.text }}</div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const LIVE_TAIL = 2400

const props = defineProps({
  items: { type: Array, default: () => [] },
  emptyText: { type: String, default: '' },
  /** 父级已知进度（如 GeneratePanel 的 status），轨迹尚未收到 SSE 时先展示 */
  statusHint: { type: String, default: '' },
  /** 进行中：思考块展开；思考结束或流结束则自动折叠 */
  live: { type: Boolean, default: false },
})

const rootEl = ref(null)
let scrollPreRaf = 0

function isLastReasoning(index) {
  const last = props.items[props.items.length - 1]
  return last?.type === 'reasoning' && index === props.items.length - 1
}

function reasoningOpen(index) {
  if (!props.live) return false
  return isLastReasoning(index)
}

function reasoningVisible(index) {
  if (!props.live) return true
  return isLastReasoning(index)
}

function reasoningSummary(it, index) {
  const n = (it.text || '').length
  if (props.live && isLastReasoning(index)) {
    return n > 0 ? `思考中（${n} 字）` : '思考中'
  }
  return n > 0 ? `思考（${n} 字）` : '思考'
}

function reasoningDisplay(it, index) {
  const text = it.text || ''
  if (!props.live || !isLastReasoning(index)) return text
  if (text.length <= LIVE_TAIL) return text
  return `…（仅显示最近 ${LIVE_TAIL} 字）\n${text.slice(-LIVE_TAIL)}`
}

/** 仅跟踪最后一条思考的长度，避免 deep watch 全量扫描 */
watch(
  () => {
    const last = props.items[props.items.length - 1]
    return last?.type === 'reasoning' ? (last.text?.length || 0) : -1
  },
  () => {
    if (!props.live) return
    if (scrollPreRaf) cancelAnimationFrame(scrollPreRaf)
    scrollPreRaf = requestAnimationFrame(() => {
      scrollPreRaf = 0
      nextTick(() => {
        const pre = rootEl.value?.querySelector('.trace-block.thinking:last-of-type pre')
        if (pre && pre.scrollHeight - pre.scrollTop - pre.clientHeight <= 40) {
          pre.scrollTop = pre.scrollHeight
        }
      })
    })
  },
)
</script>

<style scoped>
.agent-trace { font-size: 13px; line-height: 1.55; }
.trace-empty { padding: 4px 0; min-height: 24px; display: flex; align-items: center; }
.trace-spin { color: var(--td-brand-color); animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.trace-item { margin-bottom: 10px; }
.trace-label { font-weight: 600; margin-bottom: 4px; }
.trace-muted { color: var(--td-text-color-secondary); }
.trace-status { color: var(--td-brand-color); font-weight: 500; }
.trace-progress {
  display: flex; align-items: center; gap: 6px;
  color: var(--td-brand-color); font-size: 12px; font-weight: 500;
  padding: 6px 10px; border-left: 2px solid var(--td-brand-color-light);
  background: var(--td-bg-color-secondarycontainer); border-radius: 6px;
}
.trace-progress-spin { flex-shrink: 0; }
.trace-error { color: var(--td-error-color); }
.trace-block {
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-sm, 8px);
  padding: 10px 12px;
  background: var(--td-bg-color-page);
}
.trace-block.thinking { border-color: var(--td-brand-color-light); }
.trace-block.tool { border-color: var(--td-warning-color-3); }
.trace-block.result { border-color: var(--td-success-color-3); }
.trace-block summary { cursor: pointer; font-weight: 600; margin-bottom: 4px; color: var(--td-text-color-secondary); }
.trace-block pre {
  margin: 0; white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, Consolas, monospace; font-size: 12px;
  max-height: 220px; overflow-y: auto;
}
</style>
