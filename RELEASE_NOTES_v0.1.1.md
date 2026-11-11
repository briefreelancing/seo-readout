# Readout v0.1.1

Fixes found by running Readout on a real Search Console export and on a new synthetic client
whose traffic goes up instead of down.

## Download

Download both files under **Assets** below. **Don't unzip them.** Upload them to Claude as they
are. New to this? Follow the [No-code setup guide](https://github.com/briefreelancing/seo-readout/blob/main/docs/no-code-setup.md).

## Fixed

- **Small sites no longer get false tracking warnings.** A day is flagged as a possible tracking
  gap only if a count that low is very unlikely by chance, measured against the same weekday as
  well as the last 14 days. For Search Console, impressions must also drop. Before this fix, a
  real site with about 4 clicks a day had 37 normal days flagged, and the explainer blamed
  tracking for part of the change.
- **Next steps match the data source.** A low Search Console day now points to Search Console
  data issues, outages and indexing changes, not tag deployments or consent banners.
- **"Web (text-based)" is treated as web search**, so real Search Console exports no longer
  trigger a search type warning.
- **Timing of Google updates inside their rollout** is now reported as 0 days, not as days since
  the update started.

## Improved

- **Gains are explained as well as drops.** The explainer lists the pages gaining the most
  clicks and suggests checks for a gain, such as finding what changed on those pages.
- **Site changes that take time to show are matched.** Entries from your event log are listed
  if the trend shift began up to 14 days after them (`--event-lag-days`), marked as "follows"
  rather than "coincides with".
- **Paused Google Ads campaigns are spotted.** A campaign that stops getting clicks part way
  through is listed with the last day it had clicks.
- **Weak trend shifts are flagged** so timing matches to events are read with more caution.

## Other changes

- Search Console's daily table is read whether it is named `Chart.csv` or `Dates.csv`, from a
  zip or as loose CSVs. The exporting guide now says so.
- New sample client, `sample-data/lakeview-plumbing/`, with a gain story. The bakery sample moved
  to `sample-data/northwind-bakery/`.
- Tests: 9 to 15.

## Still to do

- Test GA4 and Google Ads parsers on real exports.

Made by Briefreelancing
