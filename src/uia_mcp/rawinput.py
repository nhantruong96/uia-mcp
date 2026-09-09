"""Bơm chuột/bàn phím thật — chỉ dùng ở các bậc fallback cuối của thang hành động.

Lưu ý: dùng những hàm này KHÔNG có nghĩa là quay lại cơ chế screenshot. Toạ độ ở đây
đến từ ``BoundingRectangle`` của UIA (chính xác từng pixel), không phải từ việc model
nhìn ảnh và đoán.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

WHEEL_DELTA = 120

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send(*inputs: INPUT) -> None:
    count = len(inputs)
    array = (INPUT * count)(*inputs)
    sent = user32.SendInput(count, array, ctypes.sizeof(INPUT))
    if sent != count:
        raise OSError(f"SendInput gửi được {sent}/{count} sự kiện", ctypes.get_last_error())


def _key_event(vk: int, scan: int, flags: int) -> INPUT:
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags))


# Bảng phím đủ dùng cho điều hướng và xác nhận.
VK = {
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "space": 0x20,
    "backspace": 0x08,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
}
VK.update({f"f{n}": 0x6F + n for n in range(1, 13)})


def press_key(combo: str) -> None:
    """Nhấn một tổ hợp phím, ví dụ ``"enter"`` hoặc ``"ctrl+s"``."""
    parts = [part.strip().lower() for part in combo.split("+") if part.strip()]
    if not parts:
        raise ValueError("tổ hợp phím rỗng")

    codes = []
    for part in parts:
        if part in VK:
            codes.append(VK[part])
        elif len(part) == 1:
            code = user32.VkKeyScanW(ord(part))
            if code == -1:
                raise ValueError(f"không ánh xạ được phím {part!r}")
            codes.append(code & 0xFF)
        else:
            raise ValueError(f"phím không nhận dạng được: {part!r}")

    events = [_key_event(code, 0, 0) for code in codes]
    events += [_key_event(code, 0, KEYEVENTF_KEYUP) for code in reversed(codes)]
    _send(*events)


def type_text(text: str) -> None:
    """Gõ text theo Unicode scan code — độc lập với layout bàn phím.

    Đi qua từng UTF-16 code unit nên tiếng Việt có dấu và emoji đều đúng.
    """
    events: list[INPUT] = []
    for char in text:
        if char == "\n":
            # Xuống dòng phải là phím Enter thật, không phải ký tự U+000A.
            events.append(_key_event(VK["enter"], 0, 0))
            events.append(_key_event(VK["enter"], 0, KEYEVENTF_KEYUP))
            continue
        if char == "\r":
            continue
        for unit in _utf16_units(ord(char)):
            events.append(_key_event(0, unit, KEYEVENTF_UNICODE))
            events.append(_key_event(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))

    # Gửi theo lô để chuỗi dài không vượt giới hạn một lần SendInput.
    for start in range(0, len(events), 200):
        _send(*events[start : start + 200])


def _utf16_units(code_point: int) -> tuple[int, ...]:
    if code_point < 0x10000:
        return (code_point,)
    adjusted = code_point - 0x10000
    return (0xD800 + (adjusted >> 10), 0xDC00 + (adjusted & 0x3FF))


def click_at(x: int, y: int, button: str = "left", clicks: int = 1) -> None:
    """Click chuột thật tại toạ độ do UIA cung cấp."""
    down, up = {
        "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    }[button]
    if not user32.SetCursorPos(int(x), int(y)):
        raise OSError("SetCursorPos thất bại", ctypes.get_last_error())
    for _ in range(clicks):
        _send(
            INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dwFlags=down)),
            INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dwFlags=up)),
        )


def wheel_at(x: int, y: int, direction: str = "down", notches: int = 3) -> None:
    """Lăn chuột tại một điểm — fallback khi provider không có ScrollPattern."""
    amount = WHEEL_DELTA * notches
    horizontal = direction in ("left", "right")
    if direction in ("down", "right"):
        amount = -amount if direction == "down" else amount
    elif direction in ("up", "left"):
        amount = amount if direction == "up" else -amount
    else:
        raise ValueError(f"hướng cuộn không hợp lệ: {direction!r}")

    if not user32.SetCursorPos(int(x), int(y)):
        raise OSError("SetCursorPos thất bại", ctypes.get_last_error())
    _send(
        INPUT(
            type=INPUT_MOUSE,
            mi=MOUSEINPUT(
                mouseData=ctypes.c_uint32(amount).value,
                dwFlags=MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL,
            ),
        )
    )
