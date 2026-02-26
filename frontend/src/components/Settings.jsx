import { useState, useEffect, useCallback } from 'react'
import { orgHeaders, cachedFetch } from '../api'
import { supabase } from '../supabaseClient'

const API = '/api'

// Account settings don't send X-Org-Id — they're shared across all companies
function accountHeaders() {
  return { 'Content-Type': 'application/json' }
}

function StatusDot({ connected, configured }) {
  if (!configured) return <span className="dot dot-off" title="Not configured" />
  if (connected) return <span className="dot dot-on" title="Connected" />
  return <span className="dot dot-warn" title="Configured but not connected" />
}

export default function Settings({ onLog, orgId }) {
  const [settings, setSettings] = useState({})
  const [status, setStatus] = useState({})
  const [dfServices, setDfServices] = useState(null)
  const [saving, setSaving] = useState(false)
  const [edits, setEdits] = useState({})
  const [checking, setChecking] = useState(false)

  const load = useCallback(async () => {
    try {
      const [setRes, statRes] = await Promise.all([
        cachedFetch(`${API}/settings`, orgId),
        cachedFetch(`${API}/settings/status`, orgId),
      ])
      setSettings(await setRes.json())
      setStatus(await statRes.json())
    } catch (e) {
      onLog?.('Failed to load settings', 'error')
    }
  }, [onLog, orgId])

  const loadDfServices = useCallback(async () => {
    try {
      const res = await cachedFetch(`${API}/settings/df-services`, orgId)
      setDfServices(await res.json())
    } catch (e) {
      setDfServices({ available: false })
    }
  }, [orgId])

  useEffect(() => { load(); loadDfServices() }, [load, loadDfServices])
  useEffect(() => { setEdits({}) }, [orgId])

  const edit = (key, val) => setEdits(prev => ({ ...prev, [key]: val }))

  const save = async () => {
    if (Object.keys(edits).length === 0) return
    setSaving(true)
    onLog?.('Saving account settings...', 'action')
    try {
      // Account keys go without org header, ensuring they save to org_id=NULL
      await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: accountHeaders(),
        body: JSON.stringify({ settings: edits }),
      })
      setEdits({})
      onLog?.(`Account settings saved: ${Object.keys(edits).join(', ')}`, 'success')
      await load()
      await loadDfServices()
    } catch (e) {
      onLog?.(`Save failed: ${e.message}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  const checkConnections = async () => {
    setChecking(true)
    onLog?.('Checking connections...', 'action')
    try {
      const [statRes, dfRes] = await Promise.all([
        cachedFetch(`${API}/settings/status`, orgId, {}, 0),
        cachedFetch(`${API}/settings/df-services`, orgId, {}, 0),
      ])
      const data = await statRes.json()
      const dfData = await dfRes.json()
      setStatus(data)
      setDfServices(dfData)

      if (data.github?.connected) onLog?.(`GitHub: connected as ${data.github.user}`, 'success')
      else if (data.github?.configured) onLog?.(`GitHub: ${data.github.error || 'not connected'}`, 'error')
      if (data.dreamfactory?.connected) onLog?.(`DreamFactory: connected at ${data.dreamfactory.url}`, 'success')
      else if (data.dreamfactory?.configured) onLog?.(`DreamFactory: ${data.dreamfactory.error || 'not connected'}`, 'error')
      if (data.anthropic?.configured) onLog?.(`Anthropic: configured (${data.anthropic.model})`, 'success')

      if (dfData.available) {
        onLog?.(`DF Services: ${dfData.services?.length || 0} total, ${dfData.social?.length || 0} social, ${dfData.databases?.length || 0} databases`, 'success')
        dfData.social?.forEach(s => {
          const auth = s.auth_status?.connected ? 'authenticated' : 'not authenticated'
          onLog?.(`  [${s.type?.toUpperCase()}] ${s.name} — ${auth}`, 'detail')
        })
      }
    } catch (e) {
      onLog?.(`Connection check failed: ${e.message}`, 'error')
    } finally {
      setChecking(false)
    }
  }

  const getVal = (key) => edits[key] ?? settings[key]?.value ?? ''
  const isDirty = Object.keys(edits).length > 0

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2 className="settings-title">Account Settings</h2>
        <div className="settings-subtitle">Shared across all companies</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className={`btn btn-run ${checking ? 'loading' : ''}`} onClick={checkConnections} disabled={checking}>
            {checking ? 'Checking...' : 'Test Connections'}
          </button>
          <button className={`btn btn-approve ${saving ? 'loading' : ''}`} onClick={save} disabled={!isDirty || saving}>
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>

      {/* ACCOUNT */}
      <ChangePassword />

      {/* CONNECTION STATUS */}
      <div className="settings-section">
        <div className="section-label">Connection Status</div>
        <div className="status-grid">
          <div className="status-item">
            <StatusDot configured={status.anthropic?.configured} connected={status.anthropic?.configured} />
            <span>Anthropic</span>
            <span className="status-detail">{status.anthropic?.configured ? status.anthropic.model : 'No API key'}</span>
          </div>
          <div className="status-item">
            <StatusDot configured={status.github?.configured} connected={status.github?.connected} />
            <span>GitHub</span>
            <span className="status-detail">{status.github?.connected ? `@${status.github.user}` : status.github?.configured ? 'Not connected' : 'No token'}</span>
          </div>
          <div className="status-item">
            <StatusDot configured={status.dreamfactory?.configured} connected={status.dreamfactory?.connected} />
            <span>DreamFactory</span>
            <span className="status-detail">{status.dreamfactory?.connected ? status.dreamfactory.url : status.dreamfactory?.configured ? 'Not connected' : 'No API key'}</span>
          </div>
        </div>
      </div>

      {/* DF SERVICES — discovered from DreamFactory */}
      {dfServices?.available && (
        <div className="settings-section">
          <div className="section-label">DreamFactory Services</div>
          <div className="status-grid">
            {dfServices.databases?.map(db => (
              <div key={db.name} className="status-item">
                <span className="dot dot-on" />
                <span>{db.label || db.name}</span>
                <span className="status-detail">{db.type} database</span>
              </div>
            ))}
            {dfServices.social?.map(svc => (
              <div key={svc.name} className="status-item">
                <StatusDot configured={true} connected={svc.auth_status?.connected} />
                <span>{svc.label || svc.name}</span>
                <span className="status-detail">
                  {svc.auth_status?.connected ? 'Authenticated' : 'Needs OAuth'}
                </span>
              </div>
            ))}
            {(!dfServices.databases?.length && !dfServices.social?.length) && (
              <div className="status-item">
                <span className="dot dot-warn" />
                <span>No services found</span>
                <span className="status-detail">Add database + social services in DF admin</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* API KEYS */}
      <div className="settings-section">
        <div className="section-label">API Keys</div>
        <ApiKeyManager onLog={onLog} />
        <SettingField label="GitHub Token" k="github_token" type="password" getVal={getVal} edit={edit} settings={settings} />
      </div>

      {/* DREAMFACTORY */}
      <div className="settings-section">
        <div className="section-label">DreamFactory</div>
        <SettingField label="DF Base URL" k="df_base_url" getVal={getVal} edit={edit} settings={settings} placeholder="http://localhost:8080" />
        <SettingField label="DF API Key" k="df_api_key" type="password" getVal={getVal} edit={edit} settings={settings} />
      </div>

      {/* ENGINE */}
      <div className="settings-section">
        <div className="section-label">Engine</div>
        <SettingField label="Claude Model (content)" k="claude_model" getVal={getVal} edit={edit} settings={settings} placeholder="claude-sonnet-4-6" />
        <SettingField label="Claude Model (fast/analysis)" k="claude_model_fast" getVal={getVal} edit={edit} settings={settings} placeholder="claude-haiku-4-5-20251001" />
        <SettingField label="GitHub Webhook Secret" k="github_webhook_secret" type="password" getVal={getVal} edit={edit} settings={settings} />
      </div>

      {/* OAUTH APP CREDENTIALS */}
      <div className="settings-section">
        <div className="section-label">OAuth App Credentials</div>
        <SettingField label="LinkedIn Client ID" k="linkedin_client_id" getVal={getVal} edit={edit} settings={settings} />
        <SettingField label="LinkedIn Client Secret" k="linkedin_client_secret" type="password" getVal={getVal} edit={edit} settings={settings} />
        <SettingField label="Facebook App ID" k="facebook_app_id" getVal={getVal} edit={edit} settings={settings} />
        <SettingField label="Facebook App Secret" k="facebook_app_secret" type="password" getVal={getVal} edit={edit} settings={settings} />
      </div>
    </div>
  )
}

function ChangePassword() {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSuccess(false)
    if (password !== confirm) { setError('Passwords do not match.'); return }
    if (password.length < 8) { setError('Must be at least 8 characters.'); return }
    setLoading(true)
    const { error: err } = await supabase.auth.updateUser({ password })
    if (err) setError(err.message)
    else { setSuccess(true); setPassword(''); setConfirm('') }
    setLoading(false)
  }

  return (
    <div className="settings-section">
      <div className="section-label">Account</div>
      <form onSubmit={handleSubmit} style={{ maxWidth: 320 }}>
        <div style={{ marginBottom: 8 }}>
          <input
            className="setting-input"
            type="password"
            placeholder="New password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            style={{ width: '100%', fontSize: 13 }}
          />
        </div>
        <div style={{ marginBottom: 10 }}>
          <input
            className="setting-input"
            type="password"
            placeholder="Confirm password"
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
            style={{ width: '100%', fontSize: 13 }}
          />
        </div>
        {error && <div style={{ fontSize: 11, color: 'var(--error)', marginBottom: 8 }}>{error}</div>}
        {success && <div style={{ fontSize: 11, color: 'var(--green)', marginBottom: 8 }}>Password updated.</div>}
        <button className="btn btn-approve" type="submit" disabled={loading || !password || !confirm} style={{ fontSize: 12 }}>
          {loading ? 'Saving...' : 'Change Password'}
        </button>
      </form>
    </div>
  )
}

function ApiKeyManager({ onLog }) {
  const [keys, setKeys] = useState([])
  const [adding, setAdding] = useState(false)
  const [newLabel, setNewLabel] = useState('')
  const [newKey, setNewKey] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editLabel, setEditLabel] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/settings/api-keys`, { headers: accountHeaders() })
      setKeys(await res.json())
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { load() }, [load])

  const addKey = async () => {
    if (!newLabel.trim() || !newKey.trim()) return
    try {
      await fetch(`${API}/settings/api-keys`, {
        method: 'POST',
        headers: accountHeaders(),
        body: JSON.stringify({ label: newLabel.trim(), key_value: newKey.trim() }),
      })
      onLog?.(`API key "${newLabel}" added`, 'success')
      setNewLabel('')
      setNewKey('')
      setAdding(false)
      await load()
    } catch (e) {
      onLog?.(`Failed to add key: ${e.message}`, 'error')
    }
  }

  const saveLabel = async (id) => {
    if (!editLabel.trim()) return
    try {
      await fetch(`${API}/settings/api-keys/${id}`, {
        method: 'PUT',
        headers: accountHeaders(),
        body: JSON.stringify({ label: editLabel.trim() }),
      })
      setEditingId(null)
      await load()
    } catch { /* ignore */ }
  }

  const deleteKey = async (id, label) => {
    if (!confirm(`Delete API key "${label}"? Companies using this key will fall back to another.`)) return
    try {
      await fetch(`${API}/settings/api-keys/${id}`, { method: 'DELETE', headers: accountHeaders() })
      onLog?.(`API key "${label}" deleted`, 'success')
      await load()
    } catch { /* ignore */ }
  }

  return (
    <div className="setting-field">
      <label className="setting-label">
        Anthropic API Keys
        {keys.length > 0 && <span className="setting-badge">{keys.length}</span>}
      </label>

      {keys.length > 0 && (
        <div className="api-key-list">
          {keys.map(k => (
            <div key={k.id} className="api-key-row">
              {editingId === k.id ? (
                <input
                  className="setting-input"
                  style={{ flex: 1, fontSize: 12 }}
                  value={editLabel}
                  onChange={e => setEditLabel(e.target.value)}
                  onBlur={() => saveLabel(k.id)}
                  onKeyDown={e => e.key === 'Enter' && saveLabel(k.id)}
                  autoFocus
                />
              ) : (
                <span
                  className="api-key-label"
                  onClick={() => { setEditingId(k.id); setEditLabel(k.label) }}
                  title="Click to rename"
                >
                  {k.label}
                </span>
              )}
              <span className="api-key-preview">{k.key_preview}</span>
              <button className="btn-icon" onClick={() => deleteKey(k.id, k.label)} title="Delete">×</button>
            </div>
          ))}
        </div>
      )}

      {adding ? (
        <div className="api-key-add-form">
          <input
            className="setting-input"
            style={{ fontSize: 12 }}
            placeholder="Label (e.g. Client A, Production)"
            value={newLabel}
            onChange={e => setNewLabel(e.target.value)}
            autoFocus
          />
          <input
            className="setting-input"
            style={{ fontSize: 12 }}
            type="password"
            placeholder="sk-ant-..."
            value={newKey}
            onChange={e => setNewKey(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addKey()}
          />
          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
            <button className="btn btn-approve" style={{ fontSize: 11, padding: '4px 10px' }} onClick={addKey} disabled={!newLabel.trim() || !newKey.trim()}>
              Save Key
            </button>
            <button className="btn" style={{ fontSize: 11, padding: '4px 10px', color: 'var(--text-dim)' }} onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button className="btn" style={{ fontSize: 11, padding: '4px 10px', marginTop: 4, color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => setAdding(true)}>
          + Add API Key
        </button>
      )}
    </div>
  )
}

function SettingField({ label, k, type = 'text', getVal, edit, settings, placeholder }) {
  const val = getVal(k)
  const isSet = settings[k]?.is_set
  return (
    <div className="setting-field">
      <label className="setting-label">
        {label}
        {isSet && <span className="setting-badge">SET</span>}
      </label>
      <input
        className="setting-input"
        type={type}
        value={val}
        onChange={e => edit(k, e.target.value)}
        placeholder={placeholder || ''}
        spellCheck={false}
      />
    </div>
  )
}
