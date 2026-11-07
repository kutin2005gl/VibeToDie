import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { StoreProvider } from '@/shell/store'
// Nunito cho toàn app (đầu nét bo tròn như nét logo), khai báo dày hơn một bậc: xem fonts.css.
import '@/styles/fonts.css'
import '@/styles/tokens.css'
import '@/styles/global.css'
// Chỉ theme và utilities của Tailwind cho component shadcn, không reset (xem tailwind.css)
import '@/styles/tailwind.css'

export const metadata: Metadata = {
  title: 'BOA',
  icons: { icon: '/favicon.svg' },
}

// Đặt theme trước khi vẽ để không nháy trắng; khoá và cách tính giống src/shell/theme.ts.
// Không lưu lựa chọn = "Tự động": theo hệ thống, kể cả khi hệ thống đổi lúc đang mở app.
const themeScript = `(function () {
  var mq = matchMedia('(prefers-color-scheme: dark)')
  function apply() {
    var t
    try { t = localStorage.getItem('boa.theme') } catch (e) {}
    if (t !== 'light' && t !== 'dark') t = mq.matches ? 'dark' : 'light'
    document.documentElement.dataset.theme = t
  }
  apply()
  mq.addEventListener('change', apply)
})()`

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // data-theme do script đặt trước khi React hydrate nên khác bản render trên server.
    <html lang="vi" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <StoreProvider>{children}</StoreProvider>
      </body>
    </html>
  )
}
