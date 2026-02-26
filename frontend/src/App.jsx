import { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense } from 'react'
// Auth components load eagerly — needed before the app shell
import Login from './components/Login'
import AcceptInvite from './components/AcceptInvite'
import ResetPassword from './components/ResetPassword'
// ChannelPicker has named exports so can't be lazy easily — keep eager
import ChannelPicker, { loadSavedChannels, saveChannels } from './components/ChannelPicker'
// Everything else loads lazily — won't compile until after login
const Settings = lazy(() => import('./components/Settings'))
const Voice = lazy(() => import('./components/Voice'))
const Scout = lazy(() => import('./components/Scout'))
const Import = lazy(() => import('./components/Import'))
const Onboard = lazy(() => import('./components/Onboard'))
const Connections = lazy(() => import('./components/Connections'))
const Audit = lazy(() => import('./components/Audit'))
const Assets = lazy(() => import('./components/Assets'))
const StoryDesk = lazy(() => import('./components/StoryDesk'))
const Team = lazy(() => import('./components/Team'))
const Blog = lazy(() => import('./components/Blog'))
const EmailDrafts = lazy(() => import('./components/EmailDrafts'))
const HubSpot = lazy(() => import('./components/HubSpot'))
const Dashboard = lazy(() => import('./components/Dashboard'))
const Company = lazy(() => import('./components/Company'))
const Scoreboard = lazy(() => import('./components/Scoreboard'))
const YouTube = lazy(() => import('./components/YouTube'))
const Skills = lazy(() => import('./components/Skills'))
const Usage = lazy(() => import('./components/Usage'))
const Competitive = lazy(() => import('./components/Competitive'))
const AIVisibility = lazy(() => import('./components/AIVisibility'))
const AdminUsers = lazy(() => import('./components/AdminUsers'))
const ApiKeys = lazy(() => import('./components/ApiKeys'))
const Feedback = lazy(() => import('./components/Feedback'))

import { supabase } from './supabaseClient'
import { invalidateCache } from './api'

const API = '/api'

function formatDate() {
  const d = new Date()
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`
}

function formatTime() {
  const d = new Date()
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function ts() {
  return new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function channelLabel(ch) {
  const labels = {
    linkedin: 'LinkedIn', x_thread: 'X Thread', facebook: 'Facebook',
    blog: 'Blog Post', devto: 'Dev.to', github_gist: 'GitHub Gist',
    release_email: 'Email', newsletter: 'Newsletter', yt_script: 'YouTube Script',
  }
  return labels[ch] || ch.toUpperCase()
}

function signalTag(type) {
  const tags = {
    github_release: 'GH RELEASE', github_commit: 'GH COMMIT', hackernews: 'HN',
    reddit: 'REDDIT', rss: 'RSS', trend: 'TREND',
    support: 'SUPPORT', performance: 'PERF',
  }
  return tags[type] || type.toUpperCase()
}

function signalBadgeClass(type) {
  const classes = {
    github_release: 'signal-badge-gh-release',
    github_commit: 'signal-badge-gh-commit',
    hackernews: 'signal-badge-hn',
    reddit: 'signal-badge-reddit',
    rss: 'signal-badge-rss',
    trend: 'signal-badge-trend',
  }
  return classes[type] || ''
}

function wordCount(text) {
  if (!text) return 0
  return text.trim().split(/\s+/).filter(Boolean).length
}

function timeAgo(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diff = Math.floor((now - d) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// Build headers with org context + session token
function orgHeaders(orgId) {
  const h = { 'Content-Type': 'application/json' }
  if (orgId) h['X-Org-Id'] = String(orgId)
  const token = localStorage.getItem('pr_session')
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

function orgFetch(url, orgId, opts = {}) {
  const headers = { ...orgHeaders(orgId), ...(opts.headers || {}) }
  return fetch(url, { ...opts, headers })
}

const NAV_GROUPS = [
  {
    label: 'Content',
    items: [
      { view: 'studio', label: 'Video' },
      { view: 'blog', label: 'Blog' },
      { view: 'email', label: 'Email' },
      { view: 'hubspot', label: 'HubSpot' },
      { view: 'import', label: 'Import' },
      { view: 'voice', label: 'Voice' },
    ],
  },
  {
    label: 'Intel',
    items: [
      { view: 'scoreboard', label: 'Scoreboard' },
      { view: 'competitive', label: 'Competitive' },
      { view: 'ai_visibility', label: 'AI Visibility' },
      { view: 'team', label: 'Team' },
      { view: 'assets', label: 'Assets' },
      { view: 'usage', label: 'Usage' },
    ],
  },
  {
    label: 'Config',
    items: [
      { view: 'company', label: 'Company' },
      { view: 'skills', label: 'Skills' },
      { view: 'connections', label: 'Connect' },
      { view: 'settings', label: 'Account' },
      { view: 'api_keys', label: 'API Keys' },
      { view: 'admin_users', label: 'Users' },
    ],
  },
]

function NavDropdown({ label, items, currentView, setView }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const isActive = items.some(i => i.view === currentView)

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="nav-group" ref={ref}>
      <button
        className={`nav-group-label ${isActive ? 'active' : ''}`}
        onClick={() => setOpen(!open)}
      >
        {label}
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="nav-dropdown">
          {items.map(item => (
            <button
              key={item.view}
              className={`nav-dropdown-item ${currentView === item.view ? 'active' : ''}`}
              onClick={() => { setView(item.view); setOpen(false) }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function App() {
  // ── Auth gate ───────────────────────────────────────────────────────────────
  const inviteMatch = window.location.pathname.match(/^\/invite\/(.+)$/)
  const hashParams = new URLSearchParams(window.location.hash.slice(1))
  const isRecovery = hashParams.get('type') === 'recovery'
  const [authChecked, setAuthChecked] = useState(false)
  const [authed, setAuthed] = useState(false)
  const [currentUser, setCurrentUser] = useState(null)

  useEffect(() => {
    if (inviteMatch) { setAuthChecked(true); return }

    // Check for Supabase session
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        localStorage.setItem('pr_session', session.access_token)
        const cachedUser = localStorage.getItem('pr_user')
        if (cachedUser) {
          try { setCurrentUser(JSON.parse(cachedUser)) } catch {}
          setAuthed(true)
          setAuthChecked(true)
          // Validate profile in background
          fetch('/api/auth/me', { headers: { Authorization: `Bearer ${session.access_token}` } })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
              if (data?.user) {
                setCurrentUser(data.user)
                localStorage.setItem('pr_user', JSON.stringify(data.user))
              } else {
                localStorage.removeItem('pr_session')
                localStorage.removeItem('pr_user')
                setAuthed(false)
                setCurrentUser(null)
              }
            })
            .catch(() => {})
        } else {
          // No cached user — must fetch before showing app
          fetch('/api/auth/me', { headers: { Authorization: `Bearer ${session.access_token}` } })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
              if (data?.user) {
                setAuthed(true)
                setCurrentUser(data.user)
                localStorage.setItem('pr_user', JSON.stringify(data.user))
              } else {
                localStorage.removeItem('pr_session')
              }
              setAuthChecked(true)
            })
            .catch(() => setAuthChecked(true))
        }
      } else {
        // No Supabase session
        localStorage.removeItem('pr_session')
        setAuthChecked(true)
      }
    })

    // Listen for auth state changes (token refresh, sign out)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (session) {
        localStorage.setItem('pr_session', session.access_token)
      } else {
        localStorage.removeItem('pr_session')
        localStorage.removeItem('pr_user')
        localStorage.removeItem('pr_orgs')
        setAuthed(false)
        setCurrentUser(null)
      }
    })

    return () => subscription.unsubscribe()
  }, [])

  if (inviteMatch) return <AcceptInvite token={inviteMatch[1]} onAccepted={() => { window.location.href = '/' }} />
  if (isRecovery) return <ResetPassword onDone={() => { window.location.href = '/' }} />
  if (!authChecked) return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-mono)', color: 'var(--text-dim)', fontSize: 12 }}>
      PRESSROOM...
    </div>
  )
  if (!authed) return <Login onLogin={(data) => { setAuthed(true); setCurrentUser(data.user) }} />

  return <AppShell currentUser={currentUser} onLogout={async () => {
    await supabase.auth.signOut()
    localStorage.removeItem('pr_session')
    localStorage.removeItem('pr_user')
    localStorage.removeItem('pr_orgs')
    setAuthed(false)
    setCurrentUser(null)
  }} />
}

function AppShell({ currentUser, onLogout }) {
  const [signals, setSignals] = useState([])
  const [queue, setQueue] = useState([])
  const [allContent, setAllContent] = useState([])
  const [time, setTime] = useState(formatTime())
  const [expanded, setExpanded] = useState(null)
  const [view, setView] = useState('dashboard')
  // Rewrite modal state
  const [rewriteTarget, setRewriteTarget] = useState(null) // content item being rewritten
  const [rewriteFeedback, setRewriteFeedback] = useState('')
  const [rewriteStatus, setRewriteStatus] = useState(null) // { type: 'success'|'error', msg }
  const [rewriteSubmitting, setRewriteSubmitting] = useState(false)

  // Run Engine modal state
  const [showEngineModal, setShowEngineModal] = useState(false)
  const [engineStrategy, setEngineStrategy] = useState(null)
  const [engineStrategyLoading, setEngineStrategyLoading] = useState(false)
  const [engineChannels, setEngineChannels] = useState([])
  const ALL_ENGINE_CHANNELS = ['linkedin', 'devto', 'blog', 'release_email', 'newsletter']

  // Multi-tenant state
  const [orgs, setOrgs] = useState([])
  const [currentOrg, setCurrentOrg] = useState(null) // { id, name, domain }
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [onboardingOrgId, setOnboardingOrgId] = useState(null) // org currently being onboarded

  // Content filter state
  const [contentFilter, setContentFilter] = useState('all') // all, queued, approved, published
  // Scout source toggles
  const ALL_SCOUT_SOURCES = ['github', 'hn', 'reddit', 'rss', 'web', 'gsc']
  const [scoutSources, setScoutSources] = useState(() => {
    try { return JSON.parse(localStorage.getItem('pr_scout_sources')) || ALL_SCOUT_SOURCES } catch { return ALL_SCOUT_SOURCES }
  })
  const [scoutSourcesOpen, setScoutSourcesOpen] = useState(false)
  const toggleScoutSource = (src) => {
    setScoutSources(prev => {
      const next = prev.includes(src) ? prev.filter(s => s !== src) : [...prev, src]
      localStorage.setItem('pr_scout_sources', JSON.stringify(next))
      return next
    })
  }
  // Keyboard shortcuts help overlay
  const [showShortcuts, setShowShortcuts] = useState(false)

  // Channel picker + post-as state
  const [selectedChannels, setSelectedChannels] = useState(() => loadSavedChannels(currentOrg?.id))
  const [teamMembers, setTeamMembers] = useState([])
  const [postAs, setPostAs] = useState('')

  // Loading states per action
  const [loading, setLoading] = useState({})
  // Scout runs in background — tracked separately so it doesn't lock the whole UI
  const [scoutRunning, setScoutRunning] = useState(false)
  // Activity log
  const [logs, setLogs] = useState([{ ts: ts(), msg: 'WIRE ONLINE — Pressroom v0.1.0', type: 'system' }])
  const logRef = useRef(null)
  // Streaming state — current streaming line
  const [streamLine, setStreamLine] = useState(null) // { channel, text }
  // Log panel collapse
  const [logCollapsed, setLogCollapsed] = useState(false)
  // Typewriter queue — new log entries get typed out character by character
  const typewriterRef = useRef(null) // current typing timeout
  const [typingEntry, setTypingEntry] = useState(null) // { full, partial, type, ts }

  const orgId = currentOrg?.id || null
  const isDemo = currentOrg?.is_demo || false

  const log = useCallback((msg, type = 'info') => {
    setLogs(prev => [...prev.slice(-200), { ts: ts(), msg, type }])
    // Persist to backend (fire and forget)
    if (orgId) {
      orgFetch(`${API}/log`, orgId, {
        method: 'POST',
        body: JSON.stringify({ level: type, message: msg }),
      }).catch(() => {})
    }
  }, [orgId])

  // Group signals by source type for the Wire panel
  const WIRE_GROUPS = [
    { types: ['github_release', 'github_commit'], label: 'GITHUB' },
    { types: ['hackernews'], label: 'HN' },
    { types: ['reddit'], label: 'REDDIT' },
    { types: ['rss'], label: 'RSS' },
  ]

  const wireGroups = useMemo(() => {
    const knownTypes = WIRE_GROUPS.flatMap(g => g.types)
    const groups = []
    for (const g of WIRE_GROUPS) {
      const items = signals.filter(s => g.types.includes(s.type))
      if (items.length > 0) groups.push({ ...g, signals: items })
    }
    const other = signals.filter(s => !knownTypes.includes(s.type))
    if (other.length > 0) groups.push({ label: 'OTHER', types: [], signals: other })
    return groups
  }, [signals])

  const deleteSignal = async (id) => {
    try {
      await orgFetch(`${API}/signals/${id}`, orgId, { method: 'DELETE' })
      setSignals(prev => prev.filter(s => s.id !== id))
    } catch (e) {
      log(`DELETE SIGNAL FAILED — ${e.message}`, 'error')
    }
  }

  // Load organizations on mount
  const loadOrgs = () => {
    fetch(`${API}/orgs`, { headers: orgHeaders() }).then(r => {
      if (!r.ok) throw new Error(r.status)
      return r.json()
    }).then(data => {
      if (Array.isArray(data) && data.length > 0) {
        setOrgs(data)
        const saved = localStorage.getItem('pressroom_org_id')
        const found = saved ? data.find(o => o.id === Number(saved)) : null
        setCurrentOrg(found || data[0])
      } else {
        setView('onboard')
      }
    }).catch(() => {
      // Retry once after short delay (token might not be in localStorage yet)
      setTimeout(() => {
        fetch(`${API}/orgs`, { headers: orgHeaders() }).then(r => r.ok ? r.json() : []).then(data => {
          if (Array.isArray(data) && data.length > 0) {
            setOrgs(data)
            const saved = localStorage.getItem('pressroom_org_id')
            const found = saved ? data.find(o => o.id === Number(saved)) : null
            setCurrentOrg(found || data[0])
          } else {
            setView('onboard')
          }
        }).catch(() => setView('onboard'))
      }, 500)
    })
  }
  useEffect(() => { loadOrgs() }, [])

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  // Clock
  useEffect(() => {
    const t = setInterval(() => setTime(formatTime()), 1000)
    return () => clearInterval(t)
  }, [])

  const queuedCount = queue.length
  const approvedCount = allContent.filter(c => c.status === 'approved').length
  const publishedCount = allContent.filter(c => c.status === 'published').length
  // Scout is excluded from isAnyLoading — it runs in background and doesn't lock the UI
  const isAnyLoading = Object.entries(loading).some(([k, v]) => k !== 'scout' && v)

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      // Don't fire in input fields
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return
      const key = e.key.toLowerCase()
      if (key === '?') { setShowShortcuts(p => !p); return }
      if (key === 'escape') { setShowShortcuts(false); return }
      if (view !== 'desk') return
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return
      if (key === 's' && !scoutRunning) { e.preventDefault(); runScout(); return }
      if (key === 'g' && !loading.generate && signals.length > 0) { e.preventDefault(); runGenerate(); return }
      if (key === 'p' && !loading.publish && approvedCount > 0) { e.preventDefault(); runPublish(); return }
      if (key === 'r' && !loading.full) { e.preventDefault(); openEngineModal(); return }
      // 1-9 switches org
      if (key >= '1' && key <= '9') {
        const idx = parseInt(key) - 1
        if (orgs[idx]) switchOrg(orgs[idx])
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [view, loading, signals, approvedCount, orgs])

  // Save selected org to localStorage
  useEffect(() => {
    if (currentOrg) localStorage.setItem('pressroom_org_id', String(currentOrg.id))
  }, [currentOrg])

  // Load data (org-scoped)
  const refresh = useCallback(async () => {
    if (!orgId) return
    try {
      const [sigRes, queueRes, contentRes] = await Promise.all([
        orgFetch(`${API}/signals?limit=200`, orgId),
        orgFetch(`${API}/content/queue`, orgId),
        orgFetch(`${API}/content?limit=50`, orgId),
      ])
      if (!sigRes.ok || !queueRes.ok || !contentRes.ok) return
      setSignals(await sigRes.json())
      setQueue(await queueRes.json())
      setAllContent(await contentRes.json())
    } catch (e) {
      // silent on refresh
    }
  }, [orgId])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 8000)
    return () => clearInterval(interval)
  }, [refresh])

  // Handle OAuth callback redirects (?oauth=success&provider=linkedin)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const oauthResult = params.get('oauth')
    const provider = params.get('provider')
    if (oauthResult && provider) {
      const label = provider.charAt(0).toUpperCase() + provider.slice(1)
      if (oauthResult === 'success') {
        log(`${label} connected successfully`, 'success')
        setView('connections')
      } else {
        const reason = params.get('reason') || 'unknown error'
        log(`${label} connection failed — ${reason}`, 'error')
        setView('connections')
      }
      // Clean URL
      window.history.replaceState({}, '', '/')
    }
  }, [])

  // Clear data when switching orgs
  useEffect(() => {
    setSignals([])
    setQueue([])
    setAllContent([])
    setExpanded(null)
    setPostAs('')
    setLoading({})
    setTeamMembers([])
    setSelectedChannels(loadSavedChannels(orgId))
    if (orgId) {
      orgFetch(`${API}/team`, orgId).then(r => r.json()).then(d => setTeamMembers(Array.isArray(d) ? d : [])).catch(() => {})
      // Load persisted activity log
      orgFetch(`${API}/log?limit=100`, orgId).then(r => r.json()).then(entries => {
        if (Array.isArray(entries) && entries.length > 0) {
          const restored = entries.map(e => ({
            ts: e.timestamp ? new Date(e.timestamp).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '',
            msg: e.message,
            type: e.level || 'info',
          }))
          setLogs([{ ts: ts(), msg: 'WIRE ONLINE — Pressroom v0.1.0', type: 'system' }, ...restored])
        } else {
          setLogs([{ ts: ts(), msg: 'WIRE ONLINE — Pressroom v0.1.0', type: 'system' }])
        }
      }).catch(() => {
        setLogs([{ ts: ts(), msg: 'WIRE ONLINE — Pressroom v0.1.0', type: 'system' }])
      })
    }
  }, [orgId])

  // Wrap action in loading state
  const withLoading = (key, fn) => async (...args) => {
    if (loading[key]) return
    setLoading(prev => ({ ...prev, [key]: true }))
    try {
      await fn(...args)
    } finally {
      setLoading(prev => ({ ...prev, [key]: false }))
    }
  }

  // Switch org
  const switchOrg = (org) => {
    invalidateCache() // flush all cached responses on org switch
    setCurrentOrg(org)
    log(`SWITCHED — now working on ${org.name}`, 'system')
    if (view === 'onboard') setView('desk')
  }

  // Delete org
  const deleteOrg = async (org, e) => {
    e.stopPropagation()
    if (!confirm(`Delete "${org.name}" and ALL its data?\n\nSignals, content, settings — everything goes. This cannot be undone.`)) return
    try {
      await fetch(`${API}/orgs/${org.id}`, { method: 'DELETE', headers: orgHeaders() })
      invalidateCache()
      const remaining = orgs.filter(o => o.id !== org.id)
      setOrgs(remaining)
      if (currentOrg?.id === org.id) {
        setCurrentOrg(remaining[0] || null)
        if (remaining.length === 0) setView('onboard')
      }
      log(`DELETED — ${org.name} removed`, 'warn')
    } catch (e) {
      log(`DELETE FAILED — ${e.message}`, 'error')
    }
  }

  // Onboard complete callback
  const onOnboardComplete = (newOrg) => {
    if (newOrg?.id) {
      setOrgs(prev => {
        const exists = prev.some(o => o.id === newOrg.id)
        return exists ? prev : [newOrg, ...prev]
      })
      setCurrentOrg(newOrg)
    }
    fetch(`${API}/orgs`, { headers: orgHeaders() }).then(r => r.json()).then(data => {
      if (Array.isArray(data)) setOrgs(data)
    }).catch(() => {})
    setView('desk')
    log(`ONBOARDED — ${newOrg?.name || 'Company'} is ready`, 'success')
  }

  // Actions
  const runScout = () => {
    if (scoutRunning) return
    setScoutRunning(true)
    const srcLabel = scoutSources.length === ALL_SCOUT_SOURCES.length ? 'all sources' : scoutSources.join(', ')
    log(`SCOUT — starting (${srcLabel})...`, 'action')
    const params = new URLSearchParams({ since_hours: 24 })
    if (orgId) params.set('x_org_id', orgId)
    if (scoutSources.length < ALL_SCOUT_SOURCES.length) params.set('sources', scoutSources.join(','))
    const es = new EventSource(`${API}/stream/scout?${params}`)
    const done = () => { es.close(); setScoutRunning(false) }
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'log') {
          log(data.content, 'action')
        } else if (data.type === 'error') {
          log(`SCOUT FAILED — ${data.content}`, 'error')
          done()
        } else if (data.type === 'done') {
          log(`SCOUT COMPLETE — ${data.signals_saved || 0} new signals`, 'success')
          refresh(); done()
        }
      } catch { /* ignore parse errors */ }
    }
    es.onerror = () => {
      if (es.readyState === EventSource.CONNECTING) return
      log('SCOUT — stream ended', 'warning')
      done()
    }
  }

  const runGenerate = withLoading('generate', async (storyId) => {
    saveChannels(orgId, selectedChannels)
    log(`GENERATE — ${selectedChannels.length} channels...`, 'action')
    try {
      const params = new URLSearchParams()
      if (selectedChannels.length) params.set('channels', selectedChannels.join(','))
      if (postAs) params.set('team_member_id', postAs)
      if (orgId) params.set('x_org_id', orgId)
      if (storyId) params.set('story_id', storyId)
      const url = `${API}/stream/generate?${params}`
      await new Promise((resolve, reject) => {
        const es = new EventSource(url)
        es.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data)
            if (data.type === 'log') {
              log(data.content, 'action')
            } else if (data.type === 'token') {
              setStreamLine(prev => ({
                channel: data.channel || (prev?.channel || ''),
                text: (prev?.text || '') + data.content,
              }))
            } else if (data.type === 'stream_start') {
              setStreamLine({ channel: data.channel, text: '' })
            } else if (data.type === 'stream_end') {
              setStreamLine(null)
            } else if (data.type === 'error') {
              log(`GENERATE ERROR — ${data.content}`, 'error')
              es.close()
              resolve()
            } else if (data.type === 'done') {
              if (data.items) {
                data.items.forEach(i => log(`  [${i.channel}] ${i.headline}`, 'detail'))
              }
              es.close()
              refresh()
              resolve()
            }
          } catch (err) { /* ignore parse errors */ }
        }
        es.onerror = () => {
          es.close()
          resolve()
        }
      })
    } catch (e) {
      log(`GENERATE ERROR — ${e.message}`, 'error')
    }
  })

  const openEngineModal = async () => {
    setShowEngineModal(true)
    setEngineStrategy(null)
    setEngineStrategyLoading(true)
    try {
      const res = await orgFetch(`${API}/pipeline/strategy`, orgId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ available_channels: ALL_ENGINE_CHANNELS }),
      })
      const data = await res.json()
      if (data.error) {
        log(`STRATEGY ERROR — ${data.error}`, 'error')
        setEngineStrategy(null)
      } else {
        setEngineStrategy(data)
        setEngineChannels(data.channels || [])
      }
    } catch (e) {
      log(`STRATEGY FAILED — ${e.message}`, 'error')
    } finally {
      setEngineStrategyLoading(false)
    }
  }

  const runFull = withLoading('full', async (storyId, channelOverride) => {
    const channels = channelOverride || selectedChannels
    saveChannels(orgId, channels)
    log('FULL RUN — scout + brief + generate + humanize', 'action')
    try {
      const params = new URLSearchParams()
      if (channels.length) params.set('channels', channels.join(','))
      if (postAs) params.set('team_member_id', postAs)
      if (orgId) params.set('x_org_id', orgId)
      if (storyId) params.set('story_id', storyId)
      const url = `${API}/stream/run?${params}`
      await new Promise((resolve, reject) => {
        const es = new EventSource(url)
        es.onmessage = (e) => {
          try {
            const data = JSON.parse(e.data)
            if (data.type === 'log') {
              log(data.content, 'action')
            } else if (data.type === 'token') {
              setStreamLine(prev => ({
                channel: data.channel || (prev?.channel || ''),
                text: (prev?.text || '') + data.content,
              }))
            } else if (data.type === 'stream_start') {
              setStreamLine({ channel: data.channel, text: '' })
            } else if (data.type === 'stream_end') {
              setStreamLine(null)
            } else if (data.type === 'error') {
              log(`FULL RUN ERROR — ${data.content}`, 'error')
              es.close()
              resolve()
            } else if (data.type === 'done') {
              if (data.items) {
                data.items.forEach(i => log(`  [${i.channel}] ${i.headline}`, 'detail'))
              }
              es.close()
              refresh()
              resolve()
            }
          } catch (err) { /* ignore parse errors */ }
        }
        es.onerror = () => {
          es.close()
          resolve()
        }
      })
    } catch (e) {
      log(`FULL RUN ERROR — ${e.message}`, 'error')
    }
  })

  const runPublish = withLoading('publish', async () => {
    log('PUBLISH — sending approved content to destinations...', 'action')
    try {
      const res = await orgFetch(`${API}/publish`, orgId, { method: 'POST' })
      const data = await res.json()
      const parts = []
      if (data.published) parts.push(`${data.published} published`)
      if (data.sent_to_slack) parts.push(`${data.sent_to_slack} sent to Slack`)
      if (data.disabled) parts.push(`${data.disabled} skipped`)
      if (data.errors) parts.push(`${data.errors} errors`)
      log(`PUBLISH COMPLETE — ${parts.join(', ') || 'nothing to publish'}`, data.errors > 0 ? 'warn' : 'success')
      if (data.results) {
        data.results.forEach(r => {
          const st = r.result?.status
          if (r.error) log(`  [${r.channel}] FAILED: ${r.error}`, 'error')
          else if (st === 'sent_to_slack') log(`  [${r.channel}] sent to Slack`, 'detail')
          else if (st === 'manual') log(`  [${r.channel}] marked published (manual)`, 'detail')
          else if (st === 'disabled') log(`  [${r.channel}] skipped (disabled)`, 'detail')
          else log(`  [${r.channel}] sent`, 'detail')
        })
      }
      refresh()
    } catch (e) {
      log(`PUBLISH ERROR — ${e.message}`, 'error')
    }
  })

  const contentAction = async (id, action) => {
    const item = [...queue, ...allContent].find(c => c.id === id)
    const label = item ? `[${channelLabel(item.channel)}] ${item.headline?.slice(0, 60)}` : `#${id}`
    setLoading(prev => ({ ...prev, [`card-${id}`]: true }))
    try {
      await orgFetch(`${API}/content/${id}/action`, orgId, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      log(`${action.toUpperCase()} — ${label}`, action === 'approve' ? 'success' : 'warn')
      refresh()
    } catch (e) {
      log(`${action.toUpperCase()} FAILED — ${e.message}`, 'error')
    } finally {
      setLoading(prev => ({ ...prev, [`card-${id}`]: false }))
    }
  }

  const openRewriteModal = (item) => {
    setRewriteTarget(item)
    setRewriteFeedback('')
    setRewriteStatus(null)
    setRewriteSubmitting(false)
  }

  const submitRewrite = async () => {
    if (!rewriteTarget) return
    const id = rewriteTarget.id
    const label = `[${channelLabel(rewriteTarget.channel)}] ${rewriteTarget.headline?.slice(0, 60)}`
    setRewriteSubmitting(true)
    setRewriteStatus(null)
    log(`REWRITE — ${label}${rewriteFeedback ? ` (feedback: ${rewriteFeedback.slice(0, 60)})` : ''}`, 'action')
    try {
      const res = await orgFetch(`${API}/pipeline/regenerate/${id}`, orgId, {
        method: 'POST',
        body: JSON.stringify({ feedback: rewriteFeedback }),
      })
      const data = await res.json()
      if (data.error) {
        log(`REWRITE FAILED — ${data.error}`, 'error')
        setRewriteStatus({ type: 'error', msg: data.error })
        setRewriteSubmitting(false)
      } else {
        log(`REWRITE DONE — ${data.headline?.slice(0, 80)}`, 'success')
        setRewriteStatus({ type: 'success', msg: 'REWRITE COMPLETE' })
        setRewriteSubmitting(false)
        refresh()
        setTimeout(() => setRewriteTarget(null), 2000)
      }
    } catch (e) {
      log(`REWRITE ERROR — ${e.message}`, 'error')
      setRewriteStatus({ type: 'error', msg: e.message })
      setRewriteSubmitting(false)
    }
  }

  const togglePriority = async (signalId) => {
    try {
      const res = await orgFetch(`${API}/signals/${signalId}/prioritize`, orgId, { method: 'PATCH' })
      const data = await res.json()
      if (data.error) return
      setSignals(prev => prev.map(s => s.id === signalId ? { ...s, prioritized: data.prioritized } : s))
    } catch (e) {
      log(`PRIORITIZE FAILED — ${e.message}`, 'error')
    }
  }

  // Build a signal lookup map for source attribution on content cards
  const signalMap = useMemo(() => {
    const m = {}
    signals.forEach(s => { m[s.id] = s })
    return m
  }, [signals])

  // GSC index inspect state — { [contentId]: { url, loading, result } }
  const [inspectState, setInspectState] = useState({})

  const toggleInspect = (id) => {
    setInspectState(prev => {
      if (prev[id]) return { ...prev, [id]: undefined }
      return { ...prev, [id]: { url: '', loading: false, result: null } }
    })
  }

  const runInspect = async (id) => {
    const url = inspectState[id]?.url?.trim()
    if (!url) return
    setInspectState(prev => ({ ...prev, [id]: { ...prev[id], loading: true, result: null } }))
    try {
      const res = await orgFetch(`${API}/gsc/inspect`, orgId, {
        method: 'POST',
        body: JSON.stringify({ url }),
      })
      const data = await res.json()
      const verdict = data.inspectionResult?.indexStatusResult?.coverageState || data.error || 'Unknown'
      const robotsTxt = data.inspectionResult?.indexStatusResult?.robotsTxtState
      const indexState = data.inspectionResult?.indexStatusResult?.indexingState
      setInspectState(prev => ({
        ...prev,
        [id]: { ...prev[id], loading: false, result: { verdict, robotsTxt, indexState } },
      }))
    } catch (e) {
      setInspectState(prev => ({ ...prev, [id]: { ...prev[id], loading: false, result: { verdict: e.message } } }))
    }
  }

  // Recommendation layer state
  const [recommendations, setRecommendations] = useState([])
  const [recsLoading, setRecsLoading] = useState(false)
  const [recsExpanded, setRecsExpanded] = useState(false)
  const [recsError, setRecsError] = useState(null)
  const [generatingRec, setGeneratingRec] = useState(null) // rec index being acted on

  const fetchRecommendations = async () => {
    if (!orgId) return
    setRecsLoading(true)
    setRecsError(null)
    try {
      const res = await orgFetch(`${API}/pipeline/recommend`, orgId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channels: selectedChannels }),
      })
      const data = await res.json()
      if (data.error) {
        setRecsError(data.error)
      } else {
        setRecommendations(data.recommendations || [])
        setRecsExpanded(true)
      }
    } catch (e) {
      setRecsError(e.message)
    } finally {
      setRecsLoading(false)
    }
  }

  const generateFromRec = async (rec, idx) => {
    setGeneratingRec(idx)
    saveChannels(orgId, [rec.channel])
    const signalNote = rec.angle ? ` — ${rec.angle.slice(0, 80)}` : ''
    log(`GENERATE (rec) — [${rec.channel}]${signalNote}`, 'action')
    try {
      const params = new URLSearchParams()
      params.set('channels', rec.channel)
      if (postAs) params.set('team_member_id', postAs)
      if (orgId) params.set('x_org_id', orgId)
      const url = `${API}/stream/generate?${params}`
      await new Promise((resolve) => {
        const es = new EventSource(url)
        es.onmessage = (e) => {
          try {
            const d = JSON.parse(e.data)
            if (d.type === 'log') log(d.content, 'action')
            else if (d.type === 'token') setStreamLine(prev => ({ channel: d.channel || (prev?.channel || ''), text: (prev?.text || '') + d.content }))
            else if (d.type === 'stream_start') setStreamLine({ channel: d.channel, text: '' })
            else if (d.type === 'stream_end') setStreamLine(null)
            else if (d.type === 'done' || d.type === 'error') { es.close(); refresh(); resolve() }
          } catch {}
        }
        es.onerror = () => { es.close(); resolve() }
      })
    } catch (e) {
      log(`GENERATE ERROR — ${e.message}`, 'error')
    } finally {
      setGeneratingRec(null)
    }
  }

  // Filtered content list based on content filter
  const filteredContent = useMemo(() => {
    const baseList = queue.length > 0 && contentFilter === 'all' ? queue : allContent
    if (contentFilter === 'all') return baseList
    return allContent.filter(c => c.status === contentFilter)
  }, [queue, allContent, contentFilter])

  return (
    <>
      {/* HEADER */}
      <div className="header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
          <img src="/logo-icon-128.png" alt="Pressroom HQ" style={{ height: 28, width: 28 }} />
          <div>
            <div className="header-title">Pressroom HQ</div>
            <div className="header-edition">
              {currentOrg ? currentOrg.name : 'Daily Edition'}
            </div>
          </div>
          <div className="nav-shell">
            {/* Row 1 — top-level tabs */}
            <nav className="nav-tabs">
              <button className={`nav-tab ${view === 'dashboard' ? 'active' : ''}`} onClick={() => setView('dashboard')}>Dashboard</button>
              <button className={`nav-tab ${view === 'audit' ? 'active' : ''}`} onClick={() => setView('audit')}>Audit</button>
              <button className={`nav-tab ${view === 'desk' ? 'active' : ''}`} onClick={() => setView('desk')}>Desk</button>
              <button className={`nav-tab ${view === 'scout' ? 'active' : ''}`} onClick={() => setView('scout')}>Signals</button>
              <span className="nav-divider" />
              {NAV_GROUPS.map(g => (
                <NavDropdown key={g.label} label={g.label} items={g.items} currentView={view} setView={setView} />
              ))}
              <span style={{ flex: 1 }} />
              <button className={`nav-tab ${view === 'feedback' ? 'active' : ''}`} style={{ color: view === 'feedback' ? 'var(--accent)' : 'var(--text-dim)', fontSize: 11 }} onClick={() => setView('feedback')}>Feedback</button>
            </nav>
            {/* Row 2 — sub-tab strip for active group */}
            {NAV_GROUPS.map(g => {
              const isGroupActive = g.items.some(i => i.view === view)
              if (!isGroupActive) return null
              return (
                <div key={g.label} className="nav-subtabs">
                  <span className="nav-subtabs-group">{g.label}</span>
                  {g.items.map(item => (
                    <button
                      key={item.view}
                      className={`nav-subtab ${view === item.view ? 'active' : ''}`}
                      onClick={() => setView(item.view)}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              )
            })}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="header-date">{formatDate()}</div>
          <div className="header-date">{time}</div>
          {currentUser && (
            <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 2, display: 'flex', gap: 8, justifyContent: 'flex-end', alignItems: 'center' }}>
              <span>{currentUser.email}</span>
              <button
                onClick={onLogout}
                style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 10, fontFamily: 'var(--font-mono)', padding: 0, textDecoration: 'underline' }}
              >
                logout
              </button>
            </div>
          )}
        </div>
      </div>

      <Suspense fallback={<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', flex: 1, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: 1 }}>LOADING...</div>}>
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* ORG SIDEBAR */}
        <div className={`org-sidebar ${sidebarOpen ? 'open' : 'collapsed'}`}>
          <div className="org-sidebar-header" onClick={() => setSidebarOpen(!sidebarOpen)}>
            {sidebarOpen ? 'Companies' : ''}
            <span className="org-sidebar-toggle">{sidebarOpen ? '\u25C0' : '\u25B6'}</span>
          </div>
          {sidebarOpen && (
            <div className="org-list">
              {orgs.map(org => (
                <div
                  key={org.id}
                  className={`org-item ${currentOrg?.id === org.id ? 'active' : ''}`}
                  onClick={() => switchOrg(org)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
                    <div>
                      <div className="org-item-name">
                        {org.name}
                        {org.is_demo && <span style={{ marginLeft: 5, fontSize: 9, background: 'var(--text-dim)', color: '#000', borderRadius: 2, padding: '1px 4px', fontWeight: 700, letterSpacing: 0.5 }}>DEMO</span>}
                      </div>
                      <div className="org-item-domain">{org.domain}</div>
                    </div>
                    <button
                      className="org-delete-btn"
                      onClick={(e) => deleteOrg(org, e)}
                      title={`Delete ${org.name}`}
                    >&times;</button>
                  </div>
                  {org.domain && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (onboardingOrgId === org.id) return
                        setOnboardingOrgId(org.id)
                        orgFetch(`${API}/orgs/${org.id}/onboard`, org.id, { method: 'POST' })
                          .then(r => r.json())
                          .then(d => {
                            log(`ONBOARD started — ${org.name} (${org.domain})`, 'info')
                          })
                          .catch(err => log(`ONBOARD failed — ${err.message}`, 'error'))
                          .finally(() => setOnboardingOrgId(null))
                      }}
                      style={{
                        marginTop: 6,
                        width: '100%',
                        padding: '5px 0',
                        background: onboardingOrgId === org.id ? 'var(--text-dim)' : 'var(--accent)',
                        color: '#000',
                        border: 'none',
                        borderRadius: 3,
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: 1,
                        cursor: onboardingOrgId === org.id ? 'wait' : 'pointer',
                        textTransform: 'uppercase',
                      }}
                      disabled={onboardingOrgId === org.id}
                      title={`Run full onboard for ${org.domain}`}
                    >
                      {onboardingOrgId === org.id ? 'ONBOARDING...' : 'ONBOARD'}
                    </button>
                  )}
                </div>
              ))}
              {orgs.length === 0 && (
                <div className="org-item" style={{ color: 'var(--text-dim)', cursor: 'default' }}>
                  No companies yet
                </div>
              )}
              <div
                className="org-item org-add"
                onClick={() => setView('onboard')}
              >
                + Add Company
              </div>
            </div>
          )}
        </div>

        {/* MAIN CONTENT */}
        <div key={orgId} style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>
          {view === 'email' && (
            <div className="pressroom" style={{ gridTemplateColumns: '1fr' }}>
              <EmailDrafts orgId={orgId} />
            </div>
          )}

          {(view === 'settings' || view === 'voice' || view === 'scout' || view === 'import' || view === 'blog' || view === 'onboard' || view === 'connections' || view === 'hubspot' || view === 'audit' || view === 'assets' || view === 'team' || view === 'dashboard' || view === 'company' || view === 'scoreboard' || view === 'skills' || view === 'competitive' || view === 'ai_visibility' || view === 'usage' || view === 'admin_users' || view === 'api_keys' || view === 'feedback') && (
            <div className="pressroom" style={{ gridTemplateColumns: '1fr' }}>
              <div className="desk-area" style={{ gridTemplateRows: '1fr' }}>
                {view === 'settings' && <Settings onLog={log} orgId={orgId} />}
                {view === 'voice' && <Voice onLog={log} orgId={orgId} />}
                {view === 'scout' && <Scout onLog={log} orgId={orgId} />}
                {view === 'import' && <Import onLog={log} orgId={orgId} />}
                {view === 'blog' && <Blog orgId={orgId} />}
                {view === 'onboard' && <Onboard onLog={log} onComplete={onOnboardComplete} />}
                {view === 'connections' && <Connections onLog={log} orgId={orgId} userId={currentUser?.id} />}
                {view === 'hubspot' && <HubSpot onLog={log} orgId={orgId} onNavigate={setView} />}
                {view === 'audit' && <Audit onLog={log} orgId={orgId} />}
                {view === 'assets' && <Assets orgId={orgId} />}
                {view === 'team' && <Team orgId={orgId} />}
                {view === 'dashboard' && <Dashboard orgId={orgId} onNavigate={setView} />}
                {view === 'company' && <Company orgId={orgId} onLog={log} />}
                {view === 'scoreboard' && <Scoreboard orgId={orgId} onSwitchOrg={(org) => { switchOrg(org); setView('desk') }} />}
                {view === 'skills' && <Skills orgId={orgId} />}
                {view === 'competitive' && <Competitive orgId={orgId} />}
                {view === 'ai_visibility' && <AIVisibility orgId={orgId} />}
                {view === 'usage' && <Usage orgId={orgId} />}
                {view === 'admin_users' && <AdminUsers orgs={orgs} />}
                {view === 'api_keys' && <ApiKeys orgId={orgId} orgs={orgs} />}
                {view === 'feedback' && <Feedback orgId={orgId} currentView={view} />}
              </div>
            </div>
          )}

          {view === 'studio' && (
            <div className="main-content" style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
              <YouTube orgId={orgId} allContent={allContent} onLog={log} />
            </div>
          )}

          {view === 'desk' && (
            <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
              <StoryDesk
                orgId={orgId}
                signals={signals}
                allContent={allContent}
                queue={queue}
                loading={{ ...loading, scout: scoutRunning }}
                onRunScout={runScout}
                onRunGenerate={runGenerate}
                onRunFull={openEngineModal}
                onRunPublish={runPublish}
                selectedChannels={selectedChannels}
                setSelectedChannels={setSelectedChannels}
                postAs={postAs}
                setPostAs={setPostAs}
                teamMembers={teamMembers}
                log={log}
                refresh={refresh}
                streamLine={streamLine}
                contentAction={contentAction}
                channelLabel={channelLabel}
                timeAgo={timeAgo}
                isAnyLoading={isAnyLoading}
                queuedCount={queuedCount}
                approvedCount={approvedCount}
                publishedCount={publishedCount}
              />
            </div>
          )}

          {/* ── GLOBAL LOG PANEL — always visible, collapsible ── */}
          <div className={`log-panel${logCollapsed ? ' log-collapsed' : ''}`}>
            <div className="log-panel-header" onClick={() => setLogCollapsed(p => !p)}>
              <div className={`log-panel-indicator${isAnyLoading ? ' active' : ''}`} />
              <span className="log-panel-title">Activity Log</span>
              {logs.length > 0 && !logCollapsed && (
                <span style={{ fontSize: 10, color: '#2a5a2a', marginLeft: 6 }}>{logs.length}</span>
              )}
              {!logCollapsed && logs.length > 0 && (
                <span style={{ fontSize: 10, color: '#3a7a3a', marginLeft: 8, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {logs[logs.length - 1].msg}
                </span>
              )}
              <span className="log-panel-toggle">{logCollapsed ? '▲' : '▼'}</span>
            </div>
            {!logCollapsed && (
              <div className="log-feed" ref={logRef}>
                {logs.map((l, i) => (
                  <div key={i} className={`log-line log-${l.type}`}>
                    <span className="log-ts">{l.ts}</span>{l.msg}
                  </div>
                ))}
                {streamLine && (
                  <div className="log-line log-stream">
                    <span className="log-ts">{ts()}</span>
                    <span className="stream-text">{streamLine.text}<span className="stream-cursor">&#9608;</span></span>
                  </div>
                )}
              </div>
            )}
          </div>
          {/* STATUS BAR */}
          <div className="status-bar">
            <span>
              <span className={`status-indicator ${isAnyLoading ? 'busy' : 'online'}`}></span>
              {isAnyLoading ? Object.entries(loading).filter(([k, v]) => k !== 'scout' && v).map(([k]) => k.toUpperCase()).join(' + ') : 'WIRE ONLINE'}
              {scoutRunning && <span style={{ color: 'var(--text-dim)', marginLeft: 6 }}>· SCOUT RUNNING</span>}
              {queuedCount > 0 && !isAnyLoading && !scoutRunning && <span className="status-pending"> — {queuedCount} awaiting approval</span>}
            </span>
            <span>
              {currentOrg ? `${currentOrg.name} | ` : ''}PRESSROOM v0.1.0
              <button className="shortcut-trigger" onClick={() => setShowShortcuts(true)} title="Keyboard shortcuts">?</button>
            </span>
          </div>
        </div>
      </div>

      {/* REWRITE MODAL */}
      {rewriteTarget && (
        <div className="modal-overlay" onClick={() => setRewriteTarget(null)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <span>Rewrite: {channelLabel(rewriteTarget.channel)}</span>
              <button className="modal-close" onClick={() => setRewriteTarget(null)}>&times;</button>
            </div>
            <div className="modal-headline">{rewriteTarget.headline}</div>
            <div className="modal-body-preview">{rewriteTarget.body?.slice(0, 300)}...</div>
            <label className="modal-label">Editor Instructions (optional)</label>
            <textarea
              className="setting-input modal-textarea"
              value={rewriteFeedback}
              onChange={e => setRewriteFeedback(e.target.value)}
              placeholder="e.g. make it punchier, focus more on the security angle, lead with the DF integration..."
              rows={4}
              autoFocus
              onKeyDown={e => { if (e.key === 'Enter' && e.metaKey) submitRewrite() }}
            />
            {rewriteStatus && (
              <div style={{
                padding: '8px 12px',
                marginBottom: 10,
                fontSize: 12,
                fontWeight: 700,
                letterSpacing: '1px',
                textTransform: 'uppercase',
                color: rewriteStatus.type === 'success' ? 'var(--green)' : 'var(--red)',
                border: `1px solid ${rewriteStatus.type === 'success' ? 'var(--green)' : 'var(--red)'}`,
                background: rewriteStatus.type === 'success' ? 'rgba(51,255,51,0.05)' : 'rgba(255,68,68,0.05)',
              }}>
                {rewriteStatus.msg}
              </div>
            )}
            <div className="modal-actions">
              <button className="btn btn-run" onClick={submitRewrite} disabled={rewriteSubmitting}>
                {rewriteSubmitting ? 'Rewriting...' : 'Rewrite'}
              </button>
              <button className="btn btn-spike" onClick={() => { setRewriteFeedback(''); submitRewrite() }} disabled={rewriteSubmitting}>
                Rewrite (No Instructions)
              </button>
              <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => setRewriteTarget(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* RUN ENGINE MODAL */}
      {showEngineModal && (
        <div className="modal-overlay" onClick={() => setShowEngineModal(false)}>
          <div className="modal engine-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <span>⚡ Run Engine</span>
              <button className="modal-close" onClick={() => setShowEngineModal(false)}>&times;</button>
            </div>

            {engineStrategyLoading && (
              <div className="engine-strategy-loading">
                <div className="engine-spinner" />
                <span>Analyzing signals and content history...</span>
              </div>
            )}

            {!engineStrategyLoading && engineStrategy && (
              <div className="engine-strategy">
                <div className="engine-strategy-summary">{engineStrategy.summary}</div>

                {engineStrategy.angles && engineStrategy.angles.length > 0 && (
                  <div className="engine-angles">
                    <div className="engine-section-label">Recommended Angles</div>
                    {engineStrategy.angles.map((a, i) => (
                      <div key={i} className="engine-angle-item">→ {a}</div>
                    ))}
                  </div>
                )}

                {engineStrategy.avoid && engineStrategy.avoid.length > 0 && (
                  <div className="engine-avoid">
                    <div className="engine-section-label">Avoid</div>
                    {engineStrategy.avoid.map((a, i) => (
                      <div key={i} className="engine-avoid-item">✕ {a}</div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {!engineStrategyLoading && !engineStrategy && (
              <div className="engine-strategy-error">
                Strategy unavailable — will run with selected channels
              </div>
            )}

            <div className="engine-channel-section">
              <div className="engine-section-label">Channels to Generate</div>
              <div className="engine-channel-grid">
                {ALL_ENGINE_CHANNELS.map(ch => (
                  <label key={ch} className={`engine-channel-chip ${engineChannels.includes(ch) ? 'active' : ''}`}>
                    <input
                      type="checkbox"
                      checked={engineChannels.includes(ch)}
                      onChange={e => {
                        if (e.target.checked) setEngineChannels(prev => [...prev, ch])
                        else setEngineChannels(prev => prev.filter(c => c !== ch))
                      }}
                    />
                    {ch === 'release_email' ? 'Release Email' : ch === 'yt_script' ? 'YT Script' : ch.charAt(0).toUpperCase() + ch.slice(1)}
                  </label>
                ))}
              </div>
            </div>

            <div className="modal-actions">
              <button
                className="btn btn-engine"
                disabled={engineChannels.length === 0 || loading.full}
                onClick={() => {
                  setShowEngineModal(false)
                  runFull(undefined, engineChannels)
                }}
              >
                {loading.full ? 'Running...' : `Fire — ${engineChannels.length} channel${engineChannels.length !== 1 ? 's' : ''}`}
              </button>
              <button className="btn" style={{ color: 'var(--text-dim)', borderColor: 'var(--border)' }} onClick={() => setShowEngineModal(false)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* KEYBOARD SHORTCUTS OVERLAY */}
      {showShortcuts && (
        <div className="modal-overlay" onClick={() => setShowShortcuts(false)}>
          <div className="modal shortcuts-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <span>Keyboard Shortcuts</span>
              <button className="modal-close" onClick={() => setShowShortcuts(false)}>&times;</button>
            </div>
            <div className="shortcuts-list">
              <div className="shortcut-row"><kbd>S</kbd> <span>Signals — pull signals</span></div>
              <div className="shortcut-row"><kbd>G</kbd> <span>Generate — write content (quick or story)</span></div>
              <div className="shortcut-row"><kbd>R</kbd> <span>Run Pipeline — scout + generate</span></div>
              <div className="shortcut-row"><kbd>P</kbd> <span>Publish — send approved content</span></div>
              <div className="shortcut-row"><kbd>N</kbd> <span>New Story</span></div>
              <div className="shortcut-row"><kbd>1-9</kbd> <span>Switch to org by position</span></div>
              <div className="shortcut-row"><kbd>?</kbd> <span>Toggle this overlay</span></div>
              <div className="shortcut-row"><kbd>Esc</kbd> <span>Close overlay</span></div>
            </div>
            <div style={{ marginTop: 12, fontSize: 10, color: 'var(--text-dim)' }}>Shortcuts only fire on the Desk view and outside input fields.</div>
          </div>
        </div>
      )}

      </Suspense>
    </>
  )
}
