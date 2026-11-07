import { useId, type ReactElement, type ReactNode, type SVGProps } from 'react'

/*
 * Bộ icon riêng của BOA, vẽ theo nét logo: nét đơn dày (2), đầu và góc bo tròn, góc bo lớn,
 * vài hình để hở như nét vẽ tay; mặt cười ^ ^ cho người/agent, hai vạch lấp lánh cho điểm nhấn.
 * Tên giữ giống tên cũ (lucide) để các màn hình chỉ đổi đường dẫn import.
 */
export interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'ref'> {
  size?: number | string
  strokeWidth?: number | string
}
export type IconComponent = (props: IconProps) => ReactElement

function icon(name: string, body: ReactNode): IconComponent {
  const C = ({ size = 24, strokeWidth = 2, ...rest }: IconProps) => (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}
    >
      {body}
    </svg>
  )
  C.displayName = name
  return C
}

const dot = (cx: number, cy: number) => <circle cx={cx} cy={cy} r="1.1" fill="currentColor" stroke="none" />
// Mắt cười ^ ^ của logo, đặt quanh tâm (x, y).
const smile = (x: number, y: number, gap = 2.2) => (
  <path d={`M${x - gap - 1.1} ${y + .5}c.4-1 1.8-1 2.2 0M${x + gap - 1.1} ${y + .5}c.4-1 1.8-1 2.2 0`} />
)
// Hai vạch lấp lánh phía trên logo.
const ticks = (x: number, y: number) => <path d={`M${x - 1.6} ${y}l.6 1.8M${x + 1.6} ${y}l-.6 1.8`} />
const folder = 'M3.5 8A3 3 0 0 1 6.5 5h2.8c.7 0 1.3.3 1.8.8L12.5 7.5h5a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3h-11a3 3 0 0 1-3-3z'
const external = <path d="M13.5 4.5h6v6M19.5 4.5 11.5 12.5M18.5 14v2.5a3 3 0 0 1-3 3h-8a3 3 0 0 1-3-3v-8a3 3 0 0 1 3-3H10" />

/* Điều hướng */
export const Home = icon('Home', <><path d="M4 11.2 11 5.2a1.6 1.6 0 0 1 2 0l7 6M5.5 10v7a3 3 0 0 0 3 3h7a3 3 0 0 0 3-3v-7" /><path d="M9.8 15.2c1.2 1.1 3.2 1.1 4.4 0" /></>)
// Chữ O của logo: mặt méo hơi nghiêng, tai nghe chữ D ôm sát, mắt ^ ^ nét mảnh hơn cho khỏi thành cục.
const botTicks = 'M9.6 2.6l.9 2.4M14.6 2.4l-1 2.4'
const botFace = 'M11.6 7.7C15.6 7.3 18.3 9.4 18.2 12.6 18.1 16.8 15.6 19.6 12.4 19.7 8.6 19.8 6 17.6 5.9 14.2 5.8 10.6 8.2 8 11.6 7.7z'
const botCups = 'M6.65 10.8C4.3 10.6 3.5 11.8 3.5 13.5S4.2 16.3 6.25 16.1M17.6 10.2c2.3-.1 3 1.1 3 2.6 0 1.7-.7 2.6-2.8 2.4'
const botEyes = 'M8.5 14.7c.4-1.6 2-1.6 2.4 0M13.2 14.4c.4-1.6 2-1.6 2.4 0'
export const Bot = icon('Bot', <><path d={botTicks} /><path d={botFace} /><path d={botCups} /><path strokeWidth="1.7" d={botEyes} /></>)
// Đội agent: hai mặt BOA thu nhỏ (0.72), mặt sau ló ra sau mặt trước qua một mặt nạ khoét khe quanh mặt trước.
// Nét quy đổi theo tỉ lệ: viền 1.8, mắt 1.5, khe 1 mỗi bên.
const place = (x: number, y: number) => `translate(${x - 12.05 * 0.72} ${y - 13.7 * 0.72}) scale(0.72)`
function BotsBody() {
  const id = `bots${useId().replace(/[^\w-]/g, '')}`
  return (
    <>
      <mask id={id} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
        <rect width="24" height="24" fill="white" />
        <g transform={place(8.8, 15.2)} stroke="black" fill="black" strokeWidth={3.8 / 0.72}><path d={botTicks} /><path d={botFace} /><path d={botCups} /></g>
      </mask>
      <g mask={`url(#${id})`}>
        <g transform={place(15.2, 10.6)} strokeWidth={1.8 / 0.72}><path d={botFace} /><path d={botCups} /><path strokeWidth={1.5 / 0.72} d={botEyes} /></g>
      </g>
      <g transform={place(8.8, 15.2)} strokeWidth={1.8 / 0.72}><path d={botTicks} /><path d={botFace} /><path d={botCups} /><path strokeWidth={1.5 / 0.72} d={botEyes} /></g>
    </>
  )
}
export const Bots = icon('Bots', <BotsBody />)
// Agent theo phòng ban (tên = tên mandate): mặt BOA thu nhỏ (0.8, giữ đỉnh vạch) chừa chỗ cho huy hiệu.
// Huy hiệu nét 1.5; `cut` khoét khe trên mặt quanh huy hiệu nằm đè lên mặt; `eyes` thay mắt ^ ^ khi cần nét mặt khác.
const botMini = (x: number, y: number, s: number) => (
  <g transform={`translate(${x - 12.05 * s} ${y - 11.05 * s}) scale(${s})`} strokeWidth={1.1 / s}>
    <path d={botTicks} /><path d={botFace} /><path d={botCups} /><path strokeWidth={1 / s} d={botEyes} />
  </g>
)
function agentIcon(name: string, badge: ReactNode, cut?: ReactNode, eyes = botEyes): IconComponent {
  function Body() {
    const id = `agent${useId().replace(/[^\w-]/g, '')}`
    const face = (
      <g transform="translate(2.2 .48) scale(.8)" strokeWidth={2 / .8}>
        <path d={botTicks} /><path d={botFace} /><path d={botCups} /><path strokeWidth={1.7 / .8} d={eyes} />
      </g>
    )
    return (
      <>
        {cut && (
          <mask id={id} maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">
            <rect width="24" height="24" fill="white" />
            <g fill="black" stroke="none">{cut}</g>
          </mask>
        )}
        <g mask={cut ? `url(#${id})` : undefined}>{face}</g>
        <g strokeWidth="1.5">{badge}</g>
      </>
    )
  }
  return icon(name, <Body />)
}
export const AgentCoordinator = agentIcon('AgentCoordinator',
  <path d="M14.8 17a3.6 3.6 0 0 1 6.8 0M22.1 15.7l-.5 1.3-1.2-.7M21.6 19.4a3.6 3.6 0 0 1-6.8 0M14.3 20.7l.5-1.3 1.2.7" />,
  <circle cx="18.2" cy="18.2" r="5.1" />)
export const AgentCustomerService = agentIcon('AgentCustomerService',
  <><path d="M18.7 12.6c.5 1.8.3 3.6-.9 4.6" /><circle cx="17.2" cy="17.8" r="1.2" fill="currentColor" /></>)
export const AgentExecutive = agentIcon('AgentExecutive',
  <><path d="M8.4 17.6l2.6 2.2M15.4 17.6l-2.6 2.2" /><path fill="currentColor" strokeWidth="1" d="M11.9 18l-1 1.2 1 2.6 1-2.6z" /></>,
  undefined, 'M9 14.1h1.4M13.7 13.8h1.4')
export const AgentFactory = agentIcon('AgentFactory',
  <>
    <path fill="currentColor" strokeWidth="1" d="M20 2c.3 1.5.9 2.1 2.4 2.4-1.5.3-2.1.9-2.4 2.4-.3-1.5-.9-2.1-2.4-2.4 1.5-.3 2.1-.9 2.4-2.4z" />
    {botMini(18.3, 18.6, .42)}
  </>,
  <circle cx="18.3" cy="18.6" r="4.6" />)
export const AgentItSupport = agentIcon('AgentItSupport',
  <><path transform="translate(5.8 19) rotate(-45)" fill="currentColor" stroke="none" d="M-.6-4.3V-2.9H.6V-4.3A1.8 1.8 0 0 1 .7-.94V3.4a.7.7 0 0 1-1.4 0V-.94A1.8 1.8 0 0 1-.6-4.3z" /><rect x="14.4" y="14.6" width="8" height="5.6" rx="1.5" /><path d="M18.4 20.2v1.8M16.4 22.2h4" /></>,
  <rect x="13.2" y="13.4" width="10.4" height="8" rx="2.4" />)
export const AgentKnowledge = agentIcon('AgentKnowledge',
  <path d="M11.9 16.8c-1-.8-2.5-1.2-4.6-1.2v6c2.1 0 3.6.4 4.6 1.2 1-.8 2.5-1.2 4.6-1.2v-6c-2.1 0-3.6.4-4.6 1.2zM11.9 16.8v6" />,
  <rect x="6" y="14.4" width="11.8" height="9.6" rx="2" />)
export const AgentOrders = agentIcon('AgentOrders',
  <path d="M18.2 14.2l3.8 2v4.4l-3.8 2-3.8-2v-4.4zM14.4 16.2l3.8 2 3.8-2M18.2 18.2v4.4" />,
  <circle cx="18.2" cy="18.4" r="5.2" />)
// Icon theo tên mandate; agent chưa có icon riêng dùng Bot.
export const agentIcons: Record<string, IconComponent> = {
  coordinator: AgentCoordinator, customer_service: AgentCustomerService, executive: AgentExecutive, factory: AgentFactory,
  it_support: AgentItSupport, knowledge: AgentKnowledge, orders: AgentOrders,
}
export const Users = icon('Users', <><circle cx="9" cy="8.5" r="3.6" /><path d="M3.2 19.5c.8-3 3-4.8 5.8-4.8s5 1.8 5.8 4.8M15.6 5.2a3.6 3.6 0 0 1 .3 6.6M17.6 14.9c1.6.7 2.7 2.2 3.2 4.6" /></>)
export const MessagesSquare = icon('MessagesSquare', <><path d="M7 4h6a3.5 3.5 0 0 1 3.5 3.5v2A3.5 3.5 0 0 1 13 13H9.2L5.6 15.8a.6.6 0 0 1-1-.5v-3A3.5 3.5 0 0 1 3.5 9.5v-2A3.5 3.5 0 0 1 7 4z" /><path d="M19.2 9.4a3.3 3.3 0 0 1 1.3 2.6v2a3.4 3.4 0 0 1-1.6 2.9v2.4a.5.5 0 0 1-.8.4l-2.9-2.3h-2.4a3.4 3.4 0 0 1-2.6-1.2" /></>)
// Phiên làm việc (màn quản trị soi lại từng room): phiếu nhật ký để hở góc, kính lúp đặt vào chỗ hở.
// Khác hẳn bong bóng chat của Room: đây là xem lại, không phải trò chuyện.
export const SessionTrace = icon('SessionTrace', <><path d="M12.4 20H7.5A3.5 3.5 0 0 1 4 16.5v-9A3.5 3.5 0 0 1 7.5 4h9A3.5 3.5 0 0 1 20 7.5v3.6" /><path d="M8 8.6h8M8 12.2h4.4" /><circle cx="16.4" cy="16.4" r="2.9" /><path d="m18.6 18.6 2.1 2.1" /></>)
export const BarChart3 = icon('BarChart3', <path d="M4 20h16M7.5 16.5v-4M12 16.5V7M16.5 16.5v-6.5" />)
export const Radar = icon('Radar', <><path d="M20.5 12a8.5 8.5 0 1 1-4.2-7.3" /><path d="M16.5 12A4.5 4.5 0 1 1 12 7.5" /><path d="m12 12 6-6" />{dot(12, 12)}</>)
export const Contact = icon('Contact', <><rect x="4" y="3.5" width="16" height="17" rx="4.5" /><circle cx="12" cy="11" r="3.4" /><path d="M8.3 17.2c1-.9 2.3-1.3 3.7-1.3s2.7.4 3.7 1.3" /></>)
export const BookOpen = icon('BookOpen', <path d="M12 7c-1.6-1.5-4-2.3-8-2.2v12.6c4-.1 6.4.7 8 2.1 1.6-1.4 4-2.2 8-2.1V4.8c-4-.1-6.4.7-8 2.2zM12 7v12.5" />)
export const Settings = icon('Settings', <><path d="M10.3 3.6a3.4 3.4 0 0 1 3.4 0l5 2.9a3.4 3.4 0 0 1 1.7 2.9v5.2a3.4 3.4 0 0 1-1.7 2.9l-5 2.9a3.4 3.4 0 0 1-3.4 0l-5-2.9a3.4 3.4 0 0 1-1.7-2.9V9.4a3.4 3.4 0 0 1 1.7-2.9z" /><circle cx="12" cy="12" r="3" /></>)
export const PanelLeft = icon('PanelLeft', <><rect x="3.5" y="4.5" width="17" height="15" rx="4" /><path d="M9.5 5v14" /></>)
export const PanelLeftClose = icon('PanelLeftClose', <><rect x="3.5" y="4.5" width="17" height="15" rx="4" /><path d="M9.5 5v14M15.5 10l-2 2 2 2" /></>)

/* Hướng và thao tác cơ bản */
export const ChevronDown = icon('ChevronDown', <path d="m7 10 5 5 5-5" />)
export const ChevronRight = icon('ChevronRight', <path d="m10 7 5 5-5 5" />)
export const ChevronLeft = icon('ChevronLeft', <path d="m14 7-5 5 5 5" />)
export const ArrowLeft = icon('ArrowLeft', <path d="M19 12H5.5M11 6.5 5.5 12l5.5 5.5" />)
export const ArrowRight = icon('ArrowRight', <path d="M5 12h13.5M13 6.5l5.5 5.5-5.5 5.5" />)
export const Plus = icon('Plus', <path d="M12 5.5v13M5.5 12h13" />)
export const X = icon('X', <path d="M7 7l10 10M17 7 7 17" />)
export const Check = icon('Check', <path d="m5.5 12.5 4 4 9-9" />)
export const CheckCircle2 = icon('CheckCircle2', <><path d="M20.5 12a8.5 8.5 0 1 1-3.6-6.9" /><path d="m8.5 11.8 2.8 2.8 8.2-8.3" /></>)
export const Search = icon('Search', <><circle cx="10.8" cy="10.8" r="6.3" /><path d="m15.6 15.6 4 4" /></>)
export const Filter = icon('Filter', <path d="M5.2 5h13.6a1 1 0 0 1 .8 1.6L14 13.4v4.8a1 1 0 0 1-.6.9l-2 1a1 1 0 0 1-1.4-.9v-5.8L4.4 6.6A1 1 0 0 1 5.2 5z" />)
export const MoreVertical = icon('MoreVertical', <>{dot(12, 5.5)}{dot(12, 12)}{dot(12, 18.5)}</>)
export const Info = icon('Info', <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5" />{dot(12, 7.8)}</>)
export const Undo2 = icon('Undo2', <path d="M9 14 4.5 9.5 9 5M4.5 9.5H15a4.5 4.5 0 0 1 0 9h-3" />)
export const RefreshCw = icon('RefreshCw', <path d="M19.5 12a7.5 7.5 0 0 1-13.2 4.9M4.5 12a7.5 7.5 0 0 1 13.2-4.9M18 3.5v4h-4M6 20.5v-4h4" />)
export const Download = icon('Download', <path d="M12 4.5V15M7.5 11l4.5 4.5 4.5-4.5M5.5 19.5h13" />)
export const Upload = icon('Upload', <path d="M12 15.5V5M7.5 9 12 4.5 16.5 9M5.5 19.5h13" />)
export const ExternalLink = icon('ExternalLink', external)
export const SquareArrowOutUpRight = icon('SquareArrowOutUpRight', external)

/* Soạn thảo và nội dung */
export const Send = icon('Send', <path d="M19.6 4.2 4.8 10.1a.6.6 0 0 0 0 1.1l5.7 2.3 2.3 5.7a.6.6 0 0 0 1.1 0zM10.5 13.5l4-4" />)
export const Copy = icon('Copy', <><rect x="8.5" y="8.5" width="12" height="12" rx="3.5" /><path d="M15.5 8.5V7a3.5 3.5 0 0 0-3.5-3.5H7A3.5 3.5 0 0 0 3.5 7v5A3.5 3.5 0 0 0 7 15.5h1.5" /></>)
export const Pencil = icon('Pencil', <path d="M14.2 5.8l4 4M4.5 19.5l.9-4.2L15.6 5.1a1.8 1.8 0 0 1 2.5 0l1.3 1.3a1.8 1.8 0 0 1 0 2.5L9.2 19.1z" />)
export const SquarePen = icon('SquarePen', <><path d="M11 4.5H8A3.5 3.5 0 0 0 4.5 8v8A3.5 3.5 0 0 0 8 19.5h8a3.5 3.5 0 0 0 3.5-3.5v-3" /><path d="M17.6 4a1.7 1.7 0 0 1 2.4 2.4l-7.4 7.4-3.1.7.7-3.1z" /></>)
/* Trạng thái room ở sidebar: cùng một vòng méo vẽ tay như mặt BOA, khác nhau ở dấu bên trong.
   Đang chạy là vòng hở (kẻ 62/38) để xoay; chờ bạn có dấu chấm than; xong có dấu tích; lỗi có dấu x. */
const ring = 'M11.7 4.4C16.2 4 19.7 6.9 19.6 11.4 19.5 16.4 16.4 19.7 12.2 19.8 7.6 19.9 4.4 17.1 4.3 12.5 4.2 8.1 7.5 4.8 11.7 4.4z'
export const StateRunning = icon('StateRunning', <path d={ring} pathLength={100} strokeDasharray="62 38" />)
export const StateWaiting = icon('StateWaiting', <><path d={ring} /><path d="M12 8.6v3.9" />{dot(12, 15.5)}</>)
export const StateDone = icon('StateDone', <><path d={ring} /><path d="m8.7 12.3 2.2 2.3 4.4-4.8" /></>)
export const StateFailed = icon('StateFailed', <><path d={ring} /><path d="M9.7 9.7l4.6 4.6M14.3 9.7l-4.6 4.6" /></>)
// Dừng lượt chạy: hai vạch đứng, nét bo tròn như phần còn lại của bộ icon
export const Pause = icon('Pause', <path d="M9 6.5v11M15 6.5v11" />)
export const Trash2 = icon('Trash2', <path d="M4.5 7h15M9.5 4h5M6.5 7l.8 10.6a3 3 0 0 0 3 2.9h3.4a3 3 0 0 0 3-2.9L17.5 7M10.2 11v4.5M13.8 11v4.5" />)
export const Archive = icon('Archive', <><rect x="3.5" y="4" width="17" height="4.5" rx="2" /><path d="M5 8.5v8a3 3 0 0 0 3 3h8a3 3 0 0 0 3-3v-8M10 12.5h4" /></>)
export const FileText = icon('FileText', <path d="M14.5 3.5H8A3 3 0 0 0 5 6.5v11A3 3 0 0 0 8 20.5h8a3 3 0 0 0 3-3V8zM14.5 3.5V8H19M8.8 12.5h6.4M8.8 16h4.4" />)
export const ScrollText = icon('ScrollText', <><rect x="4" y="3.5" width="16" height="17" rx="4" /><path d="M8 8.5h8M8 12h8M8 15.5h4.5" /></>)
export const Paperclip = icon('Paperclip', <path d="m19.5 11.5-7.4 7.4a4.6 4.6 0 0 1-6.5-6.5l7.8-7.8a3 3 0 0 1 4.3 4.3l-7.6 7.6a1.5 1.5 0 0 1-2.1-2.1l6.9-6.9" />)
export const AtSign = icon('AtSign', <><circle cx="12" cy="12" r="3.5" /><path d="M15.5 8.5v4.8a2.4 2.4 0 0 0 4.8 0V12a8.5 8.5 0 1 0-3.4 6.8" /></>)
export const Mail = icon('Mail', <><rect x="3.5" y="5.5" width="17" height="13" rx="4" /><path d="m4.8 8.2 6.3 4.5a1.6 1.6 0 0 0 1.8 0l6.3-4.5" /></>)
export const MessageSquarePlus = icon('MessageSquarePlus', <path d="M7.5 4.5h9A3.5 3.5 0 0 1 20 8v5.5a3.5 3.5 0 0 1-3.5 3.5h-6.2l-4.1 3.1a.6.6 0 0 1-1-.5V17A3.5 3.5 0 0 1 4 13.5V8a3.5 3.5 0 0 1 3.5-3.5zM12 7.8v5.4M9.3 10.5h5.4" />)

/* Thư mục */
export const Folder = icon('Folder', <path d={folder} />)
export const FolderPlus = icon('FolderPlus', <><path d={folder} /><path d="M12 10.8v5.4M9.3 13.5h5.4" /></>)
export const FolderOpen = icon('FolderOpen', <path d="M3.5 16.5V8A3 3 0 0 1 6.5 5h2.8c.7 0 1.3.3 1.8.8L12.5 7.5H16a3 3 0 0 1 3 3M3.5 16.5l2-4.6A2.5 2.5 0 0 1 7.8 10.5h12a1 1 0 0 1 .9 1.4L18.6 17a3.5 3.5 0 0 1-3.2 2.5H6.5a3 3 0 0 1-3-3z" />)

/* Cài đặt, trạng thái, số liệu */
export const Bell = icon('Bell', <><path d="M6.5 16.5v-5a5.5 5.5 0 0 1 11 0v5l1.3 1.8a.5.5 0 0 1-.4.7H5.6a.5.5 0 0 1-.4-.7zM10 21a2.3 2.3 0 0 0 4 0" />{ticks(12, 1.6)}</>)
export const UserCircle = icon('UserCircle', <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="10" r="3.2" />{smile(12, 10, 1.3)}<path d="M6.8 18.4c1.3-1.6 3.1-2.5 5.2-2.5s3.9.9 5.2 2.5" /></>)
export const SlidersHorizontal = icon('SlidersHorizontal', <><path d="M4 7h8.5M17.5 7H20M4 17h2.5M11.5 17H20" /><circle cx="15" cy="7" r="2.3" /><circle cx="9" cy="17" r="2.3" /></>)
export const Palette = icon('Palette', <><path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.1 0 1.6-.8 1.6-1.6 0-1.3-1.1-1.6-1.1-2.7 0-.9.7-1.6 1.6-1.6h2a3.4 3.4 0 0 0 3.4-3.4c0-4.3-3.3-7.7-7.5-7.7z" />{dot(8, 11)}{dot(10.5, 7.5)}{dot(14.5, 7.5)}</>)
export const Plug = icon('Plug', <path d="M9 3.5V8M15 3.5V8M6.5 8h11v3a5.5 5.5 0 0 1-11 0zM12 16.5v4" />)
export const Cpu = icon('Cpu', <><rect x="6" y="6" width="12" height="12" rx="3.5" /><rect x="9.5" y="9.5" width="5" height="5" rx="1.5" /><path d="M9.5 3v3M14.5 3v3M9.5 18v3M14.5 18v3M3 9.5h3M3 14.5h3M18 9.5h3M18 14.5h3" /></>)
export const FlaskConical = icon('FlaskConical', <path d="M9.5 3.5h5M10.2 3.5V9l-5 8.8a1.8 1.8 0 0 0 1.6 2.7h10.4a1.8 1.8 0 0 0 1.6-2.7l-5-8.8V3.5M7.6 15h8.8" />)
export const SquareTerminal = icon('SquareTerminal', <><rect x="3.5" y="4.5" width="17" height="15" rx="4" /><path d="m7.5 9.5 2.5 2.5-2.5 2.5M12.5 15h4" /></>)
export const Sparkles = icon('Sparkles', <><path d="M11 6.5c.6 3.2 2 4.6 5.2 5.2-3.2.6-4.6 2-5.2 5.2-.6-3.2-2-4.6-5.2-5.2 3.2-.6 4.6-2 5.2-5.2z" />{ticks(17.5, 2.8)}<path d="M19 18.5v.01" /></>)
export const ShieldCheck = icon('ShieldCheck', <path d="M11.3 3.7a2 2 0 0 1 1.4 0l5 1.9A2 2 0 0 1 19 7.5v4c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9v-4a2 2 0 0 1 1.3-1.9zM9 12l2.2 2.2L15.5 10" />)
export const KeyRound = icon('KeyRound', <><circle cx="8.5" cy="15.5" r="4" /><path d="m11.4 12.6 8.1-8.1M16.5 7.5 19 10" /></>)
export const Eye = icon('Eye', <><path d="M2.8 12.6a1.4 1.4 0 0 1 0-1.2C4.6 7.8 8 5.5 12 5.5s7.4 2.3 9.2 5.9a1.4 1.4 0 0 1 0 1.2c-1.8 3.6-5.2 5.9-9.2 5.9s-7.4-2.3-9.2-5.9z" /><circle cx="12" cy="12" r="3" /></>)
export const EyeOff = icon('EyeOff', <path d="M10 5.7c.6-.1 1.3-.2 2-.2 4 0 7.4 2.3 9.2 5.9a1.4 1.4 0 0 1 0 1.2 13 13 0 0 1-2.1 3.1M6.6 6.6C5 7.7 3.7 9.3 2.8 11.4a1.4 1.4 0 0 0 0 1.2c1.8 3.6 5.2 5.9 9.2 5.9 1.9 0 3.5-.5 4.9-1.4M9.9 9.9a3 3 0 0 0 4.2 4.2M4 4l16 16" />)
export const Play = icon('Play', <path d="M7.5 6.2v11.6a1.5 1.5 0 0 0 2.3 1.3l9.1-5.8a1.5 1.5 0 0 0 0-2.6L9.8 4.9a1.5 1.5 0 0 0-2.3 1.3z" />)
export const Power = icon('Power', <path d="M12 3.5v8M7 6.5a7.5 7.5 0 1 0 10 0" />)
export const Crown = icon('Crown', <path d="M4.6 8.4 8 11.5l3.2-5.2a.9.9 0 0 1 1.6 0l3.2 5.2 3.4-3.1a.6.6 0 0 1 1 .5l-1.3 9a1.5 1.5 0 0 1-1.5 1.3H6.4a1.5 1.5 0 0 1-1.5-1.3l-1.3-9a.6.6 0 0 1 1-.5z" />)
export const CalendarDays = icon('CalendarDays', <><rect x="3.5" y="5" width="17" height="15.5" rx="4" /><path d="M3.5 10h17M8 3v4M16 3v4M8 14h.01M12 14h.01M16 14h.01M8 17.5h.01M12 17.5h.01" /></>)
export const Activity = icon('Activity', <path d="M3.5 12H7l2.5-6 5 12 2.5-6h3.5" />)
export const Zap = icon('Zap', <path d="M12.6 3.9 5.6 12.7a.6.6 0 0 0 .5 1H11l-.8 6a.4.4 0 0 0 .7.3l7-8.8a.6.6 0 0 0-.5-1H13l.8-6a.4.4 0 0 0-.7-.3z" />)
export const Globe = icon('Globe', <><circle cx="12" cy="12" r="8.5" /><path d="M3.5 12h17M12 3.5c2.3 2.4 3.4 5.2 3.4 8.5s-1.1 6.1-3.4 8.5c-2.3-2.4-3.4-5.2-3.4-8.5S9.7 5.9 12 3.5z" /></>)
