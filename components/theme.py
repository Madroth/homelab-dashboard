from nicegui import ui

BG = '#1e1e2e'
SIDEBAR_BG = '#191925'
CARD_BG = '#242435'
BORDER = 'rgba(255,255,255,0.06)'
TEXT = '#e4e4f0'
TEXT_MUTED = '#9399b2'
TEXT_DIM = '#6c7086'
TEXT_DISABLED = '#4c4f61'
ACCENT = '#a5b4fc'
ACCENT_TINT = 'rgba(165,180,252,0.1)'
AMBER = '#f9c97c'
RED = '#f38ba8'
GREEN = '#a6e3a1'
PURPLE = '#cba6f7'

HEAD_HTML = '''
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
'''

GLOBAL_CSS = f'''
html, body {{ margin:0; padding:0; height:100%; overflow:hidden; background:{BG}; font-family:'Inter',sans-serif; color:{TEXT}; }}
.nq-nav-item:hover:not(.nq-disabled) {{ background:rgba(255,255,255,0.05) !important; color:{TEXT} !important; }}
.nq-nav-item.nq-active {{ background:{ACCENT_TINT} !important; color:{TEXT} !important; }}
.nq-nav-btn-hover:hover {{ background:rgba(165,180,252,0.08) !important; }}
.nq-custom-scroll::-webkit-scrollbar {{ width:6px; }}
.nq-custom-scroll::-webkit-scrollbar-track {{ background:transparent; }}
.nq-custom-scroll::-webkit-scrollbar-thumb {{ background:rgba(255,255,255,0.1); border-radius:3px; }}
@keyframes omegaPulse {{ 0%{{box-shadow:0 0 0 0 rgba(166,227,161,.55)}} 70%{{box-shadow:0 0 0 7px rgba(166,227,161,0)}} 100%{{box-shadow:0 0 0 0 rgba(166,227,161,0)}} }}
@keyframes omegaPulseAmber {{ 0%{{box-shadow:0 0 0 0 rgba(249,201,124,.5)}} 70%{{box-shadow:0 0 0 6px rgba(249,201,124,0)}} 100%{{box-shadow:0 0 0 0 rgba(249,201,124,0)}} }}
@keyframes omegaSkel {{ 0%{{opacity:.5}} 50%{{opacity:1}} 100%{{opacity:.5}} }}
.nq-skel {{ animation: omegaSkel 1.4s ease-in-out infinite; }}
.nq-markdown {{ font-size:13.5px; line-height:1.7; color:#c2c6d6; }}
.nq-markdown h1, .nq-markdown h2, .nq-markdown h3 {{ color:{TEXT}; margin-top:1.2em; margin-bottom:0.5em; }}
.nq-markdown a {{ color:{ACCENT}; text-decoration:none; }}
.nq-markdown a:hover {{ text-decoration:underline; }}
.nq-markdown pre {{ background:rgba(0,0,0,0.3); padding:10px; border-radius:6px; overflow-x:auto; }}
.nq-markdown code {{ font-family:'JetBrains Mono',monospace; font-size:0.9em; background:rgba(0,0,0,0.2); padding:2px 4px; border-radius:4px; }}
'''


def install():
    ui.add_head_html(HEAD_HTML)
    ui.add_css(GLOBAL_CSS)
    ui.dark_mode().enable()
