'use client'

import { useEffect, useSyncExternalStore } from 'react'

// Skeleton (loading.tsx) chỉ biết id nhân viên từ URL, còn tên nằm trong dữ liệu chưa tải xong. Các trang đã tải
// ghi tên vào sessionStorage; skeleton đọc lại để đường dẫn giữ nguyên tên nhân viên thay vì mất một mắt xích.

const KEY = 'admin.userNames'

function read(): Record<string, string> {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? '{}')
  } catch {
    return {}
  }
}

/** Ghi tên các nhân viên trang này đã có, không hiện gì. */
export function RememberUsers({ users }: { users: { id: string; name: string }[] }) {
  useEffect(() => {
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ ...read(), ...Object.fromEntries(users.map((u) => [u.id, u.name])) }))
    } catch {
      // storage bị chặn: skeleton dùng tên dự phòng
    }
  }, [users])
  return null
}

const subscribe = () => () => {}

/** Tên đã nhớ của nhân viên; `undefined` trên server và khi chưa từng mở trang của họ. */
export function useRememberedName(userId: string | undefined) {
  const name = useSyncExternalStore(subscribe, () => (userId ? read()[userId] : undefined), () => undefined)
  return name
}
