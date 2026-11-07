'use client'

import { HomePage } from '@/features/home/HomePage'
import { Redirect, useRole } from '@/shell/session'

// Nhân viên không có trang tổng quan: vào thẳng danh sách yêu cầu.
export default function Home() {
  return useRole() === 'staff' ? <Redirect to="/rooms" /> : <HomePage />
}
