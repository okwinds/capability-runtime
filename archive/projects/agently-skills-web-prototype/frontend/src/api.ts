export type RunMode = 'demo' | 'real'

export type RunEvent = {
  ts: string
  run_id: string
  type: string
  payload: Record<string, unknown>
}

export type RunSnapshot = {
  run_id: string
  status: 'queued' | 'running' | 'waiting_approval' | 'completed' | 'failed'
  final_output: string
  node_report?: Record<string, unknown> | null
  events_path?: string | null
  error?: string | null
}

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export async function getMeta(): Promise<Record<string, unknown>> {
  const r = await fetch(`${API_BASE}/api/meta`)
  if (!r.ok) throw new Error(`meta failed: ${r.status}`)
  return r.json()
}

export async function startSkillTask(task: string, mode: RunMode): Promise<string> {
  const r = await fetch(`${API_BASE}/api/runs/skill-task`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ task, mode }),
  })
  if (!r.ok) throw new Error(`start run failed: ${r.status}`)
  const j = (await r.json()) as { run_id: string }
  return j.run_id
}

export async function getRun(runId: string): Promise<RunSnapshot> {
  const r = await fetch(`${API_BASE}/api/runs/${encodeURIComponent(runId)}`)
  if (!r.ok) throw new Error(`get run failed: ${r.status}`)
  return r.json()
}

export async function listPendingApprovals(): Promise<
  {
    approval_id: string
    run_id: string
    call_id: string
    question: string
    choices: string[]
    context: Record<string, unknown>
  }[]
> {
  const r = await fetch(`${API_BASE}/api/approvals/pending`)
  if (!r.ok) throw new Error(`pending approvals failed: ${r.status}`)
  const j = (await r.json()) as { items: any[] }
  return j.items ?? []
}

export async function decideApproval(approvalId: string, decision: 'approve' | 'deny', reason: string) {
  const r = await fetch(`${API_BASE}/api/approvals/${encodeURIComponent(approvalId)}/decision`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ decision, reason }),
  })
  if (!r.ok) throw new Error(`decide approval failed: ${r.status}`)
  return r.json()
}

export function subscribeRunEvents(runId: string, onEvent: (ev: RunEvent) => void) {
  const es = new EventSource(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/events`)
  es.onmessage = (msg) => {
    try {
      const ev = JSON.parse(msg.data) as RunEvent
      onEvent(ev)
    } catch {
      // ignore
    }
  }
  return () => es.close()
}

