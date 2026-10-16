"""Derived, gameplay-oriented view of the original official mechanism evidence.

Preserves the original 11-column 棋盘可能效果.csv unchanged: every row remains
traceable by (season, mechanism ID). Classification is about *where it acts*,
not a claim about developer intention or live encounter probability.
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "tables" / "棋盘可能效果.csv"
DEST = ROOT / "tables" / "赛季机制图鉴.csv"
SUMMARY = ROOT / "data" / "mechanism_overview.json"
EXTRA = ["系统大类", "机制子类", "设计层级", "是否独立赛季规则", "分类依据"]

SYSTEMS = (
    "对局环境与全局规则",
    "赛季专属互动",
    "主动购买与使用",
    "羁绊影响的站位",
    "赛季公告与补充",
    "待分类",
)


def classify(record):
    raw = record["玩法类别"]
    name = record["赛季名称"]
    if raw == "星系/全局环境规则":
        # The SDK field is called galaxy in many other seasons as well.
        # Never call them all S3 galaxies simply because the file is named galaxy.js.
        label = "星系" if name == "银河战争" else "全局规则候选"
        return SYSTEMS[0], label, "对局级", "待确认", "官网 galaxyurl；仅银河战争明确称为星系"
    if raw == "自然仙灵效果（非地格）":
        return SYSTEMS[1], "自然仙灵", "局内获得／触发", "是（该系统效果）", "官网 adventureurl；按自然仙灵系统整理"
    if raw == "画之灵奇遇（非地格）":
        return SYSTEMS[1], "奇遇事件", "局内随机事件", "是（该系统效果）", "官网 adventureurl；具体出现时点未核"
    if raw.startswith("法杖/一次性效果"):
        subtype = raw.partition("·")[2] or "其他"
        return SYSTEMS[2], "法杖／一次性效果 · " + subtype, "商店／道具交互", "是（该系统效果）", "官网 adventureurl；仅整理配置中的使用效果"
    if raw == "棋盘站位相关羁绊":
        return SYSTEMS[3], "站位触发羁绊", "羁绊与布阵", "否（属于羁绊）", "官网 raceurl/joburl；按关键词检出，需人工复核"
    if raw == "国服独立公告机制":
        return SYSTEMS[4], "版本公告与赛季规则", "赛季设计与版本说明", "待确认", "外部独立来源；不和官网SDK配置混为同等级"
    return SYSTEMS[5], "未知", "未确定", "待确认", "旧标签未映射，需单项复核"


def build():
    with SOURCE.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        old_headers = reader.fieldnames
        if not old_headers or "机制ID" not in old_headers:
            raise ValueError("官方原始机制表结构变化，拒绝静默整理")
        rows = list(reader)
    enriched = []
    seen = set()
    counts = defaultdict(Counter)
    for r in rows:
        identity = (r["赛季编号"], r["机制ID"])
        if identity in seen:
            raise ValueError("旧机制表有重复 identity，拒绝覆盖: " + str(identity))
        seen.add(identity)
        major, minor, layer, independent, reason = classify(r)
        enriched.append([r[k] for k in old_headers] + [major, minor, layer, independent, reason])
        counts[r["赛季编号"]][major] += 1
    DEST.parent.mkdir(exist_ok=True)
    with DEST.with_suffix(".tmp").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(old_headers + EXTRA)
        writer.writerows(enriched)
    new_path = DEST.with_suffix(".tmp")
    if not DEST.exists() or new_path.read_bytes() != DEST.read_bytes():
        new_path.replace(DEST)
    else:
        new_path.unlink()
    # An empty season is not silently given another season's mechanism.
    seasons = {r["赛季编号"] for r in rows}
    site = ROOT / "data" / "site_index.json"
    if site.exists():
        payload = json.loads(site.read_text(encoding="utf-8"))
        seasons.update(e["ref"] for e in payload["catalog"])
    overview = {
        "not_a_list_of_placement_tiles": True,
        "source": SOURCE.name,
        "systems": list(SYSTEMS),
        "seasons": {
            k: {"count": sum(counts[k].values()), "by_system": dict(counts[k]),
                "status": "存在来源记录" if counts[k] else "未取得可归类的机制记录"}
            for k in sorted(seasons)
        },
    }
    SUMMARY.parent.mkdir(exist_ok=True)
    SUM_TEMP = SUMMARY.with_suffix(".tmp")
    SUM_TEMP.write_text(json.dumps(overview, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not SUMMARY.exists() or SUM_TEMP.read_bytes() != SUMMARY.read_bytes():
        SUM_TEMP.replace(SUMMARY)
    else:
        SUM_TEMP.unlink()
    print("机制图鉴", len(enriched), "条，系统分布",
          dict(Counter(r[len(old_headers)] for r in enriched)),
          "赛季", len(overview["seasons"]))
    return overview


if __name__ == "__main__":
    build()
