'use client'

import { Fragment, useTransition, type ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { RefreshCw } from '../../components/icons'
import { PageHeader } from '../../components/PageHeader'
import { agentCatalog } from '../../mocks/agentCatalog'
import type { ThreadItem } from '../../mocks/staff'
import type { RoomDetail, Run, TraceEvent } from '../../api/admin'
import {
  answerParts, clock, liveItems, planMessage, reviewMessage, stepReply, toItems, type Progress, type SessionItem,
} from '../../api/sessions'
import { ThreadItemView, workingGroup } from '../requests/ThreadItems'
import { cost, Crumbs, departmentName, statusLabel, tokens, when } from './UsagePages'
import styles from './AdminTrace.module.css'

// Room như nhân viên thấy (Điều phối @agent, agent trả lời lại), dựng từ trace theo đúng thứ tự đã
// xảy ra; dưới tên mỗi tin là những gì agent đã làm để ra tin đó: từng lượt gọi model (model, token,
// $), từng công cụ kèm tham số và kết quả, các lần code từ chối.

const agentName = (id?: string) => (id ? agentCatalog.find((a) => a.id === id)?.name ?? id : '')

// Event của chính agent (không phải mốc của Điều phối): gom vào tin mà chúng tạo ra.
// `model_wait` chỉ có lúc đang chạy: agent đã vào lượt mới, model chưa trả lời.
const WORK = new Set(['llm_call', 'tool_call', 'tool_result', 'agent_finished', 'model_wait'])

const secondsBetween = (from?: string, to?: string) =>
  from && to ? Math.max(0, (Date.parse(to) - Date.parse(from)) / 1000) : undefined

/** JSON đẹp nếu đọc được, không thì để nguyên. */
function pretty(text: unknown) {
  if (typeof text !== 'string') return JSON.stringify(text, null, 2)
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}

function Fold({ label, text }: { label: string; text: unknown }) {
  if (text === undefined || text === null || text === '') return null
  return (
    <details>
      <summary>{label}</summary>
      <pre>{pretty(text)}</pre>
    </details>
  )
}

/** Một việc agent đã làm; `name` của tool_result là công cụ mà kết quả này trả lời. */
function WorkLine({ e }: { e: TraceEvent }) {
  const s = (k: string) => e[k] as string
  const n = (k: string) => e[k] as number
  switch (e.event) {
    case 'llm_call':
      return (
        <div className={styles.dim}>
          Gọi <code>{s('model')}</code> · {tokens(n('prompt_tokens'))} → {tokens(n('completion_tokens'))} tokens
          · {e.cost_usd === null ? '$ —' : cost({ cost_usd: n('cost_usd'), unpriced_calls: 0 })} · {(n('duration_ms') / 1000).toFixed(1)}s
          {n('attempts') > 1 && <span className={styles.warn}> · thử {n('attempts')} lần</span>}
          {s('finish_reason') === 'length' && <span className={styles.bad}> · bị cắt vì hết token đầu ra</span>}
          <Fold label="Nội dung model viết" text={e.text} />
        </div>
      )
    case 'tool_call':
      return (
        <div>
          → <code>{s('name')}</code>
          <Fold label="Tham số" text={e.arguments} />
        </div>
      )
    case 'tool_result': {
      const name = s('name') ?? s('id')
      const rejected = e.is_error && name === 'final_answer'
      return (
        <div className={e.is_error ? styles.bad : undefined}>
          ← <code>{name}</code> {rejected ? 'bị code từ chối' : e.is_error ? 'lỗi' : <span className={styles.good}>ok</span>}
          <Fold label={rejected ? 'Lý do từ chối' : 'Kết quả'} text={e.content} />
        </div>
      )
    }
    case 'agent_finished':
      return s('status') === 'done' ? null : (
        <div className={styles.bad}>Dừng: {s('status')}{e.reason ? ` (${s('reason')})` : ''} sau {n('steps')} lượt</div>
      )
    case 'model_wait':
      return <div className={`${styles.dim} ${styles.waiting}`}>Lượt {n('step')}/{n('max_steps')} · đang chờ model trả lời…</div>
    default:
      return null
  }
}

function Work({ events, start }: { events: TraceEvent[]; start: number }) {
  const calls = events.filter((e) => e.event === 'llm_call')
  const spent = {
    cost_usd: calls.reduce((s, e) => s + ((e.cost_usd as number | null) ?? 0), 0),
    unpriced_calls: calls.filter((e) => e.cost_usd === null).length,
  }
  return (
    <div className={styles.work}>
      {calls.length > 0 && (
        <p className={styles.dim}>
          {calls.length} lượt gọi model · {tokens(calls.reduce((s, e) => s + (e.prompt_tokens as number), 0))} →
          {' '}{tokens(calls.reduce((s, e) => s + (e.completion_tokens as number), 0))} tokens · {cost(spent)}
        </p>
      )}
      {/* Agent xong bình thường không có dòng nào để hiện */}
      {events.filter((e) => !(e.event === 'agent_finished' && e.status === 'done')).map((e, i) => (
        <div key={i} className={styles.row}>
          <time>+{((Date.parse(e.at) - start) / 1000).toFixed(1)}s</time>
          <div className={styles.line}><WorkLine e={e} /></div>
        </div>
      ))}
    </div>
  )
}

const withWork = (item: ThreadItem, work: ReactNode): ThreadItem => (item.kind === 'message' ? { ...item, work } : item)

/**
 * Các tin của một lượt chạy: `segment` là phần thread của lượt đó (yêu cầu hoặc câu trả lời, rồi kết
 * quả), `run` là trace đã lưu. Lượt chạy trước khi có trace thì hiện như màn nhân viên.
 */
function runItems(run: Run | undefined, segment: SessionItem[], startedAt?: string): ThreadItem[] {
  if (!run) return segment.flatMap((i) => toItems(i, startedAt))
  const start = Date.parse(run.started_at)
  const out: ThreadItem[] = segment.flatMap((i) => (i.kind === 'request' ? toItems(i) : []))
  const toolNames = new Map<string, string>()
  const lastReview: Record<string, string> = {}
  let planningSince: string | undefined
  // Việc đang gom theo (step, agent), `start` là vị trí trong trace của việc đầu tiên: các step chạy cùng
  // lúc ghi event xen kẽ nhau. Việc ngoài step của Điều phối (lập plan, tổng hợp, agent Jev giao thẳng) có step rỗng.
  const work = new Map<string, { start: number; events: TraceEvent[] }>()
  const keyOf = (step: unknown, agent: unknown) => `${typeof step === 'string' ? step : ''}|${agent as string}`
  const outside = (key: string) => key.startsWith('|')
  // Việc của một step; trace lưu trước khi có step_id thì việc nằm ngoài step
  const stepKey = (step: string, agent: string) => (work.has(keyOf(step, agent)) ? keyOf(step, agent) : keyOf(undefined, agent))
  // Tin mang phần việc thì lấy id theo phần việc (id tin chỉ có phần việc theo vị trí đó, nên bản live
  // và bản đã lưu trùng id): tin "đang làm" lúc live và tin trả lời sau đó là một tin, cập nhật tại chỗ
  const own = (key: string, id: string) => {
    const w = work.get(key)
    return w ? `work-${run.run}-${w.start}` : id
  }
  const take = (key: string) => {
    const w = work.get(key)
    work.delete(key)
    return w ? <Work events={w.events} start={start} /> : undefined
  }
  // Việc chưa thành tin nào (agent dừng giữa chừng, chuyển cho Điều phối): một tin chỉ có phần việc
  const flush = (only: (key: string) => boolean = () => true) => {
    for (const [key, w] of [...work]) {
      if (!only(key)) continue
      const first = w.events[0]
      out.push({ kind: 'message', id: `work-${run.run}-${w.start}`, time: clock(first.at), at: first.at,
        agent: first.agent ?? 'coordinator', body: [], work: take(key) })
    }
  }

  run.trace.forEach((e, n) => {
    const id = `run${run.run}-${n}`
    const s = (k: string) => e[k] as string
    const seconds = e.seconds as number | undefined
    if (WORK.has(e.event)) {
      const key = keyOf(e.step_id, e.agent)
      // Ngoài step các agent làm lần lượt: agent khác bắt đầu thì việc của agent trước thành tin riêng
      if (outside(key)) flush((k) => outside(k) && k !== key)
      if (!work.has(key)) work.set(key, { start: n, events: [] })
      if (e.event === 'tool_call') toolNames.set(`${key}|${s('id')}`, s('name'))
      work.get(key)!.events.push(e.event === 'tool_result' ? { ...e, name: toolNames.get(`${key}|${s('id')}`) } : e)
      return
    }
    switch (e.event) {
      case 'route':
        flush()
        out.push({ kind: 'route', id, time: clock(e.at), body: `Chuyển cho ${agentName(s('target'))}` })
        break
      case 'phase':
        if (s('phase') === 'plan') planningSince = e.at
        break
      case 'plan': {
        const key = keyOf(undefined, 'coordinator')
        const item = planMessage(own(key, id), e.at, e.steps as { id: string; agent: string; label: string }[],
          secondsBetween(planningSince, e.at))
        const done = take(key)
        out.push(withWork(item, done))
        break
      }
      case 'step_done': {
        const key = stepKey(s('id'), s('agent'))
        out.push(withWork(stepReply(own(key, id), e.at, s('agent'),
          (e.result as Record<string, unknown> | undefined) ?? { summary: e.summary }, seconds), take(key)))
        break
      }
      case 'step_reviewed': {
        const key = stepKey(s('id'), 'coordinator')
        lastReview[s('id')] = s('decision')
        out.push(withWork(reviewMessage(own(key, id), e.at, s('agent'),
          { decision: s('decision'), note: e.note as string | null, seconds }), take(key)))
        break
      }
      case 'step_failed': {
        // Điều phối đã nói phần này phải lập lại kế hoạch; còn lại là hết lượt mà không qua được code
        const key = stepKey(s('id'), s('agent'))
        if (lastReview[s('id')] !== 'replan') out.push(withWork(stepReply(own(key, id), e.at, s('agent'), null, seconds), take(key)))
        else flush((k) => k === key)
        break
      }
    }
  })

  for (const i of segment) {
    if (i.kind === 'result') {
      // Như màn nhân viên: không agent nào chạy (chưa có quyền, nhánh chưa nối) là thông báo của hệ thống
      const agent = Object.keys(i.result).length === 0 ? 'coordinator' : i.agent
      const key = keyOf(undefined, agent)
      flush((k) => outside(k) && k !== key)
      out.push({ kind: 'message', id: own(key, i.id), time: clock(i.at), at: i.at, agent, ...answerParts(i.result, i.output),
        status: { label: 'Worked', seconds: secondsBetween(startedAt, i.at) }, work: take(key) })
    } else if (i.kind === 'clarify' || i.kind === 'approval' || i.kind === 'agent_proposal' || i.kind === 'failed') {
      flush()
      out.push(...toItems(i, startedAt))
    }
  }
  flush()
  return out
}

// Agent Factory đề xuất mà nhân viên đã đồng ý: lượt sau (Điều phối làm lại với agent đó) bắt đầu lúc duyệt
const approvedAgent = (i: SessionItem | undefined) =>
  i?.kind === 'agent_proposal' && i.decision?.value === 'yes' ? i.decision.at : undefined

/**
 * Thread chia theo lượt chạy như máy chủ đánh số: mỗi yêu cầu, mỗi câu trả lời hỏi lại và mỗi agent
 * mới được duyệt mở một lượt mới. Kèm lúc lượt bắt đầu, để tính thời gian.
 */
function segments(items: SessionItem[]): { items: SessionItem[]; startedAt: string }[] {
  const out: { items: SessionItem[]; startedAt: string }[] = []
  let approved: string | undefined
  for (const i of items) {
    if (i.kind === 'request' || i.kind === 'reply' || approved || !out.length) out.push({ items: [i], startedAt: approved ?? i.at })
    else out[out.length - 1].items.push(i)
    approved = approvedAgent(i)
  }
  return out
}

/** Cả room dựng từ trace đã lưu: dùng cho room của chính admin trên /rooms khi lượt chạy đã xong. */
export function traceItems(room: Pick<RoomDetail, 'items' | 'runs'>): ThreadItem[] {
  return segments(room.items).flatMap((s, n) => runItems(room.runs.find((r) => r.run === n), s.items, s.startedAt))
}

/**
 * Tin của lượt đang chạy trong room của admin, dựng từ tiến độ đầy đủ (máy chủ gửi cả lượt gọi model,
 * tham số và kết quả công cụ): như trace đã lưu, cộng dòng ai đang làm gì của liveItems ở cuối, kèm phần
 * việc agent đó đang làm dở. `run` là số thứ tự lượt chạy (0, mỗi yêu cầu tiếp hay câu trả lời hỏi lại thêm 1): id các tin
 * trùng với bản dựng từ trace đã lưu (traceItems), nên lúc lượt xong và thay bằng bản lưu không tin nào vẽ lại.
 */
export function liveTraceItems(received: Progress[], run: number): ThreadItem[] {
  const now = new Date().toISOString()
  const trace: TraceEvent[] = received.map((e) => ({ ...e.data, event: e.event, at: e.data.at ?? now }))
  // Lượt mới đã bắt đầu mà model chưa trả lời: một dòng chờ ở cuối phần việc, để thấy agent đang ở lượt nào.
  // Tính riêng cho từng (step, agent), vì các step chạy cùng lúc; dòng chờ mang `step_id` của lượt đó để nằm
  // cùng phần việc của đúng step thay vì thành tin riêng.
  const latest = new Map<string, Progress>()
  for (const e of received) {
    if (e.event !== 'step' && (e.event as string) !== 'llm_call') continue
    const data = e.data as { agent: string; step_id?: string }
    latest.set(`${data.step_id ?? ''}|${data.agent}`, e)
  }
  for (const e of latest.values()) {
    if (e.event !== 'step') continue
    trace.push({ event: 'model_wait', at: e.data.at ?? now, agent: e.data.agent, step: e.data.step,
      max_steps: e.data.max_steps, step_id: e.data.step_id })
  }
  const items = runItems({
    run, started_at: trace[0]?.at ?? now, trace, input_tokens: 0, output_tokens: 0, cost_usd: 0, unpriced_calls: 0,
  }, [])
  // Dòng ai đang làm gì ở cuối liveItems: agent làm một mình và Điều phối, hoặc chỉ dòng chờ định tuyến
  const live = liveItems(received)
  const statuses = live.filter((i) => i.id === 'running' || i.id === 'live-active' || i.id.startsWith('live-working-'))
  for (const status of statuses) {
    // Tin chỉ có phần việc (chưa thành câu trả lời) của đúng agent đang làm: gắn dòng trạng thái vào nó
    let at = items.length - 1
    while (at >= 0) {
      const i = items[at]
      if (status.kind === 'message' && i.kind === 'message' && !i.status && i.body.length === 0 && !i.mentions?.length
        && i.agent === status.agent) break
      at--
    }
    const target = items[at]
    if (status.kind === 'message' && target?.kind === 'message') items[at] = { ...status, id: target.id, work: target.work }
    else items.push(status)
  }
  // Khung song song chỉ để RequestsPage dán sticky bên phải lúc còn agent đang làm; xong thì khung trong luồng đã thay nó
  const parallel = workingGroup(live)
  if (parallel) items.push(parallel)
  return items
}

const ignore = () => {}

/** Room đã lấy trên server; Tải lại thì server lấy lại (router.refresh), trang giữ nguyên chỗ cuộn. */
export function TraceView({ department, userId, userName, room }: {
  department: string; userId: string; userName: string; room: RoomDetail
}) {
  const router = useRouter()
  const [reloading, startReload] = useTransition()
  const sum = (k: 'input_tokens' | 'output_tokens' | 'cost_usd' | 'unpriced_calls') =>
    room.runs.reduce((s, r) => s + r[k], 0)

  return (
    <>
      <PageHeader
        title={room.title}
        actions={
          <button className={styles.badge} disabled={reloading} onClick={() => startReload(() => router.refresh())}>
            <RefreshCw size={12} /> {reloading ? 'Đang tải…' : 'Tải lại'}
          </button>
        }
      />
      <div className={styles.body}>
        <Crumbs department={department} user={{ id: userId, name: userName }} room={room.title} />
        <div className={styles.summary}>
          <span>Trạng thái <b className={room.status === 'failed' ? styles.bad : undefined}>{statusLabel[room.status]}</b>
            {room.deleted_at && <span className={`${styles.badge} ${styles.badgeDanger}`}>nhân viên đã xóa</span>}</span>
          <span>Phòng ban <b>{room.departments.length ? room.departments.map(departmentName).join(', ') : departmentName('-')}</b></span>
          <span>Provider <b>{room.provider}</b></span>
          <span>Tạo lúc <b>{when(room.created_at)}</b></span>
          <span>Tokens <b>{tokens(sum('input_tokens'))} → {tokens(sum('output_tokens'))}</b></span>
          <span>Chi phí <b>{cost({ cost_usd: sum('cost_usd'), unpriced_calls: sum('unpriced_calls') })}</b></span>
        </div>
        {room.runs.length === 0 && room.status !== 'running' && (
          <p className={styles.muted}>Room này chạy trước khi ai-service lưu diễn tiến nên chỉ có phần nhân viên thấy.</p>
        )}
        <div className={styles.thread}>
          {segments(room.items).map((segment, n) => {
            const run = room.runs.find((r) => r.run === n)
            const first = segment.items[0]
            return (
              <Fragment key={n}>
                {n > 0 && run && (
                  <p className={styles.runNote}>
                    {first.kind === 'request' ? 'Yêu cầu tiếp' : first.kind === 'reply' ? 'Trả lời hỏi lại' : 'Duyệt agent mới'} · lượt #{n} · {tokens(run.input_tokens)} → {tokens(run.output_tokens)} tokens · {cost(run)}
                  </p>
                )}
                {runItems(run, segment.items, segment.startedAt).map((item) => (
                  <ThreadItemView key={item.id} item={item} onDecide={ignore} onAnswer={ignore} />
                ))}
              </Fragment>
            )
          })}
          {room.status === 'running' && (
            <p className={styles.runNote}>Đang chạy: diễn tiến của lượt này được lưu khi lượt xong. Bấm Tải lại để xem.</p>
          )}
        </div>
      </div>
    </>
  )
}
