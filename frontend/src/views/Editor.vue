<template>
  <div class="editor-page">
    <!-- 顶部章节导航 -->
    <header class="ed-topbar page-topbar">
      <t-button variant="text" size="small" @click="$router.push(`/project/${pid}/outline`)">
        <t-icon name="chevron-left" /> 大纲
      </t-button>
      <t-select v-model="chid" class="ch-select" filterable @change="loadChapter">
        <t-option v-for="o in flatChapters" :key="o.id" :value="String(o.id)"
          :label="`${o.volTitle} · ${o.idx+1}. ${o.title}`" />
      </t-select>
      <t-tag size="small" :theme="statusTheme" variant="light">{{ statusText }}</t-tag>
      <div class="spacer"></div>
      <span class="muted">{{ wordCount }} 字</span>
      <t-button size="small" variant="outline" :loading="saving" @click="saveContent(true)">
        <t-icon name="save" /> 保存
      </t-button>
      <t-button size="small" :variant="focusMode ? 'base' : 'outline'" @click="focusMode = !focusMode">
        <t-icon name="fullscreen" /> {{ focusMode ? '退出专注' : '专注模式' }}
      </t-button>
    </header>

    <div class="ed-body" :class="{ 'focus-mode': focusMode }">
      <!-- 左：正文 -->
      <div class="ed-left">
        <div class="ed-field">
          <t-input v-model="chapter.title" placeholder="章节标题" class="title-input" @blur="saveMeta" />
        </div>
        <div class="ed-field">
          <t-textarea v-model="chapter.brief" placeholder="本章梗概（写作依据，可留空）"
            :autosize="{minRows:1,maxRows:3}" @blur="saveMeta" />
        </div>
        <!-- Diff 审阅（Cursor 式接受/拒绝） -->
        <div v-if="pendingDiff" class="diff-panel">
          <div class="diff-bar">
            <span class="diff-title">Agent 提议的变更</span>
            <t-tag size="small" theme="success" variant="light">+{{ pendingDiff.added }}</t-tag>
            <t-tag size="small" theme="danger" variant="light">−{{ pendingDiff.removed }}</t-tag>
            <div class="spacer"></div>
            <t-button size="small" variant="outline" @click="rejectDiff">拒绝</t-button>
            <t-button size="small" theme="primary" @click="acceptDiff">接受变更</t-button>
          </div>
          <div class="diff-scroll">
            <DiffView :old-text="pendingDiff.oldText" :new-text="pendingDiff.newText" />
          </div>
        </div>
        <textarea v-else ref="textareaEl" v-model="content" class="editor-textarea" placeholder="正文…（右侧与 Agent 对话生成）"
          @input="onInput" @blur="saveContent(false)" />
        <div class="muted save-hint">{{ saveHint }}</div>
      </div>

      <!-- 右：Agent 对话 -->
      <div class="ed-right">
        <t-tabs v-model="tab">
          <t-tab-panel value="agent" label="Agent">
            <AgentChatPanel
              ref="chatRef"
              :pid="pid"
              :chid="chid"
              :get-content="() => content"
              :get-selection="getSelection"
              @propose-diff="onProposeDiff"
              @show-diff="onShowDiff"
              @review="onReview"
              @done="onChatDone"
              @auto="autoOpen = true"
            />
          </t-tab-panel>

          <t-tab-panel value="review" label="审校报告">
            <div class="panel">
              <div v-if="review" class="review-box">
                <div class="review-head">
                  <span class="score-ring" :class="review.score>=85?'score-pass':'score-fail'">{{ review.score }}</span>
                  <span class="muted">/ 100 · 第{{ review.round }}轮 · {{ fmt.date(review.created_at) }}</span>
                </div>
                <div class="review-summary">{{ review.report.summary }}</div>
                <t-divider />
                <div v-if="review.report.issues?.length">
                  <div v-for="(it,i) in review.report.issues" :key="i" class="issue">
                    <div class="issue-head">
                      <t-tag size="small" :theme="sevTheme(it.severity)" variant="light">{{ it.severity }}</t-tag>
                      <t-tag size="small" variant="outline">{{ it.type }}</t-tag>
                      <span class="muted">{{ it.location }}</span>
                    </div>
                    <div class="issue-desc">{{ it.description }}</div>
                    <div class="issue-sug">建议：{{ it.suggestion }}</div>
                  </div>
                </div>
                <t-empty v-else description="没有发现问题" size="small" />
              </div>
              <t-empty v-else description="还没有审校报告" />
              <t-button style="margin-top:12px" variant="outline" size="small" @click="loadReviews" :loading="loadingReview">刷新</t-button>
            </div>
          </t-tab-panel>

          <t-tab-panel value="versions" label="版本">
            <div class="panel">
              <t-button variant="outline" size="small" @click="loadVersions" :loading="loadingVer" style="margin-bottom:12px">刷新版本</t-button>
              <div v-for="v in versions" :key="v.id" class="ver-row">
                <t-tag size="small" :theme="vtypeTheme(v.vtype)" variant="light">{{ vtypeText(v.vtype) }}</t-tag>
                <span class="ver-meta">{{ v.word_count }}字 · {{ fmt.date(v.created_at) }}</span>
                <span class="muted ver-note">{{ v.note }}</span>
                <div class="spacer"></div>
                <t-tag v-if="v.is_current" size="small" theme="success" variant="light">当前</t-tag>
                <t-button v-else size="small" variant="text" @click="restore(v.id)">回滚</t-button>
                <t-button size="small" variant="text" @click="preview(v)">查看</t-button>
              </div>
              <t-empty v-if="!versions.length" description="暂无版本" size="small" />
            </div>
          </t-tab-panel>
        </t-tabs>
      </div>
    </div>

    <!-- 自动全流程参数 -->
    <t-dialog v-model:visible="autoOpen" header="自动全流程" :on-confirm="runAuto">
      <t-form label-width="110px">
        <t-form-item label="模式">
          <t-radio-group v-model="autoForm.mode">
            <t-radio value="draft_only">快速（仅初稿）</t-radio>
            <t-radio value="full">完整（初稿→审校→修订循环）</t-radio>
            <t-radio value="polish">打磨（仅审校→修订现有稿）</t-radio>
          </t-radio-group>
        </t-form-item>
        <t-form-item label="最大轮数">
          <t-input-number v-model="autoForm.rounds" :min="1" :max="6" theme="column" />
        </t-form-item>
      </t-form>
      <div class="muted">达标分数与每章字数在「设置」中配置。</div>
    </t-dialog>

    <!-- 版本预览 -->
    <t-dialog v-model:visible="previewOpen" :header="`版本预览 · ${previewVer.vtype||''} ${previewVer.word_count||''}字`" width="720px" :footer="false">
      <pre class="ver-preview">{{ previewVer.content }}</pre>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api, fmt } from '../api'
import AgentChatPanel from '../components/AgentChatPanel.vue'
import DiffView from '../components/DiffView.vue'
import { createAgentTrace } from '../agentTrace'
import { saveLastSession } from '../composables/useSession'
import {
  runGenerationStreamTracked,
  subscribeGenerationSession,
  hydrateGenerationSnapshot,
  persistSessionSnapshot,
  setSessionSnapshotProvider,
  clearSessionSnapshotProvider,
  isSessionActive,
} from '../composables/generationSession'

const route = useRoute()
const pid = computed(() => route.params.pid)
const chid = ref(String(route.params.chid || ''))
const tab = ref('agent')
const chapter = ref({ title: '', brief: '', status: 'todo', word_count: 0 })
const content = ref('')
const flatChapters = ref([])
const chatRef = ref(null)
const logEl = ref(null)
const { handleEvent: traceEvent, clear: clearTrace } = createAgentTrace(logEl)
const busy = ref(false)
const saving = ref(false)
const saveHint = ref('')
const review = ref(null)
const versions = ref([])
const loadingReview = ref(false)
const loadingVer = ref(false)
const autoOpen = ref(false)
const autoForm = ref({ mode: 'draft_only', rounds: 2 })
const previewOpen = ref(false)
const previewVer = ref({})
const pendingDiff = ref(null)
const focusMode = ref(false)
const textareaEl = ref(null)
let saveTimer = null
let skipLoadContent = false
let autoUnsub = null
let localAutoStreaming = false

function autoKey() { return `editor-auto:${pid.value}:${chid.value}` }

async function bindAutoSession() {
  autoUnsub?.()
  const key = autoKey()
  const saved = await hydrateGenerationSnapshot(key)
  if (saved?.snapshot?.content != null && !pendingDiff.value) content.value = saved.snapshot.content
  busy.value = isSessionActive(key)
  autoUnsub = subscribeGenerationSession(key, {
    onRestore: (snap) => {
      if (snap?.content != null && !pendingDiff.value) content.value = snap.content
    },
    onActive: (v) => { busy.value = v },
    onEvent: (ev) => { if (!localAutoStreaming) onAutoEvent(ev) },
    onDone: () => { if (!localAutoStreaming) onAutoEnd() },
    onError: (e) => { if (!localAutoStreaming) onAutoErr(e) },
  })
  setSessionSnapshotProvider(key, () => ({ content: content.value }))
}

const STATUS = { todo: ['待写','default'], drafted: ['初稿','warning'], reviewed: ['已审','primary'], final: ['定稿','success'] }
const statusText = computed(() => STATUS[chapter.value.status]?.[0] || '待写')
const statusTheme = computed(() => STATUS[chapter.value.status]?.[1] || 'default')
const wordCount = computed(() => content.value.replace(/\s/g, '').length)

function sevTheme(s) { return s === '高' ? 'danger' : s === '中' ? 'warning' : 'default' }
function vtypeText(t) { return { draft:'初稿', revise:'修订', manual:'手改', restore:'回滚' }[t] || t }
function vtypeTheme(t) { return { draft:'warning', revise:'primary', manual:'default', restore:'success' }[t] || 'default' }

async function loadFlat() {
  const outline = await api.get(`/api/projects/${pid.value}/outline`)
  flatChapters.value = outline.flatMap(v => v.chapters.map(c => ({ ...c, volTitle: v.title })))
}

async function loadChapter(resetChat = false) {
  if (!chid.value) return
  try {
    const ch = await api.get(`/api/projects/${pid.value}/chapters/${chid.value}`)
    chapter.value = ch
    if (!skipLoadContent && !pendingDiff.value) content.value = ch.content || ''
    review.value = ch.last_review
    if (resetChat && chatRef.value?.clear) chatRef.value.clear()
    loadVersions(); loadReviews()
  } catch (e) { MessagePlugin.error(e.message) }
}

async function loadReviews() {
  loadingReview.value = true
  try {
    const rs = await api.get(`/api/projects/${pid.value}/chapters/${chid.value}/reviews`)
    if (rs.length) review.value = rs[0]
  } catch {} finally { loadingReview.value = false }
}

async function loadVersions() {
  loadingVer.value = true
  try { versions.value = await api.get(`/api/projects/${pid.value}/chapters/${chid.value}/versions`) }
  catch {} finally { loadingVer.value = false }
}

async function saveMeta() {
  try { await api.put(`/api/projects/${pid.value}/chapters/${chid.value}`, { title: chapter.value.title, brief: chapter.value.brief }) }
  catch (e) { MessagePlugin.error(e.message) }
}

function getSelection() {
  const el = textareaEl.value
  if (!el || el.selectionStart === el.selectionEnd) return null
  return { text: content.value.slice(el.selectionStart, el.selectionEnd) }
}

function onInput() {
  saveHint.value = '编辑中…'
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => saveContent(false), 1200)
}

function onGlobalKey(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 's') {
    e.preventDefault()
    saveContent(true)
  }
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'f') {
    e.preventDefault()
    focusMode.value = !focusMode.value
  }
  if (e.key === 'Escape' && focusMode.value) focusMode.value = false
}

function recordSession() {
  saveLastSession({
    project_id: Number(pid.value),
    chapter_id: Number(chid.value),
    route: `/project/${pid.value}/chapter/${chid.value}`,
    label: `${chapter.value.title || '章节'}`,
  })
}

async function saveContent(manual) {
  clearTimeout(saveTimer)
  saving.value = true
  try {
    const r = await api.put(`/api/projects/${pid.value}/chapters/${chid.value}`, { content: content.value })
    chapter.value.word_count = r.word_count
    chapter.value.status = r.status
    saveHint.value = manual ? '已保存' : '自动保存 ' + new Date().toLocaleTimeString()
    loadVersions()
  } catch (e) { MessagePlugin.error(e.message); saveHint.value = '保存失败' }
  finally { saving.value = false }
}

function onProposeDiff(diff) {
  pendingDiff.value = diff
  skipLoadContent = true
}

function onShowDiff(diff) {
  pendingDiff.value = diff
}

async function acceptDiff() {
  if (!pendingDiff.value) return
  content.value = pendingDiff.value.newText
  pendingDiff.value = null
  skipLoadContent = false
  await saveContent(true)
  MessagePlugin.success('已接受变更')
  loadChapter(false)
}

async function rejectDiff() {
  if (!pendingDiff.value) return
  const old = pendingDiff.value.oldText
  pendingDiff.value = null
  skipLoadContent = false
  content.value = old
  await saveContent(true)
  MessagePlugin.info('已拒绝变更，正文已恢复')
  loadVersions()
}

function onReview(ev) {
  review.value = { ...ev, report: { summary: ev.summary, issues: ev.issues }, created_at: '' }
  tab.value = 'review'
}

function onChatDone({ hasDiff } = {}) {
  if (!hasDiff) {
    skipLoadContent = false
    loadChapter(false)
  } else {
    loadVersions()
    loadReviews()
  }
}

function runAuto() {
  autoOpen.value = false
  if (busy.value) return
  localAutoStreaming = true
  busy.value = true
  clearTrace()
  const key = autoKey()
  setSessionSnapshotProvider(key, () => ({ content: content.value }))
  runGenerationStreamTracked(key, `/api/projects/${pid.value}/chapters/${chid.value}/auto`, autoForm.value, {
    onEvent: onAutoEvent,
    onDone: () => { localAutoStreaming = false; onAutoEnd() },
    onError: (e) => { localAutoStreaming = false; onAutoErr(e) },
  })
}

function onAutoEvent(ev) {
  if (ev.type === 'delta') {
    traceEvent(ev, { onDelta: (t) => { content.value += t }, showOutput: false })
  } else if (ev.type === 'content_set') {
    content.value = ev.text || ''
  }
  if (ev.type === 'delta' || ev.type === 'content_set') {
    persistSessionSnapshot(autoKey(), { content: content.value })
  } else if (ev.type === 'phase') {
    if (ev.phase === 'draft' && (ev.round === 1 || ev.round == null) && autoForm.value?.mode !== 'polish') {
      content.value = ''
    }
    traceEvent({ type: 'phase', phase: phaseText(ev) })
  } else if (ev.type === 'review') {
    review.value = { ...ev, report: { summary: ev.summary, issues: ev.issues }, created_at: '' }
    traceEvent({ type: 'status', message: `审校完成：${ev.score} 分` })
  } else if (ev.type === 'reasoning' || ev.type === 'tool_call' || ev.type === 'tool_call_delta'
    || ev.type === 'tool_result' || ev.type === 'output' || ev.type === 'status') {
    traceEvent(ev)
  } else if (ev.type === 'error') {
    traceEvent(ev)
  }
}

function phaseText(ev) {
  const m = { start: `开始（最多${ev.rounds}轮，达标${ev.threshold}分）`, draft: `第${ev.round}轮·初稿`, review: `第${ev.round}轮·审校`, revise: `第${ev.round}轮·修订` }
  return m[ev.phase] || ev.phase
}

function onAutoEnd() { busy.value = false; loadChapter(false) }
function onAutoErr(e) { busy.value = false; MessagePlugin.error(e.message) }

async function restore(vid) {
  try {
    await api.post(`/api/projects/${pid.value}/chapters/${chid.value}/versions/${vid}/restore`)
    MessagePlugin.success('已回滚'); loadChapter(true)
  } catch (e) { MessagePlugin.error(e.message) }
}

async function preview(v) {
  try { previewVer.value = await api.get(`/api/projects/${pid.value}/chapters/${chid.value}/versions/${v.id}`); previewOpen.value = true }
  catch (e) { MessagePlugin.error(e.message) }
}

watch(() => route.params.chid, (v) => {
  if (v) {
    pendingDiff.value = null
    skipLoadContent = false
    chid.value = String(v)
    bindAutoSession()
    loadChapter(false)
  }
})
onMounted(async () => {
  bindAutoSession()
  await loadFlat()
  await loadChapter(false)
  recordSession()
  window.addEventListener('keydown', onGlobalKey)
})
onBeforeUnmount(() => {
  clearTimeout(saveTimer)
  persistSessionSnapshot(autoKey(), { content: content.value })
  autoUnsub?.()
  if (!isSessionActive(autoKey())) clearSessionSnapshotProvider(autoKey())
  window.removeEventListener('keydown', onGlobalKey)
})
watch(chid, () => { if (chapter.value.title) recordSession() })
</script>

<style scoped>
.editor-page { display: flex; flex-direction: column; height: 100%; }
.ed-topbar { padding: 8px 16px; }
.ch-select { width: 320px; }
.ed-body { flex: 1; display: flex; overflow: hidden; }
.ed-left { flex: 1; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; }
.ed-field { margin-bottom: 10px; }
.title-input :deep(input) { font-size: 17px; font-weight: 600; }
.editor-textarea { flex: 1; }
.diff-panel { flex: 1; display: flex; flex-direction: column; min-height: 0; border: 1px solid var(--td-brand-color-light); border-radius: 8px; overflow: hidden; }
.diff-bar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--td-bg-color-page); border-bottom: 1px solid var(--td-component-stroke); }
.diff-title { font-size: 13px; font-weight: 600; }
.diff-scroll { flex: 1; overflow-y: auto; }
.save-hint { margin-top: 6px; font-size: 12px; }
.ed-right { width: 420px; border-left: 1px solid var(--td-component-stroke); background: var(--td-bg-color-container); display: flex; flex-direction: column; overflow: hidden; transition: width .2s, opacity .2s; }
.ed-body.focus-mode .ed-right { width: 0; opacity: 0; pointer-events: none; border: none; overflow: hidden; }
.ed-body.focus-mode .ed-left { max-width: 900px; margin: 0 auto; width: 100%; }
.ed-right :deep(.t-tabs) { height: 100%; display: flex; flex-direction: column; }
.ed-right :deep(.t-tabs__content) { flex: 1; overflow: hidden; }
.ed-right :deep(.t-tab-panel) { height: 100%; }
.ed-right :deep(.t-tabs__content .t-tab-panel) { padding: 12px 14px; box-sizing: border-box; }
.panel { height: 100%; overflow-y: auto; }
.review-head { display: flex; align-items: baseline; gap: 10px; }
.review-summary { margin-top: 8px; color: var(--td-text-color-secondary); }
.issue { padding: 10px 0; border-bottom: 1px dashed var(--td-component-stroke); }
.issue-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.issue-desc { font-size: 13px; }
.issue-sug { font-size: 12px; color: var(--td-text-color-secondary); margin-top: 2px; }
.ver-row { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--td-component-stroke); }
.ver-meta { font-size: 12px; color: var(--td-text-color-secondary); }
.ver-note { font-size: 12px; }
.ver-preview { white-space: pre-wrap; font-family: inherit; line-height: 1.8; max-height: 60vh; overflow-y: auto; }
</style>
