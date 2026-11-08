import { useEffect, useState, type ReactNode } from 'react'
import { usePathname } from 'next/navigation'
import { PanelLeft } from '../components/icons'
import { Sidebar } from './Sidebar'
import { BrandLogo } from './BrandMark'
import styles from './AppShell.module.css'

// Dưới ngưỡng này (điện thoại, máy tính bảng dọc) sidebar thành ngăn kéo; giữ khớp với @media trong CSS.
const DRAWER_QUERY = '(max-width: 900px)'

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const [drawer, setDrawer] = useState(false)
  const [open, setOpen] = useState(false)
  const pathname = usePathname()

  useEffect(() => {
    const mq = window.matchMedia(DRAWER_QUERY)
    const sync = () => { setDrawer(mq.matches); if (!mq.matches) setOpen(false) }
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  // Chuyển trang thì đóng ngăn kéo.
  useEffect(() => setOpen(false), [pathname])

  // Ctrl/Cmd+B thu gọn hoặc mở sidebar, như sidebar của shadcn/animate-ui.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === 'b' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        if (drawer) setOpen((o) => !o)
        else setCollapsed((c) => !c)
      }
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawer])

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <button className={styles.menu} onClick={() => setOpen(true)} aria-label="Mở menu" aria-expanded={open}>
          <PanelLeft size={20} />
        </button>
        <BrandLogo height={30} />
      </header>
      <div className={styles.body}>
        <Sidebar
          collapsed={drawer ? false : collapsed}
          onToggle={() => (drawer ? setOpen(false) : setCollapsed((c) => !c))}
          drawerOpen={open}
          onNavigate={() => setOpen(false)}
        />
        {open && <div className={styles.backdrop} onClick={() => setOpen(false)} aria-hidden="true" />}
        <main className={styles.main}>
          {children}
        </main>
      </div>
    </div>
  )
}
