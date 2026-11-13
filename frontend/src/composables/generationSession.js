import { ref, shallowRef } from 'vue'
import { api, ssePost } from '../api'

/** 全局 AI 生成 SSE 会话：切页不 abort；快照仅存后端 SQLite */
const sessions = new Map()
const hydrated = new Map()

function createSession(key) {
  return {
    key,
    active: false,
    stream: null,
    url: '',
    subscribers: new Set(),
    snapshot: null,
    getSnapshot: null,
    meta: null,
  }
}

export function getGenerationSession(key) {
  if (!sessions.has(key)) sessions.set(key, createSession(key))
  return sessions.get(key)
}

function normalizeSaved(data) {
  if (!data?.snapshot) return null
  const interrupted = !!(data.wasActive || data.active)
  return { ...data, active: false, interrupted }
}

export async function hydrateGenerationSnapshot(key) {
  if (hydrated.has(key)) return hydrated.get(key)
  const s = getGenerationSession(key)
  if (s.snapshot && s.active) {
    const live = { snapshot: s.snapshot, active: true, url: s.url, interrupted: false }
    hydrated.set(key, live)
    return live
  }
  try {
    const data = await api.get(`/api/generation-snapshots/${encodeURIComponent(key)}`)
    const norm = normalizeSaved(data)
    if (norm) s.snapshot = norm.snapshot
    hydrated.set(key, norm)
    return norm
  } catch {
    hydrated.set(key, null)
    return null
  }
}

export function registerSessionMeta(key, meta) {
  getGenerationSession(key).meta = meta
}

const PERSIST_DELAY_MS = 1500
const persistTimers = new Map()

function trimSnapshotForPersist(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return snapshot
  const out = { ...snapshot }
  if (Array.isArray(out.items)) {
    out.items = out.items.map((it) => {
      if (!it || typeof it !== 'object') return it
      if (it.type === 'reasoning' || it.type === 'output') {
        const t = it.text || ''
        if (t.length > 6000) return { ...it, text: t.slice(-6000), truncated: true }
      }
      if (it.type === 'tool_result') {
        const t = it.text || it.result || ''
        if (t.length > 2000) return { ...it, text: t.slice(-2000), truncated: true }
      }
      return it
    })
  }
  if (Array.isArray(out.liveTrace)) {
    out.liveTrace = out.liveTrace.map((it) => {
      if (it?.type === 'reasoning' || it?.type === 'output') {
        const t = it.text || ''
        if (t.length > 6000) return { ...it, text: t.slice(-6000), truncated: true }
      }
      return it
    })
  }
  return out
}

function postSnapshot(key, snapshot) {
  const s = getGenerationSession(key)
  const trimmed = trimSnapshotForPersist(snapshot)
  s.snapshot = trimmed
  const payload = {
    snapshot: trimmed,
    active: false,
    wasActive: s.active,
    url: s.url,
    ts: Date.now(),
  }
  const norm = normalizeSaved(payload)
  hydrated.set(key, norm)
  api.post(`/api/generation-snapshots/${encodeURIComponent(key)}`, payload).catch(() => {})
}

export function persistSessionSnapshot(key, snapshot, { immediate = false } = {}) {
  if (immediate) {
    const t = persistTimers.get(key)
    if (t) clearTimeout(t)
    persistTimers.delete(key)
    postSnapshot(key, snapshot)
    return
  }
  const s = getGenerationSession(key)
  s.snapshot = trimSnapshotForPersist(snapshot)
  if (persistTimers.has(key)) clearTimeout(persistTimers.get(key))
  persistTimers.set(key, setTimeout(() => {
    persistTimers.delete(key)
    const snap = s.getSnapshot?.() ?? s.snapshot
    if (snap) postSnapshot(key, snap)
  }, PERSIST_DELAY_MS))
}

export function flushPersistSessionSnapshot(key) {
  const s = getGenerationSession(key)
  const t = persistTimers.get(key)
  if (t) clearTimeout(t)
  persistTimers.delete(key)
  const snap = s.getSnapshot?.() ?? s.snapshot
  if (snap) postSnapshot(key, snap)
}

export function loadSessionSnapshot(key) {
  const s = getGenerationSession(key)
  if (s.snapshot && s.active) {
    return { snapshot: s.snapshot, active: true, url: s.url, interrupted: false }
  }
  return hydrated.get(key) ?? null
}

export function wasSessionInterrupted(key) {
  return !!loadSessionSnapshot(key)?.interrupted
}

export function isSessionActive(key) {
  return getGenerationSession(key).active
}

export function setSessionSnapshotProvider(key, fn) {
  getGenerationSession(key).getSnapshot = fn
}

export function clearSessionSnapshotProvider(key) {
  getGenerationSession(key).getSnapshot = null
}

function flushSnapshot(key, { immediate = false } = {}) {
  const s = getGenerationSession(key)
  if (s.getSnapshot) {
    persistSessionSnapshot(key, s.getSnapshot(), { immediate })
  } else if (s.snapshot) {
    persistSessionSnapshot(key, s.snapshot, { immediate })
  }
}

function dispatch(key, type, payload) {
  getGenerationSession(key).subscribers.forEach((sub) => {
    if (type === 'event') sub.onEvent?.(payload)
    if (type === 'done') sub.onDone?.(payload)
    if (type === 'error') sub.onError?.(payload)
    if (type === 'restore' && sub.onRestore) sub.onRestore(payload)
  })
}

export function subscribeGenerationSession(key, callbacks) {
  const s = getGenerationSession(key)
  s.subscribers.add(callbacks)
  const saved = loadSessionSnapshot(key)
  if (saved?.snapshot) callbacks.onRestore?.(saved.snapshot, saved.active)
  if (s.active) callbacks.onActive?.(true)
  return () => s.subscribers.delete(callbacks)
}

export function runGenerationStream(key, url, body, handlers = {}) {
  const s = getGenerationSession(key)

  if (s.active && s.stream && s.url === url) {
    return waitSessionEnd(key, handlers)
  }

  if (s.active && s.stream) {
    s.stream.abort()
    s.stream = null
  }

  s.active = true
  s.url = url
  registerSessionMeta(key, metaFromKey(key))
  touchActiveSessions()
  let result = null

  s.stream = ssePost(
    url,
    body ?? {},
    (ev) => {
      handlers.onEvent?.(ev)
      dispatch(key, 'event', ev)
      flushSnapshot(key)
      if (ev.type === 'done') result = true
      else if (ev.type === 'error') result = false
    },
    () => {
      s.active = false
      s.stream = null
      flushSnapshot(key, { immediate: true })
      handlers.onDone?.()
      dispatch(key, 'done')
      touchActiveSessions()
    },
    (e) => {
      if (e.name === 'AbortError') {
        s.active = false
        s.stream = null
        return
      }
      s.active = false
      s.stream = null
      flushSnapshot(key, { immediate: true })
      handlers.onError?.(e)
      dispatch(key, 'error', e)
      result = false
      touchActiveSessions()
    },
  )

  return waitSessionEnd(key, handlers, () => result)
}

function waitSessionEnd(key, handlers, getResult) {
  return new Promise((resolve) => {
    if (!isSessionActive(key)) {
      const r = getResult?.()
      resolve(r === true)
      return
    }
    const unsub = subscribeGenerationSession(key, {
      onDone: () => {
        unsub()
        handlers.onDone?.()
        resolve(getResult?.() === true)
      },
      onError: (e) => {
        unsub()
        handlers.onError?.(e)
        resolve(false)
      },
    })
  })
}

export function cancelGenerationSession(key) {
  const s = getGenerationSession(key)
  s.stream?.abort()
  s.active = false
  s.stream = null
  s.url = ''
  flushSnapshot(key)
  dispatch(key, 'done')
}

export function clearGenerationSession(key) {
  cancelGenerationSession(key)
  sessions.delete(key)
  hydrated.delete(key)
  api.del(`/api/generation-snapshots/${encodeURIComponent(key)}`).catch(() => {})
}

const activeList = shallowRef([])

function refreshActiveList() {
  const items = []
  for (const [key, s] of sessions.entries()) {
    if (!s.active) continue
    items.push({ key, ...(s.meta || metaFromKey(key)) })
  }
  activeList.value = items
}

export function useActiveGenerationSessions() {
  return activeList
}

export function metaFromKey(key) {
  if (key === 'interview:next' || key === 'interview:compile') return { label: '开书访谈', route: '/new' }
  let m = key.match(/^import:analyze:(\d+)$/)
  if (m) return { label: '导入分析', route: `/import?pid=${m[1]}` }
  m = key.match(/^character-design:(\d+):(next|compile)$/)
  if (m) return { label: '角色设计访谈', route: `/project/${m[1]}/characters/design` }
  m = key.match(/^wizard:(\d+)$/)
  if (m) return { label: '作品生成向导', route: `/wizard/${m[1]}` }
  m = key.match(/^chars-quick:(\d+)$/)
  if (m) return { label: '快速生成角色', route: `/project/${m[1]}/characters` }
  m = key.match(/^outline:(\d+)$/)
  if (m) return { label: 'AI 生成大纲', route: `/project/${m[1]}/outline` }
  m = key.match(/^editor-auto:(\d+):(\d+)$/)
  if (m) return { label: '章节自动创作', route: `/project/${m[1]}/chapter/${m[2]}` }
  m = key.match(/^agent-chat:(\d+):(\d+)$/)
  if (m) return { label: '写作助手', route: `/project/${m[1]}/chapter/${m[2]}` }
  return { label: 'AI 生成中', route: '/' }
}

export function touchActiveSessions() {
  refreshActiveList()
}

const _run = runGenerationStream
export function runGenerationStreamTracked(key, url, body, handlers) {
  registerSessionMeta(key, metaFromKey(key))
  touchActiveSessions()
  return _run(key, url, body, {
    ...handlers,
    onDone: () => { handlers.onDone?.(); touchActiveSessions() },
    onError: (e) => { handlers.onError?.(e); touchActiveSessions() },
  }).finally(() => touchActiveSessions())
}
