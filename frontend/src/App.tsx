import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { api, getToken, setToken, verify, type VerifyInput } from './api'
import { Logo, Moon, Sun } from './icons'
import Account from './pages/Account'
import History from './pages/History'
import Home from './pages/Home'
import Methodology from './pages/Methodology'
import ReportPage from './pages/ReportPage'
import type { Report, StepEvent, User } from './types'

export interface Run {
  subject: string
  steps: Partial<Record<StepEvent['step'], StepEvent>>
  error?: string
}

interface Ctx {
  user: User | null
  setUser: (u: User | null) => void
  grounding: boolean | null
  run: Run | null
  start: (input: VerifyInput, subject: string) => void
  cancel: () => void
  reports: Map<string, Report>
  toast: (msg: string) => void
}
const AppCtx = createContext<Ctx>(null!)
export const useApp = () => useContext(AppCtx)

type Theme = 'light' | 'dark'
function initialTheme(): Theme {
  const t = document.documentElement.dataset.theme
  if (t === 'light' || t === 'dark') return t
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [user, setUser] = useState<User | null>(null)
  const [grounding, setGrounding] = useState<boolean | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [toastMsg, setToastMsg] = useState('')
  const reports = useRef(new Map<string, Report>()).current
  const abort = useRef<AbortController | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    api.status().then((s) => setGrounding(s.models.length > 0)).catch(() => setGrounding(false))
    if (getToken()) api.me().then(setUser).catch(() => setToken(null))
  }, [])

  const flipTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    document.documentElement.dataset.theme = next
    try {
      localStorage.setItem('tl-theme', next)
    } catch {
      /* not persisted */
    }
  }

  const toast = useCallback((msg: string) => {
    setToastMsg(msg)
    window.setTimeout(() => setToastMsg(''), 2600)
  }, [])

  const start = useCallback(
    (input: VerifyInput, subject: string) => {
      abort.current?.abort()
      const ctl = new AbortController()
      abort.current = ctl
      setRun({ subject, steps: {} })
      navigate('/')
      verify(input, (e) => setRun((r) => (r ? { ...r, steps: { ...r.steps, [e.step]: e } } : r)), ctl.signal)
        .then((rep) => {
          reports.set(rep.id, rep)
          setRun(null)
          navigate(`/r/${rep.id}`)
        })
        .catch((e: Error) => {
          if (ctl.signal.aborted) return
          setRun((r) => (r ? { ...r, error: e.message } : r))
        })
    },
    [navigate, reports],
  )
  const cancel = useCallback(() => {
    abort.current?.abort()
    setRun(null)
  }, [])

  return (
    <AppCtx.Provider value={{ user, setUser, grounding, run, start, cancel, reports, toast }}>
      <header className="topbar">
        <Link to="/" className="brand" onClick={() => run?.error && cancel()}>
          <Logo />
          <span className="brand-name">TruthLens</span>
        </Link>
        {grounding !== null && (
          <span className={`live ${grounding ? '' : 'off'}`} title={grounding ? 'AI analysis connected' : 'Running on the offline engine'}>
            <i /> {grounding ? 'Live evidence' : 'Offline engine'}
          </span>
        )}
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end className="hide-sm">
            Check
          </NavLink>
          <NavLink to="/history">History</NavLink>
          <NavLink to="/methodology" className="hide-sm">
            Methodology
          </NavLink>
          <NavLink to="/account">{user ? user.name.split(' ')[0] : 'Sign in'}</NavLink>
          <button className="icon-btn" onClick={flipTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
            {theme === 'dark' ? <Sun /> : <Moon />}
          </button>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/r/:id" element={<ReportPage />} />
          <Route path="/s/:shareId" element={<ReportPage shared />} />
          <Route path="/history" element={<History />} />
          <Route path="/methodology" element={<Methodology />} />
          <Route path="/account" element={<Account />} />
          <Route path="*" element={<p className="empty">That page doesn't exist. <Link to="/">Check a claim</Link></p>} />
        </Routes>
      </main>
      <footer>
        TruthLens weighs published evidence; it can be wrong. Open the sources before you rely on a verdict.
      </footer>
      {toastMsg && (
        <div className="toast" role="status">
          {toastMsg}
        </div>
      )}
    </AppCtx.Provider>
  )
}
