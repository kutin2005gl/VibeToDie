// Chủ đề sáng/tối. index.html đặt data-theme trước khi vẽ (cùng khoá, cùng cách tính) và theo dõi
// hệ thống khi chọn "Tự động"; file này lưu lựa chọn và đổi theme có hiệu ứng.
export type Theme = 'light' | 'dark' | 'auto'
type Resolved = 'light' | 'dark'

const THEME_KEY = 'boa.theme'

export function readTheme(): Theme {
  try {
    const v = localStorage.getItem(THEME_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch { /* không có localStorage: theo hệ thống */ }
  return 'auto'
}

function resolve(theme: Theme): Resolved {
  if (theme !== 'auto') return theme
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function apply(theme: Theme) {
  try {
    if (theme === 'auto') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, theme)
  } catch { /* chỉ giữ trong phiên */ }
  document.documentElement.dataset.theme = resolve(theme)
}

// Hiệu ứng ThemeToggler của animate-ui: View Transitions chụp trang cũ/mới, trang mới quét
// từ trái sang phải bằng clip-path. Không hỗ trợ hoặc giảm chuyển động: đổi ngay.
// `render` cập nhật UI (vd. flushSync setState) để ảnh chụp trang mới đã có lựa chọn mới.
export function switchTheme(next: Theme, render?: () => void) {
  const swap = () => { apply(next); render?.() }
  const changes = resolve(next) !== document.documentElement.dataset.theme
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!changes || reduced || !document.startViewTransition) { swap(); return }

  document.startViewTransition(swap).ready.then(() => {
    document.documentElement.animate(
      { clipPath: ['inset(0 100% 0 0)', 'inset(0 0 0 0)'] },
      { duration: 700, easing: 'ease-in-out', pseudoElement: '::view-transition-new(root)' },
    )
  })
}
