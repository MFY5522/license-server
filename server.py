# -*- coding: utf-8 -*-
"""晚更v授权 - 卡密后台（Render 免费部署版）"""
import os, secrets, sqlite3, time
from contextlib import contextmanager
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

DB_PATH = os.environ.get("DATABASE_PATH", "data.db")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
SESSIONS = set()
app = FastAPI(title="license")

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn; conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            note TEXT DEFAULT '',
            created_at INTEGER NOT NULL,
            expires_at INTEGER,
            activated_at INTEGER,
            device_id TEXT,
            banned INTEGER NOT NULL DEFAULT 0,
            ban_reason TEXT DEFAULT '',
            last_seen INTEGER)""")

def gen_code():
    a = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "-".join("".join(secrets.choice(a) for _ in range(4)) for _ in range(4))

DURATIONS = {"1d": ("天卡", 86400), "30d": ("月卡", 2592000), "365d": ("年卡", 31536000), "forever": ("永久", None)}

def fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""

init_db()

def require_admin(request: Request):
    tok = request.cookies.get("session")
    if not tok or tok not in SESSIONS:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})

def check_row(row):
    if row["banned"]:
        return False, f"卡密已被封禁: {row['ban_reason'] or '联系客服'}"
    if row["expires_at"] and row["expires_at"] < int(time.time()):
        return False, f"卡密已过期 ({fmt_ts(row['expires_at'])})"
    return True, ""

@app.post("/api/activate")
async def activate(request: Request):
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    device_id = (body.get("device_id") or "").strip()
    if not code or not device_id:
        return JSONResponse({"ok": False, "msg": "参数缺失"})
    now = int(time.time())
    with db() as c:
        row = c.execute("SELECT * FROM cards WHERE code=?", (code,)).fetchone()
        if not row:
            return JSONResponse({"ok": False, "msg": "卡密不存在"})
        ok, msg = check_row(row)
        if not ok:
            return JSONResponse({"ok": False, "msg": msg})
        if row["activated_at"] and row["device_id"] != device_id:
            c.execute("UPDATE cards SET activated_at=?, device_id=?, last_seen=? WHERE id=?",
                      (now, device_id, now, row["id"]))
            msg = "已在新设备激活，旧设备已下线"
        else:
            c.execute("UPDATE cards SET activated_at=?, device_id=?, last_seen=? WHERE id=?",
                      (now, device_id, now, row["id"]))
            msg = "激活成功"
        return JSONResponse({"ok": True, "msg": msg,
                             "expires_at": row["expires_at"],
                             "expires_text": "永久" if not row["expires_at"] else fmt_ts(row["expires_at"])})

@app.post("/api/verify")
async def verify(request: Request):
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    device_id = (body.get("device_id") or "").strip()
    with db() as c:
        row = c.execute("SELECT * FROM cards WHERE code=?", (code,)).fetchone()
        if not row:
            return JSONResponse({"ok": False, "msg": "卡密不存在"})
        ok, msg = check_row(row)
        if not ok:
            return JSONResponse({"ok": False, "msg": msg})
        if row["device_id"] and row["device_id"] != device_id:
            return JSONResponse({"ok": False, "msg": "卡密已在其他设备登录，本机已失效"})
        c.execute("UPDATE cards SET last_seen=? WHERE id=?", (int(time.time()), row["id"]))
        return JSONResponse({"ok": True, "expires_at": row["expires_at"],
                             "expires_text": "永久" if not row["expires_at"] else fmt_ts(row["expires_at"])})

LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>登录</title>
<style>body{font-family:sans-serif;max-width:320px;margin:80px auto;background:#F1F5F9}
input{width:100%;padding:10px;margin:6px 0;box-sizing:border-box;border:1px solid #CBD5E1;border-radius:8px}
button{width:100%;padding:10px;background:#F59E0B;color:#fff;border:0;border-radius:8px}</style>
</head><body><h2 style="color:#0F172A">晚更v授权 · 卡密后台</h2>
<form method=post action=/admin/login>
<input name=u placeholder="账号" required><input name=p type=password placeholder="密码" required>
<button>登录</button></form></body></html>"""

@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(): return LOGIN_HTML

@app.post("/admin/login")
async def login_post(u: str = Form(...), p: str = Form(...)):
    if u == ADMIN_USER and p == ADMIN_PASS:
        tok = secrets.token_hex(16); SESSIONS.add(tok)
        r = RedirectResponse("/admin/", status_code=302)
        r.set_cookie("session", tok, httponly=True); return r
    return HTMLResponse("<p>账号或密码错误。<a href=/admin/login>重试</a></p>", status_code=401)

@app.get("/admin/logout")
async def logout(request: Request):
    tok = request.cookies.get("session")
    if tok in SESSIONS: SESSIONS.discard(tok)
    return RedirectResponse("/admin/login")

@app.get("/admin/", response_class=HTMLResponse)
async def admin_index(_=Depends(require_admin)):
    with db() as c:
        rows = c.execute("SELECT * FROM cards ORDER BY id DESC").fetchall()
    trs = []
    for r in rows:
        if r["banned"]: status = '<span style="color:#DC2626;font-weight:bold">已封禁</span>'
        elif r["expires_at"] and r["expires_at"] < int(time.time()): status = '<span style="color:#DC2626">已过期</span>'
        elif r["activated_at"]: status = '<span style="color:#10B981;font-weight:bold">已激活</span>'
        else: status = "未使用"
        expires = "永久" if not r["expires_at"] else fmt_ts(r["expires_at"])
        act = []
        if r["banned"]:
            act.append(f'<form method=post action="/admin/{r["id"]}/unban" style="display:inline"><button>解封</button></form>')
        else:
            act.append(f'<form method=post action="/admin/{r["id"]}/ban" style="display:inline" onsubmit="return confirm(\'确认封禁?\')"><button style="color:#DC2626">封禁</button></form>')
        act.append(f'<form method=post action="/admin/{r["id"]}/delete" style="display:inline" onsubmit="return confirm(\'确认删除?\')"><button style="color:#64748B">删除</button></form>')
        trs.append(f"<tr><td><code>{r['code']}</code></td><td>{r['note'] or ''}</td><td>{status}</td><td style='font-family:monospace;font-size:12px'>{expires}</td><td>{r['device_id'] or ''}</td><td>{fmt_ts(r['last_seen']) if r['last_seen'] else ''}</td><td>{' '.join(act)}</td></tr>")
    dur_opts = "".join(f'<label style="margin-right:10px"><input type=radio name=duration value="{k}" {"checked" if k=="30d" else ""}> {label}</label>' for k,(label,_) in DURATIONS.items())
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>卡密后台</title>
<style>body{{font-family:sans-serif;max-width:1200px;margin:0 auto;padding:20px;background:#F1F5F9;color:#0F172A}}
table{{border-collapse:collapse;width:100%;font-size:13px;background:#fff;border-radius:12px;overflow:hidden}}
td,th{{border:1px solid #E2E8F0;padding:8px 10px;text-align:left}}th{{background:#0F172A;color:#fff}}
button{{padding:5px 12px;margin-right:4px;cursor:pointer;border:0;border-radius:6px;background:#F59E0B;color:#fff}}
.bar{{background:#fff;padding:16px;border-radius:12px;margin:14px 0}}input[type=number]{{width:70px;padding:6px;border:1px solid #CBD5E1;border-radius:6px}}input[type=text]{{padding:6px;border:1px solid #CBD5E1;border-radius:6px}}a{{color:#F59E0B;text-decoration:none}}</style></head><body>
<h2>晚更v授权 · 卡密后台</h2>
<div class=bar><form method=post action="/admin/generate" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
生成 <input type=number name=count value=10 min=1 max=500> 张
<span style="margin-left:10px">时长:</span> {dur_opts}
<span style="margin-left:10px">备注</span><input type=text name=note placeholder="如 张三-月卡">
<button>生成</button></form><a href=/admin/logout>退出</a></div>
<table><tr><th>卡密</th><th>备注</th><th>状态</th><th>到期时间</th><th>设备</th><th>最近在线</th><th>操作</th></tr>
{''.join(trs)}</table></body></html>"""
    return html

@app.post("/admin/generate")
async def generate(count: int = Form(10), note: str = Form(""), duration: str = Form("30d"), _=Depends(require_admin)):
    count = max(1, min(500, count)); now = int(time.time())
    seconds = DURATIONS.get(duration, DURATIONS["30d"])[1]
    expires_at = (now + seconds) if seconds else None
    new = []
    with db() as c:
        for _ in range(count):
            code = gen_code()
            while c.execute("SELECT 1 FROM cards WHERE code=?", (code,)).fetchone(): code = gen_code()
            c.execute("INSERT INTO cards(code,note,created_at,expires_at) VALUES(?,?,?,?)", (code, note, now, expires_at))
            new.append(code)
    label = DURATIONS.get(duration, ("月卡",0))[0]
    exp = "永久" if not expires_at else fmt_ts(expires_at)
    return HTMLResponse(f"<h3>已生成 {count} 张（{label}，到期 {exp}）</h3><pre>" + "\n".join(new) + "</pre><p><a href=/admin/>返回</a></p>")

@app.post("/admin/{cid}/ban")
async def ban(cid: int, _=Depends(require_admin)):
    with db() as c: c.execute("UPDATE cards SET banned=1 WHERE id=?", (cid,))
    return RedirectResponse("/admin/", status_code=302)

@app.post("/admin/{cid}/unban")
async def unban(cid: int, _=Depends(require_admin)):
    with db() as c: c.execute("UPDATE cards SET banned=0, ban_reason='' WHERE id=?", (cid,))
    return RedirectResponse("/admin/", status_code=302)

@app.post("/admin/{cid}/delete")
async def delete(cid: int, _=Depends(require_admin)):
    with db() as c: c.execute("DELETE FROM cards WHERE id=?", (cid,))
    return RedirectResponse("/admin/", status_code=302)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), log_level="info")
