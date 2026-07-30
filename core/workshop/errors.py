"""Typed Creative Workshop domain errors."""

from __future__ import annotations


class WorkshopError(Exception):
    """Base error for Workshop domain operations.

    创意工坊领域操作的基础错误。
    """


class WorkshopPackageError(WorkshopError):
    """Raised when a Workshop package fails closed validation.

    创意工坊安装包未通过安全校验时抛出。
    """

