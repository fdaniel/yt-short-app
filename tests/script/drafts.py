from shorts.config import VideoSettings
from shorts.script.schema import Claim, ScriptDraft
from shorts.sources.article import Article

SOURCE = "The RTX 5090 launches January 30, 2025 at $1,999. It has 32GB of GDDR7 memory."

SMALL = VideoSettings(min_words=5, max_words=140)


def article(text: str = SOURCE, url: str = "https://nvidianews.nvidia.com/x") -> Article:
    return Article(url=url, title="RTX 5090", text=text, domain="nvidianews.nvidia.com")


def draft(**overrides) -> ScriptDraft:
    fields = dict(
        hook="The RTX 5090 is official.",
        body=["It launches January 30.", "It costs $1,999.", "It has 32GB of GDDR7 memory."],
        closing="Would you buy one?",
        title_options=["RTX 5090: price and date", "RTX 5090 is official", "RTX 5090 launch"],
        description="NVIDIA's new flagship GPU.",
        hashtags=["#nvidia", "#rtx5090", "#gpu"],
        claims=[Claim(text="launches January 30, 2025 at $1,999", source_quote="launches January 30, 2025 at $1,999")],
        card_facts=[],
    )
    fields.update(overrides)
    return ScriptDraft(**fields)

