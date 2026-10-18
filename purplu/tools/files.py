"""내 PC에서 파일 찾기: Windows 검색 색인 → Everything(es.exe) → 직접 탐색."""
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from .. import trace

MAX_RESULTS = 15
HOME = Path.home()
SCAN_ROOTS = [HOME / d for d in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive")]
# 색인에 보통 안 들어가는 다른 드라이브(D: 등)는 직접 훑는다
OTHER_DRIVES = [Path(f"{c}:/") for c in "DEFGH" if Path(f"{c}:/").is_dir()]
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "AppData", ".venv", "$Recycle.Bin", "Windows", "Program Files"}


def _ext(kind: str | None) -> str | None:
    if not kind:
        return None
    kind = kind.strip().lower().lstrip(".")
    return "." + kind if kind else None


def _info(path: str) -> dict:
    try:
        st = os.stat(path)
        return {"path": path, "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "size_kb": round(st.st_size / 1024)}
    except OSError:
        return {"path": path}


def _search_index(keyword, ext, since) -> list[str] | None:
    """Windows 검색 색인(파일 이름 + 내용). 서비스가 꺼져 있으면 None."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return None
    q = keyword.replace("'", "''")
    where = [f"(System.FileName LIKE '%{q}%' OR CONTAINS(*, '\"{q}\"'))"] if q else []
    if ext:
        where.append(f"System.FileExtension = '{ext}'")
    if since:
        where.append(f"System.DateModified >= '{since:%Y-%m-%d %H:%M:%S}'")
    where.append("System.ItemType <> 'Directory'")
    sql = (f"SELECT TOP {MAX_RESULTS} System.ItemUrl FROM SystemIndex WHERE "
           + " AND ".join(where) + " ORDER BY System.DateModified DESC")
    pythoncom.CoInitialize()
    try:
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
        rs = win32com.client.Dispatch("ADODB.Recordset")
        trace.cmd(f"Windows Search(ADODB): {sql}")
        rs.Open(sql, conn)
        out = []
        while not rs.EOF:
            url = rs.Fields.Item("System.ItemUrl").Value or ""
            if url.lower().startswith("file:"):
                out.append(os.path.normpath(url[5:]))
            rs.MoveNext()
        rs.Close()
        conn.Close()
        return out
    except Exception:
        return None
    finally:
        pythoncom.CoUninitialize()


def _search_everything(keyword, ext, since) -> list[str] | None:
    es = shutil.which("es.exe") or shutil.which("es")
    if not es:
        return None
    args = [es, "-n", str(MAX_RESULTS), "-sort", "date-modified-descending"]
    query = keyword
    if ext:
        query += f" ext:{ext[1:]}"
    if since:
        query += f" dm:>={since:%Y-%m-%d}"
    try:
        trace.cmd(" ".join(args + [query.strip()]))
        r = subprocess.run(args + [query.strip()], capture_output=True, text=True, timeout=10,
                           encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return [line for line in r.stdout.splitlines() if line.strip()] if r.returncode == 0 else None


def _walk_into(hits, keyword, ext, since, roots, deadline):
    kw = keyword.lower()
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            if time.monotonic() > deadline:
                return
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith((".", "$"))]
            for f in filenames:
                low = f.lower()
                if (kw and kw not in low) or (ext and not low.endswith(ext)):
                    continue
                full = os.path.join(dirpath, f)
                if since:
                    try:
                        if datetime.fromtimestamp(os.path.getmtime(full)) < since:
                            continue
                    except OSError:
                        continue
                hits.append(full)


def _search_walk(keyword, ext, since, roots, budget=2.5) -> list[str]:
    """색인이 없는 곳을 직접 훑는다. budget초가 지나면 그때까지 찾은 것만 돌려준다."""
    hits: list[str] = []
    t = threading.Thread(target=_walk_into, args=(hits, keyword, ext, since, roots, time.monotonic() + budget),
                         daemon=True)
    trace.cmd(f"os.walk({', '.join(map(str, roots))})  # 색인에 없는 곳 직접 훑기, 최대 {budget}초")
    t.start()
    t.join(budget + 0.5)
    return list(hits)


def find_file(keyword: str = "", file_type: str | None = None, modified_within_days: int | None = None) -> dict:
    keyword = (keyword or "").strip()
    ext = _ext(file_type)
    since = datetime.now() - timedelta(days=int(modified_within_days)) if modified_within_days else None
    if not keyword and not ext:
        return {"ok": False, "error": "찾을 이름이나 파일 종류를 알려주세요."}
    found, sources = [], []
    for source, fn in (("windows_index", _search_index), ("everything", _search_everything)):
        paths = fn(keyword, ext, since)
        if paths is not None:
            found, sources = paths, [source]
            break
    if sources != ["everything"]:  # Everything은 모든 드라이브를 이미 봄
        roots = OTHER_DRIVES if sources else SCAN_ROOTS + OTHER_DRIVES
        found += _search_walk(keyword, ext, since, roots)
        sources.append("folder_scan")
    found = [p for p in dict.fromkeys(found) if os.path.exists(p)]
    found.sort(key=os.path.getmtime, reverse=True)
    result = {"ok": True, "source": "+".join(sources), "files": [_info(p) for p in found[:MAX_RESULTS]]}
    if not found:
        result["note"] = "못 찾았어요. 다른 단어로 다시 찾아볼까요?"
    return result


def open_path(path: str, show_in_folder: bool = False) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "그 파일이 없어요."}
    if show_in_folder:
        trace.cmd(f'explorer /select,"{p}"')
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        trace.cmd(f'os.startfile(r"{p}")')
        os.startfile(str(p))
    return {"ok": True, "opened": str(p)}
