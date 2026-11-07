import { useState } from 'react'
import { ApiError, decideTask, type Task, type TaskStatus } from '../../api/client'
import styles from './TaskResult.module.css'

const statusLabel: Record<TaskStatus, string> = {
  running: 'Đang xử lý',
  awaiting_approval: 'Chờ duyệt',
  approved: 'Đã duyệt',
  rejected: 'Đã từ chối',
  failed: 'AI lỗi',
}

export function TaskResult({ task, onChange }: { task: Task; onChange: (t: Task) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function decide(approve: boolean) {
    setBusy(true)
    setError('')
    try {
      onChange(await decideTask(task.id, approve))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Có lỗi xảy ra')
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className={styles.card}>
      <header>
        <h3>Task #{task.id}</h3>
        <span className={`${styles.badge} ${styles[task.status]}`}>{statusLabel[task.status]}</span>
        {task.model && <span className={styles.model}>{task.model}</span>}
      </header>
      <p className={styles.request}>{task.text}</p>
      {task.status === 'failed' && <p className={styles.error} role="alert">{task.error ?? 'AI không phản hồi'}</p>}
      {task.output && <pre className={styles.output}>{task.output}</pre>}
      {task.status === 'awaiting_approval' && (
        <footer>
          <span>Duyệt đề xuất và gửi email cho khách?</span>
          <button disabled={busy} onClick={() => decide(false)}>Không</button>
          <button className={styles.yes} disabled={busy} onClick={() => decide(true)}>Có</button>
        </footer>
      )}
      {task.status === 'approved' && <p className={styles.note}>Đã duyệt. Email sẽ được gửi.</p>}
      {error && <p className={styles.error} role="alert">{error}</p>}
    </article>
  )
}
