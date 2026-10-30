# AI data analyst for your database

## Overview

I install an analyst on your server. Your team uploads a CSV, or I connect a read-only snapshot of Postgres or MySQL, and they ask questions in plain English. Each answer returns the SQL, the result table, a chart, and a short report. The SQL is checked before it runs: one SELECT, known tables only, no file or system functions, on a connection opened read-only. The chart code runs in a Docker container with no network, a read-only filesystem, and every capability dropped. Every number in the report is checked against the query result, and an answer that fails that check is marked unverified with the reason. On my sample sales file, Claude Haiku 5.5 plus a two-role writing crew averaged about $0.002 per question. A 10-question held-out set, scored after the prompts were frozen, came in at 90% accuracy and 90% verified. You keep the code and the deployment notes.

## Packages

Prices are `[PRICE]` until we scope your data and host.

### Starter — CSV analyst on your server — [PRICE]

Deliverables:

- The Tahlil app on a server you control, with Docker Compose
- CSV upload, plain-English questions, SQL, table, chart, and report
- The SQL guard, the read-only database connection, and the sandbox, with the flags left intact
- The number check on the report, and the step trace in the UI
- A short runbook: how to start it, where the data lives, how to rotate the API key

Timeline: 1 week after I have the host and a sample CSV.

### Standard — Starter, plus your database and your branding — [PRICE]

Deliverables, in addition to Starter:

- A read-only snapshot connector for Postgres or MySQL, including a refresh path
- Your name, logo, and colors on the web app
- The sample questions on the home screen rewritten for your schema

Timeline: 2 weeks after Starter’s inputs, plus a read-only database user and a logo.

### Premium — Standard, plus your questions, deploy, and two weeks of support — [PRICE]

Deliverables, in addition to Standard:

- A custom eval file of your questions, with reference SQL where you can provide the expected numbers, scored the same way as the public set (accuracy, verified rate, first-try rate, latency, cost)
- Deploy onto the host you name, with HTTPS in front and the API bound to localhost
- Two weeks of support after go-live: bug fixes in the deployed app, and one pass of prompt edits measured on your eval file

Timeline: 3–4 weeks. The eval pass starts once you send the question list and the expected answers.
