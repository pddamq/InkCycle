<template>
  <div class="agent-chat">
    <div class="chat-header">
      <t-icon name="chat" class="chat-header-icon" />
      <span class="chat-header-title">写作助手</span>
      <div class="spacer"></div>
      <ContextUsagePanel :usage="contextUsage" :loading="contextLoading" />
    </div>
    <div class="chat-messages" ref="scrollEl">
      <div v-if="!messages.length" class="chat-welcome muted">
        像 Cursor 一样对话写作。输入 <code>@</code> 引用设定/角色/章节/伏笔；Agent 不确定时会弹窗问你。
      </div>
      <div v-for="msg in messages" :key="msg.id" :class="['chat-msg', msg.role === 'user' ? 'user' : 'ai']">
        <div class="chat-msg-label">{{ msg.role === 'user' ? '你' : 'Agent' }}</div>
        <div class="chat-bubble">
          <div v-if="msg.role === 'user'" class="chat-utext">{{ msg.content }}</div>
          <template v-else>
            <AgentTrace v-if="msg.trace?.length" :items="msg.trace" empty-text="" :live="false" />
            <div v-if="msg.readerReview" class="reader-box">
              <div class="reader-head">
                <t-tag size="small" theme="primary" variant="light">{{ msg.readerReview.persona }}</t-tag>
                <span>弃书风险：{{ msg.readerReview.report?.drop_risk || '—' }}</span>
                <span>追读欲：{{ msg.readerReview.report?.hook_score ?? '—' }}</span>
              </div>
              <p>{{ msg.readerReview.report?.summary }}</p>
            </div>
            <div v-if="msg.diff" class="diff-hint" @click="$emit('show-diff', msg.diff)">
              <t-icon name="file-code" /> 正文变更 +{{ msg.diff.added }} / −{{ msg.diff.removed }} 行
              <span class="link">查看 Diff</span>
            </div>
            <div v-if="msg.content" class="assistant-text">{{ msg.content }}</div>
          </template>
        </div>
      </div>

      <div v-if="busy" class="chat-msg ai live">
        <div class="chat-msg-label">Agent</div>
        <div class="chat-bubble">
          <AgentTrace :items="liveTrace" :live="busy" />
          <div v-if="liveWriting" class="writing-preview streaming">
            <div class="stream-label">正在写入正文…</div>
            <pre>{{ liveWriting.slice(-800) }}</pre>
          </div>
        </div>
      </div>
    </div>

    <div v-if="pickedRefs.length" class="ref-tags">
      <t-tag v-for="(r,i) in pickedRefs" :key="i" size="small" closable @close="pickedRefs.splice(i,1)">
        @{{ r.label }}
      </t-tag>
    </div>

    <div class="chat-chips">
      <t-tag v-for="c in chips" :key="c.label" size="small" variant="outline"
        class="chip" :class="{ disabled: busy }" @click="useChip(c)">{{ c.label }}</t-tag>
      <t-tag size="small" variant="outline" class="chip" :class="{ disabled: busy }" @click="readerReview">读者审校</t-tag>
      <t-tag size="small" variant="outline" class="chip" :class="{ disabled: busy }" @click="$emit('auto')">自动全流程</t-tag>
    </div>

    <div class="chat-input-wrap">
      <MentionPicker :visible="mentionOpen" :items="mentionItems" :idx="mentionIdx" @pick="onMentionPick" />
      <div class="chat-input">
        <t-textarea ref="inputRef" v-model="input" placeholder="描述你想写什么… 输入 @ 引用"
          :autosize="{ minRows: 2, maxRows: 5 }" :disabled="busy"
          @keydown="onKeydown" @input="onInput" />
        <div class="input-actions">
          <span class="muted key-hint">Enter 发送 · Shift+Enter 换行</span>
          <t-button v-if="busy" theme="danger" variant="outline" size="small" @click="abort">
            <t-icon name="stop" /> 停止
          </t-button>
          <div class="spacer"></div>
          <t-button theme="primary" size="small" :loading="busy" :disabled="!input.trim() || busy" @click="send">
            发送 <t-icon name="send" />
          </t-button>
        </div>
      </div>
    </div>

    <AskUserDialog :question="pendingAsk" @answer="onAskAnswer" @cancel="pendingAsk = null" />
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { api, ssePost } from '../api'
import { diffLines, diffStats, hasDiff } from '../textDiff'
import AgentTrace from './AgentTrace.vue'
import MentionPicker from './MentionPicker.vue'
import AskUserDialog from './AskUserDialog.vue'
import ContextUsagePanel from './ContextUsagePanel.vue'
import { createAgentTrace } from '../agentTrace'
import { useContextEstimate } from '../composables/useContextEstimate'
import {
  runGenerationStreamTracked,
  subscribeGenerationSession,
  hydrateGenerationSnapshot,
  persistSessionSnapshot,
  setSessionSnapshotProvider,
  clearSessionSnapshotProvider,
  isSessionActive,
  cancelGenerationSession,
} from '../composables/generationSession'

const props = defineProps({
  pid: { type: [String, Number], required: true },
  chid: { type: [String, Number], required: true },
  getContent: { type: Function, default: () => '' },
  getSelection: { type: Function, default: () => null },
})

const emit = defineEmits(['propose-diff', 'review', 'done', 'auto', 'show-diff'])

const scrollEl = ref(null)
const {
  items: liveTrace, handleEvent: traceEvent, clear: clearLiveTrace,
  scroll, resetPinned, bindScroll, unbindScroll,
} = createAgentTrace(scrollEl)

const messages = ref([])
const input = ref('')
const busy = ref(false)
const liveWriting = ref('')
const assistantReply = ref('')
const pickedRefs = ref([])
const mentionOpen = ref(false)
const mentionItems = ref([])
const mentionIdx = ref(0)
const mentionQuery = ref('')
const pendingAsk = ref(null)

function estimatePayload() {
  const sel = props.getSelection?.()
  return {
    feature: 'chat',
    project_id: Number(props.pid),
    chapter_id: Number(props.chid),
    history: apiMessages(),
    references: pickedRefs.value.map((r) => ({ ...r })),
    selection: sel?.text ? { text: sel.text } : null,
  }
}

const { usage: contextUsage, loading: contextLoading, applyUsage: applyContextUsage } = useContextEstimate(
  estimatePayload,
  [messages, pickedRefs, () => props.pid, () => props.chid],
)

let msgId = 0
let contentSnapshot = ''
let pendingQuestionHandled = false
let chatUnsub = null
let readerCur = null
let localStreaming = false

function chatKey() { return `agent-chat:${props.pid}:${props.chid}` }

function chatSnapshot() {
  return {
    messages: messages.value,
    liveTrace: liveTrace.value.map((x) => ({ ...x })),
    liveWriting: liveWriting.value,
    assistantReply: assistantReply.value,
    busy: busy.value,
    contentSnapshot,
    pendingAsk: pendingAsk.value,
    msgId,
  }
}

function restoreChatSnapshot(snap) {
  if (!snap) return
  if (snap.messages) messages.value = snap.messages
  if (snap.liveTrace?.length) liveTrace.value = snap.liveTrace.map((x) => ({ ...x }))
  if (snap.liveWriting != null) liveWriting.value = snap.liveWriting
  if (snap.assistantReply != null) assistantReply.value = snap.assistantReply
  if (snap.busy != null) busy.value = snap.busy
  if (snap.contentSnapshot != null) contentSnapshot = snap.contentSnapshot
  if (snap.pendingAsk !== undefined) pendingAsk.value = snap.pendingAsk
  if (snap.msgId != null) msgId = snap.msgId
}

async function bindChatSession() {
  chatUnsub?.()
  const key = chatKey()
  const saved = await hydrateGenerationSnapshot(key)
  if (saved?.snapshot) restoreChatSnapshot(saved.snapshot)
  busy.value = isSessionActive(key) || busy.value
  chatUnsub = subscribeGenerationSession(key, {
    onRestore: restoreChatSnapshot,
    onActive: (v) => { busy.value = v; if (v) bindScroll() },
    onEvent: (ev) => {
      if (!localStreaming) onEvent(ev)
      persistSessionSnapshot(key, chatSnapshot())
    },
    onDone: () => { if (!localStreaming) onEnd() },
    onError: (e) => { if (!localStreaming) onErr(e) },
  })
  setSessionSnapshotProvider(key, chatSnapshot)
}

const chips = [
  { label: '生成初稿', text: '请根据本章梗概和设定，生成完整章节初稿。' },
  { label: '审校', text: '请审校本章正文，给出评分和具体修订意见。' },
  { label: '按审校修订', text: '请根据最新审校意见修订正文。' },
  { label: '扩写润色', text: '在现有正文基础上扩写润色，增强画面感与节奏。' },
]

function persistChat() {
  persistSessionSnapshot(chatKey(), chatSnapshot())
}

function apiMessages() {
  return messages.value
    .filter((m) => m.content && (m.role === 'user' || m.role === 'assistant'))
    .map((m) => ({ role: m.role, content: m.content }))
}

function useChip(c) {
  if (busy.value) return
  input.value = c.text
  send()
}

async function fetchMentions(q) {
  try {
    const r = await api.get(`/api/projects/${props.pid}/references?q=${encodeURIComponent(q)}`)
    mentionItems.value = r.items || []
    mentionIdx.value = 0
    mentionOpen.value = mentionItems.value.length > 0
  } catch {
    mentionOpen.value = false
  }
}

function onInput() {
  const val = input.value
  const m = val.match(/@([^\s@]*)$/)
  if (m) {
    mentionQuery.value = m[1]
    fetchMentions(mentionQuery.value)
  } else {
    mentionOpen.value = false
  }
}

function onMentionPick(it) {
  const val = input.value
  input.value = val.replace(/@([^\s@]*)$/, `@${it.label} `)
  if (!pickedRefs.value.find((r) => r.type === it.type && r.id === it.id)) {
    pickedRefs.value.push({ type: it.type, id: it.id, label: it.label, content: it.content })
  }
  mentionOpen.value = false
}

function onKeydown(e) {
  if (mentionOpen.value && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    e.preventDefault()
    const n = mentionItems.value.length
    if (!n) return
    mentionIdx.value = e.key === 'ArrowDown' ? (mentionIdx.value + 1) % n : (mentionIdx.value - 1 + n) % n
    return
  }
  if (mentionOpen.value && e.key === 'Enter' && mentionItems.value.length) {
    e.preventDefault()
    onMentionPick(mentionItems.value[mentionIdx.value])
    return
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function send(extraText = '') {
  const text = (extraText || input.value).trim()
  if (!text || busy.value) return
  messages.value.push({ id: ++msgId, role: 'user', content: text })
  input.value = ''
  persistChat()
  runStream()
}

function runStream(extraBody = {}) {
  localStreaming = true
  busy.value = true
  pendingQuestionHandled = false
  contentSnapshot = props.getContent() || ''
  clearLiveTrace()
  liveWriting.value = ''
  assistantReply.value = ''
  resetPinned()

  const sel = props.getSelection?.()
  const body = {
    messages: apiMessages(),
    references: pickedRefs.value.map((r) => ({ ...r })),
    selection: sel?.text ? { text: sel.text } : null,
    ...extraBody,
  }
  pickedRefs.value = []

  const key = chatKey()
  setSessionSnapshotProvider(key, chatSnapshot)
  runGenerationStreamTracked(key, `/api/projects/${props.pid}/chapters/${props.chid}/chat`, body, {
    onEvent: (ev) => {
      onEvent(ev)
      persistSessionSnapshot(key, chatSnapshot())
    },
    onDone: () => { localStreaming = false; onEnd() },
    onError: (e) => { localStreaming = false; onErr(e) },
  })
}

function onEvent(ev) {
  if (ev.type === 'context_usage') applyContextUsage(ev)
  else if (ev.type === 'delta') {
    liveWriting.value += ev.text || ''
    traceEvent(ev, { showOutput: false })
  } else if (ev.type === 'content_set') {
    liveWriting.value = ev.text || ''
    traceEvent({ type: 'status', message: `成稿就绪（${(ev.text || '').replace(/\s/g, '').length} 字），等待确认 Diff` })
  } else if (ev.type === 'message') {
    assistantReply.value = ev.text || ''
  } else if (ev.type === 'ask_user') {
    pendingAsk.value = { question: ev.question, options: ev.options || [], allow_custom: ev.allow_custom !== false }
    traceEvent({ type: 'status', message: '等待你的选择…' })
  } else if (ev.type === 'review') {
    emit('review', ev)
    traceEvent({ type: 'status', message: `审校完成：${ev.score} 分，${(ev.issues || []).length} 条意见` })
  } else if (ev.type === 'version_saved') {
    traceEvent({ type: 'status', message: `已保存版本（${ev.word_count} 字）` })
  } else if (ev.type === 'reasoning' || ev.type === 'tool_call' || ev.type === 'tool_call_delta'
    || ev.type === 'tool_result' || ev.type === 'output' || ev.type === 'status') {
    traceEvent(ev)
  } else if (ev.type === 'error') {
    traceEvent(ev)
    MessagePlugin.error(ev.message || 'Agent 出错')
  }
  scroll()
}

function onAskAnswer(text) {
  pendingAsk.value = null
  pendingQuestionHandled = true
  messages.value.push({ id: ++msgId, role: 'user', content: `【回答 Agent】${text}` })
  persistChat()
  runStream()
}

function onEnd() {
  if (pendingAsk.value && !pendingQuestionHandled) {
    const trace = liveTrace.value.map((x) => ({ ...x }))
    if (trace.length) {
      messages.value.push({
        id: ++msgId,
        role: 'assistant',
        content: '需要你确认后再继续：',
        trace,
      })
      persistChat()
    }
    clearLiveTrace()
    liveWriting.value = ''
    assistantReply.value = ''
    busy.value = false
    scroll()
    return
  }
  busy.value = false
  const trace = liveTrace.value.map((x) => ({ ...x }))
  const newText = liveWriting.value
  let content = assistantReply.value
  let diffMeta = null

  if (newText && hasDiff(contentSnapshot, newText)) {
    const stats = diffStats(diffLines(contentSnapshot, newText))
    diffMeta = { oldText: contentSnapshot, newText, ...stats }
    emit('propose-diff', diffMeta)
    if (!content) content = `已生成变更（+${stats.added} / −${stats.removed} 行），请在左侧确认。`
  } else if (!content && newText) {
    content = '已完成。'
  }

  if (trace.length || content || diffMeta) {
    messages.value.push({ id: ++msgId, role: 'assistant', content, trace, diff: diffMeta })
  }
  clearLiveTrace()
  liveWriting.value = ''
  assistantReply.value = ''
  persistChat()
  scroll()
  emit('done', { hasDiff: !!diffMeta })
}

function onErr(e) {
  busy.value = false
  traceEvent({ type: 'error', message: e.message })
  MessagePlugin.error(e.message)
}

function abort() {
  localStreaming = false
  cancelGenerationSession(chatKey())
  busy.value = false
  pendingAsk.value = null
  onEnd()
}

function readerReview() {
  if (busy.value) return
  busy.value = true
  clearLiveTrace()
  resetPinned()
  readerCur = ssePost(
    `/api/projects/${props.pid}/chapters/${props.chid}/reader-review`,
    { persona: '目标读者' },
    (ev) => {
      if (ev.type === 'reader_review') {
        messages.value.push({
          id: ++msgId,
          role: 'assistant',
          content: ev.report?.summary || '读者审校完成',
          readerReview: { persona: ev.persona, report: ev.report || {} },
        })
        persistChat()
      } else if (ev.type !== 'done') {
        traceEvent(ev)
      }
      scroll()
    },
    () => { busy.value = false; readerCur = null; scroll() },
    (e) => { busy.value = false; MessagePlugin.error(e.message) },
  )
}

watch(() => props.chid, async () => {
  messages.value = []
  clearLiveTrace()
  liveWriting.value = ''
  assistantReply.value = ''
  await bindChatSession()
  scroll(true)
})

watch(liveWriting, () => scroll())

onMounted(() => {
  bindChatSession()
  bindScroll()
  scroll(true)
})
onBeforeUnmount(() => {
  persistSessionSnapshot(chatKey(), chatSnapshot())
  chatUnsub?.()
  if (!isSessionActive(chatKey())) clearSessionSnapshotProvider(chatKey())
  if (readerCur) readerCur.abort()
  unbindScroll()
})

defineExpose({
  clear: () => {
    messages.value = []
    liveWriting.value = ''
    assistantReply.value = ''
    clearLiveTrace()
    persistSessionSnapshot(chatKey(), chatSnapshot())
  },
  send: (text) => send(text),
  focusInput: () => {},
})
</script>

<style scoped>
.agent-chat {
  display: flex; flex-direction: column; height: 100%; min-height: 0;
}
.chat-header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; border-bottom: 1px solid var(--td-component-stroke);
  flex-shrink: 0; background: var(--td-bg-color-container);
}
.chat-header-icon { color: var(--td-brand-color); font-size: 16px; }
.chat-header-title { font-size: 13px; font-weight: 600; }
.chat-messages {
  flex: 1; overflow-y: auto; padding: 12px 14px; min-height: 0;
}
.chat-welcome { font-size: 13px; line-height: 1.7; padding: 8px 4px 16px; color: var(--td-text-color-placeholder); }
.chat-msg.ai .chat-bubble { max-width: 100%; background: transparent; border: none; padding: 4px 0; }
.chat-msg.ai.live .chat-bubble { background: var(--app-chat-ai-bg); border: 1px solid var(--td-component-stroke); padding: 12px 14px; border-radius: var(--app-radius-md); }
.assistant-text { margin-top: 8px; font-size: 14px; line-height: 1.65; white-space: pre-wrap; }
.reader-box { margin-top: 8px; padding: 10px; border-radius: 8px; background: var(--td-bg-color-page); border: 1px solid var(--td-component-stroke); font-size: 13px; }
.reader-head { display: flex; gap: 10px; align-items: center; margin-bottom: 6px; font-size: 12px; }
.diff-hint {
  margin-top: 8px; padding: 8px 10px; border-radius: 8px; cursor: pointer;
  background: var(--td-bg-color-page); border: 1px solid var(--td-component-stroke);
  font-size: 13px; display: flex; align-items: center; gap: 6px;
}
.diff-hint .link { margin-left: auto; color: var(--td-brand-color); font-size: 12px; }
.writing-preview { margin-top: 8px; }
.writing-preview pre {
  margin: 6px 0 0; font-size: 12px; line-height: 1.6; white-space: pre-wrap;
  max-height: 160px; overflow-y: auto; color: var(--td-text-color-secondary);
}
.streaming .stream-label { font-size: 12px; color: var(--td-brand-color); margin-bottom: 4px; }
.ref-tags { display: flex; flex-wrap: wrap; gap: 4px; padding: 4px 0; }
.chat-chips {
  display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 0; border-top: 1px solid var(--td-component-stroke);
}
.chip { cursor: pointer; user-select: none; }
.chip.disabled { opacity: 0.5; pointer-events: none; }
.chat-input-wrap { position: relative; border-top: 1px solid var(--td-component-stroke); padding-top: 8px; }
.chat-input { padding-top: 0; }
.input-actions { display: flex; align-items: center; margin-top: 8px; gap: 8px; }
.key-hint { font-size: 11px; }
.spacer { flex: 1; }
</style>
