import { useState } from 'react'
import { orgHeaders } from '../api'

const API = '/api'

const CATEGORIES = [
  { value: 'feature_request', label: 'Feature Request' },
  { value: 'bug', label: 'Bug / Issue' },
  { value: 'incorrect_scan', label: 'Incorrect Scanning' },
  { value: 'content_quality', label: 'Content Quality' },
  { value: 'ui_ux', label: 'UI / UX' },
  { value: 'general', label: 'General Feedback' },
]

export default function Feedback({ orgId, currentView }) {
  const [category, setCategory] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    if (!category || !message.trim()) return
    setSending(true)
    setError('')
    try {
      const res = await fetch(`${API}/feedback`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ category, message: message.trim(), page: currentView || '' }),
      })
      if (res.ok) {
        setSent(true)
        setCategory('')
        setMessage('')
      } else {
        const data = await res.json()
        setError(data.detail || 'Failed to send feedback.')
      }
    } catch {
      setError('Connection error.')
    }
    setSending(false)
  }

  return (
    <div className="settings-page">
      <h2 className="settings-title">Feedback</h2>
      <p style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 24, lineHeight: 1.6 }}>
        Help us improve Pressroom. Tell us what's working, what's broken, or what you'd like to see next.
      </p>

      {sent ? (
        <div style={{ padding: '32px 0', textAlign: 'center' }}>
          <div style={{ fontSize: 14, color: 'var(--accent)', marginBottom: 12, fontWeight: 600 }}>
            Feedback received — thank you!
          </div>
          <p style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 20 }}>
            We review every submission. Your input directly shapes what we build next.
          </p>
          <button className="btn btn-approve" onClick={() => setSent(false)}>
            Send More Feedback
          </button>
        </div>
      ) : (
        <>
          <div className="setting-field" style={{ marginBottom: 16 }}>
            <label className="setting-label">Category</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {CATEGORIES.map(c => (
                <button
                  key={c.value}
                  className={`btn ${category === c.value ? 'btn-approve' : ''}`}
                  style={{
                    fontSize: 11,
                    padding: '6px 12px',
                    borderColor: category === c.value ? 'var(--accent)' : 'var(--border)',
                    color: category === c.value ? 'var(--accent)' : 'var(--text-dim)',
                  }}
                  onClick={() => setCategory(c.value)}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>

          <div className="setting-field" style={{ marginBottom: 20 }}>
            <label className="setting-label">Message</label>
            <textarea
              className="setting-input"
              style={{ width: '100%', minHeight: 120, fontSize: 13, resize: 'vertical' }}
              value={message}
              onChange={e => setMessage(e.target.value)}
              placeholder="Describe what you're seeing, what you expected, or what you'd like..."
            />
          </div>

          {error && (
            <div style={{ fontSize: 11, color: 'var(--error)', marginBottom: 12 }}>{error}</div>
          )}

          <button
            className="btn btn-approve"
            onClick={submit}
            disabled={sending || !category || !message.trim()}
          >
            {sending ? 'Sending...' : 'Send Feedback'}
          </button>
        </>
      )}
    </div>
  )
}
