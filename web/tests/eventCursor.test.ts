import { describe, expect, it } from 'vitest'
import { applyEventCursor } from '../src/api/eventCursor'

describe('applyEventCursor 事件游标推进', () => {
  it('控制帧（event_id=0）始终接受且不推进游标', () => {
    let out = applyEventCursor(0, { event_id: 0 })
    expect(out).toEqual({ accepted: true, nextCursor: 0, needRestore: false })
    out = applyEventCursor(42, { event_id: 0 })
    expect(out).toEqual({ accepted: true, nextCursor: 42, needRestore: false })
  })

  it('首个带号事件建立游标', () => {
    const out = applyEventCursor(0, { event_id: 7 })
    expect(out).toEqual({ accepted: true, nextCursor: 7, needRestore: false })
  })

  it('重复事件（event_id ≤ 游标）丢弃', () => {
    const out = applyEventCursor(10, { event_id: 10 })
    expect(out).toEqual({ accepted: false, nextCursor: 10, needRestore: false })
    const older = applyEventCursor(10, { event_id: 3 })
    expect(older).toEqual({ accepted: false, nextCursor: 10, needRestore: false })
  })

  it('连续事件接受并推进', () => {
    let out = applyEventCursor(10, { event_id: 11 })
    expect(out).toEqual({ accepted: true, nextCursor: 11, needRestore: false })
    out = applyEventCursor(11, { event_id: 12 })
    expect(out).toEqual({ accepted: true, nextCursor: 12, needRestore: false })
  })

  it('跳号事件接受并要求补洞（needRestore）', () => {
    const out = applyEventCursor(10, { event_id: 15 })
    expect(out).toEqual({ accepted: true, nextCursor: 15, needRestore: true })
  })

  it('重连重放窗口内的小回退（如重放子序列）不重置游标', () => {
    // 重放通常从 cursor-1 或 cursor+1 开始；此处 event_id=10 == cursor
    // 已由重复分支处理。真正的正常重连不会出现远小于游标的 ID。
    const out = applyEventCursor(10, { event_id: 10 })
    expect(out.accepted).toBe(false)
  })

  it('跨重启：服务端 ID 从 1 重新计数时重置游标接受新事件流', () => {
    // 游标已到 5000；服务端重启后新事件 event_id=1。
    // 不加保护时 1 <= 5000 会被当重复事件丢弃 → 界面永久冻结。
    const out = applyEventCursor(5000, { event_id: 1 })
    expect(out).toEqual({ accepted: true, nextCursor: 1, needRestore: false })
    // 后续新事件流正常推进
    const next = applyEventCursor(1, { event_id: 2 })
    expect(next).toEqual({ accepted: true, nextCursor: 2, needRestore: false })
  })

  it('小回退（游标 100 内）仍按重复丢弃，不误触发跨重启重置', () => {
    // 乱序到达的极小回退（如 990 < 1000）不属于重启特征
    const out = applyEventCursor(1000, { event_id: 990 })
    expect(out).toEqual({ accepted: false, nextCursor: 1000, needRestore: false })
  })

  it('游标回退后允许更大跳变作为新流接受（重启后首事件不是 1）', () => {
    const out = applyEventCursor(5000, { event_id: 3999 })
    expect(out).toEqual({ accepted: true, nextCursor: 3999, needRestore: false })
  })
})
