import { useState, useEffect, useCallback } from 'react'

const API = '/api'

function orgHeaders(orgId) {
  const h = { 'Content-Type': 'application/json' }
  if (orgId) h['X-Org-Id'] = String(orgId)
  return h
}

function orgFetch(url, orgId, opts = {}) {
  const headers = { ...orgHeaders(orgId), ...(opts.headers || {}) }
  return fetch(url, { ...opts, headers })
}

const WIRED_SKILLS = ['humanizer', 'seo_geo']

export default function Skills({ orgId }) {
  const [skills, setSkills] = useState([])
  const [selected, setSelected] = useState(null)
  const [content, setContent] = useState('')
  const [original, setOriginal] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedFlash, setSavedFlash] = useState(false)
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/skills`, { headers: orgHeaders(orgId) })
      if (res.ok) setSkills(await res.json())
    } catch {}
  }, [orgId])

  useEffect(() => {
    setSelected(null)
    setContent('')
    setOriginal('')
    load()
  }, [load])

  const selectSkill = async (skill) => {
    setSelected(skill)
    setSavedFlash(false)
    try {
      const res = await fetch(`${API}/skills/${skill.name}`)
      if (res.ok) {
        const data = await res.json()
        setContent(data.content || '')
        setOriginal(data.content || '')
      }
    } catch {}
  }

  const save = async () => {
    if (!selected || saving) return
    setSaving(true)
    try {
      const res = await fetch(`${API}/skills/${selected.name}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      if (res.ok) {
        setOriginal(content)
        setSavedFlash(true)
        setTimeout(() => setSavedFlash(false), 1500)
        load()
      }
    } catch {} finally {
      setSaving(false)
    }
  }

  const revert = () => {
    setContent(original)
  }

  const deleteSkill = async () => {
    if (!selected) return
    if (WIRED_SKILLS.includes(selected.name)) {
      alert('Cannot delete core wired skills.')
      return
    }
    if (!confirm(`Delete skill "${selected.name}"? This cannot be undone.`)) return
    try {
      await fetch(`${API}/skills/${selected.name}`, { method: 'DELETE' })
      setSelected(null)
      setContent('')
      setOriginal('')
      load()
    } catch {}
  }

  const createSkill = async () => {
    const name = newName.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_')
    if (!name) return
    setCreating(true)
    try {
      const res = await fetch(`${API}/skills`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, content: `# ${name}\n\nYour skill prompt here.\n` }),
      })
      if (res.ok) {
        setNewName('')
        await load()
        selectSkill({ name })
      } else {
        const data = await res.json()
        alert(data.error || 'Failed to create skill')
      }
    } catch {} finally {
      setCreating(false)
    }
  }

  const isDirty = content !== original
  const lines = content.split('\n').length
  const chars = content.length

  return (
    <div className="skills-layout">
      <div className="skills-list-panel">
        <div className="skills-list-header">
          <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 2, color: 'var(--amber)' }}>Skills</span>
          <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>{skills.length}</span>
        </div>

        <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', gap: 4 }}>
            <input
              className="tag-input"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="new skill name"
              onKeyDown={e => { if (e.key === 'Enter') createSkill() }}
              style={{ flex: 1 }}
            />
            <button className="btn" onClick={createSkill} disabled={creating || !newName.trim()} style={{ fontSize: 9, padding: '2px 8px' }}>
              NEW
            </button>
          </div>
        </div>

        {skills.map(s => (
          <div
            key={s.name}
            className={`skill-item ${selected?.name === s.name ? 'active' : ''}`}
            onClick={() => selectSkill(s)}
          >
            <div className="skill-item-name">{s.name}</div>
            <div className="skill-item-preview">{s.first_line || ''}</div>
            <div className="skill-item-meta">
              <span className={WIRED_SKILLS.includes(s.name) ? 'skill-badge-wired' : 'skill-badge-available'}>
                {WIRED_SKILLS.includes(s.name) ? 'WIRED' : 'AVAILABLE'}
              </span>
              <span>{s.size_bytes ? `${s.size_bytes}b` : ''}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="skills-editor-panel">
        {!selected && (
          <div style={{ color: 'var(--text-dim)', padding: 40, textAlign: 'center' }}>
            Select a skill to edit or create a new one.
          </div>
        )}

        {selected && (
          <>
            <div className="skill-editor-header">
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <span className="skill-editor-name">{selected.name}.md</span>
                {isDirty && <span className="skill-unsaved">UNSAVED</span>}
                {savedFlash && <span className="skill-saved-flash">SAVED</span>}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="btn btn-approve" onClick={save} disabled={saving || !isDirty} style={{ fontSize: 10 }}>
                  {saving ? 'Saving...' : 'Save'}
                </button>
                <button className="btn" onClick={revert} disabled={!isDirty} style={{ fontSize: 10, color: 'var(--text-dim)', borderColor: 'var(--border)' }}>
                  Revert
                </button>
                {!WIRED_SKILLS.includes(selected.name) && (
                  <button className="btn btn-spike" onClick={deleteSkill} style={{ fontSize: 10 }}>
                    Delete
                  </button>
                )}
              </div>
            </div>
            <textarea
              className="skill-editor-textarea"
              value={content}
              onChange={e => setContent(e.target.value)}
              spellCheck={false}
            />
            <div className="skill-editor-footer">
              <span className="skill-editor-stats">{lines} lines &middot; {chars} chars</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
