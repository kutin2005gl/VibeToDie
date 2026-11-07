'use client'

import { useEffect, useSyncExternalStore, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { getServerSession, getSession, subscribe } from '../api/auth'

/** `undefined` khi chưa hỏi xong máy chủ, `null` khi chưa đăng nhập. */
export function useSession() {
  return useSyncExternalStore(subscribe, getSession, getServerSession)
}

/** Chuyển trang thay cho `<Navigate replace>` của react-router. */
export function Redirect({ to }: { to: string }) {
  const router = useRouter()
  useEffect(() => router.replace(to), [router, to])
  return null
}

/** Chưa đăng nhập (hoặc phiên vừa bị thu hồi) thì về màn đăng nhập; đang hỏi phiên thì chưa vẽ gì. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const session = useSession()
  if (session === undefined) return null
  return session ? children : <Redirect to="/login" />
}

export type Role = 'admin' | 'staff'

// Ban điều hành (sếp tổng/admin) và IT xem màn quản trị có biểu đồ; các phòng ban khác là nhân viên.
// TODO: user-service chưa có vai trò trong token nên suy ra từ phòng ban.
const adminDepartments = ['executive', 'it']

export function roleOf(departments: string[]): Role {
  return departments.some((d) => adminDepartments.includes(d)) ? 'admin' : 'staff'
}

export function useRole(): Role {
  return roleOf(useSession()?.user.departments ?? [])
}

export { departmentLabel, initials } from './labels'
