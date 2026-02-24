import { useState } from 'react'

export default function Login({ onLogin }) {
  const [view, setView] = useState('login') // login | request | sent
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleLogin = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || 'Login failed.')
      } else {
        localStorage.setItem('pr_session', data.token)
        localStorage.setItem('pr_user', JSON.stringify(data.user))
        localStorage.setItem('pr_orgs', JSON.stringify(data.orgs))
        onLogin(data)
      }
    } catch {
      setError('Connection error.')
    }
    setLoading(false)
  }

  const handleRequest = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/auth/request-access', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, name, reason }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || 'Request failed.')
      } else {
        setView('sent')
      }
    } catch {
      setError('Connection error.')
    }
    setLoading(false)
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bg)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: 'var(--font-mono)',
    }}>
      <div style={{
        width: '100%',
        maxWidth: 380,
        padding: '40px 32px',
        border: '1px solid var(--border)',
        background: 'var(--bg-card)',
      }}>
        {/* Header */}
        <div style={{ marginBottom: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: 2, color: 'var(--text)' }}>
            PRESSROOM
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 4, letterSpacing: 1 }}>
            {view === 'login' ? 'SIGN IN' : view === 'request' ? 'REQUEST ACCESS' : 'REQUEST SENT'}
          </div>
        </div>

        {view === 'sent' && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.6, marginBottom: 20 }}>
              Request received. We'll review it and send you an invite link.
            </div>
            <button className="btn btn-approve" style={{ width: '100%' }} onClick={() => setView('login')}>
              Back to Login
            </button>
          </div>
        )}

        {view === 'login' && (
          <form onSubmit={handleLogin}>
            <div style={{ marginBottom: 12 }}>
              <input
                className="setting-input"
                type="email"
                placeholder="Email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                style={{ width: '100%', fontSize: 13 }}
                required
                autoFocus
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <input
                className="setting-input"
                type="password"
                placeholder="Password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                style={{ width: '100%', fontSize: 13 }}
                required
              />
            </div>
            {error && (
              <div style={{ fontSize: 11, color: 'var(--error)', marginBottom: 12 }}>{error}</div>
            )}
            <button
              className="btn btn-approve"
              type="submit"
              disabled={loading}
              style={{ width: '100%', marginBottom: 12 }}
            >
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
            <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--text-dim)' }}>
              No account?{' '}
              <button
                type="button"
                onClick={() => { setView('request'); setError('') }}
                style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 11, padding: 0 }}
              >
                Request access
              </button>
            </div>
          </form>
        )}

        {view === 'request' && (
          <form onSubmit={handleRequest}>
            <div style={{ marginBottom: 10 }}>
              <input
                className="setting-input"
                type="email"
                placeholder="Email *"
                value={email}
                onChange={e => setEmail(e.target.value)}
                style={{ width: '100%', fontSize: 13 }}
                required
                autoFocus
              />
            </div>
            <div style={{ marginBottom: 10 }}>
              <input
                className="setting-input"
                placeholder="Name"
                value={name}
                onChange={e => setName(e.target.value)}
                style={{ width: '100%', fontSize: 13 }}
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <textarea
                className="setting-input"
                placeholder="What are you working on? (optional)"
                value={reason}
                onChange={e => setReason(e.target.value)}
                style={{ width: '100%', fontSize: 13, minHeight: 72, resize: 'vertical' }}
              />
            </div>
            {error && (
              <div style={{ fontSize: 11, color: 'var(--error)', marginBottom: 12 }}>{error}</div>
            )}
            <button
              className="btn btn-approve"
              type="submit"
              disabled={loading || !email}
              style={{ width: '100%', marginBottom: 12 }}
            >
              {loading ? 'Sending...' : 'Request Access'}
            </button>
            <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--text-dim)' }}>
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => { setView('login'); setError('') }}
                style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontSize: 11, padding: 0 }}
              >
                Sign in
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
