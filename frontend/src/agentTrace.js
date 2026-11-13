import { ref, nextTick } from 'vue'

const SCROLL_THRESHOLD = 64
/** 流式思考：合并到下一帧再写入，避免每个 token 触发重渲染 */
const REASONING_TAIL_STORE = 12000

/** Cursor 风格 Agent 轨迹：思考 / 工具 / 输出流；带「贴底滚动」 */
export function createAgentTrace(scrollElRef = null) {
  const items = ref([])
  let pinned = true
  let scrollListener = null
  let reasoningBuf = ''
  let reasoningFlushId = 0
  let scrollRaf = 0

  function isNearBottom(el) {
    if (!el) return true
    return el.scrollHeight - el.scrollTop - el.clientHeight <= SCROLL_THRESHOLD
  }

  function onUserScroll() {
    const el = scrollElRef?.value
    if (el) pinned = isNearBottom(el)
  }

  function bindScroll() {
    unbindScroll()
    const el = scrollElRef?.value
    if (!el) return
    scrollListener = onUserScroll
    el.addEventListener('scroll', scrollListener, { passive: true })
  }

  function unbindScroll() {
    const el = scrollElRef?.value
    if (el && scrollListener) el.removeEventListener('scroll', scrollListener)
    scrollListener = null
  }

  /** force=true 时无视 pinned，用于新一轮开始 */
  function scroll(force = false) {
    if (scrollRaf) cancelAnimationFrame(scrollRaf)
    scrollRaf = requestAnimationFrame(() => {
      scrollRaf = 0
      nextTick(() => {
        const el = scrollElRef?.value
        if (el && (force || pinned)) el.scrollTop = el.scrollHeight
      })
    })
  }

  function flushReasoningBuf() {
    reasoningFlushId = 0
    if (!reasoningBuf) return
    const chunk = reasoningBuf
    reasoningBuf = ''
    const last = items.value[items.value.length - 1]
    if (last?.type === 'reasoning') {
      last.text += chunk
      if (last.text.length > REASONING_TAIL_STORE) {
        last.text = last.text.slice(-REASONING_TAIL_STORE)
        last.truncated = true
      }
    } else {
      items.value.push({ type: 'reasoning', text: chunk })
    }
    scroll()
  }

  function appendReasoning(text) {
    if (!text) return
    reasoningBuf += text
    if (reasoningFlushId) return
    reasoningFlushId = requestAnimationFrame(flushReasoningBuf)
  }

  function flushPending() {
    if (reasoningFlushId) {
      cancelAnimationFrame(reasoningFlushId)
      reasoningFlushId = 0
    }
    flushReasoningBuf()
  }

  function resetPinned() {
    pinned = true
    scroll(true)
  }

  function clear() {
    flushPending()
    items.value = []
  }

  function appendOutput(text) {
    const last = items.value[items.value.length - 1]
    if (last?.type === 'output') last.text += text
    else items.value.push({ type: 'output', text })
  }

  function handleEvent(ev, opts = {}) {
    const onDelta = opts.onDelta
    const showOutput = opts.showOutput !== false

    switch (ev.type) {
      case 'reasoning':
        appendReasoning(ev.text || '')
        return
      case 'delta':
        if (onDelta) onDelta(ev.text || '')
        if (showOutput) appendOutput(ev.text || '')
        break
      case 'output':
        appendOutput(ev.text || '')
        break
      case 'tool_call_delta': {
        const idx = ev.index ?? 0
        let slot = items.value.find((x) => x.type === 'tool_call' && x.index === idx && x.pending)
        if (!slot) {
          slot = { type: 'tool_call', index: idx, name: '', argsText: '', pending: true }
          items.value.push(slot)
        }
        if (ev.name) slot.name += ev.name
        if (ev.arguments) slot.argsText += ev.arguments
        break
      }
      case 'tool_call': {
        const idx = ev.index ?? items.value.filter((x) => x.type === 'tool_call').length
        const pending = items.value.find((x) => x.type === 'tool_call' && x.index === idx && x.pending)
        const argsText = ev.arguments
          ? JSON.stringify(ev.arguments, null, 2)
          : (pending?.argsText || '{}')
        if (pending) {
          pending.name = ev.name || pending.name
          pending.argsText = argsText
          pending.pending = false
        } else {
          items.value.push({ type: 'tool_call', index: idx, name: ev.name, argsText, pending: false })
        }
        break
      }
      case 'tool_result':
        items.value.push({
          type: 'tool_result',
          name: ev.name || '',
          text: ev.result || ev.text || '',
        })
        break
      case 'phase':
        items.value.push({ type: 'phase', text: opts.phaseText ? opts.phaseText(ev) : (ev.phase || ev.text || '') })
        break
      case 'volume': {
        const label = ev.stage === 'done'
          ? `✓ 卷 ${ev.index}/${ev.total}：${ev.title || ''}`
          : `▶ 卷 ${ev.index}/${ev.total}：${ev.title || ''}`
        items.value.push({ type: 'phase', text: label })
        break
      }
      case 'status': {
        const msg = ev.message || ev.text || ''
        const last = items.value[items.value.length - 1]
        if (last?.type === 'status') last.text = msg
        else items.value.push({ type: 'status', text: msg })
        break
      }
      case 'progress': {
        const msg = ev.hint || ev.message || `${ev.chars || 0} 字符`
        const slot = items.value.find((x) => x.type === 'progress')
        if (slot) {
          if (slot.text !== msg) slot.text = msg
        } else {
          items.value.push({ type: 'progress', text: msg })
        }
        break
      }
      case 'error':
        items.value.push({ type: 'error', text: ev.message || ev.text || '未知错误' })
        break
      default:
        break
    }
    scroll()
  }

  return { items, handleEvent, clear, scroll, resetPinned, bindScroll, unbindScroll, flushPending }
}
