import { NextResponse, type NextRequest } from 'next/server'
import { clearTokens, crossOrigin, errorJson, postUsers, refreshCookie } from '../../../../server/bff'

// Thu hồi phiên trên user-service rồi xoá cookie; lỗi mạng ở đây vẫn xoá cookie.
export async function POST(req: NextRequest) {
  if (crossOrigin(req)) return errorJson(403, 'cross-origin request')
  const token = refreshCookie(req)
  if (token) await postUsers(req, '/logout', { refresh_token: token }).catch(() => {})
  const res = new NextResponse(null, { status: 204 })
  clearTokens(res)
  return res
}
