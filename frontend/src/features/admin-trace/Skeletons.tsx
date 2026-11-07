'use client'

import type { ReactNode } from 'react'
import { useParams } from 'next/navigation'
import { PageHeader } from '../../components/PageHeader'
import { Skeleton } from '../../components/ui/skeleton'
import { Crumbs, departmentName } from './UsagePages'
import { useRememberedName } from './userNames'
import styles from './AdminTrace.module.css'

// Khung chờ (loading.tsx) của từng màn quản trị, cùng bố cục với trang thật để lúc dữ liệu tới không giật.
// Tiêu đề và đường dẫn đã biết từ URL nên hiện chữ thật ngay; chỉ phần dữ liệu mới là skeleton, và nó hiện
// dần sau một nhịp ngắn để trang tải nhanh không chớp khung rồi biến mất.

function Frame({ title, crumbs, children }: { title?: string; crumbs: ReactNode; children: ReactNode }) {
  return (
    <>
      <PageHeader title={title ?? <Skeleton className="h-4 w-48" />} />
      <div className={styles.body} aria-busy="true" aria-label="Đang tải">
        {crumbs}
        <div className={styles.settle}>
          <div className="flex items-baseline gap-3">
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-3 w-72" />
          </div>
          {children}
        </div>
      </div>
    </>
  )
}

/** Phòng ban đang xem, lấy từ URL (không có ở trang tổng). */
function useDepartment() {
  const { department } = useParams<{ department?: string }>()
  return department ? decodeURIComponent(department) : undefined
}

/** Đường dẫn của skeleton từ URL; nhân viên lấy tên đã nhớ, chưa có thì ghi tạm "Nhân viên". */
function UserCrumbs({ room }: { room?: string }) {
  const params = useParams<{ department?: string; userId?: string }>()
  const userId = params.userId ? decodeURIComponent(params.userId) : undefined
  const name = useRememberedName(userId)
  return (
    <Crumbs
      department={params.department && decodeURIComponent(params.department)}
      user={userId ? { id: userId, name: name ?? 'Nhân viên' } : undefined}
      room={room}
    />
  )
}

export function DepartmentsSkeleton() {
  return (
    <Frame title="Phiên làm việc" crumbs={<Crumbs />}>
      <div className={styles.deptGrid}>
        {[0, 1, 2].map((i) => (
          <div key={i} className={`${styles.card} flex flex-col gap-4`}>
            <div className="flex justify-between">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-3 w-16" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Skeleton className="h-6 w-28" />
              <Skeleton className="h-1 w-full" />
              <Skeleton className="h-3 w-24" />
            </div>
            <div className="grid grid-cols-3 gap-2 border-t border-border pt-3">
              {[0, 1, 2].map((j) => <Skeleton key={j} className="h-8" />)}
            </div>
            <div className="flex gap-1">
              {[0, 1, 2].map((j) => <Skeleton key={j} className="size-6 rounded-full" />)}
            </div>
          </div>
        ))}
      </div>
    </Frame>
  )
}

export function PeopleSkeleton() {
  const department = useDepartment()
  return (
    <Frame title={department && `Phòng ban ${departmentName(department)}`} crumbs={<Crumbs department={department} />}>
      <ul className={styles.people}>
        {[0, 1, 2, 3].map((i) => (
          <li key={i} className={styles.person}>
            <Skeleton className="size-9 rounded-full" />
            <span className="flex flex-col gap-1.5">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-32" />
            </span>
            <Skeleton className={`${styles.personStat} h-4 w-14`} />
            <Skeleton className={`${styles.personStat} h-4 w-28`} />
            <span className="flex flex-col items-end gap-1.5">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-1 w-full" />
            </span>
            <span />
          </li>
        ))}
      </ul>
    </Frame>
  )
}

export function RoomsSkeleton() {
  return (
    <Frame crumbs={<UserCrumbs />}>
      <div className={styles.profile}>
        <Skeleton className="size-12 rounded-full" />
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3 w-36" />
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <Skeleton className="h-6 w-24" />
          <Skeleton className="h-3 w-40" />
        </div>
      </div>
      <Skeleton className="h-4 w-28" />
      <ol className={styles.timeline}>
        {[0, 1, 2].map((i) => (
          <li key={i} className={styles.entry}>
            <Skeleton className="mt-3.5 ml-auto h-3 w-9" />
            <Skeleton className="mt-4 size-3 rounded-full" />
            <div className={styles.entryCard}>
              <div className="flex flex-col gap-2">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-3 w-1/2" />
              </div>
              <div className="flex flex-col items-end gap-2">
                <Skeleton className="h-4 w-16" />
                <Skeleton className="h-1 w-full" />
              </div>
            </div>
          </li>
        ))}
      </ol>
    </Frame>
  )
}

// Như chuỗi tin của room: bong bóng yêu cầu bên phải, rồi tin của các agent có avatar
export function TraceSkeleton() {
  return (
    <Frame crumbs={<UserCrumbs />}>
      <div className={styles.thread}>
        <Skeleton className="ml-auto h-16 w-3/5 rounded-lg" />
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex gap-3">
            <Skeleton className="size-7 shrink-0 rounded-full" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-4 w-4/5" />
            </div>
          </div>
        ))}
      </div>
    </Frame>
  )
}
