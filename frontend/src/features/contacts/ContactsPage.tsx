import { useState } from 'react'
import { Search } from '../../components/icons'
import { PageHeader } from '../../components/PageHeader'
import { Button } from '../../components/Button'
import { ListSelect } from '../../components/ListSelect'
import { contacts, contactFilterOptions, identityOptions } from '../../mocks/network'
import styles from './ContactsPage.module.css'

// TODO(NOT VERIFIED): nhu cầu Danh bạ trong bán lẻ chưa được Owner chốt (có thể đổi thành danh bạ khách hàng).
// TODO: "Gửi lời mời" chỉ xoá form; trạng thái thành công/lỗi chưa có screenshot.
export function ContactsPage() {
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')
  const [handle, setHandle] = useState('')
  const [message, setMessage] = useState('')
  const [identity, setIdentity] = useState('you')

  const list = contacts.filter((c) => `${c.identity} ${c.connectedTo}`.toLowerCase().includes(q.toLowerCase()))

  return (
    <>
      <PageHeader title="Danh bạ" />
      <div className={styles.filterBar}>
        <ListSelect label="Lọc theo danh tính" value={filter} options={contactFilterOptions} onChange={setFilter} />
        <label className={styles.search}>
          <Search size={14} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm theo tên hoặc @handle…" />
        </label>
      </div>
      <div className={styles.body}>
        <form
          className={styles.invite}
          onSubmit={(e) => {
            e.preventDefault()
            setHandle('')
            setMessage('')
          }}
        >
          <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="@handle hoặc owner/agent…" />
          <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Lời nhắn (tuỳ chọn)…" />
          <ListSelect label="Gửi với danh tính" value={identity} options={identityOptions} onChange={setIdentity} align="right" />
          <Button variant="primary" type="submit" disabled={!handle.trim()}>Gửi lời mời</Button>
        </form>

        <section>
          <h2 className={styles.h2}>KẾT NỐI ({list.length})</h2>
          <table className={styles.table}>
            <thead><tr><th>Danh tính của bạn</th><th>Kết nối với</th><th className={styles.right}>Thao tác</th></tr></thead>
            <tbody>
              {list.length === 0 ? (
                <tr><td colSpan={3} className={styles.empty}>Chưa có liên hệ nào. Hãy gửi lời mời theo handle ở trên.</td></tr>
              ) : (
                list.map((c) => <tr key={c.id}><td>{c.identity}</td><td>{c.connectedTo}</td><td className={styles.right} /></tr>)
              )}
            </tbody>
          </table>
        </section>
      </div>
    </>
  )
}
