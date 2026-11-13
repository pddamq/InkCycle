import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'

/** 防抖调用 /api/context/estimate，预览上下文占用。 */
export function useContextEstimate(getPayload, watchSources = []) {
  const usage = ref(null)
  const loading = ref(false)
  let timer = null
  let seq = 0

  function applyUsage(data) {
    if (!data || typeof data !== 'object') return
    const { type, ...rest } = data
    if (rest.total != null) {
      usage.value = rest
      // SSE 推送的是实际组装结果，取消尚未发出的防抖估算以免覆盖
      clearTimeout(timer)
      seq += 1
      loading.value = false
    }
  }

  async function refresh() {
    const payload = typeof getPayload === 'function' ? getPayload() : getPayload
    if (!payload?.feature) return
    const id = ++seq
    loading.value = true
    try {
      const data = await api.post('/api/context/estimate', payload)
      if (id === seq) applyUsage(data)
    } catch {
      /* 预览失败不影响对话 */
    } finally {
      if (id === seq) loading.value = false
    }
  }

  function scheduleRefresh() {
    clearTimeout(timer)
    timer = setTimeout(refresh, 350)
  }

  watch(watchSources, scheduleRefresh, { deep: true })
  onMounted(scheduleRefresh)
  onBeforeUnmount(() => clearTimeout(timer))

  return { usage, loading, refresh, applyUsage }
}
