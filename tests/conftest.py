"""
模块描述：测试环境默认关闭生产启动副作用。
"""

import os


os.environ.setdefault("LAWVER_RELEASE_SYNC_ON_STARTUP", "0")
