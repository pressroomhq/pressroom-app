import { useState, useEffect, useCallback } from 'react'
import { orgHeaders } from '../api'

const API = '/api'

function MemberModal({ member, orgId, onClose, onSaved }) {
  const headers = orgHeaders(orgId)
  const [fields, setFields] = useState({
    name: member.name || '',
    title: member.title || '',
    bio: member.bio || '',
    email: member.email || '',
    linkedin_url: member.linkedin_url || '',
    github_username: member.github_username || '',
    expertise_tags: (member.expertise_tags || []).join(', '),
    voice_style: member.voice_style || '',
    linkedin_post_samples: member.linkedin_post_samples || '',
  })
  const [saving, setSaving] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeMsg, setAnalyzeMsg] = useState('')

  const set = (k, v) => setFields(p => ({ ...p, [k]: v }))

  const save = async () => {
    setSaving(true)
    const tags = fields.expertise_tags
      ? fields.expertise_tags.split(',').map(t => t.trim()).filter(Boolean)
      : []
    await fetch(`${API}/team/${member.id}`, {
      method: 'PUT', headers,
      body: JSON.stringify({ ...fields, expertise_tags: tags }),
    })
    setSaving(false)
    onSaved()
  }

  const analyzeVoice = async () => {
    // Save samples first so the endpoint can read them
    await fetch(`${API}/team/${member.id}`, {
      method: 'PUT', headers,
      body: JSON.stringify({ linkedin_post_samples: fields.linkedin_post_samples }),
    })
    setAnalyzing(true)
    setAnalyzeMsg('')
    try {
      const res = await fetch(`${API}/team/${member.id}/analyze-voice`, { method: 'POST', headers })
      const data = await res.json()
      if (data.error) {
        setAnalyzeMsg(`Error: ${data.error}`)
      } else {
        set('voice_style', data.style)
        setAnalyzeMsg(`Analyzed ${data.posts_analyzed} posts`)
      }
    } catch (e) {
      setAnalyzeMsg(`Error: ${e.message}`)
    }
    setAnalyzing(false)
  }

  // Close on Escape
  useEffect(() => {
    const handler = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const inputStyle = { width: '100%', boxSizing: 'border-box' }
  const labelStyle = { fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.5px', display: 'block', marginBottom: 4 }
  const fieldStyle = { marginBottom: 14 }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, padding: 16,
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        width: '100%', maxWidth: 620, maxHeight: '90vh',
        overflowY: 'auto', padding: 24,
      }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 44, height: 44, borderRadius: '50%',
              background: 'var(--border)', flexShrink: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 18, overflow: 'hidden',
            }}>
              {member.photo_url
                ? <img src={member.photo_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                : member.name?.charAt(0)?.toUpperCase() || '?'}
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 15 }}>{member.name}</div>
              {member.title && <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>{member.title}</div>}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 20, lineHeight: 1 }}
          >&times;</button>
        </div>

        {/* LinkedIn connection status */}
        <div style={{ marginBottom: 16, padding: '8px 12px', background: 'var(--bg)', border: '1px solid var(--border)', fontSize: 11 }}>
          {member.linkedin_author_urn ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6 }}>
              <span style={{ color: 'var(--success, #4caf50)' }}>&#10003; LinkedIn connected — can post as {member.name.split(' ')[0]}</span>
              <a href={`/api/oauth/linkedin?org_id=${orgId || 0}&member_id=${member.id}`} style={{ color: 'var(--text-dim)' }}>Reconnect</a>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6 }}>
              <span style={{ color: 'var(--text-dim)' }}>LinkedIn not connected</span>
              <a
                href={`/api/oauth/linkedin?org_id=${orgId || 0}&member_id=${member.id}`}
                style={{ color: 'var(--accent)', textDecoration: 'none', padding: '2px 8px', border: '1px solid var(--accent)' }}
              >
                + Connect LinkedIn
              </a>
            </div>
          )}
        </div>

        {/* GitHub connection status */}
        <div style={{ marginBottom: 16, padding: '8px 12px', background: 'var(--bg)', border: '1px solid var(--border)', fontSize: 11 }}>
          {member.github_connected ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6 }}>
              <span style={{ color: 'var(--success, #4caf50)' }}>&#10003; GitHub connected — can publish gists as {member.github_username || member.name.split(' ')[0]}</span>
              <a href={`/api/oauth/github?org_id=${orgId || 0}&member_id=${member.id}`} style={{ color: 'var(--text-dim)' }}>Reconnect</a>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6 }}>
              <span style={{ color: 'var(--text-dim)' }}>GitHub not connected{member.github_username ? ` (@${member.github_username})` : ''}</span>
              <a
                href={`/api/oauth/github?org_id=${orgId || 0}&member_id=${member.id}`}
                style={{ color: 'var(--accent)', textDecoration: 'none', padding: '2px 8px', border: '1px solid var(--accent)' }}
              >
                + Connect GitHub
              </a>
            </div>
          )}
        </div>

        {/* Profile fields */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 16px' }}>
          <div style={fieldStyle}>
            <label style={labelStyle}>Name</label>
            <input className="setting-input" style={inputStyle} value={fields.name} onChange={e => set('name', e.target.value)} />
          </div>
          <div style={fieldStyle}>
            <label style={labelStyle}>Title</label>
            <input className="setting-input" style={inputStyle} value={fields.title} onChange={e => set('title', e.target.value)} />
          </div>
          <div style={fieldStyle}>
            <label style={labelStyle}>Email</label>
            <input className="setting-input" style={inputStyle} value={fields.email} onChange={e => set('email', e.target.value)} />
          </div>
          <div style={fieldStyle}>
            <label style={labelStyle}>GitHub Username</label>
            <input className="setting-input" style={inputStyle} value={fields.github_username} onChange={e => set('github_username', e.target.value)} />
          </div>
          <div style={{ ...fieldStyle, gridColumn: '1 / -1' }}>
            <label style={labelStyle}>LinkedIn URL</label>
            <input className="setting-input" style={inputStyle} value={fields.linkedin_url} onChange={e => set('linkedin_url', e.target.value)} />
          </div>
          <div style={{ ...fieldStyle, gridColumn: '1 / -1' }}>
            <label style={labelStyle}>Bio</label>
            <textarea
              className="setting-input"
              style={{ ...inputStyle, height: 72, resize: 'vertical', fontFamily: 'inherit' }}
              value={fields.bio}
              onChange={e => set('bio', e.target.value)}
            />
          </div>
          <div style={{ ...fieldStyle, gridColumn: '1 / -1' }}>
            <label style={labelStyle}>Expertise Tags (comma-separated)</label>
            <input className="setting-input" style={inputStyle} value={fields.expertise_tags} onChange={e => set('expertise_tags', e.target.value)} />
          </div>
        </div>

        {/* Voice section */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16, marginTop: 4 }}>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Writing Voice</div>

          <div style={fieldStyle}>
            <label style={labelStyle}>LinkedIn Post Samples — paste 3–10 posts, separated by ---</label>
            <textarea
              className="setting-input"
              style={{ ...inputStyle, height: 140, resize: 'vertical', fontFamily: 'inherit', fontSize: 11 }}
              placeholder={"Paste a LinkedIn post here\n\n---\n\nPaste another post here\n\n---\n\nAnd another..."}
              value={fields.linkedin_post_samples}
              onChange={e => set('linkedin_post_samples', e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
            <button
              className="btn btn-run"
              onClick={analyzeVoice}
              disabled={analyzing || !fields.linkedin_post_samples.trim()}
              style={{ fontSize: 11 }}
            >
              {analyzing ? 'Analyzing...' : 'Analyze Voice'}
            </button>
            {analyzeMsg && (
              <span style={{ fontSize: 11, color: analyzeMsg.startsWith('Error') ? 'var(--error)' : 'var(--text-dim)' }}>
                {analyzeMsg}
              </span>
            )}
          </div>

          <div style={fieldStyle}>
            <label style={labelStyle}>Voice Style Description — used when generating content as this person</label>
            <textarea
              className="setting-input"
              style={{ ...inputStyle, height: 96, resize: 'vertical', fontFamily: 'inherit', fontSize: 11 }}
              placeholder="Describe how this person writes — or click Analyze Voice above to generate from samples."
              value={fields.voice_style}
              onChange={e => set('voice_style', e.target.value)}
            />
          </div>
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
          <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={onClose}>Cancel</button>
          <button className="btn btn-approve" onClick={save} disabled={saving}>{saving ? 'Saving...' : 'Save'}</button>
        </div>
      </div>
    </div>
  )
}


function GistSuggestionsPanel({ orgId, gistData, headers, members }) {
  const [generating, setGenerating] = useState({})
  const [suggestions, setSuggestions] = useState({})
  const [copied, setCopied] = useState({})
  const [publishing, setPublishing] = useState({})
  const [published, setPublished] = useState({})

  const noGistMembers = (gistData?.members || []).filter(m => m.needs_gist && m.github_username)

  if (noGistMembers.length === 0) return null

  const generate = async (member) => {
    setGenerating(g => ({ ...g, [member.id]: true }))
    try {
      const res = await fetch(`/api/team/${member.id}/generate-gist`, { method: 'POST', headers })
      const data = await res.json()
      if (data.suggestion) setSuggestions(s => ({ ...s, [member.id]: data.suggestion }))
      else setSuggestions(s => ({ ...s, [member.id]: { error: data.error || 'Failed to generate' } }))
    } catch (e) {
      setSuggestions(s => ({ ...s, [member.id]: { error: e.message } }))
    }
    setGenerating(g => ({ ...g, [member.id]: false }))
  }

  const copy = (id, text) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(c => ({ ...c, [id]: true }))
      setTimeout(() => setCopied(c => ({ ...c, [id]: false })), 2000)
    })
  }

  const publishGist = async (member, sug) => {
    setPublishing(p => ({ ...p, [member.id]: true }))
    try {
      const res = await fetch(`/api/team/${member.id}/publish-gist`, {
        method: 'POST', headers,
        body: JSON.stringify({
          title: sug.title,
          description: sug.description,
          content: sug.content,
          public: true,
        }),
      })
      const data = await res.json()
      if (data.success) {
        setPublished(p => ({ ...p, [member.id]: data.gist_url }))
      } else {
        setPublished(p => ({ ...p, [member.id]: { error: data.error } }))
      }
    } catch (e) {
      setPublished(p => ({ ...p, [member.id]: { error: e.message } }))
    }
    setPublishing(p => ({ ...p, [member.id]: false }))
  }

  return (
    <div style={{ marginTop: 24, borderTop: '1px solid var(--border)', paddingTop: 20 }}>
      <div style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: 4 }}>
        Gist Suggestions
      </div>
      <p style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 16 }}>
        {noGistMembers.length} teammate{noGistMembers.length !== 1 ? 's' : ''} with no public gists — generate a starter for them to share.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {noGistMembers.map(member => {
          const sug = suggestions[member.id]
          return (
            <div key={member.id} style={{ border: '1px solid var(--border)', background: 'var(--bg-card)', padding: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                <div>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{member.name}</span>
                  {member.title && <span style={{ fontSize: 11, color: 'var(--text-dim)', marginLeft: 8 }}>{member.title}</span>}
                  <a
                    href={`https://gist.github.com/${member.github_username}`}
                    target="_blank" rel="noopener noreferrer"
                    style={{ fontSize: 10, color: 'var(--text-dim)', marginLeft: 8 }}
                    onClick={e => e.stopPropagation()}
                  >
                    @{member.github_username} · 0 gists
                  </a>
                </div>
                <button
                  className="btn btn-run"
                  style={{ fontSize: 11 }}
                  onClick={() => generate(member)}
                  disabled={generating[member.id]}
                >
                  {generating[member.id] ? 'Generating...' : sug ? 'Regenerate' : 'Generate Gist Idea'}
                </button>
              </div>

              {sug && !sug.error && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 600, fontSize: 12, fontFamily: 'monospace' }}>{sug.title}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{sug.description}</span>
                  </div>
                  {sug.rationale && (
                    <div style={{ fontSize: 11, color: 'var(--accent)', marginBottom: 8 }}>↳ {sug.rationale}</div>
                  )}
                  <div style={{ position: 'relative' }}>
                    <pre style={{
                      background: 'var(--bg)', border: '1px solid var(--border)',
                      padding: '10px 12px', fontSize: 11, lineHeight: 1.5,
                      overflowX: 'auto', maxHeight: 280, margin: 0,
                      fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    }}>
                      {sug.content}
                    </pre>
                    <button
                      onClick={() => copy(member.id, sug.content)}
                      style={{
                        position: 'absolute', top: 6, right: 6,
                        background: 'var(--bg-card)', border: '1px solid var(--border)',
                        color: copied[member.id] ? 'var(--success, #4caf50)' : 'var(--text-dim)',
                        cursor: 'pointer', fontSize: 10, padding: '2px 8px',
                      }}
                    >
                      {copied[member.id] ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                  <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    {published[member.id] && typeof published[member.id] === 'string' ? (
                      <a
                        href={published[member.id]}
                        target="_blank" rel="noopener noreferrer"
                        style={{ fontSize: 10, color: 'var(--success, #4caf50)' }}
                      >
                        ✓ Published → {published[member.id]}
                      </a>
                    ) : published[member.id]?.error ? (
                      <span style={{ fontSize: 10, color: 'var(--error)' }}>
                        {published[member.id].error}
                        {published[member.id].error?.includes('not connected') && (
                          <a href={`/api/oauth/github?org_id=${orgId || 0}&member_id=${member.id}`}
                            style={{ marginLeft: 6, color: 'var(--accent)' }}>Connect GitHub →</a>
                        )}
                      </span>
                    ) : (
                      <>
                        {(() => {
                          const fullMember = members?.find(m => m.id === member.id)
                          return fullMember?.github_connected ? (
                            <button
                              className="btn btn-approve"
                              style={{ fontSize: 10 }}
                              onClick={() => publishGist(member, sug)}
                              disabled={publishing[member.id]}
                            >
                              {publishing[member.id] ? 'Publishing...' : '↑ Publish to GitHub'}
                            </button>
                          ) : (
                            <a
                              href={`/api/oauth/github?org_id=${orgId || 0}&member_id=${member.id}`}
                              style={{ fontSize: 10, color: 'var(--accent)', padding: '2px 8px', border: '1px solid var(--accent)', textDecoration: 'none' }}
                            >
                              + Connect GitHub to publish
                            </a>
                          )
                        })()}
                        <a
                          href={`https://gist.github.com/`}
                          target="_blank" rel="noopener noreferrer"
                          style={{ fontSize: 10, color: 'var(--text-dim)' }}
                        >
                          or create manually ↗
                        </a>
                      </>
                    )}
                  </div>
                </div>
              )}

              {sug?.error && (
                <div style={{ fontSize: 11, color: 'var(--error)', marginTop: 8 }}>Error: {sug.error}</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}


export default function Team({ orgId }) {
  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)
  const [discovering, setDiscovering] = useState(false)
  const [discoverResult, setDiscoverResult] = useState(null)
  const [linkingGithub, setLinkingGithub] = useState(false)
  const [checkingGists, setCheckingGists] = useState(false)
  const [gistData, setGistData] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [newMember, setNewMember] = useState({ name: '', title: '', bio: '', email: '', linkedin_url: '', github_username: '', expertise_tags: '' })
  const [modalMember, setModalMember] = useState(null)

  const headers = orgHeaders(orgId)

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
      if (data.members?.length > 0 || data.saved > 0) fetchMembers()
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

  const checkGists = async () => {
    setCheckingGists(true)
    setGistData(null)
    try {
      const res = await fetch(`${API}/team/gist-check`, { headers })
      const data = await res.json()
      setGistData(data)
    } catch (e) {
      setDiscoverResult({ error: `Gist check failed: ${e.message}` })
    }
    setCheckingGists(false)
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
        setDiscoverResult({ message: data.message || `Linked ${data.linked || 0} members.` })
        fetchMembers()
      }
    } catch (e) {
      setDiscoverResult({ error: e.message })
    }
    setLinkingGithub(false)
  }

  const deleteMember = async (id, e) => {
    e.stopPropagation()
    await fetch(`${API}/team/${id}`, { method: 'DELETE', headers })
    fetchMembers()
  }

  if (loading) return <div className="settings-page"><p style={{ color: 'var(--text-dim)' }}>Loading team...</p></div>

  return (
    <div className="settings-page">
      {modalMember && (
        <MemberModal
          member={modalMember}
          orgId={orgId}
          onClose={() => setModalMember(null)}
          onSaved={() => { fetchMembers(); setModalMember(null) }}
        />
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h2 className="settings-title" style={{ margin: 0 }}>Team Members</h2>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn btn-run" onClick={discover} disabled={discovering}>
            {discovering ? 'Discovering...' : 'Discover Team'}
          </button>
          <button className="btn" style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }} onClick={linkGithub} disabled={linkingGithub}>
            {linkingGithub ? 'Linking...' : 'Link GitHub'}
          </button>
          <button className="btn" style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }} onClick={checkGists} disabled={checkingGists}>
            {checkingGists ? 'Checking...' : 'Gist Check'}
          </button>
          <button className="btn btn-approve" onClick={() => setShowAdd(!showAdd)}>
            {showAdd ? 'Cancel' : '+ Add Member'}
          </button>
        </div>
      </div>

      {discoverResult && (
        <div style={{ padding: '10px 14px', marginBottom: 16, border: '1px solid var(--border)', background: 'var(--bg-card)', fontSize: 12, lineHeight: 1.5 }}>
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
          <input className="setting-input" placeholder="Name *" value={newMember.name} onChange={e => setNewMember(p => ({ ...p, name: e.target.value }))} style={{ flex: '1 1 180px' }} />
          <input className="setting-input" placeholder="Title" value={newMember.title} onChange={e => setNewMember(p => ({ ...p, title: e.target.value }))} style={{ flex: '1 1 180px' }} />
          <input className="setting-input" placeholder="Email" value={newMember.email} onChange={e => setNewMember(p => ({ ...p, email: e.target.value }))} style={{ flex: '1 1 180px' }} />
          <input className="setting-input" placeholder="LinkedIn URL" value={newMember.linkedin_url} onChange={e => setNewMember(p => ({ ...p, linkedin_url: e.target.value }))} style={{ flex: '1 1 220px' }} />
          <input className="setting-input" placeholder="GitHub username" value={newMember.github_username} onChange={e => setNewMember(p => ({ ...p, github_username: e.target.value }))} style={{ flex: '1 1 160px' }} />
          <input className="setting-input" placeholder="Expertise (comma-separated)" value={newMember.expertise_tags} onChange={e => setNewMember(p => ({ ...p, expertise_tags: e.target.value }))} style={{ flex: '1 1 240px' }} />
          <button className="btn btn-approve" onClick={addMember} disabled={!newMember.name.trim()}>Add</button>
        </div>
      )}

      {members.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)' }}>
          <p style={{ fontSize: 14, marginBottom: 8 }}>No team members found.</p>
          <p style={{ fontSize: 12 }}>Click <strong>Discover Team</strong> to scan your site, or add manually.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
          {members.map(m => {
            const gistInfo = gistData?.members?.find(g => g.id === m.id)
            return (
            <div
              key={m.id}
              onClick={() => setModalMember(m)}
              style={{
                border: '1px solid var(--border)', background: 'var(--bg-card)',
                padding: 14, cursor: 'pointer',
                display: 'flex', flexDirection: 'column', gap: 6,
                transition: 'border-color 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--accent)'}
              onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
            >
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <div style={{
                  width: 44, height: 44, borderRadius: '50%',
                  background: 'var(--border)', flexShrink: 0,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 16, color: 'var(--text-dim)', overflow: 'hidden',
                }}>
                  {m.photo_url
                    ? <img src={m.photo_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    : m.name?.charAt(0)?.toUpperCase() || '?'}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, lineHeight: 1.2 }}>{m.name}</div>
                  {m.title && <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>{m.title}</div>}
                  {m.voice_style && (
                    <div style={{ fontSize: 10, color: 'var(--accent)', marginTop: 3 }}>&#10003; Voice analyzed</div>
                  )}
                  {gistInfo && gistInfo.status === 'ok' && (
                    gistInfo.gist_count > 0
                      ? <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 2 }}>
                          &#10003; {gistInfo.gist_count} gist{gistInfo.gist_count !== 1 ? 's' : ''}
                        </div>
                      : <div style={{ fontSize: 10, color: 'var(--warning, #ff9800)', marginTop: 2 }}>
                          &#9651; No gists yet
                        </div>
                  )}
                </div>
                <button
                  style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0 }}
                  onClick={e => deleteMember(m.id, e)}
                  title="Remove member"
                >&times;</button>
              </div>

              {m.bio && (
                <div style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.4 }}>
                  {m.bio.length > 120 ? m.bio.slice(0, 120) + '...' : m.bio}
                </div>
              )}

              {m.expertise_tags?.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 2 }}>
                  {m.expertise_tags.map((tag, i) => (
                    <span key={i} style={{ fontSize: 10, padding: '1px 6px', border: '1px solid var(--border)', color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>{tag}</span>
                  ))}
                </div>
              )}

              <div style={{ display: 'flex', gap: 8, fontSize: 10, marginTop: 2, flexWrap: 'wrap' }}>
                {m.linkedin_url && <a href={m.linkedin_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)' }} onClick={e => e.stopPropagation()}>LinkedIn</a>}
                {m.github_username && <a href={`https://github.com/${m.github_username}`} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--text-dim)' }} onClick={e => e.stopPropagation()}>@{m.github_username}</a>}
                {m.linkedin_author_urn && <span style={{ color: 'var(--success, #4caf50)' }}>&#10003; LI connected</span>}
              </div>
            </div>
          )})}
        </div>
      )}

      {gistData && (
        <GistSuggestionsPanel orgId={orgId} gistData={gistData} headers={headers} members={members} />
      )}
    </div>
  )
}
