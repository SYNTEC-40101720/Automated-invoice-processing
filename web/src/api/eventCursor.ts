import type { DomainEvent } from '../api/types'

/**
 * 事件游标推进规则（useWorkbenchEvents 内 connectEvents 回调的核心判定）。
 *
 * 抽成纯函数以便单测；返回值：
 * - accepted: 事件是否应交给 appendEvent 落地
 * - nextCursor: 游标推进后的值（调用方写回 lastEventId.current）
 *
 * 规则（与后端 events.py 帧语义对齐）：
 * 1. event_id 为 0 是控制帧（ready/heartbeat/服务端快照）：始终接受，
 *    不参与游标推进。
 * 2. 带号事件小于等于游标 → 重复事件，丢弃。
 * 3. 带号事件跳号（> cursor+1）→ 接受且调用方需触发补洞（needRestore）。
 * 4. 跨重启保护：带号事件明显小于游标（服务端重启后 event_id 从 1
 *    重新计数）→ 重置游标接受新事件流；否则旧游标会吞掉全部新事件，
 *    界面永久冻结。
 */
export function applyEventCursor(
  cursor: number,
  event: Pick<DomainEvent, 'event_id'>,
): { accepted: boolean; nextCursor: number; needRestore: boolean } {
  const id = event.event_id
  if (id <= 0) return { accepted: true, nextCursor: cursor, needRestore: false }
  // 跨重启：服务端事件历史清零后 ID 从 1 重新计数。
  // 阈值 1000 兼容单任务正常事件量，远小于跨重启的落差。
  if (cursor > 0 && id < cursor - 1000) {
    cursor = 0
  }
  const needRestore = cursor > 0 && id > cursor + 1
  if (id <= cursor) return { accepted: false, nextCursor: cursor, needRestore: false }
  return { accepted: true, nextCursor: id, needRestore }
}
