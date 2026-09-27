import { Download, ExternalLink, X } from 'lucide-react'
import { useState } from 'react'
import type { UpdateResponse } from '../api/types'

interface UpdateBannerProps {
  update: UpdateResponse
}

export function UpdateBanner({ update }: UpdateBannerProps) {
  const [dismissedVersion, setDismissedVersion] = useState<string | null>(null)

  if (
    !update.available
    || !update.latest_version
    || dismissedVersion === update.latest_version
  ) {
    return null
  }

  return (
    <aside className="update-banner" role="status" aria-live="polite">
      <Download className="update-banner-icon" size={18} />
      <div className="update-banner-copy">
        <strong>发现新版本 v{update.latest_version}</strong>
        <span>当前版本 v{update.current_version}，请前往 Release 页面下载安装包。</span>
      </div>
      <a
        className="primary-button update-action"
        href={update.release_url ?? 'https://github.com/SYNTEC-40101720/Automated-invoice-processing/releases/latest'}
        target="_blank"
        rel="noopener noreferrer"
      >
        <ExternalLink size={14} /> 前往下载
      </a>
      <button
        className="icon-button update-dismiss"
        title="关闭更新提示"
        aria-label="关闭更新提示"
        onClick={() => setDismissedVersion(update.latest_version!)}
      >
        <X size={16} />
      </button>
    </aside>
  )
}
