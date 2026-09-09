"""Điểm vào: chạy MCP server trên stdio."""

from __future__ import annotations

import ctypes


def _set_dpi_awareness() -> None:
    """Không khai báo DPI awareness thì BoundingRectangle sẽ lệch trên màn hình scale."""
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> None:
    _set_dpi_awareness()
    from .server import mcp

    mcp.run()


if __name__ == "__main__":
    main()
