import { Link } from 'react-router-dom'
import type { HistoryRow, Verdict } from '../types'
import { VERDICT } from '../verdicts'

export function VerdictChip({ v, big = false }: { v: Verdict | null; big?: boolean }) {
  if (!v)
    return (
      <span className={`chip-v t-na ${big ? 'big' : ''}`}>
        <span className="ic">!</span>Didn’t finish
      </span>
    )
  const d = VERDICT[v]
  return (
    <span className={`chip-v t-${d.tone} ${big ? 'big' : ''}`}>
      <span className="ic" aria-hidden>
        {d.icon}
      </span>
      {d.label}
    </span>
  )
}

export function when(iso: string) {
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

const KIND: Record<string, string> = {
  text: 'Text',
  url: 'News link',
  image: 'Screenshot',
  document: 'Document',
  audio: 'Voice',
  video: 'Video',
}

export default function Cards({ rows, onDelete }: { rows: HistoryRow[]; onDelete?: (id: string) => void }) {
  return (
    <div className="cards">
      {rows.map((r) => {
        const done = r.status === 'completed'
        const tone = done && r.verdict ? VERDICT[r.verdict].tone : 'na'
        return (
          <Link key={r.verification_id} to={done ? `/r/${r.verification_id}` : '#'} className={`card t-${tone}`} style={{ borderTopColor: 'var(--c)' }}>
            <div>
              <VerdictChip v={done ? r.verdict : null} />
            </div>
            <div className="what">{r.input_content}</div>
            <div className="foot">
              <span>
                {KIND[r.input_type] ?? r.input_type} · {when(r.created_at)}
              </span>
              {onDelete && (
                <button
                  className="linkish del"
                  onClick={(e) => {
                    e.preventDefault()
                    onDelete(r.verification_id)
                  }}
                >
                  Delete
                </button>
              )}
            </div>
          </Link>
        )
      })}
    </div>
  )
}
