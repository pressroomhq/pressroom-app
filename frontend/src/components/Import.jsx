import { useState, useEffect, useCallback, useRef } from 'react'

const API = '/api'

function orgHeaders(orgId) {
  const h = { 'Content-Type': 'application/json' }
  if (orgId) h['X-Org-Id'] = String(orgId)
  return h
}

const TARGETS = [
  {
    id: 'signals',
    label: 'Signals',
    desc: 'Import wire signals — articles, releases, trends. Feeds the scout.',
    formats: ['json', 'csv'],
  },
  {
    id: 'content',
    label: 'Content History',
    desc: 'Import past content as approved examples. Trains the voice flywheel.',
    formats: ['json', 'csv'],
  },
  {
    id: 'voice_examples',
    label: 'Voice Samples',
    desc: 'Paste writing samples. The engine learns your voice from these.',
    formats: ['text'],
  },
  {
    id: 'support_tickets',
    label: 'Support Tickets',
    desc: 'Import Intercom / support tickets as signals. Accepts DreamFactory JSON export format.',
    formats: ['json'],
  },
]

export default function Import({ onLog, orgId }) {
  const [target, setTarget] = useState('signals')
  const [format, setFormat] = useState('json')
  const [pasteData, setPasteData] = useState('')
  const [templates, setTemplates] = useState({})
  const [importing, setImporting] = useState(false)
  const [lastResult, setLastResult] = useState(null)
  const fileRef = useRef(null)

  const loadTemplates = useCallback(async () => {
    try {
      const res = await fetch(`${API}/import/templates`)
      setTemplates(await res.json())
    } catch (e) {
      // silent
    }
  }, [])

  useEffect(() => { loadTemplates() }, [loadTemplates])

  // When target changes, update format to first available
  useEffect(() => {
    const t = TARGETS.find(t => t.id === target)
    if (t && !t.formats.includes(format)) {
      setFormat(t.formats[0])
    }
  }, [target, format])

  const currentTarget = TARGETS.find(t => t.id === target)
  const template = templates[target]

  const loadTemplate = () => {
    if (template?.example) {
      setPasteData(template.example)
    }
  }

  const importPaste = async () => {
    if (!pasteData.trim()) return
    setImporting(true)
    setLastResult(null)
    onLog?.(`IMPORT — ${target} (${format})...`, 'action')
    try {
      const res = await fetch(`${API}/import/paste`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({ target, format, data: pasteData }),
      })
      const data = await res.json()
      setLastResult(data)
      if (data.error) {
        onLog?.(`IMPORT FAILED — ${data.error}`, 'error')
      } else {
        onLog?.(`IMPORT COMPLETE — ${data.imported} ${target} imported`, 'success')
        setPasteData('')
      }
    } catch (e) {
      onLog?.(`IMPORT ERROR — ${e.message}`, 'error')
      setLastResult({ error: e.message })
    } finally {
      setImporting(false)
    }
  }

  const importFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setLastResult(null)
    onLog?.(`IMPORT FILE — ${file.name} → ${target}...`, 'action')
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('target', target)
      const res = await fetch(`${API}/import/file`, {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()
      setLastResult(data)
      if (data.error) {
        onLog?.(`IMPORT FAILED — ${data.error}`, 'error')
      } else {
        onLog?.(`IMPORT COMPLETE — ${data.imported} ${target} imported from ${file.name}`, 'success')
      }
    } catch (e) {
      onLog?.(`IMPORT ERROR — ${e.message}`, 'error')
      setLastResult({ error: e.message })
    } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2 className="settings-title">Import Data</h2>
      </div>

      {/* TARGET SELECTOR */}
      <div className="settings-section">
        <div className="section-label">Manual Import</div>
        <div className="import-targets">
          {TARGETS.map(t => (
            <button
              key={t.id}
              className={`import-target ${target === t.id ? 'active' : ''}`}
              onClick={() => setTarget(t.id)}
            >
              <div className="import-target-label">{t.label}</div>
              <div className="import-target-desc">{t.desc}</div>
            </button>
          ))}
        </div>
      </div>

      {/* FORMAT + TEMPLATE */}
      <div className="settings-section">
        <div className="section-label">Format</div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
          {currentTarget?.formats.map(f => (
            <button
              key={f}
              className={`btn ${format === f ? 'btn-run' : ''}`}
              style={format !== f ? { color: 'var(--text-dim)', borderColor: 'var(--border)' } : {}}
              onClick={() => setFormat(f)}
            >
              {f.toUpperCase()}
            </button>
          ))}
          {template && (
            <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)', marginLeft: 'auto' }} onClick={loadTemplate}>
              Load Template
            </button>
          )}
        </div>
        {template?.fields && (
          <div className="import-fields-hint">
            Fields: {template.fields.join(', ')}
            {template.required && <span style={{ color: 'var(--amber)' }}> (required: {template.required.join(', ')})</span>}
          </div>
        )}
      </div>

      {/* PASTE AREA */}
      <div className="settings-section">
        <div className="section-label">Paste Data</div>
        <textarea
          className="setting-input import-textarea"
          value={pasteData}
          onChange={e => setPasteData(e.target.value)}
          placeholder={format === 'text'
            ? 'Paste your writing samples here...\n\nSeparate examples with blank lines.'
            : format === 'csv'
            ? 'type,source,title,body\nrss,techcrunch.com,Article Title,Body text...'
            : '[\n  {"type": "rss", "source": "example.com", "title": "..."}\n]'
          }
          rows={12}
          spellCheck={false}
        />
      </div>

      {/* ACTIONS */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16 }}>
        <button
          className={`btn btn-approve ${importing ? 'loading' : ''}`}
          onClick={importPaste}
          disabled={importing || !pasteData.trim()}
        >
          {importing ? 'Importing...' : 'Import Pasted Data'}
        </button>
        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>or</span>
        <label className="btn btn-run" style={{ cursor: 'pointer' }}>
          Upload File
          <input
            ref={fileRef}
            type="file"
            accept=".json,.csv,.txt"
            onChange={importFile}
            style={{ display: 'none' }}
          />
        </label>
        {lastResult && !lastResult.error && (
          <span style={{ color: 'var(--green)', fontSize: 12, marginLeft: 'auto' }}>
            {lastResult.imported} records imported
          </span>
        )}
        {lastResult?.error && (
          <span style={{ color: 'var(--red)', fontSize: 12, marginLeft: 'auto' }}>
            {lastResult.error}
          </span>
        )}
      </div>
    </div>
  )
}
