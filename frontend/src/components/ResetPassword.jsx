import { useState } from 'react'
import { supabase } from '../supabaseClient'

export default function ResetPassword({ onDone }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (password !== confirm) { setError('Passwords do not match.'); return }
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return }
    setLoading(true)
    const { error: err } = await supabase.auth.updateUser({ password })
    if (err) {
      setError(err.message)
    } else {
      setDone(true)
      setTimeout(() => onDone(), 2000)
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
            SET NEW PASSWORD
          </div>
        </div>

        {done ? (
          <div style={{ textAlign: 'center', fontSize: 13, color: 'var(--text-dim)' }}>
            Password updated. Redirecting...
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 12 }}>
              <input
                className="setting-input"
                type="password"
                placeholder="New password"
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
              {loading ? 'Saving...' : 'Set Password'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
