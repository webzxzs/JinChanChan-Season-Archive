"""批量保留金铲铲官网版本索引的每个补丁快照与逐补丁差异。

不修改四张主表的代表版本选择；该文件只维护独立补丁史。
每个成功补丁保存原始数据（gzip）以及规范化JSON，记录URL/sha256。
"""
import concurrent.futures
import csv
import gzip
import hashlib
import json
import threading
from collections import Counter, defaultdict
from pathlib import Path
from urllib.error import HTTPError

import collect_official_index as base

ROOT=Path(__file__).resolve().parent
DEST=ROOT/"source"/"official_jcc_patch_history"
MANIFEST=DEST/"patch_manifest.json"
DIFF=ROOT/"tables"/"官方逐补丁变化.csv"
FIELDS=("herourl","raceurl","joburl")
lock=threading.Lock()
raw_cache={}
raw_root=DEST/"raw"
def cached_download(url):
    with lock:
        cached=raw_cache.get(url)
    if cached:return cached
    fingerprint=hashlib.sha256(url.encode("utf-8")).hexdigest()
    saved=raw_root/(fingerprint+".json.gz")
    if saved.exists():
        payload=gzip.decompress(saved.read_bytes())
        blob=(json.loads(payload),hashlib.sha256(payload).hexdigest(),payload)
    else:
        obj,digest,payload=base.download(url,timeout=20)
        saved.parent.mkdir(exist_ok=True,parents=True)
        tmp=saved.with_suffix(".tmp")
        with tmp.open("wb") as output:
            with gzip.GzipFile(fileobj=output,mode="wb",compresslevel=6,mtime=0) as z:z.write(payload)
        tmp.replace(saved)
        blob=(obj,digest,payload)
    with lock:
        raw_cache[url]=blob
    return blob

def identity(row):
    return (str(row.get("mode")),str(row.get("season")),str(row.get("version")),str(row.get("name")))
def patch_path(row):
    key="|".join(identity(row))
    return DEST/"normalized"/(hashlib.sha256(key.encode()).hexdigest()+".json.gz")
def save_normalized(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    text=(json.dumps(data,ensure_ascii=False,separators=(",",":"))+"\n").encode("utf-8")
    temp=path.with_suffix(".tmp")
    with temp.open("wb") as f:
        with gzip.GzipFile(fileobj=f,mode="wb",compresslevel=6,mtime=0) as z:z.write(text)
    temp.replace(path)

def load_normalized(path):
    return json.loads(gzip.decompress(path.read_bytes()))

def fetch_patch(row):
    key=identity(row)
    record=dict(mode=key[0],season=key[1],version=key[2],name=key[3],
                version_start_time=row.get("version_start_time",""),source_index=base.INDEX,
                original_urls={},hashes={},errors={})
    files={}
    for field in FIELDS:
        rel=row.get(field)
        if not rel:
            record["errors"][field]="未在官方索引给出";continue
        url=base.CDN+rel
        record["original_urls"][field]=url
        try:
            obj,sha,payload=cached_download(url)
            declared=str(obj.get("setId",obj.get("setid",key[0])))
            if declared!=key[0]:raise ValueError("模式ID不一致")
            files[field]=(obj,sha,payload,url)
            record["hashes"][field]=sha
        except Exception as e:
            record["errors"][field]=str(e)[:180]
    raw=files.get("herourl")
    if not raw:
        record["status"]="missing_chess"
        return record
    if not files.get("raceurl") or not files.get("joburl"):
        record["status"]="partial_core"
        return record
    record["status"]="complete"
    wrap={"key":(key[0],key[1],key[3]),"status":"ok",
          "files":files,"errors":record["errors"],"version":row}
    try:
        norm=base.normalize(wrap)
        record["unit_count"]=len(norm["units"])
        record["trait_count"]=len(norm["traits"])
        record["unmapped_count"]=len(norm["issues"])
        if not norm["traits"]:
            record["status"]="no_traits"
            return record
        save_normalized(patch_path(row),norm)
        record["normalized_path"]=str(patch_path(row).relative_to(ROOT)).replace("\\","/")
    except Exception as e:
        record["status"]="parse_error"
        record["errors"]["normalize"]=str(e)[:180]
    return record

def changes(prev,after,key_field,fields):
    aa={r[key_field]:r for r in prev}
    bb={r[key_field]:r for r in after}
    for key in sorted(set(aa)|set(bb)):
        left=aa.get(key);right=bb.get(key)
        if left is None: yield key,"新增","",json.dumps({f:right.get(f) for f in fields},ensure_ascii=False)
        elif right is None:yield key,"移除",json.dumps({f:left.get(f) for f in fields},ensure_ascii=False),""
        else:
            old={f:left.get(f) for f in fields}
            new={f:right.get(f) for f in fields}
            if old!=new:yield key,"变更",json.dumps(old,ensure_ascii=False),json.dumps(new,ensure_ascii=False)

def build_diffs(rows):
    sets=defaultdict(list)
    for r in rows:
        if r.get("status")!="complete" or not r.get("normalized_path"):continue
        sets[(r["mode"],r["season"],r["name"])].append(r)
    output=[]
    for (mode,season,name),rr in sets.items():
        # 官方无记录日期时按数值版本排序；相同version只比较一次
        rr.sort(key=lambda r:base.rank({"version":r["version"],"version_start_time":r["version_start_time"]}))
        for left,right in zip(rr,rr[1:]):
            a=load_normalized(ROOT/left["normalized_path"])
            b=load_normalized(ROOT/right["normalized_path"])
            for kind,section,fields in [
                ("棋子","units",("name","cost","traits","skill_name","skill_description","hp","ad","armor","mr","attack_speed","initial_mana","max_mana")),
                ("羁绊","traits",("name","description","breakpoints","counts"))]:
                for id_,change,old,new in changes(a[section],b[section],"id",fields):
                    output.append([mode,season,name,left["version"],right["version"],kind,id_,change,old,new,
                                   b["asset_urls"].get("herourl" if kind=="棋子" else "raceurl","")])
    DIFF.parent.mkdir(parents=True,exist_ok=True)
    with DIFF.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f);w.writerow(["mode","赛季","玩法","上一补丁","下一补丁","对象","数据ID","变更类型","旧字段JSON","新字段JSON","官方来源URL"]);w.writerows(output)
    return output

def main():
    DEST.mkdir(parents=True,exist_ok=True)
    index=json.loads((base.DEST/"versiondataconfig.json").read_text(encoding="utf-8"))
    requested=[row for row in index if row.get("mode") not in ("0","110") and row.get("name")
               and (not row.get("version_start_time") or row["version_start_time"][:10]<=base.CUTOFF)]
    result={}
    if MANIFEST.exists():
        old=json.loads(MANIFEST.read_text(encoding="utf-8"))
        for row in old.get("patches",[]):
            # don't re-fetch successful normalized snapshots; only refresh explicit failures
            if row.get("status")=="complete" and row.get("normalized_path") and (ROOT/row["normalized_path"]).exists():
                result[tuple(row[x] for x in ("mode","season","version","name"))]=row
    pending=[r for r in requested if identity(r) not in result]
    print("PATCH INDEX",len(index),"requested",len(requested),"cached",len(result),"fetch",len(pending),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        tasks={pool.submit(fetch_patch,row):row for row in pending}
        completed=0
        for task in concurrent.futures.as_completed(tasks):
            row=tasks[task]
            try:rec=task.result()
            except Exception as e:rec={"mode":row["mode"],"season":row["season"],"version":row["version"],"name":row["name"],"status":"error","errors":{"job":str(e)[:180]}}
            result[identity(row)]=rec
            completed+=1
            if completed%20==0:print("PATCH PROGRESS",completed,"/",len(pending),Counter(x.get("status") for x in result.values()),flush=True)
    output=[result[identity(row)] for row in requested]
    counter=Counter(r["status"] for r in output)
    diff=build_diffs(output)
    info={"source_index":base.INDEX,"cutoff":base.CUTOFF,"total_official_index":len(index),
          "requested_cn_rows":len(requested),"counts":dict(counter),"patches":output,
          "diff_rows":len(diff),"diff_file":str(DIFF.relative_to(ROOT)).replace("\\","/")}
    tmp=MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(info,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(MANIFEST)
    print("PATCH DONE",dict(counter),"diff",len(diff),"saved",MANIFEST,flush=True)

if __name__=="__main__":main()
