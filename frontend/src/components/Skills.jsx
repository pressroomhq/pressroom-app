import { useState, useEffect, useCallback } from 'react'
import { orgFetch } from '../api'

const API = '/api'

/*
 * Workflow groups — map backend categories + skill names to user-facing workflows.
 * The user thinks in terms of what they're DOING, not where the file lives.
 */
const WORKFLOW_GROUPS = [
  {
    key: 'content',
    label: 'Content Creation',
    description: 'Channel formats and post-processing used by the content pipeline',
    match: (s) => s.category === 'channel' || s.category === 'processing',
  },
  {
    key: 'outreach',
    label: 'Outreach & Email',
    description: 'Cold outreach, drip sequences, and email campaigns',
    match: (s) => ['cold_email', 'email_sequence'].includes(s.name),
  },
  {
    key: 'seo',
    label: 'SEO & Visibility',
    description: 'Search optimization, AI citations, and content auditing',
    match: (s) => s.category === 'seo',
  },
  {
    key: 'strategy',
    label: 'Strategy & Research',
    description: 'Competitor analysis, positioning, and landing page copy',
    match: (s) => ['competitor_analysis', 'landing_page_copy'].includes(s.name),
  },
]

function classifySkill(skill) {
  for (const g of WORKFLOW_GROUPS) {
    if (g.match(skill)) return g.key
  }
  return 'content' // fallback
}

export default function Skills({ orgId }) {
  const [allSkills, setAllSkills] = useState([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState(null)
  const [content, setContent] = useState('')
  const [original, setOriginal] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedFlash, setSavedFlash] = useState(false)
  const [rewriting, setRewriting] = useState(false)
  const [newName, setNewName] = useState('')
  const [newCategory, setNewCategory] = useState('marketing')
  const [creating, setCreating] = useState(false)
  const [collapsed, setCollapsed] = useState({})

  const load = useCallback(async () => {
    try {
      const res = await orgFetch(`${API}/skills`, orgId)
      if (res.ok) {
        const data = await res.json()
        // Flatten all categories into a single list
        const flat = []
        for (const [cat, skills] of Object.entries(data.skills || {})) {
          for (const s of skills) {
            flat.push({ ...s, category: cat })
          }
        }
        setAllSkills(flat)
        setTotal(data.total || 0)
      }
    } catch {}
  }, [orgId])

  useEffect(() => {
    setSelected(null)
    setContent('')
    setOriginal('')
    load()
  }, [load])

  // Group skills into workflow buckets
  const grouped = {}
  for (const g of WORKFLOW_GROUPS) {
    grouped[g.key] = allSkills.filter(s => classifySkill(s) === g.key).sort((a, b) => a.name.localeCompare(b.name))
  }

  const selectSkill = async (skill) => {
    setSelected(skill)
    setSavedFlash(false)
    try {
      const res = await orgFetch(`${API}/skills/${skill.name}`, orgId)
      if (res.ok) {
        const data = await res.json()
        setContent(data.content || '')
        setOriginal(data.content || '')
        setSelected({ ...skill, ...data })
      }
    } catch {}
  }

  const save = async () => {
    if (!selected || saving) return
    setSaving(true)
    try {
      const res = await orgFetch(`${API}/skills/${selected.name}`, orgId, {
        method: 'PUT',
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

  const revert = () => setContent(original)

  const resetToTemplate = async () => {
    if (!selected) return
    if (!confirm(`Reset "${selected.name}" to the default template? Your customizations will be lost.`)) return
    try {
      const res = await orgFetch(`${API}/skills/${selected.name}/reset`, orgId, { method: 'POST' })
      if (res.ok) {
        await selectSkill(selected)
        load()
      }
    } catch {}
  }

  const deleteSkill = async () => {
    if (!selected) return
    const msg = selected.has_template
      ? `Remove your customization of "${selected.name}"? It will revert to the default template.`
      : `Delete custom skill "${selected.name}"? This cannot be undone.`
    if (!confirm(msg)) return
    try {
      await orgFetch(`${API}/skills/${selected.name}`, orgId, { method: 'DELETE' })
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
      const res = await orgFetch(`${API}/skills`, orgId, {
        method: 'POST',
        body: JSON.stringify({ name, category: newCategory, content: `# ${name}\n\nYour skill prompt here.\n` }),
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

  const rewriteAll = async () => {
    if (!confirm('Re-generate all skills from your company profile? This will overwrite any manual edits.')) return
    setRewriting(true)
    try {
      const res = await orgFetch(`${API}/skills/rewrite`, orgId, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        alert(`Rewrote ${data.rewritten} skills successfully.`)
        load()
        if (selected) selectSkill(selected)
      } else {
        const data = await res.json()
        alert(data.error || 'Skill rewrite failed')
      }
    } catch {} finally {
      setRewriting(false)
    }
  }

  const toggleCategory = (key) => {
    setCollapsed(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const isDirty = content !== original
  const lines = content.split('\n').length
  const chars = content.length
  const customizedCount = allSkills.filter(s => s.is_customized).length

  return (
    <div className="skills-layout">
      <div className="skills-list-panel">
        <div className="skills-list-header">
          <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 2, color: 'var(--amber)' }}>Skills</span>
          <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>{customizedCount}/{total} customized</span>
        </div>

        {/* Rewrite all button */}
        <div style={{ padding: '6px 12px', borderBottom: '1px solid var(--border)' }}>
          <button
            className="btn"
            onClick={rewriteAll}
            disabled={rewriting}
            style={{ fontSize: 9, width: '100%', padding: '4px 8px', color: 'var(--amber)', borderColor: 'var(--amber)' }}
          >
            {rewriting ? 'REWRITING...' : 'REWRITE ALL FROM PROFILE'}
          </button>
          <div style={{ fontSize: 8, color: 'var(--text-dim)', marginTop: 3, textAlign: 'center' }}>
            Regenerates all skills using your company voice & profile
          </div>
        </div>

        {/* Workflow groups */}
        {WORKFLOW_GROUPS.map(g => {
          const skills = grouped[g.key]
          if (!skills || skills.length === 0) return null
          const isCollapsed = collapsed[g.key]
          const groupCustomized = skills.filter(s => s.is_customized).length

          return (
            <div key={g.key}>
              <div
                onClick={() => toggleCategory(g.key)}
                style={{
                  padding: '8px 12px',
                  fontSize: 10,
                  fontWeight: 600,
                  color: 'var(--text-bright)',
                  cursor: 'pointer',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  borderBottom: '1px solid var(--border)',
                  background: 'rgba(255,255,255,0.02)',
                  userSelect: 'none',
                }}
              >
                <div>
                  <div>{g.label}</div>
                  <div style={{ fontSize: 8, color: 'var(--text-dim)', fontWeight: 400, marginTop: 1 }}>{g.description}</div>
                </div>
                <div style={{ textAlign: 'right', whiteSpace: 'nowrap', marginLeft: 8 }}>
                  <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>{isCollapsed ? '+' : '-'}</span>
                  <div style={{ fontSize: 8, color: groupCustomized === skills.length ? 'var(--green)' : 'var(--text-dim)' }}>
                    {groupCustomized}/{skills.length}
                  </div>
                </div>
              </div>

              {!isCollapsed && skills.map(s => (
                <div
                  key={s.name}
                  className={`skill-item ${selected?.name === s.name ? 'active' : ''}`}
                  onClick={() => selectSkill(s)}
                >
                  <div className="skill-item-name">{s.name.replace(/_/g, ' ')}</div>
                  <div className="skill-item-preview">{s.first_line?.replace(/^#\s*/, '') || ''}</div>
                  <div className="skill-item-meta">
                    {s.is_customized ? (
                      <span className="skill-badge-wired">CUSTOMIZED</span>
                    ) : (
                      <span className="skill-badge-available">DEFAULT</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )
        })}

        {/* Create new skill */}
        <div style={{ padding: '8px 12px', borderTop: '1px solid var(--border)', marginTop: 'auto' }}>
          <div style={{ fontSize: 9, color: 'var(--text-dim)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 1 }}>New Custom Skill</div>
          <div style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
            <input
              className="tag-input"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              placeholder="skill name"
              onKeyDown={e => { if (e.key === 'Enter') createSkill() }}
              style={{ flex: 1 }}
            />
            <button className="btn" onClick={createSkill} disabled={creating || !newName.trim()} style={{ fontSize: 9, padding: '2px 8px' }}>
              +
            </button>
          </div>
          <select
            value={newCategory}
            onChange={e => setNewCategory(e.target.value)}
            style={{ fontSize: 9, width: '100%', background: 'var(--bg)', color: 'var(--text-dim)', border: '1px solid var(--border)', padding: '2px 4px' }}
          >
            <option value="channel">Content Channel</option>
            <option value="marketing">Marketing</option>
            <option value="seo">SEO</option>
            <option value="processing">Processing</option>
          </select>
        </div>
      </div>

      <div className="skills-editor-panel">
        {!selected && (
          <div style={{ color: 'var(--text-dim)', padding: 40, textAlign: 'center' }}>
            <div style={{ fontSize: 14, marginBottom: 8 }}>Select a skill to view or edit</div>
            <div style={{ fontSize: 11 }}>
              Skills are the system prompts that shape every piece of content Pressroom generates.
              {customizedCount === 0 && (
                <span> Hit <strong>REWRITE ALL FROM PROFILE</strong> to customize them to your company voice.</span>
              )}
            </div>
          </div>
        )}

        {selected && (
          <>
            <div className="skill-editor-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="skill-editor-name">{selected.name.replace(/_/g, ' ')}</span>
                {selected.is_customized && (
                  <span style={{ fontSize: 8, color: 'var(--green)', border: '1px solid var(--green)', padding: '0 4px', textTransform: 'uppercase', letterSpacing: 1 }}>
                    customized
                  </span>
                )}
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
                {selected.is_customized && selected.has_template && (
                  <button className="btn" onClick={resetToTemplate} style={{ fontSize: 10, color: 'var(--amber)', borderColor: 'var(--amber)' }}>
                    Reset to Default
                  </button>
                )}
                {(!selected.has_template || selected.is_customized) && (
                  <button className="btn btn-spike" onClick={deleteSkill} style={{ fontSize: 10 }}>
                    {selected.has_template ? 'Remove Override' : 'Delete'}
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
              <span className="skill-editor-stats" style={{ marginLeft: 8, color: 'var(--text-dim)' }}>
                {WORKFLOW_GROUPS.find(g => g.key === classifySkill(selected))?.label || selected.category}
              </span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
