import { useState, type FormEvent } from 'react'
import { login } from '../../api/auth'
import { ApiError } from '../../api/base'
import { BrandLogo } from '../../shell/BrandMark'
import { Redirect, useSession } from '../../shell/session'
import styles from './LoginScreen.module.css'

// Tài khoản do user-service quản lý; phòng ban do admin (executive) cấp sau khi tạo.
export function LoginScreen() {
  const session = useSession()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (session) return <Redirect to="/home" />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      // Thành công thì session đổi và component tự chuyển sang /home.
      await login(email.trim(), password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Đăng nhập thất bại')
      setBusy(false)
    }
  }

  return (
    <div className={styles.screen}>
      <form className={styles.card} onSubmit={submit}>
        <div className={styles.logo}>
          <BrandLogo height={72} />
        </div>
        <h1>Đăng nhập</h1>
        <p className={styles.sub}>Trợ lý AI xử lý khiếu nại khách hàng</p>
        <label className={styles.field}>
          <span>Email</span>
          <input
            type="email" autoComplete="username" required autoFocus
            value={email} onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span>Mật khẩu</span>
          <input
            type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className={styles.error} role="alert">{error}</p>}
        <button className={styles.submit} type="submit" disabled={busy}>
          {busy ? 'Đang đăng nhập…' : 'Đăng nhập'}
        </button>
      </form>
    </div>
  )
}
