<template>
  <t-layout class="proj-layout">
    <t-aside width="220px" class="proj-aside">
      <div class="aside-head">
        <t-button variant="text" size="small" @click="$router.push('/')">
          <t-icon name="chevron-left" /> 返回书架
        </t-button>
        <div class="aside-title">{{ project.title }}</div>
        <div class="muted aside-sub">{{ project.genre }} · {{ (project.target_words/10000).toFixed(1) }}万字</div>
      </div>
      <t-menu :value="active" theme="light" @change="go">
        <t-menu-item value="overview"><template #icon><t-icon name="dashboard" /></template>概览</t-menu-item>
        <t-menu-item value="dashboard"><template #icon><t-icon name="chart" /></template>一致性看板</t-menu-item>
        <t-menu-item value="world"><template #icon><t-icon name="earth" /></template>世界观</t-menu-item>
        <t-menu-item value="characters"><template #icon><t-icon name="usergroup" /></template>角色</t-menu-item>
        <t-menu-item value="outline"><template #icon><t-icon name="view-list" /></template>大纲</t-menu-item>
        <t-menu-item value="plot"><template #icon><t-icon name="chart-bubble" /></template>剧情流程图</t-menu-item>
        <t-menu-item value="book"><template #icon><t-icon name="play-circle" /></template>整本创作</t-menu-item>
        <t-menu-item value="foreshadow"><template #icon><t-icon name="flag" /></template>伏笔</t-menu-item>
        <t-menu-item value="timeline"><template #icon><t-icon name="history" /></template>时间线</t-menu-item>
        <t-menu-item value="export"><template #icon><t-icon name="download" /></template>导出</t-menu-item>
      </t-menu>
    </t-aside>
    <t-layout>
      <t-content class="proj-content">
        <router-view :project="project" @refresh="load" />
      </t-content>
    </t-layout>
  </t-layout>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
const project = ref({ title: '', genre: '', target_words: 0, stats: {} })
const pid = computed(() => route.params.pid)

const active = computed(() => {
  const name = route.name
  if (name === 'editor') return 'outline'
  if (name === 'characterDesign') return 'characters'
  return name || 'overview'
})

async function load() {
  try {
    project.value = await api.get(`/api/projects/${pid.value}`)
  } catch (e) {
    MessagePlugin.error('加载项目失败：' + e.message)
  }
}

function go(val) {
  router.push(`/project/${pid.value}/${val}`)
}

watch(pid, load)
onMounted(load)
</script>

<style scoped>
.proj-layout { height: 100vh; }
.proj-aside {
  border-right: 1px solid var(--td-component-stroke);
  background: var(--td-bg-color-container);
  display: flex; flex-direction: column;
  box-shadow: var(--app-shadow-sm);
}
.aside-head {
  padding: 14px 16px 16px;
  border-bottom: 1px solid var(--td-component-stroke);
  background: linear-gradient(180deg, var(--td-bg-color-container) 0%, var(--td-bg-color-page) 100%);
}
.aside-title { font-size: 15px; font-weight: 600; margin-top: 6px; line-height: 1.35; }
.aside-sub { font-size: 12px; margin-top: 4px; }
.proj-aside :deep(.t-menu) { padding: 8px 6px; }
.proj-aside :deep(.t-menu__item) { border-radius: var(--app-radius-sm); margin: 2px 0; }
.proj-content { overflow-y: auto; background: var(--td-bg-color-page); }
</style>
