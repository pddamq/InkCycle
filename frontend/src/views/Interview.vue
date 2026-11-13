<template>
  <div class="chat-shell">
    <PageTopbar title="开书访谈" icon="chat-bubble" back-to="/" back-label="返回书架">
      <template #actions>
        <span v-if="covered.length || missing.length" class="muted topbar-meta">
          已覆盖 {{ covered.length }} · 待补 {{ missing.length }}
        </span>
        <t-select v-if="phase==='interviewing'" v-model="templateId" placeholder="访谈模板" clearable
          style="width:160px" size="small" @change="applyTemplate">
          <t-option v-for="t in templates" :key="t.id" :value="t.id" :label="t.name" />
        </t-select>
        <ContextUsagePanel :usage="contextUsage" :loading="contextLoading" />
        <t-tag v-if="phase==='interviewing'" theme="primary" variant="light">第 {{ round }} 轮</t-tag>
        <t-tag v-else-if="phase==='review'" theme="success" variant="light">蓝图已生成</t-tag>
        <t-button v-if="hasDraftSaved" size="small" variant="text" @click="confirmRestart">重新开始</t-button>
      </template>
    </PageTopbar>

    <div v-if="phase==='interviewing'" class="chat-body">
      <t-alert v-if="!hasKey" theme="warning" :message="'尚未配置 API Key，请先到「设置」填入。'" />
      <t-alert v-else-if="loadError" theme="error" :message="loadError">
        <template #operation>
          <t-button size="small" variant="outline" @click="askNext">重试</t-button>
        </template>
      </t-alert>

      <template v-else>
        <!-- 主对话区：历史 + 进行中 Agent + 当前作答，全在一个滚动容器里 -->
        <div class="chat-panel">
          <div class="chat-scroll" ref="chatEl">
            <div v-if="!transcript.length && !thinking && !current.questions.length" class="chat-hint">
              像聊天一样回答编辑的问题即可，Agent 会在后台思考并调用工具。
            </div>

            <div v-for="(m,i) in transcript" :key="i" :class="['chat-msg', m.role]">
              <div class="chat-msg-label">{{ m.role === 'user' ? '你' : '编辑' }}</div>
              <div class="chat-bubble">
                <div v-if="m.intro" class="chat-intro">{{ m.intro }}</div>
                <ol v-if="m.questions?.length" class="chat-qlist">
                  <li v-for="q in m.questions" :key="q.key"><b>{{ q.label }}</b>：{{ q.text }}</li>
                </ol>
                <div v-if="m.role==='user'" class="chat-utext">{{ m.text }}</div>
              </div>
            </div>

            <div v-if="thinking" class="chat-msg ai live">
              <div class="chat-msg-label">编辑</div>
              <div class="chat-bubble">
                <AgentTrace :items="traceItems" :live="thinking" />
              </div>
            </div>

            <div v-if="!thinking && current.questions.length" class="chat-msg ai current">
              <div class="chat-msg-label">编辑</div>
              <div class="chat-bubble composer">
                <div v-if="current.intro" class="chat-intro">{{ current.intro }}</div>
                <div v-for="q in current.questions" :key="q.key" class="chat-ans-row">
                  <div class="chat-ans-label">{{ q.label }}</div>
                  <div class="chat-q-hint muted">{{ q.text }}</div>
                  <t-textarea v-model="answers[q.key]" placeholder="你的回答…" :autosize="{minRows:1,maxRows:3}" />
                </div>
                <div class="chat-ans-actions">
                  <t-button size="small" variant="text" @click="skipTurn">这些你帮我定</t-button>
                  <div class="spacer"></div>
                  <t-button theme="primary" size="small" :loading="submitting" @click="submitAnswers">
                    提交回答 <t-icon name="arrow-right" />
                  </t-button>
                </div>
              </div>
            </div>

            <div v-else-if="!thinking && current.phase==='ready'" class="chat-msg ai current">
              <div class="chat-msg-label">编辑</div>
              <div class="chat-bubble composer">
                <t-alert v-if="compileInterrupted" theme="warning" style="margin-bottom:10px"
                  message="上次生成蓝图时被中断，点击下方按钮继续生成。" />
                <p>{{ current.intro || '信息已经足够，可以生成创作蓝图了。' }}</p>
                <div class="chat-ans-actions">
                  <t-button size="small" variant="outline" @click="forceAsk">再问我几轮</t-button>
                  <div class="spacer"></div>
                  <t-button theme="primary" size="small" :loading="compiling" @click="compile">
                    {{ compileInterrupted ? '继续生成蓝图' : '生成创作蓝图' }} <t-icon name="magic" />
                  </t-button>
                </div>
              </div>
            </div>
          </div>

          <div class="chat-foot">
            <t-button variant="outline" size="small" :loading="compiling" @click="compile">
              <t-icon name="magic" /> 信息够了，直接生成蓝图
            </t-button>
            <span class="muted chat-foot-tip">没答完的维度，编辑会在蓝图里合理补全</span>
          </div>
        </div>

        <aside class="side-panel">
          <details open>
            <summary class="side-summary">维度进度</summary>
            <div class="side-sec">
              <div class="side-h">已覆盖</div>
              <div class="tag-row">
                <t-tag v-for="d in covered" :key="d" size="small" theme="success" variant="light">{{ d }}</t-tag>
                <span v-if="!covered.length" class="muted">—</span>
              </div>
            </div>
            <div class="side-sec">
              <div class="side-h">待补充</div>
              <div class="tag-row">
                <t-tag v-for="d in missing" :key="d" size="small" theme="warning" variant="light">{{ d }}</t-tag>
                <span v-if="!missing.length" class="muted">—</span>
              </div>
            </div>
          </details>
        </aside>
      </template>
    </div>

    <div v-else-if="phase==='review'" class="iv-review">
      <t-alert theme="info" style="margin-bottom:16px"
        message="下面是根据你的访谈汇编的创作蓝图，可直接修改。确认后将据此创建作品，并自动生成世界观、角色与大纲。" />
      <div v-for="grp in briefGroups" :key="grp.title" class="brief-group">
        <h3 class="bg-title">{{ grp.title }}</h3>
        <div class="bg-fields">
          <div v-for="f in grp.fields" :key="f.key" class="bf" :class="{ wide: f.wide }">
            <label class="bf-label">{{ f.label }}</label>
            <t-input v-if="f.type==='input'" v-model="brief[f.key]" :placeholder="f.ph" />
            <t-input-number v-else-if="f.type==='number'" v-model="brief[f.key]" :min="f.min" :step="f.step" theme="column" />
            <t-textarea v-else v-model="brief[f.key]" :placeholder="f.ph" :autosize="{minRows:1,maxRows:4}" />
          </div>
        </div>
      </div>
      <div class="review-actions">
        <t-button variant="outline" @click="backToInterview"><t-icon name="chevron-left" /> 回到访谈</t-button>
        <div class="spacer"></div>
        <t-button theme="primary" size="large" :loading="creating" @click="createProject">
          <t-icon name="check" /> 确认蓝图，创建作品并开始生成
        </t-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import AgentTrace from '../components/AgentTrace.vue'
import { createAgentTrace } from '../agentTrace'
import { saveLastSession } from '../composables/useSession'
import { useStreamSession } from '../composables/useStreamSession'
import {
  loadInterviewDraft, saveInterviewDraft, discardInterviewDraft, draftHint,
} from '../composables/useInterviewDraft'
import ContextUsagePanel from '../components/ContextUsagePanel.vue'
import PageTopbar from '../components/PageTopbar.vue'
import { useContextEstimate } from '../composables/useContextEstimate'

const router = useRouter()
const templates = ref([])
const templateId = ref(null)
const phase = ref('interviewing')
const hasKey = ref(true)
const loadError = ref('')
const submitting = ref(false)
const creating = ref(false)
const round = ref(0)
const chatEl = ref(null)
const trace = createAgentTrace(chatEl)
const {
  items: traceItems, handleEvent: traceEvent, clear: clearTrace,
  scroll, resetPinned, bindScroll, unbindScroll,
} = trace

function pageStreamSnapshot() {
  return {
    phase: phase.value,
    round: round.value,
    transcript: transcript.value,
    history: history.value,
    current: { phase: current.phase, intro: current.intro, questions: [...current.questions] },
    covered: covered.value,
    missing: missing.value,
    brief: { ...brief.value },
    compileInterrupted: compileInterrupted.value,
    historyNotes: historyNotes.value,
    historyThroughIndex: historyThroughIndex.value,
  }
}

function restorePageStreamSnapshot(snap) {
  if (!snap) return
  if (snap.phase != null) phase.value = snap.phase
  if (snap.round != null) round.value = snap.round
  if (snap.transcript) transcript.value = snap.transcript
  if (snap.history) history.value = snap.history
  if (snap.current) {
    current.phase = snap.current.phase || 'asking'
    current.intro = snap.current.intro || ''
    current.questions = snap.current.questions || []
  }
  if (snap.covered) covered.value = snap.covered
  if (snap.missing) missing.value = snap.missing
  if (snap.brief) brief.value = snap.brief
  if (snap.compileInterrupted != null) compileInterrupted.value = snap.compileInterrupted
  if (snap.historyNotes != null) historyNotes.value = snap.historyNotes
  if (snap.historyThroughIndex != null) historyThroughIndex.value = snap.historyThroughIndex
}

const { busy: thinking, run: runNext } = useStreamSession('interview:next', {
  trace, getStreamSnapshot: pageStreamSnapshot, restoreStreamSnapshot: restorePageStreamSnapshot,
})
const { busy: compiling, run: runCompile } = useStreamSession('interview:compile', {
  trace, getStreamSnapshot: pageStreamSnapshot, restoreStreamSnapshot: restorePageStreamSnapshot,
})

const transcript = ref([])
const history = ref([])
const current = reactive({ phase: 'asking', intro: '', questions: [] })
const answers = reactive({})
const covered = ref([])
const missing = ref([])
const brief = ref({})
const hasDraftSaved = ref(false)
const compileInterrupted = ref(false)
const historyNotes = ref('')
const historyThroughIndex = ref(0)

const { usage: contextUsage, loading: contextLoading, applyUsage: applyContextUsage } = useContextEstimate(
  () => ({
    feature: 'interview',
    history: history.value,
    history_notes: historyNotes.value,
    history_through_index: historyThroughIndex.value,
    compile: current.phase === 'ready' && compiling.value,
  }),
  [history, historyNotes, historyThroughIndex, () => current.phase],
)

function interviewBody() {
  return {
    history: history.value,
    history_notes: historyNotes.value,
    history_through_index: historyThroughIndex.value,
  }
}

function applyHistoryNotes(ev) {
  if (ev.type !== 'history_notes') return
  if (ev.notes != null) historyNotes.value = ev.notes
  if (ev.through_index != null) historyThroughIndex.value = ev.through_index
}

function snapshotDraft(extra = {}) {
  if (!history.value.length && phase.value !== 'review') return
  const data = {
    phase: phase.value,
    round: round.value,
    history: history.value,
    transcript: transcript.value,
    current: { phase: current.phase, intro: current.intro, questions: [...current.questions] },
    covered: covered.value,
    missing: missing.value,
    brief: { ...brief.value },
    answers: { ...answers },
    compileInterrupted: compileInterrupted.value,
    historyNotes: historyNotes.value,
    historyThroughIndex: historyThroughIndex.value,
    traceItems: traceItems.value.map((x) => ({ ...x })),
    ...extra,
  }
  saveInterviewDraft(data)
  hasDraftSaved.value = true
}

function restoreDraft(draft) {
  phase.value = draft.phase || 'interviewing'
  round.value = draft.round || 0
  history.value = draft.history || []
  transcript.value = draft.transcript || []
  current.phase = draft.current?.phase || 'asking'
  current.intro = draft.current?.intro || ''
  current.questions = draft.current?.questions || []
  covered.value = draft.covered || []
  missing.value = draft.missing || []
  brief.value = draft.brief || {}
  compileInterrupted.value = !!draft.compileInterrupted
  historyNotes.value = draft.historyNotes || ''
  historyThroughIndex.value = draft.historyThroughIndex || 0
  Object.keys(answers).forEach((k) => delete answers[k])
  Object.assign(answers, draft.answers || {})
  if (draft.traceItems?.length) traceItems.value = draft.traceItems.map((x) => ({ ...x }))
}

function snapshotAiToHistory(intro, questions) {
  const aiText = [intro, ...questions.map(q => `${q.label}：${q.text}`)].filter(Boolean).join('\n')
  if (!aiText) return
  const last = history.value[history.value.length - 1]
  if (last?.role === 'user') {
    history.value.push({ role: 'ai', content: aiText })
    return
  }
  if (last?.role === 'ai') {
    last.content = aiText
    return
  }
  history.value.push({ role: 'ai', content: aiText })
}

function applyInterview(r) {
  current.phase = r.phase
  current.intro = r.intro || ''
  current.questions = r.questions || []
  covered.value = r.covered || []
  missing.value = r.missing || []
  snapshotAiToHistory(r.intro, current.questions)
  compileInterrupted.value = false
  snapshotDraft()
  scroll()
}

function commitUserReply(text) {
  transcript.value.push({
    role: 'ai',
    intro: current.intro,
    questions: current.questions.map(q => ({ ...q })),
  })
  transcript.value.push({ role: 'user', text })
  history.value.push({ role: 'user', content: text })
  current.intro = ''
  current.questions = []
  Object.keys(answers).forEach(k => delete answers[k])
  snapshotDraft()
}

function askNext() {
  loadError.value = ''
  clearTrace()
  resetPinned()
  runNext('/api/interview/next', interviewBody(), {
    onEvent(ev) {
      applyHistoryNotes(ev)
      if (ev.type === 'context_usage') applyContextUsage(ev)
      else if (ev.type === 'interview') applyInterview(ev)
      else if (ev.type === 'error') {
        loadError.value = ev.message || '访谈出错'
        traceEvent(ev)
      }
      scroll()
    },
    onDone: () => { snapshotDraft(); scroll() },
    onError(e) {
      loadError.value = e.message
      MessagePlugin.error(e.message)
      snapshotDraft()
    },
  })
}

async function loadTemplates() {
  try {
    const r = await api.get('/api/interview/templates')
    templates.value = r.templates || []
  } catch { /* ignore */ }
}

function applyTemplate(id) {
  const t = templates.value.find((x) => x.id === id)
  if (!t) return
  if (round.value > 0 || transcript.value.length) {
    MessagePlugin.warning('访谈已开始，模板仅可在首轮前应用')
    templateId.value = null
    return
  }
  history.value = (t.seed_history || []).map((h) => ({ role: h.role, content: h.content }))
  if (t.blueprint && Object.keys(t.blueprint).length) {
    brief.value = { ...t.blueprint, ...brief.value }
  }
  MessagePlugin.info(`已应用模板「${t.name}」`)
}

function updateSessionLabel() {
  let label = '开书访谈'
  if (phase.value === 'review') label = '编辑创作蓝图'
  else if (current.phase === 'ready') label = '生成创作蓝图'
  else if (round.value) label = `开书访谈 · 第${round.value}轮`
  saveLastSession({ route: '/new', label })
}

async function initInterview() {
  try {
    const cfg = await api.get('/api/config')
    hasKey.value = !!cfg.has_key
    if (!hasKey.value) {
      loadError.value = '请先在「设置」中配置 API Key'
      return
    }
    const draft = await loadInterviewDraft()
    if (draft?.history?.length || draft?.phase === 'review') {
      restoreDraft(draft)
      hasDraftSaved.value = true
      updateSessionLabel()
      MessagePlugin.info(draftHint(draft))
      scroll(true)
      return
    }
    await startFresh(false)
  } catch (e) {
    loadError.value = e.message
    MessagePlugin.error(e.message)
  }
}

async function startInterview() {
  await initInterview()
}

async function startFresh(prompt = true) {
  if (prompt && (history.value.length || phase.value === 'review')) {
    const ok = window.confirm('确定重新开始？当前访谈进度将被清除。')
    if (!ok) return
  }
  await discardInterviewDraft()
  hasDraftSaved.value = false
  compileInterrupted.value = false
  phase.value = 'interviewing'
  round.value = 0
  transcript.value = []
  history.value = []
  historyNotes.value = ''
  historyThroughIndex.value = 0
  current.phase = 'asking'
  current.intro = ''
  current.questions = []
  covered.value = []
  missing.value = []
  brief.value = {}
  Object.keys(answers).forEach((k) => delete answers[k])
  loadError.value = ''
  updateSessionLabel()
  await askNext()
}

function confirmRestart() {
  startFresh(true)
}

function backToInterview() {
  phase.value = 'interviewing'
  snapshotDraft()
}

async function submitAnswers() {
  const qs = current.questions
  if (!qs.length) return
  submitting.value = true
  const parts = qs.map(q => `${q.label}：${(answers[q.key] || '').trim() || '（略，你帮我定）'}`)
  commitUserReply(parts.join('\n'))
  round.value++
  scroll(true)
  submitting.value = false
  await askNext()
}

function skipTurn() {
  const qs = current.questions
  if (!qs.length) return
  commitUserReply(qs.map(q => `${q.label}：你帮我定`).join('\n'))
  round.value++
  scroll(true)
  askNext()
}

function forceAsk() {
  history.value.push({ role: 'user', content: '（请再就还没聊透的关键维度追问我几轮）' })
  current.phase = 'asking'
  askNext()
}

function compile() {
  compileInterrupted.value = true
  snapshotDraft()
  clearTrace()
  runCompile('/api/interview/compile', interviewBody(), {
    onEvent(ev) {
      applyHistoryNotes(ev)
      if (ev.type === 'context_usage') applyContextUsage(ev)
      else if (ev.type === 'compile') {
        if (!ev.ok) {
          MessagePlugin.error(ev.error || '蓝图生成失败')
          snapshotDraft()
          return
        }
        brief.value = ev.brief || {}
        brief.value.target_words = Number(brief.value.target_words) || 200000
        brief.value.chapter_words = Number(brief.value.chapter_words) || 2500
        phase.value = 'review'
        compileInterrupted.value = false
        snapshotDraft()
        updateSessionLabel()
        window.scrollTo(0, 0)
      } else if (ev.type === 'error') {
        MessagePlugin.error(ev.message || '蓝图生成失败')
        snapshotDraft()
      }
    },
    onDone: () => { if (phase.value !== 'review') snapshotDraft() },
    onError(e) {
      MessagePlugin.error(e.message)
      snapshotDraft()
    },
  })
}

async function createProject() {
  if (!brief.value.title?.trim()) { MessagePlugin.warning('请给作品起个书名'); return }
  creating.value = true
  try {
    const r = await api.post('/api/projects', {
      title: brief.value.title, genre: brief.value.genre || '',
      premise: brief.value.logline || '', style: brief.value.style || '',
      target_words: brief.value.target_words || 200000,
      brief: brief.value,
      interview_history: history.value,
      interview_transcript: transcript.value,
    })
    await discardInterviewDraft()
    hasDraftSaved.value = false
    MessagePlugin.success('作品已创建，开始生成设定/角色/大纲')
    router.push(`/wizard/${r.id}`)
  } catch (e) {
    MessagePlugin.error(e.message)
  } finally {
    creating.value = false
  }
}

const briefGroups = [
  { title: '核心定位', fields: [
    { key: 'title', label: '书名', type: 'input', ph: '作品名' },
    { key: 'genre', label: '类型', type: 'input', ph: '如 玄幻' },
    { key: 'subgenre', label: '子类型/流派', type: 'input', ph: '如 悬疑流' },
    { key: 'logline', label: '一句话创意', type: 'textarea', wide: true, ph: '谁、想要什么、遇到什么阻碍' },
    { key: 'theme', label: '主题内核', type: 'textarea', wide: true, ph: '想表达什么' },
    { key: 'audience', label: '目标读者', type: 'input', ph: '男频/女频/全龄' },
    { key: 'tone', label: '基调', type: 'input', ph: '爽文/文学向/轻松/沉重' },
  ]},
  { title: '故事世界', fields: [
    { key: 'era_setting', label: '时代背景', type: 'textarea', wide: true },
    { key: 'world_rules', label: '世界规则/力量体系', type: 'textarea', wide: true },
    { key: 'main_scenes', label: '主要场景', type: 'textarea', wide: true },
    { key: 'factions', label: '势力/社会结构', type: 'textarea', wide: true },
  ]},
  { title: '人物', fields: [
    { key: 'protagonist', label: '主角', type: 'textarea', wide: true },
    { key: 'antagonist', label: '对手/反派', type: 'textarea', wide: true },
    { key: 'supporting', label: '配角与感情线', type: 'textarea', wide: true },
    { key: 'relationships', label: '人物关系张力', type: 'textarea', wide: true },
  ]},
  { title: '情节', fields: [
    { key: 'core_conflict', label: '核心冲突', type: 'textarea', wide: true },
    { key: 'opening_hook', label: '开篇钩子', type: 'textarea', wide: true },
    { key: 'plot_direction', label: '主要走向/转折', type: 'textarea', wide: true },
    { key: 'ending', label: '结局类型', type: 'textarea', wide: true },
    { key: 'emotional_beats', label: '情绪与爽点节奏', type: 'textarea', wide: true },
  ]},
  { title: '风格与形式', fields: [
    { key: 'pov', label: '视角人称', type: 'input' },
    { key: 'style', label: '文风语言', type: 'textarea', wide: true },
    { key: 'pacing', label: '节奏', type: 'input' },
    { key: 'chapter_words', label: '单章字数', type: 'number', min: 500, step: 100 },
    { key: 'target_words', label: '目标总字数', type: 'number', min: 10000, step: 10000 },
  ]},
  { title: '边界与偏好', fields: [
    { key: 'taboos', label: '禁忌/雷点', type: 'textarea', wide: true },
    { key: 'must_have', label: '必须包含', type: 'textarea', wide: true },
    { key: 'references', label: '对标作品', type: 'textarea', wide: true },
    { key: 'extra', label: '其他补充', type: 'textarea', wide: true },
  ]},
]

watch(answers, () => { scroll(); snapshotDraft() }, { deep: true })
watch(brief, () => snapshotDraft(), { deep: true })

onMounted(() => {
  bindScroll()
  loadTemplates()
  initInterview()
})
onBeforeUnmount(() => {
  if (compiling.value) snapshotDraft({ compileInterrupted: true })
  else snapshotDraft()
  unbindScroll()
})
</script>

<style scoped>
.topbar-meta { font-size: 12px; white-space: nowrap; }
.chat-body > .t-alert { margin: 0 18px; flex-shrink: 0; }
.iv-review {
  flex: 1; overflow-y: auto; padding: 20px 24px 40px;
  max-width: 1000px; margin: 0 auto; width: 100%;
}
.brief-group {
  background: var(--td-bg-color-container);
  border: 1px solid var(--td-component-stroke);
  border-radius: var(--app-radius-md);
  padding: 18px 20px; margin-bottom: 16px;
  box-shadow: var(--app-shadow-sm);
}
.bg-title { font-size: 15px; font-weight: 600; margin: 0 0 14px; color: var(--td-brand-color); }
.bg-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.bf.wide { grid-column: 1 / -1; }
.bf-label { display: block; font-size: 12px; color: var(--td-text-color-secondary); margin-bottom: 6px; }
.review-actions { display: flex; align-items: center; gap: 12px; padding: 8px 0 24px; }
.resume-actions { display: flex; gap: 12px; margin-top: 16px; justify-content: flex-end; }
.resume-time { font-size: 12px; margin-top: 8px; }
</style>
