import { useState, useEffect, useCallback } from 'react'
import { orgHeaders, cachedFetch } from '../api'

const API = '/api'

const CHANNEL_STYLES = [
  { key: 'voice_linkedin_style', label: 'LinkedIn', icon: 'LI' },
  { key: 'voice_x_style', label: 'X / Twitter', icon: 'X' },
  { key: 'voice_blog_style', label: 'Blog', icon: 'BG' },
  { key: 'voice_email_style', label: 'Release Email', icon: 'EM' },
  { key: 'voice_newsletter_style', label: 'Newsletter', icon: 'NL' },
  { key: 'voice_yt_style', label: 'YouTube Script', icon: 'YT' },
]

export default function Voice({ onLog, orgId }) {
  const [settings, setSettings] = useState({})
  const [edits, setEdits] = useState({})
  const [saving, setSaving] = useState(false)
  const [activeChannel, setActiveChannel] = useState('voice_linkedin_style')

  const load = useCallback(async () => {
    try {
      const res = await cachedFetch(`${API}/settings`, orgId)
      setSettings(await res.json())
    } catch (e) {
      onLog?.('Failed to load voice settings', 'error')
    }
  }, [onLog, orgId])

  useEffect(() => { load() }, [load])

  // Reset edits when org changes
  useEffect(() => { setEdits({}) }, [orgId])

  const edit = (key, val) => setEdits(prev => ({ ...prev, [key]: val }))
  const getVal = (key) => edits[key] ?? settings[key]?.value ?? ''
  const isDirty = Object.keys(edits).length > 0

  const save = async () => {
    if (!isDirty) return
    setSaving(true)
    onLog?.('Saving voice profile...', 'action')
    try {
      await fetch(`${API}/settings`, {
        method: 'PUT',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ settings: edits }),
      })
      setEdits({})
      onLog?.(`Voice profile saved: ${Object.keys(edits).join(', ')}`, 'success')
      await load()
    } catch (e) {
      onLog?.(`Save failed: ${e.message}`, 'error')
    } finally {
      setSaving(false)
    }
  }

  // Parse never_say as tags
  let neverSayTags = []
  try {
    neverSayTags = JSON.parse(getVal('voice_never_say') || '[]')
  } catch { neverSayTags = [] }

  let brandKeywords = []
  try {
    brandKeywords = JSON.parse(getVal('voice_brand_keywords') || '[]')
  } catch { brandKeywords = [] }

  const addTag = (key, currentTags, newTag) => {
    if (!newTag.trim() || currentTags.includes(newTag.trim())) return
    edit(key, JSON.stringify([...currentTags, newTag.trim()]))
  }

  const removeTag = (key, currentTags, idx) => {
    edit(key, JSON.stringify(currentTags.filter((_, i) => i !== idx)))
  }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2 className="settings-title">Voice Profile</h2>
        <button className={`btn btn-approve ${saving ? 'loading' : ''}`} onClick={save} disabled={!isDirty || saving}>
          {saving ? 'Saving...' : 'Save Voice'}
        </button>
      </div>

      {/* GOLDEN ANCHOR */}
      <div className="settings-section golden-anchor-section">
        <div className="section-label golden-anchor-label">
          <span className="anchor-icon">⚓</span> Golden Anchor Statement
        </div>
        <p className="voice-hint golden-anchor-hint">
          The core message or phrase to weave into all content. This is your company's north star.
        </p>
        <textarea
          className="setting-input voice-textarea golden-anchor-input"
          value={getVal('golden_anchor')}
          onChange={e => edit('golden_anchor', e.target.value)}
          placeholder="e.g. Every business deserves enterprise-grade APIs without enterprise-grade complexity."
          rows={3}
        />
      </div>

      {/* CORE IDENTITY */}
      <div className="settings-section">
        <div className="section-label">Identity</div>
        <div className="voice-grid">
          <div className="voice-field">
            <label className="setting-label">Persona</label>
            <textarea
              className="setting-input voice-textarea"
              value={getVal('voice_persona')}
              onChange={e => edit('voice_persona', e.target.value)}
              placeholder="Who is writing? Background, expertise, perspective."
              rows={3}
            />
            <div className="voice-field-help">How your company sounds. e.g. "Expert but approachable technical educator"</div>
          </div>
          <div className="voice-field">
            <label className="setting-label">Bio / Byline</label>
            <input
              className="setting-input"
              value={getVal('voice_bio')}
              onChange={e => edit('voice_bio', e.target.value)}
              placeholder="One-liner for author attribution"
            />
          </div>
          <div className="voice-field">
            <label className="setting-label">Target Audience</label>
            <input
              className="setting-input"
              value={getVal('voice_audience')}
              onChange={e => edit('voice_audience', e.target.value)}
              placeholder="Who are you writing for?"
            />
            <div className="voice-field-help">Who you're writing for. e.g. "CTOs and senior engineers at mid-market SaaS"</div>
          </div>
          <div className="voice-field">
            <label className="setting-label">Tone</label>
            <input
              className="setting-input"
              value={getVal('voice_tone')}
              onChange={e => edit('voice_tone', e.target.value)}
              placeholder="Direct, technical, casual, authoritative..."
            />
            <div className="voice-field-help">Writing energy. e.g. "Direct, confident, no corporate fluff"</div>
          </div>
          <div className="voice-field">
            <label className="setting-label">Always Do</label>
            <textarea
              className="setting-input voice-textarea"
              value={getVal('voice_always')}
              onChange={e => edit('voice_always', e.target.value)}
              placeholder="Guiding principles. What should every piece include or embody?"
              rows={2}
            />
          </div>
        </div>
      </div>

      {/* TAGS — Never Say & Brand Keywords */}
      <div className="settings-section">
        <div className="section-label">Word Rules</div>
        <div className="voice-tags-row">
          <div className="voice-tags-group">
            <label className="setting-label voice-tag-label-red">Never Say</label>
            <div className="tag-list">
              {neverSayTags.map((t, i) => (
                <span key={i} className="tag tag-red" onClick={() => removeTag('voice_never_say', neverSayTags, i)}>
                  {t} <span className="tag-x">&times;</span>
                </span>
              ))}
              <TagInput onAdd={(v) => addTag('voice_never_say', neverSayTags, v)} placeholder="add word..." />
            </div>
          </div>
          <div className="voice-tags-group">
            <label className="setting-label voice-tag-label-green">Brand Keywords</label>
            <div className="voice-field-help">Words that belong in your content. e.g. "API, integration, developer"</div>
            <div className="tag-list">
              {brandKeywords.map((t, i) => (
                <span key={i} className="tag tag-green" onClick={() => removeTag('voice_brand_keywords', brandKeywords, i)}>
                  {t} <span className="tag-x">&times;</span>
                </span>
              ))}
              <TagInput onAdd={(v) => addTag('voice_brand_keywords', brandKeywords, v)} placeholder="add keyword..." />
            </div>
          </div>
        </div>
      </div>

      {/* CHANNEL-SPECIFIC OVERRIDES */}
      <div className="settings-section">
        <div className="section-label">Channel Style Overrides</div>
        <div className="channel-tabs">
          {CHANNEL_STYLES.map(ch => (
            <button
              key={ch.key}
              className={`channel-tab ${activeChannel === ch.key ? 'active' : ''}`}
              onClick={() => setActiveChannel(ch.key)}
            >
              <span className="channel-tab-icon">{ch.icon}</span>
              <span className="channel-tab-name">{ch.label}</span>
            </button>
          ))}
        </div>
        <div className="channel-editor">
          {CHANNEL_STYLES.map(ch => (
            activeChannel === ch.key && (
              <textarea
                key={ch.key}
                className="setting-input voice-textarea channel-textarea"
                value={getVal(ch.key)}
                onChange={e => edit(ch.key, e.target.value)}
                placeholder={`Style notes for ${ch.label}. How should this channel sound differently?`}
                rows={4}
              />
            )
          ))}
        </div>
      </div>

      {/* WRITING EXAMPLES */}
      <div className="settings-section">
        <div className="section-label">Writing Examples</div>
        <p className="voice-hint">
          Paste examples of your ideal writing. Separate examples with blank lines.
          The engine uses these as few-shot references to match your voice.
        </p>
        <textarea
          className="setting-input voice-textarea examples-textarea"
          value={getVal('voice_writing_examples')}
          onChange={e => edit('voice_writing_examples', e.target.value)}
          placeholder={"Example post or paragraph here...\n\n---\n\nAnother example here...\n\n---\n\nThe engine learns from these."}
          rows={10}
        />
        {getVal('voice_writing_examples') && (
          <div className="voice-examples-count">
            {(getVal('voice_writing_examples').match(/---/g) || []).length + 1} examples loaded
          </div>
        )}
      </div>
    </div>
  )
}

function TagInput({ onAdd, placeholder }) {
  const [val, setVal] = useState('')
  const submit = () => {
    if (val.trim()) {
      onAdd(val)
      setVal('')
    }
  }
  return (
    <input
      className="tag-input"
      value={val}
      onChange={e => setVal(e.target.value)}
      onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); submit() } }}
      onBlur={submit}
      placeholder={placeholder}
    />
  )
}
