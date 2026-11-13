<template>
  <div class="import-page page-full">
    <PageTopbar title="导入书籍" icon="upload" back-to="/" back-label="返回书架">
      <template #actions>
        <t-tag v-if="phase==='upload'" theme="primary" variant="light">上传 / 粘贴</t-tag>
        <t-tag v-else-if="phase==='preview'" theme="primary" variant="light">{{ preview.chapter_count }} 章</t-tag>
        <t-tag v-else-if="phase==='analyzing'" theme="warning" variant="light">分析中</t-tag>
        <t-tag v-else theme="success" variant="light">已完成</t-tag>
      </template>
    </PageTopbar>

    <div class="page page-narrow import-content">
      <!-- 上传 -->
      <div v-if="phase==='upload'">
        <t-alert theme="info" style="margin-bottom:16px"
          message="导入 txt / md，自动拆卷拆章。文风抽样 3 章；剧情深度解析比例可在预览页选择（10%～100%），比例越高耗时越长。" />
        <t-card title="选择文件" style="margin-bottom:16px">
          <t-upload
            v-model="files"
            class="import-drop"
            theme="file"
            :auto-upload="false"
            accept=".txt,.md,.markdown,text/plain"
            :max="1"
            draggable
            @change="onFile"
          >
            <div class="import-drop-inner">
              <t-icon name="upload" size="28px" />
              <span class="import-drop-highlight">点击选择文件</span>
              <span class="muted">或将 txt / md 拖拽到此处</span>
              <span v-if="previewing" class="muted">正在识别章节…</span>
            </div>
          </t-upload>
          <div class="muted" style="margin-top:8px">支持 UTF-8 / GBK。按「第X章 / 第X卷 / Chapter N / 楔子」拆章。</div>
        </t-card>
        <t-card title="或粘贴正文">
          <t-textarea v-model="paste" placeholder="把全书正文贴在这里…" :autosize="{minRows:10,maxRows:22}" />
          <div class="toolbar" style="margin-top:12px">
            <t-input v-model="filename" placeholder="可选：文件名，用于猜测书名" style="width:240px" />
            <div class="spacer"></div>
            <t-button theme="primary" :loading="previewing" :disabled="!paste.trim()" @click="previewPaste">
              识别章节
            </t-button>
          </div>
        </t-card>
      </div>

      <!-- 预览 -->
      <div v-else-if="phase==='preview'">
        <t-card title="拆章结果" style="margin-bottom:16px">
          <t-form label-width="80px">
            <t-form-item label="书名"><t-input v-model="preview.title" /></t-form-item>
            <t-form-item label="类型"><t-input v-model="genre" placeholder="可留空，分析后会补" /></t-form-item>
          </t-form>
          <div class="muted" style="margin-bottom:12px">
            {{ preview.volume_count }} 卷 · {{ preview.chapter_count }} 章 · {{ preview.words }} 字
          </div>
          <t-form-item label="深度解析比例">
            <t-select v-model="deepRatio" :options="deepRatioOptions" style="max-width:320px" />
            <t-alert theme="warning" style="margin-top:10px" :message="timeEstimateHint" />
            <div class="muted" style="margin-top:8px">
              约 {{ estimatedDeep }} / {{ preview.chapter_count }} 章将进行 LLM 深度解析（摘要、流程图节点），其余章保留标题占位，可立即阅读。
              比例越高，需要调用模型的章节越多，总耗时越久。
            </div>
          </t-form-item>
          <div v-for="(vol, vi) in preview.volumes" :key="vi" class="vol-block">
            <div class="vol-title">{{ vol.title }}</div>
            <div v-for="(ch, ci) in vol.chapters" :key="ci" class="ch-row">
              <span class="ch-title">{{ ch.title }}</span>
              <span class="muted">{{ ch.words }} 字</span>
              <span class="ch-snip muted">{{ snip(ch.content) }}</span>
            </div>
          </div>
          <div class="toolbar" style="margin-top:16px">
            <t-button variant="outline" @click="resetUpload">重新选择</t-button>
            <div class="spacer"></div>
            <t-button theme="primary" :loading="committing" @click="commitAndAnalyze">
              导入并分析
            </t-button>
          </div>
        </t-card>
      </div>

      <!-- 分析中 / 完成 -->
      <div v-else>
        <t-card>
          <div class="stage-row">
            <t-icon :name="styleDone ? 'check-circle-filled' : (phase==='analyzing' && !styleDone ? 'loading' : 'time')"
              :class="styleDone ? 'ic-done' : 'ic-run'" />
            <span>解析文风</span>
            <span class="muted">{{ styleMsg }}</span>
          </div>
          <div class="stage-row">
            <t-icon :name="plotDone ? 'check-circle-filled' : (styleDone && phase==='analyzing' && !plotDone ? 'loading' : 'time')"
              :class="plotDone ? 'ic-done' : 'ic-run'" />
            <span>拆解剧情 / 流程图数据</span>
            <span class="muted">{{ plotMsg }}</span>
          </div>
          <div v-if="showVolumeStageRow" class="stage-row">
            <t-icon :name="sessionLive ? 'loading' : 'time'" :class="sessionLive ? 'ic-run' : ''" />
            <span>卷级剧情归纳</span>
            <span class="muted">{{ volumeStageHint }}</span>
          </div>
          <div v-if="phase==='analyzing' || traceItems.length" class="import-trace">
            <div class="import-trace-head">
              <t-icon v-if="phase==='analyzing'" name="loading" class="ic-run trace-spin" />
              <t-icon v-else name="check-circle-filled" class="ic-done" />
              <span class="import-trace-title">{{ analyzeTitle }}</span>
              <span v-if="analyzeStatus" class="muted import-trace-status">{{ analyzeStatus }}</span>
            </div>
            <div class="import-trace-body">
              <AgentTrace :items="traceItems" :live="phase==='analyzing'" :status-hint="traceStatusHint" />
            </div>
          </div>
          <div v-if="styleProfile.style_summary" class="style-box">
            <div class="style-h">文风档案</div>
            <div>{{ styleProfile.style_summary }}</div>
            <div class="muted" style="margin-top:8px">
              <span v-if="styleProfile.pov">视角 {{ styleProfile.pov }} · </span>
              <span v-if="styleProfile.pacing">节奏 {{ styleProfile.pacing }} · </span>
              <span v-if="styleProfile.tone">{{ styleProfile.tone }}</span>
            </div>
          </div>
          <t-alert v-if="plotPartial && phase==='done' && !needsResume" theme="success" style="margin-top:12px"
            :message="`分析完成：深度 ${plotDeep} 章（${deepRatioLabel}）+ 占位 ${plotLight} 章。正文已全部可读；需要每章摘要可点「深度补全全书」。`" />
          <div v-if="err" class="err">{{ err }}</div>
          <t-alert v-if="needsResume && !sessionLive" theme="warning" style="margin-top:12px"
            :message="resumeHint" />
          <div class="toolbar" style="margin-top:16px" v-if="needsResume && !sessionLive">
            <t-button theme="primary" @click="resumeAnalyze">继续分析</t-button>
            <t-button variant="outline" @click="$router.push(`/project/${pid}/overview`)">先进入作品阅读</t-button>
          </div>
          <div class="toolbar" style="margin-top:16px" v-else-if="phase==='analyzing'">
            <t-button variant="outline" @click="$router.push(`/project/${pid}/overview`)">先进入作品阅读</t-button>
            <span class="muted" style="margin-left:8px;font-size:12px">切页后从书架提示或顶部「导入分析」回到本页</span>
          </div>
          <div class="toolbar" style="margin-top:16px" v-if="phase==='done' && !needsResume">
            <t-button variant="outline" @click="$router.push(`/project/${pid}/plot`)">查看流程图</t-button>
            <t-button variant="outline" @click="$router.push(`/project/${pid}/overview`)">进入作品</t-button>
            <t-button v-if="plotPartial" variant="outline" :loading="deepAnalyzing" @click="analyzeDeep">
              深度补全全书
            </t-button>
            <div class="spacer"></div>
            <t-button theme="primary" @click="imitateOpen=true">一键仿写</t-button>
          </div>
          <div class="toolbar" style="margin-top:16px" v-else-if="err">
            <t-button variant="outline" @click="analyze">重试分析</t-button>
            <t-button variant="outline" @click="$router.push(`/project/${pid}/overview`)">先进入作品</t-button>
          </div>
        </t-card>
      </div>
    </div>

    <t-dialog
      v-model:visible="imitateOpen"
      :header="imitateUi.running ? '仿写进行中' : '一键仿写'"
      width="640px"
      :confirm-btn="imitateUi.running ? null : { content: '开始仿写', loading: imitating }"
      :cancel-btn="imitateUi.running ? { content: '收起（后台继续）' } : true"
      :close-on-overlay-click="!imitateUi.running"
      @confirm="doImitate"
    >
      <ImitateSetupPanel
        v-if="imitateUi.running"
        :running="imitateUi.running"
        :pct="imitateUi.pct"
        :status="imitateUi.status"
        :phase="imitateUi.phase"
        :err="imitateUi.err"
        :items="imitateItems"
      />
      <template v-else>
        <t-form label-width="88px">
          <t-form-item label="新书名">
            <t-input v-model="imitateForm.title" :placeholder="(preview.title || '本书') + '·仿写'" />
          </t-form-item>
          <t-form-item label="新故事创意" required>
            <t-textarea v-model="imitateForm.premise" placeholder="必填：你的原创故事核心（人物、冲突、背景）。只仿文风，不抄原书情节与人名。"
              :autosize="{minRows:3}" />
          </t-form-item>
          <t-form-item label="写作速度">
            <t-radio-group v-model="imitateForm.mode">
              <t-radio value="draft_only">快速（仅初稿，推荐仿写）</t-radio>
              <t-radio value="full">标准（初稿→审校→修订，更慢）</t-radio>
            </t-radio-group>
          </t-form-item>
        </t-form>
        <div class="muted">新建作品仅继承文风档案与章节数量；会自动生成原创角色，不复制原书人物/剧情/世界观。</div>
      </template>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import AgentTrace from '../components/AgentTrace.vue'
import PageTopbar from '../components/PageTopbar.vue'
import ImitateSetupPanel from '../components/ImitateSetupPanel.vue'
import { createAgentTrace } from '../agentTrace'
import { useImitateStream } from '../composables/useImitateStream'
import { saveLastSession } from '../composables/useSession'
import {
  runGenerationStreamTracked, subscribeGenerationSession, hydrateGenerationSnapshot,
  persistSessionSnapshot, isSessionActive, clearSessionSnapshotProvider,
  setSessionSnapshotProvider, wasSessionInterrupted, useActiveGenerationSessions,
} from '../composables/generationSession'

const route = useRoute()
const router = useRouter()
const phase = ref('upload')
const files = ref([])
const paste = ref('')
const filename = ref('')
const previewing = ref(false)
const committing = ref(false)
const preview = reactive({ title: '', words: 0, volume_count: 0, chapter_count: 0, volumes: [] })
const genre = ref('')
const pid = ref(0)
const trace = createAgentTrace()
const traceItems = trace.items
const analyzeStatus = ref('')
const analyzeStage = ref('')
const styleDone = ref(false)
const plotDone = ref(false)
const styleMsg = ref('')
const plotMsg = ref('')
const chapterDone = ref(0)
const plotPartial = ref(false)
const plotDeep = ref(0)
const plotLight = ref(0)
const deepAnalyzing = ref(false)
const needsResume = ref(false)
const importStatus = reactive({
  deep: 0, deep_done: 0, total: 0, pending: 0, deep_ratio: null,
  volume_total: 0, volume_index: 0, volume_title: '', stage_message: '', summarize_stage: '',
})
let progressPollTimer = null
const deepRatio = ref(10)
const DEEP_RATIO_SPEED = {
  10: '较快', 20: '较快', 30: '中等', 40: '中等', 50: '较慢',
  60: '慢', 70: '慢', 80: '很慢', 90: '很慢', 100: '极慢',
}
const deepRatioOptions = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100].map((v) => ({
  label: v === 100 ? `100%（全书 · ${DEEP_RATIO_SPEED[v]}）` : `${v}%（${DEEP_RATIO_SPEED[v]}）`,
  value: v,
}))

function formatDuration(mins) {
  if (mins < 60) return `约 ${mins} 分钟`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m ? `约 ${h} 小时 ${m} 分钟` : `约 ${h} 小时`
}
let unsubGen = null
const localAnalyzeStreaming = ref(false)
const activeSessions = useActiveGenerationSessions()

const sessionKey = computed(() => (pid.value ? `import:analyze:${pid.value}` : ''))

const sessionLive = computed(() => {
  const key = sessionKey.value
  if (!key) return false
  if (localAnalyzeStreaming.value) return true
  return activeSessions.value.some((s) => s.key === key)
})

const estimatedDeep = computed(() => {
  const n = preview.chapter_count || importStatus.total || 0
  if (!n) return 0
  if (deepRatio.value >= 100) return n
  return Math.max(1, Math.round(n * deepRatio.value / 100))
})

const deepRatioLabel = computed(() => {
  if (importStatus.deep_ratio != null) return `${importStatus.deep_ratio}%`
  if (deepRatio.value >= 100) return '100%'
  return `${deepRatio.value}%`
})

const timeEstimateHint = computed(() => {
  const n = estimatedDeep.value
  const total = preview.chapter_count || 0
  if (!n || !total) return '比例越高，深度解析的章节越多，总耗时越久。'
  const plotMins = Math.max(5, Math.round(n * 0.3))
  const dur = formatDuration(plotMins)
  const speed = DEEP_RATIO_SPEED[deepRatio.value] || ''
  if (deepRatio.value >= 100) {
    return `当前为全书深度解析（${n} 章），剧情分析 ${dur} 起，千章书可能需要数小时。建议挂机或夜间运行；若只想先阅读，可选 10%～20%。`
  }
  if (deepRatio.value >= 50) {
    return `当前 ${deepRatio.value}%（${speed}）：约 ${n} 章深度解析，剧情分析预计 ${dur}。比例再提高，耗时会继续显著增加。`
  }
  if (deepRatio.value >= 30) {
    return `当前 ${deepRatio.value}%（${speed}）：约 ${n} 章深度解析，剧情分析预计 ${dur}。比例越高耗时越久，10%～20% 适合千章书快速开读。`
  }
  return `当前 ${deepRatio.value}%（${speed}）：约 ${n} 章深度解析，剧情分析预计 ${dur}。比例越高耗时越久，可先低比例开读，之后用「深度补全全书」。`
})

const volumeSummary = reactive({ index: 0, total: 0, title: '' })

const showVolumeStageRow = computed(() => {
  const inVolume = analyzeStage.value === 'summarize'
    || volumeSummary.total > 0
    || importStatus.summarize_stage === 'running'
  if (!inVolume) return false
  return phase.value === 'analyzing' || (needsResume.value && importStatus.summarize_stage === 'running')
})

const volumeStageHint = computed(() => {
  if (importStatus.stage_message && !sessionLive.value) return importStatus.stage_message
  if (volumeSummary.total) {
    return `${volumeSummary.index}/${volumeSummary.total} 卷${volumeSummary.title ? ` · ${volumeSummary.title}` : ''}`
  }
  return importStatus.stage_message || '准备中…'
})

const resumeHint = computed(() => {
  const base = `上次分析未完成（关键章 ${importStatus.deep_done || 0}/${importStatus.deep || '?'}`
  const ratio = importStatus.deep_ratio != null ? `，比例 ${importStatus.deep_ratio}%` : ''
  const vol = importStatus.summarize_stage === 'running' && importStatus.volume_total
    ? `；卷级归纳 ${importStatus.volume_index || 0}/${importStatus.volume_total}`
    : ''
  return `${base}${ratio}${vol}），点击下方「继续分析」从断点续传。`
})

const analyzeTitle = computed(() => {
  if (analyzeStage.value === 'style') return '解析文风'
  if (analyzeStage.value === 'summarize') return '卷级归纳'
  if (analyzeStage.value === 'plot') return '拆解剧情'
  return '导入分析'
})

const traceStatusHint = computed(() => {
  if (analyzeStatus.value) return analyzeStatus.value
  if (phase.value !== 'analyzing') return ''
  if (analyzeStage.value === 'plot' || styleDone.value) return plotMsg.value
  return styleMsg.value
})
const styleProfile = ref({})
const err = ref('')
const imitateOpen = ref(false)
const imitating = ref(false)
const { ui: imitateUi, items: imitateItems, start: startImitate } = useImitateStream()
const imitateForm = reactive({ title: '', premise: '', mode: 'draft_only' })

function snip(s) {
  const t = (s || '').replace(/\s+/g, ' ').trim()
  return t.length > 48 ? t.slice(0, 48) + '…' : t
}

function resetUpload() {
  files.value = []
  phase.value = 'upload'
}

function applyPreview(data, name) {
  preview.title = data.title || name || '导入作品'
  preview.words = data.words || 0
  preview.volume_count = data.volume_count || 0
  preview.chapter_count = data.chapter_count || 0
  preview.volumes = data.volumes || []
  filename.value = name || filename.value
  phase.value = 'preview'
}

async function onFile(ctx) {
  const list = ctx?.files || ctx
  const f = (Array.isArray(list) ? list[0] : null)?.raw
  if (!f) return
  previewing.value = true
  try {
    const fd = new FormData()
    fd.append('file', f)
    const resp = await fetch('/api/import/preview-file', { method: 'POST', body: fd })
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.detail || '识别失败')
    applyPreview(data, f.name)
  } catch (e) {
    MessagePlugin.error(e.message)
  } finally {
    previewing.value = false
  }
}

async function previewPaste() {
  previewing.value = true
  try {
    const data = await api.post('/api/import/preview', { text: paste.value, filename: filename.value })
    applyPreview(data, filename.value)
  } catch (e) {
    MessagePlugin.error(e.message)
  } finally {
    previewing.value = false
  }
}

async function commitAndAnalyze() {
  if (!preview.title.trim()) return MessagePlugin.warning('请填写书名')
  committing.value = true
  try {
    const r = await api.post('/api/import/commit', {
      title: preview.title, genre: genre.value, filename: filename.value,
      volumes: preview.volumes,
    })
    pid.value = r.id
    MessagePlugin.success('已导入，开始分析')
    analyze()
  } catch (e) {
    MessagePlugin.error(e.message)
  } finally {
    committing.value = false
  }
}

function getStreamSnapshot() {
  return {
    items: traceItems.value.map((x) => ({ ...x })),
    phase: phase.value,
    styleDone: styleDone.value,
    plotDone: plotDone.value,
    styleMsg: styleMsg.value,
    plotMsg: plotMsg.value,
    analyzeStatus: analyzeStatus.value,
    analyzeStage: analyzeStage.value,
    chapterDone: chapterDone.value,
    plotPartial: plotPartial.value,
    plotDeep: plotDeep.value,
    plotLight: plotLight.value,
    deepRatio: deepRatio.value,
    styleProfile: { ...styleProfile.value },
    previewTitle: preview.title,
    err: err.value,
  }
}

function restoreStreamSnapshot(snap) {
  if (!snap) return
  if (snap.items?.length) traceItems.value = snap.items.map((x) => ({ ...x }))
  if (snap.phase != null) phase.value = snap.phase
  if (snap.styleDone != null) styleDone.value = snap.styleDone
  if (snap.plotDone != null) plotDone.value = snap.plotDone
  if (snap.styleMsg != null) styleMsg.value = snap.styleMsg
  if (snap.plotMsg != null) plotMsg.value = snap.plotMsg
  if (snap.analyzeStatus != null) analyzeStatus.value = snap.analyzeStatus
  if (snap.analyzeStage != null) analyzeStage.value = snap.analyzeStage
  if (snap.chapterDone != null) chapterDone.value = snap.chapterDone
  if (snap.plotPartial != null) plotPartial.value = snap.plotPartial
  if (snap.plotDeep != null) plotDeep.value = snap.plotDeep
  if (snap.plotLight != null) plotLight.value = snap.plotLight
  if (snap.deepRatio != null) deepRatio.value = snap.deepRatio
  if (snap.styleProfile) styleProfile.value = snap.styleProfile
  if (snap.previewTitle) preview.title = snap.previewTitle
  if (snap.err != null) err.value = snap.err
}

function applyImportProgress(st, { syncNeedsResume = true } = {}) {
  if (!st) return
  if (st.stage_message) {
    plotMsg.value = st.stage_message
    if (!sessionLive.value) analyzeStatus.value = st.stage_message
  }
  if (st.volume_total > 0 || st.summarize_stage === 'running') {
    analyzeStage.value = 'summarize'
    volumeSummary.total = st.volume_total || 0
    volumeSummary.index = st.volume_index || 0
    volumeSummary.title = st.volume_title || ''
  }
  if (st.deep_done != null) chapterDone.value = st.deep_done
  if (syncNeedsResume && st.needs_resume != null) needsResume.value = !!st.needs_resume
}

async function refreshImportStatus({ syncNeedsResume = true } = {}) {
  if (!pid.value) return null
  try {
    const st = await api.get(`/api/projects/${pid.value}/import/status`)
    Object.assign(importStatus, st)
    applyImportProgress(st, { syncNeedsResume: syncNeedsResume && !sessionLive.value })
    return st
  } catch {
    return null
  }
}

/** 断线后：用服务端进度覆盖本地快照里的旧文案（如「正在归纳各卷主线…」） */
function reconcileDisconnectedAnalyze({ warn = false } = {}) {
  if (sessionLive.value || !pid.value) return false
  const shouldResume = needsResume.value
    || importStatus.summarize_stage === 'running'
    || (importStatus.pending > 0)
  if (phase.value !== 'analyzing' && !shouldResume) return false
  stopProgressPoll()
  if (shouldResume) {
    needsResume.value = true
    plotDone.value = false
  }
  phase.value = 'done'
  applyImportProgress(importStatus)
  if (warn && shouldResume) {
    MessagePlugin.warning('分析连接已断开，请点击「继续分析」从断点续传')
  }
  return shouldResume
}

function startProgressPoll() {
  stopProgressPoll()
  progressPollTimer = setInterval(async () => {
    if (phase.value !== 'analyzing' || !pid.value) return
    try {
      const st = await api.get(`/api/projects/${pid.value}/import/status`)
      Object.assign(importStatus, st)
      applyImportProgress(st, { syncNeedsResume: !sessionLive.value })
      if (!sessionLive.value && st.needs_resume && phase.value === 'analyzing') {
        reconcileDisconnectedAnalyze({ warn: true })
      }
    } catch { /* ignore */ }
  }, 8000)
}

function stopProgressPoll() {
  if (progressPollTimer) {
    clearInterval(progressPollTimer)
    progressPollTimer = null
  }
}

async function loadProjectState(id) {
  const p = await api.get(`/api/projects/${id}`)
  pid.value = id
  preview.title = p.title || '导入作品'
  genre.value = p.genre || ''
  styleProfile.value = p.brief?.style_profile || {}
  styleDone.value = !!(p.brief?.style_profile || p.style)
  styleMsg.value = styleProfile.value.style_summary || (styleDone.value ? '已完成' : '')
  try {
    const st = await api.get(`/api/projects/${id}/import/status`)
    Object.assign(importStatus, st)
    applyImportProgress(st)
    plotDeep.value = st.deep || 0
    plotLight.value = Math.max(0, (st.total || 0) - (st.deep || 0))
    plotPartial.value = !!st.partial
    chapterDone.value = st.deep_done || 0
    if (st.deep_ratio != null) deepRatio.value = st.deep_ratio
    needsResume.value = !!st.needs_resume
    if (st.needs_resume) {
      if (st.summarize_stage === 'running' || (st.pending === 0 && st.deep_done >= st.deep)) {
        plotMsg.value = st.stage_message || `卷级归纳 ${st.volume_index || 0}/${st.volume_total || '?'}，可继续`
        analyzeStage.value = 'summarize'
      } else {
        plotMsg.value = `关键章 ${st.deep_done}/${st.deep}，可继续`
      }
      phase.value = 'done'
      plotDone.value = false
    } else if (['partial', 'done', 'full'].includes(st.status)) {
      phase.value = 'done'
      plotDone.value = true
      plotMsg.value = st.needs_deep
        ? `快速完成：深度 ${st.deep} 章`
        : `分析已完成（${st.total} 章）`
    }
  } catch {
    phase.value = styleDone.value ? 'done' : 'upload'
  }
}

function handleAnalyzeEvent(ev) {
  if (ev.type === '_end') return
  trace.handleEvent(ev, { showOutput: true })
  if (ev.type === 'phase') {
    if ((ev.phase || '').includes('文风')) analyzeStage.value = 'style'
    else if ((ev.phase || '').includes('归纳')) analyzeStage.value = 'summarize'
    else if ((ev.phase || '').includes('剧情')) analyzeStage.value = 'plot'
  } else if (ev.type === 'volume') {
    analyzeStage.value = 'summarize'
    if (ev.total != null) volumeSummary.total = ev.total
    if (ev.index != null) volumeSummary.index = ev.index
    if (ev.title) volumeSummary.title = ev.title
    const msg = ev.stage === 'done'
      ? `卷级归纳 ${ev.index}/${ev.total} 完成：${ev.title || ''}`
      : `卷级归纳 ${ev.index}/${ev.total}：${ev.title || ''}`
    plotMsg.value = msg
    analyzeStatus.value = msg
  } else if (ev.type === 'status') {
    analyzeStatus.value = ev.message || ''
    if (analyzeStage.value === 'style' || !styleDone.value) styleMsg.value = ev.message || ''
    else plotMsg.value = ev.message || ''
  } else if (ev.type === 'progress') {
    analyzeStatus.value = ev.hint || ev.message || analyzeStatus.value
  } else if (ev.type === 'style') {
    analyzeStage.value = 'style'
    styleDone.value = true
    styleProfile.value = ev.profile || {}
    styleMsg.value = ev.profile?.style_summary || '完成'
    analyzeStatus.value = '文风档案已写入'
  } else if (ev.type === 'chapter') {
    analyzeStage.value = 'plot'
    chapterDone.value += 1
    plotMsg.value = `已解析 ${chapterDone.value} 章 · ${ev.title || ''}`
    analyzeStatus.value = plotMsg.value
  } else if (ev.type === 'done') {
    volumeSummary.index = 0
    volumeSummary.total = 0
    volumeSummary.title = ''
    plotDone.value = true
    needsResume.value = false
    plotPartial.value = !!ev.partial
    plotDeep.value = ev.deep || 0
    plotLight.value = ev.light || 0
    if (ev.deep_ratio != null) {
      deepRatio.value = ev.deep_ratio
      importStatus.deep_ratio = ev.deep_ratio
    }
    const ratioHint = ev.deep_ratio != null ? `（${ev.deep_ratio}%）` : ''
    if (ev.partial) {
      plotMsg.value = `完成：深度 ${plotDeep.value} 章${ratioHint}，占位 ${plotLight.value} 章` +
        (ev.characters ? ` · ${ev.characters} 个角色` : '')
    } else {
      plotMsg.value = `完成 ${ev.chapters || 0} 章` + (ev.characters ? ` · ${ev.characters} 个角色` : '')
      plotPartial.value = false
    }
    analyzeStatus.value = plotMsg.value
    persistSessionSnapshot(sessionKey.value, getStreamSnapshot())
  } else if (ev.type === 'error') {
    err.value = ev.message
    trace.handleEvent(ev)
  }
}

function startAnalyze(url, body = {}, { onFinish, fresh = true } = {}) {
  if (!pid.value) return
  const key = sessionKey.value
  if (fresh && !isSessionActive(key)) {
    err.value = ''
    if (!body.resume) {
      styleDone.value = false
      chapterDone.value = 0
      trace.clear()
      trace.resetPinned()
    }
    plotDone.value = false
    plotPartial.value = false
    styleMsg.value = body.resume && styleDone.value ? styleMsg.value : '正在分析文风…'
    plotMsg.value = body.resume ? plotMsg.value : '等待文风阶段完成'
    analyzeStatus.value = ''
    analyzeStage.value = styleDone.value ? 'plot' : 'style'
  }
  phase.value = 'analyzing'
  needsResume.value = false
  startProgressPoll()
  saveLastSession({ route: `/import?pid=${pid.value}`, label: `导入分析·${preview.title}` })
  setSessionSnapshotProvider(key, getStreamSnapshot)
  localAnalyzeStreaming.value = true
  runGenerationStreamTracked(key, url, body, {
    onEvent: (ev) => {
      handleAnalyzeEvent(ev)
      persistSessionSnapshot(key, getStreamSnapshot())
    },
    onDone: async () => {
      localAnalyzeStreaming.value = false
      clearSessionSnapshotProvider(key)
      const st = await refreshImportStatus()
      stopProgressPoll()
      if (!err.value && st && !st.needs_resume) {
        phase.value = 'done'
        plotDone.value = true
        needsResume.value = false
        plotPartial.value = !!st.partial
        plotDeep.value = st.deep || plotDeep.value
        plotLight.value = Math.max(0, (st.total || 0) - (st.deep || 0))
        if (st.partial) {
          plotMsg.value = `完成：深度 ${st.deep} 章（${st.deep_ratio || deepRatio.value}%），占位 ${plotLight.value} 章`
        } else {
          plotMsg.value = `分析已完成（${st.total} 章）`
        }
        analyzeStatus.value = plotMsg.value
        MessagePlugin.success('导入分析已完成')
      } else if (st?.needs_resume) {
        needsResume.value = true
        plotDone.value = false
        phase.value = 'done'
      } else if (!err.value) {
        phase.value = 'done'
      }
      onFinish?.()
    },
    onError: async (e) => {
      localAnalyzeStreaming.value = false
      err.value = e.message
      needsResume.value = true
      trace.handleEvent({ type: 'error', message: e.message })
      clearSessionSnapshotProvider(key)
      await refreshImportStatus()
      stopProgressPoll()
      phase.value = 'done'
      plotDone.value = false
      onFinish?.()
    },
  })
}

function analyze() {
  startAnalyze(`/api/projects/${pid.value}/import/analyze`, { deep_ratio: deepRatio.value })
}

function resumeAnalyze() {
  startAnalyze(`/api/projects/${pid.value}/import/analyze`, { resume: true }, { fresh: false })
}

function analyzeDeep() {
  deepAnalyzing.value = true
  startAnalyze(`/api/projects/${pid.value}/import/analyze-deep`, {}, {
    onFinish: () => { deepAnalyzing.value = false },
    fresh: false,
  })
}

function doImitate() {
  if (imitating.value || imitateUi.running) return false
  if (!imitateForm.premise.trim()) {
    MessagePlugin.warning('请填写新故事创意，仿写只学文风，不会复制原书人物与情节')
    return false
  }
  imitating.value = true
  startImitate(
    pid.value,
    { title: imitateForm.title, premise: imitateForm.premise, mode: imitateForm.mode },
    {
      onDone: (r) => {
        imitating.value = false
        imitateOpen.value = false
        if (r.book && !r.book.ok) {
          MessagePlugin.warning(r.book.error || '仿写书已建，但未能自动开写')
        } else {
          MessagePlugin.success('仿写项目已就绪，已开始整本创作')
        }
        router.push(`/project/${r.id}/book`)
      },
      onError: (e) => {
        imitating.value = false
        MessagePlugin.error(e.message)
      },
    },
  )
  return false
}

onMounted(async () => {
  try {
    const cfg = await api.get('/api/config')
    if (!cfg.has_key) MessagePlugin.warning('尚未配置 API Key，拆章可用，文风/剧情分析需要 Key')
  } catch { /* ignore */ }

  const qpid = Number(route.query.pid)
  if (qpid > 0) {
    try {
      await loadProjectState(qpid)
      const key = sessionKey.value
      const serverNeedsResume = needsResume.value
      const saved = await hydrateGenerationSnapshot(key)
      if (saved?.snapshot) restoreStreamSnapshot(saved.snapshot)
      if (serverNeedsResume && !isSessionActive(key)) {
        phase.value = 'done'
        plotDone.value = false
        applyImportProgress(importStatus)
      }
      unsubGen = subscribeGenerationSession(key, {
        onRestore: restoreStreamSnapshot,
        onActive: (v) => { if (v) phase.value = 'analyzing' },
        onEvent: (ev) => { if (!localAnalyzeStreaming.value) handleAnalyzeEvent(ev) },
        onDone: () => {
          if (!localAnalyzeStreaming.value && !err.value) phase.value = 'done'
          else if (!localAnalyzeStreaming.value) reconcileDisconnectedAnalyze()
        },
        onError: (e) => {
          if (!localAnalyzeStreaming.value) {
            err.value = e.message
            needsResume.value = true
            reconcileDisconnectedAnalyze()
          }
        },
      })
      if (isSessionActive(key)) {
        phase.value = 'analyzing'
        startProgressPoll()
      } else if (reconcileDisconnectedAnalyze({ warn: true })) {
        /* toast inside */
      } else if (wasSessionInterrupted(key) || needsResume.value) {
        MessagePlugin.info('上次导入分析未完成，可点击「继续分析」')
      }
    } catch (e) {
      MessagePlugin.error('加载导入进度失败：' + e.message)
    }
  }
})

onUnmounted(() => {
  stopProgressPoll()
  trace.unbindScroll()
  if (sessionKey.value) {
    persistSessionSnapshot(sessionKey.value, getStreamSnapshot())
    clearSessionSnapshotProvider(sessionKey.value)
  }
  unsubGen?.()
})
</script>

<style scoped>
.import-page { min-height: 100vh; background: var(--td-bg-color-page); display: flex; flex-direction: column; }
.import-content { flex: 1; padding-top: 8px; }
.vol-block { margin-bottom: 14px; }
.vol-title { font-weight: 600; margin-bottom: 6px; }
.ch-row { display: flex; gap: 12px; align-items: baseline; padding: 4px 0; border-bottom: 1px dashed var(--td-component-stroke); }
.ch-title { min-width: 140px; }
.ch-snip { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.style-box {
  margin-top: 16px; padding: 12px 14px; border-radius: 8px;
  background: var(--td-bg-color-page); line-height: 1.7;
}
.style-h { font-weight: 600; margin-bottom: 6px; }
.err { color: var(--td-error-color); margin-top: 12px; }
.import-trace {
  margin-top: 12px;
  border: 1px solid var(--td-brand-color-light);
  border-radius: var(--td-radius-medium);
  background: var(--td-bg-color-container);
  overflow: hidden;
}
.import-trace-head {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px;
  background: var(--td-bg-color-secondarycontainer);
  border-bottom: 1px solid var(--td-component-stroke);
}
.import-trace-title { font-weight: 600; }
.import-trace-status { margin-left: auto; font-size: 12px; max-width: 55%; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.import-trace-body { max-height: 480px; overflow-y: auto; padding: 12px 14px; }
.trace-spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.import-drop :deep(.t-upload__dragger) {
  width: 100%;
  min-height: 168px;
}
.import-drop :deep(.t-upload__dragger-center) {
  width: 100%;
}
.import-drop :deep(.t-upload__dragger .t-upload__trigger) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  min-height: 144px;
}
.import-drop-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  pointer-events: none;
  text-align: center;
  line-height: 1.6;
}
.import-drop-highlight {
  color: var(--td-brand-color);
  font-weight: 600;
}
</style>
