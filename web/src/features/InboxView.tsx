import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ClipboardPaste, FolderOpen, LoaderCircle, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { EmailSettings, SettingsResponse } from '../api/types'

interface InboxViewProps {
  emailSettings: EmailSettings | null
}

export function InboxView({ emailSettings }: InboxViewProps) {
  const queryClient = useQueryClient()
  const [message, setMessage] = useState('')
  const pull = useMutation({ mutationFn: api.pullEmail })
  const updateEmail = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.updateEmail(values),
    onSuccess: (nextEmail) => {
      queryClient.setQueryData<SettingsResponse>(['settings'], (current) => (
        current ? { ...current, email: nextEmail } : current
      ))
      setMessage('收件设置已保存')
    },
    onError: (error) => setMessage((error as Error).message),
  })

  const chooseInboxDirectory = async () => {
    const value = window.pywebview?.api
      ? await window.pywebview.api.select_directory()
      : window.prompt('请输入统一收件目录路径', emailSettings?.inbox_dir ?? '') ?? ''
    if (!value?.trim()) return
    updateEmail.mutate({ inbox_dir: value.trim() })
  }

  const openInboxDirectory = async () => {
    const targetDir = emailSettings?.inbox_dir?.trim()
    if (!targetDir) {
      setMessage('请先指定收件目录后再打开')
      return
    }
    try {
      const opened = window.pywebview?.api
        ? await window.pywebview.api.open_directory(targetDir)
        : (await api.openDirectory(targetDir)).opened
      if (!opened) {
        setMessage('无法打开收件目录，请检查路径是否存在且可访问')
      }
    } catch (error) {
      setMessage((error as Error).message)
    }
  }

  const result = pull.data?.pull

  return (
    <div className="editor-view feature-view">
      <div className="view-scroll feature-scroll">
        <header className="view-header feature-header inbox-header">
          <div><div className="eyebrow">INBOX / MANUAL INTAKE</div><h1>发票收取</h1><p>设定统一收件目录，打开目录整理文件，或手动拉取邮箱附件。</p></div>
          <div className="state-badge success">
            <ClipboardPaste size={14} />
            <span>手动收取</span>
          </div>
        </header>
        {message && <div className={`feedback ${message.includes('失败') || message.includes('错误') ? 'error' : 'success'}`}>{message}</div>}
        {pull.error && <div className="feedback error">{(pull.error as Error).message}</div>}
        <section className="feature-section inbox-config">
          <div className="inbox-directory-block">
            <div className="source-icon"><FolderOpen size={19} /></div>
            <div className="source-copy">
              <span className="field-label">统一收件目录</span>
              <strong title={emailSettings?.inbox_dir}>{emailSettings?.inbox_dir ?? '正在读取收件目录'}</strong>
              <span className="inbox-control-hint">邮箱附件按拉取批次分目录保存，其他来源文件可手动放入</span>
            </div>
            <div className="inbox-directory-actions">
              <button className="secondary-button" onClick={() => void chooseInboxDirectory()} disabled={updateEmail.isPending}>
                <FolderOpen size={15} /> 设定目录
              </button>
              <button className="secondary-button" onClick={() => void openInboxDirectory()} disabled={updateEmail.isPending}>
                <FolderOpen size={15} /> 打开目录
              </button>
            </div>
          </div>
          <div className="inbox-action-row">
            <div className="inbox-manual-copy">
              <span className="field-label">邮箱来源</span>
              <strong>手动拉取邮箱附件</strong>
              <span className="inbox-control-hint">仅在点击按钮时连接邮箱，不会后台自动轮询</span>
            </div>
            <button className="primary-button inbox-pull-button" onClick={() => pull.mutate()} disabled={pull.isPending}>
              {pull.isPending ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />} {pull.isPending ? '正在拉取' : '手动拉取'}
            </button>
          </div>
        </section>
        <section className="feature-section inbox-result">
          <div className="feature-stat"><strong>{result?.downloaded ?? 0}</strong><span>新附件</span></div>
          <div className="feature-stat"><strong>{result?.total_scanned ?? 0}</strong><span>扫描邮件</span></div>
          <div className="feature-stat"><strong>{result?.errors.length ?? 0}</strong><span>异常</span></div>
          <div className="feature-message">
            {result
              ? result.new_files.length > 0
                ? <>已拉取新附件，保存在本次批次目录：<strong title={result.session_dir ?? undefined}>{result.session_dir ?? '（未知）'}</strong>，请到发票处理页面选择该目录开始处理</>
                : '没有发现新的 PDF 附件'
              : '尚未执行拉取'}
          </div>
        </section>
        {result?.errors.length ? <section className="feature-section error-list">{result.errors.map((error) => <p key={error}>{error}</p>)}</section> : null}
      </div>
    </div>
  )
}