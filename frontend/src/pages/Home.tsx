import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApp } from '../App'
import { api } from '../api'
import Composer from '../components/Composer'
import Cards, { VerdictChip } from '../components/Ledger'
import Progress from '../components/Progress'
import type { HistoryRow } from '../types'

export default function Home() {
  const { run, grounding } = useApp()
  const [recent, setRecent] = useState<HistoryRow[] | null>(null)

  useEffect(() => {
    if (!run) api.history().then((h) => setRecent(h.slice(0, 6))).catch(() => setRecent([]))
  }, [run])

  if (run) return <Progress run={run} />

  return (
    <>
      <section className="home-hero">
        <h1>
          Check it <em>before</em> you forward it.
        </h1>
        <div>
          <p>
            Got a forwarded message, a viral screenshot or a news link you’re not sure about? Drop it here. We check
            every claim in it against real news and fact-checkers, and tell you in plain words.
          </p>
          <div className="legend" aria-label="The answers you can get">
            <VerdictChip v="Supported" />
            <VerdictChip v="Mixed" />
            <VerdictChip v="Contradicted" />
            <VerdictChip v="Insufficient" />
          </div>
        </div>
      </section>
      {grounding === false && (
        <p className="notice" style={{ marginBottom: 16 }}>
          The AI service isn’t reachable, so checks run on the offline engine. Results are only a rough guide.
        </p>
      )}
      <Composer />

      <ol className="how">
        <li>
          <b>We pull out the claims</b>
          <span>A long message is split into the separate facts it states.</span>
        </li>
        <li>
          <b>We look for evidence</b>
          <span>News sites, fact-checkers, official pages and Wikipedia are searched for each one.</span>
        </li>
        <li>
          <b>You get a clear answer</b>
          <span>With the sources that agree, the ones that don’t, and what to watch out for.</span>
        </li>
      </ol>

      {recent && recent.length > 0 && (
        <>
          <div className="section-head">
            <h2>Your recent checks</h2>
            <Link to="/history" className="linkish">
              See all
            </Link>
          </div>
          <Cards rows={recent} />
        </>
      )}
    </>
  )
}
