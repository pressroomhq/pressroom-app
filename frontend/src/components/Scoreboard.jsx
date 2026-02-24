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

  useEffect(() => {
    setLoading(true)
    fetch(`${API}/scoreboard`)
      .then(r => r.json())
      .then(d => { setData(Array.isArray(d) ? d : []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  return (
    <div className="settings-page">
      <div className="settings-header">
        <h2 className="settings-title">Portfolio Scoreboard</h2>
      </div>

      {loading && <div style={{ color: 'var(--text-dim)', padding: 20 }}>Loading scoreboard...</div>}

      {!loading && data.length === 0 && (
        <div style={{ color: 'var(--text-dim)', padding: 20 }}>No companies found. Add companies to see the scoreboard.</div>
      )}

      {!loading && data.length > 0 && (
        <table className="scoreboard-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Domain</th>
              <th>SEO Score</th>
              <th>AI Citability</th>
              <th>Signals (7d)</th>
              <th>Published</th>
              <th>Last Active</th>
            </tr>
          </thead>
          <tbody>
            {data.map(row => (
              <tr key={row.org_id} onClick={() => onSwitchOrg?.({ id: row.org_id, name: row.org_name, domain: row.domain })}>
                <td style={{ color: 'var(--text-bright)', fontWeight: 500 }}>{row.org_name}</td>
                <td style={{ color: 'var(--text-dim)' }}>{row.domain || '—'}</td>
                <td className={scoreClass(row.seo_score)}>{row.seo_score ?? '—'}</td>
                <td className={
                  row.ai_citability === 'Yes' ? 'citability-yes' :
                  row.ai_citability === 'No' ? 'citability-no' : 'citability-unknown'
                }>
                  {row.ai_citability === 'Unknown' ? '—' : row.ai_citability}
                </td>
                <td>{row.signals_count}</td>
                <td>{row.content_published}{row.content_this_week > 0 && <span style={{ color: 'var(--green)', marginLeft: 4 }}>+{row.content_this_week}</span>}</td>
                <td style={{ color: 'var(--text-dim)' }}>{timeAgo(row.last_active)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
