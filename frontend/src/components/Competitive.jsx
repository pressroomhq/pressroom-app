import { useState, useEffect } from 'react'

const API = '/api'

const DEFAULT_COMPETITORS = [
  'https://apigee.com',
  'https://konghq.com',
  'https://tyk.io',
]

function scoreColor(score) {
  if (score >= 80) return '#33ff33'
  if (score >= 60) return '#ffb000'
  return '#ff4444'
}

export default function Competitive({ orgId }) {
  const [competitors, setCompetitors] = useState([])
  const [urls, setUrls] = useState(DEFAULT_COMPETITORS.join('\n'))
  const [scanning, setScanning] = useState(false)
  const [orgScore, setOrgScore] = useState(null)

  useEffect(() => {
    if (!orgId) return
    fetch(`${API}/competitive/${orgId}`, { headers: { 'X-Org-Id': orgId } })
      .then(r => r.json())
      .then(d => setCompetitors(d.competitors || []))
      .catch(() => {})
  }, [orgId])

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
        <button className="btn btn-sm" onClick={scan} disabled={scanning}>
          {scanning ? 'SCANNING...' : 'SCAN COMPETITORS'}
        </button>
      </div>
      <div style={{ padding: 20 }}>
        {/* Competitor URLs input */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ color: '#888', fontSize: 12, letterSpacing: 2, marginBottom: 8 }}>COMPETITOR URLS (one per line)</div>
          <textarea
            value={urls}
            onChange={e => setUrls(e.target.value)}
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
                    <span style={{
                      color: c.ai_citability ? '#33ff33' : '#ff4444',
                      fontWeight: 600,
                    }}>
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

        {competitors.length === 0 && !scanning && (
          <div style={{ color: '#666', textAlign: 'center', padding: 40 }}>
            No competitive data yet. Add competitor URLs and hit SCAN COMPETITORS.
          </div>
        )}
      </div>
    </div>
  )
}
