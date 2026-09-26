# ansi.py is for ansi related function and variable to generate better terminal experience inside Discord.

class Color:
    # Foreground
    BLACK   = 30
    RED     = 31
    GREEN   = 32
    YELLOW  = 33
    BLUE    = 34
    MAGENTA = 35
    CYAN    = 36
    WHITE   = 37

    # Bright foreground
    BRIGHT_BLACK   = 90
    BRIGHT_RED     = 91
    BRIGHT_GREEN   = 92
    BRIGHT_YELLOW  = 93
    BRIGHT_BLUE    = 94
    BRIGHT_MAGENTA = 95
    BRIGHT_CYAN    = 96
    BRIGHT_WHITE   = 97

    # Background
    BG_BLACK   = 40
    BG_RED     = 41
    BG_GREEN   = 42
    BG_YELLOW  = 43
    BG_BLUE    = 44
    BG_MAGENTA = 45
    BG_CYAN    = 46
    BG_WHITE   = 47

    # Bright background
    BG_BRIGHT_BLACK   = 100
    BG_BRIGHT_RED     = 101
    BG_BRIGHT_GREEN   = 102
    BG_BRIGHT_YELLOW  = 103
    BG_BRIGHT_BLUE    = 104
    BG_BRIGHT_MAGENTA = 105
    BG_BRIGHT_CYAN    = 106
    BG_BRIGHT_WHITE   = 107

    # Styles
    RESET = 0
    BOLD = 1
    DIM = 2
    ITALIC = 3
    UNDERLINE = 4
    BLINK = 5
    REVERSE = 7
    HIDDEN = 8
    STRIKETHROUGH = 9


def c(*args):
    *codes, text = args
    return f"\033[{';'.join(map(str, codes))}m{text}\033[0m"
