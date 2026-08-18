from app.services.completion import decide_completion


def evaluation(score: str, level: str = "Understand") -> dict[str, str]:
    return {"score": score, "level": level}


def test_never_completes_before_minimum_turns():
    decision = decide_completion([evaluation("High"), evaluation("High")], 2)
    assert not decision.complete


def test_completes_at_three_for_strong_recent_knowledge():
    decision = decide_completion([evaluation("Low"), evaluation("Medium"), evaluation("High")], 3)
    assert decision.complete
    assert decision.reason == "knowledge_threshold"


def test_completes_at_four_for_consistent_medium_knowledge():
    decision = decide_completion([evaluation("Medium")] * 4, 4)
    assert decision.complete
    assert decision.reason == "knowledge_threshold"


def test_low_or_missing_evaluations_continue_until_cap():
    assert not decide_completion([evaluation("Low")] * 5, 5).complete
    assert not decide_completion([None] * 5, 5).complete
    decision = decide_completion([evaluation("Low")] * 6, 6)
    assert decision.complete
    assert decision.reason == "max_turns"


def test_stale_good_evaluations_do_not_end_after_unrated_answer():
    decision = decide_completion([evaluation("High"), evaluation("High"), None], 3)
    assert not decision.complete
