"""Stream complete feedback files without retaining one handle per attachment.

流式读写完整工单文件，避免每个附件持续占用一个文件句柄。
"""

from __future__ import annotations

import io
from pathlib import Path
import tempfile

from starlette.formparsers import MultiPartParser


class FeedbackFile(io.BufferedIOBase):
    """Reopen a file for each operation and retain its virtual position.

    每次操作时打开文件，完成后关闭，独立保留读写位置。
    """

    _rolled = True

    def __init__(self, path: Path, size: int = 0, *, temporary: bool = False) -> None:
        self.path = path
        self._size = size
        self._position = 0
        self._temporary = temporary

    @classmethod
    def create_temporary(cls) -> FeedbackFile:
        """Create an upload file that is deleted when its owner closes it.

        创建上传临时文件，由所属请求关闭时删除。
        """
        with tempfile.NamedTemporaryFile(prefix="lumina-feedback-upload-", delete=False) as output:
            path = Path(output.name)
        return cls(path, temporary=True)

    def _ensure_open(self) -> None:
        if self.closed:
            raise ValueError("I/O operation on a closed feedback file")

    def read(self, size: int = -1) -> bytes:
        """Read exact bytes without keeping a descriptor open.

        读取原始字节，操作结束后不保留文件句柄。
        """
        self._ensure_open()
        with self.path.open("rb") as source:
            source.seek(self._position)
            data = source.read(size)
        self._position += len(data)
        return data

    def write(self, data: bytes) -> int:
        """Write an upload chunk and release its descriptor immediately.

        写入上传分块并立即释放文件句柄。
        """
        self._ensure_open()
        if not self._temporary:
            raise io.UnsupportedOperation("Ticket attachments are read-only")
        with self.path.open("r+b") as output:
            output.seek(self._position)
            written = output.write(data)
        self._position += written
        self._size = max(self._size, self._position)
        return written

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Move the virtual position without opening the file.

        调整读写位置，无需打开文件。
        """
        self._ensure_open()
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._position, io.SEEK_END: self._size}.get(whence)
        if base is None or base + offset < 0:
            raise OSError("Invalid feedback file position")
        self._position = base + offset
        return self._position

    def tell(self) -> int:
        """Return the virtual byte position. / 返回当前字节位置。"""
        self._ensure_open()
        return self._position

    def flush(self) -> None:
        """Writes already close their handles. / 每次写入已关闭句柄并刷新。"""
        self._ensure_open()

    def close(self) -> None:
        """Release the request-owned temporary file. / 清理请求所属临时文件。"""
        if self.closed:
            return
        try:
            if self._temporary:
                self.path.unlink(missing_ok=True)
        finally:
            super().close()


class FeedbackMultipartParser(MultiPartParser):
    """Parse all sources using request-owned files with no retained handles.

    解析全部源文件，临时文件由请求管理且不持续占用句柄。
    """

    def on_headers_finished(self) -> None:
        """Use a reopenable disk file for each uploaded part.

        为每个上传分段使用可按需打开的磁盘文件。
        """
        super().on_headers_finished()
        upload = self._current_part.file
        if upload is not None:
            temporary = FeedbackFile.create_temporary()
            upload.file.close()
            self._files_to_close_on_error[-1] = temporary
            upload.file = temporary
