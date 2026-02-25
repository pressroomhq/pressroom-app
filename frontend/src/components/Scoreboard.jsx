import React, { useState, useEffect } from 'react'

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

// ── Per-row team activity panel ───────────────────────────────────────────
function TeamActivityPanel({ orgId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch(`${API}/scoreboard/${orgId}/team-activity`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false) } })
      .catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [orgId])

  if (loading) return <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>loading...</span>
  if (!data) return <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>no data</span>

  const members = data.members || []
  if (members.length === 0) return <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>no team members</span>

  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      {members.map(m => (
        <div key={m.member_id} style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '6px 10px', border: '1px solid var(--border)', background: 'var(--bg)',
          minWidth: 180,
        }}>
          <div style={{
            width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
            background: 'var(--border)', overflow: 'hidden',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 12, color: 'var(--text-dim)',
          }}>
            {m.photo_url
              ? <img src={m.photo_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              : m.name?.charAt(0)?.toUpperCase()}
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text)' }}>{m.name}</div>
            <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>{m.title}</div>
            <div style={{ display: 'flex', gap: 8, marginTop: 2 }}>
              {m.published_total > 0
                ? <span style={{ fontSize: 10, color: 'var(--green, #4caf50)', fontFamily: 'var(--font-mono)' }}>
                    {m.published_total} pub{m.published_week > 0 ? ` (+${m.published_week} wk)` : ''}
                  </span>
                : <span style={{ fontSize: 10, color: 'var(--text-dim)' }}>0 published</span>
              }
              {m.queued > 0 && <span style={{ fontSize: 10, color: 'var(--amber, #ffb000)', fontFamily: 'var(--font-mono)' }}>{m.queued} queued</span>}
              {m.approved > 0 && <span style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>{m.approved} ready</span>}
            </div>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
            {m.linkedin_connected && <span style={{ fontSize: 9, color: 'var(--green, #4caf50)' }}>LI</span>}
            {m.github_username && <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>GH</span>}
          </div>
        </div>
      ))}
      {data.company_published > 0 && (
        <div style={{ fontSize: 10, color: 'var(--text-dim)', alignSelf: 'center' }}>
          +{data.company_published} company posts
        </div>
      )}
    </div>
  )
}


// ── Per-row GSC summary panel ──────────────────────────────────────────────
function GscRowPanel({ orgId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch(`${API}/gsc/summary`, { headers: { 'X-Org-Id': String(orgId) } })
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false) } })
      .catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [orgId])

  if (loading) return <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>loading...</span>
  if (!data?.connected) return <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>not connected</span>
  if (data.error) return <span style={{ color: 'var(--red)', fontSize: 10 }}>{data.error}</span>

  const t = data.totals || {}
  return (
    <div style={{ display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', gap: 12 }}>
        {[
          { label: 'Clicks', value: t.clicks?.toLocaleString() },
          { label: 'Impr', value: t.impressions?.toLocaleString() },
          { label: 'CTR', value: `${t.ctr}%` },
          { label: 'Pos', value: t.position },
        ].map(s => (
          <div key={s.label} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', fontFamily: 'var(--font-mono)' }}>{s.value ?? '—'}</div>
            <div style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1 }}>{s.label}</div>
          </div>
        ))}
      </div>
      {data.top_queries?.length > 0 && (
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 2 }}>Top Queries</div>
          {data.top_queries.slice(0, 3).map((q, i) => (
            <div key={i} style={{ fontSize: 10, color: 'var(--text)', display: 'flex', gap: 8 }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160 }}>{q.key}</span>
              <span style={{ color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>{q.clicks} clk · pos {q.position}</span>
            </div>
          ))}
        </div>
      )}
      <div style={{ fontSize: 9, color: 'var(--text-dim)', alignSelf: 'flex-end', marginLeft: 'auto' }}>
        {data.period_days}d · {data.property?.replace(/^https?:\/\//, '')}
      </div>
    </div>
  )
}

export default function Scoreboard({ orgId, onSwitchOrg }) {
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(true)
  const [scanningAll, setScanningAll] = useState(false)
  const [scanningRow, setScanningRow] = useState(null)
  const [scanMsg, setScanMsg] = useState('')
  const [expandedGsc, setExpandedGsc] = useState(null)
  const [expandedTeam, setExpandedTeam] = useState(null)

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
                <th>GSC</th>
                <th>Team</th>
                <th>Signals (7d)</th>
                <th>Published</th>
                <th>Last Active</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.map(row => (
                <React.Fragment key={row.org_id}>
                  <tr onClick={() => onSwitchOrg?.({ id: row.org_id, name: row.org_name, domain: row.domain })}>
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
                    <td onClick={e => e.stopPropagation()}>
                      {row.gsc_connected ? (
                        <button
                          onClick={() => setExpandedGsc(expandedGsc === row.org_id ? null : row.org_id)}
                          style={{
                            background: 'transparent',
                            border: 'none',
                            color: expandedGsc === row.org_id ? 'var(--green)' : 'var(--text-dim)',
                            fontFamily: 'inherit',
                            fontSize: '10px',
                            cursor: 'pointer',
                            padding: '2px 4px',
                            letterSpacing: '0.05em',
                          }}
                          title="Show GSC data"
                        >
                          {expandedGsc === row.org_id ? '▼ GSC' : '▶ GSC'}
                        </button>
                      ) : (
                        <span style={{ color: 'var(--text-dim)', fontSize: '10px' }}>—</span>
                      )}
                    </td>
                    <td onClick={e => e.stopPropagation()}>
                      <button
                        onClick={() => setExpandedTeam(expandedTeam === row.org_id ? null : row.org_id)}
                        style={{
                          background: 'transparent', border: 'none',
                          color: expandedTeam === row.org_id ? 'var(--green)' : 'var(--text-dim)',
                          fontFamily: 'inherit', fontSize: '10px', cursor: 'pointer',
                          padding: '2px 4px', letterSpacing: '0.05em',
                        }}
                      >
                        {expandedTeam === row.org_id ? '▼ TEAM' : '▶ TEAM'}
                      </button>
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
                  {expandedGsc === row.org_id && (
                    <tr>
                      <td colSpan={12} style={{ background: 'var(--bg-panel)', padding: '8px 16px', borderBottom: '1px solid var(--border)' }}>
                        <GscRowPanel orgId={row.org_id} />
                      </td>
                    </tr>
                  )}
                  {expandedTeam === row.org_id && (
                    <tr>
                      <td colSpan={12} style={{ background: 'var(--bg-panel)', padding: '10px 16px', borderBottom: '1px solid var(--border)' }}>
                        <TeamActivityPanel orgId={row.org_id} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
