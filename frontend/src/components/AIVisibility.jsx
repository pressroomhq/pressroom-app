import { useState, useEffect } from 'react'

const API = '/api'

const SCORE_STYLES = {
  cited: { color: '#33ff33', label: 'CITED' },
  mentioned: { color: '#ffb000', label: 'MENTIONED' },
  absent: { color: '#ff4444', label: 'ABSENT' },
  skipped: { color: '#555', label: 'SKIPPED' },
}

const PROVIDER_LABELS = {
  claude: 'Claude',
  gpt4o: 'GPT-4o',
  perplexity: 'Perplexity',
  gemini: 'Gemini',
  grok: 'Grok',
}

export default function AIVisibility({ orgId }) {
  const [results, setResults] = useState([])
  const [scanning, setScanning] = useState(false)
  const [expandedCell, setExpandedCell] = useState(null) // "q-provider"
  const [editingQuestions, setEditingQuestions] = useState(false)
  const [questions, setQuestions] = useState([])
  const [editText, setEditText] = useState('')

  useEffect(() => {
    if (!orgId) return
    fetch(`${API}/ai-visibility/${orgId}`, { headers: { 'X-Org-Id': orgId } })
      .then(r => r.json())
      .then(d => setResults(d.questions || []))
      .catch(() => {})

    fetch(`${API}/ai-visibility/${orgId}/questions`, { headers: { 'X-Org-Id': orgId } })
      .then(r => r.json())
      .then(d => {
        setQuestions(d.questions || [])
        setEditText((d.questions || []).map(q => q.question).join('\n'))
      })
      .catch(() => {})
  }, [orgId])

  const scan = async () => {
    setScanning(true)
    try {
      const res = await fetch(`${API}/ai-visibility/scan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Org-Id': orgId },
      })
      const data = await res.json()
      setResults(data.questions || [])
    } catch (e) {
      console.error('Scan failed:', e)
    } finally {
      setScanning(false)
    }
  }

  const saveQuestions = async () => {
    const qs = editText.split('\n').map(q => q.trim()).filter(Boolean).slice(0, 4)
    await fetch(`${API}/ai-visibility/${orgId}/questions`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Org-Id': orgId },
      body: JSON.stringify({ questions: qs }),
    })
    setEditingQuestions(false)
    setQuestions(qs.map((q, i) => ({ question: q, position: i + 1 })))
  }

  // Collect all providers from results
  const providers = [...new Set(results.flatMap(r => r.results.map(p => p.provider)))]

  // Summary
  const allScores = results.flatMap(r => r.results.map(p => p.score))
  const cited = allScores.filter(s => s === 'cited').length
  const mentioned = allScores.filter(s => s === 'mentioned').length
  const absent = allScores.filter(s => s === 'absent').length
  const total = cited + mentioned + absent

  return (
    <div className="panel" style={{ overflow: 'auto' }}>
      <div className="panel-header">
        <span>AI Visibility</span>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-sm" onClick={() => setEditingQuestions(!editingQuestions)}>
            {editingQuestions ? 'CANCEL' : 'EDIT QUESTIONS'}
          </button>
          <button className="btn btn-sm" onClick={scan} disabled={scanning}>
            {scanning ? 'SCANNING...' : 'SCAN AI VISIBILITY'}
          </button>
        </div>
      </div>
      <div style={{ padding: 20 }}>
        {/* Question editor */}
        {editingQuestions && (
          <div style={{ marginBottom: 20, padding: 16, border: '1px solid #333', background: '#111' }}>
            <div style={{ color: '#888', fontSize: 12, letterSpacing: 2, marginBottom: 8 }}>QUESTIONS (one per line, max 4)</div>
            <textarea
              value={editText}
              onChange={e => setEditText(e.target.value)}
              style={{
                width: '100%', minHeight: 100, background: '#0a0a0a', border: '1px solid #333',
                color: '#ccc', padding: 10, fontFamily: 'monospace', fontSize: 13, resize: 'vertical',
              }}
            />
            <button className="btn btn-sm" onClick={saveQuestions} style={{ marginTop: 8 }}>SAVE QUESTIONS</button>
          </div>
        )}

        {/* Summary */}
        {total > 0 && (
          <div style={{ marginBottom: 24, padding: 16, background: '#1a1a1a', border: '1px solid #333', borderRadius: 4 }}>
            <span style={{ color: '#33ff33', fontWeight: 700 }}>{cited}/{total} cited</span>
            <span style={{ color: '#888', margin: '0 12px' }}>|</span>
            <span style={{ color: '#ffb000', fontWeight: 700 }}>{mentioned}/{total} mentioned</span>
            <span style={{ color: '#888', margin: '0 12px' }}>|</span>
            <span style={{ color: '#ff4444', fontWeight: 700 }}>{absent}/{total} absent</span>
          </div>
        )}

        {/* Results grid */}
        {results.length > 0 && providers.length > 0 && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #333' }}>
                <th style={{ textAlign: 'left', padding: '10px 12px', color: '#ffb000', letterSpacing: 2, width: '35%' }}>QUESTION</th>
                {providers.map(p => (
                  <th key={p} style={{ textAlign: 'center', padding: '10px 12px', color: '#ffb000', letterSpacing: 1, fontSize: 12 }}>
                    {PROVIDER_LABELS[p] || p.toUpperCase()}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map((qr, qi) => (
                <>
                  <tr key={qi} style={{ borderBottom: '1px solid #222' }}>
                    <td style={{ padding: '12px', color: '#ccc', fontSize: 13 }}>{qr.question}</td>
                    {providers.map(p => {
                      const result = qr.results.find(r => r.provider === p)
                      const style = SCORE_STYLES[result?.score] || SCORE_STYLES.skipped
                      const cellKey = `${qi}-${p}`
                      return (
                        <td
                          key={p}
                          style={{ textAlign: 'center', padding: '12px', cursor: result?.response ? 'pointer' : 'default' }}
                          onClick={() => result?.response && setExpandedCell(expandedCell === cellKey ? null : cellKey)}
                        >
                          <span style={{ color: style.color, fontWeight: 700, fontSize: 13 }}>
                            {style.label}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                  {/* Expanded response row */}
                  {providers.map(p => {
                    const cellKey = `${qi}-${p}`
                    if (expandedCell !== cellKey) return null
                    const result = qr.results.find(r => r.provider === p)
                    if (!result?.response) return null
                    return (
                      <tr key={`${cellKey}-exp`}>
                        <td colSpan={providers.length + 1} style={{ padding: '16px', background: '#111', borderBottom: '1px solid #333' }}>
                          <div style={{ color: '#888', fontSize: 11, letterSpacing: 2, marginBottom: 8 }}>
                            {PROVIDER_LABELS[p] || p.toUpperCase()} RESPONSE
                          </div>
                          <div style={{ color: '#ccc', fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                            {result.response}
                          </div>
                          {result.excerpt && (
                            <div style={{ marginTop: 10, padding: '8px 12px', background: '#1a2a1a', border: '1px solid #333', borderRadius: 4 }}>
                              <span style={{ color: '#33ff33', fontSize: 11, letterSpacing: 2 }}>EXCERPT: </span>
                              <span style={{ color: '#ccc', fontSize: 13 }}>{result.excerpt}</span>
                            </div>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </>
              ))}
            </tbody>
          </table>
        )}

        {results.length === 0 && !scanning && (
          <div style={{ color: '#666', textAlign: 'center', padding: 40 }}>
            No visibility data yet. Hit SCAN AI VISIBILITY to query 5 AI providers.
          </div>
        )}

        {scanning && (
          <div style={{ color: '#ffb000', textAlign: 'center', padding: 40 }}>
            Querying AI providers... this takes 30-60 seconds.
          </div>
        )}
      </div>
    </div>
  )
}
