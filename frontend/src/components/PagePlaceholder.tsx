import styles from './PagePlaceholder.module.css'

// TODO: thay bằng màn thật ở các phần tiếp theo.
export function PagePlaceholder({ title }: { title: string }) {
  return (
    <div className={styles.wrap}>
      <h1>{title}</h1>
      <p>Màn hình này sẽ được dựng ở phần sau.</p>
    </div>
  )
}
