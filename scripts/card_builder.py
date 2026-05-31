"""
Сборка карточек задания для Telegram-бота.

  build_question_card(qid)  → PIL Image  — условие задачи
  build_solution_card(qid)  → PIL Image  — ответ + решение
  card_to_bytes(img)        → bytes      — для отправки в Telegram
  build_card(qid)           → PIL Image  — алиас build_question_card
"""

import io
import re
import shutil
import sqlite3
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests
from PIL import Image, ImageDraw, ImageFont

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "physics.db"

# ── Размеры ─────────────────────────────────────────────────────────────────
CARD_W  = 900          # ширина карточки, пикселей
PAD     = 28           # внешний отступ блоков
BORDER  = 6            # толщина левой цветной полосы
FONT_PT = 17           # основной шрифт
DPI     = 100          # DPI matplotlib

# ── LaTeX-компилятор ─────────────────────────────────────────────────────────
_XELATEX  = shutil.which("xelatex")  or "/Library/TeX/texbin/xelatex"
_PDFTOPPM = shutil.which("pdftoppm") or "/opt/homebrew/bin/pdftoppm"
_USE_LATEX = Path(_XELATEX).exists() and Path(_PDFTOPPM).exists()

# ── Цвета ────────────────────────────────────────────────────────────────────
C_BG         = (248, 249, 250)
C_Q_HEADER   = ( 30,  87, 153)   # синий
C_Q_ACCENT   = ( 52, 152, 219)
C_Q_BG       = (235, 242, 251)
C_Q_BORDER   = ( 52, 152, 219)
C_ANS_BG     = ( 39, 174,  96)   # зелёный
C_SOL_HEADER = ( 91,  44, 133)   # фиолетовый
C_SOL_ACCENT = (155,  89, 182)
C_SOL_BG     = (245, 240, 250)
C_SOL_BORDER = (155,  89, 182)
C_TEXT_DARK  = ( 25,  25,  35)
C_TEXT_LIGHT = (255, 255, 255)


# ── Шрифты ───────────────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    if bold:
        paths = [
            '/System/Library/Fonts/Helvetica.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        ]
    else:
        paths = [
            '/System/Library/Fonts/Helvetica.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ── Очистка LaTeX ─────────────────────────────────────────────────────────────

_RE_ANSWER   = re.compile(r'Ответ\s*:.*?(\n|$)', re.I | re.M)
_RE_VIDEO    = re.compile(r'Видео(решение|разбор)\s+на\s+\S+\.?\s*', re.I)


def _clean_latex(text: str) -> str:
    """Нормализует LaTeX-разметку для рендеринга."""
    if not text:
        return ''
    text = _RE_ANSWER.sub('\n', text)
    text = _RE_VIDEO.sub('', text)

    # \( \) → $ $
    text = text.replace(r'\(', '$').replace(r'\)', '$')

    # Фиксим внутренности math-блоков
    def _fix(m: re.Match) -> str:
        s = m.group(1).strip()
        if not s:
            return ''
        s = s.replace('~', r'\,')
        s = re.sub(r'\\;', r'\\,', s)
        s = re.sub(r'\\\\', ' ', s)
        s = re.sub(r'\\text\{([^}]*)\}', r'\\mathrm{\1}', s)
        s = re.sub(r'\\=', '=', s)
        return f'${s}$'

    text = re.sub(r'\$(.+?)\$', _fix, text, flags=re.DOTALL)
    return text.strip()


# ── Разбивка текста на блоки ──────────────────────────────────────────────────

def _split_blocks(text: str) -> list[tuple[str, str]]:
    """
    Возвращает список блоков:
      ('display', formula) — display-формула из $$...$$
      ('text',   content)  — абзац (может содержать inline $...$)
    """
    blocks: list[tuple[str, str]] = []
    parts = re.split(r'\$\$(.+?)\$\$', text, flags=re.DOTALL)
    for i, part in enumerate(parts):
        s = part.strip()
        if not s:
            continue
        if i % 2 == 1:
            formula = re.sub(r'\\\\', ' ', s.replace('~', r'\,'))
            formula = re.sub(r'\\;', r'\\,', formula)
            blocks.append(('display', formula))
        else:
            for para in s.split('\n'):
                para = para.strip()
                if para:
                    blocks.append(('text', para))
    return blocks


# ── Вспомогательные рендеры ───────────────────────────────────────────────────

def _rgb_hex(rgb: tuple) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*rgb)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont,
               max_width_px: int) -> list[str]:
    """Оборачивает текст по ширине в пикселях."""
    words = text.split()
    if not words:
        return ['']
    lines: list[str] = []
    current = ''
    for word in words:
        test = (current + ' ' + word).strip()
        w = font.getlength(test)
        if w <= max_width_px:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or ['']


def _wrap_math(text: str, font: ImageFont.FreeTypeFont,
               max_width_px: int) -> list[str]:
    """
    Оборачивает текст с inline $...$:
    не разрывает math-блоки, считает их как одно слово.
    """
    segments = re.split(r'(\$[^$]+?\$)', text)
    lines: list[str] = ['']
    for seg in segments:
        is_math = seg.startswith('$') and seg.endswith('$') and len(seg) > 1
        tokens = [seg] if is_math else seg.split()
        for token in tokens:
            if not token:
                continue
            test = (lines[-1] + ' ' + token).strip()
            w = font.getlength(re.sub(r'\$[^$]*\$', 'xx', test))
            if w <= max_width_px and lines[-1]:
                lines[-1] = test
            elif lines[-1]:
                lines.append(token)
            else:
                lines[-1] = token
    return [l for l in lines if l.strip()] or ['']


def _render_plain(text: str, width_px: int, fontsize: int,
                  bg: tuple) -> Image.Image:
    """PIL рендер абзаца без формул."""
    font   = _load_font(fontsize)
    lines  = _wrap_text(text, font, width_px)
    line_h = fontsize + 8
    h      = max(1, len(lines) * line_h)
    img    = Image.new('RGBA', (width_px, h), bg + (255,))
    draw   = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((0, i * line_h), line, fill=C_TEXT_DARK, font=font)
    return img


def _escape_tex(s: str) -> str:
    """Экранирует LaTeX-спецсимволы в текстовых (не-math) фрагментах."""
    for old, new in (
        ('\\', r'\textbackslash{}'),
        ('{',  r'\{'), ('}', r'\}'),
        ('%',  r'\%'), ('&', r'\&'), ('#', r'\#'),
        ('^',  r'\^{}'), ('~', r'\textasciitilde{}'),
    ):
        s = s.replace(old, new)
    return s


def _to_latex_src(text: str) -> str:
    """Превращает текст с $…$ / $$…$$ в корректный LaTeX."""
    parts = re.split(r'(\$\$[^$]+?\$\$|\$[^$]+?\$)', text, flags=re.DOTALL)
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 1:                         # math-токен
            if p.startswith('$$'):
                out.append(r'\[' + p[2:-2] + r'\]')
            else:
                out.append(p)                  # $…$ оставляем как есть
        else:
            out.append(_escape_tex(p))
    return ''.join(out)


_TEX_DOC = r"""\documentclass[varwidth={w}cm,border=2pt]{{standalone}}
\usepackage{{fontspec}}
\setmainfont{{Helvetica}}
\usepackage{{amsmath,amssymb}}
\usepackage{{xcolor}}
\pagecolor[RGB]{{{br},{bg},{bb}}}
\color[RGB]{{{fr},{fg},{fb}}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{3pt}}
\begin{{document}}
\raggedright
\fontsize{{{fs}pt}}{{{ls}pt}}\selectfont
{center}{content}
\end{{document}}
"""


def _render_xelatex(content: str, width_px: int, fontsize: int,
                    bg: tuple, center: bool = False) -> Optional[Image.Image]:
    """Компилирует блок текста/формул через xelatex → pdftoppm → PIL."""
    cm_per_px = 2.54 / DPI
    w_cm = width_px * cm_per_px
    br, bg_g, bb = bg
    fr, fg_c, fb = C_TEXT_DARK
    ls = int(fontsize * 1.5)

    tex = _TEX_DOC.format(
        w=f'{w_cm:.3f}',
        br=br, bg=bg_g, bb=bb,
        fr=fr, fg=fg_c, fb=fb,
        fs=fontsize, ls=ls,
        center=r'\centering' + '\n' if center else '',
        content=_to_latex_src(content),
    )

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / 'block.tex').write_text(tex, encoding='utf-8')
        r = subprocess.run(
            [_XELATEX, '-interaction=nonstopmode', '-halt-on-error', 'block.tex'],
            cwd=tmp, capture_output=True, timeout=30,
        )
        pdf = d / 'block.pdf'
        if not pdf.exists():
            return None
        subprocess.run(
            [_PDFTOPPM, '-r', str(DPI * 2), '-png', '-singlefile',
             'block.pdf', str(d / 'out')],
            cwd=tmp, capture_output=True, timeout=15,
        )
        candidates = sorted(d.glob('out*.png'))
        if not candidates:
            return None
        img = Image.open(candidates[0]).convert('RGBA')
        # Рендерим при DPI*2 для качества → уменьшаем до целевого размера
        target_w = width_px
        target_h = max(1, img.height // 2)
        return img.resize((target_w, target_h), Image.LANCZOS)


def _mpl_to_pil(fig) -> Image.Image:
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=DPI, bbox_inches='tight',
                facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert('RGBA')


def _safe_ax_text(ax, x, y, text, fontsize, color, ha='left', va='top'):
    try:
        ax.text(x, y, text, fontsize=fontsize, ha=ha, va=va,
                color=color, transform=ax.transAxes)
        return True
    except Exception:
        pass
    plain = re.sub(r'\$[^$]*\$', '(ф)', text)
    try:
        ax.text(x, y, plain, fontsize=fontsize, ha=ha, va=va,
                color=color, transform=ax.transAxes)
        return True
    except Exception:
        return False


def _render_math_para(text: str, width_px: int, fontsize: int,
                      bg: tuple) -> Image.Image:
    """Рендер абзаца с inline-формулами: xelatex (если доступен) → matplotlib."""
    if _USE_LATEX:
        img = _render_xelatex(text, width_px, fontsize, bg)
        if img is not None:
            return img

    # Fallback: matplotlib mathtext
    font  = _load_font(fontsize)
    lines = _wrap_math(text, font, width_px)
    n     = max(1, len(lines))
    lh_pt   = fontsize * 1.45
    pad_pt  = fontsize * 0.6
    fig_h   = (n * lh_pt + pad_pt * 2) / 72
    fig_w   = width_px / DPI
    bg_hex  = _rgb_hex(bg)
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=bg_hex)
    ax  = fig.add_axes([0, 0, 1, 1], facecolor=bg_hex)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')
    total_h_pt = n * lh_pt + pad_pt * 2
    for i, line in enumerate(lines):
        y = 1.0 - (pad_pt + i * lh_pt + lh_pt * 0.1) / total_h_pt
        _safe_ax_text(ax, 0.005, y, line, fontsize, _rgb_hex(C_TEXT_DARK), va='top')
    try:
        return _mpl_to_pil(fig)
    except Exception:
        plt.close('all')
        return Image.new('RGBA', (width_px, 4), bg + (255,))


def _render_display_math(formula: str, width_px: int,
                          bg: tuple) -> Image.Image:
    """Рендер display-формулы: xelatex → matplotlib."""
    if _USE_LATEX:
        content = f'$${formula}$$'
        img = _render_xelatex(content, width_px, FONT_PT + 2, bg, center=True)
        if img is not None:
            return img

    # Fallback: matplotlib mathtext
    fs     = FONT_PT + 2
    fig_h  = (fs * 2.5) / 72
    fig_w  = width_px / DPI
    bg_hex = _rgb_hex(bg)
    fig = plt.figure(figsize=(fig_w, fig_h), facecolor=bg_hex)
    ax  = fig.add_axes([0, 0, 1, 1], facecolor=bg_hex)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')
    _safe_ax_text(ax, 0.5, 0.5, f'${formula}$', fs,
                  _rgb_hex(C_TEXT_DARK), ha='center', va='center')
    try:
        return _mpl_to_pil(fig)
    except Exception:
        plt.close('all')
        return Image.new('RGBA', (width_px, 4), bg + (255,))


# ── Загрузка ресурсов ─────────────────────────────────────────────────────────

def _download(url: str, timeout: int = 12) -> Optional[Image.Image]:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert('RGBA')
    except Exception:
        return None


def _fit(img: Image.Image, max_w: int) -> Image.Image:
    if img.width <= max_w:
        return img
    return img.resize((max_w, int(img.height * max_w / img.width)),
                      Image.LANCZOS)


def _load_question(qid: int, db_path: Path):
    conn = sqlite3.connect(db_path)
    row  = conn.execute("""
        SELECT q.text, q.answer, q.exam_topic, s.text
        FROM   questions q
        LEFT JOIN solutions s ON s.question_id = q.id
        WHERE  q.id = ?
    """, (qid,)).fetchone()
    if not row:
        conn.close()
        return None
    q_text, answer, topic, solution = row
    imgs = conn.execute(
        "SELECT type, url FROM images WHERE question_id = ? ORDER BY id",
        (qid,)
    ).fetchall()
    conn.close()
    # deduplicate, preserve order
    q_urls = list(dict.fromkeys(u for t, u in imgs if t == 'question'))
    s_urls = list(dict.fromkeys(u for t, u in imgs if t == 'solution'))
    return q_text, answer, topic, solution, q_urls, s_urls


# ── PIL-хелперы ───────────────────────────────────────────────────────────────

def _new(w: int, h: int, color: tuple) -> Image.Image:
    return Image.new('RGBA', (w, h), color + (255,))


def _paste(dst: Image.Image, src: Image.Image, x: int, y: int):
    if src.mode == 'RGBA':
        dst.paste(src, (x, y), src)
    else:
        dst.paste(src, (x, y))


# ── Строительные блоки ────────────────────────────────────────────────────────

def _text_width() -> int:
    """Ширина области текста (без отступов и границы)."""
    return CARD_W - PAD * 2 - BORDER - 8


def _build_text_section(text: Optional[str], bg: tuple, border: tuple,
                         images: list[Image.Image],
                         fontsize: int = FONT_PT) -> Image.Image:
    """
    Секция: цветной фон + левая полоса + текст (с формулами) + картинки.
    """
    tw = _text_width()
    parts: list[Image.Image] = []

    if text:
        text = _clean_latex(text)
        for kind, content in _split_blocks(text):
            if kind == 'display':
                img = _fit(_render_display_math(content, tw, bg), tw)
                parts.append(img)
            elif '$' in content:
                parts.append(_render_math_para(content, tw, fontsize, bg))
            else:
                parts.append(_render_plain(content, tw, fontsize, bg))

    for photo in images:
        parts.append(_fit(photo, tw))

    if not parts:
        return _new(CARD_W, 1, bg)

    gap    = PAD // 2
    total  = sum(p.height for p in parts) + PAD * 2 + gap * (len(parts) - 1)
    canvas = _new(CARD_W, total, bg)
    ImageDraw.Draw(canvas).rectangle(
        [0, 0, BORDER, total], fill=border + (255,)
    )
    y = PAD
    for part in parts:
        _paste(canvas, part, PAD + BORDER + 4, y)
        y += part.height + gap

    return canvas


def _build_header(text: str, bg: tuple, accent: tuple,
                   fontsize: int = 16) -> Image.Image:
    h    = 58
    img  = _new(CARD_W, h, bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, h - 4, CARD_W, h], fill=accent + (255,))
    draw.text((PAD, h // 2 - fontsize // 2), text,
              fill=C_TEXT_LIGHT, font=_load_font(fontsize, bold=True))
    return img


def _build_answer_bar(answer: str) -> Image.Image:
    h    = 66
    img  = _new(CARD_W, h, C_ANS_BG)
    draw = ImageDraw.Draw(img)
    draw.text((PAD, 10),  'Ответ:',    fill=(200, 255, 210), font=_load_font(13))
    draw.text((PAD, 28),  str(answer), fill=C_TEXT_LIGHT,    font=_load_font(22, bold=True))
    return img


def _assemble(sections: list[Image.Image]) -> Image.Image:
    total = sum(s.height for s in sections)
    out   = _new(CARD_W, total, C_BG)
    y     = 0
    for sec in sections:
        _paste(out, sec, 0, y)
        y += sec.height
    return out.convert('RGB')


# ── Публичные функции ─────────────────────────────────────────────────────────

def build_question_card(question_id: int,
                         db_path: Path = DB_PATH) -> Optional[Image.Image]:
    """Карточка с условием задания (без ответа и решения)."""
    data = _load_question(question_id, db_path)
    if not data:
        return None
    q_text, answer, topic, solution, q_urls, s_urls = data

    q_imgs = [img for url in q_urls if (img := _download(url)) is not None]

    return _assemble([
        _build_header(topic or 'Физика', C_Q_HEADER, C_Q_ACCENT),
        _build_text_section(q_text, C_Q_BG, C_Q_BORDER, q_imgs),
    ])


def build_solution_card(question_id: int,
                         db_path: Path = DB_PATH) -> Optional[Image.Image]:
    """Карточка с ответом и разбором решения."""
    data = _load_question(question_id, db_path)
    if not data:
        return None
    q_text, answer, topic, solution, q_urls, s_urls = data

    s_imgs = [img for url in s_urls if (img := _download(url)) is not None]

    sections = [
        _build_header('Решение  ·  ' + (topic or 'Физика'),
                      C_SOL_HEADER, C_SOL_ACCENT),
    ]
    if answer:
        sections.append(_build_answer_bar(answer))
    sections.append(
        _build_text_section(solution, C_SOL_BG, C_SOL_BORDER, s_imgs,
                            fontsize=FONT_PT - 1)
    )
    return _assemble(sections)


def build_card(question_id: int,
               db_path: Path = DB_PATH) -> Optional[Image.Image]:
    """Алиас для build_question_card (используется в pregenerate_cards.py)."""
    return build_question_card(question_id, db_path)


def card_to_bytes(card: Image.Image, fmt: str = 'JPEG',
                  quality: int = 92) -> bytes:
    """Конвертирует карточку в байты для отправки в Telegram."""
    buf = io.BytesIO()
    rgb = card.convert('RGB')
    if fmt.upper() == 'JPEG':
        rgb.save(buf, format='JPEG', quality=quality, optimize=True)
    else:
        rgb.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    return buf.getvalue()


# ── Быстрый тест ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    ids = [int(x) for x in sys.argv[1:]] or [661869, 687751, 682354]
    for qid in ids:
        print(f'Q {qid}...', end=' ', flush=True)
        c = build_question_card(qid)
        if c:
            c.save(f'/tmp/q_{qid}.png')
            print(f'ok {c.size}')
        else:
            print('not found')
        print(f'S {qid}...', end=' ', flush=True)
        c = build_solution_card(qid)
        if c:
            c.save(f'/tmp/s_{qid}.png')
            print(f'ok {c.size}')
        else:
            print('not found')
