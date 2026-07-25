"""项目集中配置"""
import os

# 业务配置
TARGET_TAX_ID = '91320594688334374M'
MAX_WORKERS = min(8, os.cpu_count() or 4)

# UI 配置
WINDOW_GEOMETRY = '780x820'
WINDOW_MIN_SIZE = (640, 680)

# 字体族
FONT_FAMILY = 'Microsoft YaHei UI'
FONT_CODE = 'Cascadia Code'
