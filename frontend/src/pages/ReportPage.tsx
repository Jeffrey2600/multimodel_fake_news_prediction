import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api'
import ReportView from '../components/ReportView'
import { Back } from '../icons'
import type { Report } from '../types'
import { VERDICT } from '../verdicts'

export default function ReportPage({ shared = false }: { shared?: boolean }) {
  const { id = '', shareId = '' } = useParams()
  const { reports, toast } = useApp()
  const [r, setR] = useState<Report | null>(() => (shared ? null : reports.get(id) ?? null))
  const [err, setErr] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    if (r && (r.id === id || shared)) return
    setErr('')
    const p = shared ? api.shared(shareId) : api.get(id)
    p.then((rep) => {
      if (!shared) reports.set(rep.id, rep)
      setR(rep)
    }).catch((e: Error) => setErr(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, shareId, shared])

  useEffect(() => {
    if (r) document.title = `${VERDICT[r.verdict].label} — TruthLens`
    return () => {
      document.title = 'TruthLens'
    }
  }, [r])

  async function share() {
    if (!r) return
    try {
      const sid = r.share_id || (await api.share(r.id)).share_id
      const link = `${location.origin}/s/${sid}`
      setR({ ...r, share_id: sid })
      reports.set(r.id, { ...r, share_id: sid })
      await navigator.clipboard.writeText(link).catch(() => window.prompt('Copy this link', link))
      toast('Share link copied')
    } catch (e) {
      toast((e as Error).message)
    }
  }

  async function remove() {
    if (!r || !window.confirm('Delete this check from your history?')) return
    await api.remove(r.id)
    reports.delete(r.id)
    toast('Check deleted')
    navigate('/history')
  }

  if (err)
    return (
      <p className="empty">
        {err} <Link to="/">Check something new</Link>
      </p>
    )
  if (!r) return <p className="empty">Loading the report…</p>

  return (
    <>
      <div className="report-bar">
        <Link to="/" className="btn small">
          <Back size={16} /> New check
        </Link>
        <span className="grow" />
        {!shared && (
          <button className="btn small" onClick={share}>
            Copy share link
          </button>
        )}
        <button className="btn small" onClick={() => window.print()}>
          Download PDF
        </button>
        {!shared && (
          <button className="linkish" onClick={remove}>
            Delete
          </button>
        )}
      </div>
      {shared && <p className="notice" style={{ marginBottom: 16 }}>Someone shared this fact-check with you.</p>}
      <ReportView key={r.id} r={r} />
    </>
  )
}
