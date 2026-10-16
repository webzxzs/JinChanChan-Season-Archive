"""Build per-mode, per-season augment records from saved Tencent first-party hex assets.

No network activity, no inferred game availability, and no cross-season union.
This output is a representative patch snapshot, NOT all historical patch variants.
The CSV is committed so the public read-only web viewer works without raw dumps.
"""
import csv
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source" / "official_jcc_bulk"
DEST = ROOT / "tables" / "强化符文.csv"
HEADERS = [
    "赛季编号", "赛季名称", "配置版本", "强化名称", "强化效果",
    "官方等级", "档位分类", "图标", "强化ID", "英雄强化类型",
    "是否传说强化", "羁绊关联ID", "核验状态", "版本说明", "来源网址",
]
LEVELS = {"1": "银色", "2": "金色", "3": "彩色"}
SOURCE_PREFIX = "https://game.gtimg.cn/images/lol/act/jkzlk/js"


def clean(value):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", str(value or ""))).strip()


def build():
    manifest_path = SOURCE / "manifest.json"
    if not manifest_path.exists():
        if DEST.exists():
            print("强化符文：本地原始快照未安装，保留已公开 CSV", DEST)
            return {"rows": sum(1 for _ in DEST.open(encoding="utf-8-sig")) - 1}
        raise FileNotFoundError("缺少官方版本快照，且不存在已导出的强化符文 CSV")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows, coverage = [], []
    for entry in manifest["entries"]:
        mode, season, name = str(entry["mode"]), str(entry["season"]), entry["name"]
        reference = f"国服·{name}｜{season}／模式{mode}"
        version = str(entry.get("version") or "")
        folder = SOURCE / ("m" + mode + "_" + re.sub(r"[^A-Za-z0-9]", "", season))
        source_url = ""
        if entry.get("normal_file"):
            norm = json.loads((ROOT / entry["normal_file"]).read_text(encoding="utf-8"))
            source_url = norm.get("asset_urls", {}).get("hexurl", "")
        if not source_url:
            source_url = manifest.get("index_url", "")
        if entry["status"] == "unavailable":
            coverage.append((reference, 0, "官方历史资源不可用"))
            continue
        path = folder / "hex.json"
        if not path.exists():
            coverage.append((reference, 0, "无保存的强化配置"))
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        if str(doc.get("setId", mode)) != mode:
            raise ValueError(f"强化符文模式不匹配: {reference}")
        collection = doc.get("data", {})
        pairs = (collection.items() if isinstance(collection, dict)
                 else enumerate(collection) if isinstance(collection, list) else ())
        unique = set()
        count = 0
        for ident, item in pairs:
            if not isinstance(item, dict):
                continue
            code = str(item.get("id") or ident)
            label = clean(item.get("name"))
            desc = clean(item.get("desc"))
            if not (code and label and desc):
                continue
            if code in unique:
                raise ValueError(f"同赛季强化符文ID重复: {reference} {code}")
            unique.add(code)
            level = str(item.get("level") or "")
            category = LEVELS.get(level, f"赛季特殊（官方等级 {level or '未知'}）")
            icon = str(item.get("icon") or "")
            if icon and not icon.startswith("https://game.gtimg.cn/images/"):
                icon = ""  # Never publish untrusted links as official game icons.
            rows.append([
                reference, name, version, label, desc, level, category, icon, code,
                str(item.get("hero_enhancement_type") or "0"),
                str(item.get("is_legend") or "0"),
                str(item.get("fetterId") or ""),
                "腾讯官网配置已取得／实战可选性未逐项核对",
                "仅对应此玩法的 " + version + " 配置快照；不代表首发、全年或全部补丁",
                source_url,
            ])
            count += 1
        coverage.append((reference, count, "已取得该版本强化配置" if count else "该快照强化列表为空／不可推断玩法无强化"))
    DEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEST.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows(rows)
    if not DEST.exists() or tmp.read_bytes() != DEST.read_bytes():
        tmp.replace(DEST)
    else:
        tmp.unlink()
    manifest_output = ROOT / "data" / "augment_coverage.json"
    manifest_output.parent.mkdir(exist_ok=True)
    manifest_output.write_text(json.dumps({
        "source": manifest["index_url"], "snapshot_only": True,
        "coverage": [{"season": s, "count": n, "status": status} for s, n, status in coverage],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("强化符文:", len(rows), "条", "有数据赛季", sum(n > 0 for _, n, _ in coverage),
          "/", len(coverage), "等级", dict(Counter(r[5] for r in rows)))
    return {"rows": len(rows), "groups": len(coverage),
            "with_augments": sum(n > 0 for _, n, _ in coverage)}


if __name__ == "__main__":
    build()
