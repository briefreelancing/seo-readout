# Readout v0.1.0

The first release of Readout: two Claude skills that turn GA4, Search Console and Google Ads
exports into answers a client can read.

## Download

New to this? Follow the [No-code setup guide](https://github.com/briefreelancing/seo-readout/blob/main/docs/no-code-setup.md).
It takes about 10 minutes and needs no coding.

Download both files under **Assets** below. **Don't unzip them.** Upload them to Claude as they are.

| File | What it does |
|---|---|
| `readout-traffic-aggregator.zip` | Combines your exports into one clean view, checks the data for problems, and explains why numbers from different tools never match |
| `readout-change-explainer.zip` | Answers "why did traffic change?" in six steps and writes a client-ready report |

## What's included

**Traffic aggregator**
- Reads GA4, Search Console and Google Ads exports exactly as downloaded
- Health check: missing dates, days that look like tracking gaps, date ranges that don't line up
- Channel summary against the previous period and the same weeks last year
- Side-by-side comparisons (for example, Search Console clicks next to GA4 organic sessions), with the reasons they differ
- Excel workbook, CSV and charts

**Change explainer**
- Checks whether a change is real or a tracking problem before anything else
- Tests whether the change is unusual for the site, or seasonal
- Finds the pages, queries and channels behind the change
- Names the kind of change: ranking loss, lower demand, a change on the search results page, or brand demand
- Finds the date the trend shifted and lists site changes and Google updates it coincides with
- Suggests what to check next, with a confidence level for each check
- Client-ready report that prints to PDF. Every number in it is checked against the calculated results.

## Requirements

- A Claude plan that includes skills
- Code execution turned on in Claude (Settings > Capabilities)

## Known limits

- Tested on synthetic sample exports, not yet on a wide range of real accounts. If Readout can't
  read one of your files, it will say which one. Please [open an issue](https://github.com/briefreelancing/seo-readout/issues)
  with an anonymized copy if you can.
- Numbers must use US formatting (1,234.56).
- One client per run.
- The Google update list covers March 2024 to October 2026 and is updated by hand.
