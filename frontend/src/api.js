const BASE = ''
const DEFAULT_TIMEOUT_MS = 120000

async function req(method, url, body = null, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const opts = { method, headers: {} }
  if (body !== null) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  let resp
  try {
    resp = await fetch(BASE + url, { ...opts, signal: ctrl.signal })
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('请求超时，请检查 API 地址、Key 与网络')
    throw e
  } finally {
    clearTimeout(timer)
  }
  let data = null
  try { data = await resp.json() } catch { /* 非 JSON */ }
  if (!resp.ok) {
    const msg = (data && (data.detail || data.message)) || `HTTP ${resp.status}`
    throw new Error(msg)
  }
  return data
}

export const api = {
  get: (url) => req('GET', url),
  post: (url, body, timeoutMs) => req('POST', url, body ?? {}, timeoutMs),
  put: (url, body) => req('PUT', url, body ?? {}),
  del: (url) => req('DELETE', url),
}

/**
 * SSE 流式请求。onEvent(ev) 接收每个 JSON 事件。
 * 返回 { abort } 可取消。
 */
export function ssePost(url, body, onEvent, onDone, onError) {
  const ctrl = new AbortController()
  ;(async () => {
    try {
      const resp = await fetch(BASE + url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body ?? {}),
        signal: ctrl.signal,
      })
      if (!resp.ok) {
        let msg = `HTTP ${resp.status}`
        try { msg = (await resp.json()).detail || msg } catch {}
        throw new Error(msg)
      }
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop()
        for (const part of parts) {
          const line = part.split('\n').find((l) => l.startsWith('data:'))
          if (!line) continue
          try {
            onEvent(JSON.parse(line.slice(5)))
          } catch { /* 忽略坏帧 */ }
        }
      }
      onDone && onDone()
    } catch (e) {
      if (e.name !== 'AbortError') onError && onError(e)
    }
  })()
  return { abort: () => ctrl.abort() }
}

export const fmt = {
  date: (s) => (s || '').replace('T', ' ').slice(0, 16),
}
