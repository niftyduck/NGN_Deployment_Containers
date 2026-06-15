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
  th: { padding: '4px 8px', color: '#8b949e', fontWeight: 'normal', textAlign: 'left' },
  td: { padding: '6px 8px', borderTop: '1px solid #21262d', verticalAlign: 'middle' },
  badge: (color) => ({
    display: 'inline-block',
    background: color,
    color: '#0d1117',
    borderRadius: 3,
    padding: '1px 6px',
    fontSize: 11,
    fontWeight: 'bold',
  }),
}

function etherType(dlType) {
  if (dlType === 2054) return 'ARP'
  return 'TCP'
}

export default function FlowTable({ requirements, apps, flows, hosts, onDeleteRequirement }) {
  const reqs = Object.values(requirements)

  function pathLabel(req) {
    const src = apps[req.src_app]
    const dst = apps[req.dst_app]
    if (!src || !dst) return '?'
    const sip = hosts[src.host]?.ip ?? src.host
    const dip = hosts[dst.host]?.ip ?? dst.host
    return `${src.host}(${sip}) → ${dst.host}(${dip})`
  }

  return (
    <div style={S.card}>
      <div style={S.title}>Requirements & Active Flows ({reqs.length})</div>

      {reqs.length === 0
        ? <div style={{ color: '#6e7681', fontSize: 12 }}>No connectivity requirements installed</div>
        : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                <th style={S.th}>ID</th>
                <th style={S.th}>Path</th>
                <th style={S.th}>Flows</th>
                <th style={S.th}></th>
              </tr>
            </thead>
            <tbody>
              {reqs.map(req => (
                <tr key={req.req_id}>
                  <td style={S.td}>
                    <span style={{ color: '#8b949e', fontFamily: 'monospace' }}>{req.req_id}</span>
                  </td>
                  <td style={S.td}>
                    <span style={{ color: '#00d2ff' }}>{pathLabel(req)}</span>
                  </td>
                  <td style={{ ...S.td, textAlign: 'center' }}>
                    <span style={S.badge('#3fb950')}>{req.flow_ids?.length ?? 0}</span>
                  </td>
                  <td style={S.td}>
                    <button
                      onClick={() => onDeleteRequirement(req.req_id)}
                      style={{
                        background: 'transparent',
                        color: '#f85149',
                        border: '1px solid #f85149',
                        borderRadius: 4,
                        padding: '3px 10px',
                        cursor: 'pointer',
                        fontSize: 11,
                      }}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      }

      {/* Expandable raw flow entries */}
      {Object.keys(flows).length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary style={{
            color: '#8b949e', cursor: 'pointer', fontSize: 11,
            padding: '4px 0', borderTop: '1px solid #21262d',
          }}>
            ▸ raw flow entries ({Object.keys(flows).length})
          </summary>
          <div style={{ marginTop: 8, maxHeight: 180, overflowY: 'auto' }}>
            {Object.values(flows).map(f => (
              <div key={f.flow_id} style={{
                fontSize: 11, padding: '2px 0', fontFamily: 'monospace',
                color: '#6e7681', display: 'flex', gap: 8,
              }}>
                <span style={{ color: '#388bfd' }}>dpid:{f.dpid}</span>
                <span style={{ color: '#e6edf3' }}>{f.src_ip} → {f.dst_ip}</span>
                <span style={S.badge(f.match?.dl_type === 2054 ? '#d2a8ff' : '#79c0ff')}>
                  {etherType(f.match?.dl_type)}
                </span>
                <span>out:{f.actions?.[0]?.port}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}
