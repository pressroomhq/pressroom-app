import { useState, useEffect, useCallback, useRef } from 'react'
import SeoPR from './SeoPR'
import { orgHeaders, cachedFetch } from '../api'

const API = '/api'

function ScoreRing({ score, label }) {
  const color = score >= 80 ? 'var(--green)' : score >= 50 ? 'var(--amber)' : 'var(--red)'
  return (
    <div className="audit-score-ring" style={{ borderColor: color }}>
      <span className="audit-score-number" style={{ color }}>{score}</span>
      <span className="audit-score-label">{label || 'SCORE'}</span>
    </div>
  )
}

function IssueBadge({ count }) {
  const color = count === 0 ? 'var(--green)' : count <= 2 ? 'var(--amber)' : 'var(--red)'
  return <span className="audit-issue-count" style={{ background: color }}>{count}</span>
}

function SectionCheck({ label, found }) {
  return (
    <span className={`audit-section-check ${found ? 'found' : 'missing'}`}>
      {found ? '✓' : '✗'} {label}
    </span>
  )
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function ScoreBadge({ score }) {
  const color = score >= 80 ? 'var(--green)' : score >= 50 ? 'var(--amber)' : 'var(--red)'
  return <span className="audit-score-badge" style={{ background: color }}>{score}</span>
}

// ────────────────────────────────────────
// Priority chip
// ────────────────────────────────────────
function PriorityChip({ priority }) {
  const cfg = {
    critical: { color: 'var(--red)',   label: 'CRITICAL' },
    high:     { color: 'var(--amber)', label: 'HIGH' },
    medium:   { color: 'var(--text-dim)', label: 'MEDIUM' },
    low:      { color: 'var(--border)', label: 'LOW' },
  }
  const { color, label } = cfg[priority] || cfg.medium
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, letterSpacing: '0.08em',
      color, border: `1px solid ${color}`, padding: '1px 5px', borderRadius: 2,
      whiteSpace: 'nowrap', flexShrink: 0,
    }}>{label}</span>
  )
}

// ────────────────────────────────────────
// Category chip
// ────────────────────────────────────────
function CategoryChip({ category }) {
  const labels = {
    'on-page': 'ON-PAGE', technical: 'TECHNICAL', content: 'CONTENT',
    geo: 'GEO', robots: 'ROBOTS', llms: 'LLMS.TXT',
    performance: 'PERF', schema: 'SCHEMA',
  }
  return (
    <span style={{
      fontSize: 9, letterSpacing: '0.06em', color: 'var(--text-dim)',
      background: 'var(--surface)', border: '1px solid var(--border)',
      padding: '1px 5px', borderRadius: 2, whiteSpace: 'nowrap', flexShrink: 0,
    }}>{labels[category] || category?.toUpperCase() || 'MISC'}</span>
  )
}

// ────────────────────────────────────────
// Generate File Modal — preview + copy + download
// ────────────────────────────────────────
const GENERATABLE_SOURCES = {
  robots_check: 'robots_txt',
  llms_check:   'llms_txt',
  sitemap_check: 'sitemap_xml',
}

const FILE_LABELS = {
  robots_txt: 'robots.txt',
  llms_txt:   'llms.txt',
  sitemap_xml: 'sitemap.xml',
}

function GenerateFileModal({ content, filename, onClose }) {
  const [copied, setCopied] = useState(false)

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* fallback */ }
  }

  const download = () => {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1100,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--bg)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          width: '90%',
          maxWidth: 680,
          maxHeight: '85vh',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 16px',
          borderBottom: '1px solid var(--border)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{filename}</span>
            <span style={{ fontSize: 10, color: 'var(--green)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Generated</span>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn btn-sm" onClick={copyToClipboard}
              style={{ fontSize: 10, color: copied ? 'var(--green)' : 'var(--text-dim)', borderColor: 'var(--border)' }}>
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button className="btn btn-sm btn-approve" onClick={download} style={{ fontSize: 10 }}>
              Download
            </button>
            <button onClick={onClose} style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 18, color: 'var(--text-dim)', lineHeight: 1,
            }}>&times;</button>
          </div>
        </div>

        {/* Content */}
        <div style={{
          flex: 1,
          overflow: 'auto',
          padding: 16,
        }}>
          <pre style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 11,
            lineHeight: 1.6,
            color: 'var(--text)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            margin: 0,
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            padding: 14,
          }}>{content}</pre>
        </div>

        {/* Footer hint */}
        <div style={{
          padding: '8px 16px',
          borderTop: '1px solid var(--border)',
          fontSize: 10,
          color: 'var(--text-dim)',
        }}>
          Copy this file and place it at your domain root. For robots.txt and llms.txt, upload to your web server. For sitemap.xml, also submit to Google Search Console.
        </div>
      </div>
    </div>
  )
}

// ────────────────────────────────────────
// Evidence Drawer — shows when action item is clicked
// ────────────────────────────────────────
function EvidenceDrawer({ item, orgId, onClose, onStatusChange }) {
  const [generating, setGenerating] = useState(false)
  const [generated, setGenerated] = useState(null) // { content, filename }

  if (!item) return null
  const ev = item.evidence || {}

  // Can we generate a file for this issue?
  const fileType = GENERATABLE_SOURCES[ev.source]
  const canGenerate = fileType && ev.found === false

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res = await fetch(`${API}/audit/generate-file`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ file_type: fileType, action_item_id: item.id }),
      })
      const data = await res.json()
      if (data.error) {
        alert(`Generation failed: ${data.error}`)
      } else {
        setGenerated({ content: data.content, filename: data.filename })
      }
    } catch (e) {
      alert(`Generation error: ${e.message}`)
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="evidence-drawer-overlay" onClick={onClose}>
      <div className="evidence-drawer" onClick={e => e.stopPropagation()}>
        <div className="evidence-drawer-header">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <PriorityChip priority={item.priority} />
            <CategoryChip category={item.category} />
            {item.score_impact > 0 && (
              <span style={{ fontSize: 9, color: 'var(--green)', fontWeight: 700 }}>
                +{item.score_impact} pts if fixed
              </span>
            )}
          </div>
          <button className="evidence-drawer-close" onClick={onClose}>&times;</button>
        </div>

        <h3 className="evidence-drawer-title">{item.title}</h3>

        {/* Status controls */}
        <div className="evidence-status-row">
          <span style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Status</span>
          <div style={{ display: 'flex', gap: 6 }}>
            {['open', 'in_progress', 'resolved'].map(s => (
              <button
                key={s}
                className={`evidence-status-btn ${item.status === s ? 'active' : ''}`}
                onClick={() => onStatusChange(item.id, s)}
              >
                {s === 'in_progress' ? 'In Progress' : s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Generate file button for missing files */}
        {canGenerate && (
          <div style={{
            padding: '10px 0',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
          }}>
            <button
              className={`btn btn-engine ${generating ? 'loading' : ''}`}
              onClick={handleGenerate}
              disabled={generating}
              style={{ fontSize: 11, whiteSpace: 'nowrap' }}
            >
              {generating ? 'Generating...' : `Generate ${FILE_LABELS[fileType]}`}
            </button>
            <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>
              Uses your org context to create a ready-to-deploy file
            </span>
          </div>
        )}

        {/* Evidence section */}
        <div className="evidence-section">
          <div className="evidence-section-label">How We Found This</div>
          <div className="evidence-data">
            {ev.source === 'page_crawl' && (
              <>
                {ev.url && <div className="evidence-row"><span className="evidence-key">URL</span><span className="evidence-val">{ev.url}</span></div>}
                {ev.field && <div className="evidence-row"><span className="evidence-key">Field</span><span className="evidence-val">{ev.field}</span></div>}
                {ev.found !== undefined && ev.found !== null && (
                  <div className="evidence-row">
                    <span className="evidence-key">Found</span>
                    <span className="evidence-val evidence-found">
                      {typeof ev.found === 'object' ? JSON.stringify(ev.found) : String(ev.found)}
                    </span>
                  </div>
                )}
                {ev.found_length !== undefined && (
                  <div className="evidence-row"><span className="evidence-key">Length</span><span className="evidence-val">{ev.found_length} chars</span></div>
                )}
                {ev.expected && <div className="evidence-row"><span className="evidence-key">Expected</span><span className="evidence-val evidence-expected">{ev.expected}</span></div>}
                {ev.context && <div className="evidence-row"><span className="evidence-key">Context</span><span className="evidence-val">{ev.context}</span></div>}
              </>
            )}
            {ev.source === 'robots_check' && (
              <>
                {ev.url && <div className="evidence-row"><span className="evidence-key">URL checked</span><span className="evidence-val">{ev.url}</span></div>}
                <div className="evidence-row"><span className="evidence-key">File found</span><span className="evidence-val">{ev.found ? 'Yes' : 'No'}</span></div>
                {ev.blocked_bots?.length > 0 && (
                  <div className="evidence-row"><span className="evidence-key">Blocked bots</span><span className="evidence-val evidence-found">{ev.blocked_bots.join(', ')}</span></div>
                )}
                {ev.robots_content && (
                  <div className="evidence-code-block">{ev.robots_content}</div>
                )}
              </>
            )}
            {ev.source === 'llms_check' && (
              <>
                {ev.url && <div className="evidence-row"><span className="evidence-key">URL checked</span><span className="evidence-val">{ev.url}</span></div>}
                <div className="evidence-row"><span className="evidence-key">File found</span><span className="evidence-val">{ev.found ? 'Yes' : 'No'}</span></div>
              </>
            )}
            {ev.source === 'sitemap_check' && (
              <>
                {ev.url && <div className="evidence-row"><span className="evidence-key">URL checked</span><span className="evidence-val">{ev.url}</span></div>}
                <div className="evidence-row"><span className="evidence-key">Found</span><span className="evidence-val">{ev.found ? 'Yes' : 'No'}</span></div>
              </>
            )}
            {ev.source === 'pagespeed' && (
              <>
                {ev.mobile_score !== undefined && <div className="evidence-row"><span className="evidence-key">Mobile score</span><span className="evidence-val evidence-found">{ev.mobile_score}/100</span></div>}
                {ev.lcp && <div className="evidence-row"><span className="evidence-key">LCP</span><span className="evidence-val">{ev.lcp}</span></div>}
                {ev.cls && <div className="evidence-row"><span className="evidence-key">CLS</span><span className="evidence-val">{ev.cls}</span></div>}
                {ev.fid && <div className="evidence-row"><span className="evidence-key">FID</span><span className="evidence-val">{ev.fid}</span></div>}
              </>
            )}
            {ev.source === 'claude_analysis' && (
              <>
                <div className="evidence-row"><span className="evidence-key">Source</span><span className="evidence-val">Claude strategic analysis</span></div>
                {ev.section && <div className="evidence-row"><span className="evidence-key">Section</span><span className="evidence-val">{ev.section.replace('_', ' ')}</span></div>}
              </>
            )}
            {ev.source === 'schema_field' && (
              <>
                {ev.url && <div className="evidence-row"><span className="evidence-key">URL</span><span className="evidence-val">{ev.url}</span></div>}
                {ev.schema_type && <div className="evidence-row"><span className="evidence-key">Schema type</span><span className="evidence-val">{ev.schema_type}</span></div>}
                {ev.missing_field && <div className="evidence-row"><span className="evidence-key">Missing field</span><span className="evidence-val evidence-found">{ev.missing_field}</span></div>}
              </>
            )}
          </div>
        </div>

        {/* Fix instructions */}
        {item.fix_instructions && (
          <div className="evidence-section">
            <div className="evidence-section-label">How to Fix</div>
            <div className="evidence-fix">{item.fix_instructions}</div>
          </div>
        )}

        {/* Dates */}
        <div className="evidence-meta">
          {item.first_seen && <span>First seen {formatDate(item.first_seen)}</span>}
          {item.last_seen && item.last_seen !== item.first_seen && <span> · Last seen {formatDate(item.last_seen)}</span>}
          {item.resolved_at && <span> · Resolved {formatDate(item.resolved_at)}</span>}
        </div>
      </div>

      {/* Generate file preview modal */}
      {generated && (
        <GenerateFileModal
          content={generated.content}
          filename={generated.filename}
          onClose={() => setGenerated(null)}
        />
      )}
    </div>
  )
}

// ────────────────────────────────────────
// Fix from saved action items — no re-scan needed
// ────────────────────────────────────────
function FixFromActionItems({ orgId, items, onLog, properties }) {
  const [selectedPropertyId, setSelectedPropertyId] = useState('')
  const [fixing, setFixing] = useState(false)
  const [runStatus, setRunStatus] = useState(null)  // { status, pr_url, run_id }
  const pollRef = useRef(null)

  const repoProperties = (properties || []).filter(p => p.repo_url)
  const activeProperty = repoProperties.find(p => String(p.id) === selectedPropertyId)

  // Poll run status while active
  useEffect(() => {
    if (!runStatus?.run_id || ['complete', 'failed'].includes(runStatus.status)) {
      clearInterval(pollRef.current)
      return
    }
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API}/seo-pr/runs/${runStatus.run_id}`, { headers: orgHeaders(orgId) })
        const data = await res.json()
        setRunStatus(prev => ({ ...prev, status: data.status, pr_url: data.pr_url || '' }))
        if (data.status === 'complete') {
          onLog?.(`SEO PR COMPLETE — ${data.pr_url || 'no PR URL'}`, 'success')
          setFixing(false)
        } else if (data.status === 'failed') {
          onLog?.(`SEO PR FAILED — ${data.error || 'unknown error'}`, 'error')
          setFixing(false)
        }
      } catch { /* ignore */ }
    }, 4000)
    return () => clearInterval(pollRef.current)
  }, [runStatus?.run_id, runStatus?.status, orgId]) // eslint-disable-line react-hooks/exhaustive-deps

  const runFix = async () => {
    if (!activeProperty) { onLog?.('FIX — select a property with a repo first', 'error'); return }
    if (!items.length) { onLog?.('FIX — no open action items to fix', 'error'); return }

    // Filter action items based on site type
    const REPO_CATS = {
      static: null,  // null = send all
      cms:    ['on-page', 'technical', 'schema', 'content'],
      app:    ['technical', 'schema'],
    }
    const siteType = activeProperty.site_type || 'static'
    const allowedCats = REPO_CATS[siteType]
    const filteredItems = allowedCats
      ? items.filter(i => allowedCats.includes(i.category))
      : items
    const skipped = items.length - filteredItems.length

    if (!filteredItems.length) {
      onLog?.(`FIX — no repo-fixable action items for ${siteType} site type`, 'error')
      return
    }

    setFixing(true)
    setRunStatus(null)
    onLog?.(
      `SEO FIX — ${filteredItems.length} items → pipeline${skipped > 0 ? ` (${skipped} skipped — not repo-fixable for ${siteType})` : ''} (skipping re-scan)...`,
      'action'
    )

    try {
      const res = await fetch(`${API}/seo-pr/run`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({
          repo_url: activeProperty.repo_url,
          domain: activeProperty.domain || '',
          base_branch: activeProperty.base_branch || 'main',
          action_items: filteredItems,
        }),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`SEO FIX FAILED — ${data.error}`, 'error')
        setFixing(false)
      } else {
        setRunStatus({ run_id: data.id, status: data.status, pr_url: '' })
        onLog?.(`SEO FIX LAUNCHED — run #${data.id}, implementing changes...`, 'success')
      }
    } catch (e) {
      onLog?.(`SEO FIX ERROR — ${e.message}`, 'error')
      setFixing(false)
    }
  }

  if (!repoProperties.length) return null

  const statusLabel = {
    pending: 'Queued...',
    auditing: 'Auditing...',
    analyzing: 'Analyzing...',
    implementing: 'Implementing fixes...',
    pushing: 'Pushing...',
    complete: 'Done',
    failed: 'Failed',
  }

  // Preview filtered count for the selected property
  const REPO_CATS = { static: null, cms: ['on-page', 'technical', 'schema', 'content'], app: ['technical', 'schema'] }
  const previewType = activeProperty?.site_type || 'static'
  const previewCats = REPO_CATS[previewType]
  const previewCount = previewCats ? items.filter(i => previewCats.includes(i.category)).length : items.length
  const previewSkipped = items.length - previewCount

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '10px 0', borderBottom: '1px solid var(--border)', marginBottom: 8 }}>
      <select
        className="setting-input"
        style={{ width: 200, flexShrink: 0 }}
        value={selectedPropertyId}
        onChange={e => { setSelectedPropertyId(e.target.value); setRunStatus(null) }}
      >
        <option value="">Select repo to fix...</option>
        {repoProperties.map(p => (
          <option key={p.id} value={String(p.id)}>{p.name} [{p.site_type || 'static'}]</option>
        ))}
      </select>
      <button
        className={`btn btn-engine ${fixing ? 'loading' : ''}`}
        onClick={runFix}
        disabled={fixing || !selectedPropertyId || previewCount === 0}
        style={{ whiteSpace: 'nowrap' }}
      >
        {fixing ? (statusLabel[runStatus?.status] || 'Working...') : '⚡ Fix with PR'}
      </button>
      {selectedPropertyId ? (
        <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
          {previewCount} items → pipeline
          {previewSkipped > 0 && <span style={{ color: 'var(--text-dim)', marginLeft: 4 }}>({previewSkipped} skipped — not repo-fixable for {previewType})</span>}
        </span>
      ) : (
        <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{items.length} action items</span>
      )}
      {runStatus?.pr_url && (
        <a href={runStatus.pr_url} target="_blank" rel="noopener noreferrer"
          style={{ color: 'var(--green)', textDecoration: 'none', fontSize: 12, marginLeft: 4 }}>
          View PR →
        </a>
      )}
    </div>
  )
}

// ────────────────────────────────────────
// Action Items Panel
// ────────────────────────────────────────
function ActionItemsPanel({ orgId, onLog, properties }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState('open')
  const [selected, setSelected] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = filter !== 'all' ? `?status=${filter}` : ''
      const res = await fetch(`${API}/audit/action-items${params}`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      setItems(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [orgId, filter])

  useEffect(() => { load() }, [load])

  const updateStatus = async (itemId, status) => {
    try {
      const res = await fetch(`${API}/audit/action-items/${itemId}`, {
        method: 'PATCH',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ status }),
      })
      const updated = await res.json()
      if (updated.id) {
        setItems(prev => prev.map(i => i.id === itemId ? updated : i))
        if (selected?.id === itemId) setSelected(updated)
        onLog?.(`ACTION ITEM — marked ${status}`, 'success')
      }
    } catch (e) {
      onLog?.(`STATUS UPDATE FAILED — ${e.message}`, 'error')
    }
  }

  const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 }
  const sorted = [...items].sort((a, b) =>
    (priorityOrder[a.priority] ?? 4) - (priorityOrder[b.priority] ?? 4)
  )

  const counts = items.reduce((acc, i) => {
    acc[i.priority] = (acc[i.priority] || 0) + 1
    return acc
  }, {})

  if (loading) return <div className="audit-empty">Loading action items...</div>

  return (
    <div className="action-items-panel">
      {/* Fix from action items — no re-scan */}
      <FixFromActionItems orgId={orgId} items={sorted} onLog={onLog} properties={properties} />

      {/* Filter bar */}
      <div className="action-items-toolbar">
        <div style={{ display: 'flex', gap: 6 }}>
          {['open', 'in_progress', 'resolved', 'all'].map(f => (
            <button
              key={f}
              className={`audit-filter-btn ${filter === f ? 'active' : ''}`}
              onClick={() => setFilter(f)}
            >
              {f === 'in_progress' ? 'In Progress' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 10, fontSize: 10, color: 'var(--text-dim)' }}>
          {counts.critical > 0 && <span style={{ color: 'var(--red)' }}>{counts.critical} critical</span>}
          {counts.high > 0 && <span style={{ color: 'var(--amber)' }}>{counts.high} high</span>}
          {counts.medium > 0 && <span>{counts.medium} medium</span>}
          <button className="btn btn-sm" style={{ fontSize: 10 }} onClick={load}>Refresh</button>
        </div>
      </div>

      {sorted.length === 0 && (
        <div className="audit-empty">
          {filter === 'open' ? 'No open action items. Run an audit to generate findings.' : `No ${filter} items.`}
        </div>
      )}

      <div className="action-items-list">
        {sorted.map(item => (
          <div
            key={item.id}
            className={`action-item-row ${item.status === 'resolved' ? 'resolved' : ''}`}
            onClick={() => setSelected(item)}
          >
            <PriorityChip priority={item.priority} />
            <CategoryChip category={item.category} />
            <span className="action-item-title">{item.title}</span>
            {item.score_impact > 0 && (
              <span className="action-item-impact">+{item.score_impact}</span>
            )}
            <span className="action-item-date">{formatDate(item.last_seen)}</span>
            <div className="action-item-status-dots">
              {['open', 'in_progress', 'resolved'].map(s => (
                <button
                  key={s}
                  className={`status-dot ${item.status === s ? 'active status-' + s.replace('_', '-') : ''}`}
                  title={s}
                  onClick={e => { e.stopPropagation(); updateStatus(item.id, s) }}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <EvidenceDrawer
          item={selected}
          orgId={orgId}
          onClose={() => setSelected(null)}
          onStatusChange={updateStatus}
        />
      )}
    </div>
  )
}

// ────────────────────────────────────────
// Sitewide check row (robots, llms, sitemap, pagespeed)
// ────────────────────────────────────────
function SitewideRow({ label, found, status, detail, onGenerate, generating }) {
  const color = found
    ? (status === 'warn' ? 'var(--amber)' : 'var(--green)')
    : 'var(--red)'
  const icon = found ? (status === 'warn' ? '⚠' : '✓') : '✗'
  return (
    <div className="sitewide-row">
      <span className="sitewide-icon" style={{ color }}>{icon}</span>
      <span className="sitewide-label">{label}</span>
      {detail && <span className="sitewide-detail">{detail}</span>}
      {!found && onGenerate && (
        <button
          className={`btn btn-sm btn-engine ${generating ? 'loading' : ''}`}
          onClick={onGenerate}
          disabled={generating}
          style={{ fontSize: 9, padding: '2px 8px', marginLeft: 'auto', flexShrink: 0 }}
        >
          {generating ? 'Generating...' : 'Generate'}
        </button>
      )}
    </div>
  )
}

// ────────────────────────────────────────
// Audit Help Modal
// ────────────────────────────────────────
function AuditHelpModal({ onClose }) {
  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: 24,
          maxWidth: 560,
          width: '90%',
          maxHeight: '80vh',
          overflowY: 'auto',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>How Audits Work</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: 'var(--text-dim)', lineHeight: 1 }}>×</button>
        </div>

        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 16, lineHeight: 1.6 }}>
          Every audit starts at <strong style={{ color: 'var(--text)' }}>100</strong> and deducts points for real problems found in the crawl.
          No guessing — every deduction is tied to a specific finding.
        </div>

        <HelpSection title="Scan Domain (Quick)" color="var(--text)">
          Checks the homepage only. Fast — usually under 30 seconds.
          <ul>
            <li><strong>robots.txt</strong> — present? AI crawlers allowed or blocked?</li>
            <li><strong>sitemap.xml</strong> — discoverable by search engines?</li>
            <li><strong>llms.txt</strong> — AI site summary for LLM indexers (GEO)</li>
            <li><strong>PageSpeed (mobile)</strong> — Google's Core Web Vitals score</li>
            <li><strong>Security headers</strong> — HSTS, X-Content-Type-Options, X-Frame-Options</li>
            <li><strong>E-E-A-T signals</strong> — author schema, bylines, about page, authoritative links</li>
            <li><strong>Content freshness</strong> — Last-Modified header + dateModified in schema</li>
          </ul>
        </HelpSection>

        <HelpSection title="⚡ Deep Audit (up to 20 pages)" color="var(--amber)">
          Crawls the whole site. Saves action items to your task list.
          <ul>
            <li>Everything in Quick Scan, plus:</li>
            <li><strong>Redirect chains</strong> — multi-hop redirects dilute link equity</li>
            <li><strong>Broken internal links</strong> — 404s crawlers and users hit</li>
            <li><strong>Orphaned pages</strong> — pages with no inbound links (invisible to search)</li>
            <li><strong>Per-page issues</strong> — missing titles, meta descriptions, canonical, schema, og:image</li>
            <li><strong>Structured data</strong> — JSON-LD validation on each page</li>
          </ul>
        </HelpSection>

        <HelpSection title="GEO — Generative Engine Optimization" color="var(--amber)">
          Traditional SEO is for Google's crawler. GEO is for AI systems (ChatGPT, Perplexity, Gemini).
          <ul>
            <li><strong>llms.txt</strong> — a plain-text summary of your site that LLMs read directly</li>
            <li><strong>robots.txt AI directives</strong> — are GPTBot, ClaudeBot, PerplexityBot allowed?</li>
            <li><strong>Structured data richness</strong> — clean JSON-LD helps AI understand your content</li>
            <li><strong>E-E-A-T</strong> — Experience, Expertise, Authoritativeness, Trust signals that AI systems weight heavily</li>
          </ul>
        </HelpSection>

        <HelpSection title="Scoring Model" color="var(--text-dim)">
          Deterministic — same site always gets the same score.
          <ul>
            <li>robots.txt missing: −6 · AI bots blocked: −15</li>
            <li>sitemap missing: −8 · llms.txt missing: −5</li>
            <li>PageSpeed &lt;50: −12 · &lt;75: −6</li>
            <li>Homepage: no schema −8, no title −8, no meta desc −6, no canonical −5, no og:image −3</li>
            <li>Redirect chains: −2 each (cap −8) · Broken links: −3 each (cap −12)</li>
            <li>Security headers &lt;2 present: −4 · Stale content: −4</li>
            <li>Weak E-E-A-T: −3 to −6 · Orphaned pages: −2 each (cap −6)</li>
          </ul>
          <div style={{ marginTop: 8, color: 'var(--text-dim)', fontSize: 11 }}>
            Claude provides qualitative analysis (action items, recommendations) — but the score comes from code, not AI judgment.
          </div>
        </HelpSection>
      </div>
    </div>
  )
}

function HelpSection({ title, color, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: color || 'var(--text)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
        {title}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text)', lineHeight: 1.7 }}>
        {children}
      </div>
    </div>
  )
}

// ────────────────────────────────────────
// Score Receipt — transparent deduction breakdown
// ────────────────────────────────────────
function ScoreReceipt({ score, reasons, sitewide }) {
  const [open, setOpen] = useState(false)

  // Build pass lines from sitewide data (things that didn't get deducted)
  const passes = []
  const sw = sitewide || {}
  if (sw.robots?.found && !sw.robots?.blocked_bots?.length) passes.push('robots.txt found, AI crawlers allowed')
  if (sw.sitemap?.found) passes.push(`sitemap.xml found (${sw.sitemap.page_count || '?'} URLs)`)
  if (sw.llms_txt?.found) passes.push('llms.txt present — GEO ready')
  if (sw.pagespeed?.mobile_score >= 75) passes.push(`PageSpeed ${sw.pagespeed.mobile_score}/100 — passing`)
  if (!sw.redirect_chains?.length) passes.push('no redirect chains detected')
  if (!sw.broken_links?.length) passes.push('no broken internal links')
  if (sw.security_headers && Object.values(sw.security_headers).filter(v => !v).length < 2) passes.push('security headers in order')
  if (!sw.freshness?.stale) passes.push('content freshness OK')

  const total = 100
  const deducted = total - score

  return (
    <div style={{ marginTop: 10 }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontSize: 10,
          color: 'var(--text-dim)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          padding: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 4,
        }}
      >
        <span>{open ? '▾' : '▸'}</span>
        Score breakdown — {deducted > 0 ? `-${deducted} pts` : 'perfect score'}
      </button>

      {open && (
        <div style={{
          marginTop: 8,
          fontFamily: 'monospace',
          fontSize: 11,
          border: '1px solid var(--border)',
          borderRadius: 4,
          overflow: 'hidden',
        }}>
          {/* Header */}
          <div style={{
            background: 'var(--surface-2)',
            padding: '6px 10px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            justifyContent: 'space-between',
            color: 'var(--text-dim)',
            fontSize: 10,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
          }}>
            <span>SEO Audit Receipt</span>
            <span>Start: 100</span>
          </div>

          {/* Passing checks */}
          {passes.map((p, i) => (
            <div key={`pass-${i}`} style={{
              padding: '4px 10px',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              justifyContent: 'space-between',
              color: 'var(--green)',
            }}>
              <span>✓ {p}</span>
              <span style={{ opacity: 0.6 }}>+0</span>
            </div>
          ))}

          {/* Deductions */}
          {reasons.map((r, i) => {
            // Extract the penalty number from the end e.g. "(-6)" → -6
            const match = r.match(/\(-(\d+)\)$/)
            const penalty = match ? `-${match[1]}` : ''
            const label = r.replace(/\s*\(-\d+\)$/, '')
            return (
              <div key={`ded-${i}`} style={{
                padding: '4px 10px',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                justifyContent: 'space-between',
                color: 'var(--red)',
              }}>
                <span>✗ {label}</span>
                <span>{penalty}</span>
              </div>
            )
          })}

          {/* Total */}
          <div style={{
            padding: '6px 10px',
            background: 'var(--surface-2)',
            display: 'flex',
            justifyContent: 'space-between',
            fontWeight: 600,
            color: score >= 80 ? 'var(--green)' : score >= 50 ? 'var(--amber)' : 'var(--red)',
          }}>
            <span>Final Score</span>
            <span>{score}/100</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ────────────────────────────────────────
// SEO Results Display
// ────────────────────────────────────────
function SeoResults({ result, onRefreshActionItems, orgId }) {
  const [expandedPage, setExpandedPage] = useState(null)
  const [showFullAnalysis, setShowFullAnalysis] = useState(false)
  const [generatingFile, setGeneratingFile] = useState(null) // 'robots_txt' | 'llms_txt' | 'sitemap_xml'
  const [generatedFile, setGeneratedFile] = useState(null)   // { content, filename }
  const rec = result.recommendations || {}
  const sw = result.sitewide || {}
  const hasSections = rec.critical?.length || rec.quick_wins?.length || rec.content_gaps?.length || rec.technical?.length

  const handleGenerate = async (fileType) => {
    setGeneratingFile(fileType)
    try {
      const res = await fetch(`${API}/audit/generate-file`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ file_type: fileType }),
      })
      const data = await res.json()
      if (data.error) {
        alert(`Generation failed: ${data.error}`)
      } else {
        setGeneratedFile({ content: data.content, filename: data.filename })
      }
    } catch (e) {
      alert(`Generation error: ${e.message}`)
    } finally {
      setGeneratingFile(null)
    }
  }

  return (
    <>
      {/* ── SCORE + STATS ── */}
      <div className="settings-section">
        <div className="audit-summary">
          <ScoreRing score={rec.score || 0} label="SEO" />
          <div className="audit-summary-stats">
            <div className="audit-stat">
              <span className="audit-stat-num">{result.pages_audited}</span>
              <span className="audit-stat-label">pages</span>
            </div>
            <div className="audit-stat">
              <span className="audit-stat-num">{rec.total_issues || 0}</span>
              <span className="audit-stat-label">issues</span>
            </div>
            {result.action_items_saved > 0 && (
              <div className="audit-stat">
                <span className="audit-stat-num" style={{ color: 'var(--amber)' }}>{result.action_items_saved}</span>
                <span className="audit-stat-label">action items saved</span>
              </div>
            )}
            <div className="audit-stat">
              <span className="audit-stat-num" style={{ fontSize: 11 }}>{result.domain?.replace(/^https?:\/\//, '')}</span>
              <span className="audit-stat-label">domain</span>
            </div>
          </div>
        </div>
        {/* ── SCORE RECEIPT ── */}
        {rec.score_reasons?.length > 0 && (
          <ScoreReceipt score={rec.score || 0} reasons={rec.score_reasons} sitewide={result.sitewide || {}} />
        )}
      </div>

      {/* ── SITEWIDE CHECKS ── */}
      {(sw.robots || sw.llms_txt || sw.sitemap || sw.pagespeed) && (
        <div className="settings-section">
          <div className="section-label">Sitewide Checks</div>
          <div className="sitewide-grid">
            {sw.robots && (
              <SitewideRow
                label="robots.txt"
                found={sw.robots.found}
                status={sw.robots.blocked_bots?.length > 0 ? 'warn' : 'ok'}
                detail={sw.robots.found
                  ? (sw.robots.blocked_bots?.length > 0
                    ? `AI bots blocked: ${sw.robots.blocked_bots.join(', ')}`
                    : `${sw.robots.has_sitemap_reference ? 'Sitemap referenced' : 'No sitemap ref'}`)
                  : 'Not found'}
                onGenerate={orgId ? () => handleGenerate('robots_txt') : null}
                generating={generatingFile === 'robots_txt'}
              />
            )}
            {sw.llms_txt && (
              <SitewideRow
                label="llms.txt"
                found={sw.llms_txt.found}
                detail={sw.llms_txt.found ? 'AI site summary present' : 'Not found — hurts GEO visibility'}
                onGenerate={orgId ? () => handleGenerate('llms_txt') : null}
                generating={generatingFile === 'llms_txt'}
              />
            )}
            {sw.sitemap && (
              <SitewideRow
                label="sitemap.xml"
                found={sw.sitemap.found}
                detail={sw.sitemap.found ? `${sw.sitemap.page_count} URLs` : 'Not found'}
                onGenerate={orgId ? () => handleGenerate('sitemap_xml') : null}
                generating={generatingFile === 'sitemap_xml'}
              />
            )}
            {sw.pagespeed?.found && (
              <SitewideRow
                label="PageSpeed (mobile)"
                found={true}
                status={sw.pagespeed.mobile_score < 50 ? 'warn' : sw.pagespeed.mobile_score < 75 ? 'warn' : 'ok'}
                detail={`${sw.pagespeed.mobile_score}/100${sw.pagespeed.lcp ? ` · LCP ${sw.pagespeed.lcp}` : ''}`}
              />
            )}
          </div>

          {/* robots.txt review from Claude */}
          {rec.robots_review?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Robots.txt Analysis</div>
              {rec.robots_review.map((line, i) => (
                <div key={i} style={{ fontSize: 11, color: 'var(--text)', padding: '3px 0', borderBottom: '1px solid var(--border)' }}>→ {line}</div>
              ))}
            </div>
          )}

          {/* llms.txt review from Claude */}
          {rec.llms_review?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>llms.txt Analysis</div>
              {rec.llms_review.map((line, i) => (
                <div key={i} style={{ fontSize: 11, color: 'var(--text)', padding: '3px 0', borderBottom: '1px solid var(--border)' }}>→ {line}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── GEO section ── */}
      {rec.geo?.length > 0 && (
        <div className="settings-section">
          <div className="section-label" style={{ color: 'var(--amber)' }}>GEO — AI Visibility</div>
          {rec.geo.map((line, i) => (
            <div key={i} style={{ fontSize: 12, color: 'var(--text)', padding: '5px 0', borderBottom: '1px solid var(--border)' }}>→ {line}</div>
          ))}
        </div>
      )}

      {/* ── STRUCTURED SECTIONS ── */}
      {hasSections ? (
        <>
          {rec.critical?.length > 0 && (
            <div className="settings-section">
              <div className="section-label" style={{ color: 'var(--red)' }}>Fix These Now</div>
              {rec.critical.map((item, i) => (
                <div key={i} style={{ fontSize: 12, color: 'var(--text)', padding: '5px 0', borderBottom: '1px solid var(--border)', lineHeight: 1.5 }}>
                  <span style={{ color: 'var(--red)', marginRight: 6 }}>✗</span>{item}
                </div>
              ))}
            </div>
          )}

          {rec.quick_wins?.length > 0 && (
            <div className="settings-section">
              <div className="section-label" style={{ color: 'var(--amber)' }}>Quick Wins</div>
              {rec.quick_wins.map((item, i) => (
                <div key={i} style={{ fontSize: 12, color: 'var(--text)', padding: '5px 0', borderBottom: '1px solid var(--border)', lineHeight: 1.5 }}>
                  <span style={{ color: 'var(--amber)', marginRight: 6 }}>→</span>{item}
                </div>
              ))}
            </div>
          )}

          {rec.content_gaps?.length > 0 && (
            <div className="settings-section">
              <div className="section-label">Content Gaps</div>
              {rec.content_gaps.map((item, i) => (
                <div key={i} style={{ fontSize: 12, color: 'var(--text)', padding: '5px 0', borderBottom: '1px solid var(--border)', lineHeight: 1.5 }}>
                  <span style={{ color: 'var(--green)', marginRight: 6 }}>+</span>{item}
                </div>
              ))}
            </div>
          )}

          {rec.technical?.length > 0 && (
            <div className="settings-section">
              <div className="section-label">Technical</div>
              {rec.technical.map((item, i) => (
                <div key={i} style={{ fontSize: 12, color: 'var(--text)', padding: '5px 0', borderBottom: '1px solid var(--border)', lineHeight: 1.5 }}>
                  <span style={{ color: 'var(--text-dim)', marginRight: 6 }}>⚙</span>{item}
                </div>
              ))}
            </div>
          )}

          {rec.analysis && (
            <div className="settings-section">
              <button
                className="btn btn-sm"
                style={{ fontSize: 10, color: 'var(--text-dim)', borderColor: 'var(--border)' }}
                onClick={() => setShowFullAnalysis(v => !v)}
              >
                {showFullAnalysis ? 'Hide' : 'Show'} Full Analysis
              </button>
              {showFullAnalysis && (
                <div className="audit-analysis" style={{ marginTop: 8 }}>
                  {rec.analysis.split('\n').map((line, i) => {
                    if (!line.trim()) return <br key={i} />
                    if (/^[A-Z _]{3,}:/.test(line.trim())) return <div key={i} className="audit-section-header">{line}</div>
                    return <div key={i} className="audit-line">{line}</div>
                  })}
                </div>
              )}
            </div>
          )}
        </>
      ) : rec.analysis ? (
        <div className="settings-section">
          <div className="section-label">Analysis</div>
          <div className="audit-analysis">
            {rec.analysis.split('\n').map((line, i) => {
              if (!line.trim()) return <br key={i} />
              if (/^[0-9]+\.|^[A-Z]{3,}|^\*\*/.test(line.trim())) return <div key={i} className="audit-section-header">{line.replace(/\*\*/g, '')}</div>
              return <div key={i} className="audit-line">{line}</div>
            })}
          </div>
        </div>
      ) : null}

      {/* ── PAGE DETAILS ── */}
      {result.pages?.length > 0 && (
        <div className="settings-section">
          <div className="section-label">Page Details</div>
          {result.pages.map((p, i) => (
            <div key={i} className="audit-page">
              <div
                className="audit-page-header"
                onClick={() => setExpandedPage(expandedPage === i ? null : i)}
              >
                <div className="audit-page-url">
                  <span className="audit-page-toggle">{expandedPage === i ? '▼' : '▶'}</span>
                  {p.url.replace(result.domain, '') || '/'}
                </div>
                <IssueBadge count={p.issue_count || 0} />
              </div>
              {expandedPage === i && (
                <div className="audit-page-details">
                  <div className="audit-detail-row">
                    <span className="audit-detail-label">Title</span>
                    <span className={`audit-detail-value ${!p.title ? 'missing' : p.title_length > 60 ? 'warn' : ''}`}>
                      {p.title || 'MISSING'} ({p.title_length} chars)
                    </span>
                  </div>
                  <div className="audit-detail-row">
                    <span className="audit-detail-label">Meta Desc</span>
                    <span className={`audit-detail-value ${!p.meta_description ? 'missing' : p.meta_description_length > 160 ? 'warn' : ''}`}>
                      {p.meta_description?.slice(0, 100) || 'MISSING'} ({p.meta_description_length} chars)
                    </span>
                  </div>
                  <div className="audit-detail-row">
                    <span className="audit-detail-label">H1</span>
                    <span className={`audit-detail-value ${p.h1_count !== 1 ? 'warn' : ''}`}>
                      {p.h1_texts?.join(', ') || 'MISSING'} ({p.h1_count} found)
                    </span>
                  </div>
                  <div className="audit-detail-row">
                    <span className="audit-detail-label">Content</span>
                    <span className="audit-detail-value">{p.word_count} words · {p.h2_count} H2s · {p.h3_count || 0} H3s</span>
                  </div>
                  <div className="audit-detail-row">
                    <span className="audit-detail-label">Images</span>
                    <span className={`audit-detail-value ${p.images_missing_alt > 0 ? 'warn' : ''}`}>
                      {p.total_images} total · {p.images_missing_alt} missing alt
                    </span>
                  </div>
                  <div className="audit-detail-row">
                    <span className="audit-detail-label">Links</span>
                    <span className="audit-detail-value">{p.internal_links} internal · {p.external_links} external</span>
                  </div>
                  <div className="audit-detail-row">
                    <span className="audit-detail-label">Technical</span>
                    <span className="audit-detail-value">
                      Canonical: {p.canonical ? '✓' : '✗'} ·
                      Schema: {p.has_schema ? '✓' : '✗'} ·
                      OG: {p.og_title ? '✓' : '✗'} ·
                      Viewport: {p.has_viewport ? '✓' : '✗'}
                    </span>
                  </div>
                  {p.schema_blocks?.length > 0 && (
                    <div className="audit-detail-row">
                      <span className="audit-detail-label">Schema</span>
                      <span className="audit-detail-value">{p.schema_blocks.map(b => b.type).join(', ')}</span>
                    </div>
                  )}
                  {p.issues?.length > 0 && (
                    <div className="audit-issues">
                      {p.issues.map((issue, j) => (
                        <div key={j} className="audit-issue">{issue}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Generated file preview modal */}
      {generatedFile && (
        <GenerateFileModal
          content={generatedFile.content}
          filename={generatedFile.filename}
          onClose={() => setGeneratedFile(null)}
        />
      )}
    </>
  )
}

// ────────────────────────────────────────
// README Results Display
// ────────────────────────────────────────
function ReadmeResults({ result }) {
  return (
    <>
      <div className="settings-section">
        <div className="audit-summary">
          <ScoreRing score={result.recommendations?.score || 0} label="README" />
          <div className="audit-summary-stats">
            <div className="audit-stat">
              <span className="audit-stat-num">{result.repo}</span>
              <span className="audit-stat-label">repo</span>
            </div>
            <div className="audit-stat">
              <span className="audit-stat-num">{result.word_count}</span>
              <span className="audit-stat-label">words</span>
            </div>
            <div className="audit-stat">
              <span className="audit-stat-num">{result.recommendations?.total_issues || 0}</span>
              <span className="audit-stat-label">missing sections</span>
            </div>
          </div>
        </div>
      </div>
      <div className="settings-section">
        <div className="section-label">Structure</div>
        <div className="audit-structure-grid">
          <SectionCheck label="Installation" found={result.structure?.sections_found?.installation} />
          <SectionCheck label="Usage / Examples" found={result.structure?.sections_found?.usage} />
          <SectionCheck label="API Reference" found={result.structure?.sections_found?.api_reference} />
          <SectionCheck label="Contributing" found={result.structure?.sections_found?.contributing} />
          <SectionCheck label="License" found={result.structure?.sections_found?.license} />
          <SectionCheck label="Badges" found={result.structure?.sections_found?.badges} />
          <SectionCheck label="Screenshots / Images" found={result.structure?.sections_found?.images} />
          <SectionCheck label="Code Blocks" found={result.structure?.sections_found?.code_blocks} />
        </div>
        <div className="audit-structure-counts">
          {result.structure?.heading_count || 0} headings &middot; {result.structure?.code_block_count || 0} code blocks &middot; {result.structure?.link_count || 0} links &middot; {result.structure?.badge_count || 0} badges
        </div>
      </div>
      <div className="settings-section">
        <div className="section-label">Analysis</div>
        <div className="audit-analysis">
          {result.recommendations?.analysis?.split('\n').map((line, i) => {
            if (!line.trim()) return <br key={i} />
            if (/^[0-9]+\.|^[A-Z]{3,}|^\*\*/.test(line.trim())) return <div key={i} className="audit-section-header">{line.replace(/\*\*/g, '')}</div>
            return <div key={i} className="audit-line">{line}</div>
          })}
        </div>
      </div>
    </>
  )
}

// ────────────────────────────────────────
// Scan tab — SEO + README runners
// ────────────────────────────────────────
// ────────────────────────────────────────
// Scan Tab — domain input + quick scan + deep scan
// ────────────────────────────────────────
function ScanTab({ orgId, onLog, assets, onRefreshHistory, onRefreshActionItems }) {
  const [domain, setDomain] = useState('')
  const [quickRunning, setQuickRunning] = useState(false)
  const [quickResult, setQuickResult] = useState(null)
  const [deepRunning, setDeepRunning] = useState(false)
  const [deepResult, setDeepResult] = useState(null)
  const [showHelp, setShowHelp] = useState(false)

  const siteAssets = assets.filter(a => ['subdomain', 'blog', 'docs', 'product', 'page'].includes(a.asset_type) && a.url)

  // Pre-select the homepage on mount (or when assets first load)
  useEffect(() => {
    if (!siteAssets.length || domain) return
    // Prefer an asset explicitly labelled homepage, or whose URL has no path
    const homepage = siteAssets.find(a =>
      /homepage/i.test(a.label || '') ||
      /^https?:\/\/[^/]+\/?$/.test(a.url)
    ) || siteAssets[0]
    if (homepage) setDomain(homepage.url)
  }, [assets]) // eslint-disable-line react-hooks/exhaustive-deps

  const runScan = async (maxPages, isDeep) => {
    const setter = isDeep ? setDeepRunning : setQuickRunning
    const resultSetter = isDeep ? setDeepResult : setQuickResult
    setter(true)
    resultSetter(null)
    onLog?.(`${isDeep ? 'DEEP' : 'QUICK'} SCAN — ${domain || 'org domain'}...`, 'action')
    try {
      const res = await fetch(`${API}/audit/seo`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ domain, max_pages: maxPages }),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`SCAN FAILED — ${data.error}`, 'error')
        resultSetter({ error: data.error })
      } else {
        resultSetter(data)
        const score = data.recommendations?.score || 0
        onLog?.(
          isDeep
            ? `DEEP SCAN COMPLETE — Score: ${score}/100 · ${data.pages_audited} pages · ${data.action_items_saved || 0} action items saved`
            : `QUICK SCAN COMPLETE — Score: ${score}/100 · sitewide checks done`,
          'success'
        )
        onRefreshHistory?.()
        if (isDeep) onRefreshActionItems?.()
      }
    } catch (e) {
      onLog?.(`SCAN ERROR — ${e.message}`, 'error')
      resultSetter({ error: e.message })
    } finally {
      setter(false)
    }
  }

  const running = quickRunning || deepRunning

  return (
    <div>
      {/* GSC */}
      <GscPanel orgId={orgId} />

      {/* Domain input */}
      <div className="settings-section">
        <div className="section-label" style={{ marginBottom: 8 }}>Domain</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'stretch' }}>
          {siteAssets.length > 0 && (
            <select
              className="setting-input"
              style={{ width: 220, flexShrink: 0 }}
              value={siteAssets.some(a => a.url === domain) ? domain : ''}
              onChange={e => setDomain(e.target.value)}
            >
              {!siteAssets.some(a => a.url === domain) && (
                <option value="">Pick from assets...</option>
              )}
              {siteAssets.map(a => (
                <option key={a.id} value={a.url}>
                  {a.label || a.asset_type} — {a.url.replace(/^https?:\/\//, '').slice(0, 36)}
                </option>
              ))}
            </select>
          )}
          <input
            className="setting-input"
            style={{ flex: 1 }}
            value={domain}
            onChange={e => setDomain(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !running) runScan(1, false) }}
            placeholder="dreamfactory.com"
            spellCheck={false}
          />
        </div>
      </div>

      {/* Action row */}
      <div className="settings-section">
        <div className="scan-actions">
          <div className="scan-action-group">
            <button
              className={`btn btn-run ${quickRunning ? 'loading' : ''}`}
              onClick={() => runScan(1, false)}
              disabled={running || !domain}
            >
              {quickRunning ? 'Scanning...' : 'Scan Domain'}
            </button>
            <span className="scan-action-hint">
              robots.txt · llms.txt · sitemap · PageSpeed · security headers · E-E-A-T · freshness
            </span>
          </div>
          <div className="scan-action-divider" />
          <div className="scan-action-group">
            <button
              className={`btn btn-engine ${deepRunning ? 'loading' : ''}`}
              onClick={() => runScan(20, true)}
              disabled={running || !domain}
            >
              {deepRunning ? 'Deep scanning...' : '⚡ Deep Audit'}
            </button>
            <span className="scan-action-hint">
              20 pages · redirect chains · broken links · orphans · GEO · structured data · saves action items
            </span>
          </div>
          <button
            onClick={() => setShowHelp(true)}
            title="How audits work"
            style={{
              marginLeft: 'auto',
              background: 'none',
              border: '1px solid var(--border)',
              borderRadius: '50%',
              width: 22,
              height: 22,
              cursor: 'pointer',
              fontSize: 11,
              color: 'var(--text-dim)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              alignSelf: 'flex-start',
              marginTop: 2,
            }}
          >?</button>
        </div>
      </div>
      {showHelp && <AuditHelpModal onClose={() => setShowHelp(false)} />}

      {/* Quick scan results */}
      {quickResult?.error && (
        <div className="settings-section"><div style={{ color: 'var(--red)', fontSize: 13 }}>{quickResult.error}</div></div>
      )}
      {quickResult && !quickResult.error && (
        <>
          <div className="audit-section-divider">
            <span className="section-label">Quick Scan Results</span>
            <span className="audit-section-from">{quickResult.domain?.replace(/^https?:\/\//, '')}</span>
          </div>
          <SeoResults result={quickResult} onRefreshActionItems={onRefreshActionItems} orgId={orgId} />
        </>
      )}

      {/* Deep scan results */}
      {deepResult?.error && (
        <div className="settings-section"><div style={{ color: 'var(--red)', fontSize: 13 }}>{deepResult.error}</div></div>
      )}
      {deepResult && !deepResult.error && (
        <>
          <div className="audit-section-divider">
            <span className="section-label" style={{ color: 'var(--amber)' }}>⚡ Deep Audit Results</span>
            <span className="audit-section-from">{deepResult.domain?.replace(/^https?:\/\//, '')}</span>
            {deepResult.action_items_saved > 0 && (
              <span style={{ fontSize: 10, color: 'var(--green)', marginLeft: 'auto' }}>
                {deepResult.action_items_saved} action items saved →
              </span>
            )}
          </div>
          <SeoResults result={deepResult} onRefreshActionItems={onRefreshActionItems} orgId={orgId} />
        </>
      )}
    </div>
  )
}

// ────────────────────────────────────────
// Properties Tab — Bond Site + README audit + Fix with PR
// ────────────────────────────────────────
function PropertiesTab({ orgId, onLog, assets, properties, onRefreshProperties, onRefreshHistory }) {
  const [activeProperty, setActiveProperty] = useState(null)
  const [readmeRunning, setReadmeRunning] = useState(false)
  const [readmeResult, setReadmeResult] = useState(null)
  const [fixing, setFixing] = useState(false)
  const [prUrl, setPrUrl] = useState('')

  const repoSlug = (() => {
    const url = activeProperty?.repo_url || ''
    if (!url) return ''
    const m = url.match(/github\.com\/([^/]+\/[^/]+)/)
    return m ? m[1] : url
  })()

  const runReadmeAudit = async () => {
    if (!repoSlug) { onLog?.('README AUDIT — no repo specified', 'error'); return }
    setReadmeRunning(true)
    setReadmeResult(null)
    setPrUrl('')
    onLog?.(`README AUDIT — analyzing ${repoSlug}...`, 'action')
    try {
      const res = await fetch(`${API}/audit/readme`, {
        method: 'POST', headers: orgHeaders(orgId),
        body: JSON.stringify({ repo: repoSlug }),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`README AUDIT FAILED — ${data.error}`, 'error')
        setReadmeResult({ error: data.error })
      } else {
        setReadmeResult(data)
        onLog?.(`README AUDIT COMPLETE — Score: ${data.recommendations?.score || 0}/100`, 'success')
        onRefreshHistory?.()
      }
    } catch (e) {
      onLog?.(`README AUDIT ERROR — ${e.message}`, 'error')
      setReadmeResult({ error: e.message })
    } finally {
      setReadmeRunning(false)
    }
  }

  const fixWithPr = async () => {
    const repoUrl = activeProperty?.repo_url
    const branch = activeProperty?.base_branch || 'main'
    if (!repoUrl) { onLog?.('README FIX — no repo URL', 'error'); return }
    setFixing(true)
    setPrUrl('')
    onLog?.('README FIX — creating PR...', 'action')
    try {
      const body = { repo_url: repoUrl, base_branch: branch }
      if (readmeResult?.audit_id) body.audit_id = readmeResult.audit_id
      else if (readmeResult?.recommendations?.analysis) body.recommendations = readmeResult.recommendations.analysis
      const res = await fetch(`${API}/audit/readme/fix`, {
        method: 'POST', headers: orgHeaders(orgId), body: JSON.stringify(body),
      })
      const data = await res.json()
      if (data.error) onLog?.(`README FIX FAILED — ${data.error}`, 'error')
      else if (data.pr_url) { setPrUrl(data.pr_url); onLog?.(`README PR CREATED — ${data.pr_url}`, 'success') }
      else onLog?.('README FIX — no changes needed', 'warn')
    } catch (e) {
      onLog?.(`README FIX ERROR — ${e.message}`, 'error')
    } finally {
      setFixing(false)
    }
  }

  return (
    <div>
      <PropertyManager
        orgId={orgId}
        onLog={onLog}
        properties={properties}
        assets={assets}
        onRefresh={onRefreshProperties}
        onSelectProperty={p => {
          setActiveProperty(p)
          setReadmeResult(null)
          setPrUrl('')
        }}
        activePropertyId={activeProperty?.id}
      />

      {activeProperty && (
        <>
          {/* README Audit */}
          <div className="audit-section-divider">
            <span className="section-label">README Audit</span>
            <span className="audit-section-from">{activeProperty.name}</span>
          </div>
          <div className="settings-section">
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                className={`btn btn-run ${readmeRunning ? 'loading' : ''}`}
                onClick={runReadmeAudit}
                disabled={readmeRunning || fixing || !repoSlug}
              >
                {readmeRunning ? 'Auditing...' : 'Run README Audit'}
              </button>
              {readmeResult && !readmeResult.error && activeProperty.repo_url && (
                <button
                  className={`btn btn-approve ${fixing ? 'loading' : ''}`}
                  onClick={fixWithPr}
                  disabled={fixing || readmeRunning}
                >
                  {fixing ? 'Creating PR...' : 'Fix with PR'}
                </button>
              )}
              <span style={{ color: 'var(--text-dim)', fontSize: 12, fontStyle: repoSlug ? 'normal' : 'italic' }}>
                {repoSlug || 'no repo linked to this property'}
              </span>
              {prUrl && (
                <a href={prUrl} target="_blank" rel="noopener noreferrer"
                  style={{ color: 'var(--green)', textDecoration: 'none', fontSize: 12 }}>
                  View PR →
                </a>
              )}
            </div>
          </div>
          {readmeResult?.error && (
            <div className="settings-section"><div style={{ color: 'var(--red)', fontSize: 13 }}>{readmeResult.error}</div></div>
          )}
          {readmeResult && !readmeResult.error && <ReadmeResults result={readmeResult} />}

          {/* Fix with PR standalone */}
          <div className="audit-section-divider">
            <span className="section-label">Fix with PR</span>
            {!activeProperty.repo_url && <span className="audit-section-from dim">needs a repo</span>}
          </div>
          <SeoPR
            onLog={onLog}
            orgId={orgId}
            repoUrl={activeProperty.repo_url}
            domain={activeProperty.domain}
            baseBranch={activeProperty.base_branch || 'main'}
          />
        </>
      )}

      {!activeProperty && properties.length > 0 && (
        <div className="audit-empty">Select a property above to run README audit or fix with PR.</div>
      )}
    </div>
  )
}

// ────────────────────────────────────────
// Audit History tab
// ────────────────────────────────────────
function HistoryTab({ orgId, history, onRefreshHistory }) {
  const [viewingSaved, setViewingSaved] = useState(null)

  const viewSaved = async (audit) => {
    try {
      const res = await fetch(`${API}/audit/history/${audit.id}`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      if (data.result) setViewingSaved(data)
    } catch { /* ignore */ }
  }

  const deleteSaved = async (id, e) => {
    e.stopPropagation()
    try {
      await fetch(`${API}/audit/history/${id}`, { method: 'DELETE', headers: orgHeaders(orgId) })
      onRefreshHistory?.()
      if (viewingSaved?.id === id) setViewingSaved(null)
    } catch { /* ignore */ }
  }

  if (history.length === 0) {
    return <div className="audit-empty">No audit history yet. Run a scan to get started.</div>
  }

  return (
    <div>
      <div className="audit-history-list">
        {history.map(h => (
          <div key={h.id}
            className={`audit-history-item ${viewingSaved?.id === h.id ? 'active' : ''}`}
            onClick={() => viewSaved(h)}
          >
            <ScoreBadge score={h.score} />
            <span className="audit-history-type">{h.audit_type === 'seo' ? 'SEO' : 'README'}</span>
            <div className="audit-history-detail">
              <span className="audit-history-target">{h.target.replace(/^https?:\/\//, '')}</span>
              <span className="audit-history-date">{formatDate(h.created_at)}</span>
            </div>
            <span className="audit-history-issues">{h.total_issues} {h.audit_type === 'seo' ? 'issues' : 'missing'}</span>
            {h.audit_type === 'seo' && (
              <a href={`/api/audit/history/${h.id}/export`} target="_blank" rel="noreferrer"
                onClick={e => e.stopPropagation()}
                style={{ color: 'var(--text-dim)', fontSize: '10px', textDecoration: 'none', marginRight: 4 }}
                onMouseEnter={e => { e.target.style.color = 'var(--amber)' }}
                onMouseLeave={e => { e.target.style.color = 'var(--text-dim)' }}
              >EXPORT</a>
            )}
            <button className="btn-icon" onClick={e => deleteSaved(h.id, e)} title="Delete">&times;</button>
          </div>
        ))}
      </div>

      {viewingSaved && (
        <div style={{ marginTop: 16 }}>
          <div className="audit-saved-banner">
            Viewing saved {viewingSaved.audit_type === 'seo' ? 'SEO' : 'README'} audit from {formatDate(viewingSaved.created_at)}
            <button className="btn" style={{ fontSize: 11, padding: '3px 10px', marginLeft: 12, color: 'var(--text-dim)', borderColor: 'var(--border)' }}
              onClick={() => setViewingSaved(null)}>Close</button>
          </div>
          {viewingSaved.audit_type === 'seo' && viewingSaved.result && <SeoResults result={viewingSaved.result} orgId={orgId} />}
          {viewingSaved.audit_type === 'readme' && viewingSaved.result && <ReadmeResults result={viewingSaved.result} />}
        </div>
      )}
    </div>
  )
}

// ────────────────────────────────────────
// PropertyManager (site <-> repo bonds)
// ────────────────────────────────────────
function PropertyManager({ orgId, onLog, properties, assets, onRefresh, onSelectProperty, activePropertyId }) {
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({ name: '', domain: '', repo_url: '', base_branch: 'main', site_type: 'static' })

  const siteAssets = (assets || []).filter(a => ['subdomain', 'blog', 'docs', 'product', 'page'].includes(a.asset_type) && a.url)
  const repoAssets = (assets || []).filter(a => a.asset_type === 'repo' && a.url)

  const saveProperty = async () => {
    if (!form.name.trim() || !form.domain.trim()) return
    try {
      const res = await fetch(`${API}/properties`, {
        method: 'POST', headers: orgHeaders(orgId), body: JSON.stringify(form),
      })
      const data = await res.json()
      if (data.error) { onLog?.(`PROPERTY ERROR — ${data.error}`, 'error') }
      else {
        onLog?.(`PROPERTY ADDED — ${data.name}`, 'success')
        setForm({ name: '', domain: '', repo_url: '', base_branch: 'main', site_type: 'static' })
        setShowAdd(false)
        onRefresh()
      }
    } catch (e) { onLog?.(`SAVE FAILED — ${e.message}`, 'error') }
  }

  const deleteProperty = async (id, e) => {
    e.stopPropagation()
    try { await fetch(`${API}/properties/${id}`, { method: 'DELETE', headers: orgHeaders(orgId) }); onRefresh() }
    catch { /* ignore */ }
  }

  if (properties.length === 0 && !showAdd) {
    return (
      <div className="settings-section">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <div className="section-label" style={{ margin: 0 }}>Properties</div>
          <button className="btn btn-sm btn-approve" onClick={() => setShowAdd(true)}>+ Bond Site</button>
        </div>
        <p className="voice-hint" style={{ marginBottom: 0 }}>Bond a site to its repo, or type a domain below.</p>
      </div>
    )
  }

  return (
    <div className="settings-section">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div className="section-label" style={{ margin: 0 }}>Properties</div>
        {!showAdd && <button className="btn btn-sm btn-approve" onClick={() => setShowAdd(true)}>+ Bond Site</button>}
      </div>

      {properties.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: showAdd ? 12 : 0 }}>
          {properties.map(p => (
            <div key={p.id}
              className={`property-card ${activePropertyId === p.id ? 'active' : ''}`}
              onClick={() => onSelectProperty(activePropertyId === p.id ? null : p)}
            >
              <div className="property-card-name">{p.name}</div>
              <div className="property-card-domain">{p.domain.replace(/^https?:\/\//, '')}</div>
              {p.repo_url
                ? <div className="property-card-repo">{p.repo_url.replace(/^https?:\/\/github\.com\//, '')}</div>
                : <div className="property-card-repo" style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>no repo linked</div>}
              <div style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 2 }}>
                {p.site_type || 'static'}
              </div>
              {p.last_audit_score != null && (
                <div className="property-card-score" style={{ color: p.last_audit_score >= 80 ? 'var(--green)' : p.last_audit_score >= 50 ? 'var(--amber)' : 'var(--red)' }}>
                  {p.last_audit_score}/100
                </div>
              )}
              <button className="btn-icon" onClick={e => deleteProperty(p.id, e)} title="Remove"
                style={{ position: 'absolute', top: 4, right: 6, fontSize: 14 }}>&times;</button>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 4, padding: 12 }}>
          <input className="setting-input" style={{ width: '100%', marginBottom: 8 }} value={form.name}
            onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Property name (e.g. DreamFactory Docs)" />
          <div style={{ marginBottom: 8 }}>
            <label style={{ display: 'block', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Site</label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {siteAssets.length > 0 && (
                <select className="setting-input" style={{ width: 240 }}
                  value={siteAssets.some(a => a.url === form.domain) ? form.domain : ''}
                  onChange={e => { if (e.target.value) setForm(f => ({ ...f, domain: e.target.value, name: f.name || siteAssets.find(a => a.url === e.target.value)?.label || e.target.value.replace(/^https?:\/\//, '') })) }}>
                  <option value="">Pick from assets...</option>
                  {siteAssets.map(a => <option key={a.id} value={a.url}>{a.label || a.asset_type} — {a.url.replace(/^https?:\/\//, '').slice(0, 40)}</option>)}
                </select>
              )}
              <input className="setting-input" style={{ flex: 1, minWidth: 200 }} value={form.domain}
                onChange={e => setForm({ ...form, domain: e.target.value })} placeholder="Site URL" spellCheck={false} />
            </div>
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Repo (optional)</label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {repoAssets.length > 0 && (
                <select className="setting-input" style={{ width: 280 }}
                  value={repoAssets.some(a => a.url === form.repo_url) ? form.repo_url : ''}
                  onChange={e => { if (e.target.value) setForm(f => ({ ...f, repo_url: e.target.value })) }}>
                  <option value="">Pick from assets...</option>
                  {repoAssets.map(a => { const m = a.url.match(/github\.com\/([^/]+\/[^/]+)/); return <option key={a.id} value={a.url}>{m ? m[1] : a.label || a.url}</option> })}
                </select>
              )}
              <input className="setting-input" style={{ flex: 1, minWidth: 200 }} value={form.repo_url}
                onChange={e => setForm({ ...form, repo_url: e.target.value })} placeholder="https://github.com/owner/repo" spellCheck={false} />
              <input className="setting-input" style={{ width: 80 }} value={form.base_branch}
                onChange={e => setForm({ ...form, base_branch: e.target.value })} placeholder="main" spellCheck={false} />
            </div>
          </div>
          <div style={{ marginBottom: 12 }}>
            <label style={{ display: 'block', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Site Type</label>
            <div style={{ display: 'flex', gap: 6 }}>
              {[
                { value: 'static', label: 'Static / JAMstack', hint: 'Next.js, Gatsby, Astro, Hugo — repo controls everything' },
                { value: 'cms',    label: 'CMS',               hint: 'WordPress, Webflow, Squarespace — repo is partial or none' },
                { value: 'app',    label: 'App',               hint: 'SaaS — repo is the app, not the marketing site' },
              ].map(t => (
                <button
                  key={t.value}
                  className={`btn btn-sm ${form.site_type === t.value ? 'btn-approve' : ''}`}
                  style={{ fontSize: 10 }}
                  title={t.hint}
                  onClick={() => setForm(f => ({ ...f, site_type: t.value }))}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 4 }}>
              {form.site_type === 'static' && 'All action items sent to pipeline — repo can fix robots.txt, llms.txt, sitemap, and code'}
              {form.site_type === 'cms'    && 'Only on-page, technical, schema, content items sent — config changes excluded'}
              {form.site_type === 'app'    && 'Only technical and schema items sent — content/on-page excluded'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-approve btn-sm" onClick={saveProperty}>Save</button>
            <button className="btn btn-sm" onClick={() => setShowAdd(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ────────────────────────────────────────
// GSC Panel
// ────────────────────────────────────────
function GscPanel({ orgId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [inspectUrl, setInspectUrl] = useState('')
  const [inspecting, setInspecting] = useState(false)
  const [inspectResult, setInspectResult] = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/gsc/summary`, { headers: orgHeaders(orgId) })
      const d = await res.json()
      setData(d)
      if (d.connected) setExpanded(true)
    } catch { /* ignore */ } finally { setLoading(false) }
  }

  const runInspect = async () => {
    if (!inspectUrl.trim()) return
    setInspecting(true)
    setInspectResult(null)
    try {
      const res = await fetch(`${API}/gsc/inspect`, {
        method: 'POST', headers: orgHeaders(orgId),
        body: JSON.stringify({ url: inspectUrl.trim() }),
      })
      const d = await res.json()
      const verdict = d.inspectionResult?.indexStatusResult?.coverageState || d.error || 'Unknown'
      const indexingState = d.inspectionResult?.indexStatusResult?.indexingState || ''
      setInspectResult({ verdict, indexingState })
    } catch (e) { setInspectResult({ verdict: e.message }) }
    finally { setInspecting(false) }
  }

  const isIndexed = v => v?.toLowerCase().includes('indexed') && !v?.toLowerCase().includes('not')

  return (
    <div className="settings-section">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div className="section-label" style={{ margin: 0, cursor: 'pointer', userSelect: 'none' }} onClick={() => setExpanded(p => !p)}>
          <span style={{ fontSize: 9, marginRight: 6 }}>{expanded ? '▼' : '▶'}</span>
          Search Performance (GSC)
          {data?.connected && (
            <span style={{ fontSize: 10, fontWeight: 400, color: 'var(--text-dim)', marginLeft: 8 }}>
              {data.totals?.clicks?.toLocaleString()} clicks · {data.totals?.impressions?.toLocaleString()} impr · pos {data.totals?.position}
            </span>
          )}
        </div>
        <button className={`btn btn-sm ${loading ? 'loading' : ''}`} onClick={load} disabled={loading} style={{ fontSize: 10, padding: '2px 10px' }}>
          {loading ? '...' : data ? 'Refresh' : 'Load GSC'}
        </button>
      </div>

      {expanded && data && !data.connected && <p style={{ color: 'var(--text-dim)', fontSize: 11 }}>GSC not connected. Go to Connections → Google Search Console.</p>}
      {expanded && data?.error && <p style={{ color: 'var(--red)', fontSize: 11 }}>{data.error}</p>}

      {expanded && data?.connected && !data.error && (
        <>
          <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
            {[
              { label: 'Clicks', value: data.totals?.clicks?.toLocaleString() },
              { label: 'Impressions', value: data.totals?.impressions?.toLocaleString() },
              { label: 'Avg CTR', value: `${data.totals?.ctr}%` },
              { label: 'Avg Position', value: data.totals?.position },
            ].map(s => (
              <div key={s.label} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--font-mono)' }}>{s.value}</div>
                <div style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1 }}>{s.label}</div>
              </div>
            ))}
            <div style={{ fontSize: 9, color: 'var(--text-dim)', alignSelf: 'flex-end', marginLeft: 'auto' }}>
              {data.period_days}d · {data.property?.replace(/^https?:\/\//, '')}
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Top Queries</div>
              {data.top_queries?.map((q, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>{q.key}</span>
                  <span style={{ color: 'var(--text-dim)', whiteSpace: 'nowrap', marginLeft: 8 }}>{q.clicks} clk · {q.ctr}% · {q.position}</span>
                </div>
              ))}
            </div>
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Top Pages</div>
              {data.top_pages?.map((p, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>{p.key.replace(/^https?:\/\/[^/]+/, '') || '/'}</span>
                  <span style={{ color: 'var(--text-dim)', whiteSpace: 'nowrap', marginLeft: 8 }}>{p.clicks} clk · {p.ctr}%</span>
                </div>
              ))}
            </div>
          </div>
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>URL Index Check</div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input
                style={{ flex: 1, fontSize: 10, fontFamily: 'var(--font-mono)', background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', padding: '3px 8px' }}
                placeholder="https://yoursite.com/page" value={inspectUrl}
                onChange={e => setInspectUrl(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') runInspect() }}
              />
              <button className="btn btn-sm" style={{ fontSize: 10 }} onClick={runInspect} disabled={inspecting || !inspectUrl.trim()}>
                {inspecting ? '...' : 'Check'}
              </button>
              {inspectResult && (
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.5px', color: isIndexed(inspectResult.verdict) ? 'var(--green)' : 'var(--amber)' }}>
                  {inspectResult.verdict}
                  {inspectResult.indexingState && inspectResult.indexingState !== inspectResult.verdict && (
                    <span style={{ fontWeight: 400, marginLeft: 4 }}>({inspectResult.indexingState})</span>
                  )}
                </span>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ────────────────────────────────────────
// Main Audit Component
// ────────────────────────────────────────
export default function Audit({ onLog, orgId }) {
  const [tab, setTab] = useState('scan')
  const [assets, setAssets] = useState([])
  const [history, setHistory] = useState([])
  const [properties, setProperties] = useState([])
  const [actionItemsKey, setActionItemsKey] = useState(0)

  const loadAssets = useCallback(async () => {
    try {
      const res = await cachedFetch(`${API}/assets`, orgId)
      const data = await res.json()
      setAssets(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
  }, [orgId])

  const loadHistory = useCallback(async () => {
    try {
      const res = await cachedFetch(`${API}/audit/history`, orgId)
      const data = await res.json()
      setHistory(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
  }, [orgId])

  const loadProperties = useCallback(async () => {
    try {
      const res = await cachedFetch(`${API}/properties`, orgId)
      const data = await res.json()
      setProperties(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
  }, [orgId])

  useEffect(() => { loadAssets(); loadHistory(); loadProperties() }, [loadAssets, loadHistory, loadProperties])

  const refreshActionItems = () => setActionItemsKey(k => k + 1)

  const TABS = [
    { id: 'scan', label: 'Scan' },
    { id: 'action-items', label: 'Action Items' },
    { id: 'properties', label: 'Properties' },
    { id: 'history', label: 'History' },
  ]

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2 className="settings-title">Audit</h2>
      </div>

      {/* Tab bar */}
      <div className="audit-tabs">
        {TABS.map(t => (
          <button key={t.id} className={`audit-tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'scan' && (
        <ScanTab
          orgId={orgId}
          onLog={onLog}
          assets={assets}
          onRefreshHistory={loadHistory}
          onRefreshActionItems={refreshActionItems}
        />
      )}

      {tab === 'action-items' && (
        <ActionItemsPanel key={actionItemsKey} orgId={orgId} onLog={onLog} properties={properties} />
      )}

      {tab === 'properties' && (
        <PropertiesTab
          orgId={orgId}
          onLog={onLog}
          assets={assets}
          properties={properties}
          onRefreshProperties={loadProperties}
          onRefreshHistory={loadHistory}
        />
      )}

      {tab === 'history' && (
        <HistoryTab orgId={orgId} history={history} onRefreshHistory={loadHistory} />
      )}
    </div>
  )
}
