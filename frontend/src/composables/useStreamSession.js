import { ref, onMounted, onUnmounted } from 'vue'
import {
  isSessionActive,
  hydrateGenerationSnapshot,
  persistSessionSnapshot,
  subscribeGenerationSession,
  setSessionSnapshotProvider,
  clearSessionSnapshotProvider,
  runGenerationStreamTracked,
} from './generationSession'

/** 访谈类页面的 SSE（Interview / CharacterDesign）：切页不断流 */
export function useStreamSession(sessionKey, { trace, getStreamSnapshot, restoreStreamSnapshot }) {
  const busy = ref(false)
  let unsub = null
  let localStreaming = false

  function snapshot() {
    return {
      traceItems: trace.items.value.map((x) => ({ ...x })),
      busy: busy.value,
      ...(getStreamSnapshot?.() || {}),
    }
  }

  function restore(snap) {
    if (!snap) return
    if (snap.traceItems?.length) trace.items.value = snap.traceItems.map((x) => ({ ...x }))
    restoreStreamSnapshot?.(snap)
    busy.value = !!snap.busy
  }

  onMounted(async () => {
    const saved = await hydrateGenerationSnapshot(sessionKey)
    if (saved?.snapshot) restore(saved.snapshot)
    busy.value = isSessionActive(sessionKey) || busy.value

    unsub = subscribeGenerationSession(sessionKey, {
      onRestore: (snap) => restore(snap),
      onActive: (v) => { busy.value = v },
      onEvent: (ev) => {
        if (!localStreaming && ev.type !== 'output') trace.handleEvent(ev, { showOutput: false })
      },
      onDone: () => { if (!localStreaming) busy.value = false },
      onError: () => { if (!localStreaming) busy.value = false },
    })

    setSessionSnapshotProvider(sessionKey, snapshot)
  })

  onUnmounted(() => {
    persistSessionSnapshot(sessionKey, snapshot())
    unsub?.()
    if (!isSessionActive(sessionKey)) clearSessionSnapshotProvider(sessionKey)
  })

  function run(url, body, { onEvent, onDone, onError, beforeStart } = {}) {
    beforeStart?.()
    localStreaming = true
    busy.value = true
    setSessionSnapshotProvider(sessionKey, snapshot)
    return runGenerationStreamTracked(sessionKey, url, body, {
      onEvent: (ev) => {
        if (ev.type !== 'output') trace.handleEvent(ev, { showOutput: false })
        onEvent?.(ev)
        persistSessionSnapshot(sessionKey, snapshot())
      },
      onDone: () => {
        localStreaming = false
        busy.value = false
        onDone?.()
      },
      onError: (e) => {
        localStreaming = false
        busy.value = false
        onError?.(e)
      },
    })
  }

  return { busy, run, restore, snapshot }
}
