import type { MyAgent } from '../../api/sessions'
import Link from 'next/link'
import { Bot } from '../../components/icons'
import { EmptyState } from '../../components/EmptyState'
import { PageHeader } from '../../components/PageHeader'
import styles from './SkillsPage.module.css'

// Giờ cửa hàng (UTC+7), để ngày không lệch theo múi giờ của máy chủ
const day = (iso: string) =>
  new Date(iso).toLocaleDateString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', day: '2-digit', month: '2-digit', year: 'numeric' })

// `social_media_marketing` -> "Social media marketing"
const label = (name: string) => {
  const words = name.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * Agent riêng của tài khoản (FR-14/15), render ở server: Factory soạn khi chưa có agent nào làm được việc,
 * nhân viên đã đồng ý dùng. Chỉ xem; bản nháp chưa duyệt nằm trong room đã tạo ra nó.
 */
export function SkillsPage({ agents }: { agents: MyAgent[] }) {
  return (
    <>
      <PageHeader title="Agent của tôi" />
      <div className={styles.body}>
        {agents.length === 0 ? (
          <EmptyState icon={<Bot size={32} />} title="Chưa có agent nào">
            <p>Agent mới sẽ xuất hiện ở đây sau khi bạn đồng ý dùng nó trong một room.</p>
          </EmptyState>
        ) : (
          <section aria-labelledby="my-agents">
            <div className={styles.sectionHead}><h2 id="my-agents">Agent</h2><span>{agents.length}</span></div>
            <ul className={styles.grid}>
              {agents.map((a) => (
                <li key={a.id} className={styles.card}>
                  <header>
                    <span className={styles.icon} aria-hidden="true"><Bot size={28} /></span>
                    <div className={styles.names}>
                      <strong><Link href={`/skills/${a.id}`}>{label(a.name)}</Link></strong>
                      <code>{a.name}</code>
                    </div>
                  </header>
                  <p>{a.role}</p>
                  <div className={styles.chips}>
                    {a.tools.length === 0
                      ? <span className={styles.meta}>Không dùng công cụ</span>
                      : a.tools.map((t) => <code key={t} className={styles.chip}>{t}</code>)}
                  </div>
                  {a.approved_at && (
                    <footer>Đồng ý ngày <time dateTime={a.approved_at}>{day(a.approved_at)}</time></footer>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </>
  )
}
