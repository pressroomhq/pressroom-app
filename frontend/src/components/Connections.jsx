import { useState, useEffect } from 'react'

const API = '/api'

function orgHeaders(orgId) {
  const h = { 'Content-Type': 'application/json' }
  if (orgId) h['X-Org-Id'] = String(orgId)
  return h
}

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

export default function Connections({ onLog, orgId }) {
  const [oauthStatus, setOauthStatus] = useState({})
  const [dataSources, setDataSources] = useState([])
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({
    name: '', description: '', category: 'database',
    connection_type: 'mcp', base_url: '', api_key: '',
  })
  const [testing, setTesting] = useState(null)

  // HubSpot connection state
  const [hubStatus, setHubStatus] = useState({})
  const [hubKey, setHubKey] = useState('')
  const [hubConnecting, setHubConnecting] = useState(false)

  // GSC state
  const [gscStatus, setGscStatus] = useState({})
  const [gscJsonInput, setGscJsonInput] = useState('')
  const [gscSaving, setGscSaving] = useState(false)

  // Slack state
  const [slackUrl, setSlackUrl] = useState('')
  const [slackChannel, setSlackChannel] = useState('')
  const [slackNotify, setSlackNotify] = useState(false)
  const [slackConnected, setSlackConnected] = useState(false)
  const [slackTesting, setSlackTesting] = useState(false)
  const [slackSaving, setSlackSaving] = useState(false)

  // Load OAuth status + data sources + HubSpot + Slack
  useEffect(() => {
    if (!orgId) return
    fetch(`${API}/oauth/status`, { headers: orgHeaders(orgId) })
      .then(r => r.json()).then(setOauthStatus).catch(() => {})
    fetch(`${API}/hubspot/status`, { headers: orgHeaders(orgId) })
      .then(r => r.json()).then(setHubStatus).catch(() => setHubStatus({ connected: false }))
    fetch(`${API}/gsc/status`, { headers: orgHeaders(orgId) })
      .then(r => r.json()).then(setGscStatus).catch(() => setGscStatus({ connected: false }))
    loadDataSources()
    loadSlackSettings()
  }, [orgId])

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
    } catch { /* ignore */ }
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

  async function disconnectHubSpot() {
    try {
      await fetch(`${API}/hubspot/disconnect`, { method: 'DELETE', headers: orgHeaders(orgId) })
      onLog?.('HUBSPOT DISCONNECTED', 'warn')
      setHubStatus({ connected: false })
    } catch (e) {
      onLog?.(`DISCONNECT FAILED — ${e.message}`, 'error')
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
              <div className="connection-detail dim">Set LinkedIn Client ID/Secret in Config first</div>
            ) : (
              <button
                className="btn btn-sm"
                onClick={() => window.location.href = `${API}/oauth/linkedin?org_id=${orgId || 0}`}
              >
                {linkedin.connected ? (linkedin.days_remaining === 0 ? 'Reconnect (Expired)' : 'Reconnect') : 'Connect LinkedIn'}
              </button>
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
              <div className="connection-detail dim">Set Facebook App ID/Secret in Config first</div>
            ) : (
              <button
                className="btn btn-sm"
                onClick={() => window.location.href = `${API}/oauth/facebook?org_id=${orgId || 0}`}
              >
                {facebook.connected ? 'Reconnect' : 'Connect Facebook'}
              </button>
            )}
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
