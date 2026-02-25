/**
 * Shared API helpers — all requests include the Supabase JWT
 * from localStorage and X-Org-Id header for org scoping.
 */

export function orgHeaders(orgId) {
  const h = { 'Content-Type': 'application/json' }
  if (orgId) h['X-Org-Id'] = String(orgId)
  const token = localStorage.getItem('pr_session')
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

export function orgFetch(url, orgId, opts = {}) {
  const headers = { ...orgHeaders(orgId), ...(opts.headers || {}) }
  return fetch(url, { ...opts, headers })
}
