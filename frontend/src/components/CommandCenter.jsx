import { useState, useEffect } from 'react'
import { cachedFetch } from '../api'

const API = '/api'

function ScoreRing({ score, label }) {
  const color = score >= 80 ? 'var(--green)' : score >= 50 ? 'var(--amber)' : 'var(--red)'
  return (
    <div className="cc-score-ring" style={{ borderColor: color }}>
      <span className="cc-score-number" style={{ color }}>{score}</span>
      <span className="cc-score-label">{label || 'SEO'}</span>
    </div>
  )
}

function StatusCard({ label, value, sub, color, onClick }) {
  return (
    <div className="cc-status-card" onClick={onClick} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <div className="cc-status-value" style={color ? { color } : {}}>{value}</div>
      <div className="cc-status-label">{label}</div>
      {sub && <div className="cc-status-sub">{sub}</div>}
    </div>
  )
}

function PriorityDot({ priority }) {
  const colors = { critical: 'var(--red)', high: 'var(--amber)', medium: 'var(--text-dim)', low: 'var(--border)' }
  return <span className="cc-priority-dot" style={{ background: colors[priority] || colors.medium }} />
}

function ActionItem({ item, onClick }) {
  return (
    <div className="cc-action-item" onClick={onClick}>
      <PriorityDot priority={item.priority} />
      <span className="cc-action-title">{item.title}</span>
      <span className="cc-action-category">{item.category?.toUpperCase()}</span>
      {item.score_impact && <span className="cc-action-impact">-{item.score_impact}pts</span>}
    </div>
  )
}

function timeAgo(dateStr) {
  if (!dateStr) return 'never'
  const d = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now - d) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function hoursAgo(dateStr) {
  if (!dateStr) return Infinity
  return (Date.now() - new Date(dateStr).getTime()) / 3600000
}

export default function CommandCenter({ orgId, onNavigate }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    cachedFetch(`${API}/analytics/dashboard`, orgId)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [orgId])

  if (loading) {
    return (
      <div className="cc-page">
        <div className="cc-loading">LOADING COMMAND CENTER...</div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="cc-page">
        <div className="cc-empty">
          <p>No data yet. Run the pipeline from the Desk to get started.</p>
          <button className="cc-action-btn" onClick={() => onNavigate?.('desk')}>Go to Desk</button>
        </div>
      </div>
    )
  }

  const { signals, content, pipeline, approval_rate, top_signals, top_spiked, audit } = data
  const statusMap = content?.by_status || {}
  const channelMap = content?.by_channel || {}
  const typeMap = signals?.by_type || {}
  const dayMap = signals?.by_day || {}

  const scoutHoursAgo = hoursAgo(pipeline?.last_scout_run)
  const genHoursAgo = hoursAgo(pipeline?.last_generate_run)

  // Build attention items
  const attentionItems = []

  // Queued content needing approval
  const queued = statusMap.queued || 0
  if (queued > 0) {
    attentionItems.push({
      priority: queued > 5 ? 'critical' : 'high',
      title: `${queued} piece${queued !== 1 ? 's' : ''} awaiting approval`,
      category: 'content',
      action: () => onNavigate?.('desk'),
    })
  }

  // Stale pipeline warnings
  if (scoutHoursAgo > 48) {
    attentionItems.push({
      priority: scoutHoursAgo > 96 ? 'critical' : 'high',
      title: `No signals collected in ${Math.floor(scoutHoursAgo / 24)} days`,
      category: 'pipeline',
      action: () => onNavigate?.('desk'),
    })
  }
  if (genHoursAgo > 72) {
    attentionItems.push({
      priority: 'high',
      title: `No content generated in ${Math.floor(genHoursAgo / 24)} days`,
      category: 'pipeline',
      action: () => onNavigate?.('desk'),
    })
  }

  // Audit action items
  if (audit?.open_actions) {
    audit.open_actions.forEach(a => {
      attentionItems.push({
        ...a,
        action: () => onNavigate?.('intel'),
      })
    })
  }

  return (
    <div className="cc-page">
      {/* ── ZONE 1: Status Strip ── */}
      <div className="cc-status-strip">
        {audit?.last_score != null ? (
          <div className="cc-score-section" onClick={() => onNavigate?.('intel')}>
            <ScoreRing score={audit.last_score} label="SEO" />
            <div className="cc-score-meta">
              {audit.open_actions_total > 0 && (
                <span className="cc-score-issues">{audit.open_actions_total} open issues</span>
              )}
              {audit.last_run && (
                <span className="cc-score-when">{timeAgo(audit.last_run)}</span>
              )}
            </div>
          </div>
        ) : (
          <div className="cc-score-section cc-score-empty" onClick={() => onNavigate?.('intel')}>
            <div className="cc-score-ring cc-score-ring-empty">
              <span className="cc-score-number" style={{ color: 'var(--text-dim)' }}>?</span>
              <span className="cc-score-label">SEO</span>
            </div>
            <span className="cc-score-cta">Run audit</span>
          </div>
        )}

        <div className="cc-status-cards">
          <StatusCard
            label="Signals"
            value={signals?.total || 0}
            sub={`Last scout ${timeAgo(pipeline?.last_scout_run)}`}
            onClick={() => onNavigate?.('desk')}
          />
          <StatusCard
            label="Queued"
            value={statusMap.queued || 0}
            color={queued > 0 ? 'var(--amber)' : undefined}
            sub="awaiting review"
            onClick={() => onNavigate?.('desk')}
          />
          <StatusCard
            label="Approved"
            value={statusMap.approved || 0}
            sub="ready to publish"
            onClick={() => onNavigate?.('desk')}
          />
          <StatusCard
            label="Published"
            value={statusMap.published || 0}
            sub={`${Object.keys(channelMap).length} channels`}
            onClick={() => onNavigate?.('desk')}
          />
          <StatusCard
            label="Approval Rate"
            value={`${approval_rate}%`}
            color={approval_rate >= 75 ? 'var(--green)' : approval_rate >= 50 ? 'var(--amber)' : 'var(--red)'}
            sub={`${statusMap.spiked || 0} spiked`}
          />
        </div>
      </div>

      {/* ── ZONE 2: Needs Your Attention ── */}
      {attentionItems.length > 0 && (
        <div className="cc-attention">
          <div className="cc-section-header">
            <span className="cc-section-title">Needs Your Attention</span>
            <span className="cc-section-count">{attentionItems.length}</span>
          </div>
          <div className="cc-attention-list">
            {attentionItems.map((item, i) => (
              <ActionItem key={i} item={item} onClick={item.action} />
            ))}
          </div>
        </div>
      )}

      {attentionItems.length === 0 && (
        <div className="cc-attention cc-all-clear">
          <span className="cc-all-clear-icon">&#x2713;</span>
          <span>All clear. Pipeline is healthy, no outstanding issues.</span>
        </div>
      )}

      {/* ── ZONE 3: Overview Grid ── */}
      <div className="cc-overview">
        {/* Signal volume sparkline */}
        <div className="cc-overview-card">
          <div className="cc-card-header" onClick={() => onNavigate?.('desk')}>Signal Volume (7 Days)</div>
          {Object.keys(dayMap).length > 0 ? (
            <div className="cc-day-chart">
              {Object.entries(dayMap).map(([day, count]) => {
                const max = Math.max(...Object.values(dayMap))
                return (
                  <div key={day} className="cc-day-col">
                    <div className="cc-day-bar" style={{ height: `${(count / (max || 1)) * 100}%` }} />
                    <div className="cc-day-label">{String(day).slice(5)}</div>
                    <div className="cc-day-count">{count}</div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="cc-card-empty">No signals in the last 7 days</div>
          )}
        </div>

        {/* Signals by source */}
        <div className="cc-overview-card">
          <div className="cc-card-header" onClick={() => onNavigate?.('desk')}>Signals by Source</div>
          <div className="cc-bar-list">
            {Object.entries(typeMap).map(([type, count]) => (
              <div key={type} className="cc-bar-row">
                <span className="cc-bar-label">{type.replace('_', ' ')}</span>
                <div className="cc-bar-track">
                  <div className="cc-bar-fill" style={{ width: `${Math.min(100, (count / (signals?.total || 1)) * 100)}%` }} />
                </div>
                <span className="cc-bar-count">{count}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Content by channel */}
        <div className="cc-overview-card">
          <div className="cc-card-header" onClick={() => onNavigate?.('desk')}>Content by Channel</div>
          <div className="cc-bar-list">
            {Object.entries(channelMap).map(([ch, count]) => (
              <div key={ch} className="cc-bar-row">
                <span className="cc-bar-label">{ch.replace('_', ' ')}</span>
                <div className="cc-bar-track">
                  <div className="cc-bar-fill" style={{ width: `${Math.min(100, (count / (content?.total || 1)) * 100)}%` }} />
                </div>
                <span className="cc-bar-count">{count}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Top signals */}
        <div className="cc-overview-card">
          <div className="cc-card-header">Top Producing Signals</div>
          {top_signals?.length > 0 ? (
            <div className="cc-signal-list">
              {top_signals.map(s => (
                <div key={s.id} className="cc-signal-row">
                  <span className="cc-signal-type">{s.type?.replace('_', ' ')}</span>
                  <span className="cc-signal-title">{s.title?.slice(0, 70)}</span>
                  <span className="cc-signal-used">{s.times_used}x</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="cc-card-empty">No signal data yet</div>
          )}
        </div>
      </div>

      {/* Pipeline timing footer */}
      <div className="cc-pipeline-footer">
        <span>Last scout: {timeAgo(pipeline?.last_scout_run)}</span>
        <span>Last generate: {timeAgo(pipeline?.last_generate_run)}</span>
      </div>
    </div>
  )
}
