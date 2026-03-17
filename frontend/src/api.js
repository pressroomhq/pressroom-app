/**
 * Shared API helpers — all requests include the Supabase JWT
 * from localStorage and X-Org-Id header for org scoping.
 */

/**
 * Build URLSearchParams with auth token + org ID for SSE EventSource calls.
 * EventSource can't send headers, so token goes as query param.
 */
export function sseParams(orgId, extra = {}) {
  const params = new URLSearchParams(extra)
  if (orgId) params.set('x_org_id', String(orgId))
  const token = localStorage.getItem('pr_session')
  if (token) params.set('authorization', token)
  return params
}

export function orgHeaders(orgId) {
  const h = { 'Content-Type': 'application/json' }
  if (orgId) h['X-Org-Id'] = String(orgId)
  const token = localStorage.getItem('pr_session')
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

export async function orgFetch(url, orgId, opts = {}) {
  const headers = { ...orgHeaders(orgId), ...(opts.headers || {}) }
  const res = await fetch(url, { ...opts, headers })
  if (res.status === 401) {
    // Session expired or invalid — clear local auth and reload to login
    localStorage.removeItem('pr_session')
    localStorage.removeItem('pr_user')
    window.location.reload()
  }
  return res
}

// ─── Fetch Cache ────────────────────────────────────────────────────────────
// Simple in-memory cache for GET requests. Keyed by `${url}:${orgId}`.
// Avoids hammering the backend on every render/tab switch.

const _cache = new Map() // key → { data, ts }

/**
 * cachedFetch — like orgFetch but caches GET results for `ttlMs` ms.
 * Any POST/PUT/DELETE to the same path prefix auto-invalidates the cache.
 */
export async function cachedFetch(url, orgId, opts = {}, ttlMs = 10000) {
  const method = (opts.method || 'GET').toUpperCase()

  // Writes invalidate cache entries sharing the same path prefix
  if (method !== 'GET') {
    const path = url.split('?')[0]
    for (const key of _cache.keys()) {
      if (key.startsWith(path)) _cache.delete(key)
    }
    return orgFetch(url, orgId, opts)
  }

  const key = `${url}:${orgId}`
  const cached = _cache.get(key)
  if (cached && Date.now() - cached.ts < ttlMs) {
    // Return a fake Response-like object with the cached data
    return {
      ok: true,
      status: 200,
      json: async () => cached.data,
      _fromCache: true,
    }
  }

  const res = await orgFetch(url, orgId, opts)
  if (res.ok) {
    const data = await res.json()
    _cache.set(key, { data, ts: Date.now() })
    // Return same fake Response so callers can always call .json()
    return { ok: true, status: res.status, json: async () => data, _fromCache: false }
  }
  return res
}

/**
 * invalidateCache — bust all cache entries, or only those matching a prefix.
 * Call on org switch or after writes.
 */
export function invalidateCache(prefix) {
  if (!prefix) {
    _cache.clear()
    return
  }
  for (const key of _cache.keys()) {
    if (key.includes(prefix)) _cache.delete(key)
  }
}
