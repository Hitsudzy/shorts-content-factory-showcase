"""CF-0752: why a fact candidate was refused, in plain Russian.

`fact_rule.check_candidate` answers with codes from `fact_rule.FAIL_CODES`
(`no_url`, `cut_short`, ...). The command center (CC-0119) shows the user why
a fact was refused, and the user does not read codes - this module is the
dictionary from a code to a short reason, each worded after what the check in
`fact_rule.py` really does.

Why a separate file: `fact_rule.py` is copied byte for byte into the
trend-hunter repository (tests/test_fact_rule_copies.py), so a dictionary
added there would have to land in two repositories at once. This module only
reads `FAIL_CODES` from its neighbour; `set(FAIL_CODES_RU) == set(FAIL_CODES)`
is pinned by tests/test_fact_rule_ru.py, so a new code without a Russian
reason fails there.

Stdlib only; loaded by path like every module of shared/factrule/.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# CF-0231: a neighbour loads this file by path; register the directory before
# naming the sibling, as every module of shared/runlog/ does.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import fact_rule  # noqa: E402

FAIL_CODES = fact_rule.FAIL_CODES

FAIL_CODES_RU = {
    fact_rule.FAIL_NO_TEXT: "у факта нет текста",
    fact_rule.FAIL_NO_URL: "нет ссылки на источник",
    fact_rule.FAIL_SOURCE_BANNED: "источник из списка запрещённых для канала",
    fact_rule.FAIL_SOURCE_UNLISTED: "источника нет в списке разрешённых для канала",
    fact_rule.FAIL_TIER2_WITHOUT_PRIMARY: "источник второго ряда, а ссылки на "
                                          "первоисточник из основного списка нет",
    fact_rule.FAIL_INTERVIEW_WITHOUT_QUOTE: "интервью без дословной цитаты",
    fact_rule.FAIL_NO_SPECIFICS: "нет конкретики (числа, даты или имени) - "
                                 "похоже на мнение",
    fact_rule.FAIL_RETELLS_NEWS: "пересказывает новость и не добавляет к ней "
                                 "ничего нового",
    fact_rule.FAIL_PERSON_NOT_MAJOR_OUTLET: "факт о реальном человеке взят не из "
                                            "крупного издания",
    fact_rule.FAIL_PERSON_UNATTRIBUTED: "факт о реальном человеке без указания, "
                                        "кто это сообщил",
    fact_rule.FAIL_CUT_SHORT: "предложение обрезано",
}


def reason_ru(code):
    """The Russian reason for a refusal code; an unknown code comes back as
    it is (never an exception - the center shows something either way)."""
    try:
        return FAIL_CODES_RU.get(code, code)
    except TypeError:               # an unhashable "code" - still no exception
        return code
