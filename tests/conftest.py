"""
模块描述：测试环境默认关闭生产启动副作用，并确保任何用例都不会写入仓库内的真实 data 目录。
"""

import atexit
import os
import shutil
import tempfile


os.environ.setdefault("LAWVER_RELEASE_SYNC_ON_STARTUP", "0")
# 兜底启动凭据：个别用例在模块顶层 import routes/auth，此时尚未进入 setUp。
os.environ.setdefault("SECRET_KEY", "t" * 32)
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "bootstrap-password")

# 部分用例会在 tearDown 中把 LAWVER_DATA_DIR 还原为「未设置」；若之后的用例在导入
# auth/agent 前忘记重新指定目录，模块级路径就会解析到仓库内的 data/ 并执行真实迁移。
# 这里先兜底一个一次性临时目录，用例自身设置的值仍会覆盖它。
if not os.environ.get("LAWVER_DATA_DIR"):
    _FALLBACK_DATA_DIR = tempfile.mkdtemp(prefix="lawver-test-data-")
    os.environ["LAWVER_DATA_DIR"] = _FALLBACK_DATA_DIR
    atexit.register(shutil.rmtree, _FALLBACK_DATA_DIR, ignore_errors=True)
