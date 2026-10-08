import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api'
import Cards from '../components/Ledger'
import type { HistoryRow } from '../types'
import { VERDICT } from '../verdicts'

const FILTERS = ['All', 'Supported', 'Contradicted', 'Mixed', 'Insufficient'] as const

export default function History() {
  const { user, toast } = useApp()
  const [rows, setRows] = useState<HistoryRow[] | null>(null)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('All')
  const [q, setQ] = useState('')

  useEffect(() => {
    api.history().then(setRows).catch((e: Error) => setErr(e.message))
  }, [user])

  const shown = useMemo(
    () =>
      (rows ?? []).filter(
        (r) => (filter === 'All' || r.verdict === filter) && r.input_content.toLowerCase().includes(q.toLowerCase()),
      ),
    [rows, filter, q],
  )

  async function del(id: string) {
    await api.remove(id)
    setRows((r) => r?.filter((x) => x.verification_id !== id) ?? null)
    toast('Check deleted')
  }

  async function clearAll() {
    if (!window.confirm('Delete your entire check history? This can’t be undone.')) return
    const { deleted } = await api.clearHistory()
    setRows([])
    toast(`Deleted ${deleted} check${deleted === 1 ? '' : 's'}`)
  }

  return (
    <>
      <h1 className="page-title">History</h1>
      <p className="page-lede">
        {user
          ? 'Every check made while signed in, on any device.'
          : 'Checks made in this browser. Sign in to keep them across devices.'}
      </p>
      {err && <div className="error">{err}</div>}
      {rows && rows.length > 0 && (
        <div className="filters">
          <input
            className="field"
            style={{ maxWidth: 320, padding: '10px 16px', fontSize: 17 }}
            placeholder="Search your checks"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label="Search history"
          />
          {FILTERS.map((f) => (
            <button key={f} className="pill" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f === 'All' ? 'All' : VERDICT[f].label}
            </button>
          ))}
          <span style={{ flex: 1 }} />
          <button className="linkish" onClick={clearAll}>
            Clear history
          </button>
        </div>
      )}
      {rows === null && !err && <p className="empty">Loading…</p>}
      {rows && rows.length === 0 && (
        <p className="empty">
          Nothing checked yet. <Link to="/">Check your first claim</Link>
        </p>
      )}
      {rows && rows.length > 0 && shown.length === 0 && <p className="empty">No checks match that filter.</p>}
      {shown.length > 0 && <Cards rows={shown} onDelete={del} />}
    </>
  )
}
