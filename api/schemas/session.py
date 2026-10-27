"""Session route schemas.
Session 路由的数据模型。
"""

from pydantic import BaseModel, Field


class SessionRequest(BaseModel):
    """Request model carrying a session identifier and optional kept files.
    携带 Session ID 与可选保留文件 ID 的请求模型。
    """

    session_id: str = Field(..., description="Session ID")
    keep_file_ids: list[str] = Field(
        default_factory=list,
        description="File IDs to keep when closing the session",
    )


class SessionHeartbeatResponse(BaseModel):
    """Response model for session lease renewal.
    Session 租约续期的响应模型。
    """

    status: str = Field("ok", description="操作状态")
    expires_at: str = Field(..., description="新的过期时间（ISO 8601）")


class SessionCloseResponse(BaseModel):
    """Response model for immediate session close.
    立即关闭 Session 的响应模型。
    """

    status: str = Field("ok", description="操作状态")
    cleaned_files: int = Field(0, description="成功清理的文件数")
