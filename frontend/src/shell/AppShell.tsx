import { useEffect, useState, type ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import styles from './AppShell.module.css'

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)

  // Ctrl/Cmd+B thu gọn hoặc mở sidebar, như sidebar của shadcn/animate-ui.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === 'b' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        setCollapsed((c) => !c)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className={styles.shell}>
      <div className={styles.body}>
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
        <main className={styles.main}>
          {children}
        </main>
      </div>
    </div>
  )
}
