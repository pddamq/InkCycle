import { api } from '../api'

/** 项目级 UI 草稿：仅存后端 SQLite */
export async function loadProjectDraft(pid, name) {
  try {
    const data = await api.get(`/api/projects/${pid}/drafts/${encodeURIComponent(name)}`)
    if (data && Object.keys(data).length) return data
  } catch { /* ignore */ }
  return null
}

export async function saveProjectDraft(pid, name, data) {
  const payload = { ...data, savedAt: new Date().toISOString() }
  await api.post(`/api/projects/${pid}/drafts/${encodeURIComponent(name)}`, payload)
  return payload
}

export async function clearProjectDraft(pid, name) {
  await api.del(`/api/projects/${pid}/drafts/${encodeURIComponent(name)}`)
}
