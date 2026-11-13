import { api } from '../api'

export async function saveLastSession(payload) {
  const data = { ...payload, at: new Date().toISOString() }
  await api.post('/api/session/last', data)
}

export async function loadLastSession() {
  try {
    return await api.get('/api/session/last')
  } catch {
    return null
  }
}
