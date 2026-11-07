import { authFetch } from './auth'
import { ApiError } from './base'
import type { SessionItem } from './sessions'

// Dạng dữ liệu của ai-service `/api/admin/*` (README, mục ai-service); các màn quản trị lấy trên server ở
// src/server/admin.ts, còn room của chính admin lấy trên trình duyệt bằng getRoomDetail.
export interface Usage {
  input_tokens: number
  output_tokens: number
  cost_usd: number
  /** Số lượt gọi model chưa có giá trong models.json: chi phí thật cao hơn `cost_usd`. */
  unpriced_calls: number
}

export interface DepartmentUsage extends Usage {
  department: string
  sessions: number
}

export interface UserUsage extends Usage {
  user_id: string
  sessions: number
}

export interface RoomSummary extends Usage {
  id: number
  title: string
  provider: string
  status: 'running' | 'waiting' | 'done' | 'failed'
  departments: string[]
  created_at: string
  updated_at: string
  deleted_at: string | null
  runs: number
}

/** Một event của lượt chạy: các event SSE của `/run` cộng phần chỉ admin thấy (README, mục Admin). */
export type TraceEvent = { event: string; at: string; agent?: string; step?: number } & Record<string, unknown>

export interface Run extends Usage {
  run: number
  started_at: string
  trace: TraceEvent[]
}

export interface RoomDetail extends Omit<RoomSummary, 'runs' | keyof Usage> {
  user_id: string
  items: SessionItem[]
  runs: Run[]
}

/** Room kèm trace đầy đủ, cho room của chính admin trên màn /rooms. */
export async function getRoomDetail(id: number): Promise<RoomDetail> {
  const res = await authFetch(`/api/admin/sessions/${id}`)
  if (!res.ok) throw new ApiError(res.status, `Lỗi ${res.status}`)
  return res.json()
}

/** Phòng ban của các room lưu trước khi ai-service ghi phòng ban. */
export const UNKNOWN_DEPARTMENT = '-'

/** Báo cáo `/api/admin/analytics` (README, mục ai-service › Admin): cộng từ trace các lượt chạy trong `days` ngày; lấy trên server ở src/server/admin.ts. */
export interface AnalyticsDay extends Usage {
  /** `MM-DD`, giờ Việt Nam */
  day: string
  runs: number
  events: number
  by_agent: Record<string, number>
  by_type: Record<string, number>
}

export interface Analytics {
  days: number
  stats: Usage & {
    agents: number
    rooms: number
    runs: number
    models: number
    llm_calls: number
    tool_calls: number
    errors: number
  }
  per_day: AnalyticsDay[]
  per_agent: (Usage & { agent: string; sessions: number; llm_calls: number; tool_calls: number; errors: number; last: string })[]
  per_model: (Usage & { model: string; calls: number })[]
  per_room: (Usage & { id: number; title: string; runs: number; last: string })[]
  top_tools: { name: string; count: number }[]
}

/** Một agent trong `/api/admin/agents` (README, mục ai-service › Admin): nội dung file mandate của nó. */
export interface AgentInfo {
  name: string
  description: string
  tools: string[]
  includes: string[]
  /** Phòng ban được định tuyến tới agent; `*` là mọi phòng ban, rỗng là agent nội bộ (không định tuyến tới). */
  departments: string[]
  model_tier: 'strong' | 'standard' | 'cheap'
  effort: 'low' | 'medium' | 'high'
  /** Id model config theo từng provider profile, ví dụ `{ anthropic: 'claude-sonnet' }`. */
  models: Record<string, string>
  prompt: string
}

/** Provider mọi request đang chạy trên đó và các provider admin chọn được (`/api/admin/provider`). */
export interface ProviderChoice {
  provider: string
  available: string[]
}

export async function setProvider(provider: string): Promise<ProviderChoice> {
  let res: Response
  try {
    res = await authFetch('/api/admin/provider', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    })
  } catch {
    throw new ApiError(0, 'Không kết nối được tới máy chủ')
  }
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(res.status, typeof body.detail === 'string' ? body.detail : `Lỗi ${res.status}`)
  return body
}
