#!/usr/bin/env python3
"""Validate the static project site before GitHub Pages deployment."""

from __future__ import annotations

import json
import struct
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PAGES = (SITE / "index.html", SITE / "zh" / "index.html")
EXPECTED_CANONICALS = {
    "https://fuhehe12.github.io/cc-wire-analyzer/",
    "https://fuhehe12.github.io/cc-wire-analyzer/zh/",
}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.h1_count = 0
        self.ids: set[str] = set()
        self.links: list[tuple[str, str]] = []
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.hreflangs: dict[str, str] = {}
        self.json_ld: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []
        self._json_ld_parts: list[str] | None = None

    @property
    def title(self) -> str:
        return "".join(self._title_parts).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "h1":
            self.h1_count += 1
        if values.get("id"):
            self.ids.add(values["id"])
        if tag in {"a", "link"} and values.get("href"):
            self.links.append(("href", values["href"]))
        if tag in {"img", "script"} and values.get("src"):
            self.links.append(("src", values["src"]))
        if tag == "meta":
            key = values.get("name") or values.get("property")
            if key:
                self.meta[key] = values.get("content", "")
        if tag == "link":
            rel = values.get("rel", "").split()
            if "canonical" in rel:
                self.canonical = values.get("href", "")
            if "alternate" in rel and values.get("hreflang"):
                self.hreflangs[values["hreflang"]] = values.get("href", "")
        if tag == "title":
            self._in_title = True
        if tag == "script" and values.get("type") == "application/ld+json":
            self._json_ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._json_ld_parts is not None:
            self.json_ld.append("".join(self._json_ld_parts))
            self._json_ld_parts = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._json_ld_parts is not None:
            self._json_ld_parts.append(data)


def check_page(path: Path) -> list[str]:
    errors: list[str] = []
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(f"{path.relative_to(ROOT)}: {message}")

    require(bool(parser.title), "missing <title>")
    require(parser.h1_count == 1, f"expected one <h1>, found {parser.h1_count}")
    require(bool(parser.meta.get("description")), "missing meta description")
    require(parser.meta.get("robots", "").lower() != "noindex", "page is noindex")
    require(parser.canonical in EXPECTED_CANONICALS, "unexpected or missing canonical URL")
    require(set(parser.hreflangs) == {"en", "zh-CN", "x-default"}, "incomplete hreflang set")
    require(parser.meta.get("og:type") == "website", "missing Open Graph type")
    require(parser.meta.get("og:image", "").endswith("/assets/social-preview.png"), "missing social preview")
    require(parser.meta.get("twitter:card") == "summary_large_image", "missing Twitter card")
    require(bool(parser.json_ld), "missing JSON-LD")
    for document in parser.json_ld:
        try:
            payload = json.loads(document)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid JSON-LD ({exc})")
            continue
        require(payload.get("@type") == "SoftwareApplication", "unexpected JSON-LD type")

    for attribute, value in parser.links:
        parsed = urlparse(value)
        if parsed.scheme or value.startswith("//"):
            continue
        if value.startswith("#"):
            require(value[1:] in parser.ids, f"broken page anchor {value!r}")
            continue
        target = (path.parent / parsed.path).resolve()
        require(target.exists(), f"broken local {attribute} {value!r}")
    return errors


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) != 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    return struct.unpack(">II", data[16:24])


def main() -> int:
    errors = [error for page in PAGES for error in check_page(page)]
    try:
        dimensions = png_dimensions(SITE / "assets" / "social-preview.png")
        if dimensions != (1280, 640):
            errors.append(f"social preview must be 1280x640, found {dimensions[0]}x{dimensions[1]}")
    except (OSError, ValueError) as exc:
        errors.append(f"invalid social preview: {exc}")

    sitemap = ElementTree.parse(SITE / "sitemap.xml")
    urls = {element.text for element in sitemap.findall("{*}url/{*}loc")}
    if urls != EXPECTED_CANONICALS:
        errors.append("sitemap URLs do not match the bilingual canonical URLs")
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    if "Sitemap: https://fuhehe12.github.io/cc-wire-analyzer/sitemap.xml" not in robots:
        errors.append("robots.txt does not advertise the sitemap")

    if errors:
        print("Static site audit failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Static site audit passed: bilingual metadata, links, sitemap, and 1280x640 social preview are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
