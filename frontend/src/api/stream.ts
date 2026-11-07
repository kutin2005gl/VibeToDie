import { authFetch } from './auth'
import { ApiError } from './base'
import type { Provider, Task } from './client'

// Tiến độ của một task đang chạy. `route`/`step`/`tool_call`/`tool_result` do ai-service gửi và backend
// chuyển tiếp nguyên dạng (README gốc, mục SSE của ai-service); `task`, `done`, `error` là của backend.
export type TaskEvent =
  | { event: 'task'; data: Task }
  | { event: 'route'; data: { branch: string; target: string } }
  | { event: 'step'; data: { agent: string; step: number; max_steps: number } }
  | { event: 'tool_call'; data: { agent: string; step: number; id: string; name: string } }
  | { event: 'tool_result'; data: { agent: string; step: number; id: string; is_error: boolean } }
  | { event: 'done'; data: Task }
  | { event: 'error'; data: { error: string; task?: Task } }

/**
 * Tách các event SSE ra khỏi chuỗi đã nhận. Trả về các event hoàn chỉnh và phần dư (event chưa đủ).
 * Event cách nhau bằng dòng trống; dòng bắt đầu bằng ":" là comment (heartbeat) nên bỏ qua.
 */
export function parseSse(buffer: string): { events: { event: string; data: unknown }[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: { event: string; data: unknown }[] = []
  for (const block of blocks) {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
    }
    if (!data.length) continue
    try {
      events.push({ event, data: JSON.parse(data.join('\n')) })
    } catch {
      // Event hỏng thì bỏ qua, các event sau vẫn đọc được.
    }
  }
  return { events, rest }
}

/**
 * Tạo task qua `POST /api/tasks` với `Accept: text/event-stream` và nhận tiến độ từng event. Dùng `fetch` +
 * `response.body` thay vì `EventSource` vì `EventSource` chỉ GET và không gửi được `Authorization`.
 * Trả về task đã xong (event `done`). AI lỗi thì backend lưu task `failed` và gửi event `error`: khi đó
 * hàm trả task `failed` như đường JSON thường (502 kèm task); lỗi khác thì ném ApiError. Huỷ bằng `signal`.
 */
export async function createTaskStream(
  text: string,
  provider: Provider,
  onEvent: (e: TaskEvent) => void,
  signal?: AbortSignal,
): Promise<Task> {
  let res: Response
  try {
    res = await authFetch('/api/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ text, provider }),
      signal,
    })
  } catch (e) {
    if (signal?.aborted) throw e
    throw new ApiError(0, 'Không kết nối được tới máy chủ')
  }
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.error ?? `Lỗi ${res.status}`)
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    let chunk: ReadableStreamReadResult<string>
    try {
      chunk = await reader.read()
    } catch (e) {
      if (signal?.aborted) throw e
      throw new ApiError(0, 'Kết nối bị ngắt giữa chừng')
    }
    if (chunk.done) break
    buffer += chunk.value
    const parsed = parseSse(buffer)
    buffer = parsed.rest
    for (const item of parsed.events) {
      const e = item as TaskEvent
      onEvent(e)
      if (e.event === 'done') return e.data
      if (e.event === 'error') {
        if (e.data.task) return e.data.task
        throw new ApiError(502, e.data.error)
      }
    }
  }
  throw new ApiError(0, 'Kết nối bị ngắt trước khi có kết quả')
}
