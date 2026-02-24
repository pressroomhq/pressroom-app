import { useState, useEffect, useCallback } from 'react'

const API = '/api'

export default function Team({ orgId }) {
  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)
  const [discovering, setDiscovering] = useState(false)
  const [discoverResult, setDiscoverResult] = useState(null)
  const [linkingGithub, setLinkingGithub] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [newMember, setNewMember] = useState({ name: '', title: '', bio: '', email: '', linkedin_url: '', github_username: '', expertise_tags: '' })
  const [editingId, setEditingId] = useState(null)
  const [editFields, setEditFields] = useState({})

  const headers = { 'Content-Type': 'application/json', ...(orgId ? { 'X-Org-Id': String(orgId) } : {}) }

  const fetchMembers = useCallback(async () => {
    try {
      const res = await fetch(`${API}/team`, { headers })
      const data = await res.json()
      setMembers(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [orgId])

  useEffect(() => { fetchMembers() }, [fetchMembers])

  const discover = async () => {
    setDiscovering(true)
    setDiscoverResult(null)
    try {
      const res = await fetch(`${API}/team/discover`, { method: 'POST', headers })
      const data = await res.json()
      setDiscoverResult(data)
      if (data.members?.length > 0 || data.saved > 0) {
        fetchMembers()
      }
    } catch (e) {
      setDiscoverResult({ error: e.message })
    }
    setDiscovering(false)
  }

  const addMember = async () => {
    if (!newMember.name.trim()) return
    const tags = newMember.expertise_tags
      ? newMember.expertise_tags.split(',').map(t => t.trim()).filter(Boolean)
      : []
    await fetch(`${API}/team`, {
      method: 'POST', headers,
      body: JSON.stringify({ ...newMember, expertise_tags: tags }),
    })
    setNewMember({ name: '', title: '', bio: '', email: '', linkedin_url: '', github_username: '', expertise_tags: '' })
    setShowAdd(false)
    fetchMembers()
  }

  const linkGithub = async () => {
    setLinkingGithub(true)
    setDiscoverResult(null)
    try {
      const res = await fetch(`${API}/team/link-github`, { method: 'POST', headers })
      const data = await res.json()
      if (data.error) {
        setDiscoverResult({ error: data.error })
      } else {
        setDiscoverResult({ message: data.message || `Linked ${data.linked || 0} members. Found ${data.github_members_found || 0} GitHub members.` })
        fetchMembers()
      }
    } catch (e) {
      setDiscoverResult({ error: e.message })
    }
    setLinkingGithub(false)
  }

  const startEdit = (member) => {
    setEditingId(member.id)
    setEditFields({
      name: member.name,
      title: member.title || '',
      linkedin_url: member.linkedin_url || '',
      github_username: member.github_username || '',
    })
  }

  const saveEdit = async (id) => {
    await fetch(`${API}/team/${id}`, {
      method: 'PUT', headers,
      body: JSON.stringify(editFields),
    })
    setEditingId(null)
    fetchMembers()
  }

  const deleteMember = async (id) => {
    await fetch(`${API}/team/${id}`, { method: 'DELETE', headers })
    fetchMembers()
  }

  if (loading) return <div className="settings-page"><p style={{ color: 'var(--text-dim)' }}>Loading team...</p></div>

  return (
    <div className="settings-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h2 className="settings-title" style={{ margin: 0 }}>Team Members</h2>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn btn-run" onClick={discover} disabled={discovering}>
            {discovering ? 'Discovering...' : 'Discover Team'}
          </button>
          <button className="btn" style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }} onClick={linkGithub} disabled={linkingGithub}>
            {linkingGithub ? 'Linking...' : 'Link GitHub'}
          </button>
          <button className="btn btn-approve" onClick={() => setShowAdd(!showAdd)}>
            {showAdd ? 'Cancel' : '+ Add Member'}
          </button>
        </div>
      </div>

      {discoverResult && (
        <div style={{
          padding: '10px 14px', marginBottom: 16,
          border: '1px solid var(--border)',
          background: 'var(--bg-card)',
          fontSize: 12, lineHeight: 1.5,
        }}>
          {discoverResult.error ? (
            <span style={{ color: 'var(--error)' }}>Discovery failed: {discoverResult.error}</span>
          ) : discoverResult.message ? (
            <span style={{ color: 'var(--text-dim)' }}>{discoverResult.message}</span>
          ) : (
            <span>
              Found {discoverResult.total_found} members — saved {discoverResult.saved}, skipped {discoverResult.skipped_duplicates} duplicates.
              {discoverResult.pages_checked?.length > 0 && (
                <span style={{ color: 'var(--text-dim)' }}> Checked: {discoverResult.pages_checked.join(', ')}</span>
              )}
            </span>
          )}
          <button
            style={{ marginLeft: 12, cursor: 'pointer', background: 'none', border: 'none', color: 'var(--text-dim)', fontSize: 14 }}
            onClick={() => setDiscoverResult(null)}
          >&times;</button>
        </div>
      )}

      {showAdd && (
        <div className="asset-add-form" style={{ flexWrap: 'wrap' }}>
          <input
            className="setting-input"
            placeholder="Name *"
            value={newMember.name}
            onChange={e => setNewMember(p => ({ ...p, name: e.target.value }))}
            style={{ flex: '1 1 180px' }}
          />
          <input
            className="setting-input"
            placeholder="Title"
            value={newMember.title}
            onChange={e => setNewMember(p => ({ ...p, title: e.target.value }))}
            style={{ flex: '1 1 180px' }}
          />
          <input
            className="setting-input"
            placeholder="Email"
            value={newMember.email}
            onChange={e => setNewMember(p => ({ ...p, email: e.target.value }))}
            style={{ flex: '1 1 180px' }}
          />
          <input
            className="setting-input"
            placeholder="LinkedIn URL"
            value={newMember.linkedin_url}
            onChange={e => setNewMember(p => ({ ...p, linkedin_url: e.target.value }))}
            style={{ flex: '1 1 220px' }}
          />
          <input
            className="setting-input"
            placeholder="GitHub username"
            value={newMember.github_username}
            onChange={e => setNewMember(p => ({ ...p, github_username: e.target.value }))}
            style={{ flex: '1 1 160px' }}
          />
          <input
            className="setting-input"
            placeholder="Expertise (comma-separated)"
            value={newMember.expertise_tags}
            onChange={e => setNewMember(p => ({ ...p, expertise_tags: e.target.value }))}
            style={{ flex: '1 1 240px' }}
          />
          <button className="btn btn-approve" onClick={addMember} disabled={!newMember.name.trim()}>Add</button>
        </div>
      )}

      {members.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)' }}>
          <p style={{ fontSize: 14, marginBottom: 8 }}>No team members found.</p>
          <p style={{ fontSize: 12 }}>Click <strong>Discover Team</strong> to scan your site, or add manually.</p>
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: 12,
        }}>
          {members.map(m => (
            <div key={m.id} style={{
              border: '1px solid var(--border)',
              background: 'var(--bg-card)',
              padding: 14,
              display: 'flex', flexDirection: 'column', gap: 6,
            }}>
              {/* Photo placeholder + name/title */}
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <div style={{
                  width: 44, height: 44, borderRadius: '50%',
                  background: 'var(--border)', flexShrink: 0,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 16, color: 'var(--text-dim)',
                  overflow: 'hidden',
                }}>
                  {m.photo_url ? (
                    <img src={m.photo_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    m.name?.charAt(0)?.toUpperCase() || '?'
                  )}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  {editingId === m.id ? (
                    <>
                      <input
                        className="setting-input"
                        value={editFields.name}
                        onChange={e => setEditFields(p => ({ ...p, name: e.target.value }))}
                        style={{ fontSize: 13, marginBottom: 4, width: '100%' }}
                        autoFocus
                        placeholder="Name"
                      />
                      <input
                        className="setting-input"
                        value={editFields.title}
                        onChange={e => setEditFields(p => ({ ...p, title: e.target.value }))}
                        style={{ fontSize: 11, width: '100%', marginBottom: 4 }}
                        placeholder="Title"
                      />
                      <input
                        className="setting-input"
                        value={editFields.linkedin_url}
                        onChange={e => setEditFields(p => ({ ...p, linkedin_url: e.target.value }))}
                        style={{ fontSize: 11, width: '100%', marginBottom: 4 }}
                        placeholder="LinkedIn URL"
                      />
                      <input
                        className="setting-input"
                        value={editFields.github_username}
                        onChange={e => setEditFields(p => ({ ...p, github_username: e.target.value }))}
                        style={{ fontSize: 11, width: '100%' }}
                        placeholder="GitHub username"
                        onKeyDown={e => e.key === 'Enter' && saveEdit(m.id)}
                      />
                      <div style={{ marginTop: 4, display: 'flex', gap: 6 }}>
                        <button className="btn btn-approve" style={{ fontSize: 10, padding: '2px 8px' }} onClick={() => saveEdit(m.id)}>Save</button>
                        <button className="btn" style={{ fontSize: 10, padding: '2px 8px', color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => setEditingId(null)}>Cancel</button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div
                        style={{ fontWeight: 600, fontSize: 13, cursor: 'pointer', lineHeight: 1.2 }}
                        onClick={() => startEdit(m)}
                        title="Click to edit"
                      >
                        {m.name}
                      </div>
                      {m.title && (
                        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>{m.title}</div>
                      )}
                    </>
                  )}
                </div>
                <button
                  style={{
                    background: 'none', border: 'none', color: 'var(--text-dim)',
                    cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0,
                  }}
                  onClick={() => deleteMember(m.id)}
                  title="Remove member"
                >&times;</button>
              </div>

              {/* Bio */}
              {m.bio && (
                <div style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.4 }}>
                  {m.bio.length > 150 ? m.bio.slice(0, 150) + '...' : m.bio}
                </div>
              )}

              {/* Expertise tags */}
              {m.expertise_tags?.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 2 }}>
                  {m.expertise_tags.map((tag, i) => (
                    <span key={i} style={{
                      fontSize: 10, padding: '1px 6px',
                      border: '1px solid var(--border)',
                      color: 'var(--accent)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}>{tag}</span>
                  ))}
                </div>
              )}

              {/* Links */}
              <div style={{ display: 'flex', gap: 8, fontSize: 10, marginTop: 2, flexWrap: 'wrap' }}>
                {m.linkedin_url && (
                  <a href={m.linkedin_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }}>LinkedIn</a>
                )}
                {m.github_username && (
                  <a href={`https://github.com/${m.github_username}`} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--text-dim)' }}>
                    @{m.github_username}
                  </a>
                )}
                {m.email && (
                  <a href={`mailto:${m.email}`} style={{ color: 'var(--text-dim)' }}>{m.email}</a>
                )}
              </div>

              {/* LinkedIn OAuth — connect personal account for "post as" */}
              <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--border)' }}>
                {m.linkedin_author_urn ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 10, color: 'var(--success, #4caf50)' }}>&#10003; LinkedIn connected</span>
                    {m.linkedin_token_expires_at > 0 && (
                      <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                        (expires {new Date(m.linkedin_token_expires_at * 1000).toLocaleDateString()})
                      </span>
                    )}
                    <a
                      href={`/api/oauth/linkedin?org_id=${orgId || 0}&member_id=${m.id}`}
                      style={{ fontSize: 10, color: 'var(--text-dim)', marginLeft: 'auto' }}
                    >
                      Reconnect
                    </a>
                  </div>
                ) : (
                  <a
                    href={`/api/oauth/linkedin?org_id=${orgId || 0}&member_id=${m.id}`}
                    style={{
                      fontSize: 10, color: 'var(--accent)',
                      textDecoration: 'none', display: 'inline-block',
                      padding: '3px 8px',
                      border: '1px solid var(--accent)',
                    }}
                  >
                    + Connect LinkedIn (post as {m.name.split(' ')[0]})
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
