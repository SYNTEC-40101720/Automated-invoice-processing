import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Car, FolderOpen, LoaderCircle, Plus, Save, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { PrivateCarRow } from '../api/types'

async function pickExportDirectory(): Promise<string | null> {
  if (window.pywebview?.api) {
    const picked = await window.pywebview.api.select_directory()
    return typeof picked === 'string' && picked.trim() !== '' ? picked : null
  }
  return window.prompt('请输入导出目录路径')
}

const EMPTY_ROW: PrivateCarRow = {
  date: '',
  user_name: '',
  destination: '',
  start_time: '',
  end_time: '',
  start_mileage: '',
  end_mileage: '',
  distance_text: '',
  subsidy_text: '',
  toll_fee: '',
  parking_fee: '',
}

interface ColumnSpec {
  key: keyof PrivateCarRow
  label: string
  title?: string
  width?: number
  kind: 'date' | 'time' | 'text' | 'number' | 'computed'
}

const COLUMNS: ColumnSpec[] = [
  { key: 'date', label: '日期', width: 136, kind: 'date' },
  { key: 'user_name', label: '使用人', width: 92, kind: 'text' },
  { key: 'destination', label: '出差目的地', kind: 'text' },
  { key: 'start_time', label: '开始', title: '开始时间', width: 100, kind: 'time' },
  { key: 'end_time', label: '结束', title: '结束时间', width: 100, kind: 'time' },
  { key: 'start_mileage', label: '里程 A', title: '出发里程数（A）', width: 96, kind: 'number' },
  { key: 'end_mileage', label: '里程 B', title: '结束里程数（B）', width: 96, kind: 'number' },
  { key: 'distance_text', label: '行驶', title: '行驶里程数（B−A），保存后自动计算', width: 84, kind: 'computed' },
  { key: 'subsidy_text', label: '补贴', title: '补贴金额，按 1.5 元/公里自动计算', width: 88, kind: 'computed' },
  { key: 'toll_fee', label: '过路（桥）费', width: 96, kind: 'number' },
  { key: 'parking_fee', label: '停车费', width: 88, kind: 'number' },
]

function parseAmount(value: string): number {
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function formatAmount(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

function feedbackTone(text: string): 'success' | 'error' {
  return /(失败|错误|无效|不能|无法)/.test(text) ? 'error' : 'success'
}

export function PrivateCarView() {
  const queryClient = useQueryClient()
  const metaQuery = useQuery({ queryKey: ['private-car-meta'], queryFn: api.privateCarMeta })
  const rowsQuery = useQuery({ queryKey: ['private-car-rows'], queryFn: api.privateCarRows })
  const [meta, setMeta] = useState({ license_plate: '', user_name: '' })
  const [rows, setRows] = useState<PrivateCarRow[]>([])
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (metaQuery.data) setMeta({ license_plate: metaQuery.data.license_plate, user_name: metaQuery.data.user_name })
  }, [metaQuery.data])

  useEffect(() => {
    if (rowsQuery.data) setRows(rowsQuery.data.rows.map((row) => ({ ...EMPTY_ROW, ...row })))
  }, [rowsQuery.data])

  const totals = useMemo(() => ({
    distance: rows.reduce((sum, row) => sum + parseAmount(row.distance_text), 0),
    subsidy: rows.reduce((sum, row) => sum + parseAmount(row.subsidy_text), 0),
    toll: rows.reduce((sum, row) => sum + parseAmount(row.toll_fee), 0),
    parking: rows.reduce((sum, row) => sum + parseAmount(row.parking_fee), 0),
  }), [rows])

  const saveMeta = useMutation({
    mutationFn: () => api.updatePrivateCarMeta({ license_plate: meta.license_plate, user_name: meta.user_name }),
    onSuccess: async () => {
      setMessage('车牌与使用人已保存')
      await queryClient.invalidateQueries({ queryKey: ['private-car-meta'] })
    },
    onError: (error) => setMessage((error as Error).message),
  })

  const saveRows = useMutation({
    mutationFn: () => api.replacePrivateCarRows(rows),
    onSuccess: async (response) => {
      setMessage('明细已保存，里程差与补贴已按 1.5 元/公里重新计算')
      setRows(response.rows.map((row) => ({ ...EMPTY_ROW, ...row })))
      await queryClient.invalidateQueries({ queryKey: ['private-car-rows'] })
    },
    onError: (error) => setMessage((error as Error).message),
  })

  const exportSheet = useMutation({
    mutationFn: async () => {
      const directory = await pickExportDirectory()
      if (!directory) throw new Error('未选择导出目录')
      await api.replacePrivateCarRows(rows)
      return await api.exportPrivateCar({ output_directory: directory })
    },
    onSuccess: async (response) => {
      setMessage(`已导出：${response.path}`)
      await queryClient.invalidateQueries({ queryKey: ['private-car-rows'] })
    },
    onError: (error) => setMessage((error as Error).message),
  })

  const updateRow = (index: number, key: keyof PrivateCarRow, value: string) => {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, [key]: value } : row)))
  }

  const totalFor = (key: keyof PrivateCarRow): string | null => {
    if (key === 'distance_text') return `${formatAmount(totals.distance)} km`
    if (key === 'subsidy_text') return `¥${formatAmount(totals.subsidy)}`
    if (key === 'toll_fee') return `¥${formatAmount(totals.toll)}`
    if (key === 'parking_fee') return `¥${formatAmount(totals.parking)}`
    return null
  }

  return (
    <div className="editor-view feature-view pc-wide">
      <div className="view-scroll feature-scroll">
        <header className="view-header feature-header">
          <div>
            <div className="eyebrow">PRIVATE CAR / LEDGER</div>
            <h1>私车公用</h1>
            <p>登记私车公用行程，保存后自动按 1.5 元/公里计算补贴，并可导出财务统计表。</p>
          </div>
          <div className="state-badge">
            <Car size={14} />
            <span>{rows.length} 条行程</span>
          </div>
        </header>

        {message && <div className={`feedback ${feedbackTone(message)}`} role="status">{message}</div>}

        <section className="feature-section" aria-label="车辆信息">
          <div className="pc-meta-grid">
            <label>
              <span>车牌号</span>
              <input
                maxLength={20}
                value={meta.license_plate}
                onChange={(event) => setMeta((current) => ({ ...current, license_plate: event.target.value }))}
                placeholder="苏U930FQ"
              />
            </label>
            <label>
              <span>使用人</span>
              <input
                maxLength={40}
                value={meta.user_name}
                onChange={(event) => setMeta((current) => ({ ...current, user_name: event.target.value }))}
                placeholder="张三"
              />
            </label>
            <button
              type="button"
              className="secondary-button"
              onClick={() => saveMeta.mutate()}
              disabled={saveMeta.isPending}
            >
              {saveMeta.isPending ? <LoaderCircle size={14} className="spin" /> : <Save size={14} />}
              <span>保存信息</span>
            </button>
          </div>
        </section>

        <section className="feature-section pc-ledger" aria-label="行程明细">
          <div className="pc-card-header">
            <div className="pc-card-title">
              <strong>行程明细</strong>
              <span className="feature-section-meta">{rows.length} 条</span>
            </div>
            <div className="pc-summary">
              <span>里程 <strong>{formatAmount(totals.distance)}</strong> km</span>
              <span>补贴 <strong>¥{formatAmount(totals.subsidy)}</strong></span>
              <span>过路 <strong>¥{formatAmount(totals.toll)}</strong></span>
              <span>停车 <strong>¥{formatAmount(totals.parking)}</strong></span>
            </div>
          </div>

          {rows.length === 0 ? (
            <div className="pc-empty">
              <Car size={18} />
              <span>暂无行程，点击下方「添加一行」开始登记</span>
            </div>
          ) : (
            <div className="pc-table-wrap">
              <table className="pc-table">
                <colgroup>
                  <col style={{ width: 40 }} />
                  {COLUMNS.map((column) => (
                    <col key={column.key} style={column.width ? { width: column.width } : undefined} />
                  ))}
                  <col style={{ width: 44 }} />
                </colgroup>
                <thead>
                  <tr>
                    <th className="pc-index">#</th>
                    {COLUMNS.map((column) => (
                      <th key={column.key} title={column.title}>{column.label}</th>
                    ))}
                    <th className="pc-index" aria-label="操作" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <tr key={index}>
                      <td className="pc-index">{index + 1}</td>
                      {COLUMNS.map((column) => {
                        const numeric = column.kind === 'number' || column.kind === 'computed'
                        const className = `${numeric ? 'pc-num' : ''} ${column.kind === 'computed' ? 'pc-computed' : ''}`.trim() || undefined
                        return (
                          <td key={column.key} className={className}>
                            {column.kind === 'computed' ? (
                              <span className="pc-static">{row[column.key]}</span>
                            ) : (
                              <input
                                className="pc-input"
                                type={column.kind === 'date' ? 'date' : column.kind === 'time' ? 'time' : 'text'}
                                inputMode={column.kind === 'number' ? 'decimal' : undefined}
                                value={row[column.key]}
                                onChange={(event) => updateRow(index, column.key, event.target.value)}
                              />
                            )}
                          </td>
                        )
                      })}
                      <td className="pc-index">
                        <button
                          type="button"
                          className="icon-button subtle"
                          title={`删除第 ${index + 1} 行`}
                          onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td className="pc-index" />
                    {COLUMNS.map((column) => {
                      const total = totalFor(column.key)
                      return <td key={column.key}>{total ? <strong>{total}</strong> : null}</td>
                    })}
                    <td className="pc-index" />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}

          <div className="pc-card-footer">
            <div className="pc-footer-left">
              <button
                type="button"
                className="secondary-button"
                onClick={() => setRows((current) => [...current, { ...EMPTY_ROW }])}
              >
                <Plus size={14} />
                <span>添加一行</span>
              </button>
              <span className="pc-hint">补贴 = 行驶里程 × 1.5 元/公里，保存后自动计算</span>
            </div>
            <div className="pc-footer-actions">
              <button
                type="button"
                className="secondary-button"
                onClick={() => saveRows.mutate()}
                disabled={saveRows.isPending || rows.length === 0}
              >
                {saveRows.isPending ? <LoaderCircle size={14} className="spin" /> : <Save size={14} />}
                <span>保存明细</span>
              </button>
              <button
                type="button"
                className="primary-button"
                onClick={() => exportSheet.mutate()}
                disabled={exportSheet.isPending || rows.length === 0}
              >
                {exportSheet.isPending ? <LoaderCircle size={14} className="spin" /> : <FolderOpen size={14} />}
                <span>导出费用统计表</span>
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
