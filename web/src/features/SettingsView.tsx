import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Download, ExternalLink, KeyRound, LoaderCircle, Mail, RefreshCw, Save, ShieldCheck } from 'lucide-react'
import { api } from '../api/client'
import type { SettingsResponse, UpdateApplyResponse, UpdateResponse } from '../api/types'
import type { SettingsSection } from '../stores/workbench'
import { useWorkbench } from '../stores/workbench'

interface SettingsViewProps {
  version: string | null
  update: UpdateResponse | null
  onCheckUpdate: () => Promise<UpdateResponse | null>
  onApplyUpdate: () => Promise<UpdateApplyResponse>
}

const DEFAULT_RELEASE_URL = 'https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/latest'

const settingsSectionMeta: Record<SettingsSection, { label: string; eyebrow: string; description: string; icon: React.ReactNode }> = {
  business: {
    label: '业务规则',
    eyebrow: 'WORKBENCH / SETTINGS / BUSINESS',
    description: '配置发票处理的业务规则和并发策略。',
    icon: <ShieldCheck size={17} />,
  },
  email: {
    label: '邮箱连接',
    eyebrow: 'WORKBENCH / SETTINGS / EMAIL',
    description: '管理 IMAP 连接、授权码以及发件人和主题白名单。',
    icon: <Mail size={17} />,
  },
  ai: {
    label: 'AI 审核',
    eyebrow: 'WORKBENCH / SETTINGS / AI',
    description: '配置智能审核服务，并在保存前测试接口连通性。',
    icon: <Bot size={17} />,
  },
  updates: {
    label: '软件更新',
    eyebrow: 'WORKBENCH / SETTINGS / UPDATES',
    description: '检查当前版本，并在有可用版本时执行更新。',
    icon: <RefreshCw size={17} />,
  },
}
const settingsSectionOrder: SettingsSection[] = ['business', 'email', 'ai', 'updates']

export function SettingsView({ version, update, onCheckUpdate, onApplyUpdate }: SettingsViewProps) {
  const queryClient = useQueryClient()
  const settingsSection = useWorkbench((state) => state.settingsSection)
  const setSettingsSection = useWorkbench((state) => state.setSettingsSection)
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [authCode, setAuthCode] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [message, setMessage] = useState('')
  const [emailTestMessage, setEmailTestMessage] = useState('')
  const [aiTestMessage, setAiTestMessage] = useState('')
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const [applyingUpdate, setApplyingUpdate] = useState(false)
  const [updateMessage, setUpdateMessage] = useState('')

  useEffect(() => {
    if (settingsQuery.data) setSettings(settingsQuery.data)
  }, [settingsQuery.data])

  const save = useMutation({
    mutationFn: async () => {
      if (!settings) return
      const email = { ...settings.email, auth_code_configured: undefined, ...(authCode ? { auth_code: authCode } : {}) }
      delete email.auth_code_configured
      const ai = { ...settings.ai, api_key_configured: undefined, ...(apiKey ? { api_key: apiKey } : {}) }
      delete ai.api_key_configured
      await api.updateSettings({ business: settings.business, email, ai })
    },
    onSuccess: async () => {
      setAuthCode('')
      setApiKey('')
      setMessage('配置已保存')
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
    onError: (error) => setMessage((error as Error).message),
  })

  const testEmail = useMutation({
    mutationFn: () => api.testEmail({
      imap_host: settings?.email.imap_host,
      imap_port: settings?.email.imap_port,
      username: settings?.email.username,
      ...(authCode ? { auth_code: authCode } : {}),
    }),
    onMutate: () => setEmailTestMessage('正在测试邮箱连接…'),
    onSuccess: (response) => setEmailTestMessage(response.message),
    onError: (error) => setEmailTestMessage((error as Error).message),
  })

  const testAi = useMutation({
    mutationFn: () => api.testAi({
      api_base: settings?.ai.api_base,
      model: settings?.ai.model,
      timeout: settings?.ai.timeout,
      ...(apiKey ? { api_key: apiKey } : {}),
    }),
    onMutate: () => setAiTestMessage('正在测试 AI 接口…'),
    onSuccess: (response) => setAiTestMessage(response.message),
    onError: (error) => setAiTestMessage((error as Error).message),
  })

  const checkUpdate = async () => {
    setCheckingUpdate(true)
    setUpdateMessage('正在检查 GitHub Release…')
    try {
      const result = await onCheckUpdate()
      if (!result || !result.checked) {
        setUpdateMessage('暂时无法连接 GitHub，请稍后再试')
      } else if (!result.available) {
        setUpdateMessage(`当前已是最新版本 v${result.current_version}`)
      } else if (!result.installable) {
        setUpdateMessage(`发现 v${result.latest_version ?? '--'}，但该 Release 没有可安装的 ZIP 文件`)
      } else {
        setUpdateMessage(`发现 v${result.latest_version}，可以自动下载并安装`)
      }
    } catch (error) {
      setUpdateMessage((error as Error).message)
    } finally {
      setCheckingUpdate(false)
    }
  }

  const applyUpdate = async () => {
    setApplyingUpdate(true)
    setUpdateMessage('正在下载并准备安装更新，请稍候…')
    try {
      const result = await onApplyUpdate()
      setUpdateMessage(result.message)
    } catch (error) {
      setUpdateMessage((error as Error).message)
    } finally {
      setApplyingUpdate(false)
    }
  }

  if (settingsQuery.error) return <div className="editor-view feature-view"><div className="feedback error">{(settingsQuery.error as Error).message}</div></div>
  if (settingsQuery.isLoading || !settings) return <div className="editor-view feature-view"><div className="loading-state"><LoaderCircle size={20} className="spin" /> 正在读取配置</div></div>

  const section = settingsSectionMeta[settingsSection]

  return <div className="editor-view feature-view">
    <div className="view-scroll feature-scroll settings-scroll">
      <nav className="settings-subnav" aria-label="设置分类">
        {settingsSectionOrder.map((sectionId) => {
          const item = settingsSectionMeta[sectionId]
          return <button
            key={sectionId}
            className={settingsSection === sectionId ? 'is-active' : ''}
            onClick={() => setSettingsSection(sectionId)}
            aria-current={settingsSection === sectionId ? 'page' : undefined}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        })}
      </nav>
      <header className="view-header feature-header">
        <div>
          <div className="eyebrow">{section.eyebrow}</div>
          <h1>{section.label}</h1>
          <p>{section.description}</p>
        </div>
        {settingsSection !== 'updates' && (
          <button className="primary-button" onClick={() => save.mutate()} disabled={save.isPending}>
            <Save size={15} /> {save.isPending ? '保存中' : '保存配置'}
          </button>
        )}
      </header>
      {message && <div className={`feedback ${message.includes('失败') || message.includes('错误') ? 'error' : 'success'}`}>{message}</div>}
      <section className="settings-panel-shell">
        {settingsSection === 'business' && <SettingsCard icon={section.icon} title={section.label}>
          <label>购买方税号<input value={settings.business.target_tax_id} onChange={(event) => setSettings({ ...settings, business: { ...settings.business, target_tax_id: event.target.value } })} /></label>
          <label>并发线程<input type="number" min="2" max="16" value={settings.business.max_workers} onChange={(event) => setSettings({ ...settings, business: { ...settings.business, max_workers: Number(event.target.value) } })} /></label>
        </SettingsCard>}
        {settingsSection === 'email' && <SettingsCard icon={section.icon} title={section.label}>
          <label>IMAP 服务器<input value={settings.email.imap_host} onChange={(event) => setSettings({ ...settings, email: { ...settings.email, imap_host: event.target.value } })} /></label>
          <label>端口<input type="number" value={settings.email.imap_port} onChange={(event) => setSettings({ ...settings, email: { ...settings.email, imap_port: Number(event.target.value) } })} /></label>
          <label>邮箱账号<input value={settings.email.username} onChange={(event) => setSettings({ ...settings, email: { ...settings.email, username: event.target.value } })} /></label>
          <label>授权码<input type="password" placeholder={settings.email.auth_code_configured ? '已配置，留空保持不变' : '输入 IMAP 授权码'} value={authCode} onChange={(event) => setAuthCode(event.target.value)} /></label>
          <label>发件人白名单<textarea rows={5} value={settings.email.senders.join('\n')} onChange={(event) => setSettings({ ...settings, email: { ...settings.email, senders: event.target.value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean) } })} placeholder="每行一个邮箱地址" /></label>
          <label>主题关键词白名单<textarea rows={4} value={settings.email.keywords.join('\n')} onChange={(event) => setSettings({ ...settings, email: { ...settings.email, keywords: event.target.value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean) } })} placeholder="每行一个主题关键词" /></label>
          <div className="settings-action-row">
            <button className="secondary-button" onClick={() => testEmail.mutate()} disabled={testEmail.isPending}><KeyRound size={14} /> {testEmail.isPending ? '测试中' : '测试连接'}</button>
            {emailTestMessage && <p className={`settings-test-message ${testEmail.isError ? 'error' : 'success'}`}>{emailTestMessage}</p>}
          </div>
        </SettingsCard>}
        {settingsSection === 'ai' && <SettingsCard icon={section.icon} title={section.label}>
          <label className="toggle-label"><input type="checkbox" checked={settings.ai.enabled} onChange={(event) => setSettings({ ...settings, ai: { ...settings.ai, enabled: event.target.checked } })} />启用 AI 审核</label>
          <label>接口地址<input value={settings.ai.api_base} onChange={(event) => setSettings({ ...settings, ai: { ...settings.ai, api_base: event.target.value } })} /></label>
          <label>模型<input value={settings.ai.model} onChange={(event) => setSettings({ ...settings, ai: { ...settings.ai, model: event.target.value } })} /></label>
          <label>API Key<input type="password" placeholder={settings.ai.api_key_configured ? '已配置，留空保持不变' : '输入 API Key'} value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
          <div className="settings-action-row">
            <button className="secondary-button" onClick={() => testAi.mutate()} disabled={testAi.isPending}><KeyRound size={14} /> {testAi.isPending ? '测试中' : '测试连接'}</button>
            {aiTestMessage && <p className={`settings-test-message ${testAi.isError ? 'error' : 'success'}`}>{aiTestMessage}</p>}
          </div>
        </SettingsCard>}
        {settingsSection === 'updates' && <SettingsCard icon={section.icon} title={section.label}>
          <div className="update-settings">
            <div className="update-version">
              <span className="field-label">当前版本</span>
              <strong>v{update?.current_version ?? version ?? '--'}</strong>
              {update?.available && <span className="update-available">发现 v{update.latest_version ?? '--'}</span>}
            </div>
            <div className="update-actions">
              <button className="secondary-button" onClick={() => void checkUpdate()} disabled={checkingUpdate || applyingUpdate}>
                <RefreshCw size={14} className={checkingUpdate ? 'spin' : ''} /> {checkingUpdate ? '检查中' : '检查更新'}
              </button>
              {update?.available && update.installable && <button className="primary-button" onClick={() => void applyUpdate()} disabled={checkingUpdate || applyingUpdate}>
                <Download size={14} className={applyingUpdate ? 'spin' : ''} /> {applyingUpdate ? '下载并安装中' : '立即更新'}
              </button>}
            </div>
            <a className="update-release-link" href={update?.release_url ?? DEFAULT_RELEASE_URL} target="_blank" rel="noopener noreferrer">
              <span>打开 Release 页面</span>
              <ExternalLink size={13} />
            </a>
            <p className="update-message">{updateMessage || '检测到新版本后，可由程序自动下载、替换并重启。'}</p>
            {update?.available && !update.installable && <p className="update-message warning">请在该 Release 上传 SYNTEC ZIP 打包文件。</p>}
          </div>
        </SettingsCard>}
      </section>
    </div>
  </div>
}

function SettingsCard({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return <section className="settings-card"><h2>{icon}{title}</h2><div className="settings-fields">{children}</div></section>
}