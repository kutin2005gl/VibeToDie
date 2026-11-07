import { authFetch } from './auth'
import { ApiError } from './base'

export { ApiError, setApiBase } from './base'

export type Provider = 'anthropic' | 'openai' | 'deepseek' | 'fake'
export type TaskStatus = 'running' | 'awaiting_approval' | 'approved' | 'rejected' | 'failed'

// Khớp backend/internal/task.Task và bảng API trong README gốc.
export interface Task {
  id: number
  text: string
  provider: Provider
  status: TaskStatus
  model?: string
  output?: string
  error?: string
  decision?: 'yes' | 'no'
  created_at: string
  updated_at: string
}

async function request(path: string, init?: RequestInit): Promise<Task> {
  let res: Response
  try {
    res = await authFetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    })
  } catch {
    throw new ApiError(0, 'Không kết nối được tới máy chủ')
  }
  const body = await res.json().catch(() => ({}))
  // 502 vẫn trả task `failed` kèm lỗi AI nên coi đó là kết quả, không phải ngoại lệ.
  if (res.ok || (res.status === 502 && body.status === 'failed')) return body as Task
  throw new ApiError(res.status, body.error ?? `Lỗi ${res.status}`)
}

// TODO: từ 25/10 task chạy bất đồng bộ, đổi sang trả `running` rồi dùng getTask để polling.
export function createTask(text: string, provider: Provider) {
  return request('/api/tasks', { method: 'POST', body: JSON.stringify({ text, provider }) })
}

export function getTask(id: number) {
  return request(`/api/tasks/${id}`)
}

export function decideTask(id: number, approve: boolean) {
  return request(`/api/tasks/${id}/decision`, { method: 'POST', body: JSON.stringify({ approve }) })
}
