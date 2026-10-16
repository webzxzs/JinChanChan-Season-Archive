"""Non-destructive migration checks for the game-design mechanism taxonomy."""
import csv
import unittest
from collections import Counter
from pathlib import Path
import json

import mechanism_catalog as catalog
import web_server


def load(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class MechanismTests(unittest.TestCase):
    def test_identity_and_evidence_are_preserved(self):
        raw = load(catalog.SOURCE)
        new = load(catalog.DEST)
        self.assertEqual(len(raw), 1563)
        self.assertEqual(len(new), len(raw))
        source_fields = tuple(raw[0])
        old = {(r["赛季编号"], r["机制ID"]):r for r in raw}
        self.assertEqual(len(old), len(raw))
        for row in new:
            key = (row["赛季编号"], row["机制ID"])
            self.assertIn(key, old)
            self.assertEqual({k: row[k] for k in source_fields}, old[key])
            self.assertIn(row["系统大类"], catalog.SYSTEMS)
            self.assertTrue(row["分类依据"])

    def test_canonical_separation(self):
        rows = load(catalog.DEST)
        counts=Counter(r["系统大类"] for r in rows)
        self.assertEqual(counts["羁绊影响的站位"],130)
        self.assertEqual(counts["赛季专属互动"],456)
        self.assertEqual(counts["主动购买与使用"],181)
        self.assertEqual(counts["对局环境与全局规则"],790)
        self.assertEqual(counts["赛季公告与补充"],6)
        for row in rows:
            if row["系统大类"]=="羁绊影响的站位":
                self.assertEqual(row["是否独立赛季规则"],"否（属于羁绊）")
            if row["机制子类"]=="星系":
                self.assertEqual(row["赛季名称"],"银河战争")
        # No cross-season enrichment masquerading as a verified first-party mechanic.
        self.assertTrue(all(r["机制ID"] and r["来源网址"] for r in rows))

    def test_build_idempotence_and_complete_coverage(self):
        before = catalog.DEST.read_bytes()
        result = catalog.build()
        self.assertEqual(catalog.DEST.read_bytes(), before)
        self.assertEqual(len(result["seasons"]),42)
        self.assertEqual(sum(r["count"] for r in result["seasons"].values()),1563)

    def test_web_core_filter_and_single_mode_summary(self):
        archive=web_server.Archive()
        core=archive.search("boards",{"category":["core"],"limit":["60"]})
        self.assertEqual(core["total"],1433)
        related=archive.search("boards",{"category":["羁绊影响的站位"],"limit":["60"]})
        self.assertEqual(related["total"],130)
        self.assertTrue(all(r["系统大类"]=="羁绊影响的站位" for r in related["items"]))
        season="国服·自然之力｜S19／模式18"
        summary=archive.summary(season)
        self.assertEqual(summary["counts"]["boards"],371)
        self.assertEqual(summary["mechanism_subtypes"]["自然仙灵"],348)
        self.assertEqual(sum(summary["mechanism_systems"].values()),371)

    def test_editorial_main_mechanics_have_independent_public_evidence(self):
        with (catalog.ROOT/"data"/"season_signatures.json").open(encoding="utf-8") as stream:
            entries=json.load(stream)["by_name"]
        self.assertGreaterEqual(len(entries),13)
        for season,signature in entries.items():
            self.assertTrue(season and signature["title"] and signature["rule"])
            self.assertTrue(signature["player_decision"])
            self.assertTrue(signature["source_url"].startswith("https://"))
        archive=web_server.Archive()
        live=archive.catalog_data()["items"]
        current=next(x for x in live if x["name"]=="自然之力" and x["season"]=="S19")
        self.assertEqual(current["signature"]["title"],"自然仙灵")
        self.assertTrue(any(x["kind"]=="indexed" and "signature" not in x for x in live))


if __name__=="__main__":
    unittest.main()
