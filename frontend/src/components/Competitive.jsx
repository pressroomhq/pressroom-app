import { useState, useEffect } from 'react'

const API = '/api'

function scoreColor(score) {
  if (score >= 80) return '#33ff33'
  if (score >= 60) return '#ffb000'
  return '#ff4444'
}

export default function Competitive({ orgId }) {
  const [competitors, setCompetitors] = useState([])
  const [urls, setUrls] = useState('')
  const [scanning, setScanning] = useState(false)
  const [suggesting, setSuggesting] = useState(false)

  useEffect(() => {
    if (!orgId) return
    // Clear stale state from previous org immediately
    setCompetitors([])
    setUrls('')
    setSuggesting(false)

    fetch(`${API}/competitive/${orgId}`, { headers: { 'X-Org-Id': orgId } })
      .then(r => r.json())
      .then(d => {
        const existing = d.competitors || []
        setCompetitors(existing)
        // Pre-fill textarea with known competitor URLs
        if (existing.length > 0) {
          setUrls(existing.map(c => c.url).join('\n'))
        } else {
          // No history — auto-suggest
          suggestCompetitors()
        }
      })
      .catch(() => {})
  }, [orgId])

  const suggestCompetitors = async () => {
    if (suggesting) return
    setSuggesting(true)
    try {
      const res = await fetch(`${API}/competitive/suggest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Org-Id': orgId },
      })
      const data = await res.json()
      if (data.urls?.length) setUrls(data.urls.join('\n'))
    } catch { /* ignore */ }
    setSuggesting(false)
  }

  const scan = async () => {
    setScanning(true)
    try {
      const competitor_urls = urls.split('\n').map(u => u.trim()).filter(Boolean)
      const res = await fetch(`${API}/competitive/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Org-Id': orgId },
        body: JSON.stringify({ competitor_urls }),
      })
      const data = await res.json()
      setCompetitors(data.competitors || [])
    } catch (e) {
      console.error('Scan failed:', e)
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="panel" style={{ overflow: 'auto' }}>
      <div className="panel-header">
        <span>Competitive Intelligence</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-sm" onClick={suggestCompetitors} disabled={suggesting} style={{ color: '#ffb000', borderColor: '#ffb000' }}>
            {suggesting ? 'THINKING...' : 'SUGGEST'}
          </button>
          <button className="btn btn-sm" onClick={scan} disabled={scanning || !urls.trim()}>
            {scanning ? 'SCANNING...' : 'SCAN COMPETITORS'}
          </button>
        </div>
      </div>
      <div style={{ padding: 20 }}>
        {/* Competitor URLs input */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ color: '#888', fontSize: 12, letterSpacing: 2, marginBottom: 8 }}>
            COMPETITOR URLS (one per line)
            {suggesting && <span style={{ color: '#ffb000', marginLeft: 10 }}>generating suggestions...</span>}
          </div>
          <textarea
            value={urls}
            onChange={e => setUrls(e.target.value)}
            placeholder={suggesting ? 'Generating suggestions...' : 'https://competitor.com'}
            style={{
              width: '100%', minHeight: 80, background: '#111', border: '1px solid #333',
              color: '#ccc', padding: 10, fontFamily: 'monospace', fontSize: 13, resize: 'vertical',
            }}
          />
        </div>

        {/* Results table */}
        {competitors.length > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #333' }}>
                <th style={{ textAlign: 'left', padding: '10px 12px', color: '#ffb000', letterSpacing: 2 }}>COMPANY</th>
                <th style={{ textAlign: 'center', padding: '10px 12px', color: '#ffb000', letterSpacing: 2 }}>SEO SCORE</th>
                <th style={{ textAlign: 'center', padding: '10px 12px', color: '#ffb000', letterSpacing: 2 }}>AI CITABILITY</th>
                <th style={{ textAlign: 'left', padding: '10px 12px', color: '#ffb000', letterSpacing: 2 }}>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {competitors.map((c, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #222' }}>
                  <td style={{ padding: '12px', color: '#fff' }}>
                    <div style={{ fontWeight: 600 }}>{c.name}</div>
                    <div style={{ color: '#666', fontSize: 12 }}>{c.url}</div>
                  </td>
                  <td style={{ textAlign: 'center', padding: '12px' }}>
                    <span style={{ color: scoreColor(c.score), fontSize: 24, fontWeight: 700 }}>
                      {c.score || '--'}
                    </span>
                  </td>
                  <td style={{ textAlign: 'center', padding: '12px' }}>
                    <span style={{ color: c.ai_citability ? '#33ff33' : '#ff4444', fontWeight: 600 }}>
                      {c.ai_citability ? 'YES' : 'NO'}
                    </span>
                  </td>
                  <td style={{ padding: '12px', color: '#888' }}>
                    {c.error ? <span style={{ color: '#ff4444' }}>{c.error}</span> : (c.scanned_at || 'Scanned')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {competitors.length === 0 && !scanning && !suggesting && !urls.trim() && (
          <div style={{ color: '#666', textAlign: 'center', padding: 40 }}>
            Hit SUGGEST to auto-detect competitors, or paste URLs above and SCAN.
          </div>
        )}
      </div>
    </div>
  )
}
