<template>
  <div class="ctx-usage">
    <button type="button" class="ctx-trigger" :class="{ warn: percent >= 75, danger: percent >= 90 }"
      @click.stop="open = !open" :title="tooltip">
      <span class="ctx-pct">{{ percent }}%</span>
      <span class="ctx-label muted">上下文</span>
    </button>

    <div v-if="open" class="ctx-popover" @click.stop>
      <div class="ctx-head">
        <span class="ctx-head-title">{{ percent }}% 已用</span>
        <button type="button" class="ctx-close muted" @click="open = false">×</button>
      </div>
      <div class="ctx-bar-wrap">
        <div class="ctx-bar" :style="{ width: percent + '%' }"></div>
      </div>
      <div class="ctx-total muted">{{ fmtTokens(total) }} / {{ fmtTokens(limit) }} tokens</div>

      <div v-if="loading && !items.length" class="ctx-empty muted">估算中…</div>
      <ul v-else-if="items.length" class="ctx-list">
        <li v-for="it in items" :key="it.key" class="ctx-row">
          <span class="ctx-dot" :style="{ background: it.color }"></span>
          <span class="ctx-name">{{ it.label }}</span>
          <span class="ctx-val">{{ fmtTokens(it.tokens) }}</span>
        </li>
      </ul>
      <div v-else class="ctx-empty muted">暂无占用数据</div>

      <p class="ctx-tip muted">发送前为估算值；流式开始时服务端会更新为实际组装结果。对话过长时会自动压缩为「对话纪要」。</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  usage: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})

const open = ref(false)

const total = computed(() => props.usage?.total ?? 0)
const limit = computed(() => props.usage?.limit ?? 128000)
const percent = computed(() => Math.min(100, props.usage?.percent ?? 0))
const items = computed(() => props.usage?.items ?? [])

const tooltip = computed(() => {
  const rem = props.usage?.remaining ?? (limit.value - total.value)
  return `已用 ${fmtTokens(total.value)} / ${fmtTokens(limit.value)}，剩余约 ${fmtTokens(rem)}`
})

function fmtTokens(n) {
  const v = Number(n) || 0
  if (v >= 1000) return `${(v / 1000).toFixed(1)}K`
  return String(v)
}

function onDocClick() { open.value = false }

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<style scoped>
.ctx-usage { position: relative; flex-shrink: 0; }
.ctx-trigger {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px; border-radius: var(--app-radius-sm, 8px);
  border: 1px solid var(--td-component-border);
  background: var(--td-bg-color-container); cursor: pointer; font-size: 12px;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.ctx-trigger:hover { border-color: var(--td-brand-color); }
.ctx-trigger.warn .ctx-pct { color: #f59e0b; }
.ctx-trigger.danger .ctx-pct { color: #ef4444; }
.ctx-pct { font-weight: 600; font-variant-numeric: tabular-nums; }
.ctx-popover {
  position: absolute; top: calc(100% + 6px); right: 0; z-index: 200;
  width: min(320px, 92vw); padding: 12px 14px;
  background: var(--td-bg-color-container); border: 1px solid var(--td-component-border);
  border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.12);
}
.ctx-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.ctx-head-title { font-weight: 600; font-size: 14px; }
.ctx-close { border: none; background: none; cursor: pointer; font-size: 18px; line-height: 1; padding: 0 4px; }
.ctx-bar-wrap {
  height: 6px; border-radius: 3px; background: var(--td-bg-color-secondarycontainer);
  overflow: hidden; margin-bottom: 6px;
}
.ctx-bar {
  height: 100%; border-radius: 3px;
  background: linear-gradient(90deg, #8b5cf6, #22c55e, #f59e0b, #ef4444);
  transition: width .25s ease;
}
.ctx-total { font-size: 11px; margin-bottom: 10px; }
.ctx-list { list-style: none; margin: 0; padding: 0; }
.ctx-row {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 0; font-size: 12px;
}
.ctx-dot { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
.ctx-name { flex: 1; }
.ctx-val { font-variant-numeric: tabular-nums; color: var(--td-text-color-secondary); }
.ctx-empty { font-size: 12px; padding: 8px 0; }
.ctx-tip { font-size: 11px; margin: 10px 0 0; line-height: 1.45; }
</style>
