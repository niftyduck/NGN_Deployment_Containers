import { useState } from 'react'

const S = {
  card: {
    border: '1px solid #30363d',
    borderRadius: 8,
    padding: '14px 16px',
    background: '#161b22',
  },
  title: {
    fontWeight: 'bold',
    marginBottom: 12,
    color: '#388bfd',
    fontSize: 12,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  btn: (bg = '#388bfd') => ({
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 5,
    padding: '6px 14px',
    cursor: 'pointer',
    fontWeight: 'bold',
    fontSize: 12,
  }),
  select: {
    background: '#0d1117',
    color: '#e6edf3',
    border: '1px solid #30363d',
    borderRadius: 5,
    padding: '5px 8px',
    width: '100%',
  },
  label: { fontSize: 11, color: '#8b949e', marginBottom: 4 },
  row: { display: 'flex', alignItems: 'center', gap: 8 },
}

const APP_TYPE_COLOR = { webserver: '#3fb950', database: '#d2a8ff', auth: '#f0883e' }
const SERVICES = ['shop', 'banking']

export default function DeployPanel({ apps, hosts, onDeploy, onStop, onAddRequirement, loading }) {
  const [service, setService] = useState('shop')
  const [srcApp, setSrcApp] = useState('')
  const [dstApp, setDstApp] = useState('')
  const [msg, setMsg] = useState(null)

  const running = Object.values(apps).filter(a => a.status === 'running')

  const handleDeploy = async () => {
    setMsg(null)
    try {
      const res = await onDeploy(service)
      const summary = Object.entries(res.deployed)
        .map(([type, info]) => `${type} → ${info.host}`)
        .join(', ')
      setMsg({ ok: true, text: `Deployed: ${summary}` })
    } catch (e) {
      setMsg({ ok: false, text: e.message })
    }
  }

  const handleStop = async (appId) => {
    setMsg(null)
    try {
      await onStop(appId)
    } catch (e) {
      setMsg({ ok: false, text: e.message })
    }
  }

  const handleAddReq = async () => {
    if (!srcApp || !dstApp || srcApp === dstApp) return
    setMsg(null)
    try {
      const res = await onAddRequirement(srcApp, dstApp)
      setMsg({ ok: true, text: `Flows installed: ${res.flow_ids?.length ?? 0}` })
      setSrcApp('')
      setDstApp('')
    } catch (e) {
      setMsg({ ok: false, text: e.message })
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Status banner */}
      {msg && (
        <div style={{
          padding: '8px 12px', borderRadius: 5, fontSize: 12,
          background: msg.ok ? 'rgba(63,185,80,0.12)' : 'rgba(248,81,73,0.12)',
          border: `1px solid ${msg.ok ? '#3fb950' : '#f85149'}`,
          color: msg.ok ? '#3fb950' : '#f85149',
        }}>
          {msg.text}
        </div>
      )}

      {/* Deploy */}
      <div style={S.card}>
        <div style={S.title}>Deploy Service</div>
        <div style={S.row}>
          <select
            value={service}
            onChange={e => setService(e.target.value)}
            style={{ ...S.select, width: 'auto', flexShrink: 0 }}
          >
            {SERVICES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button style={S.btn()} disabled={loading} onClick={handleDeploy}>
            {loading ? '…' : 'Deploy'}
          </button>
        </div>
        <div style={{ fontSize: 11, color: '#6e7681', marginTop: 8 }}>
          {service === 'banking'
            ? 'Deploys webserver + auth + database onto three hosts'
            : 'Deploys webserver + database onto two hosts'}
        </div>
      </div>

      {/* Running apps */}
      <div style={S.card}>
        <div style={S.title}>Running Apps ({running.length})</div>
        {running.length === 0
          ? <div style={{ color: '#6e7681', fontSize: 12 }}>No apps deployed yet</div>
          : running.map(app => {
              const ip = hosts[app.host]?.ip ?? '—'
              return (
                <div key={app.app_id} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '6px 0', borderBottom: '1px solid #21262d',
                }}>
                  <div>
                    <span style={{ color: APP_TYPE_COLOR[app.type] ?? '#e6edf3', fontWeight: 'bold' }}>
                      {app.type}
                    </span>
                    {'  '}
                    <span style={{ color: '#8b949e' }}>{app.app_id}</span>
                    <br />
                    <span style={{ fontSize: 11, color: '#6e7681' }}>
                      {app.host}  {ip}  [{app.service}]
                    </span>
                  </div>
                  <button
                    style={S.btn('#b62324')}
                    disabled={loading}
                    onClick={() => handleStop(app.app_id)}
                  >
                    Stop
                  </button>
                </div>
              )
            })
        }
      </div>

      {/* Add requirement */}
      <div style={S.card}>
        <div style={S.title}>Add Connectivity Requirement</div>
        {running.length < 2
          ? <div style={{ color: '#6e7681', fontSize: 12 }}>Need at least 2 running apps</div>
          : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div>
                <div style={S.label}>Source app</div>
                <select value={srcApp} onChange={e => setSrcApp(e.target.value)} style={S.select}>
                  <option value="">— select —</option>
                  {running.map(a => (
                    <option key={a.app_id} value={a.app_id}>
                      {a.app_id}  ({a.type} @ {a.host})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div style={S.label}>Destination app</div>
                <select value={dstApp} onChange={e => setDstApp(e.target.value)} style={S.select}>
                  <option value="">— select —</option>
                  {running.filter(a => a.app_id !== srcApp).map(a => (
                    <option key={a.app_id} value={a.app_id}>
                      {a.app_id}  ({a.type} @ {a.host})
                    </option>
                  ))}
                </select>
              </div>
              <button
                style={S.btn('#238636')}
                disabled={loading || !srcApp || !dstApp}
                onClick={handleAddReq}
              >
                Install Flows
              </button>
            </div>
          )
        }
      </div>
    </div>
  )
}
