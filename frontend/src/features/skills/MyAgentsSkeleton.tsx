import { PageHeader } from '../../components/PageHeader'
import { Skeleton } from '../../components/ui/skeleton'
import styles from './SkillsPage.module.css'

// Khung chờ (loading.tsx) cùng bố cục với trang thật.
export function MyAgentsSkeleton() {
  return (
    <>
      <PageHeader title="Agent của tôi" />
      <div className={styles.body} aria-busy="true" aria-label="Đang tải">
        <div className={styles.grid}>
          {[0, 1, 2].map((i) => (
            <div key={i} className={styles.card}>
              <div className="flex items-center gap-3">
                <Skeleton className="size-8" />
                <div className="flex flex-col gap-1.5">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-3 w-24" />
                </div>
              </div>
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-5 w-40" />
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
