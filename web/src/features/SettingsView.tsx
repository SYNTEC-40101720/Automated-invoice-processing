import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, LoaderCircle, Mail, Save, Settings2, ShieldCheck } from 'lucide-react'
import { api } from '../api/client'
import type { SettingsResponse } from '../api/types'

export function SettingsView() {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: api.settings })
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [authCode, setAuthCode] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [message, setMessage] = useState('')

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
    onSuccess: (response) => setMessage(response.message),
    onError: (error) => setMessage((error as Error).message),
  })

  const testAi = useMutation({
    mutationFn: () => api.testAi({
      api_base: settings?.ai.api_base,
      model: settings?.ai.model,
      timeout: settings?.ai.timeout,
      ...(apiKey ? { api_key: apiKey } : {}),
    }),
    onSuccess: (response) => setMessage(response.message),
    onError: (error) => setMessage((error as Error).message),
  })

  if (settingsQuery.error) return <div className="editor-view feature-view"><div className="feedback error">{(settingsQuery.error as Error).message}</div></div>
  if (settingsQuery.isLoading || !settings) return <div className="editor-view feature-view"><div className="loading-state"><LoaderCircle size={20} className="spin" /> 正在读取配置</div></div>

  return <div className="editor-view feature-view">
    <div className="editor-tabs"><div className="editor-tab active"><Settings2 size={14} /> 工作台设置</div></div>
    <div className="view-scroll feature-scroll settings-scroll">
      <header className="view-header feature-header"><div><div className="eyebrow">WORKBENCH / SETTINGS</div><h1>工作台设置</h1><p>本地服务保存业务规则、邮箱连接和智能审核配置。</p></div><button className="primary-button" onClick={() => save.mutate()} disabled={save.isPending}><Save size={15} /> {save.isPending ? '保存中' : '保存配置'}</button></header>
      {message && <div className={`feedback ${message.includes('失败') || message.includes('错误') ? 'error' : 'success'}`}>{message}</div>}
      <section className="settings-grid">
        <SettingsCard icon={<ShieldCheck size={17} />} title="业务规则">
          <label>购买方税号<input value={settings.business.target_tax_id} onChange={(event) => setSettings({ ...settings, business: { ...settings.business, target_tax_id: event.target.value } })} /></label>
          <label>并发线程<input type="number" min="2" max="16" value={settings.business.max_workers} onChange={(event) => setSettings({ ...settings, business: { ...settings.business, max_workers: Number(event.target.value) } })} /></label>
        </SettingsCard>
        <SettingsCard icon={<Mail size={17} />} title="邮箱收件箱">
          <label className="toggle-label"><input type="checkbox" checked={settings.email.enabled} onChange={(event) => setSettings({ ...settings, email: { ...settings.email, enabled: event.target.checked } })} />启用邮箱拉取</label>
          <label>IMAP 服务器<input value={settings.email.imap_host} onChange={(event) => setSettings({ ...settings, email: { ...settings.email, imap_host: event.target.value } })} /></label>
          <label>端口<input type="number" value={settings.email.imap_port} onChange={(event) => setSettings({ ...settings, email: { ...settings.email, imap_port: Number(event.target.value) } })} /></label>
          <label>邮箱账号<input value={settings.email.username} onChange={(event) => setSettings({ ...settings, email: { ...settings.email, username: event.target.value } })} /></label>
          <label>授权码<input type="password" placeholder={settings.email.auth_code_configured ? '已配置，留空保持不变' : '输入 IMAP 授权码'} value={authCode} onChange={(event) => setAuthCode(event.target.value)} /></label>
          <button className="secondary-button" onClick={() => testEmail.mutate()} disabled={testEmail.isPending}><KeyRound size={14} /> {testEmail.isPending ? '测试中' : '测试连接'}</button>
        </SettingsCard>
        <SettingsCard icon={<Settings2 size={17} />} title="AI 审核">
          <label className="toggle-label"><input type="checkbox" checked={settings.ai.enabled} onChange={(event) => setSettings({ ...settings, ai: { ...settings.ai, enabled: event.target.checked } })} />启用 AI 审核</label>
          <label>接口地址<input value={settings.ai.api_base} onChange={(event) => setSettings({ ...settings, ai: { ...settings.ai, api_base: event.target.value } })} /></label>
          <label>模型<input value={settings.ai.model} onChange={(event) => setSettings({ ...settings, ai: { ...settings.ai, model: event.target.value } })} /></label>
          <label>API Key<input type="password" placeholder={settings.ai.api_key_configured ? '已配置，留空保持不变' : '输入 API Key'} value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
          <button className="secondary-button" onClick={() => testAi.mutate()} disabled={testAi.isPending}><KeyRound size={14} /> {testAi.isPending ? '测试中' : '测试连接'}</button>
        </SettingsCard>
      </section>
    </div>
  </div>
}

function SettingsCard({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return <section className="settings-card"><h2>{icon}{title}</h2><div className="settings-fields">{children}</div></section>
}