import { useState, useEffect } from 'react'

export default function AcceptInvite({ token, onAccepted }) {
  const [status, setStatus] = useState('checking') // checking | valid | used | expired | done | error
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetch(`/api/auth/invite/${token}`)
      .then(r => r.json())
      .then(data => {
        if (data.valid) {
          setEmail(data.email)
          setStatus('valid')
        } else {
          setStatus(data.reason || 'invalid')
        }
      })
      .catch(() => setStatus('error'))
  }, [token])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    setLoading(true)
    try {
      const res = await fetch('/api/auth/set-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, password }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail || 'Failed to set password.')
      } else {
        setStatus('done')
        setTimeout(() => onAccepted(), 2000)
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
        <div style={{ marginBottom: 28, textAlign: 'center' }}>
          <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: 2, color: 'var(--text)' }}>
            PRESSROOM
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 4, letterSpacing: 1 }}>
            ACCEPT INVITE
          </div>
        </div>

        {status === 'checking' && (
          <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: 12 }}>Checking invite...</div>
        )}

        {(status === 'used' || status === 'expired' || status === 'invalid' || status === 'error') && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, color: 'var(--error)', marginBottom: 16 }}>
              {status === 'used' && 'This invite link has already been used.'}
              {status === 'expired' && 'This invite link has expired. Ask for a new one.'}
              {(status === 'invalid' || status === 'error') && 'Invalid invite link.'}
            </div>
            <a href="/" style={{ fontSize: 11, color: 'var(--accent)' }}>Back to login</a>
          </div>
        )}

        {status === 'done' && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.6 }}>
              Password set. Redirecting to login...
            </div>
          </div>
        )}

        {status === 'valid' && (
          <form onSubmit={handleSubmit}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 16 }}>
              Setting password for <strong style={{ color: 'var(--text)' }}>{email}</strong>
            </div>
            <div style={{ marginBottom: 10 }}>
              <input
                className="setting-input"
                type="password"
                placeholder="Password (min 8 chars)"
                value={password}
                onChange={e => setPassword(e.target.value)}
                style={{ width: '100%', fontSize: 13 }}
                required
                autoFocus
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <input
                className="setting-input"
                type="password"
                placeholder="Confirm password"
                value={confirm}
                onChange={e => setConfirm(e.target.value)}
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
              disabled={loading || !password || !confirm}
              style={{ width: '100%' }}
            >
              {loading ? 'Setting password...' : 'Set Password & Activate Account'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
