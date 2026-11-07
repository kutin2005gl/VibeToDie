import type { AgentInfo, Analytics } from '../../api/admin'
import { agentCatalog } from '../../mocks/agentCatalog'

export type AgentStats = Analytics['per_agent'][number]

/** Tên hiển thị và màu của agent; agent chưa có trong danh mục hiện tên mandate và màu trung tính. */
export function agentLook(id: string) {
  const a = agentCatalog.find((x) => x.id === id)
  return { label: a?.name ?? id, color: a?.color ?? 'var(--text-muted)' }
}

/** Số liệu chạy của agent trong báo cáo; chưa chạy lần nào thì toàn số 0. */
export function statsOf(name: string, rows: AgentStats[]): AgentStats {
  return rows.find((r) => r.agent === name) ?? {
    agent: name, sessions: 0, llm_calls: 0, tool_calls: 0, errors: 0, last: '',
    input_tokens: 0, output_tokens: 0, cost_usd: 0, unpriced_calls: 0,
  }
}

export function departmentsLabel(a: AgentInfo) {
  if (a.departments.length === 0) return 'Nội bộ'
  return a.departments.includes('*') ? 'Mọi phòng ban' : a.departments.join(', ')
}
