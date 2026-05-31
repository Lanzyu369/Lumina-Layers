"""Shared API service helpers.
共享 API 服务辅助模块。

Houses session-free, presentation-layer helpers that are reused by more than
one HTTP surface (the main Lumina router and the decoupled Material-LUT
Studio service), so the same logic is never copy-pasted across routers.
存放会话无关的展示层辅助函数，供多个 HTTP 出口（主 Lumina 路由与解耦后的
Material-LUT Studio 服务）复用，避免在不同路由间复制粘贴同一套逻辑。
"""
