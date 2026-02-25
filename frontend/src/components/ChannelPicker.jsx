const CHANNELS = [
  { key: 'linkedin', label: 'LinkedIn' },
  { key: 'x_thread', label: 'X Thread' },
  { key: 'facebook', label: 'Facebook' },
  { key: 'blog', label: 'Blog' },
  { key: 'devto', label: 'Dev.to' },
  { key: 'github_gist', label: 'Gist' },
  { key: 'release_email', label: 'Email' },
  { key: 'newsletter', label: 'Newsletter' },
]

const STORAGE_KEY = (orgId) => `pr_channels_${orgId || 0}`

export function loadSavedChannels(orgId) {
  try {
    const saved = localStorage.getItem(STORAGE_KEY(orgId))
    if (saved) return JSON.parse(saved)
  } catch { /* ignore */ }
  return ['linkedin', 'blog', 'devto', 'release_email']
}

export function saveChannels(orgId, channels) {
  localStorage.setItem(STORAGE_KEY(orgId), JSON.stringify(channels))
}

export default function ChannelPicker({ selected, onChange }) {
  const toggle = (key) => {
    const set = new Set(selected)
    if (set.has(key)) set.delete(key)
    else set.add(key)
    onChange([...set])
  }

  return (
    <div className="channel-picker">
      {CHANNELS.map(ch => (
        <button
          key={ch.key}
          className={`channel-toggle ${selected.includes(ch.key) ? 'on' : ''}`}
          onClick={() => toggle(ch.key)}
          type="button"
        >
          {ch.label}
        </button>
      ))}
    </div>
  )
}
