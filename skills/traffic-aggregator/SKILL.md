---
name: readout-traffic-aggregator
description: Merge GA4, Google Search Console and Google Ads exports into one clean table, with a data health check, channel summary, side-by-side comparison of numbers that never match (GSC clicks vs GA4 sessions, Ads clicks vs GA4 paid sessions), an Excel workbook and charts. Use when someone uploads marketing analytics exports and wants them combined, summarized or reconciled, or asks why GA4, Search Console and Google Ads numbers differ.
---

# Readout: traffic aggregator

Turns raw exports into one trustworthy dataset and a short, plain-language readout.
Built for consultants who report on one client at a time.

**Core rule: the script does every calculation. You write the words.** Every number you
say or write must come from `aggregate_summary.json` or from a file the script wrote.
If you need a number that is not there, compute it with Python on those files. Never
do arithmetic in your head, round differently, or estimate.

## Inputs

Native exports, exactly as downloaded. Users should not reformat anything.

| Source | What works | Notes |
|---|---|---|
| Search Console | The Performance export zip, or its CSVs | The daily table (`Chart.csv` or `Dates.csv`) gives the trend. Several zips can be combined. |
| GA4 | CSV export from an Exploration or report | Needs a Date column for trends. Channel or source / medium columns give the channel split. |
| Google Ads | Campaign report CSV | Needs the Day segment for trends. Campaign type improves channel mapping. |

Any subset works. Search Console alone still gives a useful readout.

If the user has no files yet or asks how to export, use `references/exporting-data.md`.
Menu paths in that guide may have changed since it was written; say so if a step
doesn't match what the user sees.

## Workflow

1. **Check the uploads.** List the files. If none look like exports, ask for them.
2. **Ask only what you need.** Client name (optional, for the workbook). Do not ask about
   date ranges unless the user raises them: the default compares the last 28 days with the
   28 days before and with the same weekdays a year earlier. Offer to change it after.
3. **Run the script.** Install `pandas`, `matplotlib` and `openpyxl` first if they are missing.

   ```bash
   python <this-skill-folder>/scripts/aggregate.py <file or folder or zip> [...] \
     --out readout_output --client "Client name"
   ```

   Options: `--current-start/--current-end`, `--previous-start/--previous-end`
   (YYYY-MM-DD), `--days 28`, `--rollup weekly|monthly`.
4. **Read `readout_output/aggregate_summary.json`.** Read `health` first.
5. **Write the chat summary** (format below).
6. **Deliver the files.** Send `readout_workbook.xlsx`, the charts in `charts/`, and
   `readout_daily.csv` (the standard table) if the user wants the raw data.
7. **Next step.** If a main metric moved a lot, offer the change explainer skill
   (`readout-change-explainer`), which works from the same files.

## How to write the summary

Keep it short and plain. Write for a busy consultant who will reuse lines with a client.

```
**Data health:** <one line: all clear, or the issues that affect conclusions>

**Headline (<current period dates> vs <previous period dates>)**
- <Source>: <metric> <current> (<change_pct>% vs previous, <yoy_pct>% vs a year ago)
- ...

**By channel:** <2 to 4 bullets on the channels that moved most or matter most>

**Side by side:** <for each comparison: the two numbers, the gap, and in one sentence why
they differ, taken from why_they_differ. Mention if the ratio changed a lot between periods.>

**Files:** <what you're sending>
```

Rules:
- **Health warnings come first** when they affect the numbers (missing dates, near-zero days,
  mismatched date ranges, partial periods). Say what the warning means for the reader.
- **Never add numbers from different tools together.** Search Console clicks, GA4 sessions and
  Google Ads clicks measure different things. Present them side by side.
- **A gap between tools is normal.** Don't call it an error. Treat a big change in the ratio
  between periods (`ratio_change_pct`) as a possible tracking change worth checking.
- **Percent changes:** use `change_pct` and `yoy_pct` as given. If `previous` is missing or zero,
  say there is no comparison rather than inventing one.
- **Average position:** lower is better. Use `change_abs` (points), not a percent.
- **Exports without dates:** if `totals` is empty but `period_totals` has rows, report those totals
  and explain that trends and period comparisons need an export with a Date (GA4) or Day (Google Ads) column.
- **Don't explain causes.** This skill reports what changed and where. For why, offer the
  change explainer.
- Plain language. Expand jargon on first use (for example, CTR: the share of impressions that
  became clicks).

## Outputs (in `--out`)

| File | What it is |
|---|---|
| `aggregate_summary.json` | Every number for the summary: periods, health checks, totals, channel summary, side by side |
| `readout_workbook.xlsx` | Tabs: Read me, Channel summary, Side by side, Health check, Trends, Daily data, Search Console detail |
| `readout_daily.csv` | Standard table: date, source_system, channel, source, medium, campaign, sessions, users, conversions, impressions, clicks, spend, avg_position |
| `readout_search_console_breakdowns.csv` | Search Console queries, pages, countries and devices per export period |
| `charts/*.png` | GA4 sessions by channel, Search Console clicks and impressions, Google Ads clicks and spend |

## Known limits

- Export formats were built from commonly seen layouts and tested on synthetic files. Unusual
  exports may not be recognized. Anything skipped appears in `health` as a file note; tell the
  user which file and why.
- Numbers must use US formatting (1,234.56).
- One client per run. Spend is not converted between currencies; mixed currencies are flagged.
- The channel grouping is a simplified version of GA4's default rules. GA4's own channel column
  is used when the export has it. See `references/channel-grouping.md`.
