import { redirect } from 'next/navigation'

// Đường dẫn lạ về trang chủ (nhân viên được chuyển tiếp sang danh sách yêu cầu).
export default function NotFound() {
  redirect('/home')
}
