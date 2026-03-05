import { useState, lazy, Suspense } from 'react'

const Audit = lazy(() => import('./Audit'))
const Competitive = lazy(() => import('./Competitive'))
const AIVisibility = lazy(() => import('./AIVisibility'))
const Scoreboard = lazy(() => import('./Scoreboard'))
const Blog = lazy(() => import('./Blog'))

const TABS = [
  { key: 'audit', label: 'SEO Audit' },
  { key: 'competitive', label: 'Competitive' },
  { key: 'ai_visibility', label: 'AI Visibility' },
  { key: 'scoreboard', label: 'Scoreboard' },
  { key: 'blog', label: 'Blog' },
]

export default function IntelHub({ orgId, onLog, initialTab, onSwitchOrg }) {
  const [tab, setTab] = useState(initialTab || 'audit')

  return (
    <div className="intel-hub">
      <div className="intel-tabs">
        {TABS.map(t => (
          <button
            key={t.key}
            className={`intel-tab ${tab === t.key ? 'active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="intel-content">
        <Suspense fallback={<div className="intel-loading">LOADING...</div>}>
          {tab === 'audit' && <Audit onLog={onLog} orgId={orgId} />}
          {tab === 'competitive' && <Competitive orgId={orgId} />}
          {tab === 'ai_visibility' && <AIVisibility orgId={orgId} />}
          {tab === 'scoreboard' && <Scoreboard orgId={orgId} onSwitchOrg={onSwitchOrg} />}
          {tab === 'blog' && <Blog orgId={orgId} />}
        </Suspense>
      </div>
    </div>
  )
}
