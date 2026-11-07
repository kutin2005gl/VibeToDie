'use client'

import type { ReactNode } from 'react'
import { Redirect, useRole } from '@/shell/session'

// Trang quản trị: nhân viên về danh sách yêu cầu. Chỉ là giao diện, quyền thật do backend kiểm tra.
export default function AdminLayout({ children }: { children: ReactNode }) {
  return useRole() === 'staff' ? <Redirect to="/rooms" /> : children
}
