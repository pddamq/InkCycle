<template>
  <div class="diff-view">
    <div v-for="(row, i) in parts" :key="i" :class="['diff-row', 'diff-' + row.type]">
      <span class="diff-gutter">{{ gutter(row.type) }}</span>
      <span class="diff-line">{{ row.line || ' ' }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { diffLines } from '../textDiff'

const props = defineProps({
  oldText: { type: String, default: '' },
  newText: { type: String, default: '' },
})

const parts = computed(() => diffLines(props.oldText, props.newText))

function gutter(type) {
  if (type === 'add') return '+'
  if (type === 'remove') return '−'
  return ' '
}
</script>

<style scoped>
.diff-view {
  font-family: ui-monospace, 'PingFang SC', 'Microsoft YaHei', Consolas, monospace;
  font-size: 14px; line-height: 1.75; border-radius: 8px; overflow: hidden;
  border: 1px solid var(--td-component-stroke);
}
.diff-row { display: flex; white-space: pre-wrap; word-break: break-word; }
.diff-gutter {
  flex: 0 0 28px; text-align: center; user-select: none;
  color: var(--td-text-color-placeholder); background: var(--td-bg-color-page);
  border-right: 1px solid var(--td-component-stroke);
}
.diff-line { flex: 1; padding: 0 10px; min-width: 0; }
.diff-equal .diff-line { background: var(--td-bg-color-container); }
.diff-add { background: rgba(45, 190, 120, 0.12); }
.diff-add .diff-gutter { color: #2be07f; background: rgba(45, 190, 120, 0.18); }
.diff-remove { background: rgba(227, 77, 89, 0.1); }
.diff-remove .diff-gutter { color: #e34d59; background: rgba(227, 77, 89, 0.15); }
</style>
