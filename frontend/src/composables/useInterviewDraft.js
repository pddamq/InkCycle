import { api } from '../api'
import { clearGenerationSession } from './generationSession'

export function draftHint(draft) {
  if (!draft) return ''
  if (draft.phase === 'review') return '上次已生成创作蓝图，可继续编辑并创建作品'
  if (draft.compileInterrupted) return '上次生成蓝图时被中断，可继续生成'
  if (draft.current?.phase === 'ready') return '访谈已完成，可继续生成创作蓝图'
  const n = draft.round || draft.transcript?.length || 0
  return n ? `访谈进行到第 ${draft.round || '?'} 轮，可继续回答` : '有未完成的访谈，可继续'
}

export async function loadInterviewDraft() {
  try {
    const data = await api.get('/api/interview/draft')
    if (data?.history?.length || data?.phase === 'review') return data
  } catch { /* ignore */ }
  return null
}

export async function saveInterviewDraft(draft) {
  const data = { ...draft, savedAt: new Date().toISOString() }
  await api.post('/api/interview/draft', data)
  return data
}

export async function clearInterviewDraft() {
  await api.del('/api/interview/draft')
}

/** 放弃访谈：清除草稿、流式快照与「继续上次」中的访谈入口 */
export async function discardInterviewDraft() {
  await clearInterviewDraft()
  clearGenerationSession('interview:next')
  clearGenerationSession('interview:compile')
  try {
    const last = await api.get('/api/session/last')
    if (last?.route === '/new') {
      await api.post('/api/session/last', { route: '', label: '' })
    }
  } catch { /* ignore */ }
}
