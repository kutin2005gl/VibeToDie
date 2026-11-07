import {
  ArrowLeft, Bell, BookOpen, Cpu, FlaskConical, Palette, Plug, Radar, ScrollText,
  SlidersHorizontal, UserCircle, type IconComponent,
} from '../../components/icons'
import type { ReactNode } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { settingsGroups, type SettingsSectionId } from '../../mocks/settings'
import { useRole } from '../../shell/session'
import styles from './SettingsShell.module.css'

const icons: Record<SettingsSectionId, IconComponent> = {
  account: UserCircle, notifications: Bell, general: SlidersHorizontal, appearance: Palette,
  sonar: Radar, integrations: Plug, runtime: Cpu, logs: ScrollText,
  experiments: FlaskConical, 'learn-more': BookOpen,
}

// Nhân viên chỉ chỉnh phần của mình; các mục ứng dụng/agent/nâng cao là của quản trị.
const staffSections: SettingsSectionId[] = ['account', 'notifications', 'appearance']

export function SettingsShell({ children }: { children: ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const staff = useRole() === 'staff'
  const groups = staff
    ? [{ label: 'Cá nhân', items: settingsGroups.flatMap((g) => g.items).filter((i) => staffSections.includes(i.id)) }]
    : settingsGroups
  return (
    <div className={styles.shell}>
      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <button className={styles.back} onClick={() => router.push('/home')}>
            <ArrowLeft size={17} />
            <span>Quay lại ứng dụng</span>
          </button>
          {groups.map((group) => (
            <nav key={group.label} className={styles.group}>
              <div className={styles.groupLabel}>{group.label}</div>
              {group.items.map(({ id, label }) => {
                const Icon = icons[id]
                return (
                  <Link
                    key={id}
                    href={`/settings/${id}`}
                    className={`${styles.item} ${pathname === `/settings/${id}` ? styles.active : ''}`}
                  >
                    <Icon size={17} />
                    <span>{label}</span>
                  </Link>
                )
              })}
            </nav>
          ))}
        </aside>
        <main className={styles.main}>
          {children}
        </main>
      </div>
    </div>
  )
}
