"""Shared API service helpers.
共享 API 服务辅助模块。

Houses session-free, presentation-layer helpers used by local API routers, so
the same logic is never copy-pasted across endpoints.
存放会话无关的展示层辅助函数，供本地主应用 API 路由复用，避免在端点间复制
粘贴同一套逻辑。
"""
