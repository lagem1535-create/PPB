"""무료 웹 검색: Gemini 검색 한도와 상관없이 구글 뉴스 RSS + DuckDuckGo 결과를 가져온다 (키 필요 없음)."""
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import httpx

from .. import trace

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9"}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _news(query: str, n: int) -> list[dict]:
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    trace.cmd(f"HTTP GET {url}")
    r = httpx.get(url, headers=UA, timeout=8, follow_redirects=True)
    out = []
    for item in ET.fromstring(r.content).iter("item"):
        out.append({"title": _clean(item.findtext("title")), "date": (item.findtext("pubDate") or "")[:16],
                    "source": _clean(item.findtext("source")), "url": item.findtext("link")})
        if len(out) >= n:
            break
    return out


def _web(query: str, n: int) -> list[dict]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query, "kl": "kr-kr"})
    trace.cmd(f"HTTP GET {url}")
    r = httpx.get(url, headers=UA, timeout=8, follow_redirects=True)
    out = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>',
                         r.text, re.S):
        link = m.group(1)
        if "uddg=" in link:
            link = urllib.parse.unquote(link.split("uddg=")[1].split("&")[0])
        out.append({"title": _clean(m.group(2)), "snippet": _clean(m.group(3))[:220], "url": link})
        if len(out) >= n:
            break
    return out


def search_web(query: str, kind: str = "all") -> dict:
    """kind: all(웹+뉴스) / news / web"""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "검색어가 없어요."}
    jobs = {}
    with ThreadPoolExecutor(2) as pool:
        if kind in ("all", "news"):
            jobs["news"] = pool.submit(_news, query, 8)
        if kind in ("all", "web"):
            jobs["web"] = pool.submit(_web, query, 6)
        result = {"ok": True, "query": query}
        for k, f in jobs.items():
            try:
                result[k] = f.result(timeout=12)
            except Exception as e:
                result[k] = []
                result[f"{k}_error"] = str(e)[:100]
    if not any(result.get(k) for k in ("news", "web")):
        return {"ok": False, "error": "검색 결과를 못 가져왔어요 (인터넷 확인).", **result}
    result["note"] = "최신 결과야. 이름·숫자를 구체적으로 넣어 2~4문장으로 말해. 지어내지 마."
    return result


def search_text(query: str) -> str:
    """web_research가 Gemini 검색 한도에 걸렸을 때 쓰는 자료 묶음."""
    r = search_web(query)
    lines = [f"- [뉴스] {x['title']} ({x.get('source', '')}, {x.get('date', '')})" for x in r.get("news", [])]
    lines += [f"- [웹] {x['title']}: {x.get('snippet', '')}" for x in r.get("web", [])]
    return "\n".join(lines)
