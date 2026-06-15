const BASE = "http://localhost:8000"

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options)
  const data = await res.json()
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
  return data
}

export const getTopology = () => request("/topology")
export const getState    = () => request("/state")
export const getFlows    = () => request("/flows")
export const discoverDpids = () => request("/admin/discover", { method: "POST" })

export const deployService = (service) =>
  request("/services/deploy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ service }),
  })

export const stopApp = (appId) =>
  request(`/apps/${appId}/stop`, { method: "POST" })

export const addRequirement = (srcAppId, dstAppId) =>
  request("/requirements", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ src_app_id: srcAppId, dst_app_id: dstAppId }),
  })

export const deleteRequirement = (reqId) =>
  request(`/requirements/${reqId}`, { method: "DELETE" })
