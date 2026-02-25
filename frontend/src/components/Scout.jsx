import { useState, useEffect, useCallback, useMemo } from 'react'

const API = '/api'

function orgHeaders(orgId) {
  const h = { 'Content-Type': 'application/json' }
  if (orgId) h['X-Org-Id'] = String(orgId)
  return h
}

const SOURCES = [
  {
    key: 'github',
    label: 'GitHub',
    settings: [
      { key: 'scout_github_orgs', sublabel: 'Organizations', placeholder: 'org name (e.g. pressroomhq)' },
      { key: 'scout_github_repos', sublabel: 'Repositories', placeholder: 'org/repo' },
    ],
    signalTypes: ['github_release', 'github_commit'],
    hasSync: true,
  },
  { key: 'hn', label: 'Hacker News', settings: [{ key: 'scout_hn_keywords', placeholder: 'keyword or phrase' }], signalTypes: ['hackernews'] },
  { key: 'reddit', label: 'Reddit', settings: [{ key: 'scout_subreddits', placeholder: 'subreddit name (no r/)' }], signalTypes: ['reddit'] },
  { key: 'rss', label: 'RSS Feeds', settings: [{ key: 'scout_rss_feeds', placeholder: 'https://example.com/feed.xml' }], signalTypes: ['rss'] },
  { key: 'google_news', label: 'Google News', settings: [{ key: 'scout_google_news_keywords', placeholder: 'keyword or phrase' }], signalTypes: ['google_news'] },
  { key: 'devto', label: 'Dev.to', settings: [{ key: 'scout_devto_tags', placeholder: 'tag (e.g. javascript, ai)' }], signalTypes: ['devto'] },
  { key: 'producthunt', label: 'Product Hunt', settings: [{ key: 'scout_producthunt_enabled', type: 'toggle' }], signalTypes: ['producthunt'] },
  { key: 'web', label: 'Web Search', settings: [{ key: 'scout_web_queries', placeholder: 'topic or trend to search' }], signalTypes: ['web_search'] },
]

const TYPE_LABELS = {
  github_release: 'release', github_commit: 'commit', hackernews: 'hn',
  reddit: 'reddit', rss: 'rss', trend: 'trend', web_search: 'web',
  support: 'support', performance: 'perf', google_news: 'gnews',
  devto: 'devto', producthunt: 'ph',
}

function TagInput({ onAdd, placeholder }) {
  const [val, setVal] = useState('')
  const submit = () => {
    if (val.trim()) { onAdd(val.trim()); setVal('') }
  }
  return (
    <input
      className="sig-tag-input"
      value={val}
      onChange={e => setVal(e.target.value)}
      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); submit() } }}
      onBlur={submit}
      placeholder={placeholder}
    />
  )
}

export default function Scout({ onLog, orgId }) {
  const headers = orgHeaders(orgId)

  // ── State ──
  const [settings, setSettings] = useState({})
  const [edits, setEdits] = useState({})
  const [saving, setSaving] = useState(false)
  const [signals, setSignals] = useState([])
  const [scouting, setScouting] = useState(false)
  const [expandedSource, setExpandedSource] = useState(null)
  const [typeFilter, setTypeFilter] = useState('')

  // Suggestions
  const [suggesting, setSuggesting] = useState(false)
  const [suggestions, setSuggestions] = useState(null)

  // GitHub sync
  const [syncingGithub, setSyncingGithub] = useState(false)

  // ── Load data ──
  const load = useCallback(async () => {
    if (!orgId) return
    try {
      const [setRes, sigRes] = await Promise.all([
        fetch(`${API}/settings`, { headers }),
        fetch(`${API}/signals?limit=100`, { headers }),
      ])
      if (setRes.ok) setSettings(await setRes.json())
      if (sigRes.ok) setSignals(await sigRes.json())
    } catch { /* ignore */ }
  }, [orgId])

  useEffect(() => { load() }, [load])
  useEffect(() => { setEdits({}); setExpandedSource(null) }, [orgId])

  // ── Settings helpers ──
  const edit = (key, val) => setEdits(prev => ({ ...prev, [key]: val }))
  const getVal = (key) => edits[key] ?? settings[key]?.value ?? ''
  const isDirty = Object.keys(edits).length > 0

  const getTags = (key) => {
    try { return JSON.parse(getVal(key) || '[]') }
    catch { return [] }
  }

  const addTag = (key, newTag) => {
    const tags = getTags(key)
    if (!newTag.trim() || tags.includes(newTag.trim())) return
    edit(key, JSON.stringify([...tags, newTag.trim()]))
  }

  const removeTag = (key, idx) => {
    const tags = getTags(key)
    edit(key, JSON.stringify(tags.filter((_, i) => i !== idx)))
  }

  const getSourceCount = (source) => {
    let total = 0
    for (const s of source.settings) {
      if (s.type === 'toggle') {
        total += getVal(s.key) === 'true' ? 1 : 0
      } else {
        total += getTags(s.key).length
      }
    }
    return total
  }

  // ── Save ──
  const save = async () => {
    if (!isDirty) return
    setSaving(true)
    onLog?.('Saving signal sources...', 'action')
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT', headers,
        body: JSON.stringify({ settings: edits }),
      })
      setEdits({})
      onLog?.('Signal sources saved', 'success')
      await load()
    } catch (e) {
      onLog?.(`Save failed: ${e.message}`, 'error')
    }
    setSaving(false)
  }

  // ── Run scout (SSE streaming for live progress) ──
  const runScout = async () => {
    if (scouting) return
    setScouting(true)
    onLog?.('SIGNALS — scanning all sources...', 'action')

    const params = new URLSearchParams({ since_hours: 24 })
    if (orgId) params.set('x_org_id', orgId)

    const es = new EventSource(`${API}/stream/scout?${params}`)

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'log') {
          onLog?.(data.content, 'action')
        } else if (data.type === 'error') {
          onLog?.(`SIGNALS FAILED — ${data.content}`, 'error')
          es.close()
          setScouting(false)
        } else if (data.type === 'done') {
          onLog?.(`SIGNALS COMPLETE — ${data.signals_saved || 0} new signals saved`, 'success')
          es.close()
          // Refresh signal list
          fetch(`${API}/signals?limit=100`, { headers })
            .then(r => r.ok ? r.json() : [])
            .then(setSignals)
            .catch(() => {})
          setScouting(false)
        }
      } catch { /* ignore parse errors */ }
    }

    es.onerror = () => {
      onLog?.('SIGNALS ERROR — connection lost', 'error')
      es.close()
      setScouting(false)
    }
  }

  // ── Suggest sources ──
  const suggestSources = async () => {
    if (suggesting) return
    setSuggesting(true)
    setSuggestions(null)
    onLog?.('SUGGEST — asking Claude for source recommendations...', 'action')
    try {
      const res = await fetch(`${API}/pipeline/suggest-sources`, { method: 'POST', headers })
      const data = await res.json()
      if (data.error) {
        onLog?.(`SUGGEST FAILED — ${data.error}`, 'error')
      } else {
        const total = Object.values(data).reduce((sum, arr) => sum + (Array.isArray(arr) ? arr.length : 0), 0)
        setSuggestions(data)
        onLog?.(`SUGGEST COMPLETE — ${total} source recommendations`, 'success')
      }
    } catch (e) {
      onLog?.(`SUGGEST ERROR — ${e.message}`, 'error')
    }
    setSuggesting(false)
  }

  // ── GitHub sync ──
  const syncGithub = async () => {
    if (syncingGithub) return
    setSyncingGithub(true)
    try {
      const res = await fetch(`${API}/wire/sources/sync-github`, { method: 'POST', headers })
      const data = await res.json()
      if (data.error) {
        onLog?.(`GITHUB SYNC FAILED — ${data.error}`, 'error')
      } else {
        onLog?.(`GITHUB SYNC — ${data.repos_discovered} repos from ${data.owner}`, 'success')
        await load()
      }
    } catch (e) {
      onLog?.(`GITHUB SYNC ERROR — ${e.message}`, 'error')
    }
    setSyncingGithub(false)
  }

  // ── Suggestions ──
  const acceptSuggestion = (settingsKey, value) => {
    addTag(settingsKey, value)
    setSuggestions(prev => {
      if (!prev) return prev
      const updated = { ...prev }
      if (Array.isArray(updated[settingsKey])) {
        updated[settingsKey] = updated[settingsKey].filter(v => v !== value)
      }
      return updated
    })
  }

  const dismissSuggestion = (settingsKey, value) => {
    setSuggestions(prev => {
      if (!prev) return prev
      const updated = { ...prev }
      if (Array.isArray(updated[settingsKey])) {
        updated[settingsKey] = updated[settingsKey].filter(v => v !== value)
      }
      return updated
    })
  }

  // ── Prioritize ──
  const togglePriority = async (signalId) => {
    try {
      await fetch(`${API}/signals/${signalId}/prioritize`, { method: 'PATCH', headers })
      const sigRes = await fetch(`${API}/signals?limit=100`, { headers })
      if (sigRes.ok) setSignals(await sigRes.json())
    } catch { /* silent */ }
  }

  // ── Filtered signals ──
  const allTypes = useMemo(() => [...new Set(signals.map(s => s.type).filter(Boolean))].sort(), [signals])

  const filteredSignals = useMemo(() => {
    if (!typeFilter) return signals
    return signals.filter(s => s.type === typeFilter)
  }, [signals, typeFilter])

  // ── RENDER ──
  return (
    <div className="sig-layout">
      {/* ═══ LEFT SIDEBAR: SOURCE CONFIG ═══ */}
      <div className="sig-sidebar">
        <div className="sig-sidebar-header">
          <span className="sig-sidebar-title">Sources</span>
        </div>

        <div className="sig-source-list">
          {SOURCES.map(source => {
            const isOpen = expandedSource === source.key
            const count = getSourceCount(source)
            return (
              <div key={source.key} className={`sig-source-card ${isOpen ? 'open' : ''}`}>
                <div
                  className="sig-source-header"
                  onClick={() => setExpandedSource(isOpen ? null : source.key)}
                >
                  <span className="sig-source-toggle">{isOpen ? '\u25BE' : '\u25B8'}</span>
                  <span className="sig-source-name">{source.label}</span>
                  <span className="sig-source-count">
                    {source.settings[0]?.type === 'toggle'
                      ? (getVal(source.settings[0].key) === 'true' ? 'on' : 'off')
                      : count}
                  </span>
                </div>

                {isOpen && (
                  <div className="sig-source-body">
                    {source.settings.map(s => {
                      if (s.type === 'toggle') {
                        const enabled = getVal(s.key) === 'true'
                        return (
                          <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
                            <button
                              className={`sig-toggle-btn ${enabled ? 'on' : ''}`}
                              onClick={() => edit(s.key, enabled ? '' : 'true')}
                            >
                              {enabled ? 'ON' : 'OFF'}
                            </button>
                            <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                              {enabled ? 'Enabled — will fetch trending products' : 'Disabled'}
                            </span>
                          </div>
                        )
                      }

                      const tags = getTags(s.key)
                      const suggs = suggestions && Array.isArray(suggestions[s.key]) ? suggestions[s.key] : []

                      return (
                        <div key={s.key}>
                          {s.sublabel && <div className="sig-sublabel">{s.sublabel}</div>}
                          <div className="sig-tag-list">
                            {tags.map((t, i) => (
                              <span key={i} className="sig-tag" onClick={() => removeTag(s.key, i)}>
                                {t} <span className="sig-tag-x">&times;</span>
                              </span>
                            ))}
                            <TagInput onAdd={v => addTag(s.key, v)} placeholder={s.placeholder} />
                          </div>
                          {suggs.length > 0 && (
                            <div className="sig-suggestions">
                              <span className="sig-sugg-label">suggested</span>
                              {suggs.map((v, i) => (
                                <span key={i} className="sig-sugg-tag" onClick={() => acceptSuggestion(s.key, v)}>
                                  + {v}
                                  <span className="sig-tag-x" onClick={e => { e.stopPropagation(); dismissSuggestion(s.key, v) }}>&times;</span>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )
                    })}
                    {source.hasSync && (
                      <button
                        className={`sig-sync-btn ${syncingGithub ? 'loading' : ''}`}
                        onClick={syncGithub}
                        disabled={syncingGithub}
                      >
                        {syncingGithub ? 'Syncing...' : 'Sync from GitHub'}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        <div className="sig-sidebar-actions">
          <button className={`btn btn-approve ${saving ? 'loading' : ''}`} onClick={save} disabled={!isDirty || saving}>
            {saving ? 'Saving...' : isDirty ? 'Save Sources' : 'Saved'}
          </button>
          <button className={`btn btn-run ${scouting ? 'loading' : ''}`} onClick={runScout} disabled={scouting}>
            {scouting ? 'Running...' : 'Run Scout'}
          </button>
          <button
            className={`btn ${suggesting ? 'loading' : ''}`}
            onClick={suggestSources}
            disabled={suggesting}
            style={{ borderColor: 'var(--amber-dim)', color: 'var(--amber)' }}
          >
            {suggesting ? 'Thinking...' : 'Suggest'}
          </button>
        </div>
      </div>

      {/* ═══ RIGHT PANEL: SIGNAL FEED ═══ */}
      <div className="sig-feed">
        <div className="sig-feed-header">
          <select className="sig-type-filter" value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
            <option value="">All types</option>
            {allTypes.map(t => <option key={t} value={t}>{TYPE_LABELS[t] || t}</option>)}
          </select>
          <span className="sig-feed-count">{filteredSignals.length} signals</span>
        </div>

        <div className="sig-feed-list">
          {filteredSignals.length === 0 && !scouting && (
            <div className="sig-empty">
              No signals yet. Configure sources and hit Run Scout.
            </div>
          )}

          {scouting && filteredSignals.length === 0 && (
            <div className="sig-empty" style={{ color: 'var(--amber)' }}>
              Working the wire...
            </div>
          )}

          {filteredSignals.map(s => (
            <div key={s.id} className={`sig-feed-item ${s.prioritized ? 'prioritized' : ''}`}>
              <span className="sig-item-type">{TYPE_LABELS[s.type] || s.type}</span>
              <div className="sig-item-content">
                <div className="sig-item-title">
                  {s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a> : s.title}
                </div>
                <div className="sig-item-meta">
                  <span>{s.source}</span>
                  {s.created_at && <span>{new Date(s.created_at).toLocaleDateString()}</span>}
                </div>
              </div>
              <button
                className={`sig-star ${s.prioritized ? 'active' : ''}`}
                onClick={() => togglePriority(s.id)}
                title={s.prioritized ? 'Remove priority' : 'Prioritize'}
              >
                {s.prioritized ? '\u2605' : '\u2606'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
