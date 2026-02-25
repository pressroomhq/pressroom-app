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

function formatSeconds(s) {
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}:${String(sec).padStart(2, '0')}`
}

const DURATION_OPTIONS = [
  { label: '60s — Quick outreach', value: 1 },
  { label: '90s — Short announcement', value: 1.5 },
  { label: '2 min — Standard', value: 2 },
  { label: '3 min — YouTube / thought leadership', value: 3 },
  { label: '5 min — Deep dive', value: 5 },
  { label: '8 min — Tutorial', value: 8 },
]

export default function YouTube({ orgId, allContent, onLog }) {
  const log = (msg, type = 'info') => onLog?.(msg, type)
  const [scripts, setScripts] = useState([])
  const [selected, setSelected] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const [stories, setStories] = useState([])
  const [showForm, setShowForm] = useState(false)

  // Form state
  const [scriptType, setScriptType] = useState('standard')
  const [sourceMode, setSourceMode] = useState('brief') // brief | story | content
  const [storyId, setStoryId] = useState('')
  const [contentId, setContentId] = useState('')
  const [brief, setBrief] = useState('')
  const [durationMinutes, setDurationMinutes] = useState(3)
  const [topics, setTopics] = useState('')
  const [presenter, setPresenter] = useState('person') // person | company
  const [presenterName, setPresenterName] = useState('')
  const [presenterTitle, setPresenterTitle] = useState('')
  const [targetPerson, setTargetPerson] = useState('')
  const [targetCompany, setTargetCompany] = useState('')
  const [targetRole, setTargetRole] = useState('')
  const [targetUrl, setTargetUrl] = useState('')

  // Teleprompter + footage upload
  const [teleprompter, setTeleprompter] = useState(false)
  const [uploadingFootage, setUploadingFootage] = useState(false)
  const [footageResult, setFootageResult] = useState(null)
  const [selectedFootage, setSelectedFootage] = useState(null) // File object
  const [renderingOBS, setRenderingOBS] = useState(false)
  const [chyronName, setChyronName] = useState('Nic Davidson')
  const [chyronTitle, setChyronTitle] = useState('Head of Engineering')
  const [chyronDuration, setChyronDuration] = useState(30)
  const [renderingChyron, setRenderingChyron] = useState(false)

  const load = useCallback(async () => {
    if (!orgId) return
    try {
      const [scriptsRes, storiesRes] = await Promise.all([
        orgFetch(`${API}/youtube/scripts`, orgId),
        orgFetch(`${API}/stories`, orgId),
      ])
      if (scriptsRes.ok) setScripts(await scriptsRes.json())
      if (storiesRes.ok) {
        const s = await storiesRes.json()
        setStories(Array.isArray(s) ? s : [])
      }
    } catch {}
  }, [orgId])

  useEffect(() => { load() }, [load])

  const generate = async () => {
    if (generating) return
    setGenerating(true)
    try {
      const body = {
        script_type: scriptType,
        duration_minutes: durationMinutes,
        topics: topics.split(',').map(t => t.trim()).filter(Boolean),
      }
      if (sourceMode === 'story' && storyId) body.story_id = Number(storyId)
      else if (sourceMode === 'content' && contentId) body.content_id = Number(contentId)
      else if (sourceMode === 'brief') body.brief = brief

      body.presenter = presenter
      if (presenterName.trim()) body.presenter_name = presenterName.trim()
      if (presenterTitle.trim()) body.presenter_title = presenterTitle.trim()
      if (scriptType === 'personalized') {
        body.target_person = targetPerson
        body.target_company = targetCompany
        body.target_role = targetRole
        if (targetUrl.trim()) body.target_url = targetUrl.trim()
      }

      const res = await orgFetch(`${API}/youtube/generate`, orgId, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      const auditNote = scriptType === 'personalized' && targetUrl ? ' + auditing target...' : ''
      log(`GENERATE — ${scriptType} script${auditNote}`, 'action')
      const data = await res.json()
      if (data.error) {
        log(`GENERATE FAILED — ${data.error}`, 'error')
      } else {
        await load()
        setSelected(data)
        setShowForm(false)
        log(`SCRIPT READY — "${data.title}"`, 'success')
      }
    } catch (e) {
      log(`GENERATE ERROR — ${e.message}`, 'error')
    } finally {
      setGenerating(false)
    }
  }

  const [rendering, setRendering] = useState(false)
  const [renderResult, setRenderResult] = useState(null)
  const [editingSections, setEditingSections] = useState(null) // local copy while editing
  const [saving, setSaving] = useState(false)

  const renderVideo = async (id) => {
    setRendering(true)
    setRenderResult(null)
    log('RENDER — starting Remotion render...', 'action')
    try {
      const res = await orgFetch(`${API}/youtube/scripts/${id}/render`, orgId, { method: 'POST' })
      const data = await res.json()
      if (data.error) {
        setRenderResult({ error: data.error })
        log(`RENDER FAILED — ${data.error}`, 'error')
      } else {
        setRenderResult({ path: data.output, duration: data.duration_seconds })
        setScripts(prev => prev.map(s => s.id === id ? { ...s, status: 'rendered' } : s))
        setSelected(prev => prev?.id === id ? { ...prev, status: 'rendered' } : prev)
        log(`RENDER COMPLETE — ${data.duration_seconds}s video ready`, 'success')
      }
    } catch (e) {
      setRenderResult({ error: e.message })
      log(`RENDER ERROR — ${e.message}`, 'error')
    } finally {
      setRendering(false)
    }
  }

  const exportPackage = async (id) => {
    try {
      const res = await orgFetch(`${API}/youtube/scripts/${id}/export`, orgId)
      const data = await res.json()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `remotion-package-${id}.json`
      a.click()
      URL.revokeObjectURL(url)
      log(`EXPORT — remotion-package-${id}.json downloaded`, 'info')
    } catch (e) {
      log(`EXPORT FAILED — ${e.message}`, 'error')
    }
  }

  const saveField = async (id, patch) => {
    setSaving(true)
    try {
      const res = await orgFetch(`${API}/youtube/scripts/${id}`, orgId, {
        method: 'PATCH',
        body: JSON.stringify(patch),
      })
      const updated = await res.json()
      if (!updated.error) {
        setSelected(updated)
        setScripts(prev => prev.map(s => s.id === id ? updated : s))
      }
    } catch {}
    setSaving(false)
  }

  const saveSections = async (id, secs) => {
    setSaving(true)
    try {
      const res = await orgFetch(`${API}/youtube/scripts/${id}`, orgId, {
        method: 'PATCH',
        body: JSON.stringify({ sections: secs }),
      })
      const updated = await res.json()
      if (!updated.error) {
        setSelected(updated)
        setScripts(prev => prev.map(s => s.id === id ? updated : s))
        setEditingSections(null)
      }
    } catch {}
    setSaving(false)
  }

  const deleteScript = async (id) => {
    try {
      await orgFetch(`${API}/youtube/scripts/${id}`, orgId, { method: 'DELETE' })
      setScripts(prev => prev.filter(s => s.id !== id))
      if (selected?.id === id) setSelected(null)
      log(`DELETED — script ${id}`, 'warn')
    } catch (e) {
      log(`DELETE FAILED — ${e.message}`, 'error')
    }
  }

  const uploadVideo = async (scriptId, isRendered = false) => {
    setUploading(true)
    setUploadResult(null)

    // If already rendered on server, skip file picker and publish directly
    if (isRendered) {
      log('YOUTUBE — uploading rendered video...', 'action')
      try {
        const res = await orgFetch(`${API}/youtube/scripts/${scriptId}/publish-rendered`, orgId, { method: 'POST' })
        const data = await res.json()
        if (data.error) {
          setUploadResult({ error: data.error })
          log(`YOUTUBE FAILED — ${data.error}`, 'error')
        } else {
          setUploadResult(data)
          await load()
          log(`YOUTUBE LIVE — ${data.youtube_url}`, 'success')
        }
      } catch (err) {
        setUploadResult({ error: err.message })
        log(`YOUTUBE ERROR — ${err.message}`, 'error')
      }
      setUploading(false)
      return
    }

    // Otherwise fall back to file picker
    setUploading(false)
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'video/mp4,video/*'
    input.onchange = async (e) => {
      const file = e.target.files[0]
      if (!file) return
      setUploading(true)
      log(`YOUTUBE — uploading ${file.name}...`, 'action')
      try {
        const form = new FormData()
        form.append('script_id', String(scriptId))
        form.append('video', file)
        const headers = {}
        if (orgId) headers['X-Org-Id'] = String(orgId)
        const res = await fetch(`${API}/youtube/publish`, { method: 'POST', headers, body: form })
        const data = await res.json()
        if (data.error) {
          setUploadResult({ error: data.error })
          log(`YOUTUBE FAILED — ${data.error}`, 'error')
        } else {
          setUploadResult(data)
          await load()
          log(`YOUTUBE LIVE — ${data.youtube_url}`, 'success')
        }
      } catch (err) {
        setUploadResult({ error: err.message })
        log(`YOUTUBE ERROR — ${err.message}`, 'error')
      }
      setUploading(false)
    }
    input.click()
  }

  const uploadFootage = async (scriptId, file) => {
    if (!file) return
    setUploadingFootage(true)
    setFootageResult(null)
    log(`FOOTAGE — uploading ${file.name} (${(file.size/1024/1024).toFixed(1)}MB)...`, 'action')
    try {
      const form = new FormData()
      form.append('video', file, file.name)
      const headers = {}
      if (orgId) headers['X-Org-Id'] = String(orgId)
      const res = await fetch(`${API}/youtube/scripts/${scriptId}/upload-footage`, {
        method: 'POST', headers, body: form,
      })
      const data = await res.json()
      if (data.error) {
        setFootageResult({ error: data.error })
        log(`FOOTAGE FAILED — ${data.error}`, 'error')
      } else {
        setFootageResult({ ok: true })
        setScripts(prev => prev.map(s => s.id === scriptId ? { ...s, status: 'rendered' } : s))
        setSelected(prev => prev?.id === scriptId ? { ...prev, status: 'rendered' } : prev)
        setSelectedFootage(null)
        log('FOOTAGE — brand overlay rendered, ready for YouTube', 'success')
      }
    } catch (e) {
      setFootageResult({ error: e.message })
      log(`FOOTAGE ERROR — ${e.message}`, 'error')
    } finally {
      setUploadingFootage(false)
    }
  }

  const approvedContent = (allContent || []).filter(c => c.status === 'approved' || c.status === 'published')

  let sections = [], lowerThirds = [], tags = []
  if (selected) {
    try { sections = JSON.parse(selected.sections || '[]') } catch {}
    try { lowerThirds = JSON.parse(selected.lower_thirds || '[]') } catch {}
    try { tags = JSON.parse(selected.metadata_tags || '[]') } catch {}
  }

  return (
    <div className="studio-layout">

      {/* ── LEFT: Script list + generate form ── */}
      <div className="studio-list">
        <div className="studio-list-header">
          <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 2, color: 'var(--amber)' }}>
            Video Scripts
          </span>
          <button
            className="btn btn-sm btn-approve"
            onClick={() => setShowForm(p => !p)}
            style={{ fontSize: 10, padding: '2px 8px' }}
          >
            {showForm ? '✕ Cancel' : '+ New Script'}
          </button>
        </div>

        {/* Generation form */}
        {showForm && (
          <div className="studio-gen-form">

            {/* Script type */}
            <div className="form-row">
              <label>Type</label>
              <select className="setting-input" value={scriptType} onChange={e => setScriptType(e.target.value)}>
                <option value="standard">Standard / Thought Leadership</option>
                <option value="release">Release Announcement</option>
                <option value="personalized">Personalized Outreach</option>
              </select>
            </div>

            {/* Presenter */}
            <div className="form-row">
              <label>Presenter</label>
              <div style={{ display: 'flex', gap: 4, marginBottom: presenter === 'person' ? 6 : 0 }}>
                {[{ v: 'person', label: 'Person on camera' }, { v: 'company', label: 'Company / animated' }].map(({ v, label }) => (
                  <button
                    key={v}
                    onClick={() => setPresenter(v)}
                    style={{
                      fontSize: 10, padding: '3px 10px', border: '1px solid var(--border)',
                      background: presenter === v ? 'var(--amber)' : 'var(--bg-card)',
                      color: presenter === v ? '#000' : 'var(--text-dim)',
                      cursor: 'pointer', flex: 1,
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {presenter === 'person' && (
                <div style={{ display: 'flex', gap: 4 }}>
                  <input
                    className="setting-input"
                    placeholder="Your name"
                    value={presenterName}
                    onChange={e => setPresenterName(e.target.value)}
                    style={{ flex: 2 }}
                  />
                  <input
                    className="setting-input"
                    placeholder="Title / role"
                    value={presenterTitle}
                    onChange={e => setPresenterTitle(e.target.value)}
                    style={{ flex: 2 }}
                  />
                </div>
              )}
            </div>

            {/* Personalization fields */}
            {scriptType === 'personalized' && (
              <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', padding: '8px 10px', marginBottom: 8 }}>
                <div style={{ fontSize: 10, color: 'var(--amber)', marginBottom: 6, letterSpacing: 1 }}>TARGET</div>
                <div className="form-row" style={{ marginBottom: 6 }}>
                  <input
                    className="setting-input"
                    placeholder="Name"
                    value={targetPerson}
                    onChange={e => setTargetPerson(e.target.value)}
                  />
                </div>
                <div className="form-row" style={{ marginBottom: 6 }}>
                  <input
                    className="setting-input"
                    placeholder="Role / Title"
                    value={targetRole}
                    onChange={e => setTargetRole(e.target.value)}
                  />
                </div>
                <div className="form-row" style={{ marginBottom: 6 }}>
                  <input
                    className="setting-input"
                    placeholder="Company"
                    value={targetCompany}
                    onChange={e => setTargetCompany(e.target.value)}
                  />
                </div>
                <div className="form-row" style={{ marginBottom: 0 }}>
                  <input
                    className="setting-input"
                    placeholder="Website URL — auto-crawl their brand (logo, colors)"
                    value={targetUrl}
                    onChange={e => setTargetUrl(e.target.value)}
                  />
                </div>
              </div>
            )}

            {/* Source */}
            <div className="form-row">
              <label>Source material</label>
              <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
                {['brief', 'story', 'content'].map(m => (
                  <button
                    key={m}
                    onClick={() => setSourceMode(m)}
                    style={{
                      fontSize: 10, padding: '2px 8px', border: '1px solid var(--border)',
                      background: sourceMode === m ? 'var(--amber)' : 'var(--bg-card)',
                      color: sourceMode === m ? '#000' : 'var(--text-dim)',
                      cursor: 'pointer', textTransform: 'uppercase', letterSpacing: 1,
                    }}
                  >
                    {m}
                  </button>
                ))}
              </div>

              {sourceMode === 'brief' && (
                <textarea
                  className="setting-input"
                  rows={4}
                  placeholder="What's this video about? Topic, angle, key points..."
                  value={brief}
                  onChange={e => setBrief(e.target.value)}
                />
              )}

              {sourceMode === 'story' && (
                <select className="setting-input" value={storyId} onChange={e => setStoryId(e.target.value)}>
                  <option value="">Select a story...</option>
                  {stories.map(s => (
                    <option key={s.id} value={s.id}>{s.title || 'Untitled'} ({s.signal_count || 0} signals)</option>
                  ))}
                </select>
              )}

              {sourceMode === 'content' && (
                <select className="setting-input" value={contentId} onChange={e => setContentId(e.target.value)}>
                  <option value="">Select content...</option>
                  {approvedContent.map(c => (
                    <option key={c.id} value={c.id}>[{c.channel}] {c.headline?.slice(0, 50)}</option>
                  ))}
                </select>
              )}
            </div>

            {/* Duration */}
            <div className="form-row">
              <label>Duration</label>
              <select className="setting-input" value={durationMinutes} onChange={e => setDurationMinutes(Number(e.target.value))}>
                {DURATION_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>

            {/* Additional topics */}
            <div className="form-row">
              <label>Additional topics <span style={{ color: 'var(--text-dim)', fontWeight: 400 }}>optional, comma-separated</span></label>
              <input
                className="setting-input"
                placeholder="e.g. API performance, use case for developers"
                value={topics}
                onChange={e => setTopics(e.target.value)}
              />
            </div>

            <button
              className={`btn btn-approve ${generating ? 'loading' : ''}`}
              onClick={generate}
              disabled={generating}
              style={{ width: '100%', marginTop: 4 }}
            >
              {generating ? 'Generating script...' : 'Generate Script'}
            </button>
          </div>
        )}

        {/* Script list */}
        {scripts.map(s => (
          <div
            key={s.id}
            className={`studio-script-item ${selected?.id === s.id ? 'active' : ''}`}
            onClick={() => { setSelected(s); setEditingSections(null) }}
          >
            <div className="studio-script-title">{s.title || 'Untitled'}</div>
            <div className="studio-script-meta">
              <span style={{ color: s.status === 'published' ? 'var(--green)' : 'var(--text-dim)' }}>
                {s.status}
              </span>
              <span>&middot; {s.created_at ? new Date(s.created_at).toLocaleDateString() : ''}</span>
            </div>
          </div>
        ))}

        {scripts.length === 0 && !showForm && (
          <div style={{ color: 'var(--text-dim)', fontSize: 11, padding: '16px 0' }}>
            No scripts yet. Hit + New Script to generate one.
          </div>
        )}
      </div>

      {/* ── RIGHT: Script detail ── */}
      <div className="studio-detail">
        {/* Brand Chyron — always available, no script needed */}
        <div className="studio-section" style={{ marginBottom: 24 }}>
          <div className="studio-section-label">Brand Chyron — OBS overlay</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
            <input
              className="setting-input"
              placeholder="Name"
              value={chyronName}
              onChange={e => setChyronName(e.target.value)}
              style={{ fontSize: 13 }}
            />
            <input
              className="setting-input"
              placeholder="Title"
              value={chyronTitle}
              onChange={e => setChyronTitle(e.target.value)}
              style={{ fontSize: 13 }}
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label style={{ fontSize: 11, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>Duration (s)</label>
              <input
                className="setting-input"
                type="number"
                min={5} max={300}
                value={chyronDuration}
                onChange={e => setChyronDuration(Number(e.target.value))}
                style={{ fontSize: 13, width: 70 }}
              />
            </div>
          </div>
          <button
            className={`btn btn-sm ${renderingChyron ? 'loading' : ''}`}
            disabled={renderingChyron}
            onClick={async () => {
              setRenderingChyron(true)
              log('CHYRON — rendering...', 'action')
              try {
                const headers = { 'Content-Type': 'application/json' }
                if (orgId) headers['X-Org-Id'] = String(orgId)
                const res = await fetch(`${API}/youtube/render-chyron`, {
                  method: 'POST',
                  headers,
                  body: JSON.stringify({ name: chyronName, title: chyronTitle, duration_seconds: chyronDuration }),
                })
                const data = await res.json()
                if (data.error) { log(`CHYRON failed — ${data.error}`, 'error'); setRenderingChyron(false); return }
                const jobId = data.job_id
                log(`CHYRON — job ${jobId}, polling...`, 'action')
                const poll = async () => {
                  const s = await fetch(`${API}/youtube/render-obs-status/${jobId}`, { headers: orgId ? { 'X-Org-Id': String(orgId) } : {} })
                  const status = await s.json()
                  if (status.status === 'done') {
                    const a = document.createElement('a')
                    a.href = `${API}/youtube/render-obs-download/${jobId}`
                    a.download = `brand_chyron.webm`
                    a.click()
                    log('CHYRON — downloaded. Drop into OBS as a media source.', 'success')
                    setRenderingChyron(false)
                  } else if (status.status === 'error') {
                    log(`CHYRON render failed — ${status.error}`, 'error')
                    setRenderingChyron(false)
                  } else {
                    setTimeout(poll, 3000)
                  }
                }
                setTimeout(poll, 4000)
              } catch (e) {
                log(`CHYRON error — ${e.message}`, 'error')
                setRenderingChyron(false)
              }
            }}
            style={{ fontSize: 11 }}
          >
            {renderingChyron ? 'Rendering chyron...' : '⬇ Download Chyron (.webm)'}
          </button>
        </div>

        {!selected && (
          <div style={{ color: 'var(--text-dim)', padding: 40, textAlign: 'center' }}>
            Select a script or generate a new one.
          </div>
        )}

        {selected && (
          <>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: 20, gap: 12 }}>
              <h2 style={{ fontFamily: 'var(--font-headline)', color: 'var(--amber)', fontSize: 20, margin: 0, lineHeight: 1.2 }}>
                {selected.title}
              </h2>
              <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                <button
                  className={`btn btn-sm ${teleprompter ? 'btn-approve' : ''}`}
                  onClick={() => { setTeleprompter(p => !p); setSelectedFootage(null); setFootageResult(null) }}
                  style={{ fontSize: 10 }}
                  title="Teleprompter + footage upload"
                >
                  {teleprompter ? '✕ Teleprompter' : '🎬 Record'}
                </button>
                <button
                  className={`btn btn-sm ${rendering ? 'loading' : ''}`}
                  onClick={() => renderVideo(selected.id)}
                  disabled={rendering}
                  style={{ fontSize: 10 }}
                >
                  {rendering ? 'Rendering...' : 'Render MP4'}
                </button>
                <button className="btn btn-sm" onClick={() => exportPackage(selected.id)} style={{ fontSize: 10 }}>
                  Export JSON
                </button>
                <button
                  className={`btn btn-sm btn-approve ${uploading ? 'loading' : ''}`}
                  onClick={() => uploadVideo(selected.id, selected.status === 'rendered')}
                  disabled={uploading}
                  style={{ fontSize: 10 }}
                  title={selected.status === 'rendered' ? 'Upload rendered file to YouTube' : 'Record or upload a video file'}
                >
                  {uploading ? 'Uploading...' : selected.status === 'rendered' ? '↑ YouTube' : '↑ Upload + YouTube'}
                </button>
                <button
                  className="btn btn-sm btn-danger"
                  onClick={() => deleteScript(selected.id)}
                  style={{ fontSize: 10 }}
                >
                  ✕
                </button>
              </div>
            </div>

            {renderResult && (
              <div style={{ fontSize: 11, marginBottom: 12, padding: '6px 10px', border: `1px solid ${renderResult.error ? 'var(--red)' : 'var(--green)'}` }}>
                {renderResult.error
                  ? <span style={{ color: 'var(--red)' }}>Render failed: {renderResult.error}</span>
                  : <span style={{ color: 'var(--green)' }}>
                      Rendered — <code style={{ color: 'var(--text-dim)' }}>{renderResult.path}</code>
                      {renderResult.duration && ` (${renderResult.duration}s)`}
                    </span>
                }
              </div>
            )}

            {uploadResult && (
              <div style={{ fontSize: 11, marginBottom: 16, padding: '6px 10px', border: `1px solid ${uploadResult.error ? 'var(--red)' : 'var(--green)'}` }}>
                {uploadResult.error
                  ? <span style={{ color: 'var(--red)' }}>Upload failed: {uploadResult.error}</span>
                  : <span style={{ color: 'var(--green)' }}>
                      Uploaded ({uploadResult.privacy}) — <a href={uploadResult.youtube_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--amber)' }}>{uploadResult.youtube_url}</a>
                    </span>
                }
              </div>
            )}

            {/* Teleprompter panel */}
            {teleprompter && (
              <div style={{ marginBottom: 20, border: '1px solid var(--amber)', background: 'var(--bg-panel)' }}>
                <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 2, color: 'var(--amber)' }}>
                    Teleprompter
                  </span>
                  <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                    Record yourself reading — Remotion adds brand overlays on top
                  </span>
                </div>

                {/* Script scroll */}
                <div style={{
                  padding: '16px 20px',
                  maxHeight: 280,
                  overflowY: 'auto',
                  fontSize: 18,
                  lineHeight: 1.7,
                  color: 'var(--text)',
                  fontFamily: 'var(--font-headline)',
                  background: '#0a0a0a',
                }}>
                  {selected.hook && (
                    <div style={{ color: 'var(--amber)', marginBottom: 12, fontSize: 20 }}>{selected.hook}</div>
                  )}
                  {sections.map((s, i) => (
                    <div key={i} style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
                        {s.heading}
                      </div>
                      {(Array.isArray(s.talking_points) ? s.talking_points : [])
                        .filter(tp => !tp.startsWith('[B-ROLL'))
                        .map((tp, j) => (
                          <div key={j} style={{ marginBottom: 8 }}>{tp}</div>
                        ))}
                    </div>
                  ))}
                  {selected.cta && (
                    <div style={{ color: 'var(--amber)', marginTop: 12 }}>{selected.cta}</div>
                  )}
                </div>

                {/* Controls */}
                <div style={{ padding: '10px 12px', borderTop: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <label
                    style={{
                      fontSize: 11, padding: '3px 10px', border: '1px solid var(--border)',
                      background: 'var(--bg-card)', color: 'var(--text)', cursor: 'pointer',
                    }}
                  >
                    Choose MP4...
                    <input
                      type="file"
                      accept="video/mp4,video/*"
                      style={{ display: 'none' }}
                      onChange={e => { setSelectedFootage(e.target.files[0] || null); setFootageResult(null) }}
                    />
                  </label>

                  {selectedFootage && (
                    <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      {selectedFootage.name} ({(selectedFootage.size / 1024 / 1024).toFixed(1)} MB)
                    </span>
                  )}

                  {selectedFootage && !footageResult && (
                    <button
                      className={`btn btn-sm btn-approve ${uploadingFootage ? 'loading' : ''}`}
                      onClick={() => uploadFootage(selected.id, selectedFootage)}
                      disabled={uploadingFootage}
                      style={{ fontSize: 11 }}
                    >
                      {uploadingFootage ? 'Processing...' : 'Add Brand Overlay + Render'}
                    </button>
                  )}

                  {footageResult && (
                    <div style={{ fontSize: 11, padding: '4px 8px', border: `1px solid ${footageResult.error ? 'var(--red)' : 'var(--green)'}`, flex: 1 }}>
                      {footageResult.error
                        ? <span style={{ color: 'var(--red)' }}>Failed: {footageResult.error}</span>
                        : <span style={{ color: 'var(--green)' }}>Rendered — ready to upload to YouTube</span>
                      }
                    </div>
                  )}
                </div>

                {/* OBS overlay export */}
                <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 8 }}>
                    <strong style={{ color: 'var(--text)' }}>OBS Mode</strong> — render brand overlays as a transparent .webm.
                    Drop it into OBS as a media source over your webcam. Script timing drives the duration — stick to it.
                  </div>
                  <button
                    className={`btn btn-sm ${renderingOBS ? 'loading' : ''}`}
                    disabled={renderingOBS}
                    onClick={async () => {
                      setRenderingOBS(true)
                      log('OBS — kicking off render...', 'action')
                      try {
                        const headers = {}
                        if (orgId) headers['X-Org-Id'] = String(orgId)

                        // Kick off async render job
                        const res = await fetch(`${API}/youtube/scripts/${selected.id}/render-obs`, {
                          method: 'POST', headers,
                        })
                        const data = await res.json()
                        if (!res.ok || data.error) {
                          log(`OBS render failed — ${data.error}`, 'error')
                          return
                        }

                        const jobId = data.job_id
                        log(`OBS — rendering (job ${jobId})...`, 'action')

                        // Poll until done
                        const poll = async () => {
                          const s = await fetch(`${API}/youtube/render-obs-status/${jobId}`, { headers })
                          const status = await s.json()
                          if (status.status === 'done') {
                            // Trigger download
                            const a = document.createElement('a')
                            a.href = `${API}/youtube/render-obs-download/${jobId}`
                            a.download = `obs_overlay_${selected.id}.webm`
                            a.click()
                            log('OBS overlay downloaded — add to OBS as media source over your webcam', 'success')
                            setRenderingOBS(false)
                          } else if (status.status === 'error') {
                            log(`OBS render failed — ${status.error}`, 'error')
                            setRenderingOBS(false)
                          } else {
                            setTimeout(poll, 3000)
                          }
                        }
                        setTimeout(poll, 5000)
                      } catch (e) {
                        log(`OBS error — ${e.message}`, 'error')
                        setRenderingOBS(false)
                      }
                    }}
                    style={{ fontSize: 11 }}
                  >
                    {renderingOBS ? 'Rendering OBS overlay...' : '⬇ Download OBS Overlay (.webm)'}
                  </button>
                </div>
              </div>
            )}

            {/* Hook */}
            <div className="studio-section">
              <div className="studio-section-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                Hook — first 15 seconds
                {saving && <span style={{ color: 'var(--text-dim)', fontWeight: 400 }}>saving...</span>}
              </div>
              <textarea
                className="setting-input studio-hook"
                rows={3}
                defaultValue={selected.hook || ''}
                key={selected.id + '-hook'}
                onBlur={e => { if (e.target.value !== selected.hook) saveField(selected.id, { hook: e.target.value }) }}
                style={{ width: '100%', resize: 'vertical', fontFamily: 'inherit', fontSize: 14, lineHeight: 1.5 }}
              />
            </div>

            {/* Sections */}
            {sections.length > 0 && (
              <div className="studio-section">
                <div className="studio-section-label" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>Script — {formatSeconds(sections.reduce((a, s) => a + (s.duration_seconds || 0), 0))} total</span>
                  {!editingSections
                    ? <button className="btn btn-sm" style={{ fontSize: 10 }} onClick={() => setEditingSections(JSON.parse(JSON.stringify(sections)))}>Edit</button>
                    : <div style={{ display: 'flex', gap: 4 }}>
                        <button className={`btn btn-sm btn-approve ${saving ? 'loading' : ''}`} style={{ fontSize: 10 }} disabled={saving} onClick={() => saveSections(selected.id, editingSections)}>Save</button>
                        <button className="btn btn-sm" style={{ fontSize: 10 }} onClick={() => setEditingSections(null)}>Cancel</button>
                      </div>
                  }
                </div>

                {(editingSections || sections).map((s, i) => {
                  const isEditing = !!editingSections
                  const sec = editingSections ? editingSections[i] : s
                  const points = Array.isArray(sec.talking_points) ? sec.talking_points : []

                  return (
                    <div key={i} className="studio-section-card">
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
                        {isEditing
                          ? <input
                              className="setting-input"
                              value={sec.heading}
                              onChange={e => {
                                const next = [...editingSections]
                                next[i] = { ...next[i], heading: e.target.value }
                                setEditingSections(next)
                              }}
                              style={{ flex: 1, fontSize: 13, fontWeight: 600, marginRight: 8 }}
                            />
                          : <div className="studio-section-heading">{sec.heading}</div>
                        }
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          {sec.duration_seconds && (
                            isEditing
                              ? <input
                                  className="setting-input"
                                  type="number"
                                  value={sec.duration_seconds}
                                  onChange={e => {
                                    const next = [...editingSections]
                                    next[i] = { ...next[i], duration_seconds: Number(e.target.value) }
                                    setEditingSections(next)
                                  }}
                                  style={{ width: 56, fontSize: 11, textAlign: 'right' }}
                                />
                              : <div className="studio-section-duration">{sec.duration_seconds}s</div>
                          )}
                        </div>
                      </div>

                      <div className="studio-section-points">
                        {points.map((tp, j) => (
                          isEditing
                            ? <div key={j} style={{ display: 'flex', gap: 4, marginBottom: 4 }}>
                                <textarea
                                  className="setting-input"
                                  rows={2}
                                  value={tp}
                                  onChange={e => {
                                    const next = [...editingSections]
                                    const pts = [...next[i].talking_points]
                                    pts[j] = e.target.value
                                    next[i] = { ...next[i], talking_points: pts }
                                    setEditingSections(next)
                                  }}
                                  style={{ flex: 1, fontSize: 12, resize: 'vertical' }}
                                />
                                <button
                                  style={{ fontSize: 11, padding: '2px 6px', border: '1px solid var(--border)', background: 'none', color: 'var(--text-dim)', cursor: 'pointer', alignSelf: 'flex-start' }}
                                  onClick={() => {
                                    const next = [...editingSections]
                                    const pts = next[i].talking_points.filter((_, k) => k !== j)
                                    next[i] = { ...next[i], talking_points: pts }
                                    setEditingSections(next)
                                  }}
                                >✕</button>
                              </div>
                            : <div key={j} style={{ color: tp.startsWith('[B-ROLL') ? 'var(--amber)' : 'var(--text)', marginBottom: 4 }}>
                                {tp.startsWith('[B-ROLL') ? tp : `• ${tp}`}
                              </div>
                        ))}
                        {isEditing && (
                          <button
                            style={{ fontSize: 11, padding: '2px 8px', border: '1px dashed var(--border)', background: 'none', color: 'var(--text-dim)', cursor: 'pointer', marginTop: 4 }}
                            onClick={() => {
                              const next = [...editingSections]
                              next[i] = { ...next[i], talking_points: [...(next[i].talking_points || []), ''] }
                              setEditingSections(next)
                            }}
                          >+ point</button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {/* CTA */}
            <div className="studio-section">
              <div className="studio-section-label">Call to Action</div>
              <textarea
                className="setting-input"
                rows={2}
                defaultValue={selected.cta || ''}
                key={selected.id + '-cta'}
                onBlur={e => { if (e.target.value !== selected.cta) saveField(selected.id, { cta: e.target.value }) }}
                style={{ width: '100%', resize: 'vertical', fontSize: 13 }}
              />
            </div>

            {/* Lower thirds */}
            {lowerThirds.length > 0 && (
              <div className="studio-section">
                <div className="studio-section-label">Lower Thirds</div>
                {lowerThirds.map((lt, i) => (
                  <div key={i} className="studio-lower-third">
                    <span className="studio-lower-third-time">@{formatSeconds(lt.at_second || 0)}</span>
                    {' '}{lt.name}{lt.title ? ` · ${lt.title}` : ''}{lt.company ? ` · ${lt.company}` : ''}
                  </div>
                ))}
              </div>
            )}

            {/* YouTube metadata */}
            <div className="studio-section">
              <div className="studio-section-label">YouTube Metadata</div>
              <div className="studio-meta-field">
                <span className="studio-meta-label">Title</span>
                <div className="studio-meta-value">{selected.metadata_title || '—'}</div>
              </div>
              <div className="studio-meta-field">
                <span className="studio-meta-label">Description</span>
                <div className="studio-meta-value" style={{ whiteSpace: 'pre-wrap', maxHeight: 160, overflowY: 'auto' }}>
                  {selected.metadata_description || '—'}
                </div>
              </div>
              {tags.length > 0 && (
                <div className="studio-meta-field">
                  <span className="studio-meta-label">Tags</span>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                    {tags.map((t, i) => <span key={i} className="studio-tag">{t}</span>)}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
