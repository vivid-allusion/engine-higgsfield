#!/usr/bin/env python3
"""Build the Higgsfield catalogue from the provider's own documentation.

Higgsfield publishes one page per workflow, each carrying its endpoint and an
"Input schema" section in prose. The OpenAPI file is supplementary (their words)
and lists only a handful of models, so the pages are the source of truth.

    python scripts/build_catalogue.py --out engine_higgsfield/endpoints

Every entry it writes carries `api_path`, because Higgsfield submits to a
different path per model. Anything it cannot read is skipped and reported, never
guessed.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path

BASE = "https://docs.higgsfield.ai"
INDEX = {
    "/docs/models/image-generation.md": "IMG",
    "/docs/models/video-generation.md": "VID",
}
LINK = re.compile(r"https://docs\.higgsfield\.ai/docs/models/[a-z0-9/\-]+\.md")
ENDPOINT = re.compile(r"\*\*Endpoint:\*\*\s*`POST\s+(https://api\.higgsfield\.ai/\S+)`")
TITLE = re.compile(r"^#\s+(.+)$", re.M)
FIELD = re.compile(r"^\*\*(.+?)\*\*\s*`?([a-z]+)?`?", re.M)

MEDIA_WORDS = ("image", "video", "audio", "frame", "mask")
SKIP_FIELDS = {"webhook_url", "callback_url", "metadata", "idempotency_key"}
TYPE_MAP = {"string": "text", "integer": "integer", "number": "number", "boolean": "boolean"}


def fetch(url: str, cache: Path, tries: int = 3) -> str:
    name = cache / url.replace(BASE + "/", "")
    name.parent.mkdir(parents=True, exist_ok=True)
    if name.is_file() and name.stat().st_size > 0:
        return name.read_text(encoding="utf-8")
    last: Exception | None = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                text = response.read().decode("utf-8", "replace")
            name.write_text(text, encoding="utf-8")
            return text
        except Exception as exc:  # noqa: BLE001 - retried, then reported
            last = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"could not fetch {url}: {last}")


def category_for(api_path: str) -> str | None:
    """Decide the family from the endpoint itself, never from the page it was found on.

    The documentation index links across families (a video model appears under
    the image branch), so inheriting the category from the traversal put
    image-to-video models in the image catalogue. The path is the reliable
    signal.
    """
    path = api_path.lower()
    if any(word in path for word in ("custom-reference", "soul-id", "training")):
        return None
    if any(
        word in path
        for word in ("video", "genjutsu", "motion-transfer", "object-swap", "restyle", "frame")
    ):
        return "VID"
    if any(
        word in path
        for word in (
            "image",
            "soul",
            "recraft",
            "ideogram",
            "z-image",
            "qwen",
            "marketing-studio",
            "ads-studio",
            "cinema-studio",
            "grok-imagine-image",
        )
    ):
        return "IMG"
    return None


def slug_for(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    slug = "-".join(parts).lower()
    slug = slug.replace(".", "-")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:70]


def clean(text: str) -> str:
    return text.replace("\\", "").strip()


def parse_schema(section: str) -> tuple[dict, str, list[str], list[str], str, list[str]]:
    """Return (params, media key, slots, media lists, prompt mode, notes)."""
    blocks = re.split(r"\n(?=\*\*)", section)
    params: dict = {}
    media: list[str] = []
    lists: list[str] = []
    notes: list[str] = []
    prompt = "none"

    for block in blocks:
        match = FIELD.match(block.strip())
        if not match:
            continue
        name = clean(match.group(1)).strip()
        if any(mark in name for mark in ("[", "]", ".")) or name.lower().startswith("nested"):
            # The docs list nested sub-fields (``multi_prompt[].prompt``) under
            # the parent. They are not top-level inputs and must never become a
            # catalogue key — the provider rejects the whole request.
            continue
        kind = (match.group(2) or "").lower()
        header = block.splitlines()[0]
        if name in SKIP_FIELDS:
            notes.append(f"{name} is integration plumbing — left out")
            continue
        if name == "prompt":
            prompt = "required"
            continue
        if kind == "array" and "items" not in block.lower():
            notes.append(f"{name} is a structured list — left out")
            continue
        if kind not in TYPE_MAP:
            notes.append(f"{name} has type {kind or 'unknown'} — left out")
            continue

        lowered = name.lower()
        is_media = any(word in lowered for word in MEDIA_WORDS) and (
            "url" in lowered or "uri" in lowered
        )
        if is_media:
            media.append(name)
            if kind == "array" or lowered.endswith(("urls", "images", "videos")):
                lists.append(name)
            continue

        entry: dict = {"type": TYPE_MAP[kind]}
        default = re.search(r"\(default:\s*([^)]+)\)", header)
        allowed = re.search(r"Allowed values?:\s*(.+)", block)
        if allowed:
            values = [clean(value).strip('"').strip("`") for value in re.findall(r"`([^`]+)`", allowed.group(1))]
            if values:
                entry["type"] = "select"
                entry["options"] = values
        if default:
            value = default.group(1).strip().strip('"').strip("`")
            if entry["type"] == "select" and value in entry.get("options", []):
                entry["default"] = value
            elif entry["type"] == "integer":
                try:
                    entry["default"] = int(value)
                except ValueError:
                    pass
            elif entry["type"] == "number":
                try:
                    entry["default"] = float(value)
                except ValueError:
                    pass
            elif entry["type"] == "boolean":
                entry["default"] = value.lower() in ("true", "on", "yes", "1")
            else:
                entry["default"] = value
        low = re.search(r"Minimum:\s*`?([0-9.]+)`?", block)
        high = re.search(r"Maximum:\s*`?([0-9.]+)`?", block)
        if low:
            entry["min"] = float(low.group(1)) if "." in low.group(1) else int(low.group(1))
        if high:
            entry["max"] = float(high.group(1)) if "." in high.group(1) else int(high.group(1))
        if entry["type"] == "select" and "default" not in entry:
            entry["default"] = entry["options"][0]
        params[name] = entry

    media_key = media[0] if media else ""
    return params, media_key, media[1:], lists, prompt, notes


def render(entry: dict) -> str:
    lines = [
        f'id = "{entry["id"]}"',
        f'label = "{entry["label"]}"',
        f'category = "{entry["category"]}"',
        'platform = "higgsfield"',
        f'endpoint = "{entry["endpoint"]}"',
        f'api_path = "{entry["api_path"]}"',
        f'description = "{entry["description"]}"',
        "",
        "[pricing]",
        'note = "unset — take the price from the provider\'s own page before shipping"',
        "",
        "[general]",
        f'kind = "{entry["kind"]}"',
        f'prompt = "{entry["prompt"]}"',
    ]
    if entry["media"]:
        lines.append(f'image_url_param = "{entry["media"]}"')
    if entry["slots"]:
        lines.append("slots = [" + ", ".join(f'"{slot}"' for slot in entry["slots"]) + "]")
    if entry["lists"]:
        lines.append("media_lists = [" + ", ".join(f'"{key}"' for key in entry["lists"]) + "]")
    if entry["duration"]:
        lines.append(f'duration_param_name = "{entry["duration"]}"')
    for name, param in entry["params"].items():
        lines += ["", f"[params.{name}]", f'label = "{name.replace("_", " ").title()}"']
        lines.append(f'type = "{param["type"]}"')
        if "default" in param:
            lines.append(f"default = {toml(param['default'])}")
        if "min" in param:
            lines.append(f"min = {toml(param['min'])}")
        if "max" in param:
            lines.append(f"max = {toml(param['max'])}")
        if param["type"] == "select":
            lines.append("options = [")
            for option in param["options"]:
                lines.append(f'  {{ value = {toml(option)}, label = {toml(option)} }},')
            lines.append("]")
    return "\n".join(lines) + "\n"


def toml(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return '"' + str(value).replace('"', "'") + '"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="engine_higgsfield/endpoints")
    parser.add_argument("--cache", default=".cache/higgsfield-docs")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)

    cache = Path(args.cache)
    out = Path(args.out)
    queue = deque((path, category, 0) for path, category in INDEX.items())
    seen: set[str] = set()
    written: list[str] = []
    skipped: list[tuple[str, str]] = []

    while queue and len(seen) < args.limit:
        path, category, depth = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        try:
            text = fetch(BASE + path, cache)
        except RuntimeError as exc:
            skipped.append((path, str(exc)))
            continue

        endpoint = ENDPOINT.search(text)
        if endpoint is None:
            for link in LINK.findall(text):
                child = link.replace(BASE, "")
                if child not in seen and depth < 4:
                    queue.append((child, category, depth + 1))
            continue

        title = TITLE.search(text)
        label = clean(title.group(1)) if title else path.rsplit("/", 1)[-1]
        section = re.search(r"## Input schema(.*?)(?=\n## |\Z)", text, re.S)
        params, media, slots, lists, prompt, notes = parse_schema(section.group(1) if section else "")
        api_path = endpoint.group(1).replace("https://api.higgsfield.ai", "")
        family = category_for(api_path)
        if family is None:
            skipped.append((api_path, "not a generation endpoint (training or reference workflow)"))
            continue
        slug = slug_for(api_path)
        entry = {
            "id": slug,
            "label": label,
            "category": family,
            "endpoint": f"higgsfield/{slug}",
            "api_path": api_path,
            "description": label.replace('"', "'"),
            "kind": "video" if family == "VID" else "image",
            "prompt": prompt,
            "media": media,
            "slots": slots,
            "lists": lists,
            "duration": "duration" if "duration" in params else "",
            "params": params,
        }
        target = out / f"{family}-Models" / f"{slug}.toml"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            skipped.append((path, f"duplicate api path {api_path}"))
            continue
        target.write_text(render(entry), encoding="utf-8")
        written.append(f"{family} {api_path}")
        for note in notes:
            skipped.append((f"{api_path} {note}", "left out"))

    print(f"wrote {len(written)} entries to {out}")
    for line in written:
        print("  +", line)
    if skipped:
        print(f"\n{len(skipped)} note(s):")
        for path, reason in skipped:
            print("  -", path, "—", reason)
    return 0 if written else 2


if __name__ == "__main__":
    sys.exit(main())
