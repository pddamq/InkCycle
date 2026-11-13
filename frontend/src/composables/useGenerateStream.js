import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { createAgentTrace } from '../agentTrace'
import {
  isSessionActive,
  hydrateGenerationSnapshot,
  loadSessionSnapshot,
  persistSessionSnapshot,
  subscribeGenerationSession,
  setSessionSnapshotProvider,
  clearSessionSnapshotProvider,
  runGenerationStreamTracked,
  cancelGenerationSession,
  clearGenerationSession,
  wasSessionInterrupted,
} from './generationSession'

/** AI 生成类任务（向导/角色/大纲）：SSE + Agent 轨迹；支持切页不断流 */
export function useGenerateStream(sessionKey, { extraSnapshot, restoreExtra } = {}) {
  if (!sessionKey) throw new Error('useGenerateStream 需要 sessionKey')

  const scrollEl = ref(null)
  const trace = createAgentTrace(scrollEl)
  const active = ref(false)
  const interrupted = ref(false)
  const status = ref('')
  let unsub = null

  function getSnapshot() {
    const snap = {
      items: trace.items.value.map((x) => ({ ...x })),
      status: status.value,
      active: active.value,
    }
    const extra = extraSnapshot?.()
    if (extra != null) snap.extra = extra
    return snap
  }

  function restoreSnapshot(snap) {
    if (!snap) return
    if (snap.items?.length) trace.items.value = snap.items.map((x) => ({ ...x }))
    status.value = snap.status || ''
    if (snap.extra != null) restoreExtra?.(snap.extra)
  }

  function handleSseEvent(ev, onEvent) {
    if (ev.type === '_end') return
    if (ev.type === 'status') status.value = ev.message || ''
    trace.handleEvent(ev, { showOutput: false })
    onEvent?.(ev)
  }

  let localStreaming = false

  onMounted(async () => {
    const saved = await hydrateGenerationSnapshot(sessionKey)
    if (saved?.snapshot) restoreSnapshot(saved.snapshot)
    active.value = isSessionActive(sessionKey)
    interrupted.value = !!saved?.interrupted || wasSessionInterrupted(sessionKey)
    if (interrupted.value && !active.value && !status.value) {
      status.value = '上次生成被中断，可重新操作继续'
    }

    unsub = subscribeGenerationSession(sessionKey, {
      onRestore: (snap) => restoreSnapshot(snap),
      onActive: (v) => { active.value = v; if (v) trace.bindScroll() },
      onEvent: (ev) => { if (!localStreaming) handleSseEvent(ev) },
      onDone: () => {
        if (!localStreaming) {
          active.value = false
          interrupted.value = false
          trace.unbindScroll()
        }
      },
      onError: (e) => {
        if (!localStreaming) {
          active.value = false
          trace.unbindScroll()
          trace.handleEvent({ type: 'error', message: e.message })
        }
      },
    })

    if (active.value) trace.bindScroll()
    setSessionSnapshotProvider(sessionKey, getSnapshot)
  })

  onUnmounted(() => {
    trace.flushPending?.()
    persistSessionSnapshot(sessionKey, getSnapshot(), { immediate: true })
    unsub?.()
    trace.unbindScroll()
    if (!isSessionActive(sessionKey)) clearSessionSnapshotProvider(sessionKey)
  })

  function start(url, body, { onEvent, onDone, onError } = {}) {
    const already = isSessionActive(sessionKey)
    if (!already) {
      trace.clear()
      trace.resetPinned()
      status.value = ''
    }
    interrupted.value = false
    localStreaming = true
    active.value = true
    setSessionSnapshotProvider(sessionKey, getSnapshot)
    trace.bindScroll()

    return runGenerationStreamTracked(sessionKey, url, body, {
      onEvent: (ev) => handleSseEvent(ev, onEvent),
      onDone: () => {
        trace.flushPending?.()
        localStreaming = false
        active.value = false
        interrupted.value = false
        trace.unbindScroll()
        onDone?.()
      },
      onError: (e) => {
        localStreaming = false
        active.value = false
        trace.unbindScroll()
        trace.handleEvent({ type: 'error', message: e.message })
        onError?.(e)
      },
    })
  }

  function cancel() {
    localStreaming = false
    cancelGenerationSession(sessionKey)
    active.value = false
    trace.unbindScroll()
  }

  function clearPersisted() {
    clearGenerationSession(sessionKey)
    interrupted.value = false
    status.value = ''
    trace.clear()
  }

  // reactive 包装：模板里 gen.items / gen.status 才能正确解包并响应更新
  return reactive({
    scrollEl,
    items: trace.items,
    active,
    interrupted,
    status,
    start,
    cancel,
    clearPersisted,
    bindScroll: trace.bindScroll,
    getSnapshot,
    restoreSnapshot,
  })
}
