import { useState, useEffect } from 'react'
import { supabase } from '../supabaseClient'

export default function AcceptInvite({ token, onAccepted }) {
  const [status, setStatus] = useState('processing') // processing | done | error
  const [error, setError] = useState('')

  useEffect(() => {
    // Supabase invite links redirect with tokens in the URL hash
    // The supabase client auto-processes these on init
    // We just need to check if we have a session now
    const checkSession = async () => {
      const { data: { session }, error: sessionError } = await supabase.auth.getSession()
      if (session) {
        // Store token and redirect to app
        localStorage.setItem('pr_session', session.access_token)
        setStatus('done')
        setTimeout(() => onAccepted(), 1500)
      } else if (sessionError) {
        setError(sessionError.message)
        setStatus('error')
      } else {
        // No session from invite — try to verify the token from the URL
        setError('Invalid or expired invite link.')
        setStatus('error')
      }
    }
    checkSession()
  }, [token])

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

        {status === 'processing' && (
          <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: 12 }}>
            Processing invite...
          </div>
        )}

        {status === 'done' && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.6 }}>
              Welcome! Redirecting to app...
            </div>
          </div>
        )}

        {status === 'error' && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, color: 'var(--error)', marginBottom: 16 }}>
              {error || 'Something went wrong.'}
            </div>
            <a href="/" style={{ fontSize: 11, color: 'var(--accent)' }}>Back to login</a>
          </div>
        )}
      </div>
    </div>
  )
}
