from pathlib import Path
import re, shutil
from datetime import datetime
APP = Path('app.py')
if not APP.exists(): raise SystemExit('No encuentro app.py. Guarda este archivo junto a app.py y ejecútalo desde esa carpeta.')
original = APP.read_text(encoding='utf-8')
backup = APP.with_name('app_antes_diseno_oscuro_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.py')
shutil.copy2(APP, backup)
css = '''<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
:root{color-scheme:dark;--bg:#080d0b;--panel:#121b17;--border:#2b3b32;--white:#f4f7f5;--muted:#b7c5bc;--green:#35d07f;}
html,body,[class*='css'],[data-testid='stAppViewContainer']{font-family:'DM Sans',sans-serif!important;}
.stApp,[data-testid='stAppViewContainer'],[data-testid='stMain']{background:var(--bg)!important;color:var(--white)!important;}
.block-container{max-width:1500px;padding-top:1.5rem;padding-bottom:2rem;}
[data-testid='stMain'] *{color:var(--white);}
h1,h2,h3,h4,h5,h6,p,label,li,span,small,.stMarkdown{color:var(--white);}
[data-testid='stCaptionContainer'] p,.stCaption,small{color:var(--muted)!important;}
.hero{background:linear-gradient(115deg,#101713,#173b29,#146b3c);border:1px solid #2c8b58;padding:26px 30px;border-radius:18px;margin-bottom:20px;}
.hero h1,.hero p,.hero *{color:#fff!important;}
section[data-testid='stSidebar'],section[data-testid='stSidebar']>div{background:#0c1410!important;border-right:1px solid var(--border);}
section[data-testid='stSidebar'] *{color:var(--white)!important;}
div[data-testid='stMetric'],[data-testid='metric-container']{background:var(--panel)!important;border:1px solid var(--border)!important;border-radius:14px!important;padding:16px!important;}
div[data-testid='stMetric'] label,div[data-testid='stMetric'] label *,div[data-testid='stMetricValue'],div[data-testid='stMetricValue'] *,div[data-testid='stMetricDelta'] *{color:var(--white)!important;opacity:1!important;}
div[data-testid='stMetricValue']{font-size:clamp(1.2rem,2vw,2rem)!important;overflow-wrap:anywhere!important;}
button[data-baseweb='tab'],button[data-baseweb='tab'] *{color:#d7e4dc!important;background:transparent!important;}
button[data-baseweb='tab'][aria-selected='true']{border-bottom:3px solid var(--green)!important;}
button[data-baseweb='tab'][aria-selected='true'] *{color:var(--green)!important;font-weight:700!important;}
div.stButton>button,div.stFormSubmitButton>button,button[kind='primary']{background:#16834b!important;color:#fff!important;border:1px solid var(--green)!important;border-radius:10px!important;min-height:40px;font-weight:700!important;}
div.stButton>button *,div.stFormSubmitButton>button *{color:#fff!important;}
input,textarea,div[data-baseweb='input'] input,div[data-baseweb='textarea'] textarea{background:#18231d!important;color:#fff!important;-webkit-text-fill-color:#fff!important;border-color:#405348!important;}
div[data-baseweb='select']>div{background:#18231d!important;color:#fff!important;border-color:#405348!important;}
div[data-baseweb='select'] span,div[data-baseweb='select'] input,div[data-baseweb='select'] div{color:#fff!important;}
[role='listbox'],[role='option'],[data-baseweb='popover'],[data-baseweb='menu']{background:#18231d!important;color:#fff!important;}
[role='option'] *{color:#fff!important;}
[data-testid='stDataFrame'],[data-testid='stTable']{background:var(--panel)!important;border:1px solid var(--border)!important;border-radius:10px!important;}
[data-testid='stDataFrame'] *{color:var(--white)!important;}
[data-testid='stForm'],[data-testid='stExpander']{background:var(--panel)!important;border:1px solid var(--border)!important;border-radius:12px!important;}
hr{border-color:var(--border)!important;}[data-testid='stAlert'] *{color:var(--white)!important;}
.stApp a{color:#65e69d!important;}::placeholder{color:#a9b8af!important;opacity:1!important;}
</style>'''
pattern = r'st\.markdown\("""\s*<style>.*?</style>\s*""",\s*unsafe_allow_html=True\)'
m = re.search(pattern, original, flags=re.S)
if not m: raise SystemExit('No localicé el bloque CSS inicial. No se hicieron cambios.')
updated = original[:m.start()] + 'st.markdown(r"""' + css + '""", unsafe_allow_html=True)' + original[m.end():]
old = """                    price, source = market.fetch_yfinance_price(
                        selected["symbol"]
                    )

                    db.update_price(
                        selected["id"],
                        price,
                        source,
                        market.today()
                    )"""
new = """                    price, source, quote_date = market.fetch_yfinance_price(
                        selected["symbol"]
                    )

                    db.update_price(
                        selected["id"],
                        price,
                        source,
                        quote_date
                    )"""
if old in updated: updated = updated.replace(old,new,1)
elif 'price, source, quote_date = market.fetch_yfinance_price' not in updated: raise SystemExit('No identifiqué el bloque de precios. No se guardaron cambios.')
if 'px.defaults.template' not in updated: updated = updated.replace('import streamlit as st', "import streamlit as st\n\npx.defaults.template = 'plotly_dark'",1)
compile(updated,str(APP),'exec')
APP.write_text(updated,encoding='utf-8')
print('Diseño oscuro aplicado y sintaxis verificada.')
print('Copia de seguridad:',backup.name)
print('La base de datos y el historial no fueron modificados.')
