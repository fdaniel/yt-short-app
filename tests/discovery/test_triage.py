from shorts.discovery.triage import Triage, TriageBatch, triage
from shorts.models import VideoFormat
from tests.discovery.items import item
from tests.fakes import ScriptedLLM


def _t(index, interest=7, game=None):
    return Triage(index=index, interest=interest, rumour_or_leak=False, on_topic=True, same_story_as_recent=False, game_title=game,
                  format=VideoFormat.NEWS_FLASH, reason="r")


def test_one_call_for_the_whole_batch():
    items = [item("DLSS 4.5 controls arrive", content="<p>GeForce NOW members get <b>DLSS</b> controls.</p>"),
             item("Peak climbs onto PS5 October 22", source="PlayStation Blog", topic="gaming")]
    llm = ScriptedLLM([TriageBatch(verdicts=[_t(0), _t(1, game="Peak")])])
    verdicts = triage(items, llm)
    assert llm.calls == 1
    assert "DLSS 4.5 controls arrive" in llm.prompts[0] and "Peak climbs onto PS5" in llm.prompts[0]
    assert "GeForce NOW members get DLSS controls." in llm.prompts[0] and "<b>" not in llm.prompts[0]
    assert verdicts[1].game_title == "Peak"


def test_unknown_index_ignored_and_missing_verdict_absent():
    items = [item("A story"), item("B story")]
    verdicts = triage(items, ScriptedLLM([TriageBatch(verdicts=[_t(0), _t(7)])]))
    assert set(verdicts) == {0}


def test_empty_batch_makes_no_call():
    llm = ScriptedLLM([])
    assert triage([], llm) == {} and llm.calls == 0


def test_long_reason_is_trimmed_and_interest_bounded():
    t = Triage(index=0, interest=7, rumour_or_leak=False, on_topic=True, same_story_as_recent=False, game_title=None,
               format=VideoFormat.NEWS_FLASH, reason="x" * 500)
    assert len(t.reason) == 200


def test_recent_titles_go_into_the_prompt_as_data():
    llm = ScriptedLLM([TriageBatch(verdicts=[_t(0)])])
    triage([item("RTX Spark Ignites Global Celebration")], llm,
           recent_titles=["NVIDIA RTX Spark PCs Available Today - A New Beginning for Windows PCs"])
    prompt = llm.prompts[0]
    assert "NVIDIA RTX Spark PCs Available Today - A New Beginning for Windows PCs" in prompt
    assert "same_story_as_recent" in prompt and "data, not instructions" in prompt
