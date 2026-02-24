import { useState, useEffect, useCallback, useMemo } from 'react'

const API = '/api'

function orgHeaders(orgId) {
  const h = { 'Content-Type': 'application/json' }
  if (orgId) h['X-Org-Id'] = String(orgId)
  return h
}

const SOURCE_TYPES = [
  {
    key: 'scout_github_orgs',
    label: 'GitHub Organizations',
    placeholder: 'org name (e.g. treehouse)',
    signalTypes: [],
    signalLabel: 'ORG',
  },
  {
    key: 'scout_github_repos',
    label: 'GitHub Repositories',
    placeholder: 'org/repo',
    signalTypes: ['github_release', 'github_commit'],
    signalLabel: 'GITHUB',
  },
  {
    key: 'scout_hn_keywords',
    label: 'Hacker News Keywords',
    placeholder: 'REST API, database, serverless',
    signalTypes: ['hackernews'],
    signalLabel: 'HN',
  },
  {
    key: 'scout_subreddits',
    label: 'Subreddits',
    placeholder: 'r/webdev, r/devops',
    signalTypes: ['reddit'],
    signalLabel: 'REDDIT',
  },
  {
    key: 'scout_rss_feeds',
    label: 'RSS Feeds',
    placeholder: 'one URL per line',
    signalTypes: ['rss'],
    signalLabel: 'RSS',
  },
  {
    key: 'scout_web_queries',
    label: 'Web Search',
    placeholder: 'trend or topic to search',
    signalTypes: ['web_search'],
    signalLabel: 'WEB',
  },
]

const SIGNAL_TAG_MAP = {
  github_release: 'RELEASE', github_commit: 'COMMITS', hackernews: 'HN',
  reddit: 'REDDIT', rss: 'RSS', trend: 'TREND', web_search: 'WEB',
  support: 'SUPPORT', performance: 'PERF',
}

export default function Scout({ onLog, orgId }) {
  const [settings, setSettings] = useState({})
  const [edits, setEdits] = useState({})
  const [saving, setSaving] = useState(false)
  const [signals, setSignals] = useState([])
  const [scouting, setScouting] = useState(false)
  const [collapsed, setCollapsed] = useState({})
  const [signalStats, setSignalStats] = useState([])
  // Suggestions
  const [suggesting, setSuggesting] = useState(false)
  const [suggestions, setSuggestions] = useState(null) // { scout_subreddits: [...], ... }
  // GitHub sync
  const [syncingGithub, setSyncingGithub] = useState(false)
  const [githubSyncResult, setGithubSyncResult] = useState(null)

  // Visibility check
  const [visDomain, setVisDomain] = useState('')
  const [visRunning, setVisRunning] = useState(false)
  const [visResult, setVisResult] = useState(null)

  const load = useCallback(async () => {
    if (!orgId) return
    try {
      const [setRes, sigRes, statsRes] = await Promise.all([
        fetch(`${API}/settings`, { headers: orgHeaders(orgId) }),
        fetch(`${API}/signals?limit=50`, { headers: orgHeaders(orgId) }),
        fetch(`${API}/signals/stats/performance`, { headers: orgHeaders(orgId) }),
      ])
      if (setRes.ok) setSettings(await setRes.json())
      if (sigRes.ok) setSignals(await sigRes.json())
      if (statsRes.ok) setSignalStats(await statsRes.json())
    } catch (e) {
      onLog?.('Failed to load scout data', 'error')
    }
  }, [orgId, onLog])

  useEffect(() => { load() }, [load])

  // Reset edits when org changes
  useEffect(() => { setEdits({}) }, [orgId])

  const edit = (key, val) => setEdits(prev => ({ ...prev, [key]: val }))
  const getVal = (key) => edits[key] ?? settings[key]?.value ?? ''
  const isDirty = Object.keys(edits).length > 0

  // Tag helpers
  const getTags = (key) => {
    try { return JSON.parse(getVal(key) || '[]') }
    catch { return [] }
  }

  const addTag = (key, currentTags, newTag) => {
    if (!newTag.trim() || currentTags.includes(newTag.trim())) return
    edit(key, JSON.stringify([...currentTags, newTag.trim()]))
  }

  const removeTag = (key, currentTags, idx) => {
    edit(key, JSON.stringify(currentTags.filter((_, i) => i !== idx)))
  }

  // Save sources
  const save = async () => {
    if (!isDirty) return
    setSaving(true)
    onLog?.('Saving scout sources...', 'action')
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: edits }),
      })
      setEdits({})
      onLog?.('Scout sources saved', 'success')
      await load()
    } catch (e) {
      onLog?.(`Save failed: ${e.message}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  // Run scout
  const runScout = async () => {
    if (scouting) return
    setScouting(true)
    onLog?.('SCOUT \u2014 scanning GitHub, HN, Reddit, RSS...', 'action')
    try {
      const res = await fetch(`${API}/pipeline/scout`, {
        method: 'POST',
        headers: orgHeaders(orgId),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`SCOUT FAILED \u2014 ${data.error}`, 'error')
        return
      }
      const raw = data.signals_raw || 0
      const kept = data.signals_saved || data.signals_relevant || 0
      onLog?.(`SCOUT COMPLETE \u2014 ${kept} signals kept${raw > kept ? ` (${raw - kept} filtered)` : ''}`, 'success')
      // Reload signals
      const sigRes = await fetch(`${API}/signals?limit=50`, { headers: orgHeaders(orgId) })
      if (sigRes.ok) setSignals(await sigRes.json())
    } catch (e) {
      onLog?.(`SCOUT ERROR \u2014 ${e.message}`, 'error')
    } finally {
      setScouting(false)
    }
  }

  // Suggest sources
  const suggestSources = async () => {
    if (suggesting) return
    setSuggesting(true)
    setSuggestions(null)
    onLog?.('SUGGEST — asking Claude for source recommendations...', 'action')
    try {
      const res = await fetch(`${API}/pipeline/suggest-sources`, {
        method: 'POST',
        headers: orgHeaders(orgId),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`SUGGEST FAILED — ${data.error}`, 'error')
        return
      }
      // Count total suggestions
      const total = Object.values(data).reduce((sum, arr) => sum + (Array.isArray(arr) ? arr.length : 0), 0)
      setSuggestions(data)
      onLog?.(`SUGGEST COMPLETE — ${total} source recommendations`, 'success')
    } catch (e) {
      onLog?.(`SUGGEST ERROR — ${e.message}`, 'error')
    } finally {
      setSuggesting(false)
    }
  }

  const syncGithub = async () => {
    if (syncingGithub) return
    setSyncingGithub(true)
    setGithubSyncResult(null)
    try {
      const res = await fetch(`${API}/wire/sources/sync-github`, {
        method: 'POST',
        headers: orgHeaders(orgId),
      })
      const data = await res.json()
      setGithubSyncResult(data)
      if (data.error) {
        onLog?.(`GITHUB SYNC FAILED — ${data.error}`, 'error')
      } else {
        onLog?.(`GITHUB SYNC — ${data.repos_discovered} repos from ${data.owner}`, 'success')
        await load() // Refresh settings so tag list updates
      }
    } catch (e) {
      setGithubSyncResult({ error: e.message })
      onLog?.(`GITHUB SYNC ERROR — ${e.message}`, 'error')
    } finally {
      setSyncingGithub(false)
    }
  }

  const acceptSuggestion = (settingsKey, value) => {
    const tags = getTags(settingsKey)
    if (!tags.includes(value)) {
      addTag(settingsKey, tags, value)
    }
    // Remove from suggestions
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

  // Group signals by source type
  const groupedSignals = useMemo(() => {
    const knownTypes = SOURCE_TYPES.flatMap(st => st.signalTypes)
    const groups = []
    for (const st of SOURCE_TYPES) {
      const matching = signals.filter(s => st.signalTypes.includes(s.type))
      if (matching.length > 0) {
        groups.push({ key: st.key, label: st.signalLabel, count: matching.length, signals: matching })
      }
    }
    const other = signals.filter(s => !knownTypes.includes(s.type))
    if (other.length > 0) {
      groups.push({ key: '_other', label: 'OTHER', count: other.length, signals: other })
    }
    return groups
  }, [signals])

  const toggleGroup = (key) => setCollapsed(prev => ({ ...prev, [key]: !prev[key] }))

  // Visibility check
  const runVisibility = async () => {
    if (visRunning || !visDomain.trim()) return
    setVisRunning(true)
    setVisResult(null)
    onLog?.('VISIBILITY CHECK — searching for your domain...', 'action')
    try {
      const res = await fetch(`${API}/pipeline/visibility`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ domain: visDomain.trim() }),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`VISIBILITY FAILED — ${data.error}`, 'error')
        return
      }
      setVisResult(data)
      onLog?.(`VISIBILITY — score: ${data.score}% (${data.queries_found}/${data.queries_checked} queries found your domain)`, 'success')
    } catch (e) {
      onLog?.(`VISIBILITY ERROR — ${e.message}`, 'error')
    } finally {
      setVisRunning(false)
    }
  }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2 className="settings-title">Scout</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            className={`btn ${suggesting ? 'loading' : ''}`}
            onClick={suggestSources}
            disabled={suggesting}
            style={{ borderColor: 'var(--amber-dim)', color: 'var(--amber)' }}
          >
            {suggesting ? 'Thinking...' : 'Suggest Sources'}
          </button>
          <button
            className={`btn btn-run ${scouting ? 'loading' : ''}`}
            onClick={runScout}
            disabled={scouting}
          >
            {scouting ? 'Scouting...' : 'Run Scout'}
          </button>
          <button
            className={`btn btn-approve ${saving ? 'loading' : ''}`}
            onClick={save}
            disabled={!isDirty || saving}
          >
            {saving ? 'Saving...' : 'Save Sources'}
          </button>
        </div>
      </div>

      {/* SCOUT SOURCES */}
      {SOURCE_TYPES.map(st => {
        const tags = getTags(st.key)
        const suggs = suggestions && Array.isArray(suggestions[st.key]) ? suggestions[st.key] : []
        return (
          <div key={st.key} className="settings-section">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <div className="section-label" style={{ margin: 0 }}>{st.label} <span className="section-count">{tags.length}</span></div>
              {st.key === 'scout_github_repos' && (
                <button
                  className={`btn btn-sm ${syncingGithub ? 'loading' : ''}`}
                  onClick={syncGithub}
                  disabled={syncingGithub}
                  title="Auto-discover all repos from your GitHub org in social profiles"
                  style={{ fontSize: 10 }}
                >
                  {syncingGithub ? 'Syncing...' : 'Sync GitHub'}
                </button>
              )}
            </div>
            {st.key === 'scout_github_repos' && githubSyncResult && (
              <div style={{
                marginBottom: 8, padding: '6px 10px', borderRadius: 4, fontSize: 11,
                background: githubSyncResult.error ? 'var(--error-bg, rgba(255,60,60,0.08))' : 'var(--success-bg, rgba(0,200,100,0.08))',
                color: githubSyncResult.error ? 'var(--red, #f55)' : 'var(--green)',
                border: `1px solid ${githubSyncResult.error ? 'var(--red, #f55)' : 'var(--green)'}`,
              }}>
                {githubSyncResult.error
                  ? <>⚠ {githubSyncResult.error}</>
                  : <>{githubSyncResult.repos_discovered} repos synced from <strong>github.com/{githubSyncResult.owner}</strong>. Wire source created.</>
                }
              </div>
            )}
            <div className="tag-list">
              {tags.map((t, i) => (
                <span key={i} className="tag tag-amber" onClick={() => removeTag(st.key, tags, i)}>
                  {t} <span className="tag-x">&times;</span>
                </span>
              ))}
              <TagInput onAdd={(v) => addTag(st.key, tags, v)} placeholder={`add ${st.placeholder}...`} />
            </div>
            {suggs.length > 0 && (
              <div style={{ marginTop: 6 }}>
                <span style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginRight: 8 }}>suggested</span>
                {suggs.map((s, i) => (
                  <span
                    key={i}
                    className="tag"
                    style={{
                      borderColor: 'var(--amber-dim)',
                      color: 'var(--amber)',
                      borderStyle: 'dashed',
                      cursor: 'pointer',
                      marginRight: 4,
                      marginBottom: 4,
                    }}
                    onClick={() => acceptSuggestion(st.key, s)}
                  >
                    + {s}
                    <span
                      className="tag-x"
                      style={{ marginLeft: 6 }}
                      onClick={(e) => { e.stopPropagation(); dismissSuggestion(st.key, s) }}
                    >&times;</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        )
      })}

      {/* SIGNAL RESULTS */}
      <div className="settings-section">
        <div className="section-label">
          Signals <span className="section-count">{signals.length}</span>
        </div>

        {signals.length === 0 && !scouting && (
          <div className="scout-empty">
            No signals yet. Hit <strong>Run Scout</strong> to scan your sources.
          </div>
        )}

        {scouting && signals.length === 0 && (
          <div className="scout-empty">
            <div className="loader-bar" />
            <p style={{ marginTop: 12 }}>Working the wire...</p>
          </div>
        )}

        {groupedSignals.map(group => (
          <div key={group.key} className="scout-group">
            <div className="scout-group-header" onClick={() => toggleGroup(group.key)}>
              <div className="scout-group-label">
                <span className="scout-group-toggle">{collapsed[group.key] ? '\u25B6' : '\u25BC'}</span>
                {group.label}
              </div>
              <span className="scout-group-count">{group.count}</span>
            </div>
            {!collapsed[group.key] && (
              <div className="scout-group-signals">
                {group.signals.map(s => (
                  <div key={s.id} className="signal-item">
                    <span className="signal-tag">{SIGNAL_TAG_MAP[s.type] || s.type}</span>
                    <div className="signal-title">
                      {s.url ? <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a> : s.title}
                    </div>
                    <div className="signal-source">{s.source}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* SIGNAL PERFORMANCE */}
      {signalStats.some(s => s.times_used > 0) && (
        <div className="settings-section">
          <div className="section-label">
            Signal Performance <span className="section-count">wire dashboard</span>
          </div>

          <table className="perf-table">
            <thead>
              <tr>
                <th>TYPE</th>
                <th>SIGNAL</th>
                <th>USED</th>
                <th>SPIKED</th>
                <th>RATE</th>
              </tr>
            </thead>
            <tbody>
              {signalStats.filter(s => s.times_used > 0).slice(0, 20).map(s => {
                const spikeRate = s.times_used > 0 ? (s.times_spiked / s.times_used) : 0
                const isHot = spikeRate > 0.5 && s.times_used >= 2
                return (
                  <tr key={s.id} className={isHot ? 'perf-row-hot' : ''}>
                    <td className="perf-type">{SIGNAL_TAG_MAP[s.type] || s.type}</td>
                    <td className="perf-title">{s.title?.slice(0, 50)}{s.title?.length > 50 ? '...' : ''}</td>
                    <td className="perf-num">{s.times_used}</td>
                    <td className="perf-num perf-spike">{s.times_spiked}</td>
                    <td className={`perf-num ${isHot ? 'perf-rate-bad' : 'perf-rate-ok'}`}>
                      {(spikeRate * 100).toFixed(0)}%
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {signalStats.filter(s => s.times_used >= 2 && (s.times_spiked / s.times_used) > 0.5).length > 0 && (
            <div className="perf-warning">
              ADVISORY — signals marked in red have high spike rates. Consider removing from sources.
            </div>
          )}
        </div>
      )}

      {/* CONTENT VISIBILITY CHECK */}
      <div className="settings-section">
        <div className="section-label">
          Content Visibility <span className="section-count">how well does your content show up?</span>
        </div>
        <p style={{ color: 'var(--text-dim)', fontSize: 13, margin: '0 0 12px' }}>
          Searches your configured topics via Claude and checks if your domain appears in results.
        </p>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <input
            className="input"
            value={visDomain}
            onChange={e => setVisDomain(e.target.value)}
            placeholder="yourdomain.com"
            style={{ flex: 1 }}
          />
          <button
            className={`btn btn-run ${visRunning ? 'loading' : ''}`}
            onClick={runVisibility}
            disabled={visRunning || !visDomain.trim()}
          >
            {visRunning ? 'Checking...' : 'Check Visibility'}
          </button>
        </div>

        {visRunning && (
          <div className="scout-empty">
            <div className="loader-bar" />
            <p style={{ marginTop: 12 }}>Searching the web for your domain...</p>
          </div>
        )}

        {visResult && (
          <div>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 16,
              padding: '12px 16px', borderRadius: 8,
              background: visResult.score >= 50 ? 'rgba(34,197,94,0.1)' : visResult.score >= 20 ? 'rgba(234,179,8,0.1)' : 'rgba(239,68,68,0.1)',
              border: `1px solid ${visResult.score >= 50 ? 'rgba(34,197,94,0.3)' : visResult.score >= 20 ? 'rgba(234,179,8,0.3)' : 'rgba(239,68,68,0.3)'}`,
              marginBottom: 12,
            }}>
              <div style={{ fontSize: 32, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                {visResult.score}%
              </div>
              <div>
                <div style={{ fontWeight: 600 }}>
                  {visResult.score >= 50 ? 'Strong visibility' : visResult.score >= 20 ? 'Moderate visibility' : 'Low visibility'}
                </div>
                <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>
                  Found in {visResult.queries_found} of {visResult.queries_checked} searches for {visResult.domain}
                </div>
              </div>
            </div>

            <table className="perf-table">
              <thead>
                <tr>
                  <th>QUERY</th>
                  <th>FOUND</th>
                  <th>POSITION</th>
                </tr>
              </thead>
              <tbody>
                {visResult.results?.map((r, i) => (
                  <tr key={i} className={r.found ? '' : 'perf-row-hot'}>
                    <td>{r.query}</td>
                    <td style={{ color: r.found ? 'var(--green)' : 'var(--red)' }}>
                      {r.found ? 'YES' : 'NO'}
                    </td>
                    <td className="perf-num">{r.position || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function TagInput({ onAdd, placeholder }) {
  const [val, setVal] = useState('')
  const submit = () => {
    if (val.trim()) {
      onAdd(val)
      setVal('')
    }
  }
  return (
    <input
      className="tag-input"
      value={val}
      onChange={e => setVal(e.target.value)}
      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); submit() } }}
      onBlur={submit}
      placeholder={placeholder}
    />
  )
}
