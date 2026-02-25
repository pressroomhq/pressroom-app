import { useState, useEffect, useCallback } from 'react'
import { orgHeaders } from '../api'

const API = '/api'
const ASSET_TYPES = ['subdomain', 'blog', 'docs', 'repo', 'social', 'product', 'page', 'api_endpoint']

export default function Assets({ orgId }) {
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [newAsset, setNewAsset] = useState({ asset_type: 'blog', url: '', label: '', description: '' })
  const [editingId, setEditingId] = useState(null)
  const [editLabel, setEditLabel] = useState('')

  const headers = orgHeaders(orgId)

  const fetchAssets = useCallback(async () => {
    try {
      const res = await fetch(`${API}/assets`, { headers })
      const data = await res.json()
      setAssets(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [orgId])

  useEffect(() => { fetchAssets() }, [fetchAssets])

  const addAsset = async () => {
    if (!newAsset.url.trim()) return
    await fetch(`${API}/assets`, { method: 'POST', headers, body: JSON.stringify(newAsset) })
    setNewAsset({ asset_type: 'blog', url: '', label: '', description: '' })
    setShowAdd(false)
    fetchAssets()
  }

  const saveLabel = async (id) => {
    await fetch(`${API}/assets/${id}`, { method: 'PUT', headers, body: JSON.stringify({ label: editLabel }) })
    setEditingId(null)
    fetchAssets()
  }

  const deleteAsset = async (id) => {
    await fetch(`${API}/assets/${id}`, { method: 'DELETE', headers })
    fetchAssets()
  }

  // Group by type
  const grouped = {}
  assets.forEach(a => {
    const t = a.asset_type || 'other'
    if (!grouped[t]) grouped[t] = []
    grouped[t].push(a)
  })

  if (loading) return <div className="settings-page"><p style={{ color: 'var(--text-dim)' }}>Loading assets...</p></div>

  return (
    <div className="settings-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 className="settings-title" style={{ margin: 0 }}>Company Asset Map</h2>
        <button className="btn btn-approve" onClick={() => setShowAdd(!showAdd)}>
          {showAdd ? 'Cancel' : '+ Add Asset'}
        </button>
      </div>

      {showAdd && (
        <div className="asset-add-form">
          <select
            className="setting-input"
            value={newAsset.asset_type}
            onChange={e => setNewAsset(p => ({ ...p, asset_type: e.target.value }))}
            style={{ width: 140 }}
          >
            {ASSET_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
          <input
            className="setting-input"
            placeholder="URL"
            value={newAsset.url}
            onChange={e => setNewAsset(p => ({ ...p, url: e.target.value }))}
            style={{ flex: 1 }}
          />
          <input
            className="setting-input"
            placeholder="Label (optional)"
            value={newAsset.label}
            onChange={e => setNewAsset(p => ({ ...p, label: e.target.value }))}
            style={{ width: 160 }}
          />
          <button className="btn btn-approve" onClick={addAsset} disabled={!newAsset.url.trim()}>Add</button>
        </div>
      )}

      {assets.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)' }}>
          No assets discovered yet. Onboard a company to auto-discover, or add manually.
        </div>
      ) : (
        Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b)).map(([type, items]) => (
          <div key={type} className="asset-group">
            <div className="asset-group-header">
              <span className="asset-type-badge">{type.toUpperCase()}</span>
              <span className="asset-group-count">{items.length}</span>
            </div>
            {items.map(a => (
              <div key={a.id} className="asset-card">
                <div className="asset-card-main">
                  <a href={a.url} target="_blank" rel="noopener noreferrer" className="asset-url">
                    {a.url}
                  </a>
                  {a.auto_discovered ? <span className="asset-badge-auto">auto</span> : null}
                </div>
                <div className="asset-card-label">
                  {editingId === a.id ? (
                    <input
                      className="setting-input asset-label-input"
                      value={editLabel}
                      onChange={e => setEditLabel(e.target.value)}
                      onBlur={() => saveLabel(a.id)}
                      onKeyDown={e => e.key === 'Enter' && saveLabel(a.id)}
                      autoFocus
                    />
                  ) : (
                    <span
                      className="asset-label-text"
                      onClick={() => { setEditingId(a.id); setEditLabel(a.label || '') }}
                      title="Click to edit label"
                    >
                      {a.label || 'click to label...'}
                    </span>
                  )}
                  {a.description && <span className="asset-desc">{a.description}</span>}
                </div>
                <button className="asset-delete" onClick={() => deleteAsset(a.id)} title="Remove asset">&times;</button>
              </div>
            ))}
          </div>
        ))
      )}
    </div>
  )
}
