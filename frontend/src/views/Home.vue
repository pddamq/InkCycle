<template>
  <div class="home page">
    <header class="home-hero surface surface-padded">
      <div class="hero-text">
        <h1 class="page-title" style="margin:0">小说创作 Agent</h1>
        <p class="page-subtitle">开书访谈 · 导入拆章 · 文风分析 · 剧情流程图 · 一键仿写</p>
      </div>
      <div class="hero-actions">
      <t-button theme="primary" @click="$router.push('/new')">
        <template #icon><t-icon name="add" /></template>
        开书访谈
      </t-button>
      <t-button variant="outline" @click="$router.push('/import')">
        <template #icon><t-icon name="upload" /></template>
        导入书籍
      </t-button>
      <t-button variant="outline" @click="$router.push('/extensions')">
        <template #icon><t-icon name="extension" /></template>
        扩展中心
      </t-button>
      <t-button variant="outline" @click="exportBackup">
        <template #icon><t-icon name="download" /></template>
        备份
      </t-button>
      <t-button variant="outline" @click="$router.push('/settings')">
        <template #icon><t-icon name="setting" /></template>
        设置
      </t-button>
      </div>
    </header>

    <t-alert v-if="interviewDraft" theme="info" style="margin-bottom:16px">
      <template #message>
        <div class="banner-row">
          <span>{{ draftHint(interviewDraft) }}</span>
          <span class="banner-actions">
            <t-button size="small" theme="primary" variant="text" @click="$router.push('/new')">继续</t-button>
            <t-button size="small" theme="danger" variant="text" @click="discardDraftOpen = true">放弃访谈</t-button>
          </span>
        </div>
      </template>
    </t-alert>

    <t-alert v-if="importSession?.needs_resume" theme="warning" style="margin-bottom:16px">
      <template #message>
        <div class="banner-row">
          <span>《{{ importSession.title }}》导入分析未完成（关键章 {{ importSession.deep_done }}/{{ importSession.deep }}）</span>
          <span class="banner-actions">
            <t-button size="small" theme="primary" variant="text" @click="goImportAnalyze">继续分析</t-button>
          </span>
        </div>
      </template>
    </t-alert>

    <t-alert v-else-if="lastSession?.route" theme="info" style="margin-bottom:16px">
      <template #message>
        继续上次：{{ lastSession.label || lastSession.route }}
        <t-button size="small" theme="primary" variant="text" style="margin-left:12px" @click="goLast">继续</t-button>
      </template>
    </t-alert>

    <t-alert v-if="!hasKey" theme="warning" style="margin-bottom:16px"
      message="尚未配置 API Key，AI 功能不可用。请到「设置」填入 OpenAI 兼容接口的 Key。" />

    <t-loading :loading="loading" show-overlay>
      <div v-if="projects.length" class="card-list">
        <t-card v-for="p in projects" :key="p.id" hover-shadow class="proj-card"
          @click="$router.push(`/project/${p.id}`)">
          <template #title>
            <div class="proj-title">
              <t-icon name="book" class="book-icon" />
              <span>{{ p.title }}</span>
            </div>
          </template>
          <template #actions>
            <span @click.stop>
              <t-button size="small" variant="text" theme="danger"
                @click="openDelete(p.id)">
                <t-icon name="delete" />
              </t-button>
            </span>
          </template>
          <div class="proj-meta">
            <t-tag size="small" variant="light">{{ p.genre || '未分类' }}</t-tag>
            <t-tag v-if="p.brief?.source==='imported'" size="small" theme="warning" variant="light">导入</t-tag>
            <t-tag v-if="p.brief?.source==='imitated'" size="small" theme="success" variant="light">仿写</t-tag>
            <span class="muted">目标 {{ (p.target_words / 10000).toFixed(1) }} 万字</span>
          </div>
          <div class="proj-premise">{{ p.premise || '（暂无简介）' }}</div>
          <t-progress :percentage="progress(p)" theme="primary" />
          <div class="proj-stats muted">
            <span>{{ p.stats.chapters_done }}/{{ p.stats.chapters }} 章</span>
            <span>{{ p.stats.words }} 字</span>
            <span>伏笔 {{ p.stats.foreshadow_open }} 待回收</span>
          </div>
        </t-card>
      </div>
      <t-empty v-else-if="!loading" description="还没有作品，点「开书访谈」或「导入书籍」开始" />
    </t-loading>

    <t-dialog v-model:visible="deleteOpen" header="删除作品" :on-confirm="confirmDelete">
      <p>确定删除该作品？所有章节、版本与相关数据将一并移除，且无法恢复。</p>
    </t-dialog>

    <t-dialog v-model:visible="discardDraftOpen" header="放弃访谈" :on-confirm="confirmDiscardDraft">
      <p>确定放弃本次开书访谈？已填写的回答与生成进度将被清除，且无法恢复。</p>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import { loadLastSession } from '../composables/useSession'
import { loadInterviewDraft, draftHint, discardInterviewDraft } from '../composables/useInterviewDraft'

const router = useRouter()
const projects = ref([])
const loading = ref(false)
const hasKey = ref(true)
const lastSession = ref(null)
const importSession = ref(null)
const interviewDraft = ref(null)
const deleteOpen = ref(false)
const deleteId = ref(null)
const discardDraftOpen = ref(false)

function progress(p) {
  if (!p.stats.chapters) return 0
  return Math.round((p.stats.chapters_done / p.stats.chapters) * 100)
}

async function load() {
  loading.value = true
  try {
    projects.value = await api.get('/api/projects')
    const cfg = await api.get('/api/config')
    hasKey.value = !!cfg.has_key
    lastSession.value = await loadLastSession()
    interviewDraft.value = await loadInterviewDraft()
    try {
      const imp = await api.get('/api/import/session')
      importSession.value = imp?.needs_resume ? imp : null
    } catch {
      importSession.value = null
    }
  } catch (e) {
    MessagePlugin.error('加载失败：' + e.message)
  } finally {
    loading.value = false
  }
}

function goLast() {
  if (lastSession.value?.route) router.push(lastSession.value.route)
}

function goImportAnalyze() {
  const pid = importSession.value?.pid
  if (pid) router.push(`/import?pid=${pid}`)
}

async function exportBackup() {
  try {
    const res = await fetch('/api/backup/export')
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'novel-agent-backup.zip'
    a.click()
    MessagePlugin.success('备份已开始下载')
  } catch (e) {
    MessagePlugin.error(e.message)
  }
}

function openDelete(id) {
  deleteId.value = id
  deleteOpen.value = true
}

async function confirmDelete() {
  if (!deleteId.value) return
  try {
    await api.del(`/api/projects/${deleteId.value}`)
    MessagePlugin.success('已删除')
    deleteOpen.value = false
    deleteId.value = null
    load()
  } catch (e) {
    MessagePlugin.error(e.message)
  }
}

async function confirmDiscardDraft() {
  try {
    await discardInterviewDraft()
    interviewDraft.value = null
    if (lastSession.value?.route === '/new') lastSession.value = null
    discardDraftOpen.value = false
    MessagePlugin.success('已清除访谈记录')
  } catch (e) {
    MessagePlugin.error(e.message)
  }
}

onMounted(load)
</script>

<style scoped>
.home-hero {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 20px; margin-bottom: 20px; flex-wrap: wrap;
}
.hero-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.proj-card {
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
  border-radius: var(--app-radius-md);
}
.proj-card:hover { transform: translateY(-2px); }
.proj-title { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 600; }
.book-icon { color: var(--td-brand-color); }
.proj-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.proj-premise {
  font-size: 13px; color: var(--td-text-color-secondary);
  margin-bottom: 12px; line-height: 1.65;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.proj-stats { display: flex; gap: 16px; margin-top: 10px; font-size: 12px; flex-wrap: wrap; }
</style>
