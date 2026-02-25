import { useState, useEffect, useCallback } from 'react'
import ChannelPicker, { loadSavedChannels, saveChannels } from './ChannelPicker'
import { orgHeaders } from '../api'

const API = '/api'

function CopyBtn({ text }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      className={`copy-btn ${copied ? 'copied' : ''}`}
      onClick={e => {
        e.stopPropagation()
        navigator.clipboard.writeText(text || '').then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }}
    >
      {copied ? 'COPIED' : 'COPY'}
    </button>
  )
}

export default function StoryWorkbench({ orgId, signals }) {
  const [stories, setStories] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [selected, setSelected] = useState(null)
  const [storyContent, setStoryContent] = useState([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [digging, setDigging] = useState(null) // signal id currently digging
  const [discovering, setDiscovering] = useState(null) // 'web' | 'wire' | null
  const [discovered, setDiscovered] = useState([]) // discovered signals from search
  const [selectedChannels, setSelectedChannels] = useState(() => loadSavedChannels(orgId))
  const [teamMembers, setTeamMembers] = useState([])
  const [postAs, setPostAs] = useState('') // '' = company, or team member id
  const [wireSignals, setWireSignals] = useState([]) // company wire signals (GitHub releases etc)
  const [revisingId, setRevisingId] = useState(null) // content id with revise panel open
  const [reviseFeedback, setReviseFeedback] = useState('')
  const [revisingSubmitting, setRevisingSubmitting] = useState(false)
  const [expandedContent, setExpandedContent] = useState(null) // content id with full body shown
  const [signalTypeFilter, setSignalTypeFilter] = useState('') // filter wire signals by type

  const headers = orgHeaders(orgId)

  // ── Fetch stories list ──
  const fetchStories = useCallback(async () => {
    try {
      const res = await fetch(`${API}/stories`, { headers })
      const data = await res.json()
      setStories(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [orgId])

  // ── Fetch single story with signals ──
  const fetchStory = useCallback(async (id) => {
    try {
      const res = await fetch(`${API}/stories/${id}`, { headers })
      const data = await res.json()
      if (!data.error) setSelected(data)
    } catch { /* ignore */ }
  }, [orgId])

  const fetchStoryContent = useCallback(async (id) => {
    try {
      const res = await fetch(`${API}/stories/${id}/content`, { headers })
      const data = await res.json()
      setStoryContent(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
  }, [orgId])

  useEffect(() => { fetchStories() }, [fetchStories])
  useEffect(() => {
    setExpandedContent(null)
    if (selectedId) {
      fetchStory(selectedId)
      fetchStoryContent(selectedId)
    } else {
      setStoryContent([])
    }
  }, [selectedId, fetchStory, fetchStoryContent])
  useEffect(() => {
    fetch(`${API}/team`, { headers }).then(r => r.json()).then(d => setTeamMembers(Array.isArray(d) ? d : [])).catch(() => {})
  }, [orgId])

  useEffect(() => {
    fetch(`${API}/wire/signals?limit=60`, { headers })
      .then(r => r.json())
      .then(d => {
        const items = Array.isArray(d) ? d : (d.signals || [])
        setWireSignals(items.map(ws => ({
          id: `wire:${ws.id}`,
          type: ws.type,
          title: ws.title,
          body: ws.body || '',
          url: ws.url || '',
          _table: 'wire',
        })))
      })
      .catch(() => {})
  }, [orgId])

  // ── CRUD ──
  const createStory = async () => {
    const res = await fetch(`${API}/stories`, {
      method: 'POST', headers, body: JSON.stringify({ title: 'New Story' })
    })
    const data = await res.json()
    if (data.id) {
      await fetchStories()
      setSelectedId(data.id)
    }
  }

  const updateField = async (field, value) => {
    if (!selectedId) return
    setSelected(prev => ({ ...prev, [field]: value }))
    await fetch(`${API}/stories/${selectedId}`, {
      method: 'PUT', headers, body: JSON.stringify({ [field]: value })
    })
    fetchStories() // refresh list for title changes
  }

  const deleteStory = async (id) => {
    await fetch(`${API}/stories/${id}`, { method: 'DELETE', headers })
    if (selectedId === id) { setSelectedId(null); setSelected(null) }
    fetchStories()
  }

  // ── Signal management ──
  const addSignal = async (signalId) => {
    if (!selectedId) return
    await fetch(`${API}/stories/${selectedId}/signals`, {
      method: 'POST', headers, body: JSON.stringify({ signal_id: signalId })
    })
    fetchStory(selectedId)
  }

  const removeSignal = async (storySignalId) => {
    if (!selectedId) return
    await fetch(`${API}/stories/${selectedId}/signals/${storySignalId}`, {
      method: 'DELETE', headers
    })
    fetchStory(selectedId)
  }

  const updateSignalNotes = async (storySignalId, notes) => {
    if (!selectedId) return
    await fetch(`${API}/stories/${selectedId}/signals/${storySignalId}`, {
      method: 'PUT', headers, body: JSON.stringify({ editor_notes: notes })
    })
  }

  const digDeeper = async (signalId) => {
    setDigging(signalId)
    try {
      await fetch(`${API}/signals/${signalId}/dig-deeper`, { method: 'POST', headers })
      fetchStory(selectedId)
    } catch { /* ignore */ }
    setDigging(null)
  }

  // ── Signal Discovery ──
  const discoverSignals = async (mode) => {
    if (!selectedId) return
    setDiscovering(mode)
    setDiscovered([])
    try {
      const res = await fetch(`${API}/stories/${selectedId}/discover`, {
        method: 'POST', headers, body: JSON.stringify({ mode })
      })
      const data = await res.json()
      if (data.error) {
        setDiscovered([])
      } else {
        setDiscovered(data.signals || [])
      }
    } catch { /* ignore */ }
    setDiscovering(null)
  }

  // ── Generate ──
  const generateFromStory = async () => {
    if (!selectedId || selectedChannels.length === 0) return
    saveChannels(orgId, selectedChannels)
    setGenerating(true)
    try {
      await fetch(`${API}/stories/${selectedId}/generate`, {
        method: 'POST', headers, body: JSON.stringify({
          channels: selectedChannels,
          team_member_id: postAs ? Number(postAs) : null,
        })
      })
      fetchStory(selectedId)
      fetchStories()
      fetchStoryContent(selectedId)
    } catch { /* ignore */ }
    setGenerating(false)
  }

  // Signals not yet in the story (Scout + Wire combined)
  const storySignalIds = new Set((selected?.signals || []).map(ss => ss.signal?.id ?? ss.signal_id))
  const availableScout = (signals || []).filter(s => !storySignalIds.has(s.id))
  const availableWire = wireSignals.filter(s => !storySignalIds.has(s.id))
  const availableSignals = [...availableScout, ...availableWire]
  const signalTypes = [...new Set(availableSignals.map(s => s.type).filter(Boolean))].sort()
  const filteredSignals = signalTypeFilter
    ? availableSignals.filter(s => s.type === signalTypeFilter)
    : availableSignals

  const statusColor = { draft: 'var(--text-dim)', generating: 'var(--amber)', complete: 'var(--green)' }

  return (
    <div className="story-workbench">
      {/* LEFT: Story list */}
      <div className="story-list-panel">
        <div className="story-list-header">
          <span className="section-label" style={{ margin: 0 }}>Stories</span>
          <button className="btn btn-approve btn-sm" onClick={createStory}>+ New</button>
        </div>
        {loading ? (
          <p style={{ color: 'var(--text-dim)', padding: 12, fontSize: 11 }}>Loading...</p>
        ) : stories.length === 0 ? (
          <p style={{ color: 'var(--text-dim)', padding: 12, fontSize: 11 }}>No stories yet. Create one to start curating.</p>
        ) : (
          stories.map(s => (
            <div
              key={s.id}
              className={`story-list-item ${selectedId === s.id ? 'active' : ''}`}
              onClick={() => setSelectedId(s.id)}
            >
              <div className="story-list-title">{s.title || 'Untitled'}</div>
              <div className="story-list-meta">
                <span style={{ color: statusColor[s.status] || 'var(--text-dim)' }}>{s.status}</span>
                <span>{s.signal_count || 0} signals</span>
              </div>
            </div>
          ))
        )}
      </div>

      {/* RIGHT: Story editor */}
      <div className="story-editor-panel">
        {!selected ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)' }}>
            Select a story or create a new one
          </div>
        ) : (
          <>
            <div className="story-editor-header">
              <input
                className="story-title-input"
                value={selected.title || ''}
                onChange={e => setSelected(prev => ({ ...prev, title: e.target.value }))}
                onBlur={e => updateField('title', e.target.value)}
                placeholder="Story title..."
              />
              <button className="asset-delete" onClick={() => deleteStory(selected.id)} title="Delete story">&times;</button>
            </div>

            <div className="story-field">
              <label className="story-field-label">Angle</label>
              <input
                className="setting-input"
                value={selected.angle || ''}
                onChange={e => setSelected(prev => ({ ...prev, angle: e.target.value }))}
                onBlur={e => updateField('angle', e.target.value)}
                placeholder="What's the editorial angle?"
              />
            </div>

            <div className="story-field">
              <label className="story-field-label">Editorial Notes</label>
              <textarea
                className="setting-input story-notes-input"
                value={selected.editorial_notes || ''}
                onChange={e => setSelected(prev => ({ ...prev, editorial_notes: e.target.value }))}
                onBlur={e => updateField('editorial_notes', e.target.value)}
                placeholder="Context, direction, things to emphasize..."
                rows={3}
              />
            </div>

            {/* Curated signals */}
            <div className="story-section">
              <div className="section-label">Curated Signals ({selected.signals?.length || 0})</div>
              {(selected.signals || []).length === 0 ? (
                <p style={{ color: 'var(--text-dim)', fontSize: 11 }}>Add signals from the wire below</p>
              ) : (
                (selected.signals || []).map(ss => {
                  const sig = ss.signal || {}
                  return (
                    <div key={ss.id} className="story-signal-card">
                      <div className="story-signal-header">
                        <span className="story-signal-type">{sig.type}</span>
                        <span className="story-signal-title">{sig.title}</span>
                        <div className="story-signal-actions">
                          <button
                            className="btn btn-sm"
                            onClick={() => digDeeper(sig.id)}
                            disabled={digging === sig.id}
                            title="Dig deeper — fetch source and enrich"
                          >
                            {digging === sig.id ? 'Digging...' : 'Dig Deeper'}
                          </button>
                          <button className="btn btn-sm btn-spike" onClick={() => removeSignal(ss.id)} title="Remove from story">&times;</button>
                        </div>
                      </div>
                      {sig.body && (
                        <div className="story-signal-body">
                          {sig.body.slice(0, 200)}{sig.body.length > 200 ? '...' : ''}
                        </div>
                      )}
                      <textarea
                        className="story-signal-notes"
                        placeholder="Editor notes for this signal..."
                        defaultValue={ss.editor_notes || ''}
                        onBlur={e => updateSignalNotes(ss.id, e.target.value)}
                        rows={2}
                      />
                    </div>
                  )
                })
              )}
            </div>

            {/* Signal Discovery */}
            <div className="story-section">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div className="section-label" style={{ margin: 0 }}>Find Signals</div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    className={`btn btn-sm ${discovering === 'wire' ? 'loading' : ''}`}
                    onClick={() => discoverSignals('wire')}
                    disabled={!!discovering || (selected.signals || []).length === 0}
                    title="Rank existing wire signals by relevance to this story"
                  >
                    {discovering === 'wire' ? 'Scanning...' : 'Search Wire'}
                  </button>
                  <button
                    className={`btn btn-sm ${discovering === 'web' ? 'loading' : ''}`}
                    onClick={() => discoverSignals('web')}
                    disabled={!!discovering}
                    title="Search the web for new signals related to this story"
                    style={{ borderColor: 'var(--amber)', color: 'var(--amber)' }}
                  >
                    {discovering === 'web' ? 'Searching...' : 'Search Web'}
                  </button>
                </div>
              </div>
              {discovered.length > 0 && (
                <div className="story-wire-list">
                  {discovered.map(s => (
                    <div key={s.id} className="story-wire-item" style={{ borderLeft: '2px solid var(--amber)' }}>
                      <span className="story-signal-type">{s.type || 'web'}</span>
                      <span className="story-wire-title">{s.title}</span>
                      <button className="btn btn-sm btn-approve" onClick={() => { addSignal(s.id); setDiscovered(prev => prev.filter(d => d.id !== s.id)) }}>+</button>
                    </div>
                  ))}
                </div>
              )}
              {discovering && (
                <p style={{ color: 'var(--amber)', fontSize: 11, margin: '8px 0 0' }}>
                  {discovering === 'web' ? 'Searching the web for related signals...' : 'Ranking wire signals by relevance...'}
                </p>
              )}
            </div>

            {/* Add from wire */}
            {availableSignals.length > 0 && (
              <div className="story-section">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <div className="section-label" style={{ margin: 0 }}>Add from Wire ({filteredSignals.length}{signalTypeFilter ? ` of ${availableSignals.length}` : ''})</div>
                  {signalTypes.length > 1 && (
                    <select
                      value={signalTypeFilter}
                      onChange={e => setSignalTypeFilter(e.target.value)}
                      style={{ fontSize: 10, padding: '2px 4px', background: 'var(--bg-card)', color: 'var(--text)', border: '1px solid var(--border)', cursor: 'pointer' }}
                    >
                      <option value="">all types</option>
                      {signalTypes.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                  )}
                </div>
                <div className="story-wire-list">
                  {filteredSignals.slice(0, 40).map(s => (
                    <div
                      key={s.id}
                      className="story-wire-item"
                      style={s._table === 'wire' ? { borderLeft: '2px solid var(--green)' } : {}}
                    >
                      <span className="story-signal-type" style={s._table === 'wire' ? { color: 'var(--green)' } : {}}>{s.type}</span>
                      <span className="story-wire-title">{s.title}</span>
                      <button className="btn btn-sm btn-approve" onClick={() => addSignal(s.id)}>+</button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Generate */}
            <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
              <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
                <div style={{ flex: 1 }}>
                  <div className="section-label" style={{ marginBottom: 8 }}>Channels</div>
                  <ChannelPicker selected={selectedChannels} onChange={setSelectedChannels} />
                </div>
                <div>
                  <div className="section-label" style={{ marginBottom: 8 }}>Post As</div>
                  <select
                    className="post-as-select"
                    value={postAs}
                    onChange={e => setPostAs(e.target.value)}
                  >
                    <option value="">Company</option>
                    {teamMembers.map(m => (
                      <option key={m.id} value={m.id}>{m.name}{m.title ? ` — ${m.title}` : ''}</option>
                    ))}
                  </select>
                </div>
              </div>
              <button
                className={`btn btn-approve ${generating ? 'loading' : ''}`}
                onClick={generateFromStory}
                disabled={generating || (selected.signals || []).length === 0 || selectedChannels.length === 0}
                style={{ width: '100%', padding: '10px 0', fontSize: 13, marginTop: 12 }}
              >
                {generating ? 'Generating...' : `Generate ${selectedChannels.length} Channels (${selected.signals?.length || 0} signals)`}
              </button>
            </div>

            {/* Generated content linked to this story */}
            {storyContent.length > 0 && (
              <div style={{ marginTop: 24, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
                <div className="section-label" style={{ marginBottom: 10 }}>
                  Generated Content ({storyContent.length})
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {storyContent.map(c => (
                    <div key={c.id} style={{
                      border: '1px solid var(--border)',
                      background: 'var(--bg-card)',
                      padding: '10px 14px',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6, gap: 8 }}>
                        <span style={{ fontSize: 10, letterSpacing: 1, color: 'var(--accent)', textTransform: 'uppercase' }}>
                          {c.channel}
                        </span>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <CopyBtn text={c.body} />
                          <span style={{
                            fontSize: 10, padding: '1px 6px',
                            border: `1px solid ${c.status === 'approved' ? 'var(--green)' : c.status === 'published' ? 'var(--text-dim)' : 'var(--border)'}`,
                            color: c.status === 'approved' ? 'var(--green)' : c.status === 'published' ? 'var(--text-dim)' : 'var(--accent)',
                          }}>
                            {c.status.toUpperCase()}
                          </span>
                        </div>
                      </div>
                      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, lineHeight: 1.3 }}>
                        {c.headline?.replace(/^(LINKEDIN|BLOG DRAFT|X THREAD|EMAIL|NEWSLETTER)\s*/i, '')}
                      </div>
                      <div
                        style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.5, whiteSpace: 'pre-wrap', maxHeight: expandedContent === c.id ? 'none' : 120, overflow: 'hidden', cursor: c.body?.length > 300 ? 'pointer' : 'default' }}
                        onClick={() => c.body?.length > 300 && setExpandedContent(expandedContent === c.id ? null : c.id)}
                      >
                        {expandedContent === c.id ? c.body : (c.body?.slice(0, 300) + (c.body?.length > 300 ? '…' : ''))}
                      </div>
                      {c.body?.length > 300 && (
                        <button
                          onClick={() => setExpandedContent(expandedContent === c.id ? null : c.id)}
                          style={{ background: 'none', border: 'none', color: 'var(--text-dim)', fontSize: 10, cursor: 'pointer', padding: '2px 0', marginTop: 2, letterSpacing: 0.5 }}
                        >
                          {expandedContent === c.id ? '▲ collapse' : '▼ show all'}
                        </button>
                      )}
                      {c.status === 'queued' && (
                        <div style={{ marginTop: 8 }}>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button
                              className="btn btn-approve"
                              style={{ fontSize: 10, padding: '3px 12px' }}
                              onClick={async () => {
                                await fetch(`${API}/content/${c.id}/action`, {
                                  method: 'POST', headers,
                                  body: JSON.stringify({ action: 'approve' }),
                                })
                                fetchStoryContent(selectedId)
                              }}
                            >
                              Approve
                            </button>
                            <button
                              className="btn"
                              style={{ fontSize: 10, padding: '3px 10px', color: 'var(--accent)', borderColor: 'var(--accent)' }}
                              onClick={() => {
                                setRevisingId(revisingId === c.id ? null : c.id)
                                setReviseFeedback('')
                              }}
                            >
                              {revisingId === c.id ? 'Cancel' : 'Revise'}
                            </button>
                            <button
                              className="btn"
                              style={{ fontSize: 10, padding: '3px 10px', color: 'var(--error)', borderColor: 'var(--error)' }}
                              onClick={async () => {
                                await fetch(`${API}/content/${c.id}/action`, {
                                  method: 'POST', headers,
                                  body: JSON.stringify({ action: 'spike' }),
                                })
                                fetchStoryContent(selectedId)
                              }}
                            >
                              Spike
                            </button>
                          </div>
                          {revisingId === c.id && (
                            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                              <textarea
                                className="setting-input"
                                placeholder="What should change? (tone, angle, length, specific edits...)"
                                value={reviseFeedback}
                                onChange={e => setReviseFeedback(e.target.value)}
                                style={{ fontSize: 11, minHeight: 60, resize: 'vertical', width: '100%' }}
                                autoFocus
                              />
                              <button
                                className="btn btn-run"
                                style={{ fontSize: 10, padding: '4px 14px', alignSelf: 'flex-start' }}
                                disabled={revisingSubmitting}
                                onClick={async () => {
                                  setRevisingSubmitting(true)
                                  await fetch(`${API}/pipeline/regenerate/${c.id}`, {
                                    method: 'POST', headers,
                                    body: JSON.stringify({ feedback: reviseFeedback }),
                                  })
                                  setRevisingId(null)
                                  setReviseFeedback('')
                                  setRevisingSubmitting(false)
                                  fetchStoryContent(selectedId)
                                }}
                              >
                                {revisingSubmitting ? 'Revising...' : 'Rewrite'}
                              </button>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
