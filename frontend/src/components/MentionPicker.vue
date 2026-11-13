<template>
  <div v-if="visible && items.length" class="mention-picker">
    <div v-for="(it, i) in items" :key="i" :class="['mention-item', { active: i === idx }]"
      @mousedown.prevent="pick(it)">
      <span class="mention-type">{{ typeLabel(it.type) }}</span>
      <span class="mention-label">{{ it.label }}</span>
      <span v-if="it.hint" class="mention-hint">{{ it.hint }}</span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  visible: Boolean,
  items: { type: Array, default: () => [] },
  idx: { type: Number, default: 0 },
})

const emit = defineEmits(['pick'])

function typeLabel(t) {
  return { character: '角色', world: '设定', chapter: '章节', foreshadow: '伏笔' }[t] || t
}

function pick(it) {
  emit('pick', it)
}
</script>

<style scoped>
.mention-picker {
  position: absolute; left: 0; right: 0; bottom: 100%; margin-bottom: 4px;
  max-height: 200px; overflow-y: auto; background: var(--td-bg-color-container);
  border: 1px solid var(--td-component-stroke); border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0,0,0,.08); z-index: 20;
}
.mention-item { padding: 8px 12px; cursor: pointer; display: flex; gap: 8px; align-items: baseline; font-size: 13px; }
.mention-item:hover, .mention-item.active { background: var(--td-brand-color-light); }
.mention-type { font-size: 11px; color: var(--td-brand-color); flex-shrink: 0; }
.mention-label { font-weight: 600; flex: 1; }
.mention-hint { font-size: 11px; color: var(--td-text-color-secondary); }
</style>
