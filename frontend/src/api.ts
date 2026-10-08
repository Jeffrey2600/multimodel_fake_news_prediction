import type { HistoryRow, Report, StepEvent, User } from './types'

function clientId(): string {
  try {
    let id = localStorage.getItem('tl-client')
    if (!id) {
      id = crypto.randomUUID()
      localStorage.setItem('tl-client', id)
    }
    return id
  } catch {
    return 'ephemeral'
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem('tl-token')
  } catch {
    return null
  }
}

export function setToken(t: string | null) {
  try {
    if (t) localStorage.setItem('tl-token', t)
    else localStorage.removeItem('tl-token')
  } catch {
    /* storage unavailable: session-only sign-in */
  }
}

function headers(extra: Record<string, string> = {}) {
  const h: Record<string, string> = { 'X-Client-Id': clientId(), ...extra }
  const t = getToken()
  if (t) h.Authorization = `Bearer ${t}`
  return h
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(path, { ...init, headers: headers(init.headers as Record<string, string>) })
  if (!r.ok) {
    let msg = `Request failed (${r.status})`
    try {
      const j = await r.json()
      msg = typeof j.detail === 'string' ? j.detail : j.detail?.[0]?.msg ?? msg
    } catch {
      /* not json */
    }
    throw new Error(msg)
  }
  return r.json()
}

export type VerifyInput =
  | { kind: 'text'; text: string }
  | { kind: 'url'; url: string }
  | { kind: 'file'; file: File }

export async function verify(
  input: VerifyInput,
  onStep: (e: StepEvent) => void,
  signal?: AbortSignal,
): Promise<Report> {
  const fd = new FormData()
  fd.append('kind', input.kind)
  if (input.kind === 'text') fd.append('text', input.text)
  if (input.kind === 'url') fd.append('url', input.url)
  if (input.kind === 'file') fd.append('file', input.file)

  const r = await fetch('/api/verify', { method: 'POST', body: fd, headers: headers(), signal })
  if (!r.ok || !r.body) {
    let msg = `The check couldn't start (${r.status}).`
    try {
      msg = (await r.json()).detail ?? msg
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim()
      buf = buf.slice(i + 1)
      if (!line) continue
      const ev = JSON.parse(line)
      if (ev.type === 'step') onStep(ev)
      else if (ev.type === 'report') return ev.report as Report
      else if (ev.type === 'error') throw new Error(ev.message)
    }
  }
  throw new Error('The connection closed before the result arrived. Try again.')
}

export const api = {
  status: () => req<{ grounding: boolean; models: string[]; newsapi: boolean; whisper: string; nli: string }>('/api/status'),
  history: () => req<HistoryRow[]>('/api/history'),
  clearHistory: () => req<{ deleted: number }>('/api/history', { method: 'DELETE' }),
  get: (id: string) => req<Report>(`/api/verifications/${id}`),
  remove: (id: string) => req<{ ok: boolean }>(`/api/verifications/${id}`, { method: 'DELETE' }),
  share: (id: string) => req<{ share_id: string }>(`/api/verifications/${id}/share`, { method: 'POST' }),
  shared: (sid: string) => req<Report>(`/api/shared/${sid}`),
  login: (email: string, password: string) =>
    req<{ token: string; user: User }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
      headers: { 'Content-Type': 'application/json' },
    }),
  register: (name: string, email: string, password: string) =>
    req<{ token: string; user: User }>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ name, email, password }),
      headers: { 'Content-Type': 'application/json' },
    }),
  me: () => req<User>('/api/auth/me'),
}
