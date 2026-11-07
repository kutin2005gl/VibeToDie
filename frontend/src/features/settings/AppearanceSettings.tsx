import { Check } from '../../components/icons'
import { useState, type ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { readTheme, switchTheme, type Theme } from '../../shell/theme'
import { SettingsSection } from './SettingsSection'
import { Switch } from './Switch'
import styles from './AppearanceSettings.module.css'

type FontSize = 'small' | 'default' | 'large' | 'larger' | 'xlarge' | 'max'
type Density = 'roomy' | 'compact'

const themeOptions: { id: Theme; label: string }[] = [
  { id: 'light', label: 'Sáng' }, { id: 'dark', label: 'Tối' }, { id: 'auto', label: 'Tự động' },
]
const fontOptions: { id: FontSize; label: string; px: number }[] = [
  { id: 'small', label: 'Nhỏ', px: 14 }, { id: 'default', label: 'Mặc định', px: 16 }, { id: 'large', label: 'Lớn', px: 18 },
  { id: 'larger', label: 'Lớn hơn', px: 21 }, { id: 'xlarge', label: 'Rất lớn', px: 24 }, { id: 'max', label: 'Tối đa', px: 28 },
]

function Block({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <div className={styles.block}>
      <div className={styles.text}>
        <div className={styles.blockTitle}>{title}</div>
        <div className={styles.blockDesc}>{description}</div>
      </div>
      <div className={styles.control}>{children}</div>
    </div>
  )
}

function Option({ selected, label, onSelect, children }: { selected: boolean; label: string; onSelect: () => void; children: ReactNode }) {
  return (
    <button className={`${styles.option} ${selected ? styles.selected : ''}`} onClick={onSelect} aria-pressed={selected}>
      <span className={styles.tile}>{children}</span>
      <span className={styles.optionLabel}>{selected && <Check size={12} strokeWidth={2} />}{label}</span>
    </button>
  )
}

function ThemePreview({ kind }: { kind: Theme }) {
  return (
    <span className={`${styles.preview} ${styles[`theme_${kind}`]}`}>
      <i className={styles.pSide} /><i className={styles.pLine1} /><i className={styles.pLine2} /><i className={styles.pLine3} /><i className={styles.pInput} />
    </span>
  )
}

function FontGrid({ ids, value, onChange }: { ids: FontSize[]; value: FontSize; onChange: (v: FontSize) => void }) {
  return (
    <div className={styles.grid3}>
      {fontOptions.filter((o) => ids.includes(o.id)).map((o) => (
        <Option key={o.id} selected={value === o.id} label={o.label} onSelect={() => onChange(o.id)}>
          <span className={styles.aa} style={{ fontSize: o.px }}>Aa</span>
        </Option>
      ))}
    </div>
  )
}

// TODO: cỡ chữ, gập tin và mật độ chỉ lưu trạng thái trong phiên, chưa áp lên app. Chủ đề đã áp và lưu (app/theme.ts).
export function AppearanceSettings() {
  const [fold, setFold] = useState(false)
  const [theme, setTheme] = useState<Theme>(readTheme)
  const [appFont, setAppFont] = useState<FontSize>('default')
  const [chatFont, setChatFont] = useState<FontSize>('default')
  const [density, setDensity] = useState<Density>('roomy')

  return (
    <SettingsSection title="Giao diện">
      <div className={styles.switchRow}>
        <div>
          <div className={styles.blockTitle}>Gập tin nhắn dài</div>
          <div className={styles.blockDesc}>Hiện năm dòng đầu của tin nhắn dài, bấm &quot;Xem thêm&quot; để mở phần còn lại.</div>
        </div>
        <Switch checked={fold} onChange={setFold} label="Gập tin nhắn dài" />
      </div>

      <Block title="Chủ đề" description="Giao diện Phone Retail trên máy này.">
        <div className={styles.grid3}>
          {themeOptions.map((o) => (
            <Option key={o.id} selected={theme === o.id} label={o.label} onSelect={() => switchTheme(o.id, () => flushSync(() => setTheme(o.id)))}>
              <ThemePreview kind={o.id} />
            </Option>
          ))}
        </div>
      </Block>

      <Block
        title="Cỡ chữ ứng dụng"
        description="Phóng to toàn bộ giao diện, gồm cả hội thoại và ô soạn tin. Cỡ lớn hơn cũng nâng kích thước cửa sổ tối thiểu để không bị cắt."
      >
        <FontGrid ids={['small', 'default', 'large']} value={appFont} onChange={setAppFont} />
      </Block>

      <Block
        title="Cỡ chữ hội thoại"
        description="Phóng to thêm phần nội dung hội thoại. Danh sách phiên, các panel và ô soạn tin chỉ theo cỡ chữ ứng dụng."
      >
        <FontGrid ids={['small', 'default', 'large', 'larger', 'xlarge', 'max']} value={chatFont} onChange={setChatFont} />
      </Block>

      <Block
        title="Mật độ danh sách phiên"
        description="Gọn hiển thị được nhiều phiên hơn: mỗi phiên một dòng, không hiện danh sách người tham gia."
      >
        <div className={styles.grid2}>
          <Option selected={density === 'roomy'} label="Thoáng" onSelect={() => setDensity('roomy')}>
            <span className={styles.density}><i className={styles.dLong} /><i className={styles.dShort} /></span>
          </Option>
          <Option selected={density === 'compact'} label="Gọn" onSelect={() => setDensity('compact')}>
            <span className={styles.density}><i className={styles.dLong} /></span>
          </Option>
        </div>
      </Block>
    </SettingsSection>
  )
}
