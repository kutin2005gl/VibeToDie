import { useMemo, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { parsePrompt, sectionLabel } from './promptSections'
import styles from './InstructionsTab.module.css'

/** JSON đẹp của khối `output_schema`; không đọc được thì giữ nguyên chữ. */
function prettyJson(text: string) {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}

/** System prompt đầy đủ của agent (`_base` + phần dùng chung + mandate), chỉ đọc: sửa trong file mandate. */
export function InstructionsTab({ prompt, personal = false }: { prompt: string; personal?: boolean }) {
  const [source, setSource] = useState(false)
  const sections = useMemo(() => parsePrompt(prompt), [prompt])

  return (
    <div className={styles.wrap}>
      <div className={styles.bar}>
        <span>{personal
          ? 'Hướng dẫn của agent bạn đã đồng ý sử dụng. Chỉ xem.'
          : 'Được gửi tới model của agent này trong mọi phiên. Sửa trong file mandate của agent.'}</span>
        <div className={styles.seg}>
          <button className={!source ? styles.segOn : ''} onClick={() => setSource(false)}>Xem trước</button>
          <button className={source ? styles.segOn : ''} onClick={() => setSource(true)}>Mã nguồn</button>
        </div>
      </div>
      {source ? (
        <textarea className={styles.text} value={prompt} readOnly aria-label="Nội dung hướng dẫn" />
      ) : (
        <div className={styles.preview}>
          {sections.map((s, i) => (
            <section key={i} className={styles.block}>
              <h2>{sectionLabel(s.tag)}<code>{s.tag}</code></h2>
              {s.tag === 'output_schema'
                ? <pre>{prettyJson(s.body)}</pre>
                : <div className={styles.md}><Markdown remarkPlugins={[remarkGfm]}>{s.body}</Markdown></div>}
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
