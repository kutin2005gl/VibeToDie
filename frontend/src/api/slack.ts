import { authFetch } from './auth'
import { ApiError } from './base'

export interface SlackLinkCode {
  code: string
  expires_at: string
}

/** Tài khoản Slack của một liên kết, do bot báo lúc đổi mã; chỉ để hiển thị. */
export interface SlackAccount {
  slack_user_id: string
  user_name?: string
  /** Họ tên đầy đủ trên Slack; không có nếu app chưa được cấp quyền users:read. */
  real_name?: string
  team_id?: string
  team_domain?: string
}

export interface SlackLink {
  linked_at: string
  /** Không có với liên kết tạo trước khi bot báo tài khoản. */
  account?: SlackAccount
}

export interface SlackLinkStatus {
  linked: boolean
  linked_at?: string
  links: SlackLink[]
}

async function slackFetch(method: 'GET' | 'DELETE', failure: string): Promise<Response> {
  let res: Response
  try {
    res = await authFetch('/api/users/slack-links', { method, cache: 'no-store' })
  } catch {
    throw new ApiError(0, 'Không kết nối được tới máy chủ. Vui lòng thử lại.')
  }
  if (res.status === 401) throw new ApiError(401, 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')
  if (!res.ok) throw new ApiError(res.status, failure)
  return res
}

export async function getSlackLinkStatus(): Promise<SlackLinkStatus> {
  const res = await slackFetch('GET', 'Không kiểm tra được trạng thái liên kết Slack.')
  const data = await res.json() as Partial<SlackLinkStatus>
  const links = Array.isArray(data.links) ? data.links : []
  return { linked: data.linked === true, linked_at: data.linked_at, links }
}

export async function unlinkSlack(): Promise<void> {
  await slackFetch('DELETE', 'Không hủy được liên kết Slack. Vui lòng thử lại.')
}

export async function createSlackLink(): Promise<SlackLinkCode> {
  let res: Response
  try {
    res = await authFetch('/api/users/slack-links', { method: 'POST', cache: 'no-store' })
  } catch {
    throw new ApiError(0, 'Không kết nối được tới máy chủ. Vui lòng thử lại.')
  }
  if (res.status === 401) throw new ApiError(401, 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.')
  if (res.status === 429) throw new ApiError(429, 'Bạn tạo mã quá nhanh. Vui lòng đợi một phút rồi thử lại.')
  if (!res.ok) throw new ApiError(res.status, 'Không tạo được mã liên kết Slack. Vui lòng thử lại.')
  const data = await res.json() as SlackLinkCode
  if (!data.code || !Number.isFinite(Date.parse(data.expires_at))) {
    throw new Error('Máy chủ trả về mã liên kết không hợp lệ. Vui lòng thử lại.')
  }
  return data
}
