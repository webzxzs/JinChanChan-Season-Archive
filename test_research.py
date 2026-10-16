"""离线回归测试：保留历史数据、证据门槛、幂等生成。"""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import research


@unittest.skipUnless(
    (Path(__file__).resolve().parent / "source" / "official_jcc_bulk" / "manifest.json").exists(),
    "Deep research tests require optional raw snapshots in source/ (not mirrored publicly).",
)
class ArchiveTests(unittest.TestCase):
    def test_four_sheets_and_row_lengths(self):
        notes, source = research.load()
        data, summary = research.compile_tables(notes, source)
        self.assertEqual(len(source), 18)
        self.assertEqual(set(data), set(research.SHEETS))
        self.assertEqual({k for k in summary if isinstance(k,int)},set(range(1,19)))
        self.assertGreaterEqual(summary["official_index_coverage"]["available"],30)
        self.assertTrue(all(len(row) == len(research.HEADERS[name])
                            for name, rows in data.items() for row in rows))

    def test_national_research_is_separate(self):
        notes, source = research.load()
        data, _ = research.compile_tables(notes, source)
        self.assertEqual(58, sum(x[0] == "国服S1·官方" for x in data["棋子"]))
        self.assertEqual(25, sum(x[0] == "国服S1·官方" for x in data["羁绊与效果"]))
        self.assertEqual(57, sum(x[0] == "国服S5.5·官方" for x in data["棋子"]))
        self.assertEqual(27, sum(x[0] == "国服S5.5·官方" for x in data["羁绊与效果"]))
        self.assertEqual(60, sum(x[0] == "国服S6·官方" for x in data["棋子"]))
        self.assertEqual(28, sum(x[0] == "国服S6·官方" for x in data["羁绊与效果"]))
        self.assertEqual(58, sum(x[0] == "国服·福星临门·官方" for x in data["棋子"]))
        self.assertEqual(26, sum(x[0] == "国服·福星临门·官方" for x in data["羁绊与效果"]))
        self.assertFalse(any(x[0] == "国服S1·2021" for x in data["棋子"]))
        self.assertTrue(all(x[-2] == "已核实" and x[-1].startswith("https://")
                            for x in data["羁绊与效果"] if x[0] == "国服S1·官方"))
        self.assertEqual(5, sum(x[0].startswith("国服：") for x in data["赛季特色"]))
        self.assertTrue(all("非国服" in x[1] for x in data["棋子"] if x[0] == "S1"))
        self.assertTrue(any(x[2] == "2026返场：绘境地格" and x[-2] == "已核实"
                            for x in data["棋盘可能效果"]))

    def test_official_s1_complete_consistent_and_versioned(self):
        import hashlib
        p=research.SOURCE/"official_jcc"/"mode1_config220224.json"
        raw=research.SOURCE/"official_jcc"/"config220224_full.json"
        data=json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data["raw_sha256"], hashlib.sha256(raw.read_bytes()).hexdigest())
        self.assertEqual((len(data["units"]),len(data["traits"]),data["hero_config_rows"]),(58,25,174))
        trait_names={t["name"] for t in data["traits"]}
        self.assertTrue(all(set(h["traits"]) <= trait_names for h in data["units"]))
        self.assertTrue(all(len(h["star_config_ids"])==3 for h in data["units"]))
        self.assertIn("config220224",data["config_version"])
        self.assertIn("不能证明",data["version_caution"])
        second=json.loads((research.SOURCE/"official_jcc"/"mode5_config220224.json").read_text(encoding="utf-8"))
        self.assertEqual((len(second["units"]),len(second["traits"]),second["hero_config_rows"]),(57,27,171))
        self.assertEqual(second["raw_sha256"],data["raw_sha256"])
        self.assertTrue(all(len(h["star_config_ids"])==3 for h in second["units"]))
        for mode,expected in [(6,(60,28,180)),(4,(58,26,174))]:
            obj=json.loads((research.SOURCE/"official_jcc"/f"mode{mode}_config220224.json").read_text(encoding="utf-8"))
            self.assertEqual((len(obj["units"]),len(obj["traits"]),obj["hero_config_rows"]),expected)
            self.assertEqual(obj["raw_sha256"],data["raw_sha256"])
            known={t["name"] for t in obj["traits"]}
            self.assertTrue(all(set(u["traits"])<=known for u in obj["units"]))

    def test_conflicting_season_variants_are_retained(self):
        notes, source = research.load()
        data, _ = research.compile_tables(notes, source)
        conflicting = [r for r in data["羁绊与效果"] if r[-2] == "有冲突"]
        self.assertEqual(4, len(conflicting))
        self.assertEqual(2, len([r for r in conflicting if r[2] == "北地"]))
        self.assertEqual(2, len([r for r in conflicting if r[2] == "神将"]))
        self.assertTrue(all(r[-1].startswith("https://") for r in conflicting))

    def test_tencent_version_index_coverage_and_tracing(self):
        import hashlib
        base=research.SOURCE/"official_jcc_bulk"
        m=json.loads((base/"manifest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(m["total_index_records"],197)
        self.assertGreaterEqual(m["selected_groups"],41)
        self.assertEqual(len(m["entries"]),m["selected_groups"])
        self.assertGreaterEqual(sum(x["status"]=="ok" for x in m["entries"]),39)
        self.assertEqual(m["index_sha256"],hashlib.sha256((base/"versiondataconfig.json").read_bytes()).hexdigest())
        seen=set()
        for x in m["entries"]:
            mode_season=(x["mode"],x["season"])
            self.assertNotIn(mode_season,seen)
            seen.add(mode_season)
            if x["status"] not in ("ok","partial"):continue
            snap=json.loads((research.ROOT/x["normal_file"]).read_text(encoding="utf-8"))
            self.assertEqual((snap["mode"],snap["season"]),mode_season)
            self.assertTrue(snap["asset_urls"]["herourl"].startswith("https://game.gtimg.cn/"))
            self.assertEqual(len(snap["units"]),x["unit_count"])
            self.assertEqual(len(snap["traits"]),x["trait_count"])
        n,s=research.load()
        d,_=research.compile_tables(n,s)
        self.assertTrue(any("自然之力" in r[0] for r in d["棋子"]))
        self.assertTrue(any(r[-2]=="待核实玩法边界" for r in d["棋盘可能效果"]))

    def test_full_patch_history_is_traceable(self):
        import gzip
        manifest_path=research.SOURCE/"official_jcc_patch_history"/"patch_manifest.json"
        m=json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(len(m["patches"]),m["requested_cn_rows"])
        self.assertEqual(sum(m["counts"].values()),m["requested_cn_rows"])
        self.assertGreaterEqual(m["counts"].get("complete",0),180)
        ids=set()
        for r in m["patches"]:
            key=(r["mode"],r["season"],r["version"],r["name"])
            self.assertNotIn(key,ids)
            ids.add(key)
            if r["status"]!="complete":continue
            snap=json.loads(gzip.decompress((research.ROOT/r["normalized_path"]).read_bytes()))
            self.assertEqual(snap["version"],r["version"])
            self.assertEqual(snap["mode"],r["mode"])
            self.assertEqual(snap["season"],r["season"])
        with (research.ROOT/m["diff_file"]).open(encoding="utf-8-sig",newline="") as f:
            self.assertEqual(len(list(csv.DictReader(f))),m["diff_rows"])

    def test_chinese_public_workbook_has_no_foreign_season_rows(self):
        notes,snapshots=research.load()
        all_tables,_=research.compile_tables(notes,snapshots)
        tables=research.chinese_public_tables(all_tables,notes)
        self.assertEqual({k:len(v) for k,v in tables.items()},
                         {"棋子":2857,"羁绊与效果":1370,
                          "棋盘可能效果":1563,"赛季特色":50})
        for name,rows in tables.items():
            self.assertTrue(all(str(r[0]).startswith("国服") for r in rows))
            self.assertTrue(all(len(r)==len(research.DISPLAY_HEADERS[name]) for r in rows))
        names=research.DISPLAY_HEADERS["棋子"]
        effect=names.index("技能完整效果")
        self.assertTrue(all(r[effect] and "@" not in r[effect] for r in tables["棋子"]))
        b=research.DISPLAY_HEADERS["棋盘可能效果"]
        names_column=b.index("玩法名称")
        category=b.index("玩法类别")
        self.assertTrue(all("奇遇/事件#" not in r[names_column] for r in tables["棋盘可能效果"]))
        kinds={r[category] for r in tables["棋盘可能效果"]}
        self.assertTrue(any("法杖" in k for k in kinds))
        self.assertTrue(any("自然仙灵" in k for k in kinds))
        self.assertTrue(any("画之灵奇遇" in k for k in kinds))

    def test_non_shop_does_not_enter_workbook(self):
        self.assertFalse(research.playable({"name":"魔沼蛙","cost":2,
                         "apiName":"TFT_Frog","traits":["斗士"]},{"斗士"}))

    def test_cannot_claim_verified_without_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"research_notes.json"
            dest.write_bytes(research.NOTES.read_bytes())
            with patch.object(research,"NOTES",dest):
                with self.assertRaisesRegex(ValueError,"来源URL"):
                    research.mark(1,"unit","Camille","已核实","","")
                research.mark(1,"unit","Camille","待国服核验","","待查国服")
                obj=json.loads(dest.read_text(encoding="utf-8"))
                self.assertEqual(obj["reviews"]["1|unit|Camille"]["note"],"待查国服")

    def test_repeat_build_is_unchanged(self):
        research.build(export=False)
        report=research.build(export=False)
        self.assertTrue(all(all(count == 0 for count in values.values())
                            for values in report["changes_since_previous_export"].values()))

    def test_invalid_refresh_has_no_side_effect(self):
        with self.assertRaises(ValueError):
            research.refresh(12, "../invalid", dry_run=True)


if __name__ == "__main__":
    unittest.main()
