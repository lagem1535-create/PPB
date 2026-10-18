r"""GitHub Pages용 웹 화면 만들기: purplu/web/tablet.html → docs/index.html

Pages에서 연 화면은 ?pc=PC주소:8766 으로 같은 와이파이의 PC 퍼플루에 붙는다.
화면을 고친 뒤 이걸 실행하고 커밋·푸시하면 Pages에 반영돼요:  .venv\Scripts\python build_pages.py
"""
from pathlib import Path

ROOT = Path(__file__).parent
src = (ROOT / "purplu" / "web" / "tablet.html").read_text(encoding="utf-8")
flag = '<script>window.PURPLU_REMOTE = true;</script>\n'
out = src.replace("<style>", flag + '<link rel="manifest" href="manifest.webmanifest">\n<style>', 1)
(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs" / "index.html").write_text(out, encoding="utf-8")
(ROOT / "docs" / "manifest.webmanifest").write_text(
    '{"name":"퍼플루","short_name":"퍼플루","start_url":"./","display":"fullscreen","orientation":"landscape",'
    '"background_color":"#000000","theme_color":"#000000","icons":[{"src":"icon.png","sizes":"128x128","type":"image/png"}]}',
    encoding="utf-8")
icon = ROOT / "chrome_extension" / "icons" / "128.png"
if icon.exists():
    (ROOT / "docs" / "icon.png").write_bytes(icon.read_bytes())
(ROOT / "docs" / ".nojekyll").write_text("", encoding="utf-8")
print("docs/index.html 만들었어요")
