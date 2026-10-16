"""Bulk archive Tencent JCC official-site season/version index and public JSON assets.

This is a first-party web resource, not an SLA-backed public developer API.
Preserve exact mode, season, version, url, and hashes. Do not treat this as
a launch-day or country-wide authoritative patch history.
"""
import concurrent.futures as futures
import argparse
import hashlib
import json
import re
import urllib.error
import urllib.request
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DEST=ROOT/"source"/"official_jcc_bulk"
CDN="https://game.gtimg.cn/images/lol/act/jkzlk/js"
INDEX=CDN+"/config/versiondataconfig.js"
CUTOFF="2026-10-15"
CORE=("herourl","raceurl","joburl")
OPTIONAL=("traiturl","galaxyurl","godurl","adventureurl","missionurl","goopurl","hexurl")
MIN_SAMPLE=10

def download(url, timeout=24):
    if not url.startswith(CDN+"/"):
        raise ValueError("Not the whitelisted official CDN prefix")
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json, */*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        data=r.read()
    obj=json.loads(data)
    if not isinstance(obj,dict) or not isinstance(obj.get("data"),(dict,list)):
        raise ValueError("Unexpected asset structure")
    return obj,hashlib.sha256(data).hexdigest(),data

def order_version(v):
    nums=[int(x) for x in re.findall(r"\d+",str(v))]
    return tuple((nums+[0]*5)[:5])

def rank(entry):
    dt=entry.get("version_start_time","")
    d=(dt[:10] if len(dt)>=10 else "")
    return (1 if d else 0,d,order_version(entry.get("version")),str(entry.get("version")))

def collect_group(key,versions):
    mode,season,name=key
    attempts=[]
    versions=sorted(versions,key=rank,reverse=True)
    best=None
    for ver in versions:
        files={};err={}
        for field in CORE:
            relative=ver.get(field,"")
            if not relative:err[field]="not listed";continue
            url=CDN+relative
            try:
                obj,h,raw=download(url)
                if str(obj.get("setId",obj.get("setid",mode)))!=str(mode):
                    raise ValueError("setId does not match mode")
                files[field]=(obj,h,raw,url)
            except Exception as ex:err[field]=str(ex)[:110]
        attempts.append({"version":ver.get("version"),"ok":list(files),"errors":err})
        if "herourl" in files and "raceurl" in files and "joburl" in files:
            best=(ver,files,err);break
        if best is None and "herourl" in files and "raceurl" in files:
            best=(ver,files,err)
        if len(attempts)>=8:break
    if best is None:
        return {"key":key,"status":"unavailable","attempts":attempts}
    ver,files,errors=best
    for field in OPTIONAL:
        rel=ver.get(field,"")
        if not rel:continue
        try:
            obj,h,raw=download(CDN+rel)
            files[field]=(obj,h,raw,CDN+rel)
        except Exception as ex:errors[field]=str(ex)[:110]
    return {"key":key,"status":"ok" if all(c in files for c in CORE) else "partial",
            "version":ver,"files":files,"errors":errors,"attempts":attempts}

def usable(x):
    h=x[1]
    if str(h.get("showHeroTag",1)) not in ("1","True"):return False
    if str(h.get("heroType","0")) not in ("0",""):return False
    if not h.get("name") or not h.get("skillDesc"):return False
    cost=h.get("price")
    if cost in (None,""):cost=h.get("sellPrice")
    try:cost=float(cost)
    except Exception:return False
    if cost<=0 or cost>10:return False
    return True

def normalize(res):
    mode,season,name=res["key"]
    docs={k:obj for k,(obj,_,_,_) in res["files"].items()}
    heros=docs["herourl"]["data"]
    race=docs["raceurl"]["data"]
    jobs=docs.get("joburl",{}).get("data",{})
    classes={}
    for typ,tbl in [("特质",race),("职业",jobs)]:
        for ident,obj in (tbl.items() if isinstance(tbl,dict) else enumerate(tbl)):
            if isinstance(obj,dict):classes[(typ,str(obj.get('id',ident)))]=obj
    # traiturl 是官网已经展开变量的正式分档配置，可补足race/job中遗漏的描述。
    trait_items=docs.get("traiturl",{}).get("data",{})
    completed={}
    for item in (trait_items.values() if isinstance(trait_items,dict) else trait_items):
        if not isinstance(item,dict):continue
        kind="特质" if str(item.get("type"))=="0" else "职业"
        k=(kind,str(item.get("name","")).strip())
        if not k[1]:continue
        old=completed.get(k,{})
        if len(str(item.get("desc2","")))>len(str(old.get("desc2",""))):completed[k]=item
    traits=[]
    for (typ,ident),t in classes.items():
        traits.append({
            "id":typ+":"+ident,"name":t.get("name",""),"kind":typ,
            "description":t.get("prefix") or completed.get((typ,t.get("name","")) ,{}).get("prefix",""),
            "breakpoints":t.get("desc2") or completed.get((typ,t.get("name","")) ,{}).get("desc2",""),
            "counts":t.get("numList") or completed.get((typ,t.get("name","")) ,{}).get("numList",""),
            "source_id":ident
        })
    groups=defaultdict(list)
    for ident,obj in (heros.items() if isinstance(heros,dict) else enumerate(heros)):
        if not isinstance(obj,dict):continue
        if not usable((ident,obj)):continue
        key=(str(ident)[1:] if len(str(ident))>=5 and str(ident)[0] in "1234" else str(ident))
        groups[key].append((str(ident),obj))
    units=[];issues=[]
    for key,group in groups.items():
        group.sort(key=lambda z:((z[0][0]!='1') if z[0] else True, z[0]))
        _,h=group[0]
        owned=[]
        for typ,field in [("特质","species"),("职业","class")]:
            for ident in str(h.get(field,"")).split("|"):
                if ident in ("","-1","None"):continue
                record=classes.get((typ,ident))
                if record:owned.append(record.get("name",""))
                else:issues.append(f"{key} {field}={ident} unresolved")
        cost=h.get("price") or h.get("sellPrice") or ""
        units.append({
            "id":key,"name":h["name"],"cost":cost,"traits":list(dict.fromkeys(owned)),
            "skill_name":h.get("skillName",""),"skill_description":h.get("skillDesc",""),
            "hp":h.get("initHP",""),"ad":h.get("initAttackDamage",""),
            "armor":h.get("armor",""),"mr":h.get("magicResist",""),
            "attack_speed":h.get("attackSpeed",""),"initial_mana":h.get("initMP",""),
            "max_mana":h.get("maxMP",""),"range":h.get("attackRange",""),
            "star_ids":[k for k,v in group],"hero_paint":h.get("heroPaint","")
        })
    units.sort(key=lambda d:(str(d["cost"]),d["name"],d["id"]))
    traits.sort(key=lambda x:(x["kind"],x["id"]))
    missing=[x["name"] for x in units if not x["traits"]]
    mechanics=[]
    term=re.compile(r"棋盘|格子|地格|位置|后排|前排|部署|召唤|商店|传送门|奇遇|祭坛|星系|选择|放置")
    for t in traits:
        if term.search(t["description"]+" "+t["breakpoints"]):
            mechanics.append({"type":"羁绊相关机制","name":t["name"],"description":t["description"],
                "breakpoints":t["breakpoints"],"source_field":"raceurl" if t["kind"]=="特质" else "joburl"})
    for key in ("galaxyurl","godurl","adventureurl"):
        asset=docs.get(key)
        if not asset:continue
        data=asset.get("data",{})
        if isinstance(data,(dict,list)):
            for ident,item in (data.items() if isinstance(data,dict) else enumerate(data)):
                if not isinstance(item,dict):continue
                title=str(item.get("name") or item.get("title") or "").strip()
                desc=str(item.get("desc") or item.get("description") or "").strip()
                if not title and not desc:continue
                mechanics.append({"type":"赛季机制候选","name":title,"description":desc,
                    "category":str(item.get("category") or ""), "price":item.get("price",""),
                    "breakpoints":"","source_field":key,"id":str(item.get("adventureId") or ident)})
    return {
      "mode":mode,"season":season,"name":name,"version":res["version"].get("version"),
      "start_time":res["version"].get("version_start_time"),"status":res["status"],
      "source_kind":"Tencent JCC official-site CDN; no public developer API guarantee",
      "version_caution":"Snapshot patch only, not necessarily original release patch",
      "asset_urls":{k:v[3] for k,v in res["files"].items()},
      "asset_hashes":{k:v[1] for k,v in res["files"].items()},
      "asset_errors":res["errors"],"units":units,"traits":traits,
      "mechanisms":mechanics,"issues":issues[:100],
      "raw_chess_count":len(heros),"raw_race_count":len(race),"raw_job_count":len(jobs),
      "unmapped_units":missing[:100]
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force',action='store_true',help='revalidate and refetch all season assets')
    args=parser.parse_args()
    DEST.mkdir(parents=True,exist_ok=True)
    req=urllib.request.Request(INDEX,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=35) as r:body=r.read()
    rows=json.loads(body)
    (DEST/"versiondataconfig.json").write_bytes(body)
    grouped=defaultdict(list)
    for row in rows:
        if row.get("mode") in ("0","110") or not row.get("name"):continue
        dt=row.get("version_start_time","")
        if len(dt)>=10 and dt[:10]>CUTOFF:continue
        grouped[(str(row["mode"]),str(row["season"]),str(row["name"]))].append(row)
    print("INDEX",len(rows),"groups",len(grouped),"historical rows",sum(map(len,grouped.values())),flush=True)
    summary=[];counts=Counter()
    oldpath=DEST/'manifest.json'
    old=json.loads(oldpath.read_text(encoding='utf-8')) if oldpath.exists() else {}
    cached={(e['mode'],e['season'],e['name']):e for e in old.get('entries',[])}
    requested={}
    for key,arr in grouped.items():
        prev=cached.get(key)
        latest=sorted(arr,key=rank,reverse=True)[0]
        norm=ROOT/prev['normal_file'] if prev and prev.get('normal_file') else None
        if (not args.force and prev and prev.get('status')=='ok' and norm and norm.exists()
                and (old.get('index_sha256')==hashlib.sha256(body).hexdigest()
                     or latest['version']==prev.get('version'))):
            doc=json.loads(norm.read_text(encoding='utf-8'))
            if doc.get('asset_urls') and doc.get('asset_hashes'):
                summary.append(prev.copy());counts['ok']+=1
                continue
        requested[key]=arr
    print('CACHED',len(summary),'TO_FETCH',len(requested),flush=True)
    with futures.ThreadPoolExecutor(max_workers=7) as pool:
        todo={pool.submit(collect_group,key,arr):key for key,arr in requested.items()}
        for done in futures.as_completed(todo):
            key=todo[done]
            try:res=done.result()
            except Exception as ex:
                summary.append({"mode":key[0],"season":key[1],"name":key[2],"status":"error","reason":str(ex)[:180]})
                print("ERROR",key,str(ex)[:130],flush=True);continue
            record={"mode":key[0],"season":key[1],"name":key[2],"status":res["status"],
                   "attempts":res["attempts"]}
            if res["status"] in ("ok","partial"):
                try:data=normalize(res)
                except Exception as ex:
                    record.update(status='normalize_error',reason=str(ex)[:170]);summary.append(record);counts['normalize_error']+=1
                    print('NORMALIZE_ERROR',key,str(ex)[:140],flush=True);continue
                folder=DEST/("m"+key[0]+"_"+re.sub(r"[^A-Za-z0-9]","",key[1]))
                folder.mkdir(exist_ok=True)
                for field,(_,hashval,raw,url) in res["files"].items():
                    (folder/(field.replace("url","")+".json")).write_bytes(raw)
                norm=folder/"normalized.json"
                norm.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
                record.update({"version":data["version"],"start_time":data["start_time"],
                               "unit_count":len(data["units"]),"trait_count":len(data["traits"]),
                               "mechanism_count":len(data["mechanisms"]),
                               "normal_file":str(norm.relative_to(ROOT)).replace("\\","/"),
                               "asset_count":len(res["files"]),"issues":len(data["issues"]),
                               "unmapped":len(data["unmapped_units"]),"asset_errors":res["errors"]})
                counts[res["status"]]+=1
                print("GROUP",key[0],key[1],key[2],data["version"],res["status"],"units",len(data["units"]),"traits",len(data["traits"]),"mechanisms",len(data["mechanisms"]),"assets",len(res["files"]),flush=True)
            else:
                counts["unavailable"]+=1
                print("UNAVAILABLE",key,flush=True)
            summary.append(record)
    summary.sort(key=lambda r:(int(r["mode"]) if r["mode"].isdigit() else 99999,r["season"],r["name"]))
    manifest={"index_url":INDEX,"index_sha256":hashlib.sha256(body).hexdigest(),
            "retrieved":datetime.now().isoformat(),"cutoff":CUTOFF,
            "total_index_records":len(rows),"selected_groups":len(grouped),"status_counts":dict(counts),
            "entries":summary}
    (DEST/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("DONE",dict(counts),"saved manifest",DEST/"manifest.json",flush=True)

if __name__=="__main__":main()
