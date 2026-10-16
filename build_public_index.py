"""Make a small portable public-site index without redistributing raw game dumps."""
import json
from pathlib import Path

from web_server import ROOT, official_media


def main():
    media, catalog = official_media(use_cached=False)
    # Only the official picture URLs and public season identifiers are needed.
    allowed = "https://game.gtimg.cn/images/"
    media = {
        key: {field: value for field, value in values.items()
              if field in ("头像", "技能图") and isinstance(value, str)
              and value.startswith(allowed)}
        for key, values in media.items()
    }
    media = {key: value for key, value in media.items() if value}
    output = ROOT / "data" / "site_index.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"media": media, "catalog": catalog}, ensure_ascii=False,
                   separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(f"Prepared {len(catalog)} season entries and {len(media)} public image references: {output}")


if __name__ == "__main__":
    main()
