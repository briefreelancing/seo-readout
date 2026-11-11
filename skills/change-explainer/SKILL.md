---
name: readout-change-explainer
description: Diagnose why website traffic, clicks or conversions changed, using GA4, Google Search Console and Google Ads exports. Answers in order: is the change real or a tracking issue, is it unusual or seasonal, where is it concentrated (pages, queries, channels), what kind of change it is (ranking loss, demand, SERP change, brand), when it started and which site events or Google updates it coincides with, and what to check next. Produces a chat summary, charts and a client-ready report. Use when someone asks why traffic dropped or spiked, or wants a traffic change explained to a client.
---

# Readout: change explainer

Answers "why did traffic change?" the way a careful SEO consultant would, in six steps,
and turns the answer into something a client can read.

**Core rule: the scripts calculate, you explain.** Every number you write must come from
`findings.json`. If you need a number that isn't there, compute it with Python first.
`render_report.py` refuses to build the report if the narrative contains a number it
can't trace back to `findings.json`.

## What the user needs to provide

| Input | Needed for | Notes |
|---|---|---|
| Search Console export(s) | Steps 1 to 6 | For pages and queries: one export for the current period and one for the previous period. For trend and year-ago: a 16-month export. All zips can be uploaded together. |
| GA4 export with a Date column | Tracking checks, channel breakdown | Optional but recommended |
| Google Ads export with the Day segment | Paid checks | Optional |
| Brand terms | Branded vs non-branded split | Ask for them. Example: "acme, acme co, acmeco" |
| Event log | Matching the trend shift to known events | Optional CSV: `date,end_date,type,description`. Template in `templates/events_template.csv`. Offer to build it from what the user tells you (launches, migrations, redesigns, campaigns, tracking changes, outages). |

If the user has no exports yet, use `references/exporting-data.md`. Menu paths there may
have changed; say so if a step doesn't match.

## Workflow

1. **Check the uploads** and say what you found. If page or query breakdowns can't be compared
   (only one period exported), say what to export, but continue: steps 1, 2, 4 (site level) and 5
   still work.
2. **Ask for brand terms** and **known events** in one short message, if the user hasn't given them.
   If they want to skip, continue without.
3. **Run the analysis.** Install `pandas`, `numpy`, `matplotlib` and `openpyxl` if missing.

   ```bash
   python <this-skill-folder>/scripts/explain.py <exports...> --out readout_explain \
     --brand-terms "acme,acme co" --events events.csv --client "Client name"
   ```

   Options: `--metric auto|gsc_clicks|ga4_sessions|ga4_organic|ga4_conversions|ads_clicks`
   (auto picks Search Console clicks if available), `--current-start/--current-end`,
   `--previous-start/--previous-end`, `--days 28`, `--match-days 3`, `--event-lag-days 14`.
   The default periods are the last 28 days against the 28 days before, plus the same weekdays
   a year earlier. The user can override them.
4. **Read `readout_explain/findings.json`** and write the chat summary (format below).
5. **Offer the client report.** If the user wants it:
   - Write `readout_explain/narrative.json` following `templates/narrative_template.json`.
   - Run `python <this-skill-folder>/scripts/check_narrative.py readout_explain/findings.json readout_explain/narrative.json`
     and fix any number it flags.
   - Run `python <this-skill-folder>/scripts/render_report.py --findings readout_explain/findings.json --narrative readout_explain/narrative.json --out readout_explain/report.html`
   - Send `report.html` and the charts. The HTML is self-contained; it prints cleanly to PDF from a browser.

## How to read findings.json

| Key | What it holds | How to use it |
|---|---|---|
| `q1_is_it_real` | `verdict`, `verdict_text`, `checks`, `tracking_gap_effect` | Lead with the verdict. A flag in a source other than the focus metric is a side issue: mention it, but don't let it override the verdict. |
| `q2_is_it_unusual` | change vs previous and year ago, typical range, z-score, `matches_last_year_pattern` | "Unusual" means outside this site's normal swings. If `matches_last_year_pattern` is true, call out seasonality. |
| `q3_where` | `breakdowns` per dimension: top declines and gains, share of net change, `top3_share_of_all_declines_pct`; `stopped_ads_campaigns`; `unavailable` | Name the few items driving the change, with their share. Mention any Ads campaign that stopped getting clicks. |
| `q4_what_kind` | site `pattern`, numbers, `click_change_split`, `top_declining_pages`, `top_gaining_pages`, `brand_split` | Translate the pattern into plain words (see below). For a gain, use `top_gaining_pages`. |
| `q5_when` | `change_point` (date, before and after averages, strength), `matches` (each with `relation` and `days_from_change_point`), `weak_shift_note`, `update_list_warning` | Give the date and what it lines up with (see the writing rules). |
| `q6_next_checks` | Suggested checks with `confidence` and `why` | Present the high ones first. You may reword, not add new claims. |
| `data_health` | Warnings about the data | Mention any that affect conclusions. |

Pattern meanings:
- `ranking_loss`: average position got worse, so fewer people see and click the result.
- `ranking_gain`: average position improved, so more people see and click the result.
- `higher_demand_or_visibility`: more searches showed the site while position held. Check seasonality and demand.
- `lower_demand_or_visibility`: fewer searches showed the site while position held. Check seasonality and demand.
- `serp_change`: impressions and position held but fewer clicks. Something on the results page may be taking clicks (features, AI answers), or titles became less appealing.
- `mixed`: no single pattern. Say so.

## Writing rules

- **Coincides with, never caused by.** Matching dates show timing only. Say "the shift coincides
  with the site redesign on October 5", never "the redesign caused the drop". Google updates get
  the most caution: many sites move during an update for unrelated reasons.
- **Match the wording to `relation`.** `coincides with`: the shift is within a few days of the
  event. `follows`: the shift began `days_from_change_point` days after an event from the user's
  log, as site changes often take time to show in search. Say "the gain began 8 days after the
  page refresh on October 15", never "the refresh caused the gain". If `weak_shift_note` is
  present, say the timing match is less reliable.
- **Lead with the answer**, then the evidence. One idea per sentence. Plain words; expand jargon
  (CTR, SERP) on first use.
- **Average position: lower is better.** Report position changes in points, not percent.
- **No new numbers.** No mental math, no rounding beyond one decimal, no "roughly double" unless a
  number in findings supports it.
- **Be honest about limits.** If breakdowns were unavailable, the brand split was skipped, or
  `update_list_warning` is present, say so.
- If `q1` says `likely_tracking`, the story is about tracking, not SEO. Don't diagnose rankings
  from broken data.

## Chat summary format

```
**Short answer:** <one or two sentences: what changed, how much, most likely driver, when>

1. **Real?** <verdict + key evidence>
2. **Unusual?** <change vs typical range and last year>
3. **Where?** <top items and their share>
4. **What kind?** <pattern in plain words + 2 numbers>
5. **When?** <date + what it coincides with>
6. **Check next:** <top 2 to 3 checks>

<one line on any data caveats>
Want the client-ready report?
```

## Known limits

- Export formats come from commonly seen layouts and were tested on synthetic data. Anything the
  loader can't read is listed in `data_health`; tell the user which file and why.
- Thresholds (in `findings.json` under `thresholds`) are rules of thumb, not industry standards.
- The trend-shift finder looks for the single biggest shift in the last 120 days. Gradual declines
  or several shifts can be summarized poorly; look at the trend chart before writing.
- The Google update list (`references/google_updates.csv`) is maintained by hand. Check its
  `last_updated` date; the skill warns when the shift is newer than the list.
- The number check confirms each number exists in findings.json. It cannot confirm the number is
  attached to the right claim, so read your narrative once against the tables.
