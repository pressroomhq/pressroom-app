import { useState, useEffect, useCallback } from 'react'

const API = '/api/auth'

export default function AdminUsers({ orgs = [] }) {
  const [tab, setTab] = useState('users') // users | requests
  const [users, setUsers] = useState([])
  const [requests, setRequests] = useState([])
  const [loading, setLoading] = useState(true)
  const [inviteLink, setInviteLink] = useState(null) // { email, link }

  // New user form
  const [showAdd, setShowAdd] = useState(false)
  const [newEmail, setNewEmail] = useState('')
  const [newName, setNewName] = useState('')
  const [newAdmin, setNewAdmin] = useState(false)
  const [newOrgIds, setNewOrgIds] = useState([])
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState('')

  const fetchUsers = useCallback(async () => {
    const res = await fetch(`${API}/admin/users`)
    const data = await res.json()
    setUsers(Array.isArray(data) ? data : [])
  }, [])

  const fetchRequests = useCallback(async () => {
    const res = await fetch(`${API}/admin/requests`)
    const data = await res.json()
    setRequests(Array.isArray(data) ? data : [])
  }, [])

  useEffect(() => {
    Promise.all([fetchUsers(), fetchRequests()]).then(() => setLoading(false))
  }, [fetchUsers, fetchRequests])

  const pendingCount = requests.filter(r => r.status === 'pending').length

  const createUser = async () => {
    if (!newEmail.trim()) return
    setAdding(true)
    setAddError('')
    try {
      const res = await fetch(`${API}/admin/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: newEmail, name: newName, is_admin: newAdmin, org_ids: newOrgIds }),
      })
      const data = await res.json()
      if (!res.ok) {
        setAddError(data.detail || 'Failed to create user.')
      } else {
        setInviteLink({ email: newEmail, link: data.invite_link })
        setNewEmail('')
        setNewName('')
        setNewAdmin(false)
        setNewOrgIds([])
        setShowAdd(false)
        fetchUsers()
      }
    } catch {
      setAddError('Connection error.')
    }
    setAdding(false)
  }

  const reinvite = async (userId, email) => {
    const res = await fetch(`${API}/admin/users/${userId}/reinvite`, { method: 'POST' })
    const data = await res.json()
    if (res.ok) {
      setInviteLink({ email, link: data.invite_link })
    }
  }

  const deleteUser = async (userId) => {
    if (!confirm('Delete this user?')) return
    await fetch(`${API}/admin/users/${userId}`, { method: 'DELETE' })
    fetchUsers()
  }

  const approveRequest = async (reqId, email) => {
    const res = await fetch(`${API}/admin/requests/${reqId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ org_ids: [] }),
    })
    const data = await res.json()
    if (res.ok) {
      setInviteLink({ email, link: data.invite_link })
      fetchRequests()
      fetchUsers()
    }
  }

  const rejectRequest = async (reqId) => {
    await fetch(`${API}/admin/requests/${reqId}/reject`, { method: 'POST' })
    fetchRequests()
  }

  const toggleOrgId = (id) => {
    setNewOrgIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  if (loading) return <div className="settings-page"><p style={{ color: 'var(--text-dim)' }}>Loading...</p></div>

  return (
    <div className="settings-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 className="settings-title" style={{ margin: 0 }}>Access Control</h2>
        <button className="btn btn-approve" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? 'Cancel' : '+ Add User'}
        </button>
      </div>

      {/* Invite link toast */}
      {inviteLink && (
        <div style={{
          padding: '12px 16px', marginBottom: 16,
          border: '1px solid var(--accent)',
          background: 'var(--bg-card)',
          fontSize: 12,
        }}>
          <div style={{ marginBottom: 6, color: 'var(--text)' }}>
            Invite link for <strong>{inviteLink.email}</strong> — copy and send manually:
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <code style={{
              flex: 1, fontSize: 11, padding: '4px 8px',
              background: 'var(--bg)', border: '1px solid var(--border)',
              wordBreak: 'break-all', color: 'var(--accent)',
            }}>
              {window.location.origin}{inviteLink.link}
            </code>
            <button
              className="btn"
              style={{ fontSize: 10, padding: '4px 10px', whiteSpace: 'nowrap' }}
              onClick={() => navigator.clipboard.writeText(`${window.location.origin}${inviteLink.link}`)}
            >
              Copy
            </button>
            <button
              style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 16 }}
              onClick={() => setInviteLink(null)}
            >&times;</button>
          </div>
        </div>
      )}

      {/* Add user form */}
      {showAdd && (
        <div style={{
          padding: '14px 16px', marginBottom: 16,
          border: '1px solid var(--border)',
          background: 'var(--bg-card)',
        }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
            <input
              className="setting-input"
              placeholder="Email *"
              type="email"
              value={newEmail}
              onChange={e => setNewEmail(e.target.value)}
              style={{ flex: '1 1 200px', fontSize: 12 }}
            />
            <input
              className="setting-input"
              placeholder="Name"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              style={{ flex: '1 1 160px', fontSize: 12 }}
            />
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-dim)', cursor: 'pointer' }}>
              <input type="checkbox" checked={newAdmin} onChange={e => setNewAdmin(e.target.checked)} />
              Admin
            </label>
          </div>
          {orgs.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 6, letterSpacing: 1 }}>GRANT ORG ACCESS</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {orgs.map(o => (
                  <label key={o.id} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={newOrgIds.includes(o.id)}
                      onChange={() => toggleOrgId(o.id)}
                    />
                    {o.name || o.domain}
                  </label>
                ))}
              </div>
            </div>
          )}
          {addError && <div style={{ fontSize: 11, color: 'var(--error)', marginBottom: 8 }}>{addError}</div>}
          <button className="btn btn-approve" onClick={createUser} disabled={adding || !newEmail.trim()}>
            {adding ? 'Creating...' : 'Create & Generate Invite Link'}
          </button>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '1px solid var(--border)' }}>
        {[
          { key: 'users', label: `Users (${users.length})` },
          { key: 'requests', label: `Requests${pendingCount > 0 ? ` (${pendingCount} pending)` : ''}` },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            style={{
              padding: '6px 16px',
              background: 'none',
              border: 'none',
              borderBottom: tab === t.key ? '2px solid var(--accent)' : '2px solid transparent',
              color: tab === t.key ? 'var(--accent)' : 'var(--text-dim)',
              cursor: 'pointer',
              fontSize: 11,
              letterSpacing: 1,
              fontFamily: 'var(--font-mono)',
            }}
          >
            {t.label.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Users list */}
      {tab === 'users' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {users.length === 0 ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 12 }}>No users yet.</p>
          ) : users.map(u => (
            <div key={u.id} style={{
              padding: '10px 14px',
              border: '1px solid var(--border)',
              background: 'var(--bg-card)',
              display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
            }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{u.email}</div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
                  {u.name && <span style={{ marginRight: 8 }}>{u.name}</span>}
                  {u.is_admin && <span style={{ color: 'var(--accent)', marginRight: 8 }}>ADMIN</span>}
                  <span style={{ color: u.is_active ? 'var(--success, #4caf50)' : 'var(--text-dim)' }}>
                    {u.is_active ? 'Active' : 'Pending invite'}
                  </span>
                  {u.orgs?.length > 0 && (
                    <span style={{ marginLeft: 8 }}>· {u.orgs.map(o => o.name).join(', ')}</span>
                  )}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                {!u.is_active && (
                  <button
                    className="btn"
                    style={{ fontSize: 10, padding: '3px 10px', color: 'var(--accent)', borderColor: 'var(--accent)' }}
                    onClick={() => reinvite(u.id, u.email)}
                  >
                    Resend Invite
                  </button>
                )}
                <button
                  className="btn"
                  style={{ fontSize: 10, padding: '3px 10px', color: 'var(--error)', borderColor: 'var(--error)' }}
                  onClick={() => deleteUser(u.id)}
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Requests list */}
      {tab === 'requests' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {requests.length === 0 ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 12 }}>No access requests.</p>
          ) : requests.map(r => (
            <div key={r.id} style={{
              padding: '10px 14px',
              border: `1px solid ${r.status === 'pending' ? 'var(--accent)' : 'var(--border)'}`,
              background: 'var(--bg-card)',
              display: 'flex', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap',
            }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{r.email}</div>
                {r.name && <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 1 }}>{r.name}</div>}
                {r.reason && (
                  <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4, fontStyle: 'italic' }}>
                    "{r.reason}"
                  </div>
                )}
                <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 4 }}>
                  {new Date(r.created_at).toLocaleDateString()} ·{' '}
                  <span style={{
                    color: r.status === 'pending' ? 'var(--accent)' : r.status === 'approved' ? 'var(--success, #4caf50)' : 'var(--error)'
                  }}>
                    {r.status.toUpperCase()}
                  </span>
                </div>
              </div>
              {r.status === 'pending' && (
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    className="btn btn-approve"
                    style={{ fontSize: 10, padding: '3px 12px' }}
                    onClick={() => approveRequest(r.id, r.email)}
                  >
                    Approve
                  </button>
                  <button
                    className="btn"
                    style={{ fontSize: 10, padding: '3px 10px', color: 'var(--error)', borderColor: 'var(--error)' }}
                    onClick={() => rejectRequest(r.id)}
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
