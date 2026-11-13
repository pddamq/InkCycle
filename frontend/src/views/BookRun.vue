<template>
  <div class="page bookrun">
    <div class="toolbar">
      <h1 class="page-title" style="margin:0">整本创作</h1>
      <t-tag :theme="statusTheme" variant="light">{{ statusText }}</t-tag>
      <div class="spacer"></div>
      <t-button v-if="!running" theme="primary" :disabled="st.remaining===0" @click="openStart">
        <t-icon name="play-circle" /> {{ st.done>0 && st.remaining>0 ? '继续创作' : '开始全书创作' }}
      </t-button>
      <t-button v-else theme="danger" :loading="stopping" @click="doStop">
        <t-icon name="stop" /> 停止（完成当前章后）
      </t-button>
    </div>

    <t-alert theme="info" style="margin-bottom:16px"
      message="整本创作在后台逐章运行（起草→审校→修订），靠章节摘要保持前后连贯。可以离开本页或最小化窗口，任务会继续；中断后回来点「继续创作」会从未完成的章节接着写。" />

    <!-- 进度 -->
    <t-card style="margin-bottom:16px">
      <div class="prog-head">
        <span class="prog-num">{{ st.done }} / {{ st.total }}</span>
        <span class="muted">章已完成</span>
        <div class="spacer"></div>
        <span v-if="running && st.current_chapter_title" class="cur">
          正在写：《{{ st.current_chapter_title }}》
        </span>
      </div>
      <t-progress :percentage="pct" :status="st.status==='error'?'danger':(st.status==='done'?'success':'active')" />
      <div class="prog-meta muted">
        <span>模式：{{ st.mode==='draft_only'?'快速初稿': st.mode==='polish'?'打磨':'完整' }}</span>
        <span>每章最多 {{ st.rounds }} 轮</span>
        <span>达标 {{ st.threshold }} 分</span>
        <span v-if="st.remaining>0">剩余 {{ st.remaining }} 章</span>
      </div>
    </t-card>

    <div class="book-cols">
      <!-- 事件日志 -->
      <t-card title="进度日志" class="col">
        <div class="log" ref="logEl">
          <div v-if="!log.length" class="muted">尚无事件。开始创作后这里会实时显示每章进度。</div>
          <div v-for="(l,i) in log" :key="i" :class="'lg-'+l.kind">{{ l.text }}</div>
        </div>
      </t-card>

      <!-- AI 过程 + 正文流 -->
      <t-card title="AI 过程（当前章）" class="col">
        <div class="live" ref="liveEl">
          <AgentTrace
            :items="traceItems"
            :live="running"
            :status-hint="traceHint"
            empty-text="等待 AI 响应…"
          />
        </div>
      </t-card>
    </div>

    <!-- 启动参数 -->
    <t-dialog v-model:visible="startOpen" header="开始整本创作" :on-confirm="doStart">
      <t-form label-width="120px">
        <t-form-item label="模式">
          <t-radio-group v-model="startForm.mode">
            <t-radio value="draft_only">快速（仅初稿，最快）</t-radio>
            <t-radio value="full">完整（初稿→审校→修订）</t-radio>
            <t-radio value="polish">打磨（仅审校→修订已有稿）</t-radio>
          </t-radio-group>
        </t-form-item>
        <t-form-item label="每章最大轮数">
          <t-input-number v-model="startForm.rounds" :min="1" :max="6" theme="column" />
        </t-form-item>
        <t-form-item label="出错时">
          <t-radio-group v-model="startForm.stop_on_error">
            <t-radio :value="false">跳过该章，继续写后面</t-radio>
            <t-radio :value="true">停止整个任务</t-radio>
          </t-radio-group>
        </t-form-item>
      </t-form>
      <div class="muted">将创作 {{ st.remaining }} 个未完成章节。</div>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import { createAgentTrace } from '../agentTrace'
import AgentTrace from '../components/AgentTrace.vue'

const route = useRoute()
const pid = computed(() => route.params.pid)

const st = reactive({ status: 'idle', live: false, mode: 'full', rounds: 2, threshold: 85,
  total: 0, done: 0, remaining: 0, current_chapter_title: '', seq: 0 })
const log = ref([])
const logEl = ref(null)
const liveEl = ref(null)
const trace = createAgentTrace(liveEl)
const traceItems = trace.items
const startOpen = ref(false)
const stopping = ref(false)
const startForm = reactive({ mode: 'draft_only', rounds: 2, stop_on_error: false })

let eventSource = null
let pollTimer = null
let lastAppliedSeq = 0
let disposed = false

const STATUS_TEXT = { idle: '未开始', running: '创作中', stopping: '正在停止', stopped: '已停止',
  interrupted: '已中断', done: '已完成', error: '出错' }
const STATUS_THEME = { idle: 'default', running: 'primary', stopping: 'warning', stopped: 'warning',
  interrupted: 'warning', done: 'success', error: 'danger' }
const statusText = computed(() => STATUS_TEXT[st.status] || st.status)
const statusTheme = computed(() => STATUS_THEME[st.status] || 'default')
const running = computed(() => st.status === 'running' || st.status === 'stopping')
const pct = computed(() => st.total ? Math.round(st.done / st.total * 100) : 0)
const traceHint = computed(() => {
  if (st.current_chapter_title) return `《${st.current_chapter_title}》`
  return running.value ? '准备中…' : ''
})

function pushLog(kind, text) {
  log.value.push({ kind, text })
  if (log.value.length > 600) log.value.splice(0, log.value.length - 600)
  nextTick(() => { if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight })
}

function applyState(s) {
  Object.assign(st, s)
  if (s.seq != null) lastAppliedSeq = Math.max(lastAppliedSeq, s.seq)
}

function shouldSkip(ev) {
  if (ev.seq == null) return false
  if (ev.seq <= lastAppliedSeq) return true
  lastAppliedSeq = ev.seq
  return false
}

function renderEvent(ev) {
  if (ev.type === 'state') {
    applyState(ev)
    return
  }
  if (shouldSkip(ev)) return
  switch (ev.type) {
    case 'job_start':
      pushLog('start', `▶ 开始整本创作：共 ${ev.total} 章，本次待写 ${ev.remaining} 章`)
      trace.handleEvent({ type: 'status', message: `开始整本创作，待写 ${ev.remaining} 章` })
      break
    case 'chapter_start':
      trace.clear()
      trace.resetPinned()
      trace.bindScroll()
      pushLog('chapter', `📖 第 ${ev.index} 章《${ev.title}》（剩余 ${ev.remaining}）`)
      trace.handleEvent({ type: 'phase', phase: `第 ${ev.index} 章《${ev.title}》` })
      break
    case 'phase':
      pushLog('phase', `   · ${phaseText(ev)}`)
      trace.handleEvent({ type: 'phase', phase: phaseText(ev) })
      break
    case 'review':
      pushLog('review', `   · 审校 ${ev.score} 分（${ev.issues} 条意见）`)
      trace.handleEvent({ type: 'status', message: `审校 ${ev.score} 分（${ev.issues} 条意见）` })
      break
    case 'chapter_done':
      pushLog('done', `✓ 第 ${ev.index} 章《${ev.title}》完成，${ev.score ?? '—'} 分`)
      trace.handleEvent({ type: 'status', message: `第 ${ev.index} 章完成` })
      break
    case 'chapter_error':
      pushLog('error', `✗《${ev.title}》出错：${ev.message}`)
      trace.handleEvent({ type: 'error', message: ev.message })
      break
    case 'job_done':
      pushLog('finish', `🎉 全书完成！共 ${ev.done} 章；未回收伏笔 ${ev.unresolved_foreshadow ?? 0} 条`)
      trace.handleEvent({ type: 'status', message: '全书创作完成' })
      break
    case 'job_stopped':
      pushLog('warn', `⏸ 已停止，完成 ${ev.done ?? st.done} 章`)
      trace.handleEvent({ type: 'status', message: '任务已停止' })
      break
    case 'job_error':
      pushLog('error', `✗ 任务出错：${ev.message}`)
      trace.handleEvent({ type: 'error', message: ev.message })
      break
    case 'reasoning':
      trace.handleEvent(ev, { showOutput: true })
      break
    case 'delta':
      trace.handleEvent(ev, { showOutput: true })
      break
    case 'status':
      trace.handleEvent({ type: 'status', message: ev.message || '' })
      break
    case 'tool_call':
      trace.handleEvent(ev)
      break
    case 'tool_result':
      trace.handleEvent(ev)
      break
    default:
      break
  }
}

function phaseText(ev) {
  const m = { start: '准备', draft: '起草', review: '审校', revise: '修订' }
  return `${m[ev.phase] || ev.phase}${ev.round ? '（第' + ev.round + '轮）' : ''}`
}

async function refreshStatus() {
  try { applyState(await api.get(`/api/projects/${pid.value}/book/status`)) }
  catch { /* 忽略 */ }
}

/** 轮询粗粒度事件（SSE 在 webview 中可能缓冲，靠 DB 回放保证进度日志不空） */
async function pollEvents() {
  if (disposed) return
  try {
    const r = await api.get(`/api/projects/${pid.value}/book/events?since=${lastAppliedSeq}`)
    if (r.status) applyState(r.status)
    for (const ev of r.events || []) renderEvent(ev)
  } catch { /* 忽略 */ }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(pollEvents, 1200)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function closeStream() {
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}

function connect() {
  if (disposed) return
  closeStream()
  const url = `/api/projects/${pid.value}/book/stream?since=${lastAppliedSeq}`
  if (typeof EventSource !== 'undefined') {
    eventSource = new EventSource(url)
    eventSource.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data)
        if (ev.type === 'stream_end') {
          closeStream()
          afterStreamClose(true)
          return
        }
        if (ev.type === 'ping') return
        renderEvent(ev)
      } catch { /* 坏帧 */ }
    }
    eventSource.onerror = () => {
      closeStream()
      afterStreamClose(false)
    }
    return
  }
  // 降级：fetch 读流
  const ctrl = new AbortController()
  fetch(url, { signal: ctrl.signal }).then(async (resp) => {
    if (!resp.ok) throw new Error('HTTP ' + resp.status)
    const reader = resp.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    let ended = false
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const parts = buf.split('\n\n')
      buf = parts.pop()
      for (const part of parts) {
        const line = part.split('\n').find((l) => l.startsWith('data:'))
        if (!line) continue
        try {
          const ev = JSON.parse(line.slice(5))
          if (ev.type === 'stream_end') { ended = true; continue }
          if (ev.type === 'ping') continue
          renderEvent(ev)
        } catch { /* 坏帧 */ }
      }
    }
    afterStreamClose(ended)
  }).catch((e) => {
    if (e.name !== 'AbortError') afterStreamClose(false)
  })
  eventSource = { close: () => ctrl.abort() }
}

async function afterStreamClose(ended) {
  await refreshStatus()
  if (disposed) return
  if (running.value || st.live || (!ended && st.status === 'running')) {
    setTimeout(connect, 1500)
  } else {
    stopPolling()
    trace.unbindScroll()
  }
}

function syncFollow() {
  if (running.value || st.live) {
    startPolling()
    connect()
    trace.bindScroll()
  } else {
    stopPolling()
    closeStream()
    trace.unbindScroll()
  }
}

async function openStart() {
  await refreshStatus()
  if (st.remaining === 0) return MessagePlugin.info('所有章节都已完成')
  startForm.rounds = st.rounds || 2
  startForm.mode = st.mode || 'full'
  startOpen.value = true
}

async function doStart() {
  startOpen.value = false
  log.value = []
  trace.clear()
  trace.resetPinned()
  lastAppliedSeq = 0
  try {
    const r = await api.post(`/api/projects/${pid.value}/book/start`, { ...startForm })
    if (!r.ok) return MessagePlugin.error(r.error || '启动失败')
    MessagePlugin.success('已开始整本创作')
    await refreshStatus()
    await pollEvents()
    syncFollow()
  } catch (e) { MessagePlugin.error(e.message) }
}

async function doStop() {
  stopping.value = true
  try {
    const r = await api.post(`/api/projects/${pid.value}/book/stop`)
    if (r.ok) MessagePlugin.success(r.message || '已发送停止')
    else MessagePlugin.warning(r.error || '无运行任务')
    await refreshStatus()
    await pollEvents()
  } catch (e) { MessagePlugin.error(e.message) }
  finally { stopping.value = false }
}

onMounted(async () => {
  await refreshStatus()
  await pollEvents()
  syncFollow()
})

onBeforeUnmount(() => {
  disposed = true
  stopPolling()
  closeStream()
  trace.unbindScroll()
})
</script>

<style scoped>
.bookrun { max-width: 1400px; }
.prog-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.prog-num { font-size: 24px; font-weight: 700; }
.cur { font-size: 13px; color: var(--td-brand-color); }
.prog-meta { display: flex; gap: 18px; margin-top: 10px; font-size: 12px; }
.book-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.col :deep(.t-card__body) { padding: 0; }
.log, .live { height: 380px; overflow-y: auto; padding: 12px 16px; font-size: 13px; line-height: 1.8; }
.lg-start, .lg-finish { font-weight: 600; color: var(--td-brand-color); }
.lg-chapter { font-weight: 600; margin-top: 6px; }
.lg-phase, .lg-review { color: var(--td-text-color-secondary); }
.lg-done { color: var(--td-success-color); }
.lg-error { color: var(--td-error-color); }
.lg-warn { color: var(--td-warning-color); }
@media (max-width: 900px) { .book-cols { grid-template-columns: 1fr; } }
</style>
