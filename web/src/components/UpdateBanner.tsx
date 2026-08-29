import { Download, Settings2, X } from 'lucide-react'
import { useState } from 'react'
import type { UpdateResponse } from '../api/types'

interface UpdateBannerProps {
  update: UpdateResponse
  onOpenSettings: () => void
}

export function UpdateBanner({ update, onOpenSettings }: UpdateBannerProps) {
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
        <span>当前版本 v{update.current_version}，请在设置中完成自动更新。</span>
      </div>
      <button className="primary-button update-action" onClick={onOpenSettings}>
        <Settings2 size={14} /> 前往更新设置
      </button>
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
