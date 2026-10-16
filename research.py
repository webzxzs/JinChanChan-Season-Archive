"""金铲铲长期资料研究管线：快照 -> 候选数据 -> 人工核实 -> 五张表。

只依赖 Python 标准库。不会自动把国际服资料认证为金铲铲国服事实。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
TABLES = ROOT / "tables"
NOTES = ROOT / "research_notes.json"
SHEETS = ("棋子", "羁绊与效果", "棋盘可能效果", "赛季特色")

HEADERS = {
    "棋子": ["赛季","赛季名","棋子","英文/内部名","费用","羁绊1","羁绊2","羁绊3","羁绊4","技能","技能效果","生命值","攻击力","护甲","魔抗","攻速","初始法力","最大法力","定位","采样版本","来源URL","校验说明","数据ID","审核状态","核验证据URL"],
    "羁绊与效果": ["赛季","赛季名","羁绊","内部/英文名","羁绊描述","分档效果数值","对应棋子","采样版本","来源URL","备注","数据ID","审核状态","核验证据URL"],
    "棋盘可能效果": ["赛季","赛季名","玩法类型","机制或地格效果","触发条件","作用范围","分类","来源URL","核实说明","数据ID","审核状态","核验证据URL"],
    "赛季特色": ["赛季","中文主题","国际主题","版本适用性","核心设计特色","代表机制","数据版本","棋子行数","羁绊行数","数据质量","来源URL","审核状态","核验证据URL"],
}
# 明显不属于独立可购买棋子的单位；其他不确定单位保留但标注待核验。
NON_SHOP = {"纹章之书","成装锻造器","基础装备锻造器","神器装备锻造器",
            "光明装备锻造器","奥恩装备锻造器","目标假人","训练假人",
            "魔像","虚空生物","峡谷迅捷蟹","河蟹","小型假人","练习假人",
            "魔沼蛙","暗影狼","苍蓝哨戒","绯红树怪","远古石甲虫",
            "苍蓝雕纹魔像","绯红印记树怪","深红锋喙鸟"}

def tidy(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", str(value)))).strip()

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def source_path(season: int) -> Path:
    return SOURCE / f"set{season:02}.json"

def load():
    notes = json.loads(NOTES.read_text(encoding="utf-8"))
    return notes, {int(n): json.loads(source_path(int(n)).read_text(encoding="utf-8"))
                   for n in notes["seasons"] if source_path(int(n)).exists()}

def value(obj, *keys):
    for key in keys:
        if obj.get(key) is not None:
            return obj[key]
    return ""

def review(notes, season, kind, key):
    return notes.get("reviews", {}).get(f"{season}|{kind}|{key}", {}).get("status", "待国服核验")

def review_source(notes, season, kind, key):
    return notes.get("reviews", {}).get(f"{season}|{kind}|{key}", {}).get("evidence_url", "")

def playable(c, known):
    name = tidy(c.get("name"))
    api = str(c.get("apiName", "")).lower()
    cost = c.get("cost")
    if not isinstance(cost, (int,float)) or not (0 < cost <= 10):
        return False
    if not name or name in NON_SHOP or name.endswith(("假人","锻造器")):
        return False
    if c.get("isSpawn") or any(x in api for x in ("dummy","testunit","targetdummy","carousel","item_")):
        return False
    return any(tidy(t) in known for t in c.get("traits", []))

def effects(t):
    result=[]
    for e in t.get("effects", []):
        lo=e.get("minUnits", "?")
        hi=e.get("maxUnits")
        level = str(lo) if not hi or hi==lo else f"{lo}～{hi}"
        vals = e.get("variables") or {}
        detail="; ".join(f"{k}={round(v,4) if isinstance(v,float) else v}" for k,v in sorted(vals.items()))
        result.append(f"{level}人：{detail}" if detail else f"{level}人")
    return " | ".join(result)

def append_official_jcc(tables):
    """逐个模式导出腾讯官网静态快照，国际服原始赛季不会被覆盖。"""
    for mode,label,title,expected,origin in [
        (1,"国服S1·官方","时空裂痕",(58,25),"TFT S1仅为原型"),
        (5,"国服S5.5·官方","英雄之黎明",(57,27),"TFT S5.5，不是S5"),
        (6,"国服S6·官方","双城传说",(60,28),"TFT S6"),
        (4,"国服·福星临门·官方","福星临门",(58,26),"2022年1月的限时活动玩法")]: 
        path=SOURCE/"official_jcc"/f"mode{mode}_config220224.json"
        if not path.exists():continue
        snap=json.loads(path.read_text(encoding="utf-8"))
        if snap.get("mode_id")!=str(mode) or (len(snap.get("units",[])),len(snap.get("traits",[])))!=expected:
            raise ValueError(f"腾讯官网模式{mode}配置不完整，拒绝导出")
        source=snap["source_url"]
        version=snap["config_version"]
        for unit in snap["units"]:
            tables["棋子"].append([
                label,title,unit["name"],unit["id"],unit["cost"],
                *(unit["traits"]+[""]*4)[:4],unit["skill_name"],unit["skill_description"],
                unit["hp"],unit["ad"],unit["armor"],unit["mr"],unit["attack_speed"],
                unit["initial_mana"],unit["max_mana"],"",version,source,
                "腾讯官网第一方静态配置；仅核实config220224，不能外推至该玩法首发",
                f"JCC{mode}:"+unit["id"],"已核实",source])
        for trait in snap["traits"]:
            members=sorted({u["name"] for u in snap["units"] if trait["name"] in u["traits"]})
            tables["羁绊与效果"].append([
                label,title,trait["name"],trait["category"]+":"+trait["source_key"],
                trait["prefix"],trait["breakpoints"],"; ".join(members),
                version,source,"腾讯官网原始描述及各人数档位；只对应config220224",
                f"JCC{mode}:"+trait["id"],"已核实",source])
        tables["赛季特色"].append([
            label,title,origin,"腾讯官网第一方配置config220224，不是2021首发参数",
            f"包含{expected[0]}名棋子及{expected[1]}种羁绊，技能/费用/数值/档位来自国服官方文件",
            "棋盘位置效果与赛季特殊机制仍待独立官方资料",
            version,*expected,"已核实该配置内容；历史补丁与棋盘效果未完整覆盖",
            source,"已核实",source])


def append_bulk_official(tables):
    """Add indexed JCC seasons and return accurate quality/coverage totals."""
    root=SOURCE/"official_jcc_bulk"
    manifest_path=root/"manifest.json"
    if not manifest_path.exists():return {"available":0,"missing":0,"incomplete":0}
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    counts={"available":0,"missing":0,"incomplete":0,"units":0,"traits":0,"mechanisms":0}
    for entry in manifest["entries"]:
        mode,season,name=entry["mode"],entry["season"],entry["name"]
        label=f"国服·{name}｜{season}／模式{mode}"
        meta=f"腾讯官网资料库 {season}（mode={mode}）"
        if entry["status"] not in ("ok","partial") or entry.get("trait_count",0)==0:
            counts["incomplete" if entry.get("unit_count") else "missing"]+=1
            tables["赛季特色"].append([label,name,meta,"官方索引有记录但关键数据未全部取得",
                "该版本尚不能核验完整棋子/羁绊，不应视为该赛季完成",entry["status"],
                entry.get("version",""),entry.get("unit_count",""),entry.get("trait_count",""),
                "数据缺口；请查看官方索引清单",manifest["index_url"],"待补齐",manifest["index_url"]])
            continue
        snapshot=json.loads((ROOT/entry["normal_file"]).read_text(encoding="utf-8"))
        if snapshot["mode"]!=mode or snapshot["season"]!=season:
            raise ValueError(f"Official index cross-season leakage: {mode} {season}")
        version=snapshot["version"]
        urls=snapshot["asset_urls"]
        issues=set(snapshot.get("unmapped_units",[]))
        counts["available"]+=1
        counts["units"]+=len(snapshot["units"])
        counts["traits"]+=len(snapshot["traits"])
        by_trait={}
        for ch in snapshot["units"]:
            for t in ch["traits"]:by_trait.setdefault(t,set()).add(ch["name"])
            no_primary=not any(str(i).startswith("1") for i in ch.get("star_ids",[]))
            status=("缺可见一星配置/商店可购性待核" if no_primary else
                    "待核实羁绊映射" if ch["name"] in issues else "已取得官网棋子配置")
            tables["棋子"].append([
                label,name,ch["name"],ch["id"],ch["cost"],*(ch["traits"]+[""]*4)[:4],
                ch["skill_name"],ch["skill_description"],ch["hp"],ch["ad"],ch["armor"],ch["mr"],
                ch["attack_speed"],ch["initial_mana"],ch["max_mana"],"",
                version,urls.get("herourl",""),"腾讯官网原始候选配置；缺可见一星者并非已证实可在商店购买；具体补丁见来源",
                f"IDX:{mode}:{season}:{ch['id']}",status,urls.get("herourl","")])
        for tr in snapshot["traits"]:
            source=urls.get("raceurl" if tr["kind"]=="特质" else "joburl","")
            tables["羁绊与效果"].append([
                label,name,tr["name"],tr["id"],tr["description"],tr["breakpoints"],
                "; ".join(sorted(by_trait.get(tr["name"],set()))),
                version,source,"官方数据按羁绊人数分档；本版本并不代表全部历史补丁",
                f"IDX:{mode}:{season}:{tr['id']}","已核实该官网版本",source])
        board_categories=set()
        for k,m in enumerate(snapshot.get("mechanisms",[])):
            field=m["source_field"]
            source=urls.get(field,"")
            if not source:continue
            detail=(m.get("description","")+"；"+m.get("breakpoints","")).strip("；")
            if not detail:continue
            if field=="galaxyurl":
                kind="星系/全局环境规则"
                trigger="对局开始的环境/星系规则，具体概率待核"
                scope="全局经济/商店/战斗规则（不一定是格子）"
            elif field=="adventureurl":
                if name=="画之灵":
                    kind="画之灵奇遇（非地格）"
                    trigger="奇遇发生时，具体回合由版本规则决定"
                    scope="奇遇奖励或全局规则"
                elif name=="自然之力":
                    kind="自然仙灵效果（非地格）"
                    trigger="自然仙灵获得或触发时"
                    scope="经济、战斗或其他自然仙灵效果"
                else:
                    subtype=m.get("category") or "其他"
                    kind="法杖/一次性效果·"+subtype
                    price=m.get("price")
                    trigger=("商店购买或使用；记录价格："+str(price)+"金币" if price not in (None,"") else
                             "通过赛季事件或商店使用，具体条件待核")
                    scope="经济、战斗及一次性道具效果（不等于棋盘地格）"
            elif field in ("raceurl","joburl"):
                # Only board-relevant traits: discard generic summons and income descriptions.
                if not re.search(r"棋盘|棋格|地格|站位|前[两2]?排|后[两2]?排|邻格|相邻|部署|放置|格子|位置|战斗开始时.{0,12}格",detail):
                    continue
                kind="棋盘站位相关羁绊"
                trigger="激活该羁绊后按人数及站位生效"
                scope="战斗位置/特殊格；需区分战斗前后"
            else:
                continue
            board_categories.add(kind)
            tables["棋盘可能效果"].append([
                label,name,m.get("name") or ("奇遇/事件#"+str(m.get("id",k))),detail,
                trigger,scope,kind,source,
                "腾讯官网静态配置中的分类候选；暂未证明这是独立可摆放地格或必定出现的机制",
                f"IDX:{mode}:{season}:mechanic:{field}:{m.get('id',k)}",
                "待核实玩法边界",source])
            counts["mechanisms"]+=1
        headline="、".join(sorted(board_categories))
        tables["赛季特色"].append([
            label,name,meta,"腾讯官网所列历史版本，不等于赛季首发版本",
            f"已抽取{len(snapshot['units'])}名棋子、{len(snapshot['traits'])}种羁绊；留存技能、属性、分档与来源",
            headline or "赛季特性详见来源及机制候选",
            version,len(snapshot["units"]),len(snapshot["traits"]),
            "该版本数据已取得；玩法/棋盘候选未逐项人工核验",
            manifest["index_url"],"官网数据已取得",urls.get("herourl","")])
    return counts

def compile_tables(notes, snapshots):
    result={s:[] for s in SHEETS}
    counted={}
    for season in sorted(map(int,notes["seasons"])):
        meta=notes["seasons"][str(season)]
        prefix=f"S{season}"
        if season not in snapshots:
            counted[season]={"error":"尚未取得快照"}
            continue
        snap=snapshots[season]
        url=snap["source"]
        version=snap["version"]
        chars=[]; traits=[]; membership={}
        if season<=2:
            for c in snap["champions"]:
                key=c.get("english") or c["name"]
                flags=review(notes,season,"unit",key)
                tr=c.get("traits",[])
                chars.append([prefix,meta["cn"],c["name"],key,c.get("cost",""),*(tr+[""]*4)[:4],
                  c.get("ability_name",""),tidy(c.get("ability_desc")),*[""]*8,
                  version,c.get("url",url),"历史英文资料，中文归属待核验",key,flags,review_source(notes,season,"unit",key)])
            for t in snap["traits"]:
                key=t.get("english") or t["name"]
                mem=[c["name"] for c in snap["champions"] if t["name"] in c.get("traits",[])]
                traits.append([prefix,meta["cn"],t["name"],key,tidy(t.get("desc")),tidy(t.get("effect")),
                  "; ".join(mem),version,t.get("url",url),"英文参考网站，可能含未知数值",key,review(notes,season,"trait",key),review_source(notes,season,"trait",key)])
        else:
            raw=snap["setData"]
            defs=raw.get("traits", [])
            known={tidy(t.get("name")) for t in defs}
            units=[c for c in raw.get("champions",[]) if playable(c,known)]
            for c in units:
                cid=c.get("apiName") or c.get("characterName") or c["name"]
                tr=[tidy(t) for t in c.get("traits",[]) if tidy(t) in known]
                for name in tr: membership.setdefault(name,[]).append(tidy(c["name"]))
                stats=c.get("stats") or {}; spell=c.get("ability") or {}
                flags=review(notes,season,"unit",cid)
                if season==18 and tidy(c["name"]).startswith("拉克丝 (") and flags=="待国服核验":
                    flags="疑似形态而非独立棋子"
                chars.append([prefix,meta["cn"],tidy(c["name"]),tidy(c.get("characterName")),
                  c.get("cost",""),*(tr+[""]*4)[:4],tidy(spell.get("name")),tidy(spell.get("desc")),
                  value(stats,"hp","health"),value(stats,"damage"),value(stats,"armor"),
                  value(stats,"magicResist"),value(stats,"attackSpeed"),value(stats,"initialMana"),
                  value(stats,"mana"),tidy(c.get("role")),version,url,
                  "云顶原始客户端候选；技能描述可能含@变量@",cid,flags,review_source(notes,season,"unit",cid)])
            for t in defs:
                name=tidy(t.get("name"))
                if name not in membership:
                    continue
                key=t.get("apiName") or name
                traits.append([prefix,meta["cn"],name,key,tidy(t.get("desc")),effects(t),
                    "; ".join(sorted(set(membership[name]))),version,url,
                    "原始变量未被自动代入，不视为已验证国服效果",key,
                    review(notes,season,"trait",key),review_source(notes,season,"trait",key)])
        result["棋子"].extend(chars)
        result["羁绊与效果"].extend(traits)
        counted[season]={"units":len(chars),"traits":len(traits),"version":version}
        for i,m in enumerate(notes.get("mechanisms",[])):
            if m["season"]!=season:continue
            key=m.get("id") or f"{season}|{m['name']}"
            result["棋盘可能效果"].append([prefix,meta["cn"],m["name"],m["effect"],
                m.get("trigger",""),m.get("scope",""),
                "明确地格" if "地格" in m["name"] or "元素格" in m["name"] else "非固定地格/赛季机制",
                m.get("source_url",""),m.get("variant",""),key,
                m.get("review","待国服核验"),m.get("evidence_url","")])
        result["赛季特色"].append([prefix,meta["cn"],meta["en"],
            "TFT 原始资料≠金铲铲国服版本",meta.get("feature",""),
            "; ".join(m["name"] for m in notes.get("mechanisms",[]) if m["season"]==season),
            version,len(chars),len(traits),"候选资料，需核对官方赛季规则",url,
            meta.get("review","待国服核验"),"; ".join(meta.get("sources",[]))])
    # 已查证的国服专题与TFT原始快照并存，不反向覆盖来源数据。
    national = notes.get("national_research", {})
    if national:
        # 官网配置优先。旧版十个别名及五条不完整羁绊仍保存在研究笔记，
        # 但不在同一张Excel重复列成十名“国服棋子”。
        if not (SOURCE/"official_jcc"/"mode1_config220224.json").exists():
            source = national.get("s1_names_source") or "https://weibo.com/ttarticle/p/show?id=2309404674858704568661"
            for english, chinese in national.get("s1_names", {}).items():
                row_id = "CN2021-S1:" + english
                result["棋子"].append([
                    "国服S1·2021", "时空裂痕", chinese, english, "",
                    *[""] * 4, "", "", *[""] * 8, "2021首发版本",
                    source, "仅棋子国服称谓有同期历史资料；费用/羁绊/技能未由国服来源验证",
                    row_id, "待国服核验", ""])
            for item in national.get("s1_traits", []):
                row_id = "CN2021-S1:" + item["cn"]
                link = item.get("sources", [""])[0]
                result["羁绊与效果"].append([
                    "国服S1·2021", "时空裂痕", item["cn"], "TFT参考：" + item["tft"],
                    item["difference"], "", "", "2021首发参考", link,
                    "国服同期文献对照；差异存在但完整分档/逐补丁仍需核实",
                    row_id, "待国服核验", ""])
        for item in national.get("version_discrepancies", []):
            # Same trait, different historical observations; both retained.
            result["羁绊与效果"].append([
                "国服S1·" + item["dated"], "时空裂痕", item["cn"],
                "TFT参考：" + item["tft"], item["observation"], "", "",
                item["dated"] + "的公开资料", item["source"],
                item["verdict"], "CN-S1:" + item["cn"] + ":" + item["dated"],
                "有冲突", item["source"]])
        for item in national.get("mapping", []):
            result["赛季特色"].append([
                "国服：" + item["cn"], item["cn"], item["tft"], "与TFT赛季分轨保存",
                item["facts"], "国服赛季/返场玩法对应关系",
                item["when"], "", "", "仅该模式对应关系有来源；棋子/羁绊仍未完整核实",
                item["sources"][0], "对应关系已核对", "; ".join(item["sources"])])
    append_official_jcc(result)
    counted['official_index_coverage']=append_bulk_official(result)
    return result,counted

# 人类阅读的国服中文展示字段。国际服TFT参考仍保存在原始快照中，
# 但不能混入“金铲铲国服中文版”四张正式表。
DISPLAY_COLUMN_IDS = {
    "棋子": [0,1,19,2,4,5,6,7,9,10,11,12,13,14,15,16,17,23,21,20,22],
    "羁绊与效果": [0,1,7,2,4,5,6,11,9,8,10],
    "棋盘可能效果": [0,1,6,2,3,4,5,10,8,7,9],
    "赛季特色": [0,1,6,4,5,7,8,11,9,10],
}
DISPLAY_HEADERS = {
    "棋子": ["赛季编号","赛季名称","配置版本","棋子名称","费用","羁绊一","羁绊二",
             "羁绊三","技能名称","技能完整效果","生命值","攻击力","护甲","魔抗",
             "攻击速度","初始法力","最大法力","核验状态","数据说明","来源网址","棋子ID"],
    "羁绊与效果": ["赛季编号","赛季名称","配置版本","羁绊名称","羁绊基础说明",
                  "各档人数与效果","包含棋子","核验状态","数据说明","来源网址","羁绊ID"],
    "棋盘可能效果": ["赛季编号","赛季名称","玩法类别","玩法名称","实际效果",
                     "触发条件","影响范围","核验状态","版本说明","来源网址","机制ID"],
    "赛季特色": ["赛季编号","赛季名称","配置版本","核心特色","代表机制",
                 "棋子数量","羁绊数量","核验状态","数据完整度","来源网址"],
}

def chinese_public_tables(source_tables, notes):
    # 对外仅公开金铲铲国服独立记录；先前TFT S1-S18来源不删除、不伪称国服。
    selected={k:[list(r) for r in rows if str(r[0]).startswith("国服")]
              for k,rows in source_tables.items()}
    cnnames={1:"时空裂痕",4:"天选福星",6:"双城传说",8:"怪物入侵",
             11:"画之灵",18:"自然之力"}
    # 经2021/2026年国服独立资料核验的机制，不应因剔除TFT行而丢掉。
    for m in notes.get("mechanisms",[]):
        if m.get("review")!="已核实" or not m.get("evidence_url"):continue
        name=cnnames.get(m.get("season"))
        if not name:continue
        ver=m.get("variant") or "国服独立资料"
        selected["棋盘可能效果"].append([
            "国服补充",name,m["name"],m["effect"],m.get("trigger",""),m.get("scope",""),
            "国服独立公告机制",m["source_url"],ver,
            f"CN-MECHANIC:{m['season']}:{m['name']}",m["review"],m["evidence_url"]])
    # 明确排除“2021历史数字冲突”作为官方实装数据的误认证：
    # 它们仍可保留在羁绊 Sheet，但审核状态为有冲突。
    display={}
    for tab,rows in selected.items():
        keys=DISPLAY_COLUMN_IDS[tab]
        assert len(keys)==len(DISPLAY_HEADERS[tab]),tab
        rendered=[]
        seen=set()
        for original in rows:
            row=[original[i] for i in keys]
            ident=(str(row[0]),str(row[-1]))
            if ident in seen:continue
            seen.add(ident)
            for idx,value in enumerate(row):
                if isinstance(value,str):
                    value=value.strip()
                    value=re.sub(r"<[^>]*>","",html.unescape(value))
                    row[idx]=value
            if tab=="棋子":
                # 避免玩家把内部编码当作英语名称，标注无一星可见配置的争议项。
                if row[17]=="缺可见一星配置/商店可购性待核":
                    row[18]="官网存在更高星/特殊形态配置，但尚未证实可在商店直接购买"
            elif tab=="羁绊与效果":
                if not row[4]:row[4]="官方配置未提供独立基础说明，请结合人数档位查看"
                if not row[5]:row[5]="官方配置没有给出可核实的分档数值"
            elif tab=="棋盘可能效果":
                if str(original[6]).startswith("奇遇/") and row[3].startswith("奇遇/事件#"):
                    row[3]="未命名奇遇（详见实际效果）"
            rendered.append(row)
        display[tab]=rendered
    return display

def diff(old_rows,new_rows,header):
    if not old_rows:return {"added":len(new_rows),"changed":0,"removed":0}
    idcol=next((i for i,h in enumerate(header) if h in ("数据ID","棋子ID","羁绊ID","机制ID")),0)
    def lookup(rows):
        return {str(r[0])+"|"+str(r[idcol]):tuple(map(str,r)) for r in rows if len(r)>idcol}
    a,b=lookup(old_rows),lookup(new_rows)
    return {"added":len(b.keys()-a.keys()),
            "changed":sum(a[k]!=b[k] for k in a.keys() & b.keys()),
            "removed":len(a.keys()-b.keys())}

def build(export=True):
    # Separate first-party per-mode, per-season augment table; generated from
    # saved Tencent hex snapshots, never from TFT international guesses.
    import augment_catalog
    augment_catalog.build()
    notes,snaps=load()
    raw,counts=compile_tables(notes,snaps)
    tables=chinese_public_tables(raw,notes)
    TABLES.mkdir(exist_ok=True)
    changes={}
    for tab,rows in tables.items():
        path=TABLES/f"{tab}.csv"
        old=[]
        if path.exists():
            with path.open(encoding="utf-8-sig",newline="") as f:
                reader=csv.reader(f);head=next(reader,[])
                if head==DISPLAY_HEADERS[tab]:old=list(reader)
        changes[tab]=diff(old,rows,DISPLAY_HEADERS[tab])
        if any(changes[tab].values()) or not path.exists():
            tmp=path.with_suffix(".csv.tmp")
            with tmp.open("w",encoding="utf-8-sig",newline="") as f:
                writer=csv.writer(f);writer.writerow(DISPLAY_HEADERS[tab]);writer.writerows(rows)
            tmp.replace(path)
    report={"generated":datetime.now(timezone.utc).isoformat(),
        "data_scope":"金铲铲国服中文版；国际TFT参考不进入五张正式表；海克斯强化来自独立官网hex快照",
        "counts":counts,"changes_since_previous_export":changes}
    (TABLES/"latest_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    for tab,rows in tables.items():print(f"{tab}: {len(rows)}条; delta={changes[tab]}")
    workbook=ROOT/"金铲铲全赛季研究资料库.xlsx"
    stale=(not workbook.exists() or any((TABLES/(tab+".csv")).stat().st_mtime_ns > workbook.stat().st_mtime_ns for tab in SHEETS))
    if export and sys.platform=="win32" and (any(any(x.values()) for x in changes.values()) or stale):
        script=ROOT/"export_excel.ps1"
        if script.exists():
            try:
                subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(script)],check=True)
            except subprocess.CalledProcessError:
                # Excel COM可能因本机授权过期拒绝写入；只在既有工作簿行列一致时
                # 用标准OOXML更新内容，保留原有筛选/冻结/格式，否则失败关闭。
                print("Excel接口写入失败：尝试仅更新既有Excel的表格内容",file=sys.stderr)
                subprocess.run([sys.executable,str(ROOT/"repair_xlsx_from_csv.py")],check=True)
    if export and workbook.exists():
        import importlib.util
        if importlib.util.find_spec("openpyxl"):
            subprocess.run([sys.executable,str(ROOT/"export_augments_excel.py")],check=True)
        else:
            print("海克斯CSV已生成；更新Excel第五张表需安装 openpyxl",file=sys.stderr)
    return report

def refresh(season,patch,dry_run=False):
    if season<3:raise ValueError("S1/S2 为固定历史站点快照，目前不提供自动刷新；请人工补充研究笔记")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,2}",patch):
        raise ValueError("版本只允许如 14.18 或 26.20.1")
    url=f"https://raw.communitydragon.org/{patch}/cdragon/tft/zh_cn.json"
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=50) as response:
        data=json.load(response)
    options=[s for s in data.get("setData",[]) if s.get("number")==season]
    chosen=next((s for s in options if s.get("mutator")==f"TFTSet{season}"),None)
    if chosen is None:raise ValueError(f"版本 {patch} 未找到 S{season} 主玩法（未修改旧快照）")
    if len(chosen.get("champions",[]))<30 or len(chosen.get("traits",[]))<10:
        raise ValueError("异常稀疏的响应；拒绝覆盖旧快照")
    record={"season":season,"version":patch,"source":url,"setData":chosen}
    body=(json.dumps(record,ensure_ascii=False,indent=1)+"\n").encode("utf-8")
    path=source_path(season)
    before=path.read_bytes() if path.exists() else None
    oldsha=sha256(before) if before else None
    print(f"S{season} {patch}: {len(chosen['champions'])} candidates, {len(chosen['traits'])} traits, source hash {sha256(body)[:12]}")
    if dry_run or (before and json.loads(before)==record):
        print("未写入：仅检查" if dry_run else "无变化")
        return
    if before:
        archive=SOURCE/"history"
        archive.mkdir(exist_ok=True)
        shutil.copy2(path,archive/f"set{season:02}_{oldsha[:12]}.json")
    tmp=path.with_suffix(".new")
    tmp.write_bytes(body)
    tmp.replace(path)
    print("已保存快照；请运行 python research.py build 更新四表")

def status():
    notes,snaps=load()
    tables,counts=compile_tables(notes,snaps)
    pending=sum(1 for m in notes.get("mechanisms",[]) if m.get("review")!="已核实")
    issues=[f"S{n}:缺快照" for n in map(int,notes["seasons"]) if n not in snaps]
    variants=[r for r in tables["棋子"] if r[-2].startswith("疑似")]
    print(f"快照 {len(snaps)}/{len(notes['seasons'])}; 棋子候选 {len(tables['棋子'])}; 羁绊 {len(tables['羁绊与效果'])}")
    verified=len(notes.get("mechanisms",[]))-pending
    print(f"机制已有来源核实 {verified}/{len(notes.get('mechanisms',[]))}; 待核验 {pending}; 特殊形态待核验 {len(variants)}")
    print("腾讯官网版本索引：",counts.get("official_index_coverage",{}))
    if issues:print("缺口："+"; ".join(issues))
    print("来源和审核以每行对应来源URL与审核状态为准；不得将TFT自动视为金铲铲官方数据")

def mark(season, kind, key, status, source, note):
    """人工核验写入研究笔记；正式核实必须附上独立证据。"""
    allowed={"待国服核验","已核实","有冲突","不适用"}
    if status not in allowed:
        raise ValueError("审核状态错误: "+status)
    if status=="已核实" and not re.match(r"^https?://[^/]+",source):
        raise ValueError("标记已核实必须提供独立来源URL")
    obj=json.loads(NOTES.read_text(encoding="utf-8"))
    if str(season) not in obj["seasons"]:raise ValueError("赛季不存在")
    today=datetime.now(timezone.utc).date().isoformat()
    if kind in ("unit","trait"):
        if not key:raise ValueError("需要--id（Excel的数据ID列）")
        obj.setdefault("reviews",{})[f"{season}|{kind}|{key}"]={
            "status":status,"evidence_url":source,"note":note,"reviewed_on":today}
    elif kind=="mechanism":
        item=next((m for m in obj["mechanisms"] if m["season"]==season and
                   key in (m.get("id"),m["name"],f"{season}|{m['name']}",f"{season}|{m['name']}|{m.get('variant','')}")),None)
        if not item:raise ValueError("无法识别机制数据ID")
        item.update(review=status,evidence_url=source,note=note,reviewed_on=today)
    elif kind=="season":
        obj["seasons"][str(season)].update(review=status,note=note,reviewed_on=today)
        if source:
            urls=obj["seasons"][str(season)].setdefault("sources",[])
            if source not in urls:urls.append(source)
    else:raise ValueError("kind仅支持unit/trait/mechanism/season")
    tmp=NOTES.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(NOTES)
    print(f"S{season} {kind} {key} 已标记为 {status}；运行 build 更新Excel")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    buildp=sub.add_parser("build",help="从已保存快照生成5个CSV并更新Excel")
    buildp.add_argument("--csv-only",action="store_true")
    sub.add_parser("status",help="查看数据覆盖与待核验数量")
    update=sub.add_parser("refresh",help="只按明确版本增量更新一个赛季")
    update.add_argument("--season",type=int,required=True)
    update.add_argument("--patch",required=True)
    update.add_argument("--dry-run",action="store_true")
    reviewer=sub.add_parser("mark",help="记录人工核实结论和证据，不改原始快照")
    reviewer.add_argument("--season",type=int,required=True)
    reviewer.add_argument("--kind",choices=("unit","trait","mechanism","season"),required=True)
    reviewer.add_argument("--id",default="")
    reviewer.add_argument("--status",required=True)
    reviewer.add_argument("--source",default="")
    reviewer.add_argument("--note",default="")
    a=parser.parse_args()
    if a.command=="build":build(export=not a.csv_only)
    elif a.command=="status":status()
    elif a.command=="refresh":refresh(a.season,a.patch,a.dry_run)
    else:mark(a.season,a.kind,a.id,a.status,a.source,a.note)

if __name__=="__main__":main()
