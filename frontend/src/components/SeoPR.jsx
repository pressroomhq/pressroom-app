import { useState, useEffect, useCallback, useRef } from 'react'
import { orgHeaders } from '../api'

const API = '/api'

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

const STATUS_STEPS = ['pending', 'auditing', 'analyzing', 'implementing', 'pushing', 'verifying', 'complete']

function StatusBadge({ status }) {
  const colors = {
    pending: 'var(--text-dim)',
    auditing: 'var(--amber)',
    analyzing: 'var(--amber)',
    implementing: 'var(--amber)',
    pushing: 'var(--amber)',
    verifying: 'var(--amber)',
    healing: 'var(--red)',
    complete: 'var(--green)',
    failed: 'var(--red)',
  }
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: 3,
      fontSize: 11,
      fontWeight: 700,
      letterSpacing: 1,
      textTransform: 'uppercase',
      background: colors[status] || 'var(--text-dim)',
      color: 'var(--bg)',
    }}>
      {status}
    </span>
  )
}

function StatusProgress({ status }) {
  if (status === 'failed') return null
  // healing maps to the verifying step visually
  const effectiveStatus = status === 'healing' ? 'verifying' : status
  const idx = STATUS_STEPS.indexOf(effectiveStatus)
  if (idx === -1) return null

  const isHealing = status === 'healing'

  return (
    <div style={{ display: 'flex', gap: 3, alignItems: 'center', marginTop: 6 }}>
      {STATUS_STEPS.map((step, i) => (
        <div
          key={step}
          style={{
            flex: 1,
            height: 3,
            borderRadius: 2,
            background: i <= idx
              ? (status === 'complete' ? 'var(--green)' : isHealing ? 'var(--red)' : 'var(--amber)')
              : 'var(--border)',
            transition: 'background 0.3s',
          }}
          title={step === 'verifying' && isHealing ? 'healing' : step}
        />
      ))}
    </div>
  )
}

function TierBadge({ tier }) {
  const colors = { P0: 'var(--red)', P1: 'var(--amber)', P2: 'var(--green)' }
  return (
    <span style={{
      display: 'inline-block',
      padding: '1px 8px',
      borderRadius: 3,
      fontSize: 11,
      fontWeight: 700,
      background: colors[tier] || 'var(--text-dim)',
      color: 'var(--bg)',
      marginRight: 6,
    }}>
      {tier}
    </span>
  )
}

// ────────────────────────────────────────
// Plan Viewer
// ────────────────────────────────────────
function PlanViewer({ plan }) {
  const [expandedTier, setExpandedTier] = useState(null)

  if (!plan || !plan.tiers || plan.tiers.length === 0) {
    return (
      <div className="settings-section">
        <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>
          {plan?.summary || 'No plan data available.'}
        </div>
      </div>
    )
  }

  return (
    <>
      {plan.summary && (
        <div className="settings-section">
          <div className="section-label">Analysis Summary</div>
          <div style={{ color: 'var(--text)', fontSize: 13, lineHeight: 1.6 }}>
            {plan.summary}
          </div>
        </div>
      )}

      {plan.tiers.map((tier, ti) => {
        const changes = tier.changes || []
        if (changes.length === 0) return null
        const isExpanded = expandedTier === ti

        return (
          <div key={ti} className="settings-section">
            <div
              style={{
                display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer',
                padding: '4px 0',
              }}
              onClick={() => setExpandedTier(isExpanded ? null : ti)}
            >
              <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                {isExpanded ? '\u25BC' : '\u25B6'}
              </span>
              <TierBadge tier={tier.tier} />
              <span className="section-label" style={{ margin: 0 }}>
                {tier.description || tier.tier}
              </span>
              <span style={{ color: 'var(--text-dim)', fontSize: 12, marginLeft: 'auto' }}>
                {changes.length} change{changes.length !== 1 ? 's' : ''}
              </span>
            </div>

            {isExpanded && (
              <div style={{ marginTop: 8 }}>
                {changes.map((change, ci) => (
                  <div
                    key={ci}
                    style={{
                      background: 'var(--bg)',
                      border: '1px solid var(--border)',
                      borderRadius: 4,
                      padding: '10px 14px',
                      marginBottom: 8,
                      fontSize: 12,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span style={{
                        padding: '1px 6px',
                        borderRadius: 2,
                        background: 'var(--bg-panel)',
                        border: '1px solid var(--border)',
                        fontSize: 10,
                        textTransform: 'uppercase',
                        letterSpacing: 1,
                        color: 'var(--amber)',
                      }}>
                        {change.change_type || 'update'}
                      </span>
                      {change.page_url && (
                        <a
                          href={change.page_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: 'var(--amber-dim)', textDecoration: 'none', fontSize: 11 }}
                        >
                          {change.page_url.replace(/^https?:\/\//, '').slice(0, 60)}
                        </a>
                      )}
                      {change.priority_score && (
                        <span style={{ marginLeft: 'auto', color: 'var(--text-dim)', fontSize: 10 }}>
                          score: {change.priority_score}
                        </span>
                      )}
                    </div>

                    {change.file_path && (
                      <div style={{ color: 'var(--text-dim)', fontSize: 11, marginBottom: 4 }}>
                        File: <code style={{ color: 'var(--text)' }}>{change.file_path}</code>
                      </div>
                    )}

                    {change.current_value && (
                      <div style={{ marginBottom: 4 }}>
                        <span style={{ color: 'var(--red)', fontSize: 11 }}>Current: </span>
                        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{change.current_value}</span>
                      </div>
                    )}

                    {change.suggested_value && (
                      <div style={{ marginBottom: 4 }}>
                        <span style={{ color: 'var(--green)', fontSize: 11 }}>Suggested: </span>
                        <span style={{ color: 'var(--text)', fontSize: 11 }}>{change.suggested_value}</span>
                      </div>
                    )}

                    {change.justification && (
                      <div style={{ color: 'var(--text-dim)', fontSize: 11, fontStyle: 'italic', marginTop: 4 }}>
                        {change.justification}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}


// ────────────────────────────────────────
// Run Card
// ────────────────────────────────────────
function RunCard({ run, selected, onSelect, onDelete }) {
  const isActive = ['pending', 'auditing', 'analyzing', 'implementing', 'pushing', 'verifying', 'healing'].includes(run.status)

  return (
    <div
      style={{
        background: selected ? 'var(--bg-panel)' : 'var(--bg-card)',
        border: `1px solid ${selected ? 'var(--amber-dim)' : 'var(--border)'}`,
        borderRadius: 4,
        padding: '12px 16px',
        marginBottom: 8,
        cursor: 'pointer',
        transition: 'border-color 0.2s',
      }}
      onClick={() => onSelect(run.id)}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <StatusBadge status={run.status} />
        <span style={{ color: 'var(--text-bright)', fontSize: 13, fontWeight: 600 }}>
          {run.domain.replace(/^https?:\/\//, '')}
        </span>
        <span style={{ marginLeft: 'auto', color: 'var(--text-dim)', fontSize: 11 }}>
          {formatDate(run.created_at)}
        </span>
        <button
          style={{
            background: 'none', border: 'none', color: 'var(--text-dim)',
            cursor: 'pointer', fontSize: 16, padding: '0 4px',
          }}
          onClick={(e) => { e.stopPropagation(); onDelete(run.id) }}
          title="Delete run"
        >
          &times;
        </button>
      </div>

      <StatusProgress status={run.status} />

      <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 11, color: 'var(--text-dim)', flexWrap: 'wrap' }}>
        {run.changes_made > 0 && (
          <span>{run.changes_made} changes</span>
        )}
        {run.pr_url && (
          <a
            href={run.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'var(--green)', textDecoration: 'none' }}
            onClick={e => e.stopPropagation()}
          >
            View PR &rarr;
          </a>
        )}
        {run.deploy_status && run.deploy_status !== 'pending' && (
          <span style={{
            color: run.deploy_status === 'success' ? 'var(--green)'
              : run.deploy_status === 'healed' ? 'var(--amber)'
              : run.deploy_status === 'failed' ? 'var(--red)'
              : 'var(--text-dim)',
          }}>
            deploy: {run.deploy_status}
            {run.heal_attempts > 0 && ` (${run.heal_attempts} fix${run.heal_attempts !== 1 ? 'es' : ''})`}
          </span>
        )}
        {run.status === 'failed' && run.error && (
          <span style={{ color: 'var(--red)' }}>{run.error.slice(0, 80)}</span>
        )}
        {isActive && (
          <span className="spinner" style={{ display: 'inline-block' }} />
        )}
      </div>
    </div>
  )
}


// ────────────────────────────────────────
// Main Component
// ────────────────────────────────────────
export default function SeoPR({ onLog, orgId, repoUrl = '', domain = '', baseBranch = 'main' }) {
  const [launching, setLaunching] = useState(false)
  const [runs, setRuns] = useState([])
  const [selectedRun, setSelectedRun] = useState(null)
  const [selectedPlan, setSelectedPlan] = useState(null)
  const pollRef = useRef(null)

  const loadRuns = useCallback(async () => {
    try {
      const res = await fetch(`${API}/seo-pr/runs`, { headers: orgHeaders(orgId) })
      const data = await res.json()
      if (Array.isArray(data)) setRuns(data)
    } catch { /* ignore */ }
  }, [orgId])

  // Poll for active runs
  useEffect(() => {
    loadRuns()
    pollRef.current = setInterval(loadRuns, 5000)
    return () => clearInterval(pollRef.current)
  }, [loadRuns])

  // Load plan when a run is selected
  useEffect(() => {
    if (!selectedRun) { setSelectedPlan(null); return }
    const run = runs.find(r => r.id === selectedRun)
    if (run?.plan && Object.keys(run.plan).length > 0) {
      setSelectedPlan(run.plan)
    } else {
      // Fetch from server
      fetch(`${API}/seo-pr/runs/${selectedRun}/plan`, { headers: orgHeaders(orgId) })
        .then(r => r.json())
        .then(data => {
          if (data && !data.error) setSelectedPlan(data)
          else setSelectedPlan(null)
        })
        .catch(() => setSelectedPlan(null))
    }
  }, [selectedRun, runs, orgId])

  const launchPipeline = async () => {
    if (!repoUrl.trim()) {
      onLog?.('SEO PR — repo URL is required', 'error')
      return
    }
    setLaunching(true)
    onLog?.(`SEO PR — starting pipeline for ${domain || 'org domain'}...`, 'action')
    try {
      const res = await fetch(`${API}/seo-pr/run`, {
        method: 'POST',
        headers: orgHeaders(orgId),
        body: JSON.stringify({
          repo_url: repoUrl,
          domain: domain,
          base_branch: baseBranch,
        }),
      })
      const data = await res.json()
      if (data.error) {
        onLog?.(`SEO PR FAILED — ${data.error}`, 'error')
      } else {
        onLog?.(`SEO PR LAUNCHED — run #${data.id}, auditing ${data.domain}...`, 'success')
        setSelectedRun(data.id)
        loadRuns()
      }
    } catch (e) {
      onLog?.(`SEO PR ERROR — ${e.message}`, 'error')
    } finally {
      setLaunching(false)
    }
  }

  const deleteRun = async (id) => {
    try {
      await fetch(`${API}/seo-pr/runs/${id}`, { method: 'DELETE', headers: orgHeaders(orgId) })
      if (selectedRun === id) setSelectedRun(null)
      loadRuns()
    } catch { /* ignore */ }
  }

  const activeRuns = runs.filter(r => ['pending', 'auditing', 'analyzing', 'implementing', 'pushing'].includes(r.status))
  const completedRuns = runs.filter(r => r.status === 'complete' || r.status === 'failed')
  const selectedRunData = runs.find(r => r.id === selectedRun)

  return (
    <>
      {/* LAUNCH */}
      <div className="settings-section">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button
            className={`btn btn-run ${launching ? 'loading' : ''}`}
            onClick={launchPipeline}
            disabled={launching || !repoUrl.trim()}
          >
            {launching ? 'Launching...' : 'Run SEO Pipeline'}
          </button>
          <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
            {repoUrl
              ? `${repoUrl.replace(/^https?:\/\/github\.com\//, '')} → ${domain ? domain.replace(/^https?:\/\//, '') : 'org domain'} (${baseBranch})`
              : 'add a repo above'}
          </span>
        </div>
      </div>

      {/* ACTIVE RUNS */}
      {activeRuns.length > 0 && (
        <div className="settings-section">
          <div className="section-label">Active Runs</div>
          {activeRuns.map(run => (
            <RunCard
              key={run.id}
              run={run}
              selected={selectedRun === run.id}
              onSelect={setSelectedRun}
              onDelete={deleteRun}
            />
          ))}
        </div>
      )}

      {/* COMPLETED RUNS */}
      {completedRuns.length > 0 && (
        <div className="settings-section">
          <div className="section-label">Recent Runs</div>
          {completedRuns.map(run => (
            <RunCard
              key={run.id}
              run={run}
              selected={selectedRun === run.id}
              onSelect={setSelectedRun}
              onDelete={deleteRun}
            />
          ))}
        </div>
      )}

      {/* EMPTY STATE */}
      {runs.length === 0 && !launching && (
        <div className="settings-section">
          <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>
            No pipeline runs yet. Configure a repo and domain above to get started.
          </div>
        </div>
      )}

      {/* SELECTED RUN DETAILS */}
      {selectedRunData && (
        <div className="settings-section">
          <div className="section-label">
            Run #{selectedRunData.id} — {selectedRunData.domain.replace(/^https?:\/\//, '')}
          </div>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 12, color: 'var(--text-dim)', marginBottom: 8 }}>
            <span>Status: <StatusBadge status={selectedRunData.status} /></span>
            <span>Repo: <code style={{ color: 'var(--text)' }}>{selectedRunData.repo_url}</code></span>
            {selectedRunData.branch_name && (
              <span>Branch: <code style={{ color: 'var(--amber-dim)' }}>{selectedRunData.branch_name}</code></span>
            )}
            {selectedRunData.changes_made > 0 && (
              <span>Changes: <strong style={{ color: 'var(--text-bright)' }}>{selectedRunData.changes_made}</strong></span>
            )}
            {selectedRunData.pr_url && (
              <span>
                PR:{' '}
                <a
                  href={selectedRunData.pr_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--green)', textDecoration: 'none' }}
                >
                  {selectedRunData.pr_url} &rarr;
                </a>
              </span>
            )}
          </div>

          {selectedRunData.status === 'failed' && selectedRunData.error && (
            <div style={{
              background: 'rgba(255, 68, 68, 0.1)',
              border: '1px solid var(--red)',
              borderRadius: 4,
              padding: '8px 12px',
              fontSize: 12,
              color: 'var(--red)',
              marginBottom: 8,
            }}>
              {selectedRunData.error}
            </div>
          )}

          {selectedRunData.deploy_status && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 12,
              padding: '8px 12px',
              borderRadius: 4,
              fontSize: 12,
              marginBottom: 8,
              background: selectedRunData.deploy_status === 'success' ? 'rgba(34,197,94,0.1)'
                : selectedRunData.deploy_status === 'healed' ? 'rgba(234,179,8,0.1)'
                : selectedRunData.deploy_status === 'failed' ? 'rgba(239,68,68,0.1)'
                : 'var(--bg-panel)',
              border: `1px solid ${selectedRunData.deploy_status === 'success' ? 'rgba(34,197,94,0.3)'
                : selectedRunData.deploy_status === 'healed' ? 'rgba(234,179,8,0.3)'
                : selectedRunData.deploy_status === 'failed' ? 'rgba(239,68,68,0.3)'
                : 'var(--border)'}`,
            }}>
              <span style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1, fontSize: 10 }}>
                DEPLOY
              </span>
              <span style={{
                color: selectedRunData.deploy_status === 'success' ? 'var(--green)'
                  : selectedRunData.deploy_status === 'healed' ? 'var(--amber)'
                  : selectedRunData.deploy_status === 'failed' ? 'var(--red)'
                  : 'var(--text-dim)',
                fontWeight: 600,
              }}>
                {selectedRunData.deploy_status === 'healed'
                  ? `HEALED (${selectedRunData.heal_attempts} attempt${selectedRunData.heal_attempts !== 1 ? 's' : ''})`
                  : selectedRunData.deploy_status.toUpperCase()}
              </span>
              {selectedRunData.deploy_log && selectedRunData.deploy_status === 'failed' && (
                <span style={{ color: 'var(--text-dim)', fontSize: 11, marginLeft: 'auto' }}>
                  {selectedRunData.deploy_log.slice(0, 120)}...
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* PLAN VIEWER */}
      {selectedPlan && <PlanViewer plan={selectedPlan} />}
    </>
  )
}
