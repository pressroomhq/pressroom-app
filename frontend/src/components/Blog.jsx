import { useState, useEffect, useCallback } from 'react'

const API = '/api'

export default function Blog({ orgId }) {
  const [posts, setPosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [scraping, setScraping] = useState(false)
  const [scrapeResult, setScrapeResult] = useState(null)
  const [blogUrl, setBlogUrl] = useState('')

  // GSC performance state
  const [perfData, setPerfData] = useState(null)
  const [perfLoading, setPerfLoading] = useState(false)
  const [perfDays, setPerfDays] = useState(28)

  const headers = { 'Content-Type': 'application/json', ...(orgId ? { 'X-Org-Id': String(orgId) } : {}) }

  // Load blog URL: social_profiles.blog first, then fall back to blog-type asset
  const loadBlogUrl = useCallback(async () => {
    try {
      const [settingsRes, assetsRes] = await Promise.all([
        fetch(`${API}/settings`, { headers }),
        fetch(`${API}/assets`, { headers }),
      ])
      let found = ''
      if (settingsRes.ok) {
        const data = await settingsRes.json()
        const sp = JSON.parse(data.social_profiles?.value || '{}')
        if (sp.blog) found = sp.blog
      }
      if (!found && assetsRes.ok) {
        const assets = await assetsRes.json()
        const blogAsset = (Array.isArray(assets) ? assets : []).find(a => a.asset_type === 'blog')
        if (blogAsset?.url) found = blogAsset.url
      }
      if (found) setBlogUrl(found)
    } catch { /* ignore */ }
  }, [orgId])

  const fetchPosts = useCallback(async () => {
    try {
      const res = await fetch(`${API}/blog/posts`, { headers })
      const data = await res.json()
      setPosts(Array.isArray(data) ? data : [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [orgId])

  const fetchPerformance = useCallback(async () => {
    setPerfLoading(true)
    try {
      const res = await fetch(`${API}/gsc/blog-performance?days=${perfDays}`, { headers })
      if (res.ok) setPerfData(await res.json())
    } catch { /* ignore */ }
    setPerfLoading(false)
  }, [orgId, perfDays])

  useEffect(() => { loadBlogUrl(); fetchPosts(); fetchPerformance() }, [loadBlogUrl, fetchPosts, fetchPerformance])

  const scrapeBlog = async () => {
    setScraping(true)
    setScrapeResult(null)
    try {
      const res = await fetch(`${API}/blog/scrape`, {
        method: 'POST', headers,
        body: JSON.stringify({ blog_url: blogUrl }),
      })
      const data = await res.json()
      setScrapeResult(data)
      if (data.posts_saved > 0) {
        fetchPosts()
        fetchPerformance()
      }
    } catch (e) {
      setScrapeResult({ error: e.message })
    }
    setScraping(false)
  }

  const deletePost = async (id) => {
    await fetch(`${API}/blog/posts/${id}`, { method: 'DELETE', headers })
    fetchPosts()
  }

  const formatDate = (iso) => {
    if (!iso) return 'Unknown date'
    try {
      const d = new Date(iso)
      return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
    } catch {
      return iso
    }
  }

  // Build a URL→metrics lookup from perfData
  const metricsMap = {}
  if (perfData?.posts) {
    for (const p of perfData.posts) {
      if (p.url && p.clicks != null) {
        metricsMap[p.url] = p
        // Also index without/with trailing slash
        if (p.url.endsWith('/')) metricsMap[p.url.slice(0, -1)] = p
        else metricsMap[p.url + '/'] = p
      }
    }
  }

  const getMetrics = (url) => metricsMap[url] || metricsMap[url?.replace(/\/$/, '')] || null

  if (loading) return <div className="settings-page"><p style={{ color: 'var(--text-dim)' }}>Loading blog posts...</p></div>

  const totals = perfData?.totals
  const gscConnected = perfData?.gsc_connected

  return (
    <div className="settings-page">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h2 className="settings-title" style={{ margin: 0 }}>Blog Posts</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            className="setting-input"
            placeholder="Blog URL (from Company settings)"
            value={blogUrl}
            onChange={e => setBlogUrl(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && scrapeBlog()}
            style={{ width: 260, fontSize: 12 }}
          />
          <button
            className="btn btn-run"
            onClick={scrapeBlog}
            disabled={scraping}
          >
            {scraping ? 'Scraping...' : 'Scrape Blog'}
          </button>
        </div>
      </div>

      {/* GSC Performance Summary */}
      {gscConnected && totals && (
        <div className="blog-perf-summary">
          <div className="blog-perf-summary-header">
            <span className="blog-perf-summary-title">
              GSC PERFORMANCE ({perfDays}d)
              {perfLoading && <span style={{ marginLeft: 8, opacity: 0.5 }}>loading...</span>}
            </span>
            <div className="blog-period-toggle">
              {[7, 28, 90].map(d => (
                <button
                  key={d}
                  className={perfDays === d ? 'active' : ''}
                  onClick={() => setPerfDays(d)}
                >{d}d</button>
              ))}
            </div>
          </div>
          <div className="blog-perf-stats">
            <div className="blog-perf-stat">
              <span className="blog-perf-stat-value">{totals.clicks.toLocaleString()}</span>
              <span className="blog-perf-stat-label">clicks</span>
            </div>
            <div className="blog-perf-stat">
              <span className="blog-perf-stat-value">{totals.impressions.toLocaleString()}</span>
              <span className="blog-perf-stat-label">impr</span>
            </div>
            <div className="blog-perf-stat">
              <span className="blog-perf-stat-value">{totals.ctr}%</span>
              <span className="blog-perf-stat-label">CTR</span>
            </div>
            <div className="blog-perf-stat">
              <span className="blog-perf-stat-value">{totals.position}</span>
              <span className="blog-perf-stat-label">avg pos</span>
            </div>
            <div className="blog-perf-stat">
              <span className="blog-perf-stat-value">{totals.matched}/{totals.total}</span>
              <span className="blog-perf-stat-label">matched</span>
            </div>
          </div>
        </div>
      )}

      {gscConnected === false && posts.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 12, fontStyle: 'italic' }}>
          Connect GSC in Config &rarr; Connect for search performance data
        </div>
      )}

      {scrapeResult && (
        <div style={{
          padding: '10px 14px', marginBottom: 16,
          border: '1px solid var(--border)',
          background: 'var(--bg-card)',
          fontSize: 12, lineHeight: 1.5,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span>
            {scrapeResult.error ? (
              <span style={{ color: 'var(--error)' }}>Scrape failed: {scrapeResult.error}</span>
            ) : scrapeResult.message ? (
              <span style={{ color: 'var(--text-dim)' }}>{scrapeResult.message}</span>
            ) : (
              <span>
                Found {scrapeResult.posts_found} posts from{' '}
                <span style={{ color: 'var(--accent)' }}>{scrapeResult.blog_url}</span>
                {' '}&mdash; saved {scrapeResult.posts_saved}, skipped {scrapeResult.posts_skipped} duplicates.
              </span>
            )}
          </span>
          <button
            style={{ marginLeft: 12, cursor: 'pointer', background: 'none', border: 'none', color: 'var(--text-dim)', fontSize: 14 }}
            onClick={() => setScrapeResult(null)}
          >&times;</button>
        </div>
      )}

      {posts.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)' }}>
          <p style={{ fontSize: 14, marginBottom: 8 }}>No blog posts scraped yet.</p>
          <p style={{ fontSize: 12 }}>
            Set your blog URL in <strong>Config &rarr; Company &rarr; Social Profiles</strong>, then click <strong>Scrape Blog</strong>.
          </p>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginBottom: 4 }}>
            {posts.length} post{posts.length !== 1 ? 's' : ''} scraped
          </div>
          {posts.map(p => {
            const m = getMetrics(p.url)
            return (
              <div key={p.id} style={{
                border: '1px solid var(--border)',
                background: 'var(--bg-card)',
                padding: '12px 14px',
                display: 'flex', flexDirection: 'column', gap: 4,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 13, lineHeight: 1.3 }}>
                      {p.url ? (
                        <a
                          href={p.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: 'var(--accent)', textDecoration: 'none' }}
                        >
                          {p.title || 'Untitled'}
                        </a>
                      ) : (
                        p.title || 'Untitled'
                      )}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 2 }}>
                      {formatDate(p.published_at)}
                      {p.scraped_at && (
                        <span style={{ marginLeft: 8 }}>scraped {formatDate(p.scraped_at)}</span>
                      )}
                    </div>
                  </div>
                  <button
                    style={{
                      background: 'none', border: 'none', color: 'var(--text-dim)',
                      cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0, flexShrink: 0,
                    }}
                    onClick={() => deletePost(p.id)}
                    title="Remove post"
                  >&times;</button>
                </div>
                {p.excerpt && (
                  <div style={{
                    fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.4,
                    overflow: 'hidden',
                    display: '-webkit-box',
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: 'vertical',
                  }}>
                    {p.excerpt}
                  </div>
                )}
                {gscConnected && (
                  <div className="blog-perf-metrics">
                    {m ? (
                      <>
                        <span><span className="blog-perf-metric">{m.clicks.toLocaleString()}</span><span className="blog-perf-label"> clicks</span></span>
                        <span><span className="blog-perf-metric">{m.impressions.toLocaleString()}</span><span className="blog-perf-label"> impr</span></span>
                        <span><span className="blog-perf-metric">{m.ctr}%</span><span className="blog-perf-label"> CTR</span></span>
                        <span><span className="blog-perf-metric">{m.position}</span><span className="blog-perf-label"> pos</span></span>
                      </>
                    ) : (
                      <span className="blog-perf-none">no GSC data</span>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
