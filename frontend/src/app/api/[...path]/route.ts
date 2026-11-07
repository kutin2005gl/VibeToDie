import type { NextRequest } from 'next/server'
import { crossOrigin, errorJson, proxy } from '../../../server/bff'

// Mọi /api/* (trừ /api/auth/*) đi qua đây tới gateway, kèm token lấy từ cookie.
export const dynamic = 'force-dynamic'

// Các endpoint này trả hoặc nhận token: chỉ /api/auth/* được gọi, để token không tới trình duyệt.
const tokenPaths = new Set(['/api/users/login', '/api/users/refresh', '/api/users/logout', '/api/slack-links/redeem'])

async function handle(req: NextRequest) {
  const path = req.nextUrl.pathname
  if (tokenPaths.has(path)) return errorJson(404, 'not found')
  if (crossOrigin(req)) return errorJson(403, 'cross-origin request')
  return proxy(req, path)
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE }
