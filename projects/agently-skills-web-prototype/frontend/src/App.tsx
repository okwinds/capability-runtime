import React, { useEffect, useMemo, useState } from 'react'
import {
  decideApproval,
  getMeta,
  getRun,
  listPendingApprovals,
  startSkillTask,
  subscribeRunEvents,
  type RunEvent,
  type RunMode,
  type RunSnapshot,
} from './api'

function pretty(obj: unknown) {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

export default function App() {
  const [meta, setMeta] = useState<Record<string, unknown> | null>(null)
  const [task, setTask] = useState('demo: trigger tool_calls + approvals')
  const [mode, setMode] = useState<RunMode>('demo')
  const [runId, setRunId] = useState<string>('')
  const [events, setEvents] = useState<RunEvent[]>([])
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null)
  const [pending, setPending] = useState<any[]>([])
  const [error, setError] = useState<string>('')

  useEffect(() => {
    getMeta().then(setMeta).catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    const id = setInterval(() => {
      listPendingApprovals().then(setPending).catch(() => {})
    }, 800)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!runId) return
    setEvents([])
    setSnapshot(null)
    setError('')

    const unsub = subscribeRunEvents(runId, (ev) => {
      setEvents((xs) => xs.concat([ev]))
      if (ev.type === 'run_completed' || ev.type === 'run_failed') {
        getRun(runId).then(setSnapshot).catch((e) => setError(String(e)))
      }
    })

    const poll = setInterval(() => {
      getRun(runId).then(setSnapshot).catch(() => {})
    }, 1200)

    return () => {
      unsub()
      clearInterval(poll)
    }
  }, [runId])

  const headerStyle: React.CSSProperties = { fontSize: 18, fontWeight: 700, marginBottom: 8 }
  const cardStyle: React.CSSProperties = {
    border: '1px solid #e5e7eb',
    borderRadius: 12,
    padding: 12,
    background: 'white',
  }

  return (
    <div style={{ fontFamily: 'ui-sans-serif, system-ui', background: '#f8fafc', minHeight: '100vh' }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: 20, display: 'grid', gap: 12 }}>
        <div style={{ ...cardStyle }}>
          <div style={headerStyle}>全量能力验证 Web 原型</div>
          <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.5 }}>
            默认使用离线 demo（scripted stream），验证 tool_calls + approvals + 事件证据链。真实模式需要你本机安装并配置
            `agently`。
          </div>
          {error ? <div style={{ marginTop: 8, color: '#b91c1c' }}>{error}</div> : null}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div style={{ ...cardStyle }}>
            <div style={headerStyle}>发起 Run（Skill Task）</div>
            <div style={{ display: 'grid', gap: 8 }}>
              <label style={{ display: 'grid', gap: 6 }}>
                <div style={{ fontSize: 12, color: '#334155' }}>Task</div>
                <textarea
                  value={task}
                  onChange={(e) => setTask(e.target.value)}
                  rows={3}
                  style={{ width: '100%', padding: 8, borderRadius: 10, border: '1px solid #cbd5e1' }}
                />
              </label>
              <label style={{ display: 'grid', gap: 6 }}>
                <div style={{ fontSize: 12, color: '#334155' }}>Mode</div>
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value as RunMode)}
                  style={{ padding: 8, borderRadius: 10, border: '1px solid #cbd5e1' }}
                >
                  <option value="demo">demo（离线）</option>
                  <option value="real">real（需 agently）</option>
                </select>
              </label>
              <button
                onClick={() => {
                  startSkillTask(task, mode)
                    .then((id) => setRunId(id))
                    .catch((e) => setError(String(e)))
                }}
                style={{
                  padding: '10px 12px',
                  borderRadius: 10,
                  border: '1px solid #0f172a',
                  background: '#0f172a',
                  color: 'white',
                  cursor: 'pointer',
                }}
              >
                开始
              </button>
              {runId ? (
                <div style={{ fontSize: 12, color: '#334155' }}>
                  run_id: <code>{runId}</code>
                </div>
              ) : null}
            </div>
          </div>

          <div style={{ ...cardStyle }}>
            <div style={headerStyle}>Pending Approvals</div>
            {pending.length === 0 ? (
              <div style={{ fontSize: 13, color: '#64748b' }}>暂无待审批</div>
            ) : (
              <div style={{ display: 'grid', gap: 10 }}>
                {pending.map((p) => (
                  <div
                    key={p.approval_id}
                    style={{ border: '1px solid #e2e8f0', borderRadius: 10, padding: 10, background: '#f8fafc' }}
                  >
                    <div style={{ fontSize: 12, color: '#0f172a' }}>
                      <code>{p.approval_id}</code>（run: <code>{p.run_id}</code>）
                    </div>
                    <div style={{ marginTop: 6, fontSize: 13 }}>{p.question}</div>
                    <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                      <button
                        onClick={() => decideApproval(p.approval_id, 'approve', 'ok').catch((e) => setError(String(e)))}
                        style={{
                          padding: '8px 10px',
                          borderRadius: 10,
                          border: '1px solid #16a34a',
                          background: '#16a34a',
                          color: 'white',
                          cursor: 'pointer',
                        }}
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => decideApproval(p.approval_id, 'deny', 'deny').catch((e) => setError(String(e)))}
                        style={{
                          padding: '8px 10px',
                          borderRadius: 10,
                          border: '1px solid #dc2626',
                          background: '#dc2626',
                          color: 'white',
                          cursor: 'pointer',
                        }}
                      >
                        Deny
                      </button>
                    </div>
                    <details style={{ marginTop: 8 }}>
                      <summary style={{ fontSize: 12, color: '#334155', cursor: 'pointer' }}>context</summary>
                      <pre style={{ marginTop: 8, fontSize: 12, overflowX: 'auto' }}>{pretty(p.context)}</pre>
                    </details>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div style={{ ...cardStyle }}>
            <div style={headerStyle}>事件流（SSE）</div>
            <pre style={{ fontSize: 12, overflowX: 'auto', maxHeight: 360 }}>
              {events.map((e) => `${e.ts} ${e.type}`).join('\n')}
            </pre>
          </div>
          <div style={{ ...cardStyle }}>
            <div style={headerStyle}>Run Snapshot</div>
            <pre style={{ fontSize: 12, overflowX: 'auto', maxHeight: 360 }}>{pretty(snapshot)}</pre>
          </div>
        </div>

        <div style={{ ...cardStyle }}>
          <div style={headerStyle}>Meta（冻结核验）</div>
          <pre style={{ fontSize: 12, overflowX: 'auto' }}>{pretty(meta)}</pre>
        </div>
      </div>
    </div>
  )
}

