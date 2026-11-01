# Exporting data for Readout

Readout reads exports exactly as downloaded. Don't rename columns or edit the files.

> These steps describe the menus as they were when this guide was written (late 2026).
> Google changes its interfaces often. If a step doesn't match what you see, look for the
> same option nearby, or open an issue so the guide can be updated.

## Google Search Console

**What to export:** Performance report, Search results, exported as CSV (a zip file).

1. Open **Performance > Search results**.
2. Set the **Date** filter. Keep search type as **Web**.
3. Click **Export > Download CSV**. You get a zip with tables for dates, queries, pages,
   countries, devices and filters.

**For the change explainer, export three zips:**

| Export | Date range | Used for |
|---|---|---|
| Current period | The last 28 days (or your chosen period) | Pages and queries now |
| Previous period | The 28 days before that | Pages and queries before |
| Long history | Last 16 months | Trend, year-ago comparison, finding when the shift started |

Upload all three together. Overlapping dates are counted once.

Notes:
- Search Console lists a limited number of rows per table and hides some rare queries for
  privacy, so query totals are lower than site totals. Readout reports that gap.
- Exports made with the **Compare** option turned on are supported on a best-effort basis.
  Separate exports per period are more reliable.

## Google Analytics 4

**What to export:** a table with a **Date** column, so Readout can show trends.

The most reliable route is an Exploration:

1. Open **Explore** and start a **Free form** exploration.
2. Add dimensions: **Date**, **Session default channel group**, **Session source / medium**.
   Optionally **Session campaign**.
3. Add metrics: **Sessions**, **Total users**, **Key events**.
4. Drag the dimensions into **Rows** and the metrics into **Values**. Set the rows shown to the
   maximum so no days are cut off.
5. Set the date range to match your Search Console exports.
6. Export as **CSV** (download icon at the top right).

Notes:
- Large GA4 properties can show sampled data in Explorations. If GA4 shows a sampling warning,
  shorten the date range and export in parts.
- Standard reports without a Date column still work, but only for totals, not trends.

## Google Ads

**What to export:** a campaign report segmented by day.

1. Open **Campaigns**.
2. Set the date range.
3. Click **Segment > Time > Day**.
4. Make sure these columns are visible: **Campaign type**, **Currency code**, **Impr.**,
   **Clicks**, **Cost**, **Conversions**.
5. Click **Download > .csv**.

Notes:
- Without the Day segment, Readout can show totals but not trends.
- Campaign type lets Readout group Performance Max and Search campaigns the way GA4 does.

## Event log (optional, change explainer)

A small CSV of things that happened on the site or in marketing. Readout checks whether the
trend shift lines up with any of them.

```csv
date,end_date,type,description
2026-10-05,,site change,Site redesign launched
2026-09-01,2026-09-30,campaign,September email promotion
2026-10-12,,tracking,Cookie banner update deployed
```

`end_date` is optional (use it for things that ran over several days).
