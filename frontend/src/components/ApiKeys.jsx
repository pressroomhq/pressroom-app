import { useState, useEffect, useCallback } from 'react'
import { orgHeaders } from '../api'

const API = '/api/auth'

export default function ApiKeys({ orgId, orgs = [] }) {
  const [keys, setKeys] = useState([])
  const [loading, setLoading] = useState(true)

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [newOrgId, setNewOrgId] = useState(orgId || (orgs[0]?.id ?? ''))
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  // Newly created token (shown once)
  const [createdToken, setCreatedToken] = useState(null)
  const [copied, setCopied] = useState(false)

  const fetchKeys = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api-keys`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      setKeys(Array.isArray(data) ? data : [])
    } catch {
      setKeys([])
    }
  }, [orgId])

  useEffect(() => {
    fetchKeys().then(() => setLoading(false))
  }, [fetchKeys])

  // Update default org when orgId prop changes
  useEffect(() => {
    if (orgId) setNewOrgId(orgId)
  }, [orgId])

  const orgName = (id) => {
    const org = orgs.find(o => o.id === id)
    return org ? (org.name || org.domain) : `Org #${id}`
  }

  const createKey = async () => {
    if (!newOrgId) return
    setCreating(true)
    setCreateError('')
    setCreatedToken(null)
    setCopied(false)
    try {
      const res = await fetch(`${API}/api-keys`, {
        method: 'POST',
        headers: orgHeaders(newOrgId),
        body: JSON.stringify({ label: newLabel || 'default', org_id: Number(newOrgId) }),
      })
      const data = await res.json()
      if (!res.ok) {
        setCreateError(data.detail || 'Failed to create API key.')
      } else {
        setCreatedToken(data.token)
        setNewLabel('')
        setShowCreate(false)
        fetchKeys()
      }
    } catch {
      setCreateError('Connection error.')
    }
    setCreating(false)
  }

  const revokeKey = async (keyId) => {
    if (!confirm('Revoke this API key? Any integrations using it will stop working.')) return
    try {
      await fetch(`${API}/api-keys/${keyId}`, {
        method: 'DELETE',
        headers: orgHeaders(orgId),
      })
      fetchKeys()
    } catch {
      // silently fail
    }
  }

  const copyToken = () => {
    if (createdToken) {
      navigator.clipboard.writeText(createdToken)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  if (loading) return <div className="settings-page"><p style={{ color: 'var(--text-dim)' }}>Loading...</p></div>

  return (
    <div className="settings-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 className="settings-title" style={{ margin: 0 }}>API Keys</h2>
        <button className="btn btn-approve" onClick={() => { setShowCreate(!showCreate); setCreateError(''); setCreatedToken(null) }}>
          {showCreate ? 'Cancel' : '+ New API Key'}
        </button>
      </div>

      <p style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 16, lineHeight: 1.5 }}>
        API keys provide programmatic access to the Pressroom API and MCP server.
        Each key is scoped to an organization. Treat keys like passwords.
      </p>

      {/* Newly created token — shown once */}
      {createdToken && (
        <div style={{
          padding: '12px 16px', marginBottom: 16,
          border: '1px solid var(--accent)',
          background: 'var(--bg-card)',
          fontSize: 12,
        }}>
          <div style={{ marginBottom: 6, color: 'var(--text)', fontWeight: 600 }}>
            API key created -- copy it now, it will not be shown again.
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <code style={{
              flex: 1, fontSize: 11, padding: '6px 8px',
              background: 'var(--bg)', border: '1px solid var(--border)',
              wordBreak: 'break-all', color: 'var(--accent)',
              fontFamily: 'var(--font-mono)',
            }}>
              {createdToken}
            </code>
            <button
              className="btn"
              style={{ fontSize: 10, padding: '4px 12px', whiteSpace: 'nowrap' }}
              onClick={copyToken}
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
            <button
              style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 16 }}
              onClick={() => setCreatedToken(null)}
            >&times;</button>
          </div>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div style={{
          padding: '14px 16px', marginBottom: 16,
          border: '1px solid var(--border)',
          background: 'var(--bg-card)',
        }}>
          <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 10, letterSpacing: 1 }}>CREATE API KEY</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
            <input
              className="setting-input"
              placeholder="Label (e.g. CI pipeline, MCP server)"
              value={newLabel}
              onChange={e => setNewLabel(e.target.value)}
              style={{ flex: '1 1 200px', fontSize: 12 }}
            />
            <select
              className="setting-input"
              value={newOrgId}
              onChange={e => setNewOrgId(e.target.value)}
              style={{ flex: '0 1 200px', fontSize: 12 }}
            >
              {orgs.map(o => (
                <option key={o.id} value={o.id}>{o.name || o.domain}</option>
              ))}
            </select>
          </div>
          {createError && <div style={{ fontSize: 11, color: 'var(--error)', marginBottom: 8 }}>{createError}</div>}
          <button className="btn btn-approve" onClick={createKey} disabled={creating || !newOrgId}>
            {creating ? 'Creating...' : 'Create Key'}
          </button>
        </div>
      )}

      {/* Keys list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {keys.length === 0 ? (
          <p style={{ color: 'var(--text-dim)', fontSize: 12 }}>No API keys yet. Create one to get started.</p>
        ) : keys.map(k => (
          <div key={k.id} style={{
            padding: '10px 14px',
            border: '1px solid var(--border)',
            background: 'var(--bg-card)',
            display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
          }}>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 12, fontWeight: 600 }}>
                {k.label}
                <span style={{ marginLeft: 8, fontWeight: 400, color: 'var(--text-dim)', fontSize: 11 }}>
                  {orgName(k.org_id)}
                </span>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2, fontFamily: 'var(--font-mono)' }}>
                {k.token_prefix}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 3 }}>
                Created {k.created_at ? new Date(k.created_at).toLocaleDateString() : 'unknown'}
                {k.last_used_at && (
                  <span> · Last used {new Date(k.last_used_at).toLocaleDateString()}</span>
                )}
              </div>
            </div>
            <button
              className="btn"
              style={{ fontSize: 10, padding: '3px 10px', color: 'var(--error)', borderColor: 'var(--error)' }}
              onClick={() => revokeKey(k.id)}
            >
              Revoke
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
