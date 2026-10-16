"""API and HTML smoke tests; do not modify user's archive CSV."""
import csv
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_server as app


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.create_server(port=0)
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def get(self, path):
        with urlopen(self.base + path, timeout=10) as response:
            return response.status, response.headers, response.read()

    def test_all_five_tabs_have_real_data(self):
        _, _, payload = self.get("/api/summary")
        summary = json.loads(payload)
        self.assertTrue(all(summary["counts"][k] > 0 for k in app.TABLES))
        self.assertGreater(len(summary["seasons"]), 20)
        for tab in app.TABLES:
            _, _, data = self.get("/api/records/" + tab + "?limit=5")
            rows = json.loads(data)
            self.assertEqual(len(rows["items"]), 5)
            self.assertEqual(rows["total"], summary["counts"][tab])
            self.assertTrue(all(x["赛季编号"] for x in rows["items"]))

    def test_lookup_filter_search_and_pagination(self):
        _, _, raw = self.get("/api/records/units?q=%E5%A4%A9%E7%BD%9A%E5%BC%A9%E7%A5%9E&limit=2&page=1")
        data = json.loads(raw)
        self.assertGreaterEqual(data["total"], 1)
        self.assertTrue(all("天罚弩神" in str(row) for row in data["items"]))
        first = data["items"][0]
        from urllib.parse import urlencode
        qs = urlencode({"season": first["赛季编号"], "limit": 30})
        _, _, body = self.get("/api/records/units?" + qs)
        limited = json.loads(body)
        self.assertGreater(limited["total"], 0)
        self.assertTrue(all(r["赛季编号"] == first["赛季编号"] for r in limited["items"]))
        _, _, small = self.get("/api/records/units?limit=2&page=2")
        self.assertEqual(len(json.loads(small)["items"]), 2)

    def test_official_patch_differences_and_version_filters(self):
        _, _, body = self.get("/api/records/patches?limit=3")
        data = json.loads(body)
        self.assertGreater(data["total"], 3000)
        self.assertEqual(len(data["items"]), 3)
        self.assertTrue(all(isinstance(row["差异"], list) for row in data["items"]))
        from urllib.parse import urlencode
        first = data["items"][0]
        params = urlencode({"season": first["赛季编号"], "version": first["配置版本"], "category": first["对象"]})
        _, _, filtered = self.get("/api/records/patches?" + params)
        found = json.loads(filtered)
        self.assertGreater(found["total"], 0)
        self.assertTrue(all(row["赛季编号"] == first["赛季编号"] and row["配置版本"] == first["配置版本"] for row in found["items"]))

    def test_all_seasons_and_shop_filters(self):
        _, _, raw = self.get("/api/catalog")
        info = json.loads(raw)
        indexed = [r for r in info["items"] if r["kind"] == "indexed"]
        self.assertEqual(len(indexed), 41)
        self.assertEqual(len({(x["mode"],x["season"]) for x in indexed}), 41)
        self.assertGreaterEqual(len([x for x in indexed if x["status"] == "ok"]), 39)
        _, _, raw = self.get("/api/records/units?cost=6%2B&limit=60")
        expensive = json.loads(raw)
        self.assertGreater(expensive["total"], 0)
        self.assertTrue(all(int(x["费用"]) >= 6 for x in expensive["items"]))
        _, _, raw = self.get("/api/records/units?trait=%E6%96%97%E5%A3%AB&limit=60")
        filtered = json.loads(raw)
        self.assertGreater(filtered["total"], 0)
        self.assertTrue(all("斗士" in (x.get("羁绊一"),x.get("羁绊二"),x.get("羁绊三")) for x in filtered["items"]))
        _, _, raw = self.get("/api/records/units?season=%E5%9B%BD%E6%9C%8DS1%C2%B7%E5%AE%98%E6%96%B9")
        self.assertEqual(json.loads(raw)["total"],58)

    def test_augment_catalog_search_tier_and_season(self):
        _, _, payload=self.get("/api/summary")
        self.assertGreaterEqual(json.loads(payload)["counts"]["augments"],10000)
        _, _, payload=self.get("/api/catalog")
        catalog=json.loads(payload)["items"]
        indexed=[x for x in catalog if x["kind"]=="indexed"]
        self.assertEqual(sum(x.get("augment_count",0)>0 for x in indexed),37)
        self.assertTrue(any(x["augment_count"]==0 and x["augment_status"] for x in indexed))
        from urllib.parse import urlencode
        target=next(x for x in indexed if x["name"]=="自然之力" and x["season"]=="S19")
        _, _, body=self.get("/api/records/augments?"+urlencode({"season":target["ref"],"limit":60}))
        rows=json.loads(body)
        self.assertGreater(rows["total"],250)
        self.assertTrue(all(r["赛季编号"]==target["ref"] for r in rows["items"]))
        _, _, body=self.get("/api/records/augments?"+urlencode({"season":target["ref"],"category":"金色","limit":60}))
        gold=json.loads(body)
        self.assertGreater(gold["total"],75)
        self.assertTrue(all(r["官方等级"]=="2" for r in gold["items"]))
        _, _, body=self.get("/api/records/augments?"+urlencode({"category":"special","limit":60}))
        special=json.loads(body)
        self.assertGreater(special["total"],100)
        self.assertTrue(all(r["官方等级"] not in ("1","2","3") for r in special["items"]))
        _, _, body=self.get("/api/records/augments?"+urlencode({"q":"存心失利","limit":10}))
        found=json.loads(body)
        self.assertGreater(found["total"],0)
        self.assertTrue(all("存心失利" in r["强化名称"] for r in found["items"]))

    def test_web_assets_and_security_boundary(self):
        for uri, token in (("/", b"ALL-SEASON COMPENDIUM"), ("/gallery.js", b"fetch"), ("/gallery.css", b".sidebar")):
            code, headers, raw = self.get(uri)
            self.assertEqual(code, 200)
            self.assertIn(token, raw)
            self.assertIn("nosniff", headers["X-Content-Type-Options"])
        _, _, body = self.get("/api/catalog")
        catalog = json.loads(body)
        self.assertGreaterEqual(catalog["total"], 41)
        self.assertEqual(len([e for e in catalog["items"] if e["kind"] == "indexed"]), 41)
        self.assertTrue(any(e["name"] == "自然之力" for e in catalog["items"]))
        self.assertTrue(any(e["status"] == "unavailable" for e in catalog["items"]))
        _, _, portraits = self.get("/api/records/units?limit=60&season=" +
            "%E5%9B%BD%E6%9C%8D%C2%B7%E8%87%AA%E7%84%B6%E4%B9%8B%E5%8A%9B%EF%BD%9CS19%EF%BC%8F%E6%A8%A1%E5%BC%8F18")
        self.assertGreaterEqual(sum(bool(x.get("头像")) for x in json.loads(portraits)["items"]), 40)
        self.assertTrue(all(x["头像"].startswith("https://game.gtimg.cn/") for x in
                            json.loads(portraits)["items"] if x.get("头像")))
        for uri in ("/research_notes.json", "/tables/%E6%A3%8B%E5%AD%90.csv", "/../../research.py"):
            with self.assertRaises(HTTPError) as caught:
                self.get(uri)
            self.assertEqual(caught.exception.code, 404)
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.base + "/api/records/units", data=b"change", method="POST"), timeout=5)
        self.assertEqual(caught.exception.code, 405)

    def test_records_reload_when_csv_updated(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            for name in app.TABLES.values():
                with (path / name).open("w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.DictWriter(f, fieldnames=["赛季编号", "棋子名称", "赛季名称"])
                    writer.writeheader()
                    writer.writerow({"赛季编号": "A", "棋子名称": "ONE", "赛季名称": "demo"})
            archive = app.Archive(path)
            self.assertEqual(archive.summary()["counts"]["units"], 1)
            with (path / "棋子.csv").open("a", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["B", "TWO", "demo"])
            self.assertEqual(archive.summary()["counts"]["units"], 2)


if __name__ == "__main__":
    unittest.main()
