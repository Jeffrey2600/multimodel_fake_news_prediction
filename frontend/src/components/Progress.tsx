import type { Run } from '../App'
import { useApp } from '../App'

const STEPS = [
  ['read', 'Read the input'],
  ['claims', 'Extract the claims'],
  ['evidence', 'Gather evidence'],
  ['analysis', 'Compare claims with sources'],
  ['verdict', 'Reach a verdict'],
] as const

export default function Progress({ run }: { run: Run }) {
  const { cancel } = useApp()
  return (
    <section className="progress" aria-live="polite">
      <h2>{run.error ? 'The check stopped' : 'Checking…'}</h2>
      <p className="subject">{run.subject}</p>
      <ol className={`steps ${run.error ? "halted" : ""}`}>
        {STEPS.map(([id, label]) => {
          const s = run.steps[id]
          return (
            <li key={id} className={s?.state ?? ''}>
              <div>
                <div className="label">{label}</div>
                {s?.detail && <div className="detail">{s.detail}</div>}
                {id === 'claims' && s?.claims && s.claims.length > 1 && (
                  <ul className="claims-found">
                    {s.claims.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          )
        })}
      </ol>
      {run.error ? (
        <>
          <div className="error" role="alert">
            {run.error}
          </div>
          <p>
            <button className="btn" onClick={cancel}>
              Edit and try again
            </button>
          </p>
        </>
      ) : (
        <button className="linkish" onClick={cancel}>
          Cancel
        </button>
      )}
    </section>
  )
}
