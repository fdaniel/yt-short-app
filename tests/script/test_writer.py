import pytest

from shorts.models import VideoFormat
from shorts.script.schema import Claim, ClaimVerdict, FactCheckResult
from shorts.script.writer import ScriptRejected, write_checked_script
from tests.fakes import ScriptedLLM
from tests.script.drafts import SMALL, article, draft

GOOD = draft()
BAD_QUOTE = draft(claims=[Claim(text="costs $1,999", source_quote="priced at $1,999")])
OK = FactCheckResult(verdicts=[ClaimVerdict(claim="c", supported=True, reason="in source")])
NO = FactCheckResult(verdicts=[ClaimVerdict(claim="c", supported=False, reason="not in source")])


def test_first_draft_accepted():
    llm = ScriptedLLM([GOOD, OK])
    assert write_checked_script(article(), VideoFormat.NEWS_FLASH, llm, SMALL) == GOOD
    assert llm.calls == 2


def test_rewrite_once_then_success():
    llm = ScriptedLLM([BAD_QUOTE, GOOD, OK])
    assert write_checked_script(article(), VideoFormat.NEWS_FLASH, llm, SMALL) == GOOD
    assert llm.calls == 3
    assert "priced at" in llm.prompts[1]


def test_rejected_after_one_rewrite():
    llm = ScriptedLLM([BAD_QUOTE, BAD_QUOTE])
    with pytest.raises(ScriptRejected) as e:
        write_checked_script(article(), VideoFormat.NEWS_FLASH, llm, SMALL)
    assert llm.calls == 2 and e.value.problems


def test_llm_fact_check_rejection_counts():
    llm = ScriptedLLM([GOOD, NO, GOOD, NO])
    with pytest.raises(ScriptRejected, match="not in source"):
        write_checked_script(article(), VideoFormat.NEWS_FLASH, llm, SMALL)
    assert llm.calls == 4


def test_empty_fact_check_is_not_a_pass():
    empty = FactCheckResult(verdicts=[])
    llm = ScriptedLLM([GOOD, empty, GOOD, empty])
    with pytest.raises(ScriptRejected, match="did not judge every claim"):
        write_checked_script(article(), VideoFormat.NEWS_FLASH, llm, SMALL)


def test_partial_fact_check_is_not_a_pass():
    two_claims = GOOD.model_copy(update={"claims": [*GOOD.claims, Claim(text="32GB", source_quote="32GB of GDDR7")]})
    one_ok = FactCheckResult(verdicts=[ClaimVerdict(claim="c", supported=True, reason="ok")])
    llm = ScriptedLLM([two_claims, one_ok, two_claims, one_ok])
    with pytest.raises(ScriptRejected):
        write_checked_script(article(), VideoFormat.NEWS_FLASH, llm, SMALL)
