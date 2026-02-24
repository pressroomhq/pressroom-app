import { useState, useEffect } from 'react'

const API = '/api'

function timeAgo(dateStr) {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now - d) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function scoreClass(score) {
  if (score === null || score === undefined) return 'score-amber'
  if (score >= 80) return 'score-green'
  if (score >= 60) return 'score-amber'
  return 'score-red'
}

export default function Scoreboard({ orgId, onSwitchOrg }) {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [scanningAll, setScanningAll] = useState(false)
  const [scanningRow, setScanningRow] = useState(null)
  const [scanMsg, setScanMsg] = useState('')

  const fetchScoreboard = () => {
    setLoading(true)
    fetch(`${API}/scoreboard`)
      .then(r => r.json())
      .then(d => { setData(Array.isArray(d) ? d : []); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => { fetchScoreboard() }, [])

  const handleScanAll = async () => {
    setScanningAll(true)
    setScanMsg('SCANNING ALL...')
    try {
      const res = await fetch(`${API}/audit/scan-all`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ deep: true }),
      })
      const result = await res.json()
      const ok = result.results?.filter(r => r.status === 'ok').length ?? 0
      const skip = result.results?.filter(r => r.status === 'skipped').length ?? 0
      const err = result.results?.filter(r => r.status === 'error').length ?? 0
      setScanMsg(`COMPLETE — ${ok} scanned, ${skip} skipped${err > 0 ? `, ${err} errors` : ''}`)
      fetchScoreboard()
    } catch (e) {
      setScanMsg(`SCAN FAILED — ${e.message}`)
    } finally {
      setScanningAll(false)
      setTimeout(() => setScanMsg(''), 8000)
    }
  }

  const handleScanRow = async (e, row) => {
    e.stopPropagation()
    setScanningRow(row.org_id)
    try {
      const res = await fetch(`${API}/audit/seo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Org-Id': String(row.org_id) },
        body: JSON.stringify({ domain: row.domain, max_pages: 15 }),
      })
      const result = await res.json()
      if (result.error) throw new Error(result.error)
      fetchScoreboard()
    } catch (e) {
      setScanMsg(`SCAN FAILED (${row.org_name}) — ${e.message}`)
      setTimeout(() => setScanMsg(''), 6000)
    } finally {
      setScanningRow(null)
    }
  }

  return (
    <div className="settings-page">
      <div className="settings-header" style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <h2 className="settings-title">Portfolio Scoreboard</h2>
        <button
          onClick={handleScanAll}
          disabled={scanningAll}
          style={{
            background: 'transparent',
            border: '1px solid var(--amber, #ffb000)',
            color: 'var(--amber, #ffb000)',
            fontFamily: 'inherit',
            fontSize: '11px',
            padding: '4px 12px',
            cursor: scanningAll ? 'not-allowed' : 'pointer',
            opacity: scanningAll ? 0.5 : 1,
            letterSpacing: '0.05em',
          }}
          onMouseEnter={e => { if (!scanningAll) { e.target.style.background = 'var(--amber, #ffb000)'; e.target.style.color = '#0a0a0a' } }}
          onMouseLeave={e => { e.target.style.background = 'transparent'; e.target.style.color = 'var(--amber, #ffb000)' }}
        >
          {scanningAll ? 'SCANNING...' : 'SCAN ALL'}
        </button>
        {scanMsg && (
          <span style={{ color: 'var(--text-dim, #555)', fontSize: '11px' }}>{scanMsg}</span>
        )}
      </div>

      {loading && <div style={{ color: 'var(--text-dim)', padding: 20 }}>LOADING...</div>}

      {!loading && data.length === 0 && (
        <div style={{ color: 'var(--text-dim)', padding: 20 }}>No companies found. Add companies to see the scoreboard.</div>
      )}

      {!loading && data.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className="scoreboard-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Domain</th>
                <th>SEO Score</th>
                <th>AI Citability</th>
                <th>Issues</th>
                <th>Top Gap</th>
                <th>Signals (7d)</th>
                <th>Published</th>
                <th>Last Active</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.map(row => (
                <tr key={row.org_id} onClick={() => onSwitchOrg?.({ id: row.org_id, name: row.org_name, domain: row.domain })}>
                  <td style={{ color: 'var(--text-bright)', fontWeight: 500 }}>{row.org_name}</td>
                  <td style={{ color: 'var(--text-dim)' }}>{row.domain || '—'}</td>
                  <td>
                    <span className={scoreClass(row.seo_score)}>{row.seo_score ?? '—'}</span>
                    {row.latest_audit_id && (
                      <a
                        href={`/api/audit/history/${row.latest_audit_id}/export`}
                        target="_blank"
                        rel="noreferrer"
                        onClick={e => e.stopPropagation()}
                        style={{ marginLeft: 8, color: 'var(--text-dim, #555)', fontSize: '10px', textDecoration: 'none' }}
                        onMouseEnter={e => { e.target.style.color = 'var(--amber, #ffb000)' }}
                        onMouseLeave={e => { e.target.style.color = 'var(--text-dim, #555)' }}
                      >
                        EXPORT
                      </a>
                    )}
                  </td>
                  <td className={
                    row.ai_citability === 'Yes' ? 'citability-yes' :
                    row.ai_citability === 'No' ? 'citability-no' : 'citability-unknown'
                  }>
                    {row.ai_citability === 'Unknown' ? '—' : row.ai_citability}
                  </td>
                  <td>
                    {row.p0_count === 0 && row.p1_count === 0 ? (
                      <span style={{ color: '#336633', fontSize: '11px' }}>CLEAN</span>
                    ) : (
                      <span>
                        {row.p0_count > 0 && <span style={{ color: '#cc3333', fontSize: '11px' }}>{row.p0_count}P0</span>}
                        {row.p0_count > 0 && row.p1_count > 0 && <span style={{ color: 'var(--text-dim)', fontSize: '11px' }}> </span>}
                        {row.p1_count > 0 && <span style={{ color: '#ffb000', fontSize: '11px' }}>{row.p1_count}P1</span>}
                      </span>
                    )}
                  </td>
                  <td style={{ color: 'var(--text-dim)', fontSize: '11px', maxWidth: 200 }}>
                    {row.top_opportunity
                      ? row.top_opportunity.length > 50
                        ? row.top_opportunity.slice(0, 50) + '…'
                        : row.top_opportunity
                      : '—'}
                  </td>
                  <td>{row.signals_count}</td>
                  <td>
                    {row.content_published}
                    {row.content_this_week > 0 && (
                      <span style={{ color: 'var(--green)', marginLeft: 4 }}>+{row.content_this_week}</span>
                    )}
                  </td>
                  <td style={{ color: 'var(--text-dim)' }}>{timeAgo(row.last_active)}</td>
                  <td onClick={e => e.stopPropagation()}>
                    {row.domain ? (
                      <button
                        onClick={e => handleScanRow(e, row)}
                        disabled={scanningRow === row.org_id || scanningAll}
                        style={{
                          background: 'transparent',
                          border: '1px solid var(--border)',
                          color: scanningRow === row.org_id ? 'var(--amber)' : 'var(--text-dim)',
                          fontFamily: 'inherit',
                          fontSize: '10px',
                          padding: '2px 8px',
                          cursor: (scanningRow === row.org_id || scanningAll) ? 'not-allowed' : 'pointer',
                          letterSpacing: '0.05em',
                          whiteSpace: 'nowrap',
                        }}
                        onMouseEnter={e => { if (scanningRow !== row.org_id) e.target.style.borderColor = 'var(--amber)' }}
                        onMouseLeave={e => { e.target.style.borderColor = 'var(--border)' }}
                      >
                        {scanningRow === row.org_id ? 'SCANNING...' : 'SCAN'}
                      </button>
                    ) : (
                      <span style={{ color: 'var(--text-dim)', fontSize: '10px' }}>NO DOMAIN</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
