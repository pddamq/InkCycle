<template>
  <div class="char-design page-full">
    <PageTopbar title="对话式角色设计" icon="chat-bubble"
      :back-to="`/project/${pid}/characters`" back-label="返回角色列表" sticky>
      <template #actions>
        <span v-if="covered.length || missing.length" class="muted topbar-meta">
          已覆盖 {{ covered.length }} · 待补 {{ missing.length }}
        </span>
        <ContextUsagePanel :usage="contextUsage" :loading="contextLoading" />
        <t-tag v-if="phase==='chat'" theme="primary" variant="light">第 {{ round }} 轮</t-tag>
        <t-tag v-else theme="success" variant="light">角色预览</t-tag>
      </template>
    </PageTopbar>

    <div v-if="phase==='chat'" class="chat-body char-body">
      <t-alert v-if="!hasKey" theme="warning" message="请先在「设置」配置 API Key。" />
      <t-alert v-else-if="loadError" theme="error" :message="loadError">
        <template #operation>
          <t-button size="small" variant="outline" @click="askNext">重试</t-button>
        </template>
      </t-alert>

      <template v-else>
        <div class="chat-panel">
          <div class="chat-scroll" ref="chatEl">
            <div v-if="!transcript.length && !thinking && !current.questions.length" class="chat-hint">
              像聊天一样回答角色设计师的问题，聊清楚主角、对手、关系网后再生成角色卡。
            </div>

            <div v-for="(m,i) in transcript" :key="i" :class="['chat-msg', m.role]">
              <div class="chat-msg-label">{{ m.role === 'user' ? '你' : '设计师' }}</div>
              <div class="chat-bubble">
                <div v-if="m.intro" class="chat-intro">{{ m.intro }}</div>
                <ol v-if="m.questions?.length" class="chat-qlist">
                  <li v-for="q in m.questions" :key="q.key"><b>{{ q.label }}</b>：{{ q.text }}</li>
                </ol>
                <div v-if="m.role==='user'" class="chat-utext">{{ m.text }}</div>
              </div>
            </div>

            <div v-if="thinking" class="chat-msg ai live">
              <div class="chat-msg-label">设计师</div>
              <div class="chat-bubble">
                <AgentTrace :items="traceItems" :live="thinking" />
              </div>
            </div>

            <div v-if="!thinking && current.questions.length" class="chat-msg ai current">
              <div class="chat-msg-label">设计师</div>
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
              <div class="chat-msg-label">设计师</div>
              <div class="chat-bubble composer">
                <p>{{ current.intro || '人物方向已经聊得差不多了，可以生成角色卡了。' }}</p>
                <div class="chat-ans-actions">
                  <t-button size="small" variant="outline" @click="forceAsk">再聊几轮</t-button>
                  <div class="spacer"></div>
                  <t-button theme="primary" size="small" :loading="compiling" @click="compile">
                    生成角色卡 <t-icon name="magic" />
                  </t-button>
                </div>
              </div>
            </div>
          </div>

          <div class="chat-foot">
            <t-button variant="outline" size="small" :loading="compiling" @click="compile">
              <t-icon name="magic" /> 信息够了，直接生成
            </t-button>
            <span class="muted chat-foot-tip">未聊透的维度，生成时会按蓝图合理补全</span>
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

    <div v-else class="cd-review">
      <t-alert theme="info" style="margin-bottom:16px"
        message="根据访谈生成的角色卡，可直接修改。确认后将写入本书（默认覆盖现有角色）。" />
      <div class="card-list">
        <t-card v-for="(c,i) in draftChars" :key="i" hover-shadow>
          <template #title>
            <t-input v-model="c.name" placeholder="姓名" style="max-width:160px" />
            <t-select v-model="c.role" filterable allow-input placeholder="定位" style="width:120px;margin-left:8px">
              <t-option v-for="r in roles" :key="r" :value="r" :label="r" />
            </t-select>
          </template>
          <t-form label-width="56px">
            <t-form-item v-for="f in profileFields" :key="f.key" :label="f.label">
              <t-textarea v-model="c.profile[f.key]" :autosize="{minRows:1,maxRows:3}" />
            </t-form-item>
          </t-form>
        </t-card>
      </div>
      <div class="review-actions">
        <t-checkbox v-model="replaceExisting">覆盖现有角色</t-checkbox>
        <t-button variant="outline" @click="backToChat"><t-icon name="chevron-left" /> 继续对话</t-button>
        <div class="spacer"></div>
        <t-button theme="primary" size="large" :loading="saving" @click="saveChars">
          <t-icon name="check" /> 确认并保存
        </t-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import AgentTrace from '../components/AgentTrace.vue'
import { createAgentTrace } from '../agentTrace'
import { useStreamSession } from '../composables/useStreamSession'
import { loadProjectDraft, saveProjectDraft, clearProjectDraft } from '../composables/useProjectDraft'
import ContextUsagePanel from '../components/ContextUsagePanel.vue'
import PageTopbar from '../components/PageTopbar.vue'
import { useContextEstimate } from '../composables/useContextEstimate'

const route = useRoute()
const router = useRouter()
const pid = route.params.pid

const phase = ref('chat')
const hasKey = ref(true)
const loadError = ref('')
const submitting = ref(false)
const saving = ref(false)
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
    draftChars: draftChars.value,
    replaceExisting: replaceExisting.value,
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
  if (snap.draftChars) draftChars.value = snap.draftChars.map(normalizeChar)
  if (snap.replaceExisting != null) replaceExisting.value = snap.replaceExisting
}

const sessKey = (mode) => `character-design:${pid}:${mode}`
const { busy: thinking, run: runNext } = useStreamSession(sessKey('next'), {
  trace, getStreamSnapshot: pageStreamSnapshot, restoreStreamSnapshot: restorePageStreamSnapshot,
})
const { busy: compiling, run: runCompile } = useStreamSession(sessKey('compile'), {
  trace, getStreamSnapshot: pageStreamSnapshot, restoreStreamSnapshot: restorePageStreamSnapshot,
})

const transcript = ref([])
const history = ref([])
const current = reactive({ phase: 'asking', intro: '', questions: [] })
const answers = reactive({})
const covered = ref([])
const missing = ref([])
const draftChars = ref([])
const replaceExisting = ref(true)

const { usage: contextUsage, loading: contextLoading, applyUsage: applyContextUsage } = useContextEstimate(
  () => ({
    feature: 'character_interview',
    project_id: Number(pid),
    history: history.value,
    compile: compiling.value,
  }),
  [history, () => compiling.value],
)

const roles = ['主角', '女主', '男主', '导师', '对手', '挚友', '反派', '配角']
const profileFields = [
  { key: 'appearance', label: '外貌' },
  { key: 'personality', label: '性格' },
  { key: 'goal', label: '目标' },
  { key: 'secret', label: '秘密' },
  { key: 'relationships', label: '关系' },
]

const DRAFT_NAME = 'character-design'

function snapshotDraft() {
  if (!history.value.length && phase.value !== 'review') return
  saveProjectDraft(pid, DRAFT_NAME, {
    phase: phase.value,
    round: round.value,
    history: history.value,
    transcript: transcript.value,
    current: { phase: current.phase, intro: current.intro, questions: [...current.questions] },
    covered: covered.value,
    missing: missing.value,
    draftChars: draftChars.value,
    replaceExisting: replaceExisting.value,
    traceItems: traceItems.value.map((x) => ({ ...x })),
  })
}

function applyDraft(d) {
  if (!d) return false
  phase.value = d.phase || 'chat'
  round.value = d.round || 0
  history.value = d.history || []
  transcript.value = d.transcript || []
  current.phase = d.current?.phase || 'asking'
  current.intro = d.current?.intro || ''
  current.questions = d.current?.questions || []
  covered.value = d.covered || []
  missing.value = d.missing || []
  draftChars.value = (d.draftChars || []).map(normalizeChar)
  replaceExisting.value = d.replaceExisting !== false
  if (d.traceItems?.length) traceItems.value = d.traceItems.map((x) => ({ ...x }))
  return history.value.length > 0 || phase.value === 'review'
}

function normalizeChar(c) {
  const profile = { ...(c.profile || {}) }
  profileFields.forEach((f) => {
    if (c[f.key] && !profile[f.key]) profile[f.key] = c[f.key]
  })
  return { name: c.name || '', role: c.role || '', profile }
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
  runNext(
    `/api/projects/${pid}/characters/interview/next`,
    { history: history.value },
    {
      onEvent(ev) {
        if (ev.type === 'context_usage') applyContextUsage(ev)
        else if (ev.type === 'character_interview') applyInterview(ev)
        else if (ev.type === 'error') {
          loadError.value = ev.message || '出错了'
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
    },
  )
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
  history.value.push({ role: 'user', content: '（请再就还没聊透的角色维度追问我几轮）' })
  current.phase = 'asking'
  askNext()
}

function compile() {
  snapshotDraft()
  clearTrace()
  runCompile(
    `/api/projects/${pid}/characters/interview/compile`,
    { history: history.value },
    {
      onEvent(ev) {
        if (ev.type === 'context_usage') applyContextUsage(ev)
        else if (ev.type === 'characters') {
          if (!ev.ok) {
            MessagePlugin.error(ev.error || '生成失败')
            snapshotDraft()
            return
          }
          draftChars.value = (ev.characters || []).map(normalizeChar)
          phase.value = 'review'
          snapshotDraft()
        } else if (ev.type === 'error') {
          MessagePlugin.error(ev.message || '生成失败')
          snapshotDraft()
        }
      },
      onDone: () => snapshotDraft(),
      onError(e) {
        MessagePlugin.error(e.message)
        snapshotDraft()
      },
    },
  )
}

function backToChat() {
  phase.value = 'chat'
  snapshotDraft()
}

async function saveChars() {
  if (!draftChars.value.length) return MessagePlugin.warning('没有可保存的角色')
  if (!draftChars.value.every(c => c.name?.trim())) return MessagePlugin.warning('请填写所有角色姓名')
  saving.value = true
  try {
    const r = await api.post(`/api/projects/${pid}/characters/interview/save`, {
      characters: draftChars.value,
      replace: replaceExisting.value,
      history: history.value,
    })
    await clearProjectDraft(pid, DRAFT_NAME)
    MessagePlugin.success(`已保存 ${r.count} 个角色`)
    router.push(`/project/${pid}/characters`)
  } catch (e) {
    MessagePlugin.error(e.message)
  } finally {
    saving.value = false
  }
}

async function init() {
  try {
    const cfg = await api.get('/api/config')
    hasKey.value = !!cfg.has_key
  } catch { hasKey.value = false }
  const draft = await loadProjectDraft(pid, DRAFT_NAME)
  if (applyDraft(draft)) {
    MessagePlugin.info(phase.value === 'review' ? '已恢复角色预览，可继续编辑或保存' : '已恢复角色设计对话，可继续')
    scroll(true)
    return
  }
  if (!thinking.value) askNext()
}

watch(answers, () => { scroll(); snapshotDraft() }, { deep: true })

onMounted(() => { bindScroll(); init() })
onBeforeUnmount(() => {
  snapshotDraft()
  unbindScroll()
})
</script>

<style scoped>
.char-design { min-height: calc(100vh - 48px); margin: -12px -8px 0; }
.char-body { flex: 1; min-height: 0; }
.char-body > .t-alert { margin: 0 18px; flex-shrink: 0; }
.topbar-meta { font-size: 12px; white-space: nowrap; }
.cd-review { flex: 1; overflow-y: auto; padding: 16px 20px 32px; }
.review-actions { display: flex; align-items: center; gap: 12px; padding: 16px 0 24px; flex-wrap: wrap; }
.card-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
</style>
