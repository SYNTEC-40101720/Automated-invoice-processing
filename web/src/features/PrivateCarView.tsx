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

const COLUMNS: Array<{ key: keyof PrivateCarRow; label: string; width: number; editable: boolean }> = [
  { key: 'date', label: '日期', width: 110, editable: true },
  { key: 'user_name', label: '使用人', width: 90, editable: true },
  { key: 'destination', label: '出差目的地', width: 150, editable: true },
  { key: 'start_time', label: '开始时间', width: 90, editable: true },
  { key: 'end_time', label: '结束时间', width: 90, editable: true },
  { key: 'start_mileage', label: '出发里程数（A）', width: 120, editable: true },
  { key: 'end_mileage', label: '结束里程数（B）', width: 120, editable: true },
  { key: 'distance_text', label: '行驶里程数（B-A）', width: 130, editable: false },
  { key: 'subsidy_text', label: '补贴金额', width: 100, editable: false },
  { key: 'toll_fee', label: '过路（桥）费', width: 100, editable: true },
  { key: 'parking_fee', label: '停车费', width: 90, editable: true },
]

function parseAmount(value: string): number {
  const parsed = Number.parseFloat(value)
  return Number.isFinite(parsed) ? parsed : 0
}

export function PrivateCarView() {
  const queryClient = useQueryClient()
  const metaQuery = useQuery({ queryKey: ['private-car-meta'], queryFn: api.privateCarMeta })
  const rowsQuery = useQuery({ queryKey: ['private-car-rows'], queryFn: api.privateCarRows })
  const [meta, setMeta] = useState({ license_plate: '', user_name: '' })
  const [rows, setRows] = useState<PrivateCarRow[]>([])
  const [message, setMessage] = useState('')
  const [exporting, setExporting] = useState(false)

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
      setMessage('明细已保存（里程差与补贴已按 1.5 元/公里计算）')
      setRows(response.rows.map((row) => ({ ...EMPTY_ROW, ...row })))
      await queryClient.invalidateQueries({ queryKey: ['private-car-rows'] })
    },
    onError: (error) => setMessage((error as Error).message),
  })

  const exportSheet = useMutation({
    mutationFn: async () => {
      const directory = await pickExportDirectory()
      if (!directory) throw new Error('未选择导出目录')
      setExporting(true)
      try {
        await api.replacePrivateCarRows(rows)
        return await api.exportPrivateCar({ output_directory: directory })
      } finally {
        setExporting(false)
      }
    },
    onError: (error) => setMessage((error as Error).message),
  })

  const updateRow = (index: number, key: keyof PrivateCarRow, value: string) => {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, [key]: value } : row)))
  }

  return (
    <div className="editor-view feature-view">
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

        <section className="feature-section" aria-label="私车信息">
          <div className="private-car-meta-row">
            <label className="field-label" htmlFor="private-car-plate">车牌号</label>
            <input
              id="private-car-plate"
              className="text-input"
              maxLength={20}
              value={meta.license_plate}
              onChange={(event) => setMeta((current) => ({ ...current, license_plate: event.target.value }))}
              placeholder="苏U930FQ"
            />
            <label className="field-label" htmlFor="private-car-user">使用人</label>
            <input
              id="private-car-user"
              className="text-input"
              maxLength={40}
              value={meta.user_name}
              onChange={(event) => setMeta((current) => ({ ...current, user_name: event.target.value }))}
              placeholder="张三"
            />
            <button type="button" className="ghost-button" onClick={() => saveMeta.mutate()} disabled={saveMeta.isPending}>
              {saveMeta.isPending ? <LoaderCircle size={14} className="spin" /> : <Save size={14} />}
              <span>保存信息</span>
            </button>
          </div>
        </section>

        <section className="feature-section" aria-label="行程明细">
          <div className="private-car-table-wrap">
            <table className="private-car-table">
              <thead>
                <tr>
                  <th className="row-index">#</th>
                  {COLUMNS.map((column) => (
                    <th key={column.key} style={{ minWidth: column.width }}>{column.label}</th>
                  ))}
                  <th className="row-actions">操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={index}>
                    <td className="row-index">{index + 1}</td>
                    {COLUMNS.map((column) => (
                      <td key={column.key}>
                        {column.editable ? (
                          <input
                            className="cell-input"
                            value={row[column.key]}
                            onChange={(event) => updateRow(index, column.key, event.target.value)}
                          />
                        ) : (
                          <span className="cell-static">{row[column.key]}</span>
                        )}
                      </td>
                    ))}
                    <td className="row-actions">
                      <button
                        type="button"
                        className="icon-button"
                        title="删除该行"
                        onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr><td className="empty-row" colSpan={COLUMNS.length + 2}>暂无行程，点击下方「添加一行」开始登记。</td></tr>
                )}
              </tbody>
              {rows.length > 0 && (
                <tfoot>
                  <tr>
                    <td className="row-index" />
                    {COLUMNS.map((column) => {
                      const total = column.key === 'distance_text'
                        ? totals.distance.toFixed(2)
                        : column.key === 'subsidy_text'
                          ? totals.subsidy.toFixed(2)
                          : column.key === 'toll_fee'
                            ? totals.toll.toFixed(2)
                            : column.key === 'parking_fee'
                              ? totals.parking.toFixed(2)
                              : ''
                      return <td key={column.key}>{total ? <strong>{total}</strong> : null}</td>
                    })}
                    <td />
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          <div className="private-car-actions">
            <button type="button" className="ghost-button" onClick={() => setRows((current) => [...current, { ...EMPTY_ROW }])}>
              <Plus size={14} />
              <span>添加一行</span>
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={() => saveRows.mutate()}
              disabled={saveRows.isPending}
            >
              {saveRows.isPending ? <LoaderCircle size={14} className="spin" /> : <Save size={14} />}
              <span>保存明细</span>
            </button>
            <button
              type="button"
              className="primary-button"
              onClick={() => exportSheet.mutate()}
              disabled={exporting || rows.length === 0}
            >
              {exporting ? <LoaderCircle size={14} className="spin" /> : <FolderOpen size={14} />}
              <span>导出费用统计表</span>
            </button>
          </div>
          {(message || exportSheet.isSuccess) && (
            <p className="private-car-message" role="status">
              {exportSheet.isSuccess && exportSheet.data ? `已导出：${exportSheet.data.path}` : message}
            </p>
          )}
        </section>
      </div>
    </div>
  )
}
