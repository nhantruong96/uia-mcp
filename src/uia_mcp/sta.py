"""Một apartment STA duy nhất cho toàn bộ lời gọi UI Automation.

UIA là COM và đòi hỏi STA. Nếu nhiều thread cùng gọi ``CoInitialize`` rồi cùng chạm
vào cùng một cây UIA, ta sẽ dính deadlock khi COM marshal qua lại giữa các apartment
(Windows-MCP đã phải bỏ song song hoá vì đúng lý do này). Cách chắc chắn duy nhất là:
*một* thread STA, mọi thứ khác marshal vào đó.
"""

from __future__ import annotations

import ctypes
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable

COINIT_APARTMENTTHREADED = 0x2

#: Không lời gọi UIA nào được phép chạy lâu hơn ngần này. Một cửa sổ treo sẽ khiến
#: provider không bao giờ trả lời; ta cần thoát ra thay vì đứng im mãi mãi.
DEFAULT_TIMEOUT = 20.0


class StaWedged(RuntimeError):
    """Thread STA đang bị kẹt trong một lời gọi UIA không chịu trả về."""


class StaExecutor:
    """Marshal callable vào một thread STA duy nhất và chờ kết quả."""

    def __init__(self, name: str = "uia-sta") -> None:
        self._name = name
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._wedged = False
        self._thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("không khởi tạo được apartment STA")

    def _loop(self) -> None:
        ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        self._ready.set()
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                fut, fn, args, kwargs = item
                if not fut.set_running_or_notify_cancel():
                    continue
                try:
                    fut.set_result(fn(*args, **kwargs))
                except BaseException as exc:  # noqa: BLE001 - đẩy nguyên vẹn sang caller
                    fut.set_exception(exc)
        finally:
            ctypes.windll.ole32.CoUninitialize()

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        if self._wedged:
            raise StaWedged(
                "Thread UIA đang kẹt ở một lời gọi trước đó (nhiều khả năng có cửa sổ "
                "treo). Khởi động lại MCP server để tiếp tục."
            )
        fut: Future = Future()
        self._queue.put((fut, fn, args, kwargs))
        return fut

    def call(self, fn: Callable[..., Any], *args: Any, timeout: float = DEFAULT_TIMEOUT, **kwargs: Any) -> Any:
        fut = self.submit(fn, *args, **kwargs)
        try:
            return fut.result(timeout)
        except TimeoutError:
            # Không thể giết an toàn một thread STA đang nằm trong COM. Đánh dấu hỏng
            # để mọi lời gọi sau báo lỗi rõ ràng thay vì xếp hàng sau một hàng đợi chết.
            self._wedged = True
            raise StaWedged(
                f"Lời gọi UIA vượt quá {timeout:.0f}s — ứng dụng đích nhiều khả năng "
                f"không phản hồi."
            ) from None

    @property
    def wedged(self) -> bool:
        return self._wedged


#: Executor dùng chung cho cả tiến trình.
STA = StaExecutor()
