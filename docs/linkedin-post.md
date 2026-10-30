I built a data analyst that answers a question about a CSV and then checks its own numbers.

You ask in plain English. It writes SQL, runs it read-only, draws a chart inside a Docker container with no network, and writes a short report. A guard rejects anything that is not a single SELECT on a known table. A second check compares every figure in the report to the query result. If that check fails, the answer is marked unverified and the reason is shown.

On a 23-question set I used while writing the prompts, Claude Haiku 5.5 with a two-role writing crew scored 100% accuracy and 100% verified, at about $0.002 per question and a median of 31 seconds. I then froze the prompts and scored 10 new questions: 90% accuracy and 90% verified. The miss was a question about city, and the file has no city column. Three repeats of the first set stayed at 100% accuracy and 100% verified. First-try reports moved between 91% and 96%.

Live demo: https://tahlil.muhammad-dgr.duckdns.org

A 25-second recording of one question (steps, verified report, chart, SQL): https://github.com/Ahmad-dev-top/tahlil/blob/main/docs/demo.gif

Code: https://github.com/Ahmad-dev-top/tahlil
