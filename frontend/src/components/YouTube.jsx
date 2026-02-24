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

export default function YouTube({ orgId, allContent }) {
  const [scripts, setScripts] = useState([])
  const [selected, setSelected] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [contentId, setContentId] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)

  const load = useCallback(async () => {
    if (!orgId) return
    try {
      const res = await orgFetch(`${API}/youtube/scripts`, orgId)
      if (res.ok) setScripts(await res.json())
    } catch {}
  }, [orgId])

  useEffect(() => { load() }, [load])

  const generate = async () => {
    if (generating) return
    setGenerating(true)
    try {
      const body = contentId ? { content_id: Number(contentId) } : {}
      const res = await orgFetch(`${API}/youtube/generate`, orgId, {
        method: 'POST',
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (data.error) {
        alert(data.error)
      } else {
        await load()
        setSelected(data)
      }
    } catch (e) {
      alert(`Generate failed: ${e.message}`)
    } finally {
      setGenerating(false)
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
    } catch (e) {
      alert(`Export failed: ${e.message}`)
    }
  }

  const uploadVideo = async (scriptId) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'video/mp4,video/*'
    input.onchange = async (e) => {
      const file = e.target.files[0]
      if (!file) return
      setUploading(true)
      setUploadResult(null)
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
        } else {
          setUploadResult(data)
          await load()
        }
      } catch (err) {
        setUploadResult({ error: err.message })
      }
      setUploading(false)
    }
    input.click()
  }

  const approvedContent = (allContent || []).filter(c => c.status === 'approved' || c.status === 'published')
  let sections = []
  let lowerThirds = []
  let tags = []
  if (selected) {
    try { sections = JSON.parse(selected.sections || '[]') } catch { sections = [] }
    try { lowerThirds = JSON.parse(selected.lower_thirds || '[]') } catch { lowerThirds = [] }
    try { tags = JSON.parse(selected.metadata_tags || '[]') } catch { tags = [] }
  }

  return (
    <div className="studio-layout">
      <div className="studio-list">
        <div className="studio-list-header">
          <span style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: 2, color: 'var(--amber)' }}>Scripts</span>
          <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>{scripts.length}</span>
        </div>

        <div style={{ marginBottom: 12 }}>
          <select
            className="setting-input"
            value={contentId}
            onChange={e => setContentId(e.target.value)}
            style={{ fontSize: 11, marginBottom: 6 }}
          >
            <option value="">Generate from scratch</option>
            {approvedContent.map(c => (
              <option key={c.id} value={c.id}>[{c.channel}] {c.headline?.slice(0, 50)}</option>
            ))}
          </select>
          <button
            className={`btn btn-run ${generating ? 'loading' : ''}`}
            onClick={generate}
            disabled={generating}
            style={{ width: '100%', fontSize: 10 }}
          >
            {generating ? 'Generating...' : 'Generate Script'}
          </button>
        </div>

        {scripts.map(s => (
          <div
            key={s.id}
            className={`studio-script-item ${selected?.id === s.id ? 'active' : ''}`}
            onClick={() => setSelected(s)}
          >
            <div className="studio-script-title">{s.title || 'Untitled'}</div>
            <div className="studio-script-meta">
              {s.status} &middot; {s.created_at ? new Date(s.created_at).toLocaleDateString() : ''}
            </div>
          </div>
        ))}

        {scripts.length === 0 && !generating && (
          <div style={{ color: 'var(--text-dim)', fontSize: 11, padding: '12px 0' }}>
            No scripts yet. Generate one from content or scratch.
          </div>
        )}
      </div>

      <div className="studio-detail">
        {!selected && (
          <div style={{ color: 'var(--text-dim)', padding: 40, textAlign: 'center' }}>
            Select a script or generate a new one.
          </div>
        )}

        {selected && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: 20 }}>
              <h2 style={{ fontFamily: 'var(--font-headline)', color: 'var(--amber)', fontSize: 22 }}>{selected.title}</h2>
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="btn btn-run" onClick={() => exportPackage(selected.id)} style={{ fontSize: 10 }}>
                  Export Remotion
                </button>
                <button
                  className={`btn btn-approve ${uploading ? 'loading' : ''}`}
                  onClick={() => uploadVideo(selected.id)}
                  disabled={uploading}
                  style={{ fontSize: 10 }}
                >
                  {uploading ? 'Uploading...' : 'Upload to YouTube'}
                </button>
              </div>
              {uploadResult && (
                <div style={{ fontSize: 11, marginTop: 8, padding: '6px 10px', border: '1px solid var(--border)', background: 'var(--bg-panel)' }}>
                  {uploadResult.error ? (
                    <span style={{ color: 'var(--red)' }}>Upload failed: {uploadResult.error}</span>
                  ) : (
                    <span style={{ color: 'var(--green)' }}>
                      Uploaded ({uploadResult.privacy}) — <a href={uploadResult.youtube_url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--amber)' }}>{uploadResult.youtube_url}</a>
                    </span>
                  )}
                </div>
              )}
            </div>

            {selected.hook && (
              <div className="studio-section">
                <div className="studio-section-label">Hook — you have 15 seconds</div>
                <div className="studio-hook">{selected.hook}</div>
              </div>
            )}

            {sections.length > 0 && (
              <div className="studio-section">
                <div className="studio-section-label">Sections</div>
                {sections.map((s, i) => (
                  <div key={i} className="studio-section-card">
                    <div className="studio-section-heading">{s.heading}</div>
                    <div className="studio-section-duration">{s.duration_seconds ? `${s.duration_seconds}s` : ''}</div>
                    {s.talking_points && (
                      <div className="studio-section-points">
                        {(Array.isArray(s.talking_points) ? s.talking_points : [s.talking_points]).map((tp, j) => (
                          <div key={j}>• {tp}</div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            {selected.cta && (
              <div className="studio-section">
                <div className="studio-section-label">Call to Action</div>
                <div style={{ color: 'var(--text)', fontSize: 13 }}>{selected.cta}</div>
              </div>
            )}

            {lowerThirds.length > 0 && (
              <div className="studio-section">
                <div className="studio-section-label">Lower Thirds</div>
                {lowerThirds.map((lt, i) => (
                  <div key={i} className="studio-lower-third">
                    <span className="studio-lower-third-time">At {formatSeconds(lt.at_second || 0)}</span>
                    {' — '}{lt.name} | {lt.title} | {lt.company}
                  </div>
                ))}
              </div>
            )}

            <div className="studio-section">
              <div className="studio-section-label">YouTube Metadata</div>
              <div className="studio-meta-field">
                <span className="studio-meta-label">Title</span>
                <div className="studio-meta-value">{selected.metadata_title || '—'}</div>
              </div>
              <div className="studio-meta-field">
                <span className="studio-meta-label">Description</span>
                <div className="studio-meta-value" style={{ whiteSpace: 'pre-wrap' }}>{selected.metadata_description || '—'}</div>
              </div>
              {tags.length > 0 && (
                <div className="studio-meta-field">
                  <span className="studio-meta-label">Tags</span>
                  <div>{tags.map((t, i) => <span key={i} className="studio-tag">{t}</span>)}</div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
