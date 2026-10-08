import { useState } from 'react'
import { Chevron } from '../icons'
import type { ClaimResult, Evidence, Report, Verdict } from '../types'
import { meterPosition, sureness, VERDICT } from '../verdicts'
import { VerdictChip } from './Ledger'

const TIER_LABEL: Record<string, string> = {
  official: 'Official source',
  factcheck: 'Fact-checker',
  wire: 'News agency',
  major: 'News outlet',
  reference: 'Reference',
  general: 'Website',
  social: 'Social media',
  unreliable: 'Unreliable site',
}

const KIND_LABEL: Record<string, string> = {
  text: 'The text you pasted',
  url: 'The article you linked',
  image: 'Text read from your image',
  document: 'Text from your document',
  audio: 'What was said in your recording',
  video: 'What was said in your video',
}

function fmtDate(d?: string) {
  if (!d) return ''
  const t = new Date(d)
  return isNaN(t.getTime()) ? d : t.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function TruthMeter({ v, confidence, mini = false }: { v: Verdict; confidence: number; mini?: boolean }) {
  const unknown = v === 'Insufficient'
  return (
    <div className={`truth-meter ${mini ? 'mini-meter' : ''} ${unknown ? 'unknown' : ''}`} aria-hidden>
      <div className="bar" />
      {!unknown && <span className="needle" style={{ left: `${meterPosition(v, confidence)}%` }} />}
      <div className="scale">
        <span>Fake</span>
        <span>{unknown ? 'Not enough evidence' : 'Half true'}</span>
        <span>Checks out</span>
      </div>
    </div>
  )
}

function SourceCard({ e }: { e: Evidence }) {
  const quote = e.quote || e.snippet
  return (
    <a className="source" href={e.url} target="_blank" rel="noopener noreferrer">
      <div className="src-top">
        <span className="pub">{e.publisher}</span>
        <span className="tier">{TIER_LABEL[e.tier] ?? e.tier}</span>
        {e.date && <span>{fmtDate(e.date)}</span>}
      </div>
      <div className="t">{e.title}</div>
      {quote && <q>{quote.length > 240 ? quote.slice(0, 237) + '…' : quote}</q>}
    </a>
  )
}

function ClaimCard({ c, open, onToggle, n }: { c: ClaimResult; open: boolean; onToggle: () => void; n: number }) {
  const against = c.evidence.filter((e) => e.stance === 'refutes')
  const forr = c.evidence.filter((e) => e.stance === 'supports')
  const other = c.evidence.filter((e) => e.stance === 'neutral')
  const facts = Object.entries(c.entities).flatMap(([k, vs]) => (vs ?? []).map((v) => [k, v] as const))
  const tone = VERDICT[c.verdict].tone
  return (
    <article className={`claim t-${tone} ${open ? 'open' : ''}`}>
      <button className="claim-head" onClick={onToggle} aria-expanded={open}>
        <span className="claim-no" aria-hidden>
          {n}
        </span>
        <div>
          <VerdictChip v={c.verdict} />
          <div className="ctext">
            <span className="sr-only">Claim {n}: </span>
            {c.text}
          </div>
        </div>
        <TruthMeter v={c.verdict} confidence={c.confidence} mini />
        <span className="chev">
          <Chevron size={24} />
        </span>
      </button>
      <div className="claim-body" hidden={!open}>
        <p>{c.explanation}</p>
        {c.discrepancies.length > 0 && (
          <ul className="discrepancy">
            {c.discrepancies.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        )}
        {facts.length > 0 && (
          <div className="facts" aria-label="Details we looked up">
            {facts.map(([k, v]) => (
              <span key={k + v}>
                <b>{k.replace(/s$/, '')}</b>
                {v}
              </span>
            ))}
          </div>
        )}
        <div className="ev-cols">
          <div className="ev-col t-bad">
            <h3>
              ✕ Sources that say it’s wrong <span className="n">{against.length}</span>
            </h3>
            {against.length ? against.map((e) => <SourceCard key={e.id} e={e} />) : <div className="none">None found.</div>}
          </div>
          <div className="ev-col t-ok">
            <h3>
              ✓ Sources that back it up <span className="n">{forr.length}</span>
            </h3>
            {forr.length ? forr.map((e) => <SourceCard key={e.id} e={e} />) : <div className="none">None found.</div>}
          </div>
        </div>
        {other.length > 0 && (
          <details className="more-sources">
            <summary>
              {other.length} more source{other.length > 1 ? 's' : ''} we read that didn’t settle it either way
            </summary>
            <ul className="neutral-list">
              {other.map((e) => (
                <li key={e.id}>
                  <a href={e.url} target="_blank" rel="noopener noreferrer">
                    {e.publisher} — {e.title}
                  </a>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </article>
  )
}

function Lens({ icon, title, sub, items, nil }: { icon: string; title: string; sub: string; items: string[]; nil: string }) {
  return (
    <div className="lens">
      <div className="l-ic" aria-hidden>
        {icon}
      </div>
      <h3>{title}</h3>
      <p className="l-sub">{sub}</p>
      {items.length ? (
        <ul>
          {items.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      ) : (
        <div className="nil">✓ {nil}</div>
      )}
    </div>
  )
}

export default function ReportView({ r }: { r: Report }) {
  const [open, setOpen] = useState<Record<number, boolean>>(() => ({ 0: true }) as Record<number, boolean>)
  const d = VERDICT[r.verdict]
  const uniqueSources = new Set(r.claims.flatMap((c) => c.evidence.map((e) => e.url)))
  const all = r.claims.flatMap((c) => c.evidence)
  const nFor = all.filter((e) => e.stance === 'supports').length
  const nAgainst = all.filter((e) => e.stance === 'refutes').length
  const multi = r.claims.length > 1
  const rows = r.claims.flatMap((c, i) => c.evidence.map((e) => ({ ...e, ci: i + 1 })))
  const created = new Date(r.created_at)
  const meta = r.input.meta || {}

  return (
    <>
      <div className="print-head">
        TruthLens fact-check report · {r.id} · {created.toLocaleString()}
      </div>

      <section className={`banner t-${d.tone}`}>
        <div>
          <div className="verdict-top">
            <span className="badge" aria-hidden>
              {d.icon}
            </span>
            <span className="eyebrow">Our verdict</span>
          </div>
          <div className="verdict-word" role="heading" aria-level={1}>
            {d.label}
          </div>
          <p className="verdict-line">{d.line}</p>
        </div>
        <div className="meter-box">
          <div className="sure">
            {r.verdict === 'Insufficient' ? 'We couldn’t decide' : sureness(r.confidence)}
            <small>Confidence {r.confidence}% · checked {created.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })}</small>
          </div>
          <TruthMeter v={r.verdict} confidence={r.confidence} />
          <div className="counts">
            <div>
              <b>{r.claims.length}</b>
              <span>{r.claims.length === 1 ? 'claim checked' : 'claims checked'}</span>
            </div>
            <div>
              <b>{uniqueSources.size}</b>
              <span>sources read</span>
            </div>
            <div>
              <b>
                <span style={{ color: 'var(--bad)' }}>{nAgainst}</span>
                {' / '}
                <span style={{ color: 'var(--ok)' }}>{nFor}</span>
              </b>
              <span>say wrong / back it</span>
            </div>
          </div>
        </div>
      </section>

      {r.degraded && (
        <p className="notice" style={{ marginTop: 18 }}>
          {typeof r.degraded === 'string'
            ? r.degraded
            : 'Made with the offline engine because the AI service was unavailable. Treat this verdict as indicative.'}
        </p>
      )}

      <section className="split">
        <div className="checked-box">
          <div className="eyebrow">{KIND_LABEL[r.input.kind] ?? 'What you sent'}</div>
          <p>“{r.summary || r.input.text.slice(0, 280)}”</p>
          {(meta.publisher || meta.date) && (
            <div className="src-meta">
              {meta.publisher}
              {meta.date ? ` · published ${fmtDate(meta.date)}` : ''}
            </div>
          )}
        </div>
        <div className="why">
          <h2>Why we say this</h2>
          <p>{r.explanation}</p>
        </div>
      </section>

      <section className="block">
        <div className="block-head">
          <h2>{multi ? `We found ${r.claims.length} separate claims` : 'The claim, in detail'}</h2>
          <p>{multi ? 'Each one is checked on its own. Tap a claim to see the sources.' : 'Tap to show or hide the sources.'}</p>
        </div>
        {r.claims.map((c, i) => (
          <ClaimCard key={i} n={i + 1} c={c} open={!!open[i]} onToggle={() => setOpen((o) => ({ ...o, [i]: !o[i] }))} />
        ))}
      </section>

      <section className="block">
        <div className="block-head">
          <h2>Things to watch out for</h2>
          <p>How the message is written, apart from whether its facts are right.</p>
        </div>
        <div className="lenses">
          <Lens icon="🧩" title="Missing context" sub="What changes the meaning if you know it" items={r.context_gaps} nil="Nothing important missing." />
          <Lens icon="📣" title="Slanted language" sub="Emotional, pushy or one-sided wording" items={r.bias_indicators} nil="Wording looks neutral." />
          <Lens icon="🔍" title="What’s not said" sub="Dates, names or sources left out" items={r.missing_information} nil="Key details are there." />
        </div>
      </section>

      <section className="block">
        <div className="block-head">
          <h2>Every source we read</h2>
          <p>{uniqueSources.size} sources, and what each one says about {multi ? 'each numbered claim' : 'the claim'}.</p>
        </div>
        <div className="table-wrap">
          <table className="src-table">
            <thead>
              <tr>
                {multi && <th>Claim</th>}
                <th>Source</th>
                <th>Type</th>
                <th>Date</th>
                <th>Says</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.ci + e.url}>
                  {multi && <td className="sm">#{e.ci}</td>}
                  <td>
                    <a href={e.url} target="_blank" rel="noopener noreferrer">
                      <b>{e.publisher}</b> — {e.title}
                    </a>
                  </td>
                  <td className="sm">{TIER_LABEL[e.tier] ?? e.tier}</td>
                  <td className="sm">{fmtDate(e.date) || '—'}</td>
                  <td>
                    {e.stance === 'supports' ? (
                      <VerdictChip v="Supported" />
                    ) : e.stance === 'refutes' ? (
                      <span className="chip-v t-bad">
                        <span className="ic">✕</span>Wrong
                      </span>
                    ) : (
                      <span className="sm">Background only</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="block">
        <div className="block-head">
          <h2>How we checked</h2>
        </div>
        <dl className="method-notes">
          <dt>You sent</dt>
          <dd>
            {r.input.label}
            {r.input.notes?.length ? <div style={{ color: 'var(--ink-2)' }}>{r.input.notes.join(' ')}</div> : null}
          </dd>
          {meta.visual && (
            <>
              <dt>In the image</dt>
              <dd>{meta.visual}</dd>
            </>
          )}
          <dt>Claims found by</dt>
          <dd>{r.engines.claims}</dd>
          <dt>Evidence judged by</dt>
          <dd>{r.engines.analysis}</dd>
          <dt>We searched for</dt>
          <dd>{[...new Set(r.claims.flatMap((c) => c.queries))].join(' · ')}</dd>
          <dt>Time taken</dt>
          <dd>{r.elapsed} seconds</dd>
        </dl>
        {r.input.kind !== 'text' && (
          <details className="more-sources">
            <summary>Show the full text we extracted</summary>
            <p style={{ whiteSpace: 'pre-wrap', fontSize: 17, color: 'var(--ink-2)' }}>{r.input.text}</p>
          </details>
        )}
      </section>
    </>
  )
}
