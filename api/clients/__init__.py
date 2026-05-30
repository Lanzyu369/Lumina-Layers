"""HTTP clients for out-of-process Lumina services.
跨进程 Lumina 服务的 HTTP 客户端。

Currently hosts :mod:`api.clients.mls_client`, the thin client the main app
uses to reach the decoupled Material-LUT Studio service for management-class
operations (Route B). Hot-path pipeline data access does NOT go through this
client directly; it goes through :mod:`core.material_lut_provider`, which
adds prefetch + local-cache semantics so per-pixel network calls never happen.
当前包含 :mod:`api.clients.mls_client`，主应用用它访问解耦后的 Material-LUT
Studio 服务（路线 B）执行管理类操作。管线热路径数据访问不直接走此客户端，
而是经 :mod:`core.material_lut_provider`，由后者提供预取+本地缓存语义，
确保不会发生逐像素网络调用。
"""
