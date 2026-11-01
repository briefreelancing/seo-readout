# Channel grouping

Readout puts every row from every source into one set of channel names, so GA4, Search
Console and Google Ads can be read together.

## Where the channel comes from

| Source | Channel |
|---|---|
| GA4 export with a channel column | GA4's own channel, used as is |
| GA4 export with source / medium only | Readout's rules below |
| Search Console | Always **Organic Search** (source google, medium organic) |
| Google Ads | From **Campaign type**: Search to Paid Search, Shopping to Paid Shopping, Display to Display, Video to Paid Video, Performance Max and Demand Gen to Cross-network. Without campaign type, everything is Paid Search. |

## Rules for source / medium

A simplified version of GA4's default channel rules, applied in this order:

1. `(direct) / (none)` is **Direct**
2. Campaign name contains "cross-network" is **Cross-network**
3. Medium is email, e-mail or newsletter is **Email**
4. Medium is affiliate is **Affiliates**
5. Medium is display, banner, cpm and similar is **Display**
6. Source is a search engine: paid medium (cpc, ppc, paid...) is **Paid Search**, organic is **Organic Search**
7. Source is a video site: **Paid Video** or **Organic Video**
8. Source is a social site, or medium is social: **Paid Social** or **Organic Social**
9. Medium is organic is **Organic Search**
10. Medium is referral is **Referral**
11. Everything else is **Unassigned**

These rules won't match GA4 in every edge case. When accuracy matters, export GA4 data with
the channel column included. The rules live in `shared/readout_core/channels.py`.

## Why tools never agree

Readout shows numbers from different tools side by side and never adds them together:

- **Search Console clicks vs GA4 organic sessions.** GA4 only records a visit when its tag loads
  and, with a consent banner, when the visitor accepts tracking. One session can follow several
  clicks. Search Console reports in Pacific Time; GA4 uses the property's time zone.
- **Google Ads clicks vs GA4 Paid Search sessions.** Several ad clicks can end up in one session.
  Consent banners, ad blockers and redirects that strip the click ID reduce what GA4 sees. GA4 puts
  some Google Ads traffic (for example Performance Max) outside Paid Search.
- **Google Ads conversions vs GA4 key events.** The tools can use different attribution models,
  lookback windows, counting settings and conversion dates.

A steady gap is normal. A gap that suddenly widens or narrows is worth investigating; Readout
reports that as the change in ratio between periods.
