import { useState, useEffect, useCallback, useRef } from 'react'
import TopologyGraph from './components/TopologyGraph'
import DeployPanel from './components/DeployPanel'
import FlowTable from './components/FlowTable'
import * as api from './api'

const POLL_MS = 3000

const EMPTY_TOPOLOGY = { nodes: [], links: [] }
const EMPTY_STATE = { hosts: {}, apps: {}, requirements: {}, flows: {} }

export default function App() {
  const [topology, setTopology]   = useState(EMPTY_TOPOLOGY)
  const [appState, setAppState]   = useState(EMPTY_STATE)
  const [loading, setLoading]     = useState(false)
  const [backendOk, setBackendOk] = useState(true)
  const [logs, setLogs]           = useState([])
  const wsRef = useRef(null)

  // ── polling ──────────────────────────────────────────────────────────────
  const refresh = useCallback(async () => {
    try {
      const [topo, st] = await Promise.all([api.getTopology(), api.getState()])
      setTopology(topo)
      setAppState(st)
      setBackendOk(true)
    } catch {
      setBackendOk(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [refresh])

  // ── WebSocket log stream ──────────────────────────────────────────────────
  useEffect(() => {
    function connect() {
      const ws = new WebSocket('ws://localhost:8000/logs')
      wsRef.current = ws
      ws.onmessage = (e) => {
        if (!e.data) return
        setLogs(prev => [...prev.slice(-199), e.data])
      }
      ws.onclose = () => setTimeout(connect, 3000)
    }
    connect()
    return () => wsRef.current?.close()
  }, [])

  // ── mutation helpers (loading gate + refresh) ─────────────────────────────
  const mutate = useCallback(async (fn) => {
    setLoading(true)
    try {
      const result = await fn()
      await refresh()
      return result
    } finally {
      setLoading(false)
    }
  }, [refresh])

  const handleDeploy          = (service)         => mutate(() => api.deployService(service))
  const handleStop            = (appId)            => mutate(() => api.stopApp(appId))
  const handleAddRequirement  = (srcId, dstId)     => mutate(() => api.addRequirement(srcId, dstId))
  const handleDelRequirement  = (reqId)            => mutate(() => api.deleteRequirement(reqId))
  const handleDiscover        = ()                 => mutate(() => api.discoverDpids())

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>

      {/* ── Header ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 16px', background: '#161b22',
        borderBottom: '1px solid #30363d', flexShrink: 0,
      }}>
        <div style={{ fontWeight: 'bold', color: '#388bfd', letterSpacing: '0.05em' }}>
          NGN DEPLOYMENT ORCHESTRATOR
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ fontSize: 11, color: backendOk ? '#3fb950' : '#f85149' }}>
            {backendOk ? '● connected' : '● backend offline'}
          </div>
          <button
            onClick={handleDiscover}
            disabled={loading}
            style={{
              background: 'transparent', color: '#8b949e',
              border: '1px solid #30363d', borderRadius: 4,
              padding: '3px 10px', cursor: 'pointer', fontSize: 11,
            }}
          >
            re-discover dpids
          </button>
        </div>
      </div>

      {/* ── Main layout ── */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>

        {/* Left: topology graph */}
        <div style={{ flex: '0 0 62%', borderRight: '1px solid #30363d', overflow: 'hidden' }}>
          <TopologyGraph topology={topology} />
        </div>

        {/* Right: controls + log */}
        <div style={{
          flex: '0 0 38%', display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
        }}>
          {/* Scrollable control panels */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <DeployPanel
              apps={appState.apps}
              hosts={appState.hosts}
              loading={loading}
              onDeploy={handleDeploy}
              onStop={handleStop}
              onAddRequirement={handleAddRequirement}
            />
            <FlowTable
              requirements={appState.requirements}
              apps={appState.apps}
              flows={appState.flows}
              hosts={appState.hosts}
              onDeleteRequirement={handleDelRequirement}
            />
          </div>

          {/* Log pane */}
          <div style={{
            height: 150, borderTop: '1px solid #30363d',
            background: '#0d1117', overflowY: 'auto',
            padding: '6px 10px', flexShrink: 0,
          }}>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>LOGS</div>
            {logs.length === 0
              ? <div style={{ fontSize: 11, color: '#6e7681' }}>waiting for backend…</div>
              : logs.map((l, i) => (
                <div key={i} style={{ fontSize: 11, color: '#6e7681', lineHeight: 1.5, fontFamily: 'monospace' }}>
                  {l}
                </div>
              ))
            }
          </div>
        </div>
      </div>
    </div>
  )
}
