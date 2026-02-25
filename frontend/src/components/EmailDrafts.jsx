import { useState, useEffect, useCallback, useRef } from 'react'
import { orgHeaders } from '../api'

const API = '/api'

function statusBadge(status) {
  const colors = { draft: '#888866', ready: '#ffb000', sent: '#33ff33' }
  return {
    background: colors[status] || '#888866',
    color: '#0a0a08',
    padding: '2px 8px',
    borderRadius: 2,
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '1px',
    textTransform: 'uppercase',
    display: 'inline-block',
  }
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}

export default function EmailDrafts({ orgId }) {
  const [drafts, setDrafts] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [composing, setComposing] = useState(false)
  const [emailContent, setEmailContent] = useState([])
  const [showContentPicker, setShowContentPicker] = useState(false)
  const [editSubject, setEditSubject] = useState('')
  const [editRecipients, setEditRecipients] = useState('')
  const [editStatus, setEditStatus] = useState('draft')
  const [saving, setSaving] = useState(false)
  const iframeRef = useRef(null)

  const fetchDrafts = useCallback(async () => {
    try {
      const res = await fetch(`${API}/email/drafts`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      setDrafts(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [orgId])

  const fetchEmailContent = useCallback(async () => {
    try {
      const res = await fetch(`${API}/content?limit=50`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      if (Array.isArray(data)) {
        setEmailContent(data.filter(c => c.channel === 'release_email' || c.channel === 'newsletter'))
      }
    } catch { /* ignore */ }
  }, [orgId])

  useEffect(() => { fetchDrafts() }, [fetchDrafts])

  const selectDraft = (draft) => {
    setSelected(draft)
    setEditSubject(draft.subject || '')
    setEditRecipients(Array.isArray(draft.recipients) ? draft.recipients.join(', ') : '')
    setEditStatus(draft.status || 'draft')
  }

  const composeDraft = async (contentId) => {
    setComposing(true)
    setShowContentPicker(false)
    try {
      const res = await fetch(`${API}/email/drafts/compose`, {
        method: 'POST', headers: orgHeaders(orgId),
        body: JSON.stringify({ content_id: contentId }),
      })
      if (res.ok) {
        const draft = await res.json()
        await fetchDrafts()
        selectDraft(draft)
      }
    } catch { /* ignore */ }
    setComposing(false)
  }

  const saveDraft = async () => {
    if (!selected) return
    setSaving(true)
    const recipients = editRecipients.split(',').map(e => e.trim()).filter(Boolean)
    try {
      const res = await fetch(`${API}/email/drafts/${selected.id}`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({
          subject: editSubject,
          recipients,
          status: editStatus,
        }),
      })
      if (res.ok) {
        const updated = await res.json()
        setSelected(updated)
        fetchDrafts()
      }
    } catch { /* ignore */ }
    setSaving(false)
  }

  const deleteDraft = async (id, e) => {
    if (e) e.stopPropagation()
    if (!confirm('Delete this email draft?')) return
    try {
      await fetch(`${API}/email/drafts/${id}`, { method: 'DELETE', headers: orgHeaders(orgId) })
      if (selected?.id === id) setSelected(null)
      fetchDrafts()
    } catch { /* ignore */ }
  }

  const openContentPicker = () => {
    fetchEmailContent()
    setShowContentPicker(true)
  }

  // Build preview URL for iframe
  const previewUrl = selected
    ? `${API}/email/drafts/${selected.id}/preview`
    : null

  if (loading) {
    return (
      <div className="settings-page">
        <p style={{ color: 'var(--text-dim)' }}>Loading email drafts...</p>
      </div>
    )
  }

  return (
    <div className="settings-page" style={{ display: 'flex', gap: 0, padding: 0, height: '100%', overflow: 'hidden' }}>
      {/* LEFT PANEL — Draft list */}
      <div style={{
        width: 320, minWidth: 280, borderRight: '1px solid var(--border)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        <div style={{
          padding: '16px 16px 12px', borderBottom: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{
            fontSize: 11, textTransform: 'uppercase', letterSpacing: 3,
            color: 'var(--amber)', fontWeight: 700,
          }}>Email Drafts</span>
          <button
            onClick={openContentPicker}
            disabled={composing}
            style={{
              background: 'var(--amber)', color: 'var(--bg)', border: 'none',
              padding: '4px 10px', fontSize: 11, cursor: 'pointer', letterSpacing: 1,
              fontFamily: 'var(--font-mono)', fontWeight: 700,
            }}
          >
            {composing ? 'Composing...' : '+ Compose'}
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0' }}>
          {drafts.length === 0 && (
            <div style={{ color: 'var(--text-dim)', padding: '24px 16px', fontSize: 12, textAlign: 'center' }}>
              No email drafts yet. Compose one from email or newsletter content.
            </div>
          )}
          {drafts.map(d => (
            <div
              key={d.id}
              onClick={() => selectDraft(d)}
              style={{
                padding: '10px 16px', cursor: 'pointer',
                borderBottom: '1px solid var(--border)',
                background: selected?.id === d.id ? 'var(--bg-card)' : 'transparent',
                borderLeft: selected?.id === d.id ? '3px solid var(--amber)' : '3px solid transparent',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 13, color: 'var(--text-bright)', fontWeight: 600,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>
                    {d.subject || '(no subject)'}
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
                    <span style={statusBadge(d.status)}>{d.status}</span>
                    <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>{formatDate(d.created_at)}</span>
                  </div>
                </div>
                <button
                  onClick={(e) => deleteDraft(d.id, e)}
                  style={{
                    background: 'none', border: 'none', color: 'var(--text-dim)',
                    cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: '0 2px',
                    fontFamily: 'var(--font-mono)',
                  }}
                  title="Delete draft"
                >&times;</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* RIGHT PANEL — Draft detail / preview */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {!selected && (
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--text-dim)', fontSize: 13, flexDirection: 'column', gap: 8,
          }}>
            <div style={{ fontSize: 24, opacity: 0.3 }}>&#9993;</div>
            <div>Select a draft to preview</div>
          </div>
        )}

        {selected && (
          <>
            {/* Edit bar */}
            <div style={{
              padding: '16px 20px', borderBottom: '1px solid var(--border)',
              display: 'flex', flexDirection: 'column', gap: 10,
            }}>
              {/* Subject */}
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <label style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, minWidth: 60 }}>Subject</label>
                <input
                  value={editSubject}
                  onChange={e => setEditSubject(e.target.value)}
                  style={{
                    flex: 1, background: 'var(--bg)', border: '1px solid var(--border)',
                    color: 'var(--text-bright)', padding: '6px 10px', fontSize: 13,
                    fontFamily: 'var(--font-mono)', outline: 'none',
                  }}
                />
              </div>

              {/* Recipients */}
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <label style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, minWidth: 60 }}>To</label>
                <input
                  value={editRecipients}
                  onChange={e => setEditRecipients(e.target.value)}
                  placeholder="email@example.com, other@example.com"
                  style={{
                    flex: 1, background: 'var(--bg)', border: '1px solid var(--border)',
                    color: 'var(--text)', padding: '6px 10px', fontSize: 12,
                    fontFamily: 'var(--font-mono)', outline: 'none',
                  }}
                />
              </div>

              {/* Status + actions */}
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <label style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, minWidth: 60 }}>Status</label>
                <select
                  value={editStatus}
                  onChange={e => setEditStatus(e.target.value)}
                  style={{
                    background: 'var(--bg)', border: '1px solid var(--border)',
                    color: 'var(--text)', padding: '5px 8px', fontSize: 12,
                    fontFamily: 'var(--font-mono)', outline: 'none',
                  }}
                >
                  <option value="draft">Draft</option>
                  <option value="ready">Ready</option>
                </select>

                <button
                  onClick={saveDraft}
                  disabled={saving}
                  style={{
                    background: 'var(--amber)', color: 'var(--bg)', border: 'none',
                    padding: '5px 14px', fontSize: 11, cursor: 'pointer',
                    fontFamily: 'var(--font-mono)', fontWeight: 700, letterSpacing: 1,
                  }}
                >
                  {saving ? 'Saving...' : 'Save'}
                </button>

                <div style={{ position: 'relative', display: 'inline-block' }} className="send-btn-wrapper">
                  <button
                    disabled
                    style={{
                      background: 'var(--border)', color: 'var(--text-dim)', border: 'none',
                      padding: '5px 14px', fontSize: 11, cursor: 'not-allowed',
                      fontFamily: 'var(--font-mono)', fontWeight: 700, letterSpacing: 1,
                    }}
                    title="Coming Soon"
                  >
                    Send
                  </button>
                </div>

                <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-dim)' }}>
                  ID #{selected.id} {selected.content_id ? `| Content #${selected.content_id}` : ''}
                </span>
              </div>
            </div>

            {/* Preview iframe */}
            <div style={{ flex: 1, background: '#f4f4f4', overflow: 'hidden' }}>
              {previewUrl && (
                <iframe
                  ref={iframeRef}
                  key={selected.id}
                  src={previewUrl + (orgId ? `?_org=${orgId}` : '')}
                  style={{
                    width: '100%', height: '100%', border: 'none',
                  }}
                  title="Email Preview"
                  sandbox="allow-same-origin"
                />
              )}
            </div>
          </>
        )}
      </div>

      {/* Content picker modal */}
      {showContentPicker && (
        <div
          onClick={() => setShowContentPicker(false)}
          style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            background: 'rgba(0,0,0,0.7)', zIndex: 1000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: 'var(--bg-panel)', border: '1px solid var(--border)',
              width: 500, maxHeight: '70vh', display: 'flex', flexDirection: 'column',
            }}
          >
            <div style={{
              padding: '16px 20px', borderBottom: '1px solid var(--border)',
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            }}>
              <span style={{
                fontSize: 11, textTransform: 'uppercase', letterSpacing: 2,
                color: 'var(--amber)', fontWeight: 700,
              }}>Compose from Content</span>
              <button
                onClick={() => setShowContentPicker(false)}
                style={{
                  background: 'none', border: 'none', color: 'var(--text-dim)',
                  fontSize: 18, cursor: 'pointer', fontFamily: 'var(--font-mono)',
                }}
              >&times;</button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: 0 }}>
              {emailContent.length === 0 && (
                <div style={{ padding: 24, color: 'var(--text-dim)', fontSize: 12, textAlign: 'center' }}>
                  No email or newsletter content found. Generate some first.
                </div>
              )}
              {emailContent.map(c => (
                <div
                  key={c.id}
                  onClick={() => composeDraft(c.id)}
                  style={{
                    padding: '12px 20px', cursor: 'pointer',
                    borderBottom: '1px solid var(--border)',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-card)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                    <span style={{
                      background: c.channel === 'newsletter' ? '#ffb000' : '#cc8800',
                      color: '#0a0a08', padding: '1px 6px', fontSize: 9, fontWeight: 700,
                      letterSpacing: 1, textTransform: 'uppercase',
                    }}>
                      {c.channel === 'newsletter' ? 'NEWSLETTER' : 'RELEASE EMAIL'}
                    </span>
                    <span style={{
                      background: c.status === 'approved' ? '#33ff33' : 'var(--border)',
                      color: '#0a0a08', padding: '1px 6px', fontSize: 9, fontWeight: 700,
                      letterSpacing: 1, textTransform: 'uppercase',
                    }}>
                      {c.status}
                    </span>
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-bright)', fontWeight: 600 }}>
                    {c.headline || '(untitled)'}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
                    {(c.body || '').slice(0, 100)}{(c.body || '').length > 100 ? '...' : ''}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
