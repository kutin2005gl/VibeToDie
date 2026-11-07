import { useCallback, useEffect, useRef, useState } from 'react'
import { createSlackLink, getSlackLinkStatus, unlinkSlack, type SlackAccount, type SlackLinkCode, type SlackLinkStatus } from '../../api/slack'
import { Button } from '../../components/Button'
import { Check, Copy } from '../../components/icons'
import { SettingsRow } from './SettingsSection'
import styles from './SlackLinkSettings.module.css'

// Khi đang chờ nhân viên gửi mã trên Slack, hỏi máy chủ cứ vài giây để đổi sang "Đã liên kết".
const POLL_MS = 3000

const since = (iso?: string) => {
  const time = iso ? Date.parse(iso) : NaN
  return Number.isFinite(time) ? new Date(time).toLocaleString('vi-VN') : ''
}

// Máy chủ đã kiểm dạng; kiểm lại vì giá trị này đi vào URL.
const SLACK_DOMAIN = /^[a-z0-9][a-z0-9-]{0,62}$/
const SLACK_USER_ID = /^[UW][A-Z0-9]{2,30}$/

function SlackAccountName({ account }: { account: SlackAccount }) {
  const name = account.real_name || (account.user_name ? `@${account.user_name}` : account.slack_user_id)
  const domain = account.team_domain && SLACK_DOMAIN.test(account.team_domain) ? account.team_domain : ''
  // Workspace không hiện ra chữ: nó chỉ có trong link tới hồ sơ
  if (!domain || !SLACK_USER_ID.test(account.slack_user_id)) return <strong>{name}</strong>
  return (
    <a href={`https://${domain}.slack.com/team/${account.slack_user_id}`} target="_blank" rel="noreferrer">
      <strong>{name}</strong>
    </a>
  )
}

function linkedDescription(status: SlackLinkStatus) {
  const known = status.links.flatMap(l => l.account ? [l.account] : [])
  const unknown = status.links.length - known.length
  const from = since(status.linked_at)
  return (
    <>
      {known.length === 0 ? 'Đã liên kết' : <>Đã liên kết với {known.map((a, i) => (
        <span key={`${a.team_id ?? ''}-${a.slack_user_id}-${i}`}>{i > 0 && ', '}<SlackAccountName account={a} /></span>
      ))}</>}
      {known.length > 0 && unknown > 0 && ` và ${unknown} tài khoản chưa rõ tên`}
      {from && ` từ ${from}`}
      {'. Trợ lý BOA trên Slack dùng tài khoản và quyền của bạn.'}
      {known.length === 0 && ' Liên kết lại để hiện tên tài khoản Slack.'}
    </>
  )
}

export function SlackLinkSettings() {
  const [status, setStatus] = useState<SlackLinkStatus | null>(null)
  const [link, setLink] = useState<SlackLinkCode | null>(null)
  const [now, setNow] = useState(0)
  const [loading, setLoading] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')
  const [copyState, setCopyState] = useState<'idle' | 'copying' | 'copied' | 'failed'>('idle')
  const pending = useRef(false)
  const mounted = useRef(false)

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  const refresh = useCallback(async () => {
    try {
      const next = await getSlackLinkStatus()
      if (!mounted.current) return
      setStatus(next)
      if (next.linked) setLink(null)
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : 'Không kiểm tra được trạng thái liên kết Slack.')
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const waiting = Boolean(link) && !status?.linked
  useEffect(() => {
    if (!waiting) return
    const timer = window.setInterval(() => void refresh(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [waiting, refresh])

  useEffect(() => {
    if (!link) return
    const tick = () => {
      const time = Date.now()
      setNow(time)
      if (time >= Date.parse(link.expires_at)) {
        setLink(null)
        setCopyState('idle')
        setError('Mã đã hết hạn. Hãy tạo mã mới để liên kết Slack.')
      }
    }
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [link])

  const run = async (task: () => Promise<void>, fallback: string) => {
    if (pending.current) return
    pending.current = true
    setLoading(true)
    setError('')
    try {
      await task()
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : fallback)
    } finally {
      pending.current = false
      if (mounted.current) setLoading(false)
    }
  }

  const generate = () => run(async () => {
    setCopyState('idle')
    const code = await createSlackLink()
    if (!mounted.current) return
    setNow(Date.now())
    setLink(code)
  }, 'Không tạo được mã. Vui lòng thử lại.')

  const unlink = () => run(async () => {
    await unlinkSlack()
    if (!mounted.current) return
    setConfirming(false)
    setLink(null)
    setStatus({ linked: false, links: [] })
  }, 'Không hủy được liên kết Slack. Vui lòng thử lại.')

  const copy = async () => {
    if (!link || copyState === 'copying' || Date.now() >= Date.parse(link.expires_at)) return
    setCopyState('copying')
    try {
      await navigator.clipboard.writeText(`/boa link ${link.code}`)
      if (mounted.current && Date.now() < Date.parse(link.expires_at)) setCopyState('copied')
    } catch {
      if (mounted.current && Date.now() < Date.parse(link.expires_at)) setCopyState('failed')
    }
  }

  const remaining = link ? Math.max(0, Math.ceil((Date.parse(link.expires_at) - now) / 1000)) : 0
  const active = link && remaining > 0 && !status?.linked

  const action = status?.linked
    ? confirming
      ? <>
          <Button onClick={() => void unlink()} disabled={loading}>{loading ? 'Đang hủy…' : 'Xác nhận hủy'}</Button>
          <Button onClick={() => setConfirming(false)} disabled={loading}>Giữ liên kết</Button>
        </>
      : <Button onClick={() => { setError(''); setConfirming(true) }} disabled={loading}>Hủy liên kết</Button>
    : <Button onClick={() => void generate()} disabled={loading || Boolean(active) || !status}>
        {loading ? 'Đang tạo mã…' : 'Liên kết Slack'}
      </Button>

  return (
    <div className={styles.section}>
      <SettingsRow
        title="Liên kết Slack"
        description={status?.linked
          ? linkedDescription(status)
          : 'Trò chuyện với Trợ lý BOA trên Slack bằng tài khoản và quyền của bạn.'}
        action={action}
      />
      {confirming && (
        <p role="status" className={styles.note}>
          Hủy xong, Trợ lý BOA trên Slack không còn trả lời bằng tài khoản của bạn. Đăng nhập web không bị ảnh hưởng, và bạn có thể liên kết lại bất cứ lúc nào.
        </p>
      )}
      {active && (
        <div className={styles.card}>
          <p>Mở tin nhắn riêng với Trợ lý BOA trên Slack và gửi lệnh:</p>
          <code className={styles.command}>/boa link {link.code}</code>
          <div className={styles.actions}>
            <Button
              onClick={() => void copy()}
              disabled={copyState === 'copying'}
              className={copyState === 'copied' ? styles.copied : undefined}
            >
              {copyState === 'copied' ? <Check size={15} /> : <Copy size={15} />}
              {copyState === 'copied' ? 'Đã sao chép' : copyState === 'copying' ? 'Đang sao chép…' : 'Sao chép lệnh'}
            </Button>
            <span className={styles.timer} role="timer" aria-label="Thời gian còn lại của mã">
              Hết hạn sau {Math.floor(remaining / 60)}:{String(remaining % 60).padStart(2, '0')}
            </span>
          </div>
          <div role="status" aria-live="polite" aria-atomic="true">
            {copyState === 'copied' && <p className={styles.success}>Đã sao chép lệnh. Dán vào tin nhắn riêng với Trợ lý BOA trên Slack để liên kết.</p>}
            {copyState === 'failed' && <p className={styles.error}>Không sao chép được. Hãy chọn và sao chép lệnh bên trên.</p>}
          </div>
          <p className={styles.note}>Mã có hiệu lực 10 phút và chỉ dùng một lần. Không chia sẻ mã với người khác. Trang này tự cập nhật khi liên kết xong.</p>
        </div>
      )}
      {loading && !confirming && <p role="status" className={styles.note}>Đang tạo mã liên kết Slack…</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
    </div>
  )
}
