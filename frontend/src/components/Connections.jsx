import { useState, useEffect } from 'react'
import { orgHeaders } from '../api'

const API = '/api'

const CATEGORIES = [
  { value: 'database', label: 'Database' },
  { value: 'crm', label: 'CRM' },
  { value: 'analytics', label: 'Analytics' },
  { value: 'support', label: 'Support' },
  { value: 'custom', label: 'Custom' },
]

const CONNECTION_TYPES = [
  { value: 'mcp', label: 'MCP Server' },
  { value: 'rest_api', label: 'REST API' },
]

export default function Connections({ onLog, orgId, userId }) {
  const [oauthStatus, setOauthStatus] = useState({})
  const [dataSources, setDataSources] = useState([])
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    name: '', description: '', category: 'database',
    connection_type: 'mcp', base_url: '', api_key: '',
  })
  const [testing, setTesting] = useState(null)
  const [analyzingVoice, setAnalyzingVoice] = useState(false)

  // LinkedIn/Facebook app credential state (inline editing)
  const [liClientId, setLiClientId] = useState('')
  const [liClientSecret, setLiClientSecret] = useState('')
  const [liSaving, setLiSaving] = useState(false)
  const [fbAppId, setFbAppId] = useState('')
  const [fbAppSecret, setFbAppSecret] = useState('')
  const [fbSaving, setFbSaving] = useState(false)
  const [ghClientId, setGhClientId] = useState('')
  const [ghClientSecret, setGhClientSecret] = useState('')
  const [ghSaving, setGhSaving] = useState(false)

  // HubSpot connection state
  const [hubStatus, setHubStatus] = useState({})
  const [hubKey, setHubKey] = useState('')
  const [hubConnecting, setHubConnecting] = useState(false)

  // GSC state
  const [gscStatus, setGscStatus] = useState({})
  const [gscJsonInput, setGscJsonInput] = useState('')
  const [gscSaving, setGscSaving] = useState(false)

  // Blog publish state
  const [blogRepo, setBlogRepo] = useState('')
  const [blogPath, setBlogPath] = useState('src/content/blog')
  const [blogSaving, setBlogSaving] = useState(false)

  // Brand state
  const [brand, setBrand] = useState({ logo_url: '', primary_color: '', secondary_color: '', font_family: '', company_name: '', favicon_url: '' })
  const [brandScraping, setBrandScraping] = useState(false)
  const [brandSaving, setBrandSaving] = useState(false)
  const [brandScrapeUrl, setBrandScrapeUrl] = useState('')

  // Dev.to state
  const [devtoKey, setDevtoKey] = useState('')
  const [devtoSaving, setDevtoSaving] = useState(false)
  const [devtoConnected, setDevtoConnected] = useState(false)

  // Slack state
  const [slackUrl, setSlackUrl] = useState('')
  const [slackChannel, setSlackChannel] = useState('')
  const [slackNotify, setSlackNotify] = useState(false)
  const [slackConnected, setSlackConnected] = useState(false)
  const [slackTesting, setSlackTesting] = useState(false)
  const [slackSaving, setSlackSaving] = useState(false)

  // Publish actions state
  const [publishActions, setPublishActions] = useState({})
  const [publishActionsSaving, setPublishActionsSaving] = useState(false)

  // Load OAuth status + data sources + HubSpot + Slack
  useEffect(() => {
    // Clear all connection state immediately on org switch to prevent stale data flash
    setOauthStatus({})
    setHubStatus({})
    setHubKey('')
    setGscStatus({})
    setGscJsonInput('')
    setDataSources([])
    setBrand({ logo_url: '', primary_color: '', secondary_color: '', font_family: '', company_name: '', favicon_url: '' })
    setSlackUrl('')
    setSlackChannel('')
    setSlackNotify(false)
    setSlackConnected(false)
    setDevtoConnected(false)
    setDevtoKey('')
    setPublishActions({})

    if (!orgId) return
    fetch(`${API}/oauth/status`, { headers: orgHeaders(orgId) })
      .then(r => r.json()).then(setOauthStatus).catch(() => {})
    fetch(`${API}/hubspot/status`, { headers: orgHeaders(orgId) })
      .then(r => r.json()).then(setHubStatus).catch(() => setHubStatus({ connected: false }))
    fetch(`${API}/gsc/status`, { headers: orgHeaders(orgId) })
      .then(r => r.json()).then(setGscStatus).catch(() => setGscStatus({ connected: false }))
    loadDataSources()
    loadSlackSettings()
    loadBrand()
  }, [orgId])

  async function loadBrand() {
    if (!orgId) return
    try {
      const res = await fetch(`${API}/brand/${orgId}`, { headers: orgHeaders(orgId) })
      if (res.ok) {
        const data = await res.json()
        setBrand({
          logo_url: data.logo_url || '',
          primary_color: data.primary_color || '',
          secondary_color: data.secondary_color || '',
          font_family: data.font_family || '',
          company_name: data.company_name || '',
          favicon_url: data.favicon_url || '',
        })
      }
    } catch { /* ignore */ }
  }

  async function scrapeBrand() {
    setBrandScraping(true)
    try {
      const res = await fetch(`${API}/brand/scrape`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ url: brandScrapeUrl }),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`BRAND SCRAPE FAILED — ${data.error}`, 'error')
      } else {
        setBrand({
          logo_url: data.logo_url || '',
          primary_color: data.primary_color || '',
          secondary_color: data.secondary_color || '',
          font_family: data.font_family || '',
          company_name: data.company_name || '',
          favicon_url: data.favicon_url || '',
        })
        onLog?.(`BRAND — scraped ${data.company_name || brandScrapeUrl}`, 'success')
      }
    } catch (e) {
      onLog?.(`BRAND SCRAPE FAILED — ${e.message}`, 'error')
    } finally {
      setBrandScraping(false)
    }
  }

  async function saveBrand() {
    setBrandSaving(true)
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: { brand_data: JSON.stringify(brand) } }),
      })
      onLog?.('BRAND — saved', 'success')
    } catch (e) {
      onLog?.(`BRAND SAVE FAILED — ${e.message}`, 'error')
    } finally {
      setBrandSaving(false)
    }
  }

  async function loadSlackSettings() {
    try {
      const res = await fetch(`${API}/settings`, { headers: orgHeaders(orgId) })
      if (!res.ok) return
      const data = await res.json()
      const url = data.slack_webhook_url?.value || ''
      setSlackUrl(url)
      setSlackConnected(!!url)
      setSlackChannel(data.slack_channel_name?.value || '')
      setSlackNotify(data.slack_notify_on_generate?.value === 'true')
      setBlogRepo(data.blog_github_repo?.value || '')
      setBlogPath(data.blog_content_path?.value || 'src/content/blog')
      const devTok = data.devto_api_key?.value || ''
      setDevtoConnected(!!devTok)
      // Publish actions
      const rawActions = data.publish_actions?.value || '{}'
      try { setPublishActions(JSON.parse(rawActions)) } catch { setPublishActions({}) }
    } catch { /* ignore */ }
  }

  async function saveLinkedInCreds() {
    if (!liClientId.trim() || !liClientSecret.trim()) return
    setLiSaving(true)
    try {
      const res = await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: {
          linkedin_client_id: liClientId.trim(),
          linkedin_client_secret: liClientSecret.trim(),
        }}),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setLiClientId('')
      setLiClientSecret('')
      onLog?.('LinkedIn app credentials saved', 'success')
      // Immediately update local state so Connect button appears
      setOauthStatus(prev => ({
        ...prev,
        linkedin: { ...(prev.linkedin || {}), app_configured: true },
      }))
      // Also refresh from server for full status
      try {
        const sr = await fetch(`${API}/oauth/status`, { headers: orgHeaders(orgId) })
        if (sr.ok) setOauthStatus(await sr.json())
      } catch (_) {}
    } catch (e) {
      onLog?.(`LinkedIn creds save failed — ${e.message}`, 'error')
    } finally {
      setLiSaving(false)
    }
  }

  async function saveGithubOAuthCreds() {
    if (!ghClientId.trim() || !ghClientSecret.trim()) return
    setGhSaving(true)
    try {
      const res = await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: {
          github_oauth_client_id: ghClientId.trim(),
          github_oauth_client_secret: ghClientSecret.trim(),
        }}),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setGhClientId('')
      setGhClientSecret('')
      onLog?.('GitHub OAuth credentials saved', 'success')
      setOauthStatus(prev => ({
        ...prev,
        github: { ...(prev.github || {}), app_configured: true },
      }))
    } catch (e) {
      onLog?.(`GitHub creds save failed — ${e.message}`, 'error')
    } finally {
      setGhSaving(false)
    }
  }

  async function saveFacebookCreds() {
    if (!fbAppId.trim() || !fbAppSecret.trim()) return
    setFbSaving(true)
    try {
      const res = await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: {
          facebook_app_id: fbAppId.trim(),
          facebook_app_secret: fbAppSecret.trim(),
        }}),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setFbAppId('')
      setFbAppSecret('')
      onLog?.('Facebook app credentials saved', 'success')
      // Immediately update local state so Connect button appears
      setOauthStatus(prev => ({
        ...prev,
        facebook: { ...(prev.facebook || {}), app_configured: true },
      }))
      // Also refresh from server for full status
      try {
        const sr = await fetch(`${API}/oauth/status`, { headers: orgHeaders(orgId) })
        if (sr.ok) setOauthStatus(await sr.json())
      } catch (_) {}
    } catch (e) {
      onLog?.(`Facebook creds save failed — ${e.message}`, 'error')
    } finally {
      setFbSaving(false)
    }
  }

  async function saveSlack() {
    setSlackSaving(true)
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: {
          slack_webhook_url: slackUrl,
          slack_channel_name: slackChannel,
          slack_notify_on_generate: slackNotify ? 'true' : '',
        }}),
      })
      setSlackConnected(!!slackUrl.trim())
      onLog?.('SLACK — settings saved', 'success')
    } catch (e) {
      onLog?.(`SLACK SAVE FAILED — ${e.message}`, 'error')
    } finally {
      setSlackSaving(false)
    }
  }

  async function testSlack() {
    setSlackTesting(true)
    try {
      // Save first so the test endpoint can read the URL
      await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: { slack_webhook_url: slackUrl }}),
      })
      const res = await fetch(`${API}/slack/test`, {
        method: 'POST', headers: orgHeaders(orgId),
      })
      const data = await res.json()
      if (data.success) {
        setSlackConnected(true)
        onLog?.('SLACK — test message sent successfully', 'success')
      } else {
        onLog?.(`SLACK TEST FAILED — ${data.error || 'unknown error'}`, 'error')
      }
    } catch (e) {
      onLog?.(`SLACK TEST FAILED — ${e.message}`, 'error')
    } finally {
      setSlackTesting(false)
    }
  }

  async function disconnectSlack() {
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: {
          slack_webhook_url: '',
          slack_channel_name: '',
          slack_notify_on_generate: '',
        }}),
      })
      setSlackUrl('')
      setSlackChannel('')
      setSlackNotify(false)
      setSlackConnected(false)
      onLog?.('SLACK DISCONNECTED', 'warn')
    } catch (e) {
      onLog?.(`SLACK DISCONNECT FAILED — ${e.message}`, 'error')
    }
  }

  async function savePublishActions() {
    setPublishActionsSaving(true)
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: { publish_actions: JSON.stringify(publishActions) } }),
      })
      onLog?.('PUBLISH ACTIONS — saved', 'success')
    } catch (e) {
      onLog?.(`PUBLISH ACTIONS SAVE FAILED — ${e.message}`, 'error')
    } finally {
      setPublishActionsSaving(false)
    }
  }

  async function connectHubSpot() {
    if (!hubKey.trim()) return
    setHubConnecting(true)
    try {
      const res = await fetch(`${API}/hubspot/connect`, {
        method: 'POST', headers: orgHeaders(orgId),
        body: JSON.stringify({ api_key: hubKey }),
      })
      const data = await res.json()
      if (data.connected) {
        onLog?.('HUBSPOT CONNECTED', 'success')
        setHubStatus(data)
        setHubKey('')
      } else {
        onLog?.(`HUBSPOT CONNECT FAILED — ${data.error || 'unknown'}`, 'error')
      }
    } catch (e) {
      onLog?.(`HUBSPOT CONNECT FAILED — ${e.message}`, 'error')
    } finally {
      setHubConnecting(false)
    }
  }

  async function saveGscCredentials() {
    if (!gscJsonInput.trim()) return
    setGscSaving(true)
    try {
      const trimmed = gscJsonInput.trim()
      if (!trimmed.startsWith('{')) {
        onLog?.('GSC CREDENTIALS — expected JSON', 'error')
        setGscSaving(false)
        return
      }
      const parsed = JSON.parse(trimmed)

      if (parsed.type === 'service_account') {
        // Service account path — backend validates and mints a token immediately
        const res = await fetch(`${API}/gsc/service-account`, {
          method: 'POST',
          headers: orgHeaders(orgId),
          body: JSON.stringify({ service_account_json: trimmed }),
        })
        const data = await res.json()
        if (data.error) {
          onLog?.(`GSC SERVICE ACCOUNT FAILED — ${data.error}`, 'error')
          setGscSaving(false)
          return
        }
        onLog?.(`GSC SERVICE ACCOUNT SAVED — ${data.client_email} — ${data.properties} properties found`, 'success')
        setGscJsonInput('')
      } else {
        // OAuth client JSON path — save creds, then user clicks Connect GSC
        const inner = parsed.web || parsed.installed || parsed
        const clientId = inner.client_id || ''
        const clientSecret = inner.client_secret || ''
        if (!clientId || !clientSecret) {
          onLog?.('GSC CREDENTIALS — could not extract client_id / client_secret from JSON', 'error')
          setGscSaving(false)
          return
        }
        await fetch(`${API}/settings`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ settings: { google_client_id: clientId, google_client_secret: clientSecret } }),
        })
        onLog?.('GOOGLE OAUTH CREDENTIALS SAVED — click Connect GSC to authorize', 'success')
        setGscJsonInput('')
      }

      // Refresh status either way
      const statusRes = await fetch(`${API}/gsc/status`, { headers: orgHeaders(orgId) })
      setGscStatus(await statusRes.json())
    } catch (e) {
      onLog?.(`GSC CREDENTIALS FAILED — ${e.message}`, 'error')
    } finally {
      setGscSaving(false)
    }
  }

  async function disconnectGsc() {
    try {
      await fetch(`${API}/gsc/disconnect`, { method: 'DELETE', headers: orgHeaders(orgId) })
      onLog?.('GSC DISCONNECTED', 'warn')
      setGscStatus({ connected: false })
    } catch (e) {
      onLog?.(`GSC DISCONNECT FAILED — ${e.message}`, 'error')
    }
  }

  async function saveBlogSettings() {
    setBlogSaving(true)
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: {
          blog_github_repo: blogRepo,
          blog_content_path: blogPath || 'src/content/blog',
        }}),
      })
      onLog?.('BLOG — settings saved', 'success')
    } catch (e) {
      onLog?.(`BLOG SAVE FAILED — ${e.message}`, 'error')
    } finally {
      setBlogSaving(false)
    }
  }

  async function saveDevtoKey() {
    if (!devtoKey.trim()) return
    setDevtoSaving(true)
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: { devto_api_key: devtoKey.trim() } }),
      })
      setDevtoConnected(true)
      setDevtoKey('')
      onLog?.('DEV.TO — API key saved', 'success')
    } catch (e) {
      onLog?.(`DEV.TO SAVE FAILED — ${e.message}`, 'error')
    } finally {
      setDevtoSaving(false)
    }
  }

  async function disconnectDevto() {
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT', headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: { devto_api_key: '' } }),
      })
      setDevtoConnected(false)
      onLog?.('DEV.TO — disconnected', 'warn')
    } catch (e) {
      onLog?.(`DEV.TO DISCONNECT FAILED — ${e.message}`, 'error')
    }
  }

  async function disconnectHubSpot() {
    try {
      await fetch(`${API}/hubspot/disconnect`, { method: 'DELETE', headers: orgHeaders(orgId) })
      onLog?.('HUBSPOT DISCONNECTED', 'warn')
      setHubStatus({ connected: false })
    } catch (e) {
      onLog?.(`DISCONNECT FAILED — ${e.message}`, 'error')
    }
  }

  async function analyzeLinkedInVoice() {
    setAnalyzingVoice(true)
    try {
      const res = await fetch(`${API}/oauth/linkedin/analyze-voice`, {
        method: 'POST',
        headers: orgHeaders(orgId),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`LINKEDIN VOICE — ${data.error}`, 'error')
      } else {
        onLog?.(`LINKEDIN VOICE — analyzed ${data.posts_analyzed} posts, voice saved`, 'success')
      }
    } catch (e) {
      onLog?.(`LINKEDIN VOICE FAILED — ${e.message}`, 'error')
    } finally {
      setAnalyzingVoice(false)
    }
  }

  // Check for OAuth callback in URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const oauth = params.get('oauth')
    const provider = params.get('provider')
    if (oauth && provider) {
      if (oauth === 'success') {
        onLog?.(`${provider.toUpperCase()} CONNECTED`, 'success')
      } else {
        const reason = params.get('reason') || 'unknown error'
        onLog?.(`${provider.toUpperCase()} CONNECT FAILED — ${reason}`, 'error')
      }
      // Clean URL
      window.history.replaceState({}, '', window.location.pathname)
      // Refresh status
      fetch(`${API}/oauth/status`, { headers: orgHeaders(orgId) })
        .then(r => r.json()).then(setOauthStatus).catch(() => {})
      fetch(`${API}/gsc/status`, { headers: orgHeaders(orgId) })
        .then(r => r.json()).then(setGscStatus).catch(() => {})
    }
  }, [])

  function loadDataSources() {
    fetch(`${API}/datasources`, { headers: orgHeaders(orgId) })
      .then(r => r.json()).then(setDataSources).catch(() => {})
  }

  function resetForm() {
    setForm({ name: '', description: '', category: 'database', connection_type: 'mcp', base_url: '', api_key: '' })
    setShowAdd(false)
    setEditing(null)
  }

  async function saveDataSource() {
    if (!form.name.trim()) return
    const url = editing ? `${API}/datasources/${editing}` : `${API}/datasources`
    const method = editing ? 'PUT' : 'POST'
    try {
      const res = await fetch(url, {
        method, headers: orgHeaders(orgId),
        body: JSON.stringify(form),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`DATA SOURCE ERROR — ${data.error}`, 'error')
        return
      }
      onLog?.(`${editing ? 'UPDATED' : 'ADDED'} — ${form.name}`, 'success')
      resetForm()
      loadDataSources()
    } catch (e) {
      onLog?.(`SAVE FAILED — ${e.message}`, 'error')
    }
  }

  async function deleteDataSource(ds) {
    try {
      await fetch(`${API}/datasources/${ds.id}`, {
        method: 'DELETE', headers: orgHeaders(orgId),
      })
      onLog?.(`REMOVED — ${ds.name}`, 'warn')
      loadDataSources()
    } catch (e) {
      onLog?.(`DELETE FAILED — ${e.message}`, 'error')
    }
  }

  async function testConnection(ds) {
    setTesting(ds.id)
    try {
      const res = await fetch(`${API}/datasources/${ds.id}/test`, {
        method: 'POST', headers: orgHeaders(orgId),
      })
      const data = await res.json()
      if (data.connected) {
        onLog?.(`${ds.name} — CONNECTION OK`, 'success')
      } else {
        onLog?.(`${ds.name} — ${data.error || 'Connection failed'}`, 'error')
      }
    } catch (e) {
      onLog?.(`TEST FAILED — ${e.message}`, 'error')
    } finally {
      setTesting(null)
    }
  }

  function startEdit(ds) {
    setForm({
      name: ds.name,
      description: ds.description || '',
      category: ds.category || 'database',
      connection_type: ds.connection_type || 'mcp',
      base_url: ds.base_url || '',
      api_key: '',
    })
    setEditing(ds.id)
    setShowAdd(true)
  }

  const linkedin = oauthStatus.linkedin || {}
  const facebook = oauthStatus.facebook || {}
  const youtube = oauthStatus.youtube || {}

  return (
    <div className="connections-panel">
      <h2 className="section-title">CONNECTIONS</h2>

      {/* Social Accounts */}
      <div className="connections-section">
        <h3 className="subsection-title">Social Accounts</h3>
        <p className="section-desc">Connect social platforms to publish content directly.</p>

        <div className="connection-cards">
          {/* LinkedIn */}
          <div className={`connection-card ${linkedin.connected ? 'connected' : ''}`}>
            <div className="connection-card-header">
              <span className="connection-name">LinkedIn</span>
              <span className={`connection-status ${linkedin.connected ? 'active' : 'inactive'}`}>
                {linkedin.connected ? 'CONNECTED' : 'NOT CONNECTED'}
              </span>
            </div>
            {linkedin.connected && linkedin.profile_name && (
              <div className="connection-detail">{linkedin.profile_name}</div>
            )}
            {linkedin.connected && linkedin.days_remaining != null && (
              <div className={`connection-detail ${linkedin.days_remaining < 7 ? 'warn' : 'dim'}`}>
                {linkedin.days_remaining > 0
                  ? `Token expires in ${linkedin.days_remaining} days`
                  : 'Token expired — reconnect'}
              </div>
            )}
            {!linkedin.app_configured ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                <input
                  className="setting-input"
                  value={liClientId}
                  onChange={e => setLiClientId(e.target.value)}
                  placeholder="LinkedIn Client ID"
                  style={{ fontSize: 11, padding: '4px 8px' }}
                />
                <input
                  className="setting-input"
                  type="password"
                  value={liClientSecret}
                  onChange={e => setLiClientSecret(e.target.value)}
                  placeholder="LinkedIn Client Secret"
                  style={{ fontSize: 11, padding: '4px 8px' }}
                />
                <button
                  className="btn btn-sm"
                  onClick={saveLinkedInCreds}
                  disabled={liSaving || !liClientId.trim() || !liClientSecret.trim()}
                >
                  {liSaving ? 'Saving...' : 'Save & Connect'}
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button
                  className="btn btn-sm"
                  onClick={() => window.open(`${API}/oauth/linkedin?org_id=${orgId || 0}&user_id=${userId || ''}`, '_blank')}
                >
                  {linkedin.connected ? (linkedin.days_remaining === 0 ? 'Reconnect (Expired)' : 'Reconnect') : 'Connect LinkedIn'}
                </button>
                {linkedin.connected && (
                  <button
                    className="btn btn-sm"
                    onClick={analyzeLinkedInVoice}
                    disabled={analyzingVoice}
                  >
                    {analyzingVoice ? 'Analyzing...' : 'Analyze Voice'}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Facebook */}
          <div className={`connection-card ${facebook.connected ? 'connected' : ''}`}>
            <div className="connection-card-header">
              <span className="connection-name">Facebook</span>
              <span className={`connection-status ${facebook.connected ? 'active' : 'inactive'}`}>
                {facebook.connected ? 'CONNECTED' : 'NOT CONNECTED'}
              </span>
            </div>
            {facebook.connected && facebook.page_name && (
              <div className="connection-detail">{facebook.page_name}</div>
            )}
            {!facebook.app_configured ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 4 }}>
                <input
                  className="setting-input"
                  value={fbAppId}
                  onChange={e => setFbAppId(e.target.value)}
                  placeholder="Facebook App ID"
                  style={{ fontSize: 11, padding: '4px 8px' }}
                />
                <input
                  className="setting-input"
                  type="password"
                  value={fbAppSecret}
                  onChange={e => setFbAppSecret(e.target.value)}
                  placeholder="Facebook App Secret"
                  style={{ fontSize: 11, padding: '4px 8px' }}
                />
                <button
                  className="btn btn-sm"
                  onClick={saveFacebookCreds}
                  disabled={fbSaving || !fbAppId.trim() || !fbAppSecret.trim()}
                >
                  {fbSaving ? 'Saving...' : 'Save & Connect'}
                </button>
              </div>
            ) : (
              <button
                className="btn btn-sm"
                onClick={() => window.open(`${API}/oauth/facebook?org_id=${orgId || 0}`, '_blank')}
              >
                {facebook.connected ? 'Reconnect' : 'Connect Facebook'}
              </button>
            )}
          </div>

          {/* GitHub OAuth */}
          {(() => {
            const gh = oauthStatus?.github || {}
            return (
              <div className={`connection-card ${gh.connected ? 'connected' : ''}`}>
                <div className="connection-card-header">
                  <span className="connection-name">GitHub OAuth</span>
                  <span className={`connection-status ${gh.connected ? 'active' : 'inactive'}`}>
                    {gh.connected ? 'CONNECTED' : 'NOT CONNECTED'}
                  </span>
                </div>
                {gh.connected && gh.login && (
                  <div className="connection-detail">@{gh.login}</div>
                )}
                <div className="connection-detail dim" style={{ fontSize: 10, marginTop: 2 }}>
                  Lets team members publish gists. Create an OAuth App at github.com/settings/developers.
                </div>
                {!gh.app_configured ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                    <input
                      className="setting-input"
                      value={ghClientId}
                      onChange={e => setGhClientId(e.target.value)}
                      placeholder="GitHub OAuth Client ID"
                      style={{ fontSize: 11, padding: '4px 8px' }}
                    />
                    <input
                      className="setting-input"
                      type="password"
                      value={ghClientSecret}
                      onChange={e => setGhClientSecret(e.target.value)}
                      placeholder="GitHub OAuth Client Secret"
                      style={{ fontSize: 11, padding: '4px 8px' }}
                    />
                    <button
                      className="btn btn-sm"
                      onClick={saveGithubOAuthCreds}
                      disabled={ghSaving || !ghClientId.trim() || !ghClientSecret.trim()}
                    >
                      {ghSaving ? 'Saving...' : 'Save Credentials'}
                    </button>
                  </div>
                ) : (
                  <button
                    className="btn btn-sm"
                    onClick={() => window.open(`${API}/oauth/github?org_id=${orgId || 0}`, '_blank')}
                    style={{ marginTop: 8 }}
                  >
                    {gh.connected ? 'Reconnect Org GitHub' : 'Connect GitHub'}
                  </button>
                )}
              </div>
            )
          })()}

          {/* YouTube */}
          <div className={`connection-card ${youtube.connected ? 'connected' : ''}`}>
            <div className="connection-card-header">
              <span className="connection-name">YouTube</span>
              <span className={`connection-status ${youtube.connected ? 'active' : 'inactive'}`}>
                {youtube.connected ? 'CONNECTED' : 'NOT CONNECTED'}
              </span>
            </div>
            {youtube.connected && youtube.channel_title && (
              <div className="connection-detail">{youtube.channel_title}</div>
            )}
            {youtube.connected && youtube.channel_id && (
              <div className="connection-detail dim">
                <a href={`https://youtube.com/channel/${youtube.channel_id}`} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--text-dim)' }}>
                  {youtube.channel_id}
                </a>
              </div>
            )}
            <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
              <button
                className="btn btn-sm"
                onClick={() => window.open(`${API}/oauth/youtube?org_id=${orgId || 0}`, '_blank')}
              >
                {youtube.connected ? 'Reconnect' : 'Connect YouTube'}
              </button>
              {youtube.connected && (
                <button className="btn btn-sm btn-danger" onClick={async () => {
                  await fetch(`${API}/settings`, {
                    method: 'PUT', headers: orgHeaders(orgId),
                    body: JSON.stringify({ settings: {
                      youtube_refresh_token: '',
                      youtube_channel_title: '',
                      youtube_channel_id: '',
                    }}),
                  })
                  setOauthStatus(s => ({ ...s, youtube: { connected: false } }))
                  onLog?.('YOUTUBE — disconnected', 'warn')
                }}>Disconnect</button>
              )}
            </div>
            {!youtube.connected && (
              <div className="connection-detail dim" style={{ marginTop: 8 }}>
                Requires a Google Cloud project with YouTube Data API v3 enabled and OAuth 2.0 credentials (Web App type). Set <code>YOUTUBE_CLIENT_ID</code> + <code>YOUTUBE_CLIENT_SECRET</code> env vars, then connect.
              </div>
            )}
          </div>

          {/* Blog / GitHub */}
          <div className={`connection-card ${blogRepo.trim() ? 'connected' : ''}`}>
            <div className="connection-card-header">
              <span className="connection-name">Blog (GitHub)</span>
              <span className={`connection-status ${blogRepo.trim() ? 'active' : 'inactive'}`}>
                {blogRepo.trim() ? 'CONFIGURED' : 'NOT CONFIGURED'}
              </span>
            </div>
            {blogRepo.trim() && (
              <div className="connection-detail">{blogRepo}</div>
            )}
            <div style={{ marginTop: 8 }}>
              <div className="form-row">
                <label>GitHub Repo <span style={{ fontWeight: 400, color: 'var(--text-dim)', fontSize: 10 }}>— uses GitHub token from Scout settings</span></label>
                <input
                  type="text"
                  value={blogRepo}
                  onChange={e => setBlogRepo(e.target.value)}
                  placeholder="owner/repo-name"
                />
              </div>
              <div className="form-row">
                <label>Content Path</label>
                <input
                  type="text"
                  value={blogPath}
                  onChange={e => setBlogPath(e.target.value)}
                  placeholder="src/content/blog"
                />
              </div>
            </div>
            <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
              <button className="btn btn-sm" onClick={saveBlogSettings} disabled={blogSaving || !blogRepo.trim()}>
                {blogSaving ? 'Saving...' : 'Save'}
              </button>
              {blogRepo.trim() && (
                <button className="btn btn-sm btn-danger" onClick={async () => {
                  setBlogRepo('')
                  setBlogPath('src/content/blog')
                  await fetch(`${API}/settings`, {
                    method: 'PUT', headers: orgHeaders(orgId),
                    body: JSON.stringify({ settings: { blog_github_repo: '', blog_content_path: '' }}),
                  })
                  onLog?.('BLOG — disconnected', 'warn')
                }}>
                  Disconnect
                </button>
              )}
            </div>
          </div>

          {/* HubSpot */}
          <div className={`connection-card ${hubStatus.connected ? 'connected' : ''}`}>
            <div className="connection-card-header">
              <span className="connection-name">HubSpot</span>
              <span className={`connection-status ${hubStatus.connected ? 'active' : 'inactive'}`}>
                {hubStatus.connected ? 'CONNECTED' : 'NOT CONNECTED'}
              </span>
            </div>
            {hubStatus.connected && hubStatus.hub_domain && (
              <div className="connection-detail">{hubStatus.hub_domain}</div>
            )}
            {hubStatus.connected && hubStatus.portal_id && (
              <div className="connection-detail dim">Portal ID: {hubStatus.portal_id}</div>
            )}
            {!hubStatus.connected && (
              <div className="form-row" style={{ marginTop: 8 }}>
                <input
                  type="password"
                  value={hubKey}
                  onChange={e => setHubKey(e.target.value)}
                  placeholder="pat-na1-xxxxxxxx"
                  onKeyDown={e => { if (e.key === 'Enter') connectHubSpot() }}
                />
              </div>
            )}
            <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
              {!hubStatus.connected && (
                <button className="btn btn-sm" onClick={connectHubSpot} disabled={hubConnecting || !hubKey.trim()}>
                  {hubConnecting ? 'Connecting...' : 'Connect'}
                </button>
              )}
              {hubStatus.connected && (
                <button className="btn btn-sm btn-danger" onClick={disconnectHubSpot}>Disconnect</button>
              )}
            </div>
          </div>

          {/* Dev.to */}
          <div className={`connection-card ${devtoConnected ? 'connected' : ''}`}>
            <div className="connection-card-header">
              <span className="connection-name">Dev.to</span>
              <span className={`connection-status ${devtoConnected ? 'active' : 'inactive'}`}>
                {devtoConnected ? 'CONNECTED' : 'NOT CONNECTED'}
              </span>
            </div>
            {devtoConnected && (
              <div className="connection-detail dim">Publishes as draft — you review and publish on Dev.to</div>
            )}
            {!devtoConnected && (
              <div style={{ marginTop: 8 }}>
                <div className="form-row">
                  <input
                    type="password"
                    value={devtoKey}
                    onChange={e => setDevtoKey(e.target.value)}
                    placeholder="Dev.to API Key"
                    onKeyDown={e => { if (e.key === 'Enter') saveDevtoKey() }}
                  />
                </div>
                <div className="connection-detail dim" style={{ marginTop: 4 }}>
                  Get your key at dev.to → Settings → Extensions → DEV Community API Keys
                </div>
              </div>
            )}
            <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
              {!devtoConnected && (
                <button className="btn btn-sm" onClick={saveDevtoKey} disabled={devtoSaving || !devtoKey.trim()}>
                  {devtoSaving ? 'Saving...' : 'Connect'}
                </button>
              )}
              {devtoConnected && (
                <button className="btn btn-sm btn-danger" onClick={disconnectDevto}>Disconnect</button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Brand Studio */}
      <div className="connections-section">
        <h3 className="subsection-title">Brand</h3>
        <p className="section-desc">Your visual identity used in video generation, reports, and outreach. Scrape your site or fill in manually.</p>
        <div className="connection-cards">
          <div className={`connection-card ${brand.primary_color || brand.logo_url ? 'connected' : ''}`} style={{ gridColumn: '1 / -1' }}>
            <div className="connection-card-header">
              <span className="connection-name">Brand Assets</span>
              <span className={`connection-status ${brand.primary_color || brand.logo_url ? 'active' : 'inactive'}`}>
                {brand.primary_color || brand.logo_url ? 'CONFIGURED' : 'NOT SET'}
              </span>
            </div>

            {/* Scrape input */}
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <input
                type="text"
                value={brandScrapeUrl}
                onChange={e => setBrandScrapeUrl(e.target.value)}
                placeholder="https://yourcompany.com — scrape to auto-fill"
                style={{ flex: 1 }}
                onKeyDown={e => { if (e.key === 'Enter' && brandScrapeUrl.trim()) scrapeBrand() }}
              />
              <button className="btn btn-sm" onClick={scrapeBrand} disabled={brandScraping || !brandScrapeUrl.trim()}>
                {brandScraping ? 'Scraping...' : 'Scrape'}
              </button>
            </div>

            {/* Preview row */}
            {(brand.logo_url || brand.primary_color) && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, margin: '14px 0 8px', padding: '10px 12px', background: 'var(--bg-card)', borderRadius: 6 }}>
                {brand.logo_url && (
                  <img src={brand.logo_url} alt="logo" style={{ height: 40, maxWidth: 100, objectFit: 'contain', borderRadius: 4 }} onError={e => e.target.style.display='none'} />
                )}
                <div style={{ display: 'flex', gap: 8 }}>
                  {brand.primary_color && (
                    <div title={brand.primary_color} style={{ width: 32, height: 32, borderRadius: 6, background: brand.primary_color, border: '1px solid var(--border)', cursor: 'pointer' }} />
                  )}
                  {brand.secondary_color && (
                    <div title={brand.secondary_color} style={{ width: 32, height: 32, borderRadius: 6, background: brand.secondary_color, border: '1px solid var(--border)', cursor: 'pointer' }} />
                  )}
                </div>
                {brand.company_name && (
                  <span style={{ color: 'var(--text-dim)', fontSize: 13 }}>{brand.company_name}</span>
                )}
                {brand.font_family && (
                  <span style={{ color: 'var(--text-dim)', fontSize: 11, fontFamily: brand.font_family }}>{brand.font_family}</span>
                )}
              </div>
            )}

            {/* Manual edit fields */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}>
              <div className="form-row">
                <label>Logo URL</label>
                <input type="text" value={brand.logo_url} onChange={e => setBrand({ ...brand, logo_url: e.target.value })} placeholder="https://..." />
              </div>
              <div className="form-row">
                <label>Favicon URL</label>
                <input type="text" value={brand.favicon_url} onChange={e => setBrand({ ...brand, favicon_url: e.target.value })} placeholder="https://..." />
              </div>
              <div className="form-row">
                <label>Primary Color</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input type="color" value={brand.primary_color || '#ffffff'} onChange={e => setBrand({ ...brand, primary_color: e.target.value })} style={{ width: 40, padding: 2, cursor: 'pointer' }} />
                  <input type="text" value={brand.primary_color} onChange={e => setBrand({ ...brand, primary_color: e.target.value })} placeholder="#ffb000" style={{ flex: 1 }} />
                </div>
              </div>
              <div className="form-row">
                <label>Secondary Color</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input type="color" value={brand.secondary_color || '#ffffff'} onChange={e => setBrand({ ...brand, secondary_color: e.target.value })} style={{ width: 40, padding: 2, cursor: 'pointer' }} />
                  <input type="text" value={brand.secondary_color} onChange={e => setBrand({ ...brand, secondary_color: e.target.value })} placeholder="#ffffff" style={{ flex: 1 }} />
                </div>
              </div>
              <div className="form-row">
                <label>Font Family</label>
                <input type="text" value={brand.font_family} onChange={e => setBrand({ ...brand, font_family: e.target.value })} placeholder="IBM Plex Mono" />
              </div>
              <div className="form-row">
                <label>Company Name</label>
                <input type="text" value={brand.company_name} onChange={e => setBrand({ ...brand, company_name: e.target.value })} placeholder="Pressroom HQ" />
              </div>
            </div>

            <div style={{ marginTop: 12 }}>
              <button className="btn btn-sm btn-approve" onClick={saveBrand} disabled={brandSaving}>
                {brandSaving ? 'Saving...' : 'Save Brand'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* SEO & Analytics */}
      <div className="connections-section">
        <h3 className="subsection-title">SEO & Analytics</h3>
        <p className="section-desc">Connect analytics platforms to power SEO audits and search intelligence.</p>

        <div className="connection-cards">
          {/* Google Search Console */}
          <div className={`connection-card ${gscStatus.connected ? 'connected' : ''}`}>
            <div className="connection-card-header">
              <span className="connection-name">Google Search Console</span>
              <span className={`connection-status ${gscStatus.connected ? 'active' : 'inactive'}`}>
                {gscStatus.connected ? 'CONNECTED' : 'NOT CONNECTED'}
              </span>
            </div>
            {gscStatus.connected && gscStatus.property && (
              <div className="connection-detail">{gscStatus.property}</div>
            )}
            {gscStatus.connected && gscStatus.auth_mode === 'service_account' && gscStatus.service_account_email && (
              <div className="connection-detail dim">SA: {gscStatus.service_account_email}</div>
            )}
            {gscStatus.connected && !gscStatus.token_healthy && (
              <div className="connection-detail warn">Token expired — reconnect</div>
            )}
            {!gscStatus.app_configured && (
              <div style={{ marginTop: 8 }}>
                <div className="form-row">
                  <label>Google Credentials JSON <span style={{ fontWeight: 400, color: 'var(--text-dim)', fontSize: 10 }}>— service account key OR OAuth 2.0 client JSON</span></label>
                  <textarea
                    value={gscJsonInput}
                    onChange={e => setGscJsonInput(e.target.value)}
                    placeholder='Paste service account key JSON or client_secret_*.json (OAuth 2.0 Client ID)'
                    rows={3}
                    style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}
                  />
                </div>
                <button className="btn btn-sm" onClick={saveGscCredentials}
                        disabled={gscSaving || !gscJsonInput.trim()}>
                  {gscSaving ? 'Saving...' : 'Save Credentials'}
                </button>
              </div>
            )}
            {gscStatus.app_configured && (
              <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                <button
                  className="btn btn-sm"
                  onClick={() => window.location.href = `${API}/gsc/auth?org_id=${orgId || 0}`}
                >
                  {gscStatus.connected ? 'Reconnect' : 'Connect GSC'}
                </button>
                {gscStatus.connected && (
                  <button className="btn btn-sm btn-danger" onClick={disconnectGsc}>Disconnect</button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Messaging */}
      <div className="connections-section">
        <h3 className="subsection-title">Messaging</h3>
        <p className="section-desc">Send content notifications to your team's channels.</p>

        <div className="connection-cards">
          {/* Slack */}
          <div className={`connection-card ${slackConnected ? 'connected' : ''}`}>
            <div className="connection-card-header">
              <span className="connection-name">Slack</span>
              <span className={`connection-status ${slackConnected ? 'active' : 'inactive'}`}>
                {slackConnected ? 'CONNECTED' : 'NOT CONNECTED'}
              </span>
            </div>
            {slackConnected && slackChannel && (
              <div className="connection-detail">{slackChannel}</div>
            )}

            <div style={{ marginTop: 8 }}>
              <div className="form-row">
                <label>Webhook URL</label>
                <input
                  type="password"
                  value={slackUrl}
                  onChange={e => setSlackUrl(e.target.value)}
                  placeholder="https://hooks.slack.com/services/..."
                  onKeyDown={e => { if (e.key === 'Enter') saveSlack() }}
                />
              </div>
              <div className="form-row">
                <label>Channel</label>
                <input
                  type="text"
                  value={slackChannel}
                  onChange={e => setSlackChannel(e.target.value)}
                  placeholder="#content-review"
                />
              </div>
              <div className="form-row" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="checkbox"
                  id="slack-notify-toggle"
                  checked={slackNotify}
                  onChange={e => setSlackNotify(e.target.checked)}
                  style={{ width: 'auto', margin: 0 }}
                />
                <label htmlFor="slack-notify-toggle" style={{ margin: 0, color: 'var(--text-dim)', fontSize: 12, cursor: 'pointer' }}>
                  Auto-notify when content is generated
                </label>
              </div>
            </div>

            <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
              <button className="btn btn-sm" onClick={saveSlack} disabled={slackSaving || !slackUrl.trim()}>
                {slackSaving ? 'Saving...' : 'Save'}
              </button>
              <button className="btn btn-sm" onClick={testSlack} disabled={slackTesting || !slackUrl.trim()}>
                {slackTesting ? 'Testing...' : 'Test Webhook'}
              </button>
              {slackConnected && (
                <button className="btn btn-sm btn-danger" onClick={disconnectSlack}>Disconnect</button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Publish Actions */}
      <div className="connections-section">
        <h3 className="subsection-title">Publish Actions</h3>
        <p className="section-desc">Control what happens to each channel when you hit Publish.</p>

        <div className="publish-actions-grid">
          {[
            { key: 'linkedin', label: 'LinkedIn', hasAuto: true },
            { key: 'facebook', label: 'Facebook', hasAuto: true },
            { key: 'blog', label: 'Blog', hasAuto: true },
            { key: 'devto', label: 'Dev.to', hasAuto: true },
            { key: 'release_email', label: 'Release Email', hasAuto: false },
            { key: 'newsletter', label: 'Newsletter', hasAuto: false },
            { key: 'yt_script', label: 'YouTube Script', hasAuto: false },
          ].map(ch => {
            const action = publishActions[ch.key] || 'auto'
            const isAutoNoConnection = action === 'auto' && ch.hasAuto && (
              (ch.key === 'linkedin' && !linkedin.connected) ||
              (ch.key === 'facebook' && !facebook.connected) ||
              (ch.key === 'blog' && !blogRepo.trim()) ||
              (ch.key === 'devto' && !devtoConnected)
            )
            const isSlackNoWebhook = action === 'slack' && !slackConnected
            return (
              <div key={ch.key} className="publish-action-row">
                <span className="publish-action-channel">{ch.label}</span>
                <select
                  className="publish-action-select"
                  value={action}
                  onChange={e => setPublishActions(prev => ({ ...prev, [ch.key]: e.target.value }))}
                >
                  {ch.hasAuto && <option value="auto">Auto-post</option>}
                  <option value="slack">Send to Slack</option>
                  <option value="manual">Manual (copy/paste)</option>
                  <option value="disabled">Disabled</option>
                </select>
                {isAutoNoConnection && (
                  <span className="publish-action-warn">Not connected</span>
                )}
                {isSlackNoWebhook && (
                  <span className="publish-action-warn">No Slack webhook</span>
                )}
              </div>
            )
          })}
        </div>

        <div style={{ marginTop: 12 }}>
          <button className="btn btn-sm btn-approve" onClick={savePublishActions} disabled={publishActionsSaving}>
            {publishActionsSaving ? 'Saving...' : 'Save Publish Actions'}
          </button>
        </div>
      </div>

      {/* Data Sources */}
      <div className="connections-section">
        <h3 className="subsection-title">Data Sources</h3>
        <p className="section-desc">
          Connect MCP servers or APIs to feed intelligence into the content engine.
          Point to a DreamFactory MCP, CRM, analytics platform, etc.
        </p>

        {dataSources.length > 0 && (
          <div className="datasource-list">
            {dataSources.map(ds => (
              <div key={ds.id} className="datasource-item">
                <div className="datasource-header">
                  <div>
                    <span className="datasource-name">{ds.name}</span>
                    <span className="datasource-badge">{ds.category}</span>
                    <span className="datasource-badge type">{ds.connection_type}</span>
                  </div>
                  <div className="datasource-actions">
                    <button className="btn btn-xs" onClick={() => testConnection(ds)}
                            disabled={testing === ds.id}>
                      {testing === ds.id ? 'Testing...' : 'Test'}
                    </button>
                    <button className="btn btn-xs" onClick={() => startEdit(ds)}>Edit</button>
                    <button className="btn btn-xs btn-danger" onClick={() => deleteDataSource(ds)}>Remove</button>
                  </div>
                </div>
                {ds.description && <div className="datasource-desc">{ds.description}</div>}
                {ds.base_url && <div className="datasource-url">{ds.base_url}</div>}
              </div>
            ))}
          </div>
        )}

        {!showAdd ? (
          <button className="btn btn-add" onClick={() => { resetForm(); setShowAdd(true) }}>
            + Add Data Source
          </button>
        ) : (
          <div className="datasource-form">
            <h4>{editing ? 'Edit Data Source' : 'New Data Source'}</h4>
            <div className="form-row">
              <label>Name</label>
              <input type="text" value={form.name} placeholder="e.g. Intercom Data"
                     onChange={e => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="form-row">
              <label>Description</label>
              <input type="text" value={form.description}
                     placeholder="What data does this source contain?"
                     onChange={e => setForm({ ...form, description: e.target.value })} />
            </div>
            <div className="form-row-pair">
              <div className="form-row">
                <label>Category</label>
                <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>
                  {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </div>
              <div className="form-row">
                <label>Connection Type</label>
                <select value={form.connection_type}
                        onChange={e => setForm({ ...form, connection_type: e.target.value })}>
                  {CONNECTION_TYPES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </div>
            </div>
            <div className="form-row">
              <label>{form.connection_type === 'mcp' ? 'MCP Server URL' : 'Base URL'}</label>
              <input type="text" value={form.base_url}
                     placeholder={form.connection_type === 'mcp' ? 'http://df.example.com/api/v2/mcp' : 'https://api.example.com'}
                     onChange={e => setForm({ ...form, base_url: e.target.value })} />
            </div>
            <div className="form-row">
              <label>API Key</label>
              <input type="password" value={form.api_key} placeholder={editing ? '(unchanged if empty)' : 'API key or token'}
                     onChange={e => setForm({ ...form, api_key: e.target.value })} />
            </div>
            <div className="form-buttons">
              <button className="btn btn-approve" onClick={saveDataSource}>
                {editing ? 'Update' : 'Add Source'}
              </button>
              <button className="btn" onClick={resetForm}>Cancel</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
