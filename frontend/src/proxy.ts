import { NextResponse, type NextRequest } from 'next/server'
import { ACCESS_COOKIE, clearTokens, REFRESH_COOKIE, refresh, refreshCookie, setTokens } from '@/server/bff'

// Chưa có cookie phiên thì về /login ngay, không tải trang rồi mới đổi. Quyền thật nằm ở backend.
//
// Cookie access hết hạn sớm hơn token (bff.ts) nên trình duyệt tự xoá nó. Trang render trên server chỉ
// đọc được cookie, không ghi được, nên token được làm mới ở đây, trước khi trang render: cookie mới
// đi ra trình duyệt qua response, và vào luôn request để chính lần render này đọc được.
export async function proxy(req: NextRequest) {
  const token = refreshCookie(req)
  if (!token) return NextResponse.redirect(new URL('/login', req.url))
  if (req.cookies.has(ACCESS_COOKIE)) return NextResponse.next()

  // Gom chung với các lần làm mới khác (refresh token chỉ dùng được một lần)
  const renewed = await refresh(req, token).catch(() => undefined)
  if (renewed === 'expired') {
    const res = NextResponse.redirect(new URL('/login', req.url))
    clearTokens(res)
    return res
  }
  // Lỗi tạm (gateway, mạng): giữ cookie, client hỏi /api/users/me như trước
  if (!renewed) return NextResponse.next()

  req.cookies.set(ACCESS_COOKIE, renewed.access_token)
  req.cookies.set(REFRESH_COOKIE, renewed.refresh_token)
  const res = NextResponse.next({ request: { headers: req.headers } })
  setTokens(res, renewed)
  return res
}

export const config = {
  // Bỏ qua /login, API (BFF tự làm mới trong proxy() của bff.ts), file tĩnh của Next và file trong public/.
  matcher: ['/((?!login|api|_next/static|_next/image|favicon\\.svg).*)'],
}
