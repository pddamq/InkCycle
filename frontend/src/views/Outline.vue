<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin:0">大纲</h1>
      <div class="spacer"></div>
      <t-button variant="outline" @click="regenOpen = true"><t-icon name="magic" /> AI 生成大纲</t-button>
      <t-button variant="outline" @click="addVolume"><t-icon name="add" /> 新增卷</t-button>
    </div>

    <t-loading :loading="loading" show-overlay>
      <div v-for="v in outline" :key="v.id" class="vol">
        <div class="vol-head">
          <t-icon name="folder-open" class="vol-ic" />
          <t-input v-model="v.title" class="vol-title" @blur="saveVolume(v)" />
          <t-tag size="small" variant="light">{{ v.chapters.length }} 章</t-tag>
          <div class="spacer"></div>
          <t-button size="small" variant="text" @click="addChapter(v)"><t-icon name="add" /> 章</t-button>
          <t-popconfirm content="删除该卷及其所有章节？" @confirm="removeVolume(v.id)">
            <t-button size="small" variant="text" theme="danger"><t-icon name="delete" /></t-button>
          </t-popconfirm>
        </div>
        <t-textarea v-model="v.summary" placeholder="本卷主线概要…" :autosize="{minRows:1,maxRows:3}"
          class="vol-summary" @blur="saveVolume(v)" />

        <div v-for="ch in v.chapters" :key="ch.id" class="ch-row" @click="goChapter(ch)">
          <t-tag size="small" :theme="statusTheme(ch.status)" variant="light" class="ch-status">{{ statusText(ch) }}</t-tag>
          <span class="ch-idx">{{ ch.idx + 1 }}</span>
          <span class="ch-title">{{ ch.title }}</span>
          <span class="muted ch-brief">{{ ch.brief }}</span>
          <span class="muted ch-wc" v-if="ch.word_count">{{ ch.word_count }}字</span>
          <t-button size="small" variant="text" theme="danger" @click.stop="removeChapter(ch.id)">
            <t-icon name="delete" />
          </t-button>
        </div>
        <div v-if="!v.chapters.length" class="muted" style="padding:6px 16px">本卷暂无章节</div>
      </div>
      <t-empty v-if="!outline.length && !loading" description="还没有大纲，点「AI 生成大纲」或「新增卷」" />
    </t-loading>

    <t-dialog
      v-model:visible="regenOpen"
      header="AI 生成大纲"
      width="640px"
      :footer="gen.active ? false : undefined"
      :on-confirm="regen"
      :confirm-btn="{ loading: regenLoading, disabled: gen.active }"
    >
      <t-alert v-if="!gen.active" theme="warning" message="将覆盖现有大纲（含所有空章节）。已有正文的章节版本会保留在历史中，但章节列表会重建。确定继续？" />
      <GeneratePanel
        :active="gen.active"
        title="规划全书大纲"
        :status="gen.status"
        :items="gen.items"
      />
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import GeneratePanel from '../components/GeneratePanel.vue'
import { useGenerateStream } from '../composables/useGenerateStream'
import { hydrateGenerationSnapshot } from '../composables/generationSession'

const route = useRoute()
const router = useRouter()
const pid = computed(() => route.params.pid)
const outline = ref([])
const loading = ref(false)
const regenOpen = ref(false)
const regenLoading = ref(false)
const gen = useGenerateStream(`outline:${route.params.pid}`, {
  extraSnapshot: () => ({ regenOpen: regenOpen.value, regenLoading: regenLoading.value }),
  restoreExtra: (ex) => {
    if (ex?.regenOpen != null) regenOpen.value = ex.regenOpen
    if (ex?.regenLoading != null) regenLoading.value = ex.regenLoading
  },
})

const STATUS = {
  todo: { text: '待写', theme: 'default' },
  drafted: { text: '初稿', theme: 'warning' },
  reviewed: { text: '已审', theme: 'primary' },
  final: { text: '定稿', theme: 'success' },
}
function statusText(ch) { return ch.has_content ? (STATUS[ch.status]?.text || '已写') : (STATUS[ch.status]?.text || '待写') }
function statusTheme(ch) { return ch.has_content ? (STATUS[ch.status]?.theme || 'default') : 'default' }

async function load() {
  loading.value = true
  try { outline.value = await api.get(`/api/projects/${pid.value}/outline`) }
  catch (e) { MessagePlugin.error(e.message) }
  finally { loading.value = false }
}

function goChapter(ch) { router.push(`/project/${pid.value}/chapter/${ch.id}`) }

async function saveVolume(v) {
  try { await api.put(`/api/projects/${pid.value}/volumes/${v.id}`, { title: v.title, summary: v.summary }) }
  catch (e) { MessagePlugin.error(e.message) }
}

async function addVolume() {
  try { await api.post(`/api/projects/${pid.value}/volumes`, { title: `第${outline.value.length + 1}卷` }); load() }
  catch (e) { MessagePlugin.error(e.message) }
}

async function removeVolume(id) {
  try { await api.del(`/api/projects/${pid.value}/volumes/${id}?cascade=true`); MessagePlugin.success('已删除'); load() }
  catch (e) { MessagePlugin.error(e.message) }
}

async function addChapter(v) {
  try {
    const r = await api.post(`/api/projects/${pid.value}/chapters`, { volume_id: v.id, title: '新章节' })
    router.push(`/project/${pid.value}/chapter/${r.id}`)
  } catch (e) { MessagePlugin.error(e.message) }
}

async function removeChapter(id) {
  try { await api.del(`/api/projects/${pid.value}/chapters/${id}`); MessagePlugin.success('已删除'); load() }
  catch (e) { MessagePlugin.error(e.message) }
}

function regen() {
  if (gen.active) return false
  regenLoading.value = true
  gen.start(
    `/api/projects/${pid.value}/wizard/outline`,
    {},
    {
      onEvent(ev) {
        if (ev.type === 'done') {
          MessagePlugin.success(`已生成 ${ev.volumes} 卷 ${ev.chapters} 章`)
          regenOpen.value = false
          gen.clearPersisted()
          load()
        } else if (ev.type === 'error') MessagePlugin.error(ev.message)
      },
      onDone() { regenLoading.value = false },
      onError(e) { MessagePlugin.error(e.message); regenLoading.value = false },
    },
  )
}

onMounted(async () => {
  await load()
  const saved = await hydrateGenerationSnapshot(`outline:${route.params.pid}`)
  if (saved?.snapshot?.items?.length || saved?.interrupted) {
    regenOpen.value = true
    if (saved.interrupted) MessagePlugin.info('上次大纲生成被中断，进度已恢复，可重新生成')
  }
})
</script>

<style scoped>
.vol { background: var(--td-bg-color-container); border: 1px solid var(--td-component-stroke); border-radius: var(--td-radius-medium); margin-bottom: 16px; overflow: hidden; }
.vol-head { display: flex; align-items: center; gap: 10px; padding: 12px 16px; background: var(--td-bg-color-secondarycontainer); }
.vol-ic { color: var(--td-brand-color); }
.vol-title { flex: 1; max-width: 360px; font-weight: 600; }
.vol-summary { border: none; border-radius: 0; padding: 8px 16px; }
.ch-row { display: flex; align-items: center; gap: 10px; padding: 8px 16px; border-top: 1px solid var(--td-component-stroke); cursor: pointer; }
.ch-row:hover { background: var(--td-bg-color-container-hover); }
.ch-idx { color: var(--td-text-color-placeholder); min-width: 24px; }
.ch-title { font-weight: 500; min-width: 120px; }
.ch-brief { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.ch-wc { min-width: 56px; text-align: right; }
</style>
