"""
模块描述：中性基础设施层，收纳 Redis、认证存储与密码哈希等底层依赖。

放在 services/ 之外，供 auth.py 与 services/ 共同复用，避免 auth <-> services 循环。
"""
