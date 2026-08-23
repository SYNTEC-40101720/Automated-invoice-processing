/// <reference types="vite/client" />

interface NativeBridgeApi {
	select_directory: () => Promise<string>
	select_pdf_files: () => Promise<string[]>
	save_log_dialog: (default_name?: string) => Promise<string>
	write_log: (content: string) => Promise<boolean>
	open_directory: (path: string) => Promise<boolean>
	get_runtime_info: () => Promise<Record<string, string | boolean>>
}

interface Window {
	pywebview?: {
		api: NativeBridgeApi
	}
}