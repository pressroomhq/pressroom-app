import { useState, useEffect, useCallback } from 'react'
import { orgHeaders } from '../api'

const API = '/api'

export default function HubSpot({ onLog, orgId, onNavigate }) {
  const [status, setStatus] = useState({})
  const [blogs, setBlogs] = useState([])
  const [contacts, setContacts] = useState([])
  const [loadingBlogs, setLoadingBlogs] = useState(false)
  const [loadingContacts, setLoadingContacts] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [blogContent, setBlogContent] = useState([])
  const [selectedContentId, setSelectedContentId] = useState('')

  const loadStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/hubspot/status`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      setStatus(data)
    } catch (e) {
      setStatus({ connected: false, configured: false })
    }
  }, [orgId])

  const loadBlogContent = useCallback(async () => {
    try {
      const res = await fetch(`${API}/content?limit=100`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      if (Array.isArray(data)) {
        const approved = data.filter(c => c.channel === 'blog' && (c.status === 'approved' || c.status === 'queued'))
        setBlogContent(approved)
      }
    } catch (e) { /* silent */ }
  }, [orgId])

  useEffect(() => {
    loadStatus()
    loadBlogContent()
  }, [loadStatus, loadBlogContent])

  const fetchBlogs = async () => {
    setLoadingBlogs(true)
    try {
      const res = await fetch(`${API}/hubspot/blogs`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      if (data.error) {
        onLog?.(`HUBSPOT BLOGS ERROR — ${data.error}`, 'error')
      } else {
        setBlogs(data.posts || [])
        onLog?.(`HUBSPOT — ${data.count} blog posts loaded`, 'success')
      }
    } catch (e) {
      onLog?.(`FETCH BLOGS FAILED — ${e.message}`, 'error')
    } finally {
      setLoadingBlogs(false)
    }
  }

  const syncBlogs = async () => {
    setSyncing(true)
    onLog?.('HUBSPOT SYNC — pulling blog posts into Pressroom...', 'action')
    try {
      const res = await fetch(`${API}/hubspot/sync`, {
        method: 'POST',
        headers: orgHeaders(orgId),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`HUBSPOT SYNC FAILED — ${data.error}`, 'error')
      } else {
        onLog?.(`HUBSPOT SYNC COMPLETE — ${data.imported} imported, ${data.skipped} skipped`, 'success')
      }
    } catch (e) {
      onLog?.(`SYNC FAILED — ${e.message}`, 'error')
    } finally {
      setSyncing(false)
    }
  }

  const pushToHubSpot = async () => {
    if (!selectedContentId) return
    setPublishing(true)
    onLog?.('HUBSPOT — pushing draft to HubSpot CMS...', 'action')
    try {
      const res = await fetch(`${API}/hubspot/publish`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ content_id: Number(selectedContentId) }),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`HUBSPOT PUSH FAILED — ${data.error}`, 'error')
      } else {
        const hp = data.hubspot_post || {}
        onLog?.(`HUBSPOT DRAFT CREATED — "${hp.title}" (${hp.id})`, 'success')
        setSelectedContentId('')
      }
    } catch (e) {
      onLog?.(`PUSH FAILED — ${e.message}`, 'error')
    } finally {
      setPublishing(false)
    }
  }

  const fetchContacts = async () => {
    setLoadingContacts(true)
    try {
      const res = await fetch(`${API}/hubspot/contacts`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      if (data.error) {
        onLog?.(`HUBSPOT CONTACTS ERROR — ${data.error}`, 'error')
      } else {
        setContacts(data.contacts || [])
        onLog?.(`HUBSPOT — ${data.count} contacts loaded`, 'success')
      }
    } catch (e) {
      onLog?.(`FETCH CONTACTS FAILED — ${e.message}`, 'error')
    } finally {
      setLoadingContacts(false)
    }
  }

  const isConnected = status.connected

  return (
    <div className="connections-panel">
      <h2 className="section-title">HUBSPOT</h2>

      {/* Not connected — point to Connections */}
      {!isConnected && (
        <div className="connections-section">
          <p className="section-desc">
            HubSpot is not connected.{' '}
            {onNavigate ? (
              <button
                className="btn btn-sm"
                style={{ marginLeft: 8 }}
                onClick={() => onNavigate('connections')}
              >
                Connect in Connections
              </button>
            ) : (
              <span>Connect HubSpot in the Connections tab.</span>
            )}
          </p>
        </div>
      )}

      {/* Blog Sync Section */}
      {isConnected && (
        <div className="connections-section">
          <h3 className="subsection-title">Blog Posts</h3>
          <p className="section-desc">
            Pull existing blog posts from HubSpot for engine context, or push approved content as new drafts.
          </p>

          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <button className="btn btn-sm" onClick={fetchBlogs} disabled={loadingBlogs}>
              {loadingBlogs ? 'Loading...' : 'List HubSpot Blogs'}
            </button>
            <button className="btn btn-sm" onClick={syncBlogs} disabled={syncing}>
              {syncing ? 'Syncing...' : 'Pull from HubSpot'}
            </button>
          </div>

          {blogs.length > 0 && (
            <div className="datasource-list">
              {blogs.map(post => (
                <div key={post.id} className="datasource-item">
                  <div className="datasource-header">
                    <div>
                      <span className="datasource-name">{post.title || 'Untitled'}</span>
                      <span className="datasource-badge">{post.state}</span>
                    </div>
                  </div>
                  {post.slug && <div className="datasource-url">/{post.slug}</div>}
                  {post.author_name && (
                    <div className="datasource-desc">{post.author_name}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Push to HubSpot Section */}
      {isConnected && (
        <div className="connections-section">
          <h3 className="subsection-title">Push to HubSpot</h3>
          <p className="section-desc">
            Send approved blog content to HubSpot as a new draft post.
          </p>

          {blogContent.length === 0 ? (
            <div className="connection-detail dim">
              No approved blog content available. Generate and approve blog content first.
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <select
                value={selectedContentId}
                onChange={e => setSelectedContentId(e.target.value)}
                style={{
                  flex: 1,
                  background: 'var(--bg)',
                  color: 'var(--text)',
                  border: '1px solid var(--border)',
                  padding: '6px 8px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
              >
                <option value="">Select blog content...</option>
                {blogContent.map(c => (
                  <option key={c.id} value={c.id}>
                    [{c.status.toUpperCase()}] {c.headline?.slice(0, 80) || `#${c.id}`}
                  </option>
                ))}
              </select>
              <button
                className="btn btn-sm"
                onClick={pushToHubSpot}
                disabled={publishing || !selectedContentId}
              >
                {publishing ? 'Pushing...' : 'Push Draft'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Contacts Section */}
      {isConnected && (
        <div className="connections-section">
          <h3 className="subsection-title">Contacts</h3>
          <p className="section-desc">
            CRM contacts from HubSpot (for future email campaigns).
          </p>

          <button className="btn btn-sm" onClick={fetchContacts} disabled={loadingContacts}
                  style={{ marginBottom: 12 }}>
            {loadingContacts ? 'Loading...' : 'Load Contacts'}
          </button>

          {contacts.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: 12,
                fontFamily: 'var(--font-mono)',
              }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--amber)', textTransform: 'uppercase', letterSpacing: '1px', fontSize: 10 }}>
                    <th style={{ padding: '6px 8px', textAlign: 'left' }}>Name</th>
                    <th style={{ padding: '6px 8px', textAlign: 'left' }}>Email</th>
                    <th style={{ padding: '6px 8px', textAlign: 'left' }}>Company</th>
                  </tr>
                </thead>
                <tbody>
                  {contacts.map(c => (
                    <tr key={c.id} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '6px 8px', color: 'var(--text-bright)' }}>
                        {[c.firstname, c.lastname].filter(Boolean).join(' ') || '-'}
                      </td>
                      <td style={{ padding: '6px 8px' }}>{c.email || '-'}</td>
                      <td style={{ padding: '6px 8px', color: 'var(--text-dim)' }}>{c.company || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
