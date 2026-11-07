import { Suspense } from 'react'
import Link from 'next/link'
import { PageHeader } from '../../components/PageHeader'
import { analytics as loadAnalytics, load } from '../../server/admin'
import { ActivityTab } from './ActivityTab'
import { AnalyticsSkeleton } from './AnalyticsSkeleton'
import { UsageTab } from './UsageTab'
import styles from './Analytics.module.css'

export type Tab = 'activity' | 'usage'
// Nhãn khoảng thời gian → số ngày gửi cho `/api/admin/analytics?days=`; khoảng đầu là mặc định của tab
const ranges: Record<Tab, Record<string, number>> = {
  activity: { '7N': 7, 'Hôm nay': 1, '30N': 30, '3T': 90, '6T': 180, '12T': 365 },
  usage: { '30N': 30, '7N': 7, '90N': 90 },
}

const href = (tab: Tab, days?: number) => `/analytics?tab=${tab}${days ? `&days=${days}` : ''}`

async function Body({ tab, days }: { tab: Tab; days: number }) {
  const result = await load(() => loadAnalytics(days))
  if ('error' in result) return <p className={styles.muted}>{result.error}</p>
  return tab === 'activity' ? <ActivityTab data={result.data} /> : <UsageTab data={result.data} />
}

/** Tab và khoảng thời gian nằm trên URL: đổi là server lấy lại dữ liệu, skeleton hiện trong lúc chờ. */
export async function AnalyticsPage({ searchParams }: { searchParams: Promise<{ tab?: string; days?: string }> }) {
  const params = await searchParams
  const tab: Tab = params.tab === 'usage' ? 'usage' : 'activity'
  const options = ranges[tab]
  const days = Object.values(options).find((d) => String(d) === params.days) ?? Object.values(options)[0]

  return (
    <>
      <PageHeader
        title="Báo cáo"
        actions={
          <div className={styles.headerRight}>
            <nav className={styles.tabs} aria-label="Loại báo cáo">
              <Link href={href('activity')} aria-current={tab === 'activity' ? 'page' : undefined} className={tab === 'activity' ? styles.tabOn : ''}>Hoạt động</Link>
              <Link href={href('usage')} aria-current={tab === 'usage' ? 'page' : undefined} className={tab === 'usage' ? styles.tabOn : ''}>Sử dụng & Chi phí</Link>
            </nav>
            <nav className={styles.ranges} aria-label="Khoảng thời gian">
              {Object.entries(options).map(([label, d]) => (
                <Link key={label} href={href(tab, d)} aria-current={d === days ? 'true' : undefined} className={d === days ? styles.rangeOn : ''}>{label}</Link>
              ))}
            </nav>
          </div>
        }
      />
      <div className={styles.body}>
        <Suspense key={`${tab}-${days}`} fallback={<AnalyticsSkeleton tab={tab} />}>
          <Body tab={tab} days={days} />
        </Suspense>
      </div>
    </>
  )
}
