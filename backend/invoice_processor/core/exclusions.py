"""文件名级排除规则：结账单等非票据 PDF 不进入拉取与处理流。"""

# 命中关键词的文件名一律跳过：邮箱拉取（直接附件与 ZIP 成员）与
# 目录处理（源目录扫描、启动预检）两侧统一口径。用元组避免每次
# 调用重建列表。
EXCLUDED_FILENAME_KEYWORDS: tuple[str, ...] = ('结账单',)


def is_excluded_filename(filename: str) -> bool:
    """文件名命中排除关键词（如结账单）时返回 True。"""
    lowered = filename.casefold()
    return any(kw in lowered for kw in EXCLUDED_FILENAME_KEYWORDS)
