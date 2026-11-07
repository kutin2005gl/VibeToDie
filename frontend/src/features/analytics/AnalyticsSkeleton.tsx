import { Skeleton } from '../../components/ui/skeleton'
import styles from './Analytics.module.css'

// Khung chờ cùng bố cục với từng tab, để lúc dữ liệu tới không giật.
function ChartSkeleton({ height }: { height: number }) {
  return (
    <section className={styles.chartCard}>
      <Skeleton className="mb-3 h-4 w-40" />
      <Skeleton style={{ height }} className="w-full" />
    </section>
  )
}

function TableSkeleton({ rows }: { rows: number }) {
  return (
    <section className={styles.chartCard}>
      <Skeleton className="mb-3 h-4 w-40" />
      <div className="flex flex-col gap-2">
        {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-5 w-full" />)}
      </div>
    </section>
  )
}

export function AnalyticsSkeleton({ tab }: { tab: 'activity' | 'usage' }) {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Đang tải">
      {tab === 'activity' ? (
        <>
          <div className={styles.stats}>
            {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-16" />)}
          </div>
          <div className={styles.grid2}>
            <ChartSkeleton height={220} />
            <ChartSkeleton height={220} />
            <ChartSkeleton height={220} />
            <div className={styles.col}>
              <TableSkeleton rows={1} />
              <TableSkeleton rows={4} />
            </div>
          </div>
        </>
      ) : (
        <>
          <div className={styles.stats3}>
            {Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-16" />)}
          </div>
          <ChartSkeleton height={200} />
          <TableSkeleton rows={3} />
          <TableSkeleton rows={4} />
        </>
      )}
    </div>
  )
}
