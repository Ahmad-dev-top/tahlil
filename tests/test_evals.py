import pandas as pd

from evals.run import main, score, score_unanswerable


def test_score_accepts_extra_rows_and_percent_form():
    ref = pd.DataFrame({"channel": ["WhatsApp"], "share": [0.2512]})
    agent = pd.DataFrame({"channel": ["Website", "WhatsApp"], "share_pct": [45.0, 25.12]})
    assert score(agent, ref) == (True, "ok")


def test_score_rejects_wrong_answers():
    ref = pd.DataFrame({"region": ["Punjab"], "orders": [312]})
    assert not score(pd.DataFrame({"region": ["Sindh"], "orders": [312]}), ref)[0]
    assert not score(pd.DataFrame({"region": ["Punjab"], "orders": [300]}), ref)[0]
    assert not score(None, ref)[0]


def test_unanswerable_requires_a_grounded_refusal():
    phrase = "The dataset does not contain a cost column, so margin is not available."
    assert score_unanswerable("ok", True, phrase) == (True, "ok")
    assert score_unanswerable("ok", True, "We CANNOT compute this.")[0]
    assert not score_unanswerable("failed", True, phrase)[0]
    assert not score_unanswerable("ok", False, phrase)[0]
    assert not score_unanswerable("ok", True, "Punjab leads with PKR 100.")[0]


def test_harness_self_check_scores_100(tmp_path):
    assert main(["--fake", "--min-accuracy", "1.0", "--out", str(tmp_path)]) == 0
