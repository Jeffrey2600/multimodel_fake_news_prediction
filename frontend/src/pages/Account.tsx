import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../App'
import { api, setToken } from '../api'

export default function Account() {
  const { user, setUser, toast } = useApp()
  const [mode, setMode] = useState<'in' | 'up'>('in')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  if (user)
    return (
      <div className="auth">
        <h1>{user.name}</h1>
        <p style={{ color: 'var(--ink-2)', margin: 0 }}>{user.email}</p>
        <p style={{ fontSize: 14, color: 'var(--ink-2)' }}>Your check history is saved to this account.</p>
        <button
          className="btn"
          onClick={() => {
            setToken(null)
            setUser(null)
            toast('Signed out')
          }}
        >
          Sign out
        </button>
      </div>
    )

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr('')
    setBusy(true)
    try {
      const res = mode === 'in' ? await api.login(email, pw) : await api.register(name, email, pw)
      setToken(res.token)
      setUser(res.user)
      toast(mode === 'in' ? 'Signed in' : 'Account created')
      navigate('/history')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="auth" onSubmit={submit}>
      <h1>{mode === 'in' ? 'Sign in' : 'Create an account'}</h1>
      <p style={{ color: 'var(--ink-2)', fontSize: 14, margin: 0 }}>
        Optional. Checks you’ve already made in this browser move into your account.
      </p>
      {mode === 'up' && (
        <>
          <label htmlFor="name">Name</label>
          <input id="name" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
        </>
      )}
      <label htmlFor="email">Email</label>
      <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
      <label htmlFor="pw">Password</label>
      <input
        id="pw"
        type="password"
        value={pw}
        onChange={(e) => setPw(e.target.value)}
        required
        minLength={mode === 'up' ? 8 : 1}
        autoComplete={mode === 'in' ? 'current-password' : 'new-password'}
      />
      {mode === 'up' && <div style={{ fontSize: 13, color: 'var(--ink-3)', marginTop: 6 }}>At least 8 characters.</div>}
      {err && <div className="error">{err}</div>}
      <button className="btn primary" disabled={busy}>
        {busy ? 'One moment…' : mode === 'in' ? 'Sign in' : 'Create account'}
      </button>
      <div className="switch">
        {mode === 'in' ? 'New here? ' : 'Have an account? '}
        <button type="button" className="linkish" onClick={() => setMode(mode === 'in' ? 'up' : 'in')}>
          {mode === 'in' ? 'Create an account' : 'Sign in'}
        </button>
      </div>
    </form>
  )
}
