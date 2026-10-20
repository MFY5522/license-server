import os, secrets, sqlite3, time
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
DB="data.db"; APP=FastAPI()
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
    c=db(); c.execute("CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE,note TEXT,created_at INTEGER,expires_at INTEGER,activated_at INTEGER,device_id TEXT,banned INTEGER DEFAULT 0,ban_reason TEXT,last_seen INTEGER)"); c.close()
init()
def gen():
    a="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; return "-".join("".join(secrets.choice(a) for _ in range(4)) for _ in range(4))
DUR={"1d":("天卡",86400),"30d":("月卡",2592000),"365d":("年卡",31536000),"forever":("永久",None)}
def ft(t): return time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(t)) if t else ""
@APP.post("/api/activate")
async def activate(req:Request):
    b=await req.json(); code=b.get("code","").strip().upper(); dev=b.get("device_id","")
    c=db(); r=c.execute("SELECT * FROM cards WHERE code=?",(code,)).fetchone()
    if not r: return JSONResponse({"ok":False,"msg":"卡密不存在"})
    if r["banned"]: return JSONResponse({"ok":False,"msg":"已被封禁"})
    if r["expires_at"] and r["expires_at"]<int(time.time()): return JSONResponse({"ok":False,"msg":"已过期"})
    now=int(time.time()); c.execute("UPDATE cards SET activated_at=?,device_id=?,last_seen=? WHERE id=?",(now,dev,now,r["id"])); c.commit()
    return JSONResponse({"ok":True,"msg":"激活成功","expires_text":"永久" if not r["expires_at"] else ft(r["expires_at"])})
@APP.post("/api/verify")
async def verify(req:Request):
    b=await req.json(); code=b.get("code","").strip().upper(); dev=b.get("device_id","")
    c=db(); r=c.execute("SELECT * FROM cards WHERE code=?",(code,)).fetchone()
    if not r: return JSONResponse({"ok":False,"msg":"卡密不存在"})
    if r["banned"]: return JSONResponse({"ok":False,"msg":"已被封禁"})
    if r["expires_at"] and r["expires_at"]<int(time.time()): return JSONResponse({"ok":False,"msg":"已过期"})
    if r["device_id"] and r["device_id"]!=dev: return JSONResponse({"ok":False,"msg":"已在其他设备登录"})
    c.execute("UPDATE cards SET last_seen=? WHERE id=?",(int(time.time()),r["id"])); c.commit()
    return JSONResponse({"ok":True,"expires_text":"永久" if not r["expires_at"] else ft(r["expires_at"])})
@APP.get("/admin/login")
def login(): return HTMLResponse('<form method=post action=/admin/login><input name=u placeholder=账号><input name=p type=password placeholder=密码><button>登录</button></form>')
@APP.post("/admin/login")
def login_post(u:str=Form(...),p:str=Form(...)):
    if u=="admin" and p=="admin123":
        r=RedirectResponse("/admin/",status_code=302); r.set_cookie("sess","ok"); return r
    return HTMLResponse("错误",status_code=401)
@APP.get("/admin/")
def admin(req:Request):
    if req.cookies.get("sess")!="ok": return RedirectResponse("/admin/login")
    c=db(); rows=c.execute("SELECT * FROM cards ORDER BY id DESC").fetchall(); c.close()
    tr="".join(f"<tr><td>{r['code']}</td><td>{r['note']}</td><td>{'已封禁' if r['banned'] else '正常'}</td><td>{'永久' if not r['expires_at'] else ft(r['expires_at'])}</td></tr>" for r in rows)
    return HTMLResponse(f"<h2>卡密后台</h2><form method=post action=/admin/gen>生成<input name=n type=number value=10>张<select name=d><option value=1d>天卡</option><option value=30d>月卡</option><option value=365d>年卡</option><option value=forever>永久</option></select><button>生成</button></form><table border=1><tr><th>卡密</th><th>备注</th><th>状态</th><th>到期</th></tr>{tr}</table>")
@APP.post("/admin/gen")
def gen(n:int=Form(10),d:str=Form("30d")):
    sec={"1d":86400,"30d":2592000,"365d":31536000,"forever":None}.get(d); exp=int(time.time())+sec if sec else None
    c=db(); codes=[]
    for _ in range(n):
        code=gen(); c.execute("INSERT INTO cards(code,created_at,expires_at) VALUES(?,?,?)",(code,int(time.time()),exp)); codes.append(code)
    c.commit(); c.close()
    return HTMLResponse(f"已生成{len(codes)}张<pre>{chr(10).join(codes)}</pre><a href=/admin/>返回</a>")
import uvicorn
if __name__=="__main__": uvicorn.run(APP,host="0.0.0.0",port=8000)
