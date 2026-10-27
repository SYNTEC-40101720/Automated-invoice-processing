import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import type { Job } from '../src/api/types'
import { ProcessingView } from '../src/features/processing/ProcessingView'

vi.mock('../src/api/client', () => ({
  api: {
    jobHistory: vi.fn(async () => ({ items: [], next_event_id: null })),
  },
}))

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 'job-1',
    source_dir: 'C:/inbox',
    output_dir: 'C:/inbox/output',
    trigger: 'manual',
    status: 'succeeded',
    phase: 'done',
    progress: 1,
    message: '处理完成 — 成功 2/2',
    stats: { total: 2, success: 2, failure: 0, tax_issues: 0 },
    started_at: null,
    finished_at: null,
    cancel_requested: false,
    error_code: null,
    error_message: null,
    result: null,
    ...overrides,
  }
}

function renderProcessingView(job: Job): string {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(ProcessingView, {
        job,
        onChooseDirectory: () => {},
        onStart: () => {},
        onCancel: () => {},
        onOpenOutput: () => {},
      }),
    ),
  )
}

describe('ProcessingView 结果区扩展', () => {
  it('manual_review_files 存在时渲染需人工处理清单（文件名+原因）', () => {
    const html = renderProcessingView(
      makeJob({
        manual_review_files: [
          { path: 'C:/out/需人工处理/扫描件.pdf', reason: 'PDF 无文本内容（可能是扫描件）' },
          { path: 'C:/out/需人工处理/不明类型.pdf', reason: '类型未识别' },
        ],
      }),
    )
    expect(html).toContain('需人工处理')
    expect(html).toContain('2 个文件未能自动完成')
    expect(html).toContain('扫描件.pdf')
    expect(html).toContain('类型未识别')
    expect(html).toContain('打开文件夹')
  })

  it('manual_review_files 为空时不渲染清单', () => {
    const html = renderProcessingView(makeJob())
    expect(html).not.toContain('manual-review-section')
    expect(html).not.toContain('个文件未能自动完成')
  })

  it('duplicates>0 时显示已跳过重复文件提示', () => {
    const html = renderProcessingView(
      makeJob({ stats: { total: 3, success: 2, failure: 0, tax_issues: 0, duplicates: 1 } }),
    )
    expect(html).toContain('已跳过 1 个重复文件')
  })

  it('duplicates 为 0/缺省时不显示提示', () => {
    const html = renderProcessingView(makeJob())
    expect(html).not.toContain('重复文件')
  })

  it('statistics 卡片正常渲染（回归）', () => {
    const html = renderProcessingView(makeJob())
    expect(html).toContain('文件总数')
    expect(html).toContain('处理成功')
  })
})
