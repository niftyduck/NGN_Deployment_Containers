import { useRef, useEffect, useState, useMemo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'

// Fixed relative positions [x%, y%] for each node in the tree topology
const POSITIONS = {
  score: [0.50, 0.18],
  s1:    [0.22, 0.42],
  s2:    [0.50, 0.42],
  s3:    [0.78, 0.42],
  h1:    [0.12, 0.72],
  h2:    [0.32, 0.72],
  h3:    [0.40, 0.72],
  h4:    [0.60, 0.72],
  h5:    [0.68, 0.72],
  h6:    [0.88, 0.72],
}

function nodeColor(node) {
  if (node.type === 'switch') return '#388bfd'
  const n = node.app_count ?? 0
  if (n === 0) return '#6e7681'
  if (n === 1) return '#3fb950'
  return '#f78166'  // 2/2 full
}

function paintNode(node, ctx, globalScale) {
  const isSwitch = node.type === 'switch'
  const r = isSwitch ? 10 : 7
  const color = nodeColor(node)

  if (isSwitch) {
    ctx.beginPath()
    ctx.rect(node.x - r, node.y - r, r * 2, r * 2)
  } else {
    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
  }
  ctx.fillStyle = color
  ctx.fill()
  ctx.strokeStyle = '#e6edf3'
  ctx.lineWidth = 0.8 / globalScale
  ctx.stroke()

  const fontSize = Math.max(4, 11 / globalScale)
  ctx.font = `bold ${fontSize}px monospace`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = '#e6edf3'
  ctx.fillText(node.id, node.x, node.y + r + fontSize * 0.9)
}

const LEGEND = [
  { color: '#6e7681', label: '● empty host' },
  { color: '#3fb950', label: '● 1 app' },
  { color: '#f78166', label: '● 2 apps (full)' },
  { color: '#388bfd', label: '■ switch' },
  { color: '#00d2ff', label: '━ active flow' },
]

export default function TopologyGraph({ topology }) {
  const containerRef = useRef(null)
  const [dims, setDims] = useState({ w: 800, h: 600 })

  useEffect(() => {
    if (!containerRef.current) return
    const obs = new ResizeObserver(([e]) => {
      setDims({ w: e.contentRect.width, h: e.contentRect.height })
    })
    obs.observe(containerRef.current)
    return () => obs.disconnect()
  }, [])

  // Pin every node to its fixed position scaled to container dimensions
  const graphData = useMemo(() => {
    const nodes = (topology.nodes ?? []).map(n => {
      const pos = POSITIONS[n.id]
      return {
        ...n,
        fx: pos ? pos[0] * dims.w : dims.w / 2,
        fy: pos ? pos[1] * dims.h : dims.h / 2,
      }
    })
    return { nodes, links: topology.links ?? [] }
  }, [topology, dims])

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', background: '#0d1117' }}>
      {/* Legend */}
      <div style={{
        position: 'absolute', top: 10, left: 10, zIndex: 10,
        background: 'rgba(13,17,23,0.85)', borderRadius: 6, padding: '8px 12px',
        border: '1px solid #30363d',
      }}>
        <div style={{ color: '#8b949e', fontSize: 11, marginBottom: 6, fontWeight: 'bold' }}>
          NETWORK TOPOLOGY
        </div>
        {LEGEND.map(({ color, label }) => (
          <div key={label} style={{ color, fontSize: 11, lineHeight: 1.7 }}>{label}</div>
        ))}
      </div>

      <div ref={containerRef} style={{ width: '100%', height: '100%' }}>
        <ForceGraph2D
          width={dims.w}
          height={dims.h}
          graphData={graphData}
          backgroundColor="#0d1117"
          cooldownTicks={1}
          enableNodeDrag={false}
          // Node rendering
          nodeCanvasObject={paintNode}
          nodeCanvasObjectMode={() => 'replace'}
          nodeLabel={n =>
            n.type === 'host'
              ? `${n.id}  ${n.ip}  (${n.app_count ?? 0} app)`
              : n.id
          }
          // Link rendering
          linkColor={l => l.active ? '#00d2ff' : '#30363d'}
          linkWidth={l => l.active ? 2.5 : 1}
          linkDirectionalParticles={l => l.active ? 5 : 0}
          linkDirectionalParticleWidth={2}
          linkDirectionalParticleSpeed={0.006}
          linkDirectionalParticleColor={() => '#00d2ff'}
        />
      </div>
    </div>
  )
}
