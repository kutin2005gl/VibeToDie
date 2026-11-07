import { Search, Upload, X } from '../../components/icons'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '../../components/Button'
import { CheckFilter } from '../../components/CheckFilter'
import { agentCatalog, type MockTeam } from '../../mocks/agentCatalog'
import styles from './EditTeamDialog.module.css'

const NAME_MAX = 25
const DESC_MAX = 120

interface Props {
  team: MockTeam
  onCancel: () => void
  onSave: (patch: Pick<MockTeam, 'name' | 'description' | 'guidelines' | 'agentIds'>) => void
}

// Hộp thoại sửa đội: thông tin, hướng dẫn và chọn agent (bấm thẻ để chọn/bỏ chọn).
export function EditTeamDialog({ team, onCancel, onSave }: Props) {
  const [name, setName] = useState(team.name)
  const [description, setDescription] = useState(team.description)
  const [guidelines, setGuidelines] = useState(team.guidelines)
  const [selected, setSelected] = useState<string[]>(team.agentIds)
  const [q, setQ] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const searchRef = useRef<HTMLInputElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    searchRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])

  const tagOptions = useMemo(
    () => [...new Set(agentCatalog.map((a) => a.tag))].map((value) => ({ value, count: agentCatalog.filter((a) => a.tag === value).length })),
    [],
  )
  const visible = agentCatalog.filter(
    (a) =>
      (!tags.length || tags.includes(a.tag)) &&
      (!q || `${a.name} ${a.handle} ${a.description}`.toLowerCase().includes(q.toLowerCase())),
  )
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const valid = name.trim().length > 0 && selected.length > 0

  const onFile = async (file: File | undefined) => {
    if (!file) return
    setGuidelines(await file.text())
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <div className={styles.overlay} onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel() }}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="edit-team-title">
        <div className={styles.top}>
          <header>
            <h2 id="edit-team-title">Sửa đội</h2>
            <button className={styles.close} aria-label="Đóng" onClick={onCancel}><X size={16} /></button>
          </header>

          <div className={styles.twoCol}>
            <label className={styles.field}>
              <span className={styles.label}>Tên <small>{name.length}/{NAME_MAX}</small></span>
              <input value={name} maxLength={NAME_MAX} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className={styles.field}>
              <span className={styles.label}>Mô tả <small>{description.length}/{DESC_MAX}</small></span>
              <input value={description} maxLength={DESC_MAX} onChange={(e) => setDescription(e.target.value)} />
            </label>
          </div>

          <div className={styles.field}>
            <div className={styles.label}>
              <label htmlFor="team-guidelines">Hướng dẫn của đội</label>
              <input ref={fileRef} type="file" accept=".md,.txt,text/*" hidden onChange={(e) => void onFile(e.target.files?.[0])} />
              <button className={styles.upload} onClick={() => fileRef.current?.click()}><Upload size={13} />Tải tệp lên</button>
            </div>
            <textarea id="team-guidelines" value={guidelines} onChange={(e) => setGuidelines(e.target.value)} />
            <p className={styles.hint}>Mọi thành viên đều tuân theo hướng dẫn này trong các phiên của đội.</p>
          </div>
        </div>

        <div className={styles.agents}>
          <h3>Agent trong đội</h3>
          <div className={styles.tools}>
            <label className={styles.search}>
              <Search size={15} />
              <input ref={searchRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm agent…" />
            </label>
            <CheckFilter label="Thẻ" options={tagOptions} selected={tags} onChange={setTags} />
            <span className={styles.scope}>Tất cả agent của tôi ({agentCatalog.length})</span>
          </div>
          <div className={styles.grid}>
            {visible.map((a) => {
              const on = selected.includes(a.id)
              return (
                <button key={a.id} className={`${styles.card} ${on ? styles.on : ''}`} aria-pressed={on} onClick={() => toggle(a.id)}>
                  <span className={styles.cardHead}>
                    <span className={styles.avatar} style={{ background: a.color }}>{a.name.charAt(0)}</span>
                    <span>
                      <strong>{a.name}</strong>
                      <code>@{a.handle}</code>
                    </span>
                  </span>
                  <span className={styles.cardDesc}>{a.description}</span>
                </button>
              )
            })}
            {visible.length === 0 && <p className={styles.none}>Không có agent phù hợp.</p>}
          </div>
        </div>

        <footer className={styles.footer}>
          <div className={styles.chips}>
            {selected.map((id) => {
              const a = agentCatalog.find((x) => x.id === id)
              return a && (
                <span key={id} className={styles.chip}>
                  {a.name}
                  <button aria-label={`Bỏ ${a.name}`} onClick={() => toggle(id)}><X size={12} /></button>
                </span>
              )
            })}
          </div>
          <div className={styles.footRow}>
            <span className={styles.count}>Đã chọn: {selected.length}</span>
            <div className={styles.buttons}>
              <Button onClick={onCancel}>Huỷ</Button>
              <Button
                variant="primary"
                disabled={!valid}
                onClick={() => onSave({ name: name.trim(), description: description.trim(), guidelines, agentIds: selected })}
              >
                Lưu thay đổi
              </Button>
            </div>
          </div>
        </footer>
      </div>
    </div>
  )
}
