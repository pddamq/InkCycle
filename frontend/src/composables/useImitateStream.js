import { reactive } from 'vue'
import { ssePost } from '../api'
import { createAgentTrace } from '../agentTrace'

/** 一键仿写 SSE：进度条 + Agent 轨迹 */
export function useImitateStream() {
  const trace = createAgentTrace()
  let abortStream = null

  const ui = reactive({
    running: false,
    pct: 0,
    status: '',
    phase: '',
    err: '',
    result: null,
  })

  function reset() {
    ui.running = false
    ui.pct = 0
    ui.status = ''
    ui.phase = ''
    ui.err = ''
    ui.result = null
    trace.clear()
    trace.resetPinned()
  }

  function handleEvent(ev) {
    if (ev.type === '_end') return
    trace.handleEvent(ev, { showOutput: true })
    if (ev.type === 'phase') {
      ui.phase = ev.phase || ''
    } else if (ev.type === 'status') {
      ui.status = ev.message || ''
    } else if (ev.type === 'progress') {
      if (ev.pct != null) ui.pct = Number(ev.pct) || 0
      ui.status = ev.hint || ev.message || ui.status
    } else if (ev.type === 'done') {
      ui.result = ev
      ui.pct = 100
      ui.status = '仿写准备完成'
    } else if (ev.type === 'error') {
      ui.err = ev.message || '仿写失败'
      trace.handleEvent(ev)
    }
  }

  function start(srcPid, body, { onDone, onError } = {}) {
    if (ui.running) return
    reset()
    ui.running = true
    abortStream = ssePost(
      `/api/projects/${srcPid}/imitate`,
      body,
      handleEvent,
      () => {
        ui.running = false
        abortStream = null
        if (!ui.err && ui.result) onDone?.(ui.result)
        else if (ui.err) onError?.(new Error(ui.err))
        else onError?.(new Error('仿写未完成'))
      },
      (e) => {
        ui.running = false
        abortStream = null
        ui.err = e.message
        trace.handleEvent({ type: 'error', message: e.message })
        onError?.(e)
      },
    )
  }

  function cancel() {
    abortStream?.abort()
    abortStream = null
    ui.running = false
  }

  return {
    ui,
    /** 须在 setup 顶层解构后传给 AgentTrace，否则模板里 imitate.items 不会自动解包 */
    items: trace.items,
    start,
    cancel,
    reset,
  }
}
