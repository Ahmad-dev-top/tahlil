import pytest

from app.guards import check_report, check_sql

TABLES = ["sales"]


@pytest.mark.parametrize("sql", [
    "SELECT region, SUM(revenue_pkr) AS revenue FROM sales GROUP BY region",
    "WITH m AS (SELECT date_trunc('month', order_date) AS mo, SUM(units) u FROM sales GROUP BY 1) SELECT * FROM m ORDER BY mo",
    "SELECT category, COUNT(*) FROM sales WHERE channel = 'WhatsApp' GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
])
def test_safe_sql_passes(sql):
    assert check_sql(sql, TABLES).passed


@pytest.mark.parametrize("sql,reason", [
    ("DROP TABLE sales", "Only SELECT"),
    ("DELETE FROM sales", "Only SELECT"),
    ("SELECT 1 FROM sales; DROP TABLE sales", "exactly 1 statement"),
    ("COPY sales TO '/tmp/x.csv'", "Only SELECT"),
    ("SELECT * FROM read_csv('/etc/passwd')", "read_csv"),
    ("SELECT * FROM '/etc/passwd'", "Unknown table"),
    ("SELECT getenv('HOME') FROM sales", "getenv"),
    ("SELECT * FROM customers", "Unknown table"),
    ("SELEC broken", ""),
])
def test_unsafe_sql_blocked(sql, reason):
    outcome = check_sql(sql, TABLES)
    assert not outcome.passed
    assert reason in " ".join(outcome.errors)


def test_grounded_report_passes():
    report = "## Answer\nPunjab led with PKR 17,250,400 (38.2%) of PKR 45.15M total.\n1. Top 3 regions covered most sales."
    assert check_report(report, [17250400, 0.382, 45151248]).passed


def test_rounding_tolerance_follows_written_precision():
    facts = [0.38196, 45151248]
    assert check_report("Share 38.2%, total PKR 45.15M", facts).passed
    assert check_report("Share 38%, total PKR 45M", facts).passed
    assert not check_report("Share 42%", facts).passed          # near-miss is NOT grounded
    assert not check_report("Total PKR 45.9M", facts).passed
    assert check_report("Margin was 42%", [42.0]).passed          # column already in percent


def test_hallucinated_number_fails():
    outcome = check_report("Revenue grew 23% to PKR 52,000,000.", [45151248, 0.12])
    assert not outcome.passed
    assert "23%" in outcome.errors[0] and "52,000,000" in outcome.errors[0]


def test_iso_date_passes_only_when_present_in_results():
    report = "The series runs through 2025-12-31 and totals PKR 16,778,782."
    assert check_report(report, [16778782], dates=["2025-12-31"]).passed
    assert check_report(report, [16778782], dates=["2025-12-31T00:00:00"]).passed
    missing = check_report(report, [16778782])
    assert not missing.passed
    assert "Report cites dates not found in the results: 2025-12-31." in missing.errors[0]
    assert "16,778,782" not in missing.errors[0]
