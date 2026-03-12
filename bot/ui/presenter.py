from __future__ import annotations

from html import escape


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --panel: #fffaf2;
      --ink: #1f1a17;
      --muted: #6f645c;
      --accent: #b5532f;
      --line: #d8cbb8;
      --chip: #efe2d0;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(181,83,47,0.18), transparent 28rem),
        linear-gradient(180deg, #f8f3ea 0%, var(--bg) 100%);
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    .hero {{
      display: grid;
      gap: 16px;
      padding: 28px;
      border-bottom: 2px solid var(--line);
      background: rgba(255,250,242,0.75);
      backdrop-filter: blur(6px);
    }}
    .hero h1 {{ margin: 0; font-size: 2rem; letter-spacing: 0.02em; }}
    .nav {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .nav a {{
      padding: 8px 12px;
      border: 1px solid var(--line);
      background: var(--chip);
      border-radius: 999px;
      font-size: 0.95rem;
    }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; margin-top: 22px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 10px 24px rgba(31,26,23,0.05);
    }}
    .panel h2, .panel h3 {{ margin-top: 0; }}
    .meta {{ color: var(--muted); font-size: 0.92rem; }}
    .list {{ display: grid; gap: 10px; }}
    .item {{
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(255,255,255,0.6);
    }}
    .item strong {{ display: block; margin-bottom: 4px; }}
    .kv {{ margin: 0; display: grid; grid-template-columns: minmax(130px, 220px) 1fr; gap: 8px 14px; }}
    .kv dt {{ font-weight: 700; }}
    .kv dd {{ margin: 0; }}
    .empty {{ color: var(--muted); font-style: italic; }}
    code {{ font-family: "SFMono-Regular", "Menlo", "Consolas", monospace; font-size: 0.92em; }}
    .toolbar {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; color: var(--muted); }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-top: 18px; }}
    .card {{
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255,255,255,0.72);
    }}
    .card strong {{ display: block; font-size: 1.45rem; margin-top: 6px; }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--chip);
      font-size: 0.82rem;
      line-height: 1.2;
    }}
    .badge.good {{ background: #dfeedd; }}
    .badge.warn {{ background: #f7e7c7; }}
    .badge.bad {{ background: #f4d6d1; }}
    .flash {{
      margin-top: 18px;
      padding: 14px 16px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(239,226,208,0.9);
    }}
  </style>
</head>
<body>
  <div class="shell">{body}</div>
</body>
</html>"""


def hero(title: str, subtitle: str) -> str:
    return f"""
    <section class="hero">
      <h1>{escape(title)}</h1>
      <div class="meta">{escape(subtitle)}</div>
      <nav class="nav">
        <a href="/">Главная</a>
        <a href="/proposals">Предложения</a>
        <a href="/intents">Намерения</a>
        <a href="/alerts">Алерты</a>
        <a href="/research">Исследование</a>
        <a href="/decision-reviews">Разбор решений</a>
        <a href="/analysis">Анализ итогов</a>
        <a href="/catalog/markets">Рынки</a>
        <a href="/catalog/events">События</a>
        <a href="/views">Сохраненные виды</a>
      </nav>
    </section>
    """


def panel(title: str, body: str, meta: str | None = None) -> str:
    extra = f'<div class="meta">{escape(meta)}</div>' if meta else ""
    return f'<section class="panel"><h2>{escape(title)}</h2>{extra}{body}</section>'


def list_items(items: list[str], empty_message: str = "Нет данных.") -> str:
    if not items:
        return f'<div class="empty">{escape(empty_message)}</div>'
    return '<div class="list">' + "".join(f'<div class="item">{item}</div>' for item in items) + "</div>"


def kv_table(rows: list[tuple[str, object]]) -> str:
    html_rows = []
    for key, value in rows:
        html_rows.append(f"<dt>{escape(str(key))}</dt><dd>{escape(str(value))}</dd>")
    return '<dl class="kv">' + "".join(html_rows) + "</dl>"


def item_link(title: str, subtitle: str, href: str, meta: str | None = None) -> str:
    meta_html = f'<div class="meta">{escape(meta)}</div>' if meta else ""
    return f'<strong><a href="{escape(href, quote=True)}">{escape(title)}</a></strong><div>{escape(subtitle)}</div>{meta_html}'


def chips(values: list[str], empty_message: str = "-") -> str:
    if not values:
        return f'<div class="meta">{escape(empty_message)}</div>'
    return '<div class="toolbar">' + "".join(f'<span><code>{escape(value)}</code></span>' for value in values) + "</div>"


def link_row(links: list[tuple[str, str]]) -> str:
    if not links:
        return ""
    parts = [f'<a href="{escape(href, quote=True)}">{escape(label)}</a>' for label, href in links]
    return '<div class="toolbar">' + " ".join(parts) + "</div>"


def badge(value: str, tone: str = "warn") -> str:
    return f'<span class="badge {escape(tone)}">{escape(value)}</span>'


def summary_cards(cards: list[tuple[str, object, str]]) -> str:
    return (
        '<div class="cards">'
        + "".join(
            f'<section class="card"><div class="meta">{escape(label)}</div><strong>{escape(str(value))}</strong><div class="meta">{escape(meta)}</div></section>'
            for label, value, meta in cards
        )
        + "</div>"
    )


def flash_message(message: str, tone: str = "warn") -> str:
    tone_label = {"good": "успех", "warn": "внимание", "bad": "ошибка"}.get(tone, tone)
    return f'<section class="flash">{badge(tone_label, tone)} <strong>{escape(message)}</strong></section>'


def shell_page(title: str, heading: str, subtitle: str, body: str, flash: str | None = None) -> str:
    parts = hero(heading, subtitle)
    if flash:
        parts += flash_message(flash, "good")
    parts += body
    return page(title, parts)


def json_block(payload: str) -> str:
    return f"<pre><code>{escape(payload)}</code></pre>"
