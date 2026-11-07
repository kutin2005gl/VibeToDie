import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'
import type { User } from '@/api/auth'
import type { MyAgent } from '@/api/sessions'
import type { AgentInfo, Analytics, ProviderChoice, DepartmentUsage, RoomDetail, RoomSummary, UserUsage } from '@/api/admin'
import { ACCESS_COOKIE, GATEWAY_URL } from './bff'

// Dữ liệu màn quản trị, lấy trên server lúc render trang (README, mục ai-service › Admin). Chỉ dùng trong
// server component: token đọc từ cookie, proxy.ts đã làm mới nó trước khi trang render.

/** Lỗi đã nói được cho admin; trang hiện câu này thay vì vỡ. */
export class AdminError extends Error {}

async function get<T>(path: string): Promise<T> {
  const access = (await cookies()).get(ACCESS_COOKIE)?.value
  if (!access) redirect('/login')
  let res: Response
  try {
    res = await fetch(`${GATEWAY_URL}${path}`, { headers: { authorization: `Bearer ${access}` }, cache: 'no-store' })
  } catch {
    throw new AdminError('Không kết nối được tới máy chủ')
  }
  // Token bị thu hồi giữa chừng: đăng nhập lại
  if (res.status === 401) redirect('/login')
  if (res.status === 403) throw new AdminError('Chỉ quản trị viên được xem trang này')
  if (res.status === 429) throw new AdminError('Tải quá nhiều lần, vui lòng đợi một phút rồi tải lại')
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new AdminError(typeof body.detail === 'string' ? body.detail : `Lỗi ${res.status}`)
  return body as T
}

export const departmentUsage = () => get<DepartmentUsage[]>('/api/admin/usage')

export const userUsage = (department: string) =>
  get<UserUsage[]>(`/api/admin/usage/${encodeURIComponent(department)}`)

export const provider = () => get<ProviderChoice>('/api/admin/provider')

export const agents = () => get<AgentInfo[]>('/api/admin/agents')

/** Agent riêng của chính tài khoản đang đăng nhập (nhân viên và admin đều có), không phải của cả hệ thống. */
export const myAgents = () => get<MyAgent[]>('/api/sessions/agents')

export const myAgentDetail = (id: number) =>
  get<{ agent: AgentInfo; stats: Analytics['per_agent'][number] }>(`/api/sessions/agents/${id}`)

export const analytics = (days: number) => get<Analytics>(`/api/admin/analytics?days=${days}`)

export const roomsOf = (userId: string) =>
  get<RoomSummary[]>(`/api/admin/users/${encodeURIComponent(userId)}/sessions`)

export const roomDetail = (id: number) => get<RoomDetail>(`/api/admin/sessions/${id}`)

/** Mọi tài khoản (user-service, chỉ admin), để biết tên và phòng ban hiện tại. */
export const listUsers = () => get<User[]>('/api/users/users')

/** Dữ liệu của trang, hoặc câu báo lỗi cho admin. */
export async function load<T>(work: () => Promise<T>): Promise<{ data: T } | { error: string }> {
  try {
    return { data: await work() }
  } catch (e) {
    if (e instanceof AdminError) return { error: e.message }
    throw e // redirect() và lỗi thật đi tiếp
  }
}
