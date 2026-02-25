import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
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

const SIGNAL_TYPE_LABELS = {
  github_release: 'release',
  github_commit: 'commit',
  hackernews: 'hn',
  reddit: 'reddit',
  rss: 'rss',
  web_search: 'web',
  trend: 'trend',
  support: 'support',
  performance: 'perf',
}

const CHANNEL_LABELS = {
  linkedin: 'LinkedIn',
  x_thread: 'X Thread',
  facebook: 'Facebook',
  blog: 'Blog',
  devto: 'Dev.to',
  github_gist: 'GitHub Gist',
  release_email: 'Email',
  newsletter: 'Newsletter',
  yt_script: 'YT Script',
}

function typeLabel(type) {
  return SIGNAL_TYPE_LABELS[type] || type || '?'
}

export default function StoryDesk({
  orgId,
  signals,
  allContent,
  queue,
  loading,
  onRunScout,
  onRunGenerate,
  onRunPublish,
  onRunFull,
  selectedChannels,
  setSelectedChannels,
  postAs,
  setPostAs,
  teamMembers,
  log,
  onRewrite,
  refresh,
  streamLine,
  contentAction,
  channelLabel,
  timeAgo,
  isAnyLoading,
  queuedCount,
  approvedCount,
  publishedCount,
  // legacy props we accept but don't use:
  ...rest
}) {
  const headers = orgHeaders(orgId)

  // ── Sidebar state ──
  const [sidebarTab, setSidebarTab] = useState('stories')
  const [sidebarTypeFilter, setSidebarTypeFilter] = useState('')

  // ── Story state ──
  const [stories, setStories] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [selected, setSelected] = useState(null)
  const [storyContent, setStoryContent] = useState([])
  const [storiesLoading, setStoriesLoading] = useState(true)
  const [generating, setGenerating] = useState(false)

  // ── Signal picker modal ──
  const [showSignalPicker, setShowSignalPicker] = useState(false)
  const [pickerTab, setPickerTab] = useState('wire')
  const [pickerSearch, setPickerSearch] = useState('')
  const [pickerTypeFilter, setPickerTypeFilter] = useState('')
  const [discovering, setDiscovering] = useState(null)
  const [discovered, setDiscovered] = useState([])

  // ── Ideas state ──
  const [ideas, setIdeas] = useState([])
  const [ideasLoading, setIdeasLoading] = useState(false)
  const [ideasCount, setIdeasCount] = useState(5)
  const [prioritySignalIds, setPrioritySignalIds] = useState([])
  const [makingStoryFromIdea, setMakingStoryFromIdea] = useState(null)

  // ── Wire signals ──
  const [wireSignals, setWireSignals] = useState([])

  // ── Complete section collapsed ──
  const [completeCollapsed, setCompleteCollapsed] = useState(false)

  // ── Content state ──
  const [contentFilter, setContentFilter] = useState('all')
  const [expandedContent, setExpandedContent] = useState(null)
  const [contextOpen, setContextOpen] = useState(false)
  const [revisingId, setRevisingId] = useState(null)
  const [reviseFeedback, setReviseFeedback] = useState('')
  const [revisingSubmitting, setRevisingSubmitting] = useState(false)
  const [publishErrors, setPublishErrors] = useState({}) // { contentId: errorMessage }
  const [perfMap, setPerfMap] = useState({}) // { contentId: { likes, comments, shares, ... } }

  // ── Data fetching ──
  const fetchStories = useCallback(async () => {
    try {
      const res = await fetch(`${API}/stories`, { headers })
      const data = await res.json()
      setStories(Array.isArray(data) ? data : [])
    } catch (e) { console.error('fetchStories failed:', e) }
    setStoriesLoading(false)
  }, [orgId])

  const fetchStory = useCallback(async (id) => {
    try {
      const res = await fetch(`${API}/stories/${id}`, { headers })
      if (!res.ok) { console.error('fetchStory error:', res.status); return }
      const data = await res.json()
      if (!data.error) setSelected(data)
    } catch (e) { console.error('fetchStory failed:', e) }
  }, [orgId])

  const fetchStoryContent = useCallback(async (id) => {
    try {
      const res = await fetch(`${API}/stories/${id}/content`, { headers })
      if (!res.ok) { console.error('fetchStoryContent error:', res.status); return }
      const data = await res.json()
      setStoryContent(Array.isArray(data) ? data : [])
    } catch (e) { console.error('fetchStoryContent failed:', e) }
  }, [orgId])

  // Fetch performance metrics for all published content
  const fetchPerformance = useCallback(async () => {
    try {
      const res = await fetch(`${API}/content/published/performance`, { headers })
      if (res.ok) {
        const data = await res.json()
        setPerfMap(data || {})
      }
    } catch { /* silent */ }
  }, [orgId])

  // Fetch stats for a single content item on demand
  const fetchSinglePerf = async (contentId) => {
    try {
      const res = await fetch(`${API}/content/${contentId}/fetch-performance`, { method: 'POST', headers })
      const data = await res.json()
      if (data.stats && Object.values(data.stats).some(v => v > 0)) {
        setPerfMap(prev => ({ ...prev, [contentId]: data.stats }))
        log?.(`STATS [${data.channel}] #${contentId} — ${Object.entries(data.stats).filter(([,v]) => v > 0).map(([k,v]) => `${v} ${k}`).join(', ')}`, 'success')
      } else {
        log?.(`STATS [${data.channel}] #${contentId} — no engagement data yet`, 'info')
      }
    } catch { /* silent */ }
  }

  useEffect(() => { fetchStories() }, [fetchStories])

  // Load performance data when org changes
  useEffect(() => { if (orgId) fetchPerformance() }, [orgId, fetchPerformance])

  useEffect(() => {
    setExpandedContent(null)
    if (selectedId) {
      fetchStory(selectedId)
      fetchStoryContent(selectedId)
    } else {
      setSelected(null)
      setStoryContent([])
    }
  }, [selectedId, fetchStory, fetchStoryContent])

  useEffect(() => {
    fetch(`${API}/wire/signals?limit=200`, { headers })
      .then(r => r.json())
      .then(d => {
        const items = Array.isArray(d) ? d : (d.signals || [])
        setWireSignals(items.map(ws => ({
          id: `wire:${ws.id}`,
          type: ws.type,
          title: ws.title,
          body: ws.body || '',
          url: ws.url || '',
          source: ws.source_name || ws.source || '',
          _table: 'wire',
        })))
      })
      .catch(() => {})
  }, [orgId])

  // Reset on org change
  useEffect(() => {
    setSelectedId(null)
    setSelected(null)
    setStoryContent([])
    setStories([])
    setStoriesLoading(true)
  }, [orgId])

  // ── Story CRUD ──
  const createStory = async () => {
    try {
      const res = await fetch(`${API}/stories`, {
        method: 'POST', headers, body: JSON.stringify({ title: 'New Story' })
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      const data = await res.json()
      if (data.id) {
        await fetchStories()
        setSelectedId(data.id)
        setSidebarTab('stories')
        log?.('STORY CREATED — click title to rename, add signals', 'success')
      }
    } catch (e) {
      log?.(`STORY CREATE FAILED — ${e.message}`, 'error')
    }
  }

  const updateField = async (field, value) => {
    if (!selectedId) return
    setSelected(prev => ({ ...prev, [field]: value }))
    try {
      const res = await fetch(`${API}/stories/${selectedId}`, {
        method: 'PUT', headers, body: JSON.stringify({ [field]: value })
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      fetchStories()
    } catch (e) {
      log?.(`SAVE FAILED — ${field}: ${e.message}`, 'error')
    }
  }

  const deleteStory = async (id) => {
    if (!confirm('Delete this story and all its content?')) return
    try {
      const res = await fetch(`${API}/stories/${id}`, { method: 'DELETE', headers })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      if (selectedId === id) { setSelectedId(null); setSelected(null) }
      fetchStories()
      log?.('STORY DELETED', 'warn')
    } catch (e) {
      log?.(`DELETE FAILED — ${e.message}`, 'error')
    }
  }

  // ── Ideas ──
  const loadSavedIdeas = useCallback(async () => {
    try {
      const res = await fetch(`${API}/pipeline/ideas`, { headers })
      if (!res.ok) return
      const data = await res.json()
      if (data.ideas?.length > 0) setIdeas(data.ideas)
    } catch (e) { /* silent */ }
  }, [headers])

  useEffect(() => { loadSavedIdeas() }, [loadSavedIdeas])

  const fetchIdeas = async () => {
    setIdeasLoading(true)
    setIdeas([])
    try {
      const res = await fetch(`${API}/pipeline/ideas`, {
        method: 'POST', headers,
        body: JSON.stringify({ count: ideasCount, priority_signal_ids: prioritySignalIds })
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      const data = await res.json()
      if (data.error) { log?.(`IDEAS ERROR — ${data.error}`, 'error'); return }
      setIdeas(data.ideas || [])
      log?.(`${data.ideas?.length || 0} ideas generated from ${data.signal_count} signals`, 'detail')
    } catch (e) {
      log?.(`IDEAS FAILED — ${e.message}`, 'error')
    } finally {
      setIdeasLoading(false)
    }
  }

  const makeStoryFromIdea = async (idea) => {
    setMakingStoryFromIdea(idea.title)
    try {
      // Create story with idea title
      const res = await fetch(`${API}/stories`, {
        method: 'POST', headers,
        body: JSON.stringify({ title: idea.title, angle: idea.angle })
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      const story = await res.json()
      if (!story.id) throw new Error('No story ID returned')

      // Attach priority signals from the idea
      const sigIds = (idea.signal_ids || []).slice(0, 5)
      for (const sigId of sigIds) {
        await fetch(`${API}/stories/${story.id}/signals`, {
          method: 'POST', headers,
          body: JSON.stringify({ signal_id: sigId })
        })
      }

      await fetchStories()
      setSelectedId(story.id)
      setSidebarTab('stories')
      log?.(`STORY CREATED — "${idea.title}" — ${sigIds.length} signals attached`, 'success')
    } catch (e) {
      log?.(`MAKE STORY FAILED — ${e.message}`, 'error')
    } finally {
      setMakingStoryFromIdea(null)

    }
  }

  const clearIdeas = async () => {
    try {
      await fetch(`${API}/pipeline/ideas`, { method: 'DELETE', headers })
      setIdeas([])
    } catch (e) {
      log?.(`CLEAR IDEAS FAILED — ${e.message}`, 'error')
    }
  }

  // ── Signal management ──
  const addSignal = async (signalId) => {
    if (!selectedId) return
    try {
      const res = await fetch(`${API}/stories/${selectedId}/signals`, {
        method: 'POST', headers, body: JSON.stringify({ signal_id: signalId })
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      fetchStory(selectedId)
      fetchStories()
      log?.('Signal added to story', 'detail')
    } catch (e) {
      log?.(`ADD SIGNAL FAILED — ${e.message}`, 'error')
    }
  }

  const removeSignal = async (storySignalId) => {
    if (!selectedId) return
    try {
      const res = await fetch(`${API}/stories/${selectedId}/signals/${storySignalId}`, {
        method: 'DELETE', headers
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      fetchStory(selectedId)
      fetchStories()
    } catch (e) {
      log?.(`REMOVE SIGNAL FAILED — ${e.message}`, 'error')
    }
  }

  const togglePriority = async (signalId) => {
    try {
      await fetch(`${API}/signals/${signalId}/prioritize`, { method: 'PATCH', headers })
      refresh?.()
    } catch { /* silent */ }
  }

  // ── Discover signals ──
  const discoverSignals = async (mode) => {
    if (!selectedId) return
    setDiscovering(mode)
    setDiscovered([])
    log?.(`DISCOVER — ${mode === 'web' ? 'searching the web' : 'scanning wire'}...`, 'action')
    try {
      const res = await fetch(`${API}/stories/${selectedId}/discover`, {
        method: 'POST', headers, body: JSON.stringify({ mode })
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      const data = await res.json()
      if (data.error) {
        log?.(`DISCOVER FAILED — ${data.error}`, 'error')
      } else {
        const found = data.signals || []
        setDiscovered(found)
        log?.(`DISCOVER — found ${found.length} related signal${found.length === 1 ? '' : 's'}`, found.length > 0 ? 'success' : 'info')
      }
    } catch (e) {
      log?.(`DISCOVER FAILED — ${e.message}`, 'error')
    }
    setDiscovering(null)
  }

  // ── Generate from story ──
  const generateFromStory = async () => {
    if (!selectedId || selectedChannels.length === 0) return
    saveChannels(orgId, selectedChannels)
    setGenerating(true)
    log?.(`GENERATE — writing ${selectedChannels.length} channel${selectedChannels.length === 1 ? '' : 's'} for "${selected?.title}"...`, 'action')
    try {
      const res = await fetch(`${API}/stories/${selectedId}/generate`, {
        method: 'POST', headers, body: JSON.stringify({
          channels: selectedChannels,
          team_member_id: postAs ? Number(postAs) : null,
        })
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      const data = await res.json()
      if (data.error) {
        log?.(`GENERATE ERROR — ${data.error}`, 'error')
      } else {
        log?.(`GENERATE COMPLETE — ${data.generated || 0} item${(data.generated || 0) !== 1 ? 's' : ''} queued for review`, 'success')
      }
      fetchStory(selectedId)
      fetchStories()
      fetchStoryContent(selectedId)
    } catch (e) {
      log?.(`GENERATE FAILED — ${e.message}`, 'error')
    }
    setGenerating(false)
  }

  // ── Revise handler — calls regenerate API directly ──
  const handleRevise = async (contentId) => {
    if (!reviseFeedback.trim()) return
    setRevisingSubmitting(true)
    log?.(`REWRITE — rewriting with feedback...`, 'action')
    try {
      const res = await fetch(`${API}/pipeline/regenerate/${contentId}`, {
        method: 'POST', headers, body: JSON.stringify({ feedback: reviseFeedback })
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      const data = await res.json()
      if (data.error) {
        log?.(`REWRITE FAILED — ${data.error}`, 'error')
      } else {
        log?.(`REWRITE DONE — ${data.headline?.slice(0, 80)}`, 'success')
        setRevisingId(null)
        setReviseFeedback('')
        if (selectedId) fetchStoryContent(selectedId)
        refresh?.()
      }
    } catch (e) {
      log?.(`REWRITE FAILED — ${e.message}`, 'error')
    }
    setRevisingSubmitting(false)
  }

  // ── Content action wrapper ──
  const handleContentAction = async (id, action) => {
    await contentAction(id, action)
    if (selectedId) fetchStoryContent(selectedId)
    refresh?.()
  }

  // ── Publish single ──
  const publishSingle = async (contentId) => {
    setPublishErrors(prev => ({ ...prev, [contentId]: null }))
    try {
      const res = await fetch(`${API}/content/${contentId}/publish`, { method: 'POST', headers })
      const data = await res.json()
      if (!res.ok) {
        const msg = data.detail || `Server error (${res.status})`
        setPublishErrors(prev => ({ ...prev, [contentId]: msg }))
        log?.(`PUBLISH ERROR [${res.status}] — ${msg}`, 'error')
        return
      }
      if (data.result?.error) {
        setPublishErrors(prev => ({ ...prev, [contentId]: data.result.error }))
        log?.(`PUBLISH ERROR [${data.channel}] — ${data.result.error}`, 'error')
        return
      }
      setPublishErrors(prev => ({ ...prev, [contentId]: null }))
      const url = data.result?.devto_url || data.result?.url || ''
      log?.(`PUBLISHED [${data.channel}]${url ? ' → ' + url : ''}`, 'success')
      if (selectedId) fetchStoryContent(selectedId)
      refresh?.()
    } catch (e) {
      setPublishErrors(prev => ({ ...prev, [contentId]: e.message }))
      log?.(`PUBLISH FAILED — ${e.message}`, 'error')
    }
  }

  // ── Computed values ──
  const storySignalIds = useMemo(() => {
    return new Set((selected?.signals || []).map(ss => {
      const sig = ss.signal || {}
      return sig.id ?? ss.signal_id
    }))
  }, [selected])

  const allAvailableSignals = useMemo(() => {
    const scout = (signals || []).map(s => ({ ...s, _table: 'scout' }))
    const wire = wireSignals
    return [...scout, ...wire]
  }, [signals, wireSignals])

  const sidebarSignals = useMemo(() => {
    let list = allAvailableSignals
    if (sidebarTypeFilter) list = list.filter(s => s.type === sidebarTypeFilter)
    return list
  }, [allAvailableSignals, sidebarTypeFilter])

  const pickerSignals = useMemo(() => {
    let list = allAvailableSignals
    if (pickerTypeFilter) list = list.filter(s => s.type === pickerTypeFilter)
    if (pickerSearch) {
      const q = pickerSearch.toLowerCase()
      list = list.filter(s => (s.title || '').toLowerCase().includes(q))
    }
    return list
  }, [allAvailableSignals, pickerTypeFilter, pickerSearch])

  const signalTypes = useMemo(() => {
    return [...new Set(allAvailableSignals.map(s => s.type).filter(Boolean))].sort()
  }, [allAvailableSignals])

  const filteredStoryContent = useMemo(() => {
    if (contentFilter === 'all') return storyContent
    return storyContent.filter(c => c.status === contentFilter)
  }, [storyContent, contentFilter])

  const activeStories = useMemo(() => stories.filter(s => s.status !== 'complete'), [stories])
  const completeStories = useMemo(() => stories.filter(s => s.status === 'complete'), [stories])

  const statusColor = { draft: 'var(--text-dim)', generating: 'var(--amber)', complete: 'var(--green)' }

  // ── Keyboard shortcut: N for new story ──
  const createStoryRef = useRef(createStory)
  createStoryRef.current = createStory
  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return
      if (e.key.toLowerCase() === 'n') { e.preventDefault(); createStoryRef.current() }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Auto-expand context if angle or notes have content
  useEffect(() => {
    if (selected && (selected.angle || selected.editorial_notes)) {
      setContextOpen(true)
    } else {
      setContextOpen(false)
    }
  }, [selectedId])

  // ── RENDER ──
  return (
    <div className="sd-layout">
      {/* ═══════ LEFT SIDEBAR ═══════ */}
      <div className="sd-sidebar">
        <div className="sd-sidebar-tabs">
          <button
            className={`sd-sidebar-tab ${sidebarTab === 'stories' ? 'active' : ''}`}
            onClick={() => setSidebarTab('stories')}
          >Stories</button>
          <button
            className={`sd-sidebar-tab ${sidebarTab === 'signals' ? 'active' : ''}`}
            onClick={() => setSidebarTab('signals')}
          >Signals ({signals?.length || 0})</button>
          <button
            className={`sd-sidebar-tab ${sidebarTab === 'ideas' ? 'active' : ''}`}
            onClick={() => setSidebarTab('ideas')}
          >Ideas</button>
        </div>

        {sidebarTab === 'stories' ? (
          <>
            <button className="sd-new-story-btn" onClick={createStory}>+ New Story</button>
            <div className="sd-story-list">
              {storiesLoading ? (
                <p style={{ color: 'var(--text-dim)', padding: 12, fontSize: 11 }}>Loading...</p>
              ) : stories.length === 0 ? (
                <p style={{ color: 'var(--text-dim)', padding: 12, fontSize: 11 }}>
                  No stories yet. Create one to start.
                </p>
              ) : (
                <>
                  {activeStories.map(s => (
                    <div
                      key={s.id}
                      className={`sd-story-card ${selectedId === s.id ? 'active' : ''}`}
                      onClick={() => setSelectedId(selectedId === s.id ? null : s.id)}
                    >
                      <div className="sd-story-title">{s.title || 'Untitled'}</div>
                      <div className="sd-story-meta">
                        <span style={{ color: statusColor[s.status] || 'var(--text-dim)' }}>{s.status}</span>
                        <span><span className="dot">{'\u25CF'}</span> {s.signal_count || 0}</span>
                      </div>
                    </div>
                  ))}
                  {completeStories.length > 0 && (
                    <>
                      <div
                        className="sd-complete-toggle"
                        onClick={() => setCompleteCollapsed(c => !c)}
                      >
                        <span>{completeCollapsed ? '\u25B8' : '\u25BE'}</span>
                        <span>Complete ({completeStories.length})</span>
                      </div>
                      {!completeCollapsed && completeStories.map(s => (
                        <div
                          key={s.id}
                          className={`sd-story-card complete ${selectedId === s.id ? 'active' : ''}`}
                          onClick={() => setSelectedId(selectedId === s.id ? null : s.id)}
                        >
                          <div className="sd-story-title">{s.title || 'Untitled'}</div>
                          <div className="sd-story-meta">
                            <span style={{ color: 'var(--green)' }}>complete</span>
                            <span><span className="dot">{'\u25CF'}</span> {s.signal_count || 0}</span>
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                </>
              )}
            </div>
          </>
        ) : sidebarTab === 'ideas' ? (
          <div className="sd-ideas-panel">
            <div className="sd-ideas-controls">
              <div className="sd-ideas-count">
                <label>Ideas</label>
                <input
                  type="number" min={1} max={20} value={ideasCount}
                  onChange={e => setIdeasCount(Math.max(1, Math.min(20, parseInt(e.target.value) || 5)))}
                />
              </div>
              <button
                className={`btn btn-run ${ideasLoading ? 'loading' : ''}`}
                onClick={fetchIdeas}
                disabled={ideasLoading}
              >{ideasLoading ? 'Thinking...' : 'Generate'}</button>
              {ideas.length > 0 && (
                <button className="btn btn-sm" onClick={clearIdeas} title="Clear ideas" style={{ opacity: 0.6 }}>✕</button>
              )}
            </div>
            {ideas.length > 0 && (
              <div className="sd-ideas-list">
                {ideas.map((idea, i) => (
                  <div key={i} className="sd-idea-card">
                    <div className="sd-idea-title">{idea.title}</div>
                    <div className="sd-idea-angle">{idea.angle}</div>
                    {idea.rationale && <div className="sd-idea-rationale">{idea.rationale}</div>}
                    {idea.channels && idea.channels.length > 0 && (
                      <div className="sd-idea-channels">
                        {idea.channels.map(ch => <span key={ch} className="sd-idea-ch">{ch}</span>)}
                      </div>
                    )}
                    <button
                      className="sd-idea-make-story"
                      onClick={() => makeStoryFromIdea(idea)}
                      disabled={makingStoryFromIdea === idea.title}
                    >
                      {makingStoryFromIdea === idea.title ? 'Creating...' : '→ Make Story'}
                    </button>
                  </div>
                ))}
              </div>
            )}
            {!ideasLoading && ideas.length === 0 && (
              <p className="sd-ideas-empty">Hit Generate to get content ideas from your signal feed.</p>
            )}
          </div>
        ) : (
          <>
            <div className="sd-signal-filter">
              <select value={sidebarTypeFilter} onChange={e => setSidebarTypeFilter(e.target.value)}>
                <option value="">All types</option>
                {signalTypes.map(t => <option key={t} value={t}>{typeLabel(t)}</option>)}
              </select>
            </div>
            <div className="sd-signal-list">
              {sidebarSignals.length === 0 ? (
                <p style={{ color: 'var(--text-dim)', padding: 12, fontSize: 11 }}>
                  No signals. Run Scout to pull from sources.
                </p>
              ) : (
                sidebarSignals.map(s => (
                  <div key={s.id} className="sd-signal-item">
                    <span className="sd-signal-type">{typeLabel(s.type)}</span>
                    <span className="sd-signal-title">
                      {s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>{s.title}</a> : s.title}
                    </span>
                    <div className="sd-signal-actions">
                      <button
                        className={`star ${s.prioritized ? 'active' : ''}`}
                        onClick={() => togglePriority(s.id)}
                        title={s.prioritized ? 'Remove priority' : 'Prioritize'}
                      >{s.prioritized ? '\u2605' : '\u2606'}</button>
                      {selectedId && (
                        <button
                          onClick={() => addSignal(s.id)}
                          title="Add to story"
                          disabled={storySignalIds.has(s.id)}
                        >+</button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>

      {/* ═══════ MAIN WORKSPACE ═══════ */}
      <div className="sd-workspace">
        {/* ── Toolbar ── */}
        <div className="sd-toolbar">
          <button className={`btn btn-run ${loading.scout ? 'loading' : ''}`} onClick={onRunScout} disabled={loading.scout}>
            {loading.scout ? 'Scouting...' : 'Scout [S]'}
          </button>
          <button
            className={`btn btn-run ${generating ? 'loading' : ''}`}
            onClick={selectedId ? generateFromStory : createStory}
            disabled={generating || (selectedId && selectedChannels.length === 0)}
          >
            {generating ? 'Generating...' : selectedId ? 'Generate [G]' : 'New Story [G]'}
          </button>
          <button className={`btn btn-engine ${loading.full ? 'loading' : ''}`} onClick={onRunFull} disabled={loading.full || loading.scout}>
            {loading.full ? 'Engine Running...' : '⚡ Run Engine [R]'}
          </button>
          <button
            className="btn btn-approve"
            onClick={onRunPublish}
            disabled={loading.publish || approvedCount === 0}
          >
            {loading.publish ? 'Publishing...' : 'Publish [P]'}
          </button>
          <div className="sd-toolbar-stats">
            <span>Q:<span className="val">{queuedCount}</span></span>
            <span>A:<span className="val">{approvedCount}</span></span>
            <span>P:<span className="val">{publishedCount}</span></span>
          </div>
        </div>

        {/* ── Story workspace or empty state ── */}
        {!selectedId ? (
          <div className="sd-empty">
            <p>Select a story or create one to get started.</p>
            <button onClick={createStory}>+ New Story</button>
          </div>
        ) : !selected ? (
          <p style={{ color: 'var(--text-dim)', fontSize: 11 }}>Loading story...</p>
        ) : (
          <>
            {/* ── Story Header ── */}
            <div className="sd-header">
              <span className="sd-status-dot" style={{ background: statusColor[selected.status] || 'var(--text-dim)' }} title={selected.status} />
              <input
                value={selected.title || ''}
                onChange={e => setSelected(prev => ({ ...prev, title: e.target.value }))}
                onBlur={e => updateField('title', e.target.value)}
                placeholder="Story title..."
              />
              <button className="sd-delete-btn" onClick={() => deleteStory(selectedId)}>Delete</button>
            </div>

            {/* ── Angle & Notes (collapsible) ── */}
            <div>
              <button className="sd-context-toggle" onClick={() => setContextOpen(o => !o)}>
                {contextOpen ? '\u25BE' : '\u25B8'} Angle & Notes
                {!contextOpen && selected.angle && <span style={{ color: 'var(--text-dim)', marginLeft: 8, fontSize: 10 }}>({selected.angle.slice(0, 40)}...)</span>}
              </button>
              {contextOpen && (
                <div className="sd-context-fields">
                  <div>
                    <label>Angle</label>
                    <input
                      value={selected.angle || ''}
                      onChange={e => setSelected(prev => ({ ...prev, angle: e.target.value }))}
                      onBlur={e => updateField('angle', e.target.value)}
                      placeholder="What's the editorial angle?"
                    />
                  </div>
                  <div>
                    <label>Notes</label>
                    <textarea
                      value={selected.editorial_notes || ''}
                      onChange={e => setSelected(prev => ({ ...prev, editorial_notes: e.target.value }))}
                      onBlur={e => updateField('editorial_notes', e.target.value)}
                      placeholder="Context, direction, things to emphasize..."
                      rows={2}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* ── Signals Strip ── */}
            <div>
              <div className="sd-section-label">Signals</div>
              <div className="sd-signals-strip">
                {(selected.signals || []).length === 0 && (
                  <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>No signals yet — add some to give the AI context</span>
                )}
                {(selected.signals || []).map(ss => {
                  const sig = ss.signal || {}
                  return (
                    <span key={ss.id} className="sd-signal-chip">
                      <span className="chip-type">{typeLabel(sig.type)}</span>
                      <span className="chip-title">{sig.title || 'Signal'}</span>
                      <button className="chip-remove" onClick={() => removeSignal(ss.id)}>&times;</button>
                    </span>
                  )
                })}
                <button className="sd-add-signal-btn" onClick={() => { setShowSignalPicker(true); setPickerSearch(''); setDiscovered([]) }}>
                  + Add Signal
                </button>
              </div>
            </div>

            {/* ── Action Bar ── */}
            <div>
              <div className="sd-section-label">Generate</div>
              <div className="sd-action-bar">
                <ChannelPicker selected={selectedChannels} onChange={setSelectedChannels} />
                <select className="sd-post-as" value={postAs || ''} onChange={e => setPostAs(e.target.value || null)}>
                  <option value="">Company voice</option>
                  {(teamMembers || []).map(m => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
                <button
                  className={`sd-generate-btn ${generating ? 'loading' : ''}`}
                  onClick={generateFromStory}
                  disabled={generating || selectedChannels.length === 0 || (selected.signals || []).length === 0}
                >
                  {generating ? 'GENERATING...' : 'GENERATE'}
                </button>
              </div>
            </div>

            {/* ── Content Section ── */}
              <div>
                <div className="sd-section-label">Content ({storyContent.length})</div>
                {storyContent.length === 0 ? (
                  <p style={{ color: 'var(--text-dim)', fontSize: 11, padding: '8px 0' }}>
                    No content yet — select channels above and hit Generate.
                  </p>
                ) : (<>
                <div className="sd-filter-bar">
                  {['all', 'queued', 'approved', 'published'].map(f => (
                    <button
                      key={f}
                      className={`sd-filter-tab ${contentFilter === f ? 'active' : ''}`}
                      onClick={() => setContentFilter(f)}
                    >
                      {f} {f !== 'all' ? `(${storyContent.filter(c => c.status === f).length})` : `(${storyContent.length})`}
                    </button>
                  ))}
                </div>
                <div className="sd-content-grid">
                  {filteredStoryContent.map(c => (
                    <div key={c.id} className={`sd-content-card ${c.status}`}>
                      <div className="sd-card-top">
                        <span className="sd-card-channel">{CHANNEL_LABELS[c.channel] || c.channel}</span>
                        <CopyBtn text={c.body} />
                        <span className={`sd-card-status ${c.status}`}>{c.status}</span>
                      </div>
                      <div className="sd-card-headline">{c.headline || 'Untitled'}</div>
                      <div
                        className={`sd-card-body ${expandedContent === c.id ? 'expanded' : ''}`}
                        onClick={() => setExpandedContent(expandedContent === c.id ? null : c.id)}
                      >
                        {c.body || ''}
                      </div>
                      <div className="sd-card-actions">
                        {c.status === 'queued' && (
                          <>
                            <button className="act-approve" onClick={() => handleContentAction(c.id, 'approve')}>Approve</button>
                            <button className="act-revise" onClick={() => { setRevisingId(revisingId === c.id ? null : c.id); setReviseFeedback('') }}>Revise</button>
                            <button className="act-spike" onClick={() => handleContentAction(c.id, 'spike')}>Spike</button>
                          </>
                        )}
                        {c.status === 'approved' && (
                          <>
                            <button className="act-publish" onClick={() => publishSingle(c.id)}>Publish</button>
                            <button className="act-spike" onClick={() => handleContentAction(c.id, 'unapprove')}>Unapprove</button>
                          </>
                        )}
                        {publishErrors[c.id] && (
                          <div className="publish-error-inline">⚠ {publishErrors[c.id]}</div>
                        )}
                        {c.status === 'published' && (
                          <>
                            <button className="act-revise" onClick={() => handleContentAction(c.id, 'unpublish')}>Unpublish</button>
                            {c.post_id && (
                              <button className="act-approve" onClick={() => fetchSinglePerf(c.id)} style={{ fontSize: 10 }}>Fetch Stats</button>
                            )}
                          </>
                        )}
                      </div>
                      {/* Performance metrics for published content */}
                      {c.status === 'published' && perfMap[c.id] && (
                        <div className="sd-card-perf">
                          {perfMap[c.id].likes > 0 && <span className="perf-stat">{perfMap[c.id].likes} likes</span>}
                          {perfMap[c.id].comments > 0 && <span className="perf-stat">{perfMap[c.id].comments} comments</span>}
                          {perfMap[c.id].shares > 0 && <span className="perf-stat">{perfMap[c.id].shares} shares</span>}
                          {perfMap[c.id].impressions > 0 && <span className="perf-stat">{perfMap[c.id].impressions.toLocaleString()} views</span>}
                          {perfMap[c.id].clicks > 0 && <span className="perf-stat">{perfMap[c.id].clicks} clicks</span>}
                        </div>
                      )}
                      {c.status === 'published' && c.post_url && (
                        <div className="sd-card-post-url">
                          <a href={c.post_url} target="_blank" rel="noopener noreferrer">{c.post_url.length > 60 ? c.post_url.slice(0, 60) + '...' : c.post_url}</a>
                        </div>
                      )}
                      {revisingId === c.id && (
                        <div className="sd-revise-inline">
                          <textarea
                            value={reviseFeedback}
                            onChange={e => setReviseFeedback(e.target.value)}
                            placeholder="What should change? (tone, angle, length...)"
                            rows={2}
                          />
                          <button
                            onClick={() => handleRevise(c.id)}
                            disabled={revisingSubmitting || !reviseFeedback.trim()}
                          >
                            {revisingSubmitting ? 'Rewriting...' : 'Rewrite'}
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                </>)}
              </div>

            {/* streaming indicator */}
            {streamLine && (
              <div style={{ color: 'var(--amber)', fontSize: 11, fontFamily: 'var(--font-mono)', padding: '8px 0' }}>
                {streamLine}
              </div>
            )}
          </>
        )}
      </div>

      {/* ═══════ SIGNAL PICKER MODAL ═══════ */}
      {showSignalPicker && (
        <div className="sd-modal-overlay" onClick={() => setShowSignalPicker(false)}>
          <div className="sd-modal" onClick={e => e.stopPropagation()}>
            <div className="sd-modal-header">
              <h3>Add Signals</h3>
              <button onClick={() => setShowSignalPicker(false)}>&times;</button>
            </div>
            <div className="sd-modal-tabs">
              <button
                className={`sd-modal-tab ${pickerTab === 'wire' ? 'active' : ''}`}
                onClick={() => setPickerTab('wire')}
              >Wire</button>
              <button
                className={`sd-modal-tab ${pickerTab === 'discover' ? 'active' : ''}`}
                onClick={() => setPickerTab('discover')}
              >Discover</button>
            </div>

            {pickerTab === 'wire' ? (
              <>
                <div className="sd-modal-search">
                  <input
                    value={pickerSearch}
                    onChange={e => setPickerSearch(e.target.value)}
                    placeholder="Search signals..."
                    autoFocus
                  />
                  <select value={pickerTypeFilter} onChange={e => setPickerTypeFilter(e.target.value)}>
                    <option value="">All</option>
                    {signalTypes.map(t => <option key={t} value={t}>{typeLabel(t)}</option>)}
                  </select>
                </div>
                <div className="sd-picker-list">
                  {pickerSignals.length === 0 ? (
                    <p style={{ color: 'var(--text-dim)', padding: 12, fontSize: 11 }}>No signals match.</p>
                  ) : (
                    pickerSignals.slice(0, 50).map(s => {
                      const isAdded = storySignalIds.has(s.id)
                      return (
                        <div key={s.id} className={`sd-picker-row ${isAdded ? 'added' : ''}`}>
                          <span className="sd-signal-type">{typeLabel(s.type)}</span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div className="pk-title">{s.title}</div>
                            <div className="pk-source">{s.source}</div>
                          </div>
                          <button
                            className="pk-add"
                            onClick={() => addSignal(s.id)}
                            disabled={isAdded}
                            title={isAdded ? 'Already added' : 'Add to story'}
                          >{isAdded ? '\u2713' : '+'}</button>
                        </div>
                      )
                    })
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="sd-discover-actions">
                  <button onClick={() => discoverSignals('wire')} disabled={!!discovering}>
                    {discovering === 'wire' ? 'Searching...' : 'Search Wire'}
                  </button>
                  <button onClick={() => discoverSignals('web')} disabled={!!discovering}>
                    {discovering === 'web' ? 'Searching...' : 'Search Web'}
                  </button>
                </div>
                <div className="sd-picker-list">
                  {discovered.length === 0 && !discovering && (
                    <p style={{ color: 'var(--text-dim)', padding: 12, fontSize: 11, textAlign: 'center' }}>
                      Use the buttons above to find signals related to your story.
                    </p>
                  )}
                  {discovering && (
                    <p style={{ color: 'var(--amber)', padding: 12, fontSize: 11, textAlign: 'center' }}>
                      Searching for related signals...
                    </p>
                  )}
                  {discovered.map(s => {
                    const isAdded = storySignalIds.has(s.id)
                    return (
                      <div key={s.id} className={`sd-picker-row ${isAdded ? 'added' : ''}`}>
                        <span className="sd-signal-type">{typeLabel(s.type)}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div className="pk-title">{s.title}</div>
                          <div className="pk-source">{s.source}</div>
                        </div>
                        <button
                          className="pk-add"
                          onClick={() => addSignal(s.id)}
                          disabled={isAdded}
                        >{isAdded ? '\u2713' : '+'}</button>
                      </div>
                    )
                  })}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
