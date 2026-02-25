import { useState, useEffect, useCallback } from 'react'
import { orgHeaders } from '../api'

const API = '/api'

function TagEditor({ tags, onUpdate, placeholder }) {
  const [input, setInput] = useState('')
  const add = () => {
    const v = input.trim()
    if (v && !tags.includes(v)) {
      onUpdate([...tags, v])
      setInput('')
    }
  }
  const remove = (i) => onUpdate(tags.filter((_, idx) => idx !== i))
  return (
    <div className="tag-list">
      {tags.map((t, i) => (
        <span key={i} className="tag tag-amber" onClick={() => remove(i)}>
          {t} <span className="tag-x">&times;</span>
        </span>
      ))}
      <input
        className="tag-input"
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
        onBlur={add}
        placeholder={placeholder}
      />
    </div>
  )
}

export default function Company({ orgId, onLog }) {
  const [settings, setSettings] = useState({})
  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const [industry, setIndustry] = useState('')
  const [topics, setTopics] = useState([])
  const [competitors, setCompetitors] = useState([])
  const [socials, setSocials] = useState({ linkedin: '', x: '', github: '', blog: '', facebook: '', instagram: '', youtube: '' })
  const [properties, setProperties] = useState({ docs: '', support: '', careers: '', customers: '', pricing: '', changelog: '', status: '', newsletter: '' })
  const [ghOrgs, setGhOrgs] = useState([])
  const [saving, setSaving] = useState(null) // which section is saving
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState(null)
  const [auditing, setAuditing] = useState(false)
  const [auditResults, setAuditResults] = useState(null)
  const [brandScanning, setBrandScanning] = useState(false)
  const [brandData, setBrandData] = useState(null)

  const headers = orgHeaders(orgId)

  const getVal = (key) => {
    const s = settings[key]
    return s?.value ?? s ?? ''
  }

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/settings`, { headers: orgHeaders(orgId) })
      if (!res.ok) return
      const data = await res.json()
      setSettings(data)

      setName(data.onboard_company_name?.value || '')
      setDomain(data.onboard_domain?.value || '')
      setIndustry(data.onboard_industry?.value || '')

      try { setTopics(JSON.parse(data.onboard_topics?.value || '[]')) } catch { setTopics([]) }
      try { setCompetitors(JSON.parse(data.onboard_competitors?.value || '[]')) } catch { setCompetitors([]) }
      try { setGhOrgs(JSON.parse(data.scout_github_orgs?.value || '[]')) } catch { setGhOrgs([]) }

      try {
        const sp = JSON.parse(data.social_profiles?.value || '{}')
        setSocials({
          linkedin: sp.linkedin || '',
          x: sp.x || sp.twitter || '',
          github: sp.github || '',
          blog: sp.blog || '',
          facebook: sp.facebook || '',
          instagram: sp.instagram || '',
          youtube: sp.youtube || '',
        })
      } catch { /* keep defaults */ }

      try {
        const cp = JSON.parse(data.company_properties?.value || '{}')
        setProperties(prev => ({ ...prev, ...cp }))
      } catch { /* keep defaults */ }
    } catch { /* ignore */ }
  }, [orgId])

  useEffect(() => { load() }, [load])

  // Load brand data
  useEffect(() => {
    if (!orgId) return
    fetch(`${API}/brand/${orgId}`, { headers: orgHeaders(orgId) })
      .then(r => r.json())
      .then(d => { if (d && !d.error) setBrandData(d) })
      .catch(() => {})
  }, [orgId])

  const scanBrand = async () => {
    setBrandScanning(true)
    try {
      const res = await fetch(`${API}/brand/scrape`, {
        method: 'POST', headers,
        body: JSON.stringify({ url: domain }),
      })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      const data = await res.json()
      if (data.error) {
        onLog?.(`Brand scan failed: ${data.error}`, 'error')
      } else {
        setBrandData(data)
        onLog?.(`Brand scan complete — ${data.company_name || 'unknown'}`, 'success')
      }
    } catch (e) {
      onLog?.(`Brand scan error: ${e.message}`, 'error')
    }
    setBrandScanning(false)
  }

  const saveSection = async (section, payload) => {
    setSaving(section)
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT', headers,
        body: JSON.stringify({ settings: payload }),
      })
      onLog?.(`Company ${section} saved`, 'success')
      await load()
    } catch (e) {
      onLog?.(`Save failed: ${e.message}`, 'error')
    }
    setSaving(null)
  }

  const saveIdentity = () => saveSection('identity', {
    onboard_company_name: name,
    onboard_domain: domain,
    onboard_industry: industry,
  })

  const saveTopics = () => saveSection('topics', {
    onboard_topics: JSON.stringify(topics),
    onboard_competitors: JSON.stringify(competitors),
  })

  const saveSocials = () => saveSection('socials', {
    social_profiles: JSON.stringify(socials),
  })

  const saveProperties = () => saveSection('properties', {
    company_properties: JSON.stringify(properties),
  })

  const saveOrgs = () => saveSection('orgs', {
    scout_github_orgs: JSON.stringify(ghOrgs),
  })

  const syncRepos = async () => {
    // Save orgs first, then sync
    await saveOrgs()
    setSyncing(true)
    setSyncResult(null)
    onLog?.('GITHUB SYNC — discovering repos from configured orgs...', 'action')
    try {
      const res = await fetch(`${API}/assets/github/sync-orgs`, {
        method: 'POST', headers,
      })
      const data = await res.json()
      if (data.error) {
        setSyncResult(data.error)
        onLog?.(`GITHUB SYNC FAILED — ${data.error}`, 'error')
      } else {
        const parts = Object.entries(data.orgs || {}).map(([org, info]) =>
          info.error ? `${org}: error` : `${org}: ${info.found} found, ${info.added} new`
        )
        const msg = `Synced ${data.synced} new repos. ${parts.join('. ')}`
        setSyncResult(msg)
        onLog?.(`GITHUB SYNC — ${msg}`, 'success')
      }
    } catch (e) {
      setSyncResult(`Error: ${e.message}`)
      onLog?.(`GITHUB SYNC ERROR — ${e.message}`, 'error')
    }
    setSyncing(false)
  }

  const runAudit = async () => {
    setAuditing(true)
    setAuditResults(null)
    onLog?.('AUDIT — analyzing company digital presence...', 'action')
    try {
      const res = await fetch(`${API}/company/audit`, { method: 'POST', headers })
      if (!res.ok) throw new Error(`Server error (${res.status})`)
      const data = await res.json()
      if (data.error) {
        onLog?.(`AUDIT FAILED — ${data.error}`, 'error')
      } else {
        const crit = (data.findings || []).filter(f => f.severity === 'critical').length
        const warn = (data.findings || []).filter(f => f.severity === 'warning').length
        const opp = (data.findings || []).filter(f => f.severity === 'opportunity').length
        setAuditResults(data.findings || [])
        onLog?.(`AUDIT COMPLETE — ${crit} critical, ${warn} warnings, ${opp} opportunities`, 'success')
      }
    } catch (e) {
      onLog?.(`AUDIT ERROR — ${e.message}`, 'error')
    }
    setAuditing(false)
  }

  const severityIcon = { critical: '\u26A0', warning: '\u25CB', opportunity: '\u2197' }
  const severityColor = { critical: 'var(--red, #c44)', warning: 'var(--amber)', opportunity: 'var(--green)' }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2 className="settings-title">Company</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            className={`btn btn-run ${auditing ? 'loading' : ''}`}
            onClick={runAudit}
            disabled={auditing}
          >
            {auditing ? 'Auditing...' : 'Run Company Audit'}
          </button>
        </div>
      </div>

      {/* AUDIT RESULTS */}
      {auditResults && (
        <div className="settings-section">
          <div className="section-label">
            Audit Findings <span className="section-count">{auditResults.length}</span>
          </div>
          {auditResults.length === 0 ? (
            <p style={{ color: 'var(--green)', fontSize: 12 }}>No issues found. Looking good.</p>
          ) : (
            <div className="audit-findings">
              {auditResults.map((f, i) => (
                <div key={i} className="audit-finding" style={{ borderLeftColor: severityColor[f.severity] || 'var(--border)' }}>
                  <div className="audit-finding-header">
                    <span style={{ color: severityColor[f.severity], marginRight: 6 }}>{severityIcon[f.severity]}</span>
                    <span className="audit-finding-title">{f.title}</span>
                    <span className="audit-finding-category">{f.category}</span>
                  </div>
                  <div className="audit-finding-detail">{f.detail}</div>
                  {f.metric && <div className="audit-finding-metric">{f.metric}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* IDENTITY */}
      <div className="settings-section">
        <div className="section-label">Identity</div>
        <div className="company-field-grid">
          <div className="company-field">
            <label className="company-field-label">Company Name</label>
            <input className="setting-input" value={name} onChange={e => setName(e.target.value)} placeholder="Acme Corp" />
          </div>
          <div className="company-field">
            <label className="company-field-label">Domain</label>
            <input className="setting-input" value={domain} onChange={e => setDomain(e.target.value)} placeholder="acme.com" />
          </div>
          <div className="company-field">
            <label className="company-field-label">Industry</label>
            <input className="setting-input" value={industry} onChange={e => setIndustry(e.target.value)} placeholder="Enterprise Software" />
          </div>
        </div>
        <div style={{ marginTop: 12, textAlign: 'right' }}>
          <button className={`btn btn-approve ${saving === 'identity' ? 'loading' : ''}`} onClick={saveIdentity} disabled={!!saving}>
            {saving === 'identity' ? 'Saving...' : 'Save Identity'}
          </button>
        </div>
      </div>

      {/* BRAND IDENTITY */}
      <div className="settings-section">
        <div className="section-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Brand Identity</span>
          <button
            className={`btn btn-run ${brandScanning ? 'loading' : ''}`}
            onClick={scanBrand}
            disabled={brandScanning || !domain}
            style={{ fontSize: 11 }}
          >
            {brandScanning ? 'Scanning...' : 'Scan Branding'}
          </button>
        </div>
        {brandData && (
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
            {brandData.logo_url && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <img src={brandData.logo_url} alt="Logo" style={{ maxHeight: 40, maxWidth: 120, background: '#222', padding: 4, borderRadius: 4 }} onError={e => e.target.style.display='none'} />
                <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>LOGO</span>
              </div>
            )}
            {brandData.primary_color && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 32, height: 32, borderRadius: 4, background: brandData.primary_color, border: '1px solid var(--border)' }} />
                <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>{brandData.primary_color}</span>
              </div>
            )}
            {brandData.secondary_color && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
                <div style={{ width: 32, height: 32, borderRadius: 4, background: brandData.secondary_color, border: '1px solid var(--border)' }} />
                <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>{brandData.secondary_color}</span>
              </div>
            )}
            {brandData.font_family && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <span style={{ fontSize: 13, fontFamily: brandData.font_family }}>Aa</span>
                <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>{brandData.font_family.split(',')[0]}</span>
              </div>
            )}
            {!brandData.logo_url && !brandData.primary_color && (
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>No brand data yet. Click "Scan Branding" to detect.</span>
            )}
          </div>
        )}
        {!brandData && !brandScanning && (
          <p style={{ fontSize: 12, color: 'var(--text-dim)', margin: '8px 0' }}>
            {domain ? 'Click "Scan Branding" to detect logo, colors, and fonts from your website.' : 'Set a domain first, then scan for brand assets.'}
          </p>
        )}
      </div>

      {/* TOPICS & COMPETITORS */}
      <div className="settings-section">
        <div className="section-label">Topics <span className="section-count">{topics.length}</span></div>
        <TagEditor tags={topics} onUpdate={setTopics} placeholder="add topic..." />

        <div className="section-label" style={{ marginTop: 16 }}>Competitors <span className="section-count">{competitors.length}</span></div>
        <TagEditor tags={competitors} onUpdate={setCompetitors} placeholder="add competitor..." />

        <div style={{ marginTop: 12, textAlign: 'right' }}>
          <button className={`btn btn-approve ${saving === 'topics' ? 'loading' : ''}`} onClick={saveTopics} disabled={!!saving}>
            {saving === 'topics' ? 'Saving...' : 'Save Topics'}
          </button>
        </div>
      </div>

      {/* SOCIAL PROFILES */}
      <div className="settings-section">
        <div className="section-label">Social Profiles</div>
        <div className="company-field-grid">
          {[
            { key: 'linkedin', label: 'LinkedIn', ph: 'https://linkedin.com/company/...' },
            { key: 'x', label: 'Twitter / X', ph: 'https://x.com/...' },
            { key: 'github', label: 'GitHub', ph: 'https://github.com/...' },
            { key: 'blog', label: 'Blog / News', ph: 'https://blog.acme.com' },
            { key: 'facebook', label: 'Facebook', ph: 'https://facebook.com/...' },
            { key: 'instagram', label: 'Instagram', ph: 'https://instagram.com/...' },
            { key: 'youtube', label: 'YouTube', ph: 'https://youtube.com/@...' },
          ].map(s => (
            <div key={s.key} className="company-field">
              <label className="company-field-label">{s.label}</label>
              <input
                className="setting-input"
                value={socials[s.key]}
                onChange={e => setSocials(prev => ({ ...prev, [s.key]: e.target.value }))}
                placeholder={s.ph}
              />
            </div>
          ))}
        </div>
        <div style={{ marginTop: 12, textAlign: 'right' }}>
          <button className={`btn btn-approve ${saving === 'socials' ? 'loading' : ''}`} onClick={saveSocials} disabled={!!saving}>
            {saving === 'socials' ? 'Saving...' : 'Save Socials'}
          </button>
        </div>
      </div>

      {/* DIGITAL PROPERTIES */}
      <div className="settings-section">
        <div className="section-label">Digital Properties</div>
        <p style={{ color: 'var(--text-dim)', fontSize: 12, margin: '0 0 8px' }}>
          Key URLs for your company's web presence. Auto-discovered during onboarding, editable here. Drives the company audit.
        </p>
        <div className="company-field-grid">
          {[
            { key: 'docs', label: 'Documentation', ph: 'https://docs.acme.com' },
            { key: 'support', label: 'Support / Help', ph: 'https://support.acme.com' },
            { key: 'pricing', label: 'Pricing', ph: 'https://acme.com/pricing' },
            { key: 'careers', label: 'Careers', ph: 'https://acme.com/careers' },
            { key: 'customers', label: 'Customers / Cases', ph: 'https://acme.com/customers' },
            { key: 'changelog', label: 'Changelog', ph: 'https://acme.com/changelog' },
            { key: 'status', label: 'Status Page', ph: 'https://status.acme.com' },
            { key: 'newsletter', label: 'Newsletter', ph: 'https://acme.com/newsletter' },
          ].map(p => (
            <div key={p.key} className="company-field">
              <label className="company-field-label">{p.label}</label>
              <input
                className="setting-input"
                value={properties[p.key]}
                onChange={e => setProperties(prev => ({ ...prev, [p.key]: e.target.value }))}
                placeholder={p.ph}
              />
            </div>
          ))}
        </div>
        <div style={{ marginTop: 12, textAlign: 'right' }}>
          <button className={`btn btn-approve ${saving === 'properties' ? 'loading' : ''}`} onClick={saveProperties} disabled={!!saving}>
            {saving === 'properties' ? 'Saving...' : 'Save Properties'}
          </button>
        </div>
      </div>

      {/* GITHUB ORGANIZATIONS */}
      <div className="settings-section">
        <div className="section-label">GitHub Organizations <span className="section-count">{ghOrgs.length}</span></div>
        <p style={{ color: 'var(--text-dim)', fontSize: 12, margin: '0 0 8px' }}>
          Add org names to discover all repos. Synced repos appear in your asset map and are monitored by the scout.
        </p>
        <TagEditor tags={ghOrgs} onUpdate={setGhOrgs} placeholder="add org name (e.g. treehouse)..." />

        <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className={`btn btn-approve ${saving === 'orgs' ? 'loading' : ''}`} onClick={saveOrgs} disabled={!!saving}>
            {saving === 'orgs' ? 'Saving...' : 'Save Orgs'}
          </button>
          <button
            className={`btn btn-run ${syncing ? 'loading' : ''}`}
            onClick={syncRepos}
            disabled={syncing || ghOrgs.length === 0}
          >
            {syncing ? 'Syncing...' : 'Sync Repos'}
          </button>
        </div>

        {syncResult && (
          <p style={{ color: syncResult.startsWith('Error') ? 'var(--red, #c44)' : 'var(--green)', fontSize: 12, marginTop: 8 }}>
            {syncResult}
          </p>
        )}
      </div>
    </div>
  )
}
