import { PageHeader } from '../../components/PageHeader'
import { Skeleton } from '../../components/ui/skeleton'
import cardStyles from './AgentCard.module.css'
import styles from './AgentsPage.module.css'
import detailStyles from './AgentDetailPage.module.css'

// Khung chờ (loading.tsx) cùng bố cục với trang thật.
export function AgentsSkeleton() {
  return (
    <>
      <PageHeader title="Agents" />
      <div className={styles.body} aria-busy="true" aria-label="Đang tải">
        <Skeleton className="h-9 w-full" />
        <div className={styles.grid}>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className={cardStyles.card}>
              <div className="flex items-center gap-3">
                <Skeleton className="size-8" />
                <div className="flex flex-col gap-1.5">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-24" />
                </div>
              </div>
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-10 w-full" />
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

export function AgentDetailSkeleton() {
  return (
    <div className={detailStyles.page} aria-busy="true" aria-label="Đang tải">
      <header className={detailStyles.header}>
        <Skeleton className="size-8" />
        <div className="flex flex-1 flex-col gap-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-3 w-32" />
          <Skeleton className="h-4 w-96 max-w-full" />
        </div>
      </header>
      <div className="flex flex-col gap-2 p-6">
        {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-5 w-full max-w-xl" />)}
      </div>
    </div>
  )
}
