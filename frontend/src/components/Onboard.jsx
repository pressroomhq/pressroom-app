import { useState, useEffect, useCallback } from 'react'

const API = '/api'

const STEPS = [
  { id: 'domain', label: '1. Domain', desc: 'Tell us your website' },
  { id: 'profile', label: '2. Profile', desc: 'Review your voice' },
  { id: 'connect', label: '3. Connect', desc: 'Link DreamFactory' },
  { id: 'classify', label: '4. Services', desc: 'Map your data' },
  { id: 'launch', label: '5. Launch', desc: 'First run' },
]

export default function Onboard({ onLog, onComplete }) {
  const [step, setStep] = useState('domain')
  const [domain, setDomain] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [existingKeys, setExistingKeys] = useState([])
  const [selectedKeyId, setSelectedKeyId] = useState('')
  const [newKeyLabel, setNewKeyLabel] = useState('')
  const [keyMode, setKeyMode] = useState('select') // 'select' or 'new'
  const [crawlData, setCrawlData] = useState(null)
  const [profile, setProfile] = useState(null)
  const [dfUrl, setDfUrl] = useState('')
  const [dfKey, setDfKey] = useState('')
  const [dfConnected, setDfConnected] = useState(false)
  const [classification, setClassification] = useState(null)
  const [dbServices, setDbServices] = useState([])
  const [socialServices, setSocialServices] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const currentStepIdx = STEPS.findIndex(s => s.id === step)

  // Load existing API keys on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/settings/api-keys`, { headers: { 'Content-Type': 'application/json' } })
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
  const crawl = async () => {
    const hasKey = keyMode === 'select' ? selectedKeyId : (apiKey.trim() && newKeyLabel.trim())
    if (!domain.trim() || !hasKey) return
    setLoading(true)
    setError(null)

    // Save or create API key so Claude calls work
    let usedKeyId = selectedKeyId
    if (keyMode === 'new' && apiKey.trim()) {
      onLog?.('Creating API key...', 'detail')
      try {
        const createRes = await fetch(`${API}/settings/api-keys`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label: newKeyLabel.trim() || 'Default', key_value: apiKey.trim() }),
        })
        const created = await createRes.json()
        usedKeyId = String(created.id)
        setSelectedKeyId(usedKeyId)
        setExistingKeys(prev => [created, ...prev])
        setKeyMode('select')
      } catch (e) {
        // Fallback: save as legacy setting
        onLog?.('Saving API key as legacy setting...', 'detail')
        await fetch(`${API}/settings`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ settings: { anthropic_api_key: apiKey } }),
        })
      }
    }

    onLog?.(`CRAWL — scanning ${domain}...`, 'action')
    try {
      const res = await fetch(`${API}/onboard/crawl`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain }),
      })
      const data = await res.json()
      setCrawlData(data)
      const socialCount = Object.keys(data.social_profiles || {}).length
      const socialNote = socialCount ? ` + ${socialCount} social profiles` : ''
      onLog?.(`CRAWL COMPLETE — found ${data.pages_found?.length || 0} pages${socialNote}: ${data.pages_found?.join(', ')}`, 'success')
      if (socialCount) {
        onLog?.(`SOCIALS — ${Object.entries(data.social_profiles).map(([p,u]) => `${p}`).join(', ')}`, 'detail')
      }

      // Auto-synthesize profile
      onLog?.('PROFILE — Pressroom is building your intelligence profile...', 'action')
      const profRes = await fetch(`${API}/onboard/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ crawl_data: data }),
      })
      if (!profRes.ok) {
        let errMsg = `Profile API error: ${profRes.status}`
        try {
          const errData = await profRes.json()
          errMsg = errData.error || errMsg
        } catch { /* not JSON */ }
        throw new Error(errMsg)
      }
      const profData = await profRes.json()
      if (profData.profile && !profData.profile.error) {
        setProfile(profData.profile)
        onLog?.(`PROFILE READY — ${profData.profile.company_name || 'Company'} voice synthesized`, 'success')
        setStep('profile')
      } else {
        const errMsg = profData.profile?.error || 'Profile synthesis failed'
        setError(errMsg)
        onLog?.(`PROFILE FAILED — ${errMsg}`, 'error')
        if (profData.profile?.raw) {
          onLog?.(`RAW RESPONSE — ${profData.profile.raw.slice(0, 300)}`, 'detail')
        }
      }
    } catch (e) {
      setError(e.message)
      onLog?.(`CRAWL ERROR — ${e.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  // ─── STEP 2: Profile editing ───
  const editProfile = (key, val) => {
    setProfile(prev => ({ ...prev, [key]: val }))
  }

  const editProfileArray = (key, val) => {
    try {
      const arr = val.split(',').map(s => s.trim()).filter(Boolean)
      setProfile(prev => ({ ...prev, [key]: arr }))
    } catch {
      // ignore parse errors during typing
    }
  }

  // ─── STEP 3: CONNECT DF ───
  const connectDf = async () => {
    if (!dfUrl.trim() || !dfKey.trim()) return
    setLoading(true)
    setError(null)
    onLog?.(`CONNECT — testing DreamFactory at ${dfUrl}...`, 'action')
    try {
      // Save DF settings first
      await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings: { df_base_url: dfUrl, df_api_key: dfKey } }),
      })

      // Test connection
      const res = await fetch(`${API}/settings/status`)
      const status = await res.json()
      if (status.dreamfactory?.connected) {
        setDfConnected(true)
        onLog?.(`CONNECTED — DreamFactory at ${dfUrl}`, 'success')
        setStep('classify')

        // Auto-classify
        onLog?.('CLASSIFY — introspecting services and schemas...', 'action')
        const classRes = await fetch(`${API}/onboard/df-classify`, { method: 'POST' })
        const classData = await classRes.json()
        if (classData.available) {
          setClassification(classData.classification)
          setDbServices(classData.db_services || [])
          setSocialServices(classData.social_services || [])
          const svcCount = (classData.db_services?.length || 0) + (classData.social_services?.length || 0)
          onLog?.(`CLASSIFIED — ${svcCount} services mapped`, 'success')
        } else {
          onLog?.(`CLASSIFY ISSUE — ${classData.error || 'no services found'}`, 'warn')
        }
      } else {
        setError('Could not connect to DreamFactory. Check URL and API key.')
        onLog?.('CONNECT FAILED — check URL and API key', 'error')
      }
    } catch (e) {
      setError(e.message)
      onLog?.(`CONNECT ERROR — ${e.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  const skipDf = () => {
    onLog?.('DF skipped — running standalone', 'detail')
    setStep('launch')
  }

  // ─── STEP 5: APPLY & LAUNCH ───
  const applyAndLaunch = async () => {
    setLoading(true)
    setError(null)
    onLog?.('APPLY — saving your profile and service map...', 'action')
    try {
      const res = await fetch(`${API}/onboard/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          profile: { ...(profile || {}), domain: domain || '' },
          service_map: classification?.service_map || null,
          crawl_pages: crawlData?.pages || null,
        }),
      })
      const data = await res.json()

      // Assign the selected API key to this org
      if (selectedKeyId && data.org_id) {
        await fetch(`${API}/settings`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', 'X-Org-Id': String(data.org_id) },
          body: JSON.stringify({ settings: { anthropic_api_key_id: selectedKeyId } }),
        })
        const keyLabel = existingKeys.find(k => String(k.id) === selectedKeyId)?.label || selectedKeyId
        onLog?.(`API key "${keyLabel}" assigned to this company`, 'success')
      }

      onLog?.('PROFILE SAVED — Pressroom is configured', 'success')
      onLog?.('ONBOARDING COMPLETE — head to the desk to start generating', 'success')
      // Pass back the new org so App can switch to it
      const newOrg = data.org || { id: data.org_id, name: profile?.company_name || 'Company', domain: domain || '' }
      onComplete?.(newOrg)
    } catch (e) {
      setError(e.message)
      onLog?.(`APPLY ERROR — ${e.message}`, 'error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="settings-page">
      {/* PROGRESS BAR */}
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

      {error && (
        <div className="onboard-error">{error}</div>
      )}

      {/* STEP 1: DOMAIN */}
      {step === 'domain' && (
        <div className="onboard-panel">
          <h2 className="settings-title">Let's Get Started</h2>
          <p className="onboard-subtitle">
            Enter your Anthropic API key and website. We'll crawl your site and build a content profile with Claude.
          </p>

          <div className="onboard-profile" style={{ marginTop: 16 }}>
            {/* API Key selection */}
            <div className="setting-field">
              <label className="setting-label">Anthropic API Key</label>
              {existingKeys.length > 0 && (
                <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                  <button
                    className={`btn ${keyMode === 'select' ? 'btn-approve' : ''}`}
                    style={{ fontSize: 11, padding: '3px 10px' }}
                    onClick={() => setKeyMode('select')}
                  >
                    Use Existing
                  </button>
                  <button
                    className={`btn ${keyMode === 'new' ? 'btn-approve' : ''}`}
                    style={{ fontSize: 11, padding: '3px 10px' }}
                    onClick={() => setKeyMode('new')}
                  >
                    Add New
                  </button>
                </div>
              )}
              {keyMode === 'select' && existingKeys.length > 0 ? (
                <select
                  className="setting-input"
                  value={selectedKeyId}
                  onChange={e => setSelectedKeyId(e.target.value)}
                  style={{ maxWidth: 400 }}
                >
                  {existingKeys.map(k => (
                    <option key={k.id} value={String(k.id)}>
                      {k.label} ({k.key_preview})
                    </option>
                  ))}
                </select>
              ) : (
                <>
                  <input
                    className="setting-input"
                    style={{ maxWidth: 400, fontSize: 12, marginBottom: 6 }}
                    type="text"
                    value={newKeyLabel}
                    onChange={e => setNewKeyLabel(e.target.value)}
                    placeholder="Label (e.g. Client A, Production)"
                  />
                  <input
                    className="setting-input"
                    style={{ maxWidth: 400 }}
                    type="password"
                    value={apiKey}
                    onChange={e => setApiKey(e.target.value)}
                    placeholder="sk-ant-..."
                  />
                </>
              )}
            </div>

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
                  disabled={loading || !domain.trim() || (keyMode === 'select' ? !selectedKeyId : (!apiKey.trim() || !newKeyLabel.trim()))}
                >
                  {loading ? 'Scanning...' : 'Scan & Analyze'}
                </button>
              </div>
            </div>
          </div>
          <div style={{ marginTop: 16 }}>
            <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => {
              if (keyMode === 'new' && apiKey.trim()) {
                fetch(`${API}/settings`, {
                  method: 'PUT',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ settings: { anthropic_api_key: apiKey } }),
                })
              }
              setStep('profile')
            }}>
              Skip crawl — set up manually
            </button>
          </div>
        </div>
      )}

      {/* STEP 2: PROFILE REVIEW */}
      {step === 'profile' && (
        <div className="onboard-panel">
          <h2 className="settings-title">
            {profile?.company_name ? `${profile.company_name} Profile` : 'Company Profile'}
          </h2>
          <p className="onboard-subtitle">
            Review and edit the profile Claude synthesized. This drives your content voice.
          </p>

          {profile ? (
            <div className="onboard-profile">
              <ProfileField label="Company Name" value={profile.company_name || ''} onChange={v => editProfile('company_name', v)} />
              <ProfileField label="Industry" value={profile.industry || ''} onChange={v => editProfile('industry', v)} />
              <ProfileField label="Golden Anchor Statement" value={profile.golden_anchor || ''} onChange={v => editProfile('golden_anchor', v)} textarea placeholder="Your company's north star message — woven into all content" />
              <ProfileField label="Persona" value={profile.persona || ''} onChange={v => editProfile('persona', v)} textarea />
              <ProfileField label="Bio (one-liner)" value={profile.bio || ''} onChange={v => editProfile('bio', v)} />
              <ProfileField label="Target Audience" value={profile.audience || ''} onChange={v => editProfile('audience', v)} />
              <ProfileField label="Tone" value={profile.tone || ''} onChange={v => editProfile('tone', v)} />
              <ProfileField label="Always Do" value={profile.always || ''} onChange={v => editProfile('always', v)} />
              <ProfileField label="Never Say (comma-separated)" value={(profile.never_say || []).join(', ')} onChange={v => editProfileArray('never_say', v)} />
              <ProfileField label="Brand Keywords (comma-separated)" value={(profile.brand_keywords || []).join(', ')} onChange={v => editProfileArray('brand_keywords', v)} />
              <ProfileField label="Key Topics (comma-separated)" value={(profile.topics || []).join(', ')} onChange={v => editProfileArray('topics', v)} />
              <ProfileField label="Competitors (comma-separated)" value={(profile.competitors || []).join(', ')} onChange={v => editProfileArray('competitors', v)} />

              <div className="settings-section" style={{ marginTop: 20 }}>
                <div className="section-label">Channel Styles</div>
                <ProfileField label="LinkedIn" value={profile.linkedin_style || ''} onChange={v => editProfile('linkedin_style', v)} />
                <ProfileField label="X / Twitter" value={profile.x_style || ''} onChange={v => editProfile('x_style', v)} />
                <ProfileField label="Blog" value={profile.blog_style || ''} onChange={v => editProfile('blog_style', v)} />
              </div>

              {profile.social_profiles && Object.values(profile.social_profiles).some(v => v && v !== 'null') && (
                <div className="settings-section" style={{ marginTop: 20 }}>
                  <div className="section-label">Social Profiles</div>
                  {Object.entries(profile.social_profiles).map(([platform, url]) => (
                    url && url !== 'null' ? (
                      <ProfileField
                        key={platform}
                        label={platform.charAt(0).toUpperCase() + platform.slice(1)}
                        value={url}
                        onChange={v => setProfile(prev => ({
                          ...prev,
                          social_profiles: { ...prev.social_profiles, [platform]: v }
                        }))}
                      />
                    ) : null
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="onboard-profile">
              <ProfileField label="Company Name" value="" onChange={v => editProfile('company_name', v)} />
              <ProfileField label="Persona" value="" onChange={v => editProfile('persona', v)} textarea placeholder="Describe your company voice..." />
              <ProfileField label="Target Audience" value="" onChange={v => editProfile('audience', v)} />
              <ProfileField label="Tone" value="" onChange={v => editProfile('tone', v)} placeholder="e.g. Technical, direct, conversational" />
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button className="btn btn-approve" onClick={() => setStep('connect')}>
              Looks Good — Next
            </button>
            <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => setStep('domain')}>
              Back
            </button>
          </div>
        </div>
      )}

      {/* STEP 3: CONNECT DF */}
      {step === 'connect' && (
        <div className="onboard-panel">
          <h2 className="settings-title">Connect DreamFactory</h2>
          <p className="onboard-subtitle">
            DreamFactory gives Pressroom access to your databases, CRMs, social platforms — everything it needs to write informed content.
          </p>

          <div className="onboard-profile" style={{ marginTop: 16 }}>
            <ProfileField label="DreamFactory URL" value={dfUrl} onChange={setDfUrl} placeholder="https://your-df-instance.com" />
            <ProfileField label="API Key" value={dfKey} onChange={setDfKey} type="password" placeholder="Your DF API key" />
          </div>

          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button
              className={`btn btn-approve ${loading ? 'loading' : ''}`}
              onClick={connectDf}
              disabled={loading || !dfUrl.trim() || !dfKey.trim()}
            >
              {loading ? 'Connecting...' : 'Connect & Classify'}
            </button>
            <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={skipDf}>
              Skip — No DF
            </button>
            <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => setStep('profile')}>
              Back
            </button>
          </div>
        </div>
      )}

      {/* STEP 4: SERVICE CLASSIFICATION */}
      {step === 'classify' && (
        <div className="onboard-panel">
          <h2 className="settings-title">Service Map</h2>
          <p className="onboard-subtitle">
            Claude analyzed your DreamFactory services. Here's what it found.
          </p>

          {/* DB Services */}
          {dbServices.length > 0 && (
            <div className="settings-section">
              <div className="section-label">Databases</div>
              <div className="status-grid">
                {dbServices.map(svc => {
                  const svcMap = classification?.service_map?.[svc.name] || {}
                  return (
                    <div key={svc.name} className="onboard-service-card">
                      <div className="onboard-service-name">
                        <span className="dot dot-on" /> {svc.label || svc.name}
                      </div>
                      <div className="onboard-service-type">{svc.type}</div>
                      {svcMap.role && (
                        <div className="onboard-service-role">{svcMap.role.replace(/_/g, ' ')}</div>
                      )}
                      {svcMap.description && (
                        <div className="onboard-service-desc">{svcMap.description}</div>
                      )}
                      <div className="onboard-service-tables">
                        {svc.tables?.map(t => (
                          <span key={t.name} className="onboard-table-tag">{t.name}</span>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Social Services */}
          {socialServices.length > 0 && (
            <div className="settings-section">
              <div className="section-label">Publishing Channels</div>
              <div className="status-grid">
                {socialServices.map(svc => (
                  <div key={svc.name} className="status-item">
                    <span className={`dot ${svc.auth_status?.connected ? 'dot-on' : 'dot-warn'}`} />
                    <span>{svc.label || svc.name}</span>
                    <span className="status-detail">
                      {svc.auth_status?.connected ? 'Authenticated' : 'Needs OAuth'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Intelligence Sources */}
          {classification?.intelligence_sources?.length > 0 && (
            <div className="settings-section">
              <div className="section-label">Intelligence Sources</div>
              <p style={{ fontSize: 12, color: 'var(--text)', marginBottom: 8 }}>
                Pressroom will query these services for content intelligence:
              </p>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {classification.intelligence_sources.map(s => (
                  <span key={s} className="onboard-table-tag" style={{ borderColor: 'var(--green)', color: 'var(--green)' }}>{s}</span>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button className="btn btn-approve" onClick={() => setStep('launch')}>
              Confirm — Ready to Launch
            </button>
            <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => setStep('connect')}>
              Back
            </button>
          </div>
        </div>
      )}

      {/* STEP 5: LAUNCH */}
      {step === 'launch' && (
        <div className="onboard-panel" style={{ textAlign: 'center' }}>
          <h2 className="settings-title" style={{ fontSize: 28, marginBottom: 12 }}>
            Ready to Roll
          </h2>
          <p className="onboard-subtitle">
            {profile?.company_name
              ? `${profile.company_name}'s content engine is configured.`
              : 'Your content engine is configured.'}
          </p>
          <div style={{ margin: '24px 0', fontSize: 12, color: 'var(--text)' }}>
            {profile && <div>Voice: {profile.persona?.slice(0, 80)}...</div>}
            {dfConnected && <div style={{ color: 'var(--green)', marginTop: 4 }}>DreamFactory: Connected</div>}
            {classification && <div style={{ marginTop: 4 }}>{Object.keys(classification.service_map || {}).length} services mapped</div>}
          </div>

          <button
            className={`btn btn-approve ${loading ? 'loading' : ''}`}
            style={{ fontSize: 14, padding: '10px 28px' }}
            onClick={applyAndLaunch}
            disabled={loading}
          >
            {loading ? 'Setting up...' : 'Launch Pressroom'}
          </button>
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
