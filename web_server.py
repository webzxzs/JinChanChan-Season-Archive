"""本地只读 Web 资料库。数据直接来自现有 tables/ CSV；不需要依赖或数据库。"""
import argparse
import csv
import json
import re
import threading
import time
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "tables"
WEB = ROOT / "web"
TABLES = {"units":"棋子.csv","traits":"羁绊与效果.csv","boards":"棋盘可能效果.csv","seasons":"赛季特色.csv","patches":"官方逐补丁变化.csv"}
ASSETS = ROOT / "source" / "official_jcc_bulk"
MANIFEST = ASSETS / "manifest.json"
FIELDS = {
 "units":("棋子名称","技能名称","技能完整效果","羁绊一","羁绊二","羁绊三","赛季名称","赛季编号"),
 "traits":("羁绊名称","羁绊基础说明","各档人数与效果","包含棋子","赛季名称","赛季编号"),
 "boards":("玩法名称","实际效果","触发条件","玩法类别","赛季名称","赛季编号"),
 "seasons":("赛季名称","核心特色","代表机制","赛季编号"),
 "patches":("赛季编号","玩法","名称","对象","变更类型","数据ID","上一补丁","下一补丁","旧字段JSON","新字段JSON"),
}
NAMES={"units":"棋子名称","traits":"羁绊名称","boards":"玩法名称","seasons":"赛季名称","patches":"名称"}
STATIC={"/":"gallery.html","/index.html":"gallery.html","/gallery.css":"gallery.css","/gallery.js":"gallery.js"}

def natural(v):
 return tuple((0,int(x)) if x.isdigit() else (1,x.casefold()) for x in re.split(r"(\d+)",v))

def first(params,key,limit=120):
 return str(params.get(key,[""])[0])[:limit]

def number(s,otherwise):
 try:return int(s)
 except (TypeError,ValueError):return otherwise

def patch_row(row):
 """把补丁前后字典展开为有来源的字段差异；不推定这些都是平衡变化。"""
 before=json.loads(row.get("旧字段JSON") or "{}")
 after=json.loads(row.get("新字段JSON") or "{}")
 if not isinstance(before,dict):before={"原始内容":before}
 if not isinstance(after,dict):after={"原始内容":after}
 diff=[]
 for key in sorted(before.keys()|after.keys()):
  if before.get(key)!=after.get(key):
   diff.append({"字段":key,"旧值":str(before.get(key,"")),"新值":str(after.get(key,""))})
 mode=row.get("mode","");season=row.get("赛季","");game=row.get("玩法","")
 return {"赛季编号":f"国服·{game}｜{season}／模式{mode}","赛季名称":game,"配置版本":row.get("下一补丁",""),
  "上一补丁":row.get("上一补丁",""),"下一补丁":row.get("下一补丁",""),
  "对象":row.get("对象",""),"名称":str(after.get("name") or before.get("name") or row.get("数据ID","")),
  "数据ID":row.get("数据ID",""),"变更类型":row.get("变更类型",""),
  "核验状态":"官方字段变化（性质待判）","来源网址":row.get("官方来源URL",""),
  "差异":diff,"字段全文":row.get("旧字段JSON","")+" "+row.get("新字段JSON","")}

def official_media(use_cached=True):
 """Index the original first-party portrait/trait picture fields by canonical record ID."""
 cache = ROOT / "data" / "site_index.json"
 if use_cached and cache.exists():
  payload = json.loads(cache.read_text(encoding="utf-8"))
  return payload["media"], payload["catalog"]
 media = {}
 catalog = []
 if MANIFEST.exists():
  manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
  for entry in manifest.get("entries", []):
   mode,season = str(entry.get("mode","")), str(entry.get("season",""))
   name = entry.get("name","")
   ref = f"国服·{name}｜{season}／模式{mode}"
   catalog.append({"ref":ref,"name":name,"season":season,"mode":mode,
      "version":entry.get("version",""),"date":entry.get("start_time",""),
      "status":entry.get("status",""),"units":entry.get("unit_count",0),
      "traits":entry.get("trait_count",0),"kind":"indexed"})
   file = entry.get("normal_file")
   if not file:continue
   folder = (ROOT/file).parent
   norm = json.loads((folder/"normalized.json").read_text(encoding="utf-8"))
   hero_path = folder/"hero.json"
   if hero_path.exists():
    raw = json.loads(hero_path.read_text(encoding="utf-8")).get("data",{})
    if isinstance(raw,list):raw={str(h.get("id","")):h for h in raw if isinstance(h,dict)}
    for unit in norm.get("units", []):
     hero = next((raw.get(str(k)) for k in unit.get("star_ids",[]) if str(k) in raw),None)
     if hero and hero.get("picture"):
      media[f"IDX:{mode}:{season}:{unit['id']}"] = {"头像":hero["picture"],"技能图":hero.get("skillIcon","")}
   for file_name,kind in (("race.json","特质"),("job.json","职业")):
    target=folder/file_name
    if not target.exists():continue
    collection=json.loads(target.read_text(encoding="utf-8")).get("data",{})
    for row in (collection.values() if isinstance(collection,dict) else collection):
     if not isinstance(row,dict):continue
     if row.get("picture"):
      media[f"IDX:{mode}:{season}:{kind}:{row['id']}"]={"头像":row["picture"]}
 legacy=ROOT/"source"/"official_jcc"/"config220224_full.json"
 if legacy.exists():
  doc=json.loads(legacy.read_text(encoding="utf-8"))
  for hero in doc.get("HeroConfig",{}).values():
   mode=str(hero.get("setId",""))
   if mode in ("1","4","5","6") and hero.get("picture"):
    url=hero["picture"]
    icon=hero.get("skillIcon","")
    media[f"JCC{mode}:{hero.get('group','')}"]={
      "头像":url if url.startswith("https://") else "https://game.gtimg.cn/images/jk/jkimg/"+url,
      "技能图":icon if icon.startswith("https://") else ("https://game.gtimg.cn/images/jk/jkimg/"+icon if icon else "")}
  for sec,kind in (("SpecConfig","特质"),("ClassConfig","职业")):
   for row in doc.get(sec,{}).values():
    mode=str(row.get("setId",""))
    if mode not in ("1","4","5","6") or not row.get("picture"):continue
    media[f"JCC{mode}:{kind}:{row.get('id','')}"]={
      "头像":"https://game.gtimg.cn/images/jk/jkimg/"+row["picture"]}
 return media,catalog

class Archive:
 def __init__(self,directory=DATA):
  self.directory=Path(directory);self.lock=threading.RLock();self.stamps=None;self.rows={};self.seasons=[]
  self.media,self.catalog=official_media()
  self.refresh(True)
 def refresh(self,force=False):
  stamps=tuple((k,(self.directory/v).stat().st_mtime_ns) for k,v in TABLES.items())
  if not force and stamps==self.stamps:return
  with self.lock:
   if not force and stamps==self.stamps:return
   rows={}
   for key,name in TABLES.items():
    with (self.directory/name).open(encoding="utf-8-sig",newline="") as f:
     values=list(csv.DictReader(f))
     rows[key]=[patch_row(x) for x in values] if key=="patches" else values
   for key,id_field in (("units","棋子ID"),("traits","羁绊ID")):
    for record in rows[key]:
     record.update(self.media.get(record.get(id_field,""),{}))
   self.rows=rows
   self.seasons=sorted({x.get("赛季编号","") for rs in rows.values() for x in rs if x.get("赛季编号")},key=natural)
   self.stamps=stamps
 def summary(self,season=""):
  self.refresh()
  with self.lock:
   filtered={k:[r for r in v if not season or r.get("赛季编号")==season] for k,v in self.rows.items()}
   status=Counter((r.get("核验状态") or "未知") for rs in filtered.values() for r in rs)
   return {"counts":{k:len(v) for k,v in filtered.items()},"seasons":self.seasons,"states":dict(status),"scope":season}
 def catalog_data(self):
  self.refresh()
  with self.lock:
   indexed={x["ref"] for x in self.catalog}
   extra=[{"ref":key,"name":key.replace("国服","").strip("·："),"season":"",
      "version":"","date":"","status":"historical","kind":"historical"}
      for key in self.seasons if key not in indexed]
   return {"items":self.catalog+extra,"total":len(self.catalog)+len(extra)}
 def search(self,key,params):
  if key not in TABLES:raise ValueError("Unknown type")
  self.refresh()
  season=first(params,"season",180);q=first(params,"q").strip().casefold()
  status=first(params,"status",80);cost=first(params,"cost",8);category=first(params,"category",100);sort=first(params,"sort",32)
  version=first(params,"version",100);trait=first(params,"trait",100)
  page=max(1,min(100000,number(first(params,"page"),1)))
  limit=max(1,min(60,number(first(params,"limit"),24)))
  with self.lock:
   items=[]
   for r in self.rows[key]:
    if season and r.get("赛季编号")!=season:continue
    if status and r.get("核验状态")!=status:continue
    if version and r.get("配置版本")!=version:continue
    if key=="units" and cost and not (number(r.get("费用"),0)>=6 if cost=="6+" else r.get("费用")==cost):continue
    if key=="units" and trait and trait not in (r.get("羁绊一"),r.get("羁绊二"),r.get("羁绊三")):continue
    if key=="boards" and category and r.get("玩法类别")!=category:continue
    if key=="patches" and category and r.get("对象")!=category:continue
    if q and not any(q in r.get(f,"").casefold() for f in FIELDS[key]):continue
    items.append(r)
   if sort=="cost" and key=="units":
    items.sort(key=lambda r:(number(r.get("费用"),99),natural(r.get("棋子名称",""))))
   elif sort=="season":items.sort(key=lambda r:natural(r.get("赛季编号","")))
   else:items.sort(key=lambda r:natural(r.get(NAMES[key],"")))
   start=(page-1)*limit
   return {"items":items[start:start+limit],"total":len(items),"page":page,"limit":limit,
      "pages":(len(items)+limit-1)//limit,
      "statuses":sorted({r.get("核验状态","") for r in self.rows[key] if r.get("核验状态")}),
      "versions":sorted({r.get("配置版本","") for r in self.rows[key] if r.get("配置版本") and (not season or r.get("赛季编号")==season)},key=natural),
      "trait_options":sorted({r.get(f,"") for r in self.rows["units"] if not season or r.get("赛季编号")==season for f in ("羁绊一","羁绊二","羁绊三") if r.get(f)},key=natural) if key=="units" else [],
      "categories":sorted({r.get("玩法类别" if key=="boards" else "对象","") for r in self.rows[key] if r.get("玩法类别" if key=="boards" else "对象")}) if key in ("boards","patches") else []}

class Handler(BaseHTTPRequestHandler):
 archive=None
 def do_GET(self):
  route=urlsplit(self.path);path=route.path;params=parse_qs(route.query,keep_blank_values=True)
  try:
   if path=="/api/health":return self.respond({"ok":True,"read_only":True})
   if path=="/api/summary":return self.respond(self.archive.summary(first(params,"season",180)))
   if path=="/api/catalog":return self.respond(self.archive.catalog_data())
   if path.startswith("/api/records/"):return self.respond(self.archive.search(path.split("/")[-1],params))
   if path in STATIC:
    name=STATIC[path];body=(WEB/name).read_bytes()
    mime="text/html" if name.endswith(".html") else ("text/css" if name.endswith(".css") else "text/javascript")
    self.send_response(200);self.send_header("Content-Type",mime+"; charset=utf-8")
    self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-cache")
    self.send_header("X-Content-Type-Options","nosniff")
    self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://game.gtimg.cn; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
    self.end_headers();self.wfile.write(body);return
   self.respond({"error":"Not found"},404)
  except ValueError as ex:self.respond({"error":str(ex)},400)
  except OSError:self.respond({"error":"CSV unavailable. Run research.py build."},503)
  except Exception:self.respond({"error":"Internal error"},500)
 def do_POST(self):self.respond({"error":"Read-only viewer"},405)
 def respond(self,obj,status=200):
  body=json.dumps(obj,ensure_ascii=False,separators=(",",":")).encode("utf-8")
  self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8")
  self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-store")
  self.send_header("X-Content-Type-Options","nosniff")
  self.end_headers();self.wfile.write(body)
 def log_message(self,fmt,*args):
  # pythonw.exe runs without sys.stderr. BaseHTTPRequestHandler's default
  # request logger would raise during send_response, dropping static pages.
  # Keep the read-only background service independent of a terminal.
  return

def create_server(host="127.0.0.1",port=8765,directory=DATA):
 archive=Archive(directory)
 class LocalHandler(Handler):pass
 LocalHandler.archive=archive
 return ThreadingHTTPServer((host,port),LocalHandler)

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument("--port",type=int,default=8765)
 parser.add_argument("--no-browser",action="store_true")
 args=parser.parse_args()
 server=create_server(port=args.port)
 url=f"http://127.0.0.1:{server.server_port}"
 print("金铲铲 Web 资料库："+url,flush=True)
 print("关闭此窗口结束本地服务；更新CSV后刷新网页即可。",flush=True)
 if not args.no_browser:
  import webbrowser
  webbrowser.open(url)
 try:server.serve_forever(poll_interval=0.2)
 except KeyboardInterrupt:pass
 finally:server.server_close()

if __name__=="__main__":main()
