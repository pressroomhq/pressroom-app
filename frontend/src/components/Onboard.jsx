import { useState, useEffect } from 'react'
import { orgHeaders, orgFetch } from '../api'

const API = '/api'

const STEPS = [
  { id: 'domain',  label: '1. Domain',  desc: 'Tell us your website' },
  { id: 'profile', label: '2. Profile', desc: 'Review your voice' },
  { id: 'launch',  label: '3. Launch',  desc: 'Go live' },
]

export default function Onboard({ onLog, onComplete }) {
  const [step, setStep] = useState('domain')
  const [domain, setDomain] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [existingKeys, setExistingKeys] = useState([])
  const [selectedKeyId, setSelectedKeyId] = useState('')
  const [newKeyLabel, setNewKeyLabel] = useState('')
  const [keyMode, setKeyMode] = useState('select')
  const [crawlData, setCrawlData] = useState(null)
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [auditResults, setAuditResults] = useState(null)
  const [auditLoading, setAuditLoading] = useState(false)
  const [launchedOrg, setLaunchedOrg] = useState(null)
  const [envKeyAvailable, setEnvKeyAvailable] = useState(true)

  const currentStepIdx = STEPS.findIndex(s => s.id === step)

  useEffect(() => {
    (async () => {
      // Check if backend already has an API key (env var or stored)
      try {
        const statusRes = await fetch(`${API}/settings/api-keys/status`, { headers: orgHeaders() })
        const statusData = await statusRes.json()
        if (statusData.available) {
          setEnvKeyAvailable(true)
        }
      } catch { /* ignore */ }

      try {
        const res = await fetch(`${API}/settings/api-keys`, { headers: orgHeaders() })
        const data = await res.json()
        if (Array.isArray(data) && data.length > 0) {
          setExistingKeys(data)
          setSelectedKeyId(String(data[0].id))
          setKeyMode('select')
        } else {
          setKeyMode('new')
        }
      } catch {
        setKeyMode('new')
      }
    })()
  }, [])

  // ─── STEP 1: CRAWL ───
  const isAddingNewKey = selectedKeyId === '__new__' || (existingKeys.length === 0 && !envKeyAvailable)
  const hasValidKey = envKeyAvailable || (isAddingNewKey ? (apiKey.trim() && newKeyLabel.trim()) : (selectedKeyId && selectedKeyId !== '__new__'))

  const crawl = async () => {
    if (!domain.trim() || !hasValidKey) return
    setLoading(true)
    setError(null)

    let usedKeyId = selectedKeyId
    if (!envKeyAvailable && isAddingNewKey && apiKey.trim()) {
      onLog?.('Creating API key...', 'detail')
      try {
        const createRes = await fetch(`${API}/settings/api-keys`, {
          method: 'POST',
          headers: orgHeaders(),
          body: JSON.stringify({ label: newKeyLabel.trim() || 'Default', key_value: apiKey.trim() }),
        })
        const created = await createRes.json()
        usedKeyId = String(created.id)
        setSelectedKeyId(usedKeyId)
        setExistingKeys(prev => [created, ...prev])
        setKeyMode('select')
      } catch {
        await fetch(`${API}/settings`, {
          method: 'PUT',
          headers: orgHeaders(),
          body: JSON.stringify({ settings: { anthropic_api_key: apiKey } }),
        })
      }
    }

    onLog?.(`CRAWL — scanning ${domain}...`, 'action')
    try {
      const res = await fetch(`${API}/onboard/crawl`, {
        method: 'POST',
        headers: orgHeaders(),
        body: JSON.stringify({ domain }),
      })
      const data = await res.json()
      setCrawlData(data)
      const socialCount = Object.keys(data.social_profiles || {}).length
      const socialNote = socialCount ? ` + ${socialCount} social profiles` : ''
      onLog?.(`CRAWL COMPLETE — found ${data.pages_found?.length || 0} pages${socialNote}: ${data.pages_found?.join(', ')}`, 'success')
      if (socialCount) {
        onLog?.(`SOCIALS — ${Object.entries(data.social_profiles).map(([p]) => p).join(', ')}`, 'detail')
      }

      onLog?.('PROFILE — Pressroom is building your intelligence profile...', 'action')
      const profRes = await fetch(`${API}/onboard/profile`, {
        method: 'POST',
        headers: orgHeaders(),
        body: JSON.stringify({ crawl_data: data }),
      })
      if (!profRes.ok) {
        let errMsg = `Profile API error: ${profRes.status}`
        try { const e = await profRes.json(); errMsg = e.error || errMsg } catch { /* not JSON */ }
        throw new Error(errMsg)
      }
      const profData = await profRes.json()
      if (profData.profile && !profData.profile.error) {
        setProfile(profData.profile)
        if (profData.profile._parse_warning) {
          onLog?.(`PROFILE PARTIAL — JSON parse was incomplete. Review fields before launching.`, 'error')
        } else {
          onLog?.(`PROFILE READY — ${profData.profile.company_name || 'Company'} voice synthesized`, 'success')
        }
        setStep('profile')
      } else {
        const errMsg = profData.profile?.error || 'Profile synthesis failed'
        setError(errMsg)
        onLog?.(`PROFILE FAILED — ${errMsg}`, 'error')
        if (profData.profile?.raw) onLog?.(`RAW — ${profData.profile.raw.slice(0, 300)}`, 'detail')
      }
    } catch (e) {
      setError(e.message)
      onLog?.(`CRAWL ERROR — ${e.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  const editProfile = (key, val) => setProfile(prev => ({ ...prev, [key]: val }))

  const editProfileArray = (key, val) => {
    const arr = val.split(',').map(s => s.trim()).filter(Boolean)
    setProfile(prev => ({ ...prev, [key]: arr }))
  }

  // ─── STEP 3: APPLY & LAUNCH ───
  const applyAndLaunch = async () => {
    setLoading(true)
    setError(null)
    onLog?.('APPLY — saving your profile...', 'action')
    try {
      const res = await fetch(`${API}/onboard/apply`, {
        method: 'POST',
        headers: orgHeaders(),
        body: JSON.stringify({
          profile: { ...(profile || {}), domain: domain || '' },
          service_map: null,
          crawl_pages: crawlData?.pages || null,
        }),
      })
      const text = await res.text()
      let data
      try { data = JSON.parse(text) } catch { throw new Error(`Server returned non-JSON: ${text.slice(0, 200)}`) }
      if (!res.ok) {
        const msg = data.detail || data.error || `Apply failed (${res.status})`
        setError(msg)
        onLog?.(`APPLY ERROR — ${msg}`, 'error')
        setLoading(false)
        return
      }

      // Existing org — admin was linked in, skip to launch
      if (data.existing) {
        onLog?.(`LOADED — ${data.message}`, 'success')
        const newOrg = { id: data.org_id, name: data.org_name || profile?.company_name || 'Company', domain: domain || '' }
        setLaunchedOrg(newOrg)
        setStep('launch')
        setLoading(false)
        return
      }

      if (!envKeyAvailable && selectedKeyId && data.org_id) {
        await fetch(`${API}/settings`, {
          method: 'PUT',
          headers: orgHeaders(data.org_id),
          body: JSON.stringify({ settings: { anthropic_api_key_id: selectedKeyId } }),
        })
        const keyLabel = existingKeys.find(k => String(k.id) === selectedKeyId)?.label || selectedKeyId
        onLog?.(`API key "${keyLabel}" assigned`, 'success')
      }

      onLog?.('PROFILE SAVED — running first audit...', 'success')
      const newOrg = data.org || { id: data.org_id, name: profile?.company_name || 'Company', domain: domain || '' }
      setLaunchedOrg(newOrg)

      // Fire audit
      setAuditLoading(true)
      try {
        const auditRes = await fetch(`${API}/company/audit`, {
          headers: orgHeaders(data.org_id),
        })
        const auditData = await auditRes.json()
        setAuditResults(auditData)
        const count = auditData.findings?.length || 0
        onLog?.(`AUDIT — ${count} action items found`, count > 0 ? 'warn' : 'success')
      } catch {
        onLog?.('AUDIT — skipped', 'detail')
      } finally {
        setAuditLoading(false)
      }

      setStep('launch')
    } catch (e) {
      setError(e.message)
      onLog?.(`APPLY ERROR — ${e.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  const priorityColor = (p) => {
    if (p === 'high') return 'var(--red, #e55)'
    if (p === 'medium') return 'var(--yellow, #e9a)'
    return 'var(--text-dim)'
  }

  return (
    <div className="settings-page">
      {/* PROGRESS */}
      <div className="onboard-progress">
        {STEPS.map((s, i) => (
          <div
            key={s.id}
            className={`onboard-step ${step === s.id ? 'active' : ''} ${i < currentStepIdx ? 'done' : ''}`}
            onClick={() => i <= currentStepIdx && setStep(s.id)}
          >
            <span className="onboard-step-num">{s.label}</span>
            <span className="onboard-step-desc">{s.desc}</span>
          </div>
        ))}
      </div>

      {error && <div className="onboard-error">{error}</div>}

      {/* STEP 1: DOMAIN */}
      {step === 'domain' && (
        <div className="onboard-panel">
          <h2 className="settings-title">Let's Get Started</h2>
          <p className="onboard-subtitle">
            Enter your API key and website. Pressroom will crawl your site and build a content intelligence profile.
          </p>

          <div className="onboard-profile" style={{ marginTop: 16 }}>
            {!envKeyAvailable && (
            <div className="setting-field">
              <label className="setting-label">Anthropic API Key</label>
              {existingKeys.length > 0 ? (
                <>
                  <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
                    <select className="setting-input" value={selectedKeyId} onChange={e => { setSelectedKeyId(e.target.value); setKeyMode('select') }} style={{ maxWidth: 320, flex: 1 }}>
                      {existingKeys.map(k => <option key={k.id} value={String(k.id)}>{k.label} ({k.key_preview})</option>)}
                      <option value="__new__">+ Add new key...</option>
                    </select>
                  </div>
                  {selectedKeyId === '__new__' && (
                    <>
                      <input className="setting-input" style={{ maxWidth: 400, fontSize: 12, marginBottom: 6 }} type="text" value={newKeyLabel} onChange={e => setNewKeyLabel(e.target.value)} placeholder="Label (e.g. Production)" />
                      <input className="setting-input" style={{ maxWidth: 400 }} type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-ant-..." />
                    </>
                  )}
                </>
              ) : (
                <>
                  <input className="setting-input" style={{ maxWidth: 400, fontSize: 12, marginBottom: 6 }} type="text" value={newKeyLabel} onChange={e => setNewKeyLabel(e.target.value)} placeholder="Label (e.g. Production)" />
                  <input className="setting-input" style={{ maxWidth: 400 }} type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-ant-..." />
                </>
              )}
            </div>
            )}

            <div className="setting-field">
              <label className="setting-label">Website</label>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <input
                  className="setting-input"
                  style={{ maxWidth: 400, fontSize: 14 }}
                  type="text"
                  value={domain}
                  onChange={e => setDomain(e.target.value)}
                  placeholder="yourcompany.com"
                  onKeyDown={e => e.key === 'Enter' && crawl()}
                />
                <button
                  className={`btn btn-approve ${loading ? 'loading' : ''}`}
                  onClick={crawl}
                  disabled={loading || !domain.trim() || !hasValidKey}
                >
                  {loading ? 'Scanning...' : 'Scan & Analyze'}
                </button>
              </div>
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => setStep('profile')}>
              Skip crawl — set up manually
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: PROFILE */}
      {step === 'profile' && (
        <div className="onboard-panel">
          <h2 className="settings-title">
            {profile?.company_name ? `${profile.company_name} — Voice Profile` : 'Voice Profile'}
          </h2>
          <p className="onboard-subtitle">
            Review and edit what Pressroom synthesized. This drives every piece of content.
          </p>

          <div className="onboard-profile">
            {/* Golden Anchor — hero placement */}
            <div className="golden-anchor-block">
              <div className="golden-anchor-label">
                <span className="golden-anchor-icon">⚓</span> Golden Anchor
              </div>
              <p className="golden-anchor-hint">
                Your north star message — the one idea woven into everything you publish.
              </p>
              <textarea
                className="setting-input voice-textarea golden-anchor-input"
                value={profile?.golden_anchor || ''}
                onChange={e => editProfile('golden_anchor', e.target.value)}
                rows={3}
                placeholder="e.g. DreamFactory makes any database instantly accessible via REST API — no code required."
                spellCheck={false}
              />
            </div>

            <div className="settings-section" style={{ marginTop: 24 }}>
              <div className="section-label">Company</div>
              <ProfileField label="Company Name" value={profile?.company_name || ''} onChange={v => editProfile('company_name', v)} />
              <ProfileField label="Industry" value={profile?.industry || ''} onChange={v => editProfile('industry', v)} />
              <ProfileField label="Bio (one-liner)" value={profile?.bio || ''} onChange={v => editProfile('bio', v)} />
            </div>

            <div className="settings-section" style={{ marginTop: 20 }}>
              <div className="section-label">Voice</div>
              <ProfileField label="Persona" value={profile?.persona || ''} onChange={v => editProfile('persona', v)} textarea />
              <ProfileField label="Target Audience" value={profile?.audience || ''} onChange={v => editProfile('audience', v)} />
              <ProfileField label="Tone" value={profile?.tone || ''} onChange={v => editProfile('tone', v)} />
              <ProfileField label="Always Do" value={profile?.always || ''} onChange={v => editProfile('always', v)} />
              <ProfileField label="Never Say" value={(profile?.never_say || []).join(', ')} onChange={v => editProfileArray('never_say', v)} placeholder="comma-separated" />
              <ProfileField label="Brand Keywords" value={(profile?.brand_keywords || []).join(', ')} onChange={v => editProfileArray('brand_keywords', v)} placeholder="comma-separated" />
            </div>

            <div className="settings-section" style={{ marginTop: 20 }}>
              <div className="section-label">Intelligence</div>
              <ProfileField label="Key Topics" value={(profile?.topics || []).join(', ')} onChange={v => editProfileArray('topics', v)} placeholder="comma-separated" />
              <ProfileField label="Competitors" value={(profile?.competitors || []).join(', ')} onChange={v => editProfileArray('competitors', v)} placeholder="comma-separated" />
            </div>

            <div className="settings-section" style={{ marginTop: 20 }}>
              <div className="section-label">Channel Styles</div>
              <ProfileField label="LinkedIn" value={profile?.linkedin_style || ''} onChange={v => editProfile('linkedin_style', v)} />
              <ProfileField label="X / Twitter" value={profile?.x_style || ''} onChange={v => editProfile('x_style', v)} />
              <ProfileField label="Blog" value={profile?.blog_style || ''} onChange={v => editProfile('blog_style', v)} />
            </div>

            {profile?.social_profiles && Object.values(profile.social_profiles).some(v => v && v !== 'null') && (
              <div className="settings-section" style={{ marginTop: 20 }}>
                <div className="section-label">Social Profiles</div>
                {Object.entries(profile.social_profiles).map(([platform, url]) =>
                  url && url !== 'null' ? (
                    <ProfileField
                      key={platform}
                      label={platform.charAt(0).toUpperCase() + platform.slice(1)}
                      value={url}
                      onChange={v => setProfile(prev => ({ ...prev, social_profiles: { ...prev.social_profiles, [platform]: v } }))}
                    />
                  ) : null
                )}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
            <button
              className={`btn btn-approve ${loading ? 'loading' : ''}`}
              onClick={applyAndLaunch}
              disabled={loading}
            >
              {loading ? 'Launching...' : 'Launch Pressroom'}
            </button>
            <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => setStep('domain')}>
              Back
            </button>
          </div>
        </div>
      )}

      {/* STEP 3: LAUNCH + AUDIT */}
      {step === 'launch' && (
        <div className="onboard-panel">
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <h2 className="settings-title" style={{ fontSize: 26, marginBottom: 8 }}>
              {launchedOrg?.name || profile?.company_name || 'Company'} is live
            </h2>
            <p className="onboard-subtitle" style={{ marginBottom: 0 }}>
              Intelligence profile saved. Running your first audit...
            </p>
          </div>

          {/* Audit results */}
          {auditLoading && (
            <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: 13, marginBottom: 24 }}>
              <span className="loading-dot" /> Analyzing your digital presence...
            </div>
          )}

          {auditResults && !auditLoading && (
            <div className="audit-results-block">
              <div className="audit-results-header">
                <span>First Audit — {auditResults.findings?.length || 0} action items</span>
                <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>These are the highest-impact gaps to address first</span>
              </div>

              {auditResults.findings?.length > 0 ? (
                <div className="audit-findings-list">
                  {auditResults.findings.map((f, i) => (
                    <div key={i} className="audit-finding-row">
                      <div className="audit-finding-priority" style={{ color: priorityColor(f.priority) }}>
                        {f.priority?.toUpperCase() || '—'}
                      </div>
                      <div className="audit-finding-body">
                        <div className="audit-finding-title">{f.title || f.finding}</div>
                        {f.recommendation && (
                          <div className="audit-finding-rec">{f.recommendation}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ padding: '16px', color: 'var(--text-dim)', fontSize: 13 }}>
                  No critical gaps found — you're in good shape.
                </div>
              )}
            </div>
          )}

          <div style={{ textAlign: 'center', marginTop: 32 }}>
            <button
              className="btn btn-approve"
              style={{ fontSize: 14, padding: '10px 28px' }}
              onClick={() => onComplete?.(launchedOrg)}
            >
              Go to Dashboard →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}


function ProfileField({ label, value, onChange, textarea, type = 'text', placeholder }) {
  return (
    <div className="setting-field">
      <label className="setting-label">{label}</label>
      {textarea ? (
        <textarea
          className="setting-input voice-textarea"
          value={value}
          onChange={e => onChange(e.target.value)}
          rows={3}
          placeholder={placeholder || ''}
          spellCheck={false}
        />
      ) : (
        <input
          className="setting-input"
          type={type}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''}
          spellCheck={false}
        />
      )}
    </div>
  )
}
