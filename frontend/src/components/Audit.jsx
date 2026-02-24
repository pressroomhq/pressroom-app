import { useState, useEffect, useCallback } from 'react'
import SeoPR from './SeoPR'

const API = '/api'

function orgHeaders(orgId) {
  const h = { 'Content-Type': 'application/json' }
  if (orgId) h['X-Org-Id'] = String(orgId)
  return h
}

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
      {found ? '\u2713' : '\u2717'} {label}
    </span>
  )
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

// ────────────────────────────────────────
// SEO Results Display (shared by live + saved)
// ────────────────────────────────────────
function SeoResults({ result }) {
  const [expandedPage, setExpandedPage] = useState(null)

  return (
    <>
      <div className="settings-section">
        <div className="audit-summary">
          <ScoreRing score={result.recommendations?.score || 0} label="SEO" />
          <div className="audit-summary-stats">
            <div className="audit-stat">
              <span className="audit-stat-num">{result.pages_audited}</span>
              <span className="audit-stat-label">pages</span>
            </div>
            <div className="audit-stat">
              <span className="audit-stat-num">{result.recommendations?.total_issues || 0}</span>
              <span className="audit-stat-label">issues</span>
            </div>
            <div className="audit-stat">
              <span className="audit-stat-num">{result.domain}</span>
              <span className="audit-stat-label">domain</span>
            </div>
          </div>
        </div>
      </div>

      <div className="settings-section">
        <div className="section-label">Analysis & Recommendations</div>
        <div className="audit-analysis">
          {result.recommendations?.analysis?.split('\n').map((line, i) => {
            if (!line.trim()) return <br key={i} />
            if (/^[0-9]+\.|^[A-Z]{3,}|^\*\*/.test(line.trim())) {
              return <div key={i} className="audit-section-header">{line.replace(/\*\*/g, '')}</div>
            }
            return <div key={i} className="audit-line">{line}</div>
          })}
        </div>
      </div>

      <div className="settings-section">
        <div className="section-label">Page Details</div>
        {result.pages?.map((p, i) => (
          <div key={i} className="audit-page">
            <div
              className="audit-page-header"
              onClick={() => setExpandedPage(expandedPage === i ? null : i)}
            >
              <div className="audit-page-url">
                <span className="audit-page-toggle">{expandedPage === i ? '\u25BC' : '\u25B6'}</span>
                {p.url.replace(result.domain, '')}
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
                  <span className="audit-detail-value">{p.word_count} words | {p.h2_count} H2s</span>
                </div>
                <div className="audit-detail-row">
                  <span className="audit-detail-label">Images</span>
                  <span className={`audit-detail-value ${p.images_missing_alt > 0 ? 'warn' : ''}`}>
                    {p.total_images} total, {p.images_missing_alt} missing alt
                  </span>
                </div>
                <div className="audit-detail-row">
                  <span className="audit-detail-label">Links</span>
                  <span className="audit-detail-value">{p.internal_links} internal, {p.external_links} external</span>
                </div>
                <div className="audit-detail-row">
                  <span className="audit-detail-label">Technical</span>
                  <span className="audit-detail-value">
                    Canonical: {p.canonical ? 'Yes' : 'No'} | Schema: {p.has_schema ? 'Yes' : 'No'} | OG: {p.og_title ? 'Yes' : 'No'}
                  </span>
                </div>
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
    </>
  )
}

// ────────────────────────────────────────
// README Results Display (shared by live + saved)
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
        <div className="section-label">Analysis & Recommendations</div>
        <div className="audit-analysis">
          {result.recommendations?.analysis?.split('\n').map((line, i) => {
            if (!line.trim()) return <br key={i} />
            if (/^[0-9]+\.|^[A-Z]{3,}|^\*\*/.test(line.trim())) {
              return <div key={i} className="audit-section-header">{line.replace(/\*\*/g, '')}</div>
            }
            return <div key={i} className="audit-line">{line}</div>
          })}
        </div>
      </div>
    </>
  )
}

// ────────────────────────────────────────
// SEO Audit — domain passed as prop, no inputs
// ────────────────────────────────────────
function SeoAudit({ onLog, orgId, domain, onRefreshHistory, onAuditComplete }) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)

  const runAudit = async () => {
    setRunning(true)
    setResult(null)
    onLog?.(`SEO AUDIT — scanning ${domain || 'org domain'}...`, 'action')
    try {
      const res = await fetch(`${API}/audit/seo`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ domain, max_pages: 15 }),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`AUDIT FAILED — ${data.error}`, 'error')
        setResult({ error: data.error })
      } else {
        setResult(data)
        const score = data.recommendations?.score || 0
        onLog?.(`AUDIT COMPLETE — Score: ${score}/100, ${data.pages_audited} pages, ${data.recommendations?.total_issues || 0} issues`, 'success')
        onRefreshHistory?.()
        onAuditComplete?.(score, data.audit_id)
      }
    } catch (e) {
      onLog?.(`AUDIT ERROR — ${e.message}`, 'error')
      setResult({ error: e.message })
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      <div className="settings-section">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            className={`btn btn-run ${running ? 'loading' : ''}`}
            onClick={runAudit}
            disabled={running || !domain}
          >
            {running ? 'Auditing...' : 'Run SEO Audit'}
          </button>
          <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
            {domain ? domain.replace(/^https?:\/\//, '') : 'enter a domain above'}
          </span>
        </div>
      </div>

      {result?.error && (
        <div className="settings-section">
          <div style={{ color: 'var(--red)', fontSize: 13 }}>{result.error}</div>
        </div>
      )}

      {result && !result.error && <SeoResults result={result} />}
    </>
  )
}

// ────────────────────────────────────────
// README Audit — repo/repoUrl/baseBranch passed as props
// ────────────────────────────────────────
function ReadmeAudit({ onLog, orgId, repo, repoUrl, baseBranch, onRefreshHistory }) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [fixing, setFixing] = useState(false)
  const [prUrl, setPrUrl] = useState('')

  const runAudit = async () => {
    if (!repo) {
      onLog?.('README AUDIT — no repo specified', 'error')
      return
    }
    setRunning(true)
    setResult(null)
    setPrUrl('')
    onLog?.(`README AUDIT — analyzing ${repo}...`, 'action')
    try {
      const res = await fetch(`${API}/audit/readme`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ repo }),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`README AUDIT FAILED — ${data.error}`, 'error')
        setResult({ error: data.error })
      } else {
        setResult(data)
        const score = data.recommendations?.score || 0
        onLog?.(`README AUDIT COMPLETE — Score: ${score}/100 for ${data.repo}`, 'success')
        onRefreshHistory?.()
      }
    } catch (e) {
      onLog?.(`README AUDIT ERROR — ${e.message}`, 'error')
      setResult({ error: e.message })
    } finally {
      setRunning(false)
    }
  }

  const fixWithPr = async () => {
    if (!repoUrl) {
      onLog?.('README FIX — no repo URL configured', 'error')
      return
    }
    setFixing(true)
    setPrUrl('')
    onLog?.(`README FIX — improving README and creating PR...`, 'action')
    try {
      const body = { repo_url: repoUrl, base_branch: baseBranch || 'main' }
      if (result?.audit_id) {
        body.audit_id = result.audit_id
      } else if (result?.recommendations?.analysis) {
        body.recommendations = result.recommendations.analysis
      }
      const res = await fetch(`${API}/audit/readme/fix`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`README FIX FAILED — ${data.error}`, 'error')
      } else if (data.pr_url) {
        setPrUrl(data.pr_url)
        onLog?.(`README PR CREATED — ${data.pr_url}`, 'success')
      } else {
        onLog?.('README FIX — no PR created (no changes needed?)', 'warn')
      }
    } catch (e) {
      onLog?.(`README FIX ERROR — ${e.message}`, 'error')
    } finally {
      setFixing(false)
    }
  }

  return (
    <>
      <div className="settings-section">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            className={`btn btn-run ${running ? 'loading' : ''}`}
            onClick={runAudit}
            disabled={running || fixing || !repo}
          >
            {running ? 'Auditing...' : 'Run README Audit'}
          </button>
          {result && !result.error && repoUrl && (
            <button
              className={`btn btn-approve ${fixing ? 'loading' : ''}`}
              onClick={fixWithPr}
              disabled={fixing || running}
            >
              {fixing ? 'Creating PR...' : 'Fix with PR'}
            </button>
          )}
          <span style={{ color: 'var(--text-dim)', fontSize: 12, fontStyle: repo ? 'normal' : 'italic' }}>
            {repo || 'add a repo above'}
          </span>
          {prUrl && (
            <a
              href={prUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--green)', textDecoration: 'none', fontSize: 12 }}
            >
              View PR &rarr;
            </a>
          )}
        </div>
      </div>

      {result?.error && (
        <div className="settings-section">
          <div style={{ color: 'var(--red)', fontSize: 13 }}>{result.error}</div>
        </div>
      )}

      {result && !result.error && <ReadmeResults result={result} />}
    </>
  )
}

// ────────────────────────────────────────
// Small score badge for history list
// ────────────────────────────────────────
function ScoreBadge({ score }) {
  const color = score >= 80 ? 'var(--green)' : score >= 50 ? 'var(--amber)' : 'var(--red)'
  return (
    <span className="audit-score-badge" style={{ background: color }}>
      {score}
    </span>
  )
}

// ────────────────────────────────────────
// Properties Manager (site <-> repo bonds)
// ────────────────────────────────────────
function PropertyManager({ orgId, onLog, properties, assets, onRefresh, onSelectProperty, activePropertyId }) {
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({ name: '', domain: '', repo_url: '', base_branch: 'main' })

  const siteAssets = (assets || []).filter(a =>
    ['subdomain', 'blog', 'docs', 'product', 'page'].includes(a.asset_type) && a.url
  )
  const repoAssets = (assets || []).filter(a => a.asset_type === 'repo' && a.url)

  const handleSiteSelect = (url) => {
    if (!url) return
    setForm(f => ({
      ...f,
      domain: url,
      name: f.name || siteAssets.find(a => a.url === url)?.label || url.replace(/^https?:\/\//, ''),
    }))
  }

  const handleRepoSelect = (url) => {
    if (!url) return
    setForm(f => ({ ...f, repo_url: url }))
  }

  const saveProperty = async () => {
    if (!form.name.trim() || !form.domain.trim()) return
    try {
      const res = await fetch(`${API}/properties`, {
        method: 'POST', headers: orgHeaders(orgId),
        body: JSON.stringify(form),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`PROPERTY ERROR — ${data.error}`, 'error')
      } else {
        onLog?.(`PROPERTY ADDED — ${data.name}`, 'success')
        setForm({ name: '', domain: '', repo_url: '', base_branch: 'main' })
        setShowAdd(false)
        onRefresh()
      }
    } catch (e) {
      onLog?.(`SAVE FAILED — ${e.message}`, 'error')
    }
  }

  const deleteProperty = async (id, e) => {
    e.stopPropagation()
    try {
      await fetch(`${API}/properties/${id}`, { method: 'DELETE', headers: orgHeaders(orgId) })
      onRefresh()
    } catch { /* ignore */ }
  }

  return (
    <div className="settings-section">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div className="section-label" style={{ margin: 0 }}>Properties</div>
        {!showAdd && (
          <button className="btn btn-sm btn-approve" onClick={() => setShowAdd(true)}>+ Bond Site</button>
        )}
      </div>

      {properties.length === 0 && !showAdd && (
        <p className="voice-hint" style={{ marginBottom: 0 }}>
          Bond a site to its repo, or use ad-hoc inputs below.
        </p>
      )}

      {properties.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: showAdd ? 12 : 0 }}>
          {properties.map(p => (
            <div
              key={p.id}
              className={`property-card ${activePropertyId === p.id ? 'active' : ''}`}
              onClick={() => onSelectProperty(activePropertyId === p.id ? null : p)}
            >
              <div className="property-card-name">{p.name}</div>
              <div className="property-card-domain">{p.domain.replace(/^https?:\/\//, '')}</div>
              {p.repo_url && (
                <div className="property-card-repo">
                  {p.repo_url.replace(/^https?:\/\/github\.com\//, '')}
                </div>
              )}
              {!p.repo_url && (
                <div className="property-card-repo" style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>no repo linked</div>
              )}
              {p.last_audit_score != null && (
                <div className="property-card-score" style={{
                  color: p.last_audit_score >= 80 ? 'var(--green)' : p.last_audit_score >= 50 ? 'var(--amber)' : 'var(--red)'
                }}>
                  {p.last_audit_score}/100
                </div>
              )}
              <button
                className="btn-icon"
                onClick={(e) => deleteProperty(p.id, e)}
                title="Remove property"
                style={{ position: 'absolute', top: 4, right: 6, fontSize: 14 }}
              >&times;</button>
            </div>
          ))}
        </div>
      )}

      {showAdd && (
        <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 4, padding: 12, marginBottom: 0 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
            <input
              className="setting-input"
              style={{ flex: 1, minWidth: 150 }}
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder="Property name (e.g. DreamFactory Docs)"
            />
          </div>
          <div style={{ marginBottom: 4 }}>
            <label style={{ display: 'block', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Site</label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {siteAssets.length > 0 && (
                <select
                  className="setting-input"
                  style={{ width: 240 }}
                  value={siteAssets.some(a => a.url === form.domain) ? form.domain : ''}
                  onChange={e => handleSiteSelect(e.target.value)}
                >
                  <option value="">Pick from assets...</option>
                  {siteAssets.map(a => (
                    <option key={a.id} value={a.url}>
                      {a.label || a.asset_type} — {a.url.replace(/^https?:\/\//, '').slice(0, 40)}
                    </option>
                  ))}
                </select>
              )}
              <input
                className="setting-input"
                style={{ flex: 1, minWidth: 200 }}
                value={form.domain}
                onChange={e => setForm({ ...form, domain: e.target.value })}
                placeholder={siteAssets.length > 0 ? 'or type a URL' : 'Site URL (e.g. docs.dreamfactory.com)'}
                spellCheck={false}
              />
            </div>
          </div>
          <div style={{ marginBottom: 8, marginTop: 8 }}>
            <label style={{ display: 'block', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Repo (optional)</label>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {repoAssets.length > 0 && (
                <select
                  className="setting-input"
                  style={{ width: 280 }}
                  value={repoAssets.some(a => a.url === form.repo_url) ? form.repo_url : ''}
                  onChange={e => handleRepoSelect(e.target.value)}
                >
                  <option value="">Pick from assets...</option>
                  {repoAssets.map(a => {
                    const match = a.url.match(/github\.com\/([^/]+\/[^/]+)/)
                    const label = match ? match[1] : a.label || a.url
                    return (
                      <option key={a.id} value={a.url}>{label}</option>
                    )
                  })}
                </select>
              )}
              <input
                className="setting-input"
                style={{ flex: 1, minWidth: 200 }}
                value={form.repo_url}
                onChange={e => setForm({ ...form, repo_url: e.target.value })}
                placeholder={repoAssets.length > 0 ? 'or type a repo URL' : 'https://github.com/owner/repo'}
                spellCheck={false}
              />
              <input
                className="setting-input"
                style={{ width: 100 }}
                value={form.base_branch}
                onChange={e => setForm({ ...form, base_branch: e.target.value })}
                placeholder="main"
                spellCheck={false}
              />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-approve btn-sm" onClick={saveProperty}>Save Property</button>
            <button className="btn btn-sm" onClick={() => setShowAdd(false)}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}


// ────────────────────────────────────────
// Shared Audit History
// ────────────────────────────────────────
function AuditHistory({ orgId, history, onRefreshHistory }) {
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

  if (history.length === 0) return null

  return (
    <>
      <div className="settings-section">
        <div className="section-label">Audit History</div>
        <div className="audit-history-list">
          {history.map(h => (
            <div
              key={h.id}
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
                <a
                  href={`/api/audit/history/${h.id}/export`}
                  target="_blank"
                  rel="noreferrer"
                  onClick={e => e.stopPropagation()}
                  style={{ color: 'var(--text-dim, #555)', fontSize: '10px', textDecoration: 'none', marginRight: 4 }}
                  onMouseEnter={e => { e.target.style.color = 'var(--amber, #ffb000)' }}
                  onMouseLeave={e => { e.target.style.color = 'var(--text-dim, #555)' }}
                >EXPORT</a>
              )}
              <button
                className="btn-icon"
                onClick={(e) => deleteSaved(h.id, e)}
                title="Delete"
              >&times;</button>
            </div>
          ))}
        </div>
      </div>

      {viewingSaved && (
        <>
          <div className="audit-saved-banner">
            Viewing saved {viewingSaved.audit_type === 'seo' ? 'SEO' : 'README'} audit from {formatDate(viewingSaved.created_at)}
            <button className="btn" style={{ fontSize: 11, padding: '3px 10px', marginLeft: 12, color: 'var(--text-dim)', borderColor: 'var(--border)' }}
              onClick={() => setViewingSaved(null)}>
              Close
            </button>
          </div>
          {viewingSaved.audit_type === 'seo' && viewingSaved.result && <SeoResults result={viewingSaved.result} />}
          {viewingSaved.audit_type === 'readme' && viewingSaved.result && <ReadmeResults result={viewingSaved.result} />}
        </>
      )}
    </>
  )
}


// ────────────────────────────────────────
// GSC Search Performance Panel
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
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  const runInspect = async () => {
    if (!inspectUrl.trim()) return
    setInspecting(true)
    setInspectResult(null)
    try {
      const res = await fetch(`${API}/gsc/inspect`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ url: inspectUrl.trim() }),
      })
      const d = await res.json()
      const verdict = d.inspectionResult?.indexStatusResult?.coverageState || d.error || 'Unknown'
      const indexingState = d.inspectionResult?.indexStatusResult?.indexingState || ''
      setInspectResult({ verdict, indexingState })
    } catch (e) {
      setInspectResult({ verdict: e.message })
    } finally {
      setInspecting(false)
    }
  }

  const isIndexed = (v) => v?.toLowerCase().includes('indexed') && !v?.toLowerCase().includes('not')

  return (
    <div className="settings-section">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div
          className="section-label"
          style={{ margin: 0, cursor: 'pointer', userSelect: 'none' }}
          onClick={() => setExpanded(p => !p)}
        >
          <span style={{ fontSize: 9, marginRight: 6 }}>{expanded ? '▼' : '▶'}</span>
          Search Performance (GSC)
          {data?.connected && (
            <span style={{ fontSize: 10, fontWeight: 400, color: 'var(--text-dim)', marginLeft: 8 }}>
              {data.totals?.clicks?.toLocaleString()} clicks · {data.totals?.impressions?.toLocaleString()} impr · pos {data.totals?.position}
            </span>
          )}
        </div>
        <button
          className={`btn btn-sm ${loading ? 'loading' : ''}`}
          onClick={load}
          disabled={loading}
          style={{ fontSize: 10, padding: '2px 10px' }}
        >
          {loading ? '...' : data ? 'Refresh' : 'Load GSC'}
        </button>
      </div>

      {expanded && data && !data.connected && (
        <p style={{ color: 'var(--text-dim)', fontSize: 11 }}>
          GSC not connected. Go to Connections → Google Search Console.
        </p>
      )}

      {expanded && data?.error && (
        <p style={{ color: 'var(--red)', fontSize: 11 }}>{data.error}</p>
      )}

      {expanded && data?.connected && !data.error && (
        <>
          {/* Totals row */}
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

          {/* Top queries + top pages side by side */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Top Queries</div>
              {data.top_queries?.map((q, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>{q.key}</span>
                  <span style={{ color: 'var(--text-dim)', whiteSpace: 'nowrap', marginLeft: 8 }}>
                    {q.clicks} clk · {q.ctr}% · {q.position}
                  </span>
                </div>
              ))}
            </div>
            <div>
              <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Top Pages</div>
              {data.top_pages?.map((p, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '3px 0', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '60%' }}>
                    {p.key.replace(/^https?:\/\/[^/]+/, '') || '/'}
                  </span>
                  <span style={{ color: 'var(--text-dim)', whiteSpace: 'nowrap', marginLeft: 8 }}>
                    {p.clicks} clk · {p.ctr}%
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* URL Inspector */}
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>URL Index Check</div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input
                style={{ flex: 1, fontSize: 10, fontFamily: 'var(--font-mono)', background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', padding: '3px 8px' }}
                placeholder="https://yoursite.com/page"
                value={inspectUrl}
                onChange={e => setInspectUrl(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') runInspect() }}
              />
              <button className="btn btn-sm" style={{ fontSize: 10 }} onClick={runInspect} disabled={inspecting || !inspectUrl.trim()}>
                {inspecting ? '...' : 'Check'}
              </button>
              {inspectResult && (
                <span style={{
                  fontSize: 10, fontWeight: 700, letterSpacing: '0.5px',
                  color: isIndexed(inspectResult.verdict) ? 'var(--green)' : 'var(--amber)',
                }}>
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
  const [assets, setAssets] = useState([])
  const [history, setHistory] = useState([])
  const [properties, setProperties] = useState([])
  const [activeProperty, setActiveProperty] = useState(null)

  // Ad-hoc inputs — used when no property is selected
  const [adhocDomain, setAdhocDomain] = useState('')
  const [adhocRepo, setAdhocRepo] = useState('')
  const [adhocBranch, setAdhocBranch] = useState('main')

  const loadAssets = useCallback(async () => {
    try {
      const res = await fetch(`${API}/assets`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      setAssets(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
  }, [orgId])

  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API}/audit/history`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      setHistory(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
  }, [orgId])

  const loadProperties = useCallback(async () => {
    try {
      const res = await fetch(`${API}/properties`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      setProperties(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
  }, [orgId])

  useEffect(() => { loadAssets(); loadHistory(); loadProperties() }, [loadAssets, loadHistory, loadProperties])

  const handleSelectProperty = (prop) => {
    setActiveProperty(prop)
  }

  // After an audit completes, update the property's last score
  const handleAuditComplete = async (score, auditId) => {
    if (!activeProperty) return
    try {
      await fetch(`${API}/properties/${activeProperty.id}`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ last_audit_score: score, last_audit_id: auditId }),
      })
      loadProperties()
    } catch { /* ignore */ }
  }

  // Asset lists for ad-hoc dropdowns
  const siteAssets = assets.filter(a =>
    ['subdomain', 'blog', 'docs', 'product', 'page'].includes(a.asset_type) && a.url
  )
  const repoAssets = assets.filter(a => a.asset_type === 'repo' && a.url)

  // Derive effective values: property wins, ad-hoc is fallback
  const effectiveDomain = activeProperty?.domain || adhocDomain
  const effectiveRepoUrl = activeProperty?.repo_url || adhocRepo
  const effectiveBranch = activeProperty?.base_branch || adhocBranch
  // Extract owner/repo for README audit
  const repoSlug = (() => {
    if (!effectiveRepoUrl) return ''
    const match = effectiveRepoUrl.match(/github\.com\/([^/]+\/[^/]+)/)
    return match ? match[1] : effectiveRepoUrl
  })()

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2 className="settings-title">SEO Audit</h2>
      </div>

      <PropertyManager
        orgId={orgId}
        onLog={onLog}
        properties={properties}
        assets={assets}
        onRefresh={loadProperties}
        onSelectProperty={handleSelectProperty}
        activePropertyId={activeProperty?.id}
      />

      {/* ── AD-HOC INPUTS — only when no property selected ── */}
      {!activeProperty && (
        <div className="settings-section">
          <div className="section-label" style={{ marginBottom: 6 }}>Target</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div style={{ flex: 2, minWidth: 200 }}>
              <label style={{ display: 'block', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Site</label>
              {siteAssets.length > 0 && (
                <select
                  className="setting-input"
                  style={{ width: '100%', marginBottom: 4 }}
                  value={siteAssets.some(a => a.url === adhocDomain) ? adhocDomain : ''}
                  onChange={e => { if (e.target.value) setAdhocDomain(e.target.value) }}
                >
                  <option value="">Pick from assets...</option>
                  {siteAssets.map(a => (
                    <option key={a.id} value={a.url}>
                      {a.label || a.asset_type} — {a.url.replace(/^https?:\/\//, '').slice(0, 40)}
                    </option>
                  ))}
                </select>
              )}
              <input
                className="setting-input"
                style={{ width: '100%' }}
                value={adhocDomain}
                onChange={e => setAdhocDomain(e.target.value)}
                placeholder="docs.example.com"
                spellCheck={false}
              />
            </div>
            <div style={{ flex: 2, minWidth: 200 }}>
              <label style={{ display: 'block', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Repo</label>
              {repoAssets.length > 0 && (
                <select
                  className="setting-input"
                  style={{ width: '100%', marginBottom: 4 }}
                  value={repoAssets.some(a => a.url === adhocRepo) ? adhocRepo : ''}
                  onChange={e => { if (e.target.value) setAdhocRepo(e.target.value) }}
                >
                  <option value="">Pick from assets...</option>
                  {repoAssets.map(a => {
                    const match = a.url.match(/github\.com\/([^/]+\/[^/]+)/)
                    const label = match ? match[1] : a.label || a.url
                    return <option key={a.id} value={a.url}>{label}</option>
                  })}
                </select>
              )}
              <input
                className="setting-input"
                style={{ width: '100%' }}
                value={adhocRepo}
                onChange={e => setAdhocRepo(e.target.value)}
                placeholder="https://github.com/owner/repo"
                spellCheck={false}
              />
            </div>
            <div style={{ width: 100 }}>
              <label style={{ display: 'block', color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Branch</label>
              <input
                className="setting-input"
                style={{ width: '100%' }}
                value={adhocBranch}
                onChange={e => setAdhocBranch(e.target.value)}
                placeholder="main"
                spellCheck={false}
              />
            </div>
          </div>
        </div>
      )}

      {/* ── SEARCH PERFORMANCE ── */}
      <GscPanel orgId={orgId} />

      {/* ── SITE AUDIT ── */}
      <div className="audit-section-divider">
        <span className="section-label">Site Audit</span>
        {activeProperty?.domain && <span className="audit-section-from">{activeProperty.name}</span>}
      </div>
      <SeoAudit
        onLog={onLog}
        orgId={orgId}
        domain={effectiveDomain}
        onRefreshHistory={loadHistory}
        onAuditComplete={handleAuditComplete}
      />

      {/* ── README AUDIT ── */}
      <div className="audit-section-divider">
        <span className="section-label">README Audit</span>
        {activeProperty?.repo_url && <span className="audit-section-from">{activeProperty.name}</span>}
      </div>
      <ReadmeAudit
        onLog={onLog}
        orgId={orgId}
        repo={repoSlug}
        repoUrl={effectiveRepoUrl}
        baseBranch={effectiveBranch}
        onRefreshHistory={loadHistory}
      />

      {/* ── FIX WITH PR ── */}
      <div className="audit-section-divider">
        <span className="section-label">Fix with PR</span>
        {activeProperty?.repo_url && <span className="audit-section-from">{activeProperty.name}</span>}
        {!effectiveRepoUrl && <span className="audit-section-from dim">needs a repo</span>}
      </div>
      <SeoPR
        onLog={onLog}
        orgId={orgId}
        repoUrl={effectiveRepoUrl}
        domain={effectiveDomain}
        baseBranch={effectiveBranch}
      />

      {/* ── HISTORY ── */}
      <AuditHistory orgId={orgId} history={history} onRefreshHistory={loadHistory} />
    </div>
  )
}
