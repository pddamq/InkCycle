<template>
  <div v-if="sessions.length" class="gen-banner">
    <t-icon name="loading" class="spin" />
    <span>AI 生成进行中</span>
    <t-divider layout="vertical" />
    <router-link
      v-for="s in sessions"
      :key="s.key"
      :to="s.route"
      class="gen-link"
    >{{ s.label }}</router-link>
  </div>
</template>

<script setup>
import { useActiveGenerationSessions } from '../composables/generationSession'

const sessions = useActiveGenerationSessions()
</script>

<style scoped>
.gen-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 20px;
  background: linear-gradient(90deg, var(--td-brand-color-light), var(--td-bg-color-container));
  color: var(--td-text-color-primary);
  font-size: 13px;
  border-bottom: 1px solid var(--td-brand-color-focus);
  flex-shrink: 0;
  font-weight: 500;
}
.gen-link {
  color: var(--td-brand-color);
  text-decoration: none;
  font-weight: 500;
}
.gen-link:hover { text-decoration: underline; }
.spin { animation: spin 1s linear infinite; color: var(--td-brand-color); }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
