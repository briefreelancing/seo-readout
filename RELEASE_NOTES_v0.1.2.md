# Readout v0.1.2

Fixes found by testing the v0.1.1 skill zips the way a user would: unzipped on their own,
run from a fresh folder, with a client report built for a traffic gain.

## Download

Download both files under **Assets** below. **Don't unzip them.** Upload them to Claude as they
are. New to this? Follow the [No-code setup guide](https://github.com/briefreelancing/seo-readout/blob/main/docs/no-code-setup.md).

## Fixed

- **Client report tables follow the direction of the change.** When traffic rises, the tables
  under each chart now list the biggest gains. Before, they always listed declines, so a report
  about a gain showed the wrong pages, queries and channels.
- **Branded vs non-branded split now covers gains.** A rise in non-branded clicks is reported as
  better SEO visibility, and a rise in branded clicks as brand demand. Before, gains were labeled
  "no clear split".
- **Plain wording for the click split.** The report now says "from more impressions" or "from
  fewer impressions" instead of "from fewer or more impressions".
- **Chart value labels no longer overlap the row names** on small negative bars.

## Other changes

- Skill guides now say the export formats were tested on one real Search Console export, and
  that GA4 and Google Ads are not yet tested on real exports.
- Example charts and report regenerated. The numbers are unchanged.

Made by Briefreelancing
