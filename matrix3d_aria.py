#!/usr/bin/env python3
"""
Aria Edition — the gentle version of the matrix screensaver, made for Rubin's
6-year-old daughter: slower rain, smaller rain glyphs, fewer + slow-drifting
FULL-SIZE floating words so she can read them easily (word sizes match the
original 40-76px). Words list adds AI chip companies (NVIDIA and their
products) and drops SORA. The original matrix3d.py is untouched.

Base behavior: classic vertical glyph rain (like the movie) with cycling
colors, mixed fonts (katakana + latin), and a layer of words floating up and
down. Resolution-aware; exits on any input.
"""
import os, random, sys, math

import pygame

def _dismiss_siblings():
    """Rubin's rule (2026-09-07): dismissing ONE screen clears EVERY screen.
    Called only on user-input exits (key/mouse/close) — never on crash or
    MATRIX_AUTOQUIT (test mode). Kills sibling matrix instances so no saver
    is left running on another display, and restores the cursor (the exec'd
    wrapper's EXIT trap never fires)."""
    try:
        import subprocess
        subprocess.Popen(["pkill", "-f", "matrix3d[.]py"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.Popen(["hyprctl", "eval",
                          "hl.config({ cursor = { invisible = false } })"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

PALETTES = [
    (0x00, 0xFF, 0x41),   # classic green
    (0x00, 0xD4, 0xFF),   # cyan
    (0xFF, 0xD7, 0x00),   # gold
    (0xB0, 0x4A, 0xFF),   # violet
    (0xFF, 0x45, 0x5A),   # neon red
    (0x00, 0xFF, 0x41),
]
PALETTE_CYCLE = 18.0
GOLD = (0xFF, 0xD7, 0x00)

# --- fonts ---------------------------------------------------------------
FONT_MONO = next((p for p in (
    "/usr/share/fonts/ttf-ia-writer/iAWriterMonoS-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/noto/NotoSansMono-Regular.ttf",
) if os.path.exists(p)), None)
FONT_MONO_BOLD = next((p for p in (
    "/usr/share/fonts/ttf-ia-writer/iAWriterMonoS-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
) if os.path.exists(p)), FONT_MONO)
FONT_CJK = "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"
HAS_CJK = os.path.exists(FONT_CJK)   # Windows/others: rain falls back to latin

if HAS_CJK:
    KATAKANA = "アカサタナハマヤラワヲンアイウエオカキクケコツテトニヌネノ"
else:
    KATAKANA = ""
LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
RAIN_CHARS = KATAKANA + LATIN

# rain geometry — Aria: smaller cells/glyphs, gentler
CELL_W, CELL_H = 28, 44
RAIN_SIZES = (26, 34)          # alternate per column for subtle depth
RAIN_TRAIL = 12

# per-column tint variants applied to the palette color
TINTS = ((0, 0, 0), (36, -12, 0), (-24, 0, 44), (0, 30, -18))

BRAIN_WORDS = [
    # AI chips & makers (Aria edition: the silicon story)
    "NVIDIA", "AMD", "INTEL", "TSMC", "ARM", "GPU", "CHIPS", "RTX", "CUDA",
    "GEFORCE", "TENSOR", "H100", "H200", "B200", "DGX", "JETSON",
    "BLACKWELL", "HOPPER",
    # friendly AI / models
    "AI", "ROBOT", "ROBOTS", "OPENAI", "CHATGPT", "CLAUDE", "GEMINI",
    "DEEPSEEK", "LLAMA", "MISTRAL", "GROK",
    # what AI does (kid-friendly)
    "COMPUTER", "CODING", "LEARNING", "MACHINE", "NEURAL", "BRAIN",
    "VOICE", "VISION", "PICTURE", "VIDEO", "MUSIC", "MODEL", "TRAINING",
    "PYTHON", "PYTORCH", "HERMES", "OMARCHY",
]

class RainCol:
    __slots__ = ("x", "y", "dir", "speed", "chars", "size", "tint", "burst_t")

class FloatWord:
    __slots__ = ("text", "x", "y", "dir", "speed", "size", "gold", "phase")

def main():
    os.environ.setdefault("SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", "0")
    pygame.init()
    pygame.mouse.set_visible(False)
    # MATRIX_MONITOR = SDL display index to fullscreen on (0 = laptop panel,
    # 1 = TV when docked). Unset/0 keeps the historical behavior. The launcher
    # passes it when Rubin's preferred display isn't display 0.
    mon = int(os.environ.get("MATRIX_MONITOR", "0") or "0")
    try:
        sizes = pygame.display.get_desktop_sizes()
        W, H = sizes[mon]
    except Exception:
        info = pygame.display.Info()
        W, H = info.current_w or 1920, info.current_h or 1080
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN | pygame.DOUBLEBUF, display=mon)
    clock = pygame.time.Clock()

    # word list: external file wins (drop real vault titles there later)
    words = BRAIN_WORDS
    wfile = os.path.expanduser("~/.local/share/omarchy-matrix/words.txt")
    if os.path.exists(wfile):
        got = [l.strip().upper() for l in open(wfile) if l.strip()]
        if len(got) >= 5:
            words = got

    def font_for(size, bold=False):
        p = FONT_MONO_BOLD if bold else FONT_MONO
        return pygame.font.Font(p, size) if p else pygame.font.Font(None, size * 2)

    fonts = {}                      # (size, bold) -> Font
    fonts_cjk = {}
    def get_font(size, bold=False, cjk=False):
        key = (size, bold)
        if cjk:
            if size not in fonts_cjk and os.path.exists(FONT_CJK):
                fonts_cjk[size] = pygame.font.Font(FONT_CJK, int(size * 1.7))
            return fonts_cjk.get(size)
        if key not in fonts:
            fonts[key] = font_for(size, bold)
        return fonts[key]

    glyph_cache = {}                # (char, size, color, bold) -> Surface
    def glyph(ch, size, color, bold=False, cjk=None):
        cjk = cjk if cjk is not None else (not ch.isascii())
        key = (ch, size, color, bold)
        s = glyph_cache.get(key)
        if s:
            return s
        f = get_font(size, bold, cjk)
        s = f.render(ch, True, color)
        glyph_cache[key] = s
        return s

    def tint_color(color, tint):
        return tuple(max(0, min(255, color[i] + tint[i])) for i in range(3))

    # vignette overlay
    vign = pygame.Surface((W, H), pygame.SRCALPHA)
    for i in range(0, 60):
        a = int(85 * (i / 60.0) ** 2)
        rad = int(math.hypot(W, H) * (0.55 + 0.45 * i / 60.0))
        pygame.draw.ellipse(vign, (0, 0, 0, a),
                            (W / 2 - rad, H / 2 - rad, 2 * rad, 2 * rad), 4)

    # --- rain columns -----------------------------------------------------
    ncols = W // CELL_W + 2
    cols = []
    for i in range(ncols):
        c = RainCol()
        c.x = i * CELL_W + random.uniform(-8, 8)
        c.dir = -1 if random.random() < 0.14 else 1   # 14% float UP
        c.y = random.uniform(0, H)                     # start on screen
        c.speed = random.uniform(1.0, 2.4)             # Aria: slow rain
        c.chars = [random.choice(RAIN_CHARS) for _ in range(RAIN_TRAIL + 3)]
        c.size = RAIN_SIZES[i % 2]
        c.tint = random.randrange(len(TINTS))
        c.burst_t = 0
        cols.append(c)

    # --- floating words (Aria: fewer, slower, smaller so they can be read) ---
    fwords = []
    for _ in range(14):
        w = FloatWord()
        w.text = random.choice(words)
        w.x = random.uniform(0, W)
        w.y = random.uniform(0, H)
        w.dir = 1 if random.random() < 0.5 else -1
        w.speed = random.uniform(0.2, 0.6)
        w.size = random.choice((40, 52, 64, 76))     # Aria: full-size words, slow drift
        w.gold = random.random() < 0.18
        w.phase = random.uniform(0, 2 * math.pi)
        fwords.append(w)

    # faint background glyph dust
    dust = [(random.uniform(0.02, 0.98), random.uniform(0.02, 0.98),
             random.choice(RAIN_CHARS)) for _ in range(42)]

    t = 0.0
    frame = 0
    last_color = [None]
    mouse_last = pygame.mouse.get_pos()
    autoquit = int(os.environ.get("MATRIX_AUTOQUIT", "0") or 0)
    t_end = pygame.time.get_ticks() + autoquit * 1000 if autoquit else None
    debug = os.environ.get("MATRIX_DEBUG") == "1"
    testmode = os.environ.get("MATRIX_TEST") == "1"   # ignore mouse motion

    while True:
        dt = clock.tick(60) / 1000.0
        t += dt
        frame += 1

        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                _dismiss_siblings(); pygame.quit(); sys.exit(0)
            if e.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                _dismiss_siblings(); pygame.quit(); sys.exit(0)
            if e.type == pygame.MOUSEMOTION and not testmode:
                x, y = e.pos
                lx, ly = mouse_last
                if abs(x - lx) + abs(y - ly) > 10:
                    _dismiss_siblings(); pygame.quit(); sys.exit(0)
                mouse_last = (x, y)
        if t_end and pygame.time.get_ticks() >= t_end:
            pygame.quit(); sys.exit(0)

        # palette lerp (quantized for a stable glyph cache)
        seg = (t / PALETTE_CYCLE) % (len(PALETTES) - 1)
        i = int(seg)
        f = seg - i
        a, b = PALETTES[i], PALETTES[i + 1]
        raw = tuple(int(a[j] + (b[j] - a[j]) * f) for j in range(3))
        color = tuple(c & 0xE0 for c in raw)
        if color != last_color[0]:
            glyph_cache.clear()
            last_color[0] = color

        screen.fill((0, 0, 0))

        # faint dust
        dim2 = tuple(int(c * 0.20) for c in color)
        for dx, dy, ch in dust:
            screen.blit(glyph(ch, 24, dim2), (dx * W, dy * H))

        # --- glyph rain (classic vertical scroll) ---
        for c in cols:
            c.y += c.dir * c.speed * dt * 60
            if c.dir == 1 and c.y > H + RAIN_TRAIL * CELL_H:      # fell off bottom
                c.y = -random.uniform(0, 3 * CELL_H)               # re-enter fast
                c.chars = [random.choice(RAIN_CHARS) for _ in range(RAIN_TRAIL + 3)]
                c.speed = random.uniform(1.0, 2.4)                 # Aria: slow
                if random.random() < 0.08:
                    c.burst_t = 10
            elif c.dir == -1 and c.y < -RAIN_TRAIL * CELL_H:      # rose off top
                c.y = H + random.uniform(0, 3 * CELL_H)
                c.chars = [random.choice(RAIN_CHARS) for _ in range(RAIN_TRAIL + 3)]
                c.speed = random.uniform(0.7, 1.6)                 # Aria: slow up

            tint = TINTS[c.tint]
            base = tint_color(color, tint)
            head_bright = tuple(min(255, base[j] + 150) for j in range(3))
            mid = tuple(int(base[j] * 0.80) for j in range(3))
            tail = tuple(int(base[j] * 0.38) for j in range(3))

            for k in range(RAIN_TRAIL - 1, -1, -1):
                yy = c.y - c.dir * k * CELL_H
                if yy < -CELL_H or yy > H + CELL_H:
                    continue
                ch = c.chars[k % len(c.chars)]
                col = head_bright if k == 0 else (mid if k < 5 else tail)
                if c.burst_t > 0 and k == 0:
                    c.size = 40                                    # Aria: small burst
                surf = glyph(ch, c.size, col)
                if k == 0 and c.burst_t == 0:
                    for gx, gy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                        screen.blit(surf, (c.x + gx, yy + gy))
                screen.blit(surf, (c.x, yy))
            if c.burst_t > 0:
                c.burst_t -= 1
                c.size = RAIN_SIZES[0]

        # --- floating brain words (up and down) ---
        word_col = color if not any(c for c in ()) else color
        for w in fwords:
            w.y += w.dir * w.speed * dt * 60
            w.x += 0.10 * math.sin(t * 0.3 + w.phase) * dt        # Aria: gentle sway
            if w.y > H + 80:
                w.y = -80
                w.text = random.choice(words)
            elif w.y < -80:
                w.y = H + 80
                w.text = random.choice(words)
            # fade near edges
            edge = min(w.y, H - w.y) if w.dir == 1 else min(H - w.y, w.y)
            alpha = max(0.25, min(1.0, edge / 260.0))
            wc = GOLD if w.gold else tint_color(word_col, TINTS[(frame // 90) % 4])
            wc = tuple(int(v * alpha) + int(v * (1 - alpha) * 0.15) for v in wc)
            surf = glyph(w.text, w.size, wc, bold=True)
            screen.blit(surf, (w.x, w.y))

        screen.blit(vign, (0, 0))

        if debug and frame in (120, 540):
            pygame.image.save(screen, f"/tmp/matrix-frame-{frame}.png")
        if debug and frame % 30 == 0:
            with open("/tmp/matrix-fps.log", "a") as fh:
                fh.write(f"{clock.get_fps():.0f}\n")

        pygame.display.flip()

if __name__ == "__main__":
    main()
