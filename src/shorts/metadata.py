"""Title, description, hashtags and the rights log that travel with each video."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from shorts.models import Asset, AssetKind
from shorts.script.schema import ScriptDraft
from shorts.sources.article import Article

MAX_TITLE = 100
MAX_DESCRIPTION = 5000
MAX_HASHTAGS = 5
BANNED_WORDS = ("viral", "guarantee")
FALLBACK_HASHTAGS = ("#TechNews", "#Shorts")
_TAG = re.compile(r"#?[A-Za-z][A-Za-z0-9_]{1,29}")


@dataclass(frozen=True)
class VideoMetadata:
    title: str
    title_options: tuple[str, ...]
    description: str
    hashtags: tuple[str, ...]
    sources: tuple[str, ...]
    rights: tuple[dict, ...]


def _clean(text: str) -> str:
    return " ".join(text.replace("<", "").replace(">", "").split())


def _allowed(text: str) -> bool:
    return not any(word in text.lower() for word in BANNED_WORDS)


def _titles(draft: ScriptDraft, article: Article) -> tuple[str, ...]:
    options = [_clean(t)[:MAX_TITLE].rstrip() for t in draft.title_options]
    kept = tuple(t for t in options if t and _allowed(t))
    return kept or (_clean(article.title)[:MAX_TITLE] or "Tech news",)


def _hashtags(draft: ScriptDraft) -> tuple[str, ...]:
    """Well-formed tags only: a model sometimes leaks prose or JSON into this field."""
    tags = []
    for raw in draft.hashtags:
        for token in re.split(r"[\s,\[\]]+", raw):
            if not _TAG.fullmatch(token) or (" " in raw.strip() and not token.startswith("#")):
                continue
            tag = "#" + token.lstrip("#")
            if _allowed(tag) and tag.lower() not in {t.lower() for t in tags}:
                tags.append(tag)
    return tuple(tags[:MAX_HASHTAGS]) or FALLBACK_HASHTAGS


def _credits(article: Article, assets: list[Asset]) -> list[str]:
    lines = [f"Source: {article.url}"]
    media = [a for a in assets if a.kind in (AssetKind.TRAILER, AssetKind.SCREENSHOT)]
    for holder, platform in dict.fromkeys((a.rightsholder, a.source_platform) for a in media):
        lines.append(f"Footage: {_clean(holder)} ({platform})")
    lines += [f"Stock footage: {_clean(a.rightsholder)} via {a.source_platform.capitalize()} ({a.source_url})"
              for a in assets if a.kind == AssetKind.STOCK_VIDEO]
    lines += [f"Music: {_clean(a.notes)}" for a in assets if a.kind == AssetKind.MUSIC]
    return lines


def _rights(assets: list[Asset]) -> tuple[dict, ...]:
    return tuple(
        {
            "kind": a.kind.value,
            "source_url": a.source_url,
            "rightsholder": a.rightsholder,
            "rights_basis": a.rights_basis.value,
            "licence_terms_ref": a.licence_terms_ref,
        }
        for a in assets
    )


def build_metadata(draft: ScriptDraft, article: Article, assets: list[Asset]) -> VideoMetadata:
    titles = _titles(draft, article)
    hashtags = _hashtags(draft)
    tail = "\n\n" + "\n".join(_credits(article, assets)) + ("\n\n" + " ".join(hashtags) if hashtags else "")
    body = _clean(draft.description)[: MAX_DESCRIPTION - len(tail)]
    return VideoMetadata(
        title=titles[0],
        title_options=titles,
        description=body + tail,
        hashtags=hashtags,
        sources=(article.url,),
        rights=_rights(assets),
    )


def write_metadata(meta: VideoMetadata, path: Path) -> Path:
    path.write_text(json.dumps(asdict(meta), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def content_hash(video_path: Path, meta: VideoMetadata) -> str:
    digest = hashlib.sha256()
    with video_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    digest.update(json.dumps(asdict(meta), sort_keys=True).encode())
    return digest.hexdigest()
