"""逐个赛季采集金铲铲官网托管的历史游戏配置（已验证mode=1/5/6/4）。

官方静态文件是第一方资源，不是官方承诺稳定/长期支持的公开开发者API。
"""
import hashlib
import argparse
import json
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"source"/"official_jcc"
URL="https://game.gtimg.cn/images/jk/jkimg/config220224.json"
VERSION="config220224"

def collect(mode=1):
    if mode not in (1,5,6,4):
        raise ValueError("本配置只验收国服 mode=1/5/6/4")
    OUT.mkdir(parents=True,exist_ok=True)
    rawfile=OUT/(VERSION+"_full.json")
    if rawfile.exists():
        raw=rawfile.read_bytes()
    else:
        request=urllib.request.Request(URL,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
        with urllib.request.urlopen(request,timeout=45) as result:
            raw=result.read()
    obj=json.loads(raw)
    if not all(k in obj for k in ("HeroConfig","SpecConfig","ClassConfig")):
        raise ValueError("官方数据缺少预期字段，不覆盖已有资料")
    heroes={k:v for k,v in obj["HeroConfig"].items() if v.get("setId")==str(mode)}
    kinds=[
        ("职业","ClassConfig","class"),
        ("特质","SpecConfig","species"),
    ]
    lookup={}
    traits=[]
    for category,section,key in kinds:
        values={k:v for k,v in obj[section].items() if v.get("setId")==str(mode)}
        lookup[category]=values
        for ident,t in values.items():
            traits.append({
                "id":category+":"+ident,
                "name":t["name"],"category":category,
                "prefix":t.get("prefix",""),"breakpoints":t.get("desc2",""),
                "numList":t.get("numList",""),"raw_values":t.get("values",""),
                "source_id":t.get("id",""),"source_key":ident,
            })
    grouped={}
    for key,h in heroes.items():grouped.setdefault(h["group"],[]).append((key,h))
    result=[]
    for group,stars in grouped.items():
        stars.sort(key=lambda item:(0 if item[0]==group else 1, item[0]))
        key,base=stars[0]
        owned=[]
        for category,section,field in kinds:
            for ident in base.get(field,"").split("|"):
                if ident in ("","-1"):continue  # 特殊可解锁弈子可没有普通职业
                if ident not in lookup[category]:
                    raise ValueError("无法映射羁绊 "+base["name"]+" "+field+"="+ident)
                owned.append(lookup[category][ident]["name"])
        result.append({
            "id":group, "name":base["name"], "cost":base.get("price"),
            "traits":owned, "skill_name":base.get("skillName",""),
            "skill_description":base.get("skillDesc",""),
            "skill_values":base.get("skillValueDesc",""),
            "hp":base.get("initHP",""),"ad":base.get("initAttackDamage",""),
            "armor":base.get("armor",""),"mr":base.get("magicResist",""),
            "attack_speed":base.get("attackSpeed",""),"initial_mana":base.get("initMP",""),
            "max_mana":base.get("maxMP",""),
            "attack_range":base.get("attackRange",""),
            "star_config_ids":[ident for ident,_ in stars],
            "hero_type":base.get("heroType",""),
        })
    result.sort(key=lambda x:(int(x["cost"]),x["id"]))
    traits.sort(key=lambda x:(x["category"],x["source_key"]))
    required={1:(174,58,25),5:(171,57,27),6:(180,60,28),4:(174,58,26)}[mode]
    if (len(heroes),len(result),len(traits))!=required:
        raise ValueError(f"历史官方模式{mode}数量异常，拒绝提交")
    if any(not h["name"] or not h["skill_description"] for h in result):
        raise ValueError("棋子字段不完整")
    snapshot={
        "game":"金铲铲之战","mode":{1:"时空裂痕",5:"英雄之黎明",6:"双城传说",4:"福星临门"}[mode],"mode_id":str(mode),
        "config_version":VERSION,"source_kind":"腾讯官网公开的第一方静态配置，非正式公开开发者API",
        "source_url":URL,"raw_sha256":hashlib.sha256(raw).hexdigest(),
        "version_caution":"文件名config220224不能证明是某赛季首发版，效果只归属于该配置快照",
        "hero_config_rows":len(heroes),"units":result,"traits":traits,
    }
    normfile=OUT/(f"mode{mode}_"+VERSION+".json")
    if rawfile.exists() and hashlib.sha256(rawfile.read_bytes()).hexdigest()!=snapshot["raw_sha256"]:
        raise ValueError("官方URL内容已变化，先人工确认是否保存另一份历史快照")
    if not rawfile.exists():rawfile.write_bytes(raw)
    content=json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n"
    if not normfile.exists() or normfile.read_text(encoding="utf-8")!=content:
        tmp=normfile.with_suffix(".tmp")
        tmp.write_text(content,encoding="utf-8")
        tmp.replace(normfile)
    print("官方原文",rawfile,"bytes",len(raw),"sha256",snapshot["raw_sha256"][:16])
    print(snapshot["mode"],len(result),"个棋子",len(traits),"羁绊","逐星配置",len(heroes))
    print("example",[(x["name"],x["cost"],"/".join(x["traits"])) for x in result[:4]])

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode",type=int,choices=(1,5,6,4),default=1)
    collect(parser.parse_args().mode)
