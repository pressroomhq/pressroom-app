import { useState, useEffect } from 'react'
import { orgHeaders } from '../api'

const API = '/api'

export default function Usage({ orgId }) {
  const [usage, setUsage] = useState(null)
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!orgId) return
    setLoading(true)
    Promise.all([
      fetch(`${API}/usage`, { headers: orgHeaders(orgId) }).then(r => r.json()),
      fetch(`${API}/usage/history`, { headers: orgHeaders(orgId) }).then(r => r.json()),
    ]).then(([u, h]) => {
      setUsage(u)
      setHistory(h.days || [])
    }).catch(() => {}).finally(() => setLoading(false))
  }, [orgId])

  if (loading) return <div className="panel"><div className="panel-header">Usage</div><div style={{ padding: 20, color: '#888' }}>Loading...</div></div>

  const maxCost = Math.max(...(history.map(d => d.cost_usd) || [0]), 0.001)

  return (
    <div className="panel" style={{ overflow: 'auto' }}>
      <div className="panel-header">
        <span>Token Usage</span>
      </div>
      <div style={{ padding: 20 }}>
        {/* Summary cards */}
        <div style={{ display: 'flex', gap: 20, marginBottom: 30 }}>
          <div style={{ flex: 1, background: '#1a1a1a', border: '1px solid #333', padding: 20, borderRadius: 4 }}>
            <div style={{ color: '#888', fontSize: 12, letterSpacing: 2, marginBottom: 8 }}>TOTAL COST</div>
            <div style={{ color: '#ffb000', fontSize: 32, fontWeight: 700 }}>${usage?.total_cost_usd?.toFixed(4) || '0.00'}</div>
          </div>
          <div style={{ flex: 1, background: '#1a1a1a', border: '1px solid #333', padding: 20, borderRadius: 4 }}>
            <div style={{ color: '#888', fontSize: 12, letterSpacing: 2, marginBottom: 8 }}>API CALLS</div>
            <div style={{ color: '#fff', fontSize: 32, fontWeight: 700 }}>{usage?.total_calls || 0}</div>
          </div>
          <div style={{ flex: 1, background: '#1a1a1a', border: '1px solid #333', padding: 20, borderRadius: 4 }}>
            <div style={{ color: '#888', fontSize: 12, letterSpacing: 2, marginBottom: 8 }}>TOKENS IN</div>
            <div style={{ color: '#fff', fontSize: 32, fontWeight: 700 }}>{(usage?.total_tokens_in || 0).toLocaleString()}</div>
          </div>
          <div style={{ flex: 1, background: '#1a1a1a', border: '1px solid #333', padding: 20, borderRadius: 4 }}>
            <div style={{ color: '#888', fontSize: 12, letterSpacing: 2, marginBottom: 8 }}>TOKENS OUT</div>
            <div style={{ color: '#fff', fontSize: 32, fontWeight: 700 }}>{(usage?.total_tokens_out || 0).toLocaleString()}</div>
          </div>
        </div>

        {/* Per-operation table */}
        {usage?.by_operation?.length > 0 && (
          <div style={{ marginBottom: 30 }}>
            <div style={{ color: '#ffb000', fontSize: 14, letterSpacing: 2, marginBottom: 12 }}>BY OPERATION</div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #333' }}>
                  <th style={{ textAlign: 'left', padding: '8px 12px', color: '#888' }}>OPERATION</th>
                  <th style={{ textAlign: 'right', padding: '8px 12px', color: '#888' }}>CALLS</th>
                  <th style={{ textAlign: 'right', padding: '8px 12px', color: '#888' }}>TOKENS IN</th>
                  <th style={{ textAlign: 'right', padding: '8px 12px', color: '#888' }}>TOKENS OUT</th>
                  <th style={{ textAlign: 'right', padding: '8px 12px', color: '#888' }}>COST</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_operation.map((op, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #222' }}>
                    <td style={{ padding: '8px 12px', color: '#ccc', fontFamily: 'monospace' }}>{op.operation}</td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', color: '#fff' }}>{op.calls}</td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', color: '#aaa' }}>{op.tokens_in.toLocaleString()}</td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', color: '#aaa' }}>{op.tokens_out.toLocaleString()}</td>
                    <td style={{ textAlign: 'right', padding: '8px 12px', color: '#ffb000' }}>${op.cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Daily cost chart */}
        {history.length > 0 && (
          <div>
            <div style={{ color: '#ffb000', fontSize: 14, letterSpacing: 2, marginBottom: 12 }}>DAILY COST (30 DAYS)</div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 120 }}>
              {history.map((d, i) => (
                <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <div
                    style={{
                      width: '100%',
                      height: `${(d.cost_usd / maxCost) * 100}px`,
                      background: '#ffb000',
                      borderRadius: '2px 2px 0 0',
                      minHeight: 2,
                    }}
                    title={`${d.date}: $${d.cost_usd.toFixed(4)} (${d.calls} calls)`}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {!usage?.total_calls && (
          <div style={{ color: '#666', textAlign: 'center', padding: 40 }}>
            No token usage recorded yet. Usage tracking is active — data will appear after API calls.
          </div>
        )}
      </div>
    </div>
  )
}
