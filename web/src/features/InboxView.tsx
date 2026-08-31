import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, LoaderCircle, Power, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { EmailSettings, SettingsResponse } from '../api/types'
import { useWorkbench } from '../stores/workbench'

interface InboxViewProps {
  emailSettings: EmailSettings | null
}

export function InboxView({ emailSettings }: InboxViewProps) {
  const queryClient = useQueryClient()
  const setJob = useWorkbench((state) => state.setJob)
  const [pollMinutes, setPollMinutes] = useState(emailSettings?.poll_minutes || 5)
  const [message, setMessage] = useState('')
  const pull = useMutation({
    mutationFn: api.pullEmail,
    onSuccess: (response) => {
      if (response.job) setJob(response.job)
    },
  })
  useEffect(() => {
    if (emailSettings) setPollMinutes(emailSettings.poll_minutes || 5)
  }, [emailSettings?.poll_minutes])
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
      : window.prompt('请输入邮箱收件目录路径', emailSettings?.inbox_dir ?? '') ?? ''
    if (!value?.trim()) return
    updateEmail.mutate({ inbox_dir: value.trim() })
  }

  const toggleAutomaticReceiving = (enabled: boolean) => {
    const interval = enabled
      ? Math.max(1, emailSettings?.poll_minutes ?? pollMinutes, 5)
      : pollMinutes
    if (enabled) setPollMinutes(interval)
    updateEmail.mutate({ enabled, ...(enabled ? { poll_minutes: interval } : {}) })
  }

  const toggleAutomaticProcessing = (autoProcess: boolean) => {
    updateEmail.mutate({ auto_process: autoProcess })
  }

  const savePollMinutes = () => {
    const interval = Math.min(1440, Math.max(1, Number(pollMinutes) || 5))
    setPollMinutes(interval)
    updateEmail.mutate({ poll_minutes: interval })
  }

  const openInboxDirectory = async () => {
    const targetDir = emailSettings?.inbox_dir?.trim()
    if (!targetDir) {
      setMessage('请先指定收件目录后再打开')
      return
    }
    if (window.pywebview?.api) {
      try {
        const opened = await window.pywebview.api.open_directory(targetDir)
        if (!opened) {
          setMessage('无法打开收件目录，请检查路径是否存在且可访问')
        }
      } catch (error) {
        setMessage((error as Error).message)
      }
      return
    }
    window.alert(`收件目录：${targetDir}`)
  }

  const result = pull.data?.pull

  return (
    <div className="editor-view feature-view">
      <div className="view-scroll feature-scroll">
        <header className="view-header feature-header">
          <div><div className="eyebrow">INBOX / EMAIL PULL</div><h1>发票收件箱</h1><p>从邮箱收取附件；是否自动创建处理任务由下方设置决定。</p></div>
        </header>
        {message && <div className={`feedback ${message.includes('失败') || message.includes('错误') ? 'error' : 'success'}`}>{message}</div>}
        {pull.error && <div className="feedback error">{(pull.error as Error).message}</div>}
        <section className="feature-section inbox-config">
          <div className="inbox-directory-block">
            <div className="source-icon"><FolderOpen size={19} /></div>
            <div className="source-copy">
              <span className="field-label">收件目录</span>
              <strong title={emailSettings?.inbox_dir}>{emailSettings?.inbox_dir ?? '正在读取收件目录'}</strong>
            </div>
            <button className="secondary-button" onClick={() => void chooseInboxDirectory()} disabled={updateEmail.isPending}>
              <FolderOpen size={15} /> 指定目录
            </button>
          </div>
          <div className="inbox-action-row">
            <div className="inbox-automation-block">
              <div className="inbox-automation-copy">
                <span className="field-label">自动收件</span>
                <strong>{emailSettings?.enabled && emailSettings.poll_minutes > 0 ? '自动收件已开启' : '自动收件已关闭'}</strong>
                <span className="inbox-control-hint">后台按设定间隔检查邮箱并自动创建处理任务</span>
              </div>
              <label className="switch-control">
                <input
                  type="checkbox"
                  checked={Boolean(emailSettings?.enabled && emailSettings.poll_minutes > 0)}
                  onChange={(event) => toggleAutomaticReceiving(event.target.checked)}
                  disabled={!emailSettings || updateEmail.isPending}
                />
                <span className="switch-track" aria-hidden="true"><span /></span>
              </label>
              <label className="poll-interval">
                <span>间隔（分钟）</span>
                <input
                  type="number"
                  min="1"
                  max="1440"
                  value={pollMinutes}
                  onChange={(event) => setPollMinutes(Number(event.target.value))}
                  disabled={!emailSettings || updateEmail.isPending}
                />
              </label>
              <button className="secondary-button" onClick={savePollMinutes} disabled={!emailSettings || updateEmail.isPending}>
                <Power size={14} /> 保存间隔
              </button>
            </div>
            <button className="primary-button inbox-pull-button" onClick={() => pull.mutate()} disabled={pull.isPending}>
              {pull.isPending ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />} {pull.isPending ? '正在拉取' : '立即拉取'}
            </button>
          </div>
          <div className="inbox-processing-block">
            <div className="inbox-processing-copy">
              <span className="field-label">拉取后自动处理</span>
              <strong>{emailSettings?.auto_process ? '自动处理已开启' : '仅拉取，不处理'}</strong>
              <span className="inbox-control-hint">开启后，拉取到新附件会自动创建发票处理任务</span>
            </div>
            <label className="switch-control">
              <input
                type="checkbox"
                checked={Boolean(emailSettings?.auto_process)}
                onChange={(event) => toggleAutomaticProcessing(event.target.checked)}
                disabled={!emailSettings || updateEmail.isPending}
              />
              <span className="switch-track" aria-hidden="true"><span /></span>
            </label>
          </div>
        </section>
        {result && <section className="feature-section inbox-result">
          <div className="feature-stat"><strong>{result.downloaded}</strong><span>新附件</span></div>
          <div className="feature-stat"><strong>{result.total_scanned}</strong><span>扫描邮件</span></div>
          <div className="feature-stat"><strong>{result.errors.length}</strong><span>异常</span></div>
          <div className="feature-message">{result.job_error ? result.job_error.message : pull.data?.job ? '已创建处理任务' : result.new_files.length > 0 ? '已拉取新附件，未启动处理任务' : '没有发现新的 PDF 附件'}</div>
          <button className="secondary-button" onClick={() => void openInboxDirectory()}>
            <FolderOpen size={15} /> 打开收件箱目录
          </button>
        </section>}
        {result?.errors.length ? <section className="feature-section error-list">{result.errors.map((error) => <p key={error}>{error}</p>)}</section> : null}
      </div>
    </div>
  )
}