import { Inbox, LoaderCircle, RefreshCw } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useWorkbench } from '../stores/workbench'

export function InboxView() {
  const setJob = useWorkbench((state) => state.setJob)
  const pull = useMutation({
    mutationFn: api.pullEmail,
    onSuccess: (response) => {
      if (response.job) setJob(response.job)
    },
  })
  const result = pull.data?.pull

  return (
    <div className="editor-view feature-view">
      <div className="editor-tabs"><div className="editor-tab active"><Inbox size={14} /> 发票收件箱</div></div>
      <div className="view-scroll feature-scroll">
        <header className="view-header feature-header">
          <div><div className="eyebrow">INBOX / EMAIL PULL</div><h1>发票收件箱</h1><p>从已配置的 IMAP 收件箱拉取附件，并自动进入处理队列。</p></div>
          <button className="primary-button" onClick={() => pull.mutate()} disabled={pull.isPending}>
            {pull.isPending ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />} {pull.isPending ? '正在拉取' : '立即拉取'}
          </button>
        </header>
        {pull.error && <div className="feedback error">{(pull.error as Error).message}</div>}
        {result && <section className="feature-section inbox-result">
          <div className="feature-stat"><strong>{result.downloaded}</strong><span>新附件</span></div>
          <div className="feature-stat"><strong>{result.total_scanned}</strong><span>扫描邮件</span></div>
          <div className="feature-stat"><strong>{result.errors.length}</strong><span>异常</span></div>
          <div className="feature-message">{result.job_error ? result.job_error.message : pull.data?.job ? '已创建处理任务' : '没有发现新的 PDF 附件'}</div>
        </section>}
        {result?.errors.length ? <section className="feature-section error-list">{result.errors.map((error) => <p key={error}>{error}</p>)}</section> : null}
      </div>
    </div>
  )
}