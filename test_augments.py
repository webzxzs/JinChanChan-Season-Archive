"""Official snapshot scope, tier safety and public-only build contracts."""
import csv
import json
import unittest
from collections import Counter
from pathlib import Path

import augment_catalog


class AugmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with augment_catalog.DEST.open(encoding="utf-8-sig", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))
        cls.coverage = json.loads((augment_catalog.ROOT / "data" / "augment_coverage.json").read_text(encoding="utf-8"))

    def test_all_mode_season_groups_and_gaps_stay_visible(self):
        self.assertEqual(len(self.coverage["coverage"]), 41)
        self.assertEqual(sum(int(e["count"]) > 0 for e in self.coverage["coverage"]), 37)
        self.assertEqual(len(self.rows), 10478)
        self.assertEqual(sum(int(e["count"]) for e in self.coverage["coverage"]),len(self.rows))
        self.assertEqual(len({e["season"] for e in self.coverage["coverage"]}),41)
        self.assertTrue(any("资源不可用" in x["status"] for x in self.coverage["coverage"]))
        self.assertTrue(any("列表为空" in x["status"] for x in self.coverage["coverage"]))

    def test_season_identity_provenance_and_distinct_special_levels(self):
        seen = set()
        for row in self.rows:
            key=(row["赛季编号"],row["强化ID"])
            self.assertNotIn(key,seen)
            seen.add(key)
            self.assertTrue(row["强化名称"] and row["强化效果"])
            self.assertTrue(row["来源网址"].startswith("https://game.gtimg.cn/"))
            self.assertEqual(row["档位分类"],augment_catalog.LEVELS.get(row["官方等级"],
                f"赛季特殊（官方等级 {row['官方等级'] or '未知'}）"))
        levels=Counter(x["官方等级"] for x in self.rows)
        self.assertGreater(levels["4"],100)
        self.assertGreater(levels["7"],0)
        self.assertGreater(levels["1"],1000)

    def test_build_idempotence(self):
        before=augment_catalog.DEST.read_bytes()
        result=augment_catalog.build()
        self.assertEqual(result["rows"],len(self.rows))
        self.assertEqual(augment_catalog.DEST.read_bytes(),before)


if __name__=="__main__":
    unittest.main()
