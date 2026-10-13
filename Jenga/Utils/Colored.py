#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Colored – Console colors and styles.
Provides cross‑platform colored output with automatic detection.
All public methods are PascalCase; private methods are _PascalCase.
"""

import os
import sys
import re
from typing import Optional, List, Union

class Colored:
    # -----------------------------------------------------------------------
    # ANSI escape sequences – UPPER_SNAKE_CASE (attributs de classe)
    # -----------------------------------------------------------------------

    _RESET = "\033[0m"

    # Styles
    _BOLD = "\033[1m"
    _DIM = "\033[2m"
    _ITALIC = "\033[3m"
    _UNDERLINE = "\033[4m"
    _BLINK = "\033[5m"
    _REVERSE = "\033[7m"
    _HIDDEN = "\033[8m"
    _STRIKE = "\033[9m"

    # Foreground colors (basic)
    _BLACK = "\033[30m"
    _RED = "\033[31m"
    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _BLUE = "\033[34m"
    _MAGENTA = "\033[35m"
    _CYAN = "\033[36m"
    _WHITE = "\033[37m"

    # Bright foreground colors
    _BRIGHT_BLACK = "\033[90m"
    _BRIGHT_RED = "\033[91m"
    _BRIGHT_GREEN = "\033[92m"
    _BRIGHT_YELLOW = "\033[93m"
    _BRIGHT_BLUE = "\033[94m"
    _BRIGHT_MAGENTA = "\033[95m"
    _BRIGHT_CYAN = "\033[96m"
    _BRIGHT_WHITE = "\033[97m"

    # Background colors
    _BG_BLACK = "\033[40m"
    _BG_RED = "\033[41m"
    _BG_GREEN = "\033[42m"
    _BG_YELLOW = "\033[43m"
    _BG_BLUE = "\033[44m"
    _BG_MAGENTA = "\033[45m"
    _BG_CYAN = "\033[46m"
    _BG_WHITE = "\033[47m"
    _BG_BRIGHT_BLACK = "\033[100m"
    _BG_BRIGHT_RED = "\033[101m"
    _BG_BRIGHT_GREEN = "\033[102m"
    _BG_BRIGHT_YELLOW = "\033[103m"
    _BG_BRIGHT_BLUE = "\033[104m"
    _BG_BRIGHT_MAGENTA = "\033[105m"
    _BG_BRIGHT_CYAN = "\033[106m"
    _BG_BRIGHT_WHITE = "\033[107m"

    # -----------------------------------------------------------------------
    # Internal state – _camelCase (attributs de classe)
    # -----------------------------------------------------------------------

    _supportsColor = None
    _isWindows = sys.platform == "win32"
    _useWinApi = False

    # -----------------------------------------------------------------------
    # Private helpers – _PascalCase (méthodes statiques)
    # -----------------------------------------------------------------------

    @staticmethod
    def _PrintSafe(text: str, stream, end: str = "\n") -> None:
        """
        Print text while gracefully handling consoles that cannot encode
        Unicode symbols (common on legacy Windows code pages).
        """
        try:
            print(text, file=stream, end=end)
        except UnicodeEncodeError:
            encoding = getattr(stream, "encoding", None) or "utf-8"
            safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
            print(safe_text, file=stream, end=end)

    @staticmethod
    def _DetectColorSupport() -> bool:
        """Detect if terminal supports ANSI colors."""
        if Colored._supportsColor is not None:
            return Colored._supportsColor

        # Windows: try to enable ANSI via kernel32
        if Colored._isWindows:
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                hStdout = kernel32.GetStdHandle(-11)
                hStderr = kernel32.GetStdHandle(-12)
                mode = ctypes.c_uint32()
                if kernel32.GetConsoleMode(hStdout, ctypes.byref(mode)):
                    mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
                    kernel32.SetConsoleMode(hStdout, mode)
                if kernel32.GetConsoleMode(hStderr, ctypes.byref(mode)):
                    mode.value |= 0x0004
                    kernel32.SetConsoleMode(hStderr, mode)
                Colored._useWinApi = True
                Colored._supportsColor = True
                return True
            except Exception:
                Colored._supportsColor = (
                    os.environ.get("ANSICON") is not None or
                    os.environ.get("ConEmuANSI") == "ON" or
                    os.environ.get("TERM") in ("xterm", "xterm-256color", "linux", "cygwin")
                )
                return Colored._supportsColor

        # Unix-like
        # (2.8.19) sys.stdout vaut None sans console : pas de couleur, et surtout pas d'exception.
        if sys.stdout is None or not sys.stdout.isatty():
            Colored._supportsColor = False
            return False
        term = os.environ.get("TERM", "")
        Colored._supportsColor = term in (
            "xterm", "xterm-256color", "linux", "screen",
            "screen-256color", "tmux", "tmux-256color"
        )
        return Colored._supportsColor

    @staticmethod
    def _StripAnsiCodes(text: str) -> str:
        """Remove all ANSI escape sequences from string."""
        return re.sub(r"\033\[[0-9;]*m", "", text)

    @staticmethod
    def _EnableWindowsApi() -> bool:
        """Force enable ANSI support on Windows via ctypes."""
        if not Colored._isWindows:
            return False
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            hStdout = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(hStdout, ctypes.byref(mode)):
                mode.value |= 0x0004
                kernel32.SetConsoleMode(hStdout, mode)
                Colored._useWinApi = True
                return True
        except Exception:
            pass
        return False

    # -----------------------------------------------------------------------
    # Public API – PascalCase (méthodes statiques)
    # -----------------------------------------------------------------------

    @staticmethod
    def SupportsColor() -> bool:
        """Check whether the current terminal supports colored output."""
        return Colored._DetectColorSupport()

    @staticmethod
    def EnableWindowsColor() -> bool:
        """Force enable ANSI colors on Windows."""
        return Colored._EnableWindowsApi()

    @staticmethod
    def Colorize(text: str, color: Optional[str] = None, bg: Optional[str] = None,
                 bold: bool = False, dim: bool = False, italic: bool = False,
                 underline: bool = False, blink: bool = False, reverse: bool = False,
                 strike: bool = False) -> str:
        """
        Wrap text with ANSI color/style codes.
        If colors are not supported, return plain text.
        """
        if not Colored._DetectColorSupport():
            return text

        codes = []
        if bold:        codes.append(Colored._BOLD)
        if dim:         codes.append(Colored._DIM)
        if italic:      codes.append(Colored._ITALIC)
        if underline:   codes.append(Colored._UNDERLINE)
        if blink:       codes.append(Colored._BLINK)
        if reverse:     codes.append(Colored._REVERSE)
        if strike:      codes.append(Colored._STRIKE)

        if color:
            color = color.lower()
            if color == "black":        codes.append(Colored._BLACK)
            elif color == "red":        codes.append(Colored._RED)
            elif color == "green":      codes.append(Colored._GREEN)
            elif color == "yellow":     codes.append(Colored._YELLOW)
            elif color == "blue":       codes.append(Colored._BLUE)
            elif color == "magenta":    codes.append(Colored._MAGENTA)
            elif color == "cyan":       codes.append(Colored._CYAN)
            elif color == "white":      codes.append(Colored._WHITE)
            elif color == "brightblack":  codes.append(Colored._BRIGHT_BLACK)
            elif color == "brightred":    codes.append(Colored._BRIGHT_RED)
            elif color == "brightgreen":  codes.append(Colored._BRIGHT_GREEN)
            elif color == "brightyellow": codes.append(Colored._BRIGHT_YELLOW)
            elif color == "brightblue":   codes.append(Colored._BRIGHT_BLUE)
            elif color == "brightmagenta":codes.append(Colored._BRIGHT_MAGENTA)
            elif color == "brightcyan":   codes.append(Colored._BRIGHT_CYAN)
            elif color == "brightwhite":  codes.append(Colored._BRIGHT_WHITE)

        if bg:
            bg = bg.lower()
            if bg == "black":           codes.append(Colored._BG_BLACK)
            elif bg == "red":           codes.append(Colored._BG_RED)
            elif bg == "green":         codes.append(Colored._BG_GREEN)
            elif bg == "yellow":        codes.append(Colored._BG_YELLOW)
            elif bg == "blue":          codes.append(Colored._BG_BLUE)
            elif bg == "magenta":       codes.append(Colored._BG_MAGENTA)
            elif bg == "cyan":          codes.append(Colored._BG_CYAN)
            elif bg == "white":         codes.append(Colored._BG_WHITE)
            elif bg == "brightblack":   codes.append(Colored._BG_BRIGHT_BLACK)
            elif bg == "brightred":     codes.append(Colored._BG_BRIGHT_RED)
            elif bg == "brightgreen":   codes.append(Colored._BG_BRIGHT_GREEN)
            elif bg == "brightyellow":  codes.append(Colored._BG_BRIGHT_YELLOW)
            elif bg == "brightblue":    codes.append(Colored._BG_BRIGHT_BLUE)
            elif bg == "brightmagenta": codes.append(Colored._BG_BRIGHT_MAGENTA)
            elif bg == "brightcyan":    codes.append(Colored._BG_BRIGHT_CYAN)
            elif bg == "brightwhite":   codes.append(Colored._BG_BRIGHT_WHITE)

        if codes:
            return "".join(codes) + text + Colored._RESET
        return text

    @staticmethod
    def Print(text: str, **kwargs) -> None:
        """Print colored text to stdout."""
        end = kwargs.pop("end", "\n")
        Colored._PrintSafe(Colored.Colorize(text, **kwargs), stream=sys.stdout, end=end)

    @staticmethod
    def PrintError(text: str, **kwargs) -> None:
        """Print error message in red to stderr."""
        end = kwargs.pop("end", "\n")
        kwargs["color"] = kwargs.get("color", "red")
        Colored._PrintSafe(Colored.Colorize(text, **kwargs), stream=sys.stderr, end=end)

    @staticmethod
    def PrintSuccess(text: str, **kwargs) -> None:
        """Print success message in green."""
        kwargs["color"] = kwargs.get("color", "green")
        Colored._PrintSafe(Colored.Colorize(text, **kwargs), stream=sys.stdout)

    @staticmethod
    def PrintWarning(text: str, **kwargs) -> None:
        """Print warning message in yellow."""
        kwargs["color"] = kwargs.get("color", "yellow")
        Colored._PrintSafe(Colored.Colorize(text, **kwargs), stream=sys.stdout)

    @staticmethod
    def PrintInfo(text: str, **kwargs) -> None:
        """Print informational message in cyan."""
        kwargs["color"] = kwargs.get("color", "cyan")
        Colored._PrintSafe(Colored.Colorize(text, **kwargs), stream=sys.stdout)

    @staticmethod
    def StripColors(text: str) -> str:
        """Remove all ANSI escape sequences from a string."""
        return Colored._StripAnsiCodes(text)

    @staticmethod
    def LenWithoutColors(text: str) -> int:
        """Return the length of the string without counting ANSI codes."""
        return len(Colored._StripAnsiCodes(text))

    @staticmethod
    def FormatTable(rows: List[List[str]],
                    headers: Optional[List[str]] = None,
                    colors: Optional[List[Optional[str]]] = None,
                    headerColors: Optional[List[str]] = None) -> str:
        """
        Format a list of rows as a pretty table with optional colors.
        Returns a string that can be printed.
        """
        if not rows and not headers:
            return ""

        strRows = [[str(cell) for cell in row] for row in rows]
        strHeaders = [str(h) for h in headers] if headers else None

        colCount = max(len(row) for row in strRows) if strRows else 0
        if strHeaders:
            colCount = max(colCount, len(strHeaders))

        widths = [0] * colCount
        if strHeaders:
            for i, cell in enumerate(strHeaders):
                if i < colCount:
                    widths[i] = max(widths[i], Colored.LenWithoutColors(cell))
        for row in strRows:
            for i, cell in enumerate(row):
                if i < colCount:
                    widths[i] = max(widths[i], Colored.LenWithoutColors(cell))

        lines = []

        # Headers
        if strHeaders:
            headerLine = ""
            for i in range(colCount):
                cell = strHeaders[i] if i < len(strHeaders) else ""
                color = headerColors[i] if headerColors and i < len(headerColors) else None
                formatted = Colored.Colorize(cell.ljust(widths[i]), color=color, bold=True) if color else cell.ljust(widths[i])
                headerLine += formatted + "   "
            lines.append(headerLine.rstrip())
            lines.append(Colored.Colorize("=" * (sum(widths) + 3 * (colCount - 1)), color="white", dim=True))

        # Rows
        for rowIdx, row in enumerate(strRows):
            line = ""
            for i in range(colCount):
                cell = row[i] if i < len(row) else ""
                color = colors[rowIdx] if colors and rowIdx < len(colors) else None
                formatted = Colored.Colorize(cell.ljust(widths[i]), color=color) if color else cell.ljust(widths[i])
                line += formatted + "   "
            lines.append(line.rstrip())

        return "\n".join(lines)
