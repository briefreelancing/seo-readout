"""One channel grouping used across every source.

GA4 rows that already carry a default channel group keep it (normalized to the
names below). Rows that only have source and medium are grouped with a
simplified version of GA4's default rules. It will not match GA4 exactly for
every edge case; see docs/channel-grouping.md.
"""

from __future__ import annotations

import re

CHANNELS = [
    "Organic Search", "Paid Search", "Direct", "Referral", "Organic Social",
    "Paid Social", "Email", "Display", "Paid Video", "Organic Video",
    "Paid Shopping", "Organic Shopping", "Cross-network", "Affiliates",
    "SMS", "Audio", "Mobile Push Notifications", "Unassigned",
]

_CANON = {c.lower(): c for c in CHANNELS}
_CANON.update({"(other)": "Unassigned", "other": "Unassigned", "(not set)": "Unassigned"})

SEARCH_ENGINES = {
    "google", "bing", "yahoo", "duckduckgo", "baidu", "yandex", "ecosia", "naver",
    "brave", "startpage", "qwant", "seznam", "aol", "ask",
}
SOCIAL_SITES = {
    "facebook", "instagram", "linkedin", "lnkd.in", "t.co", "twitter", "x.com", "pinterest",
    "reddit", "tiktok", "threads", "youtube", "quora", "snapchat", "tumblr", "m.facebook.com",
    "l.facebook.com", "lm.facebook.com", "l.instagram.com", "bsky.app", "mastodon",
}
VIDEO_SITES = {"youtube", "vimeo", "twitch", "dailymotion"}

_PAID_MEDIUM = re.compile(r"^(.*cp.*|ppc|retargeting|paid.*)$")


def normalize_channel(name: str) -> str:
    key = (name or "").strip().lower()
    return _CANON.get(key, name.strip() if name else "Unassigned")


def _site(source: str) -> str:
    s = source.lower().strip()
    s = re.sub(r"^(www\.|m\.)", "", s)
    return s.split("/")[0]


def _matches(site: str, names: set[str]) -> bool:
    return any(site == n or site.startswith(n + ".") or site.endswith("." + n) or site == n + ".com" for n in names)


def channel_from_source_medium(source: str, medium: str, campaign: str = "") -> str:
    src = _site(source or "")
    med = (medium or "").strip().lower()
    camp = (campaign or "").strip().lower()

    if src in {"(direct)", "direct"} and med in {"(none)", "(not set)", "none", ""}:
        return "Direct"
    if "cross-network" in camp:
        return "Cross-network"
    if med in {"email", "e-mail", "e_mail", "e mail", "newsletter"} or src in {"email", "newsletter"}:
        return "Email"
    if med in {"affiliate", "affiliates"}:
        return "Affiliates"
    if med in {"sms"}:
        return "SMS"
    if med in {"audio"}:
        return "Audio"
    if med in {"push", "mobile", "notification"}:
        return "Mobile Push Notifications"
    if med in {"display", "banner", "expandable", "interstitial", "cpm"}:
        return "Display"
    paid = bool(_PAID_MEDIUM.match(med))
    if _matches(src, SEARCH_ENGINES):
        if paid:
            return "Paid Search"
        if med in {"organic", "(none)", "referral", ""}:
            return "Organic Search"
    if _matches(src, VIDEO_SITES) or "video" in med:
        return "Paid Video" if paid else "Organic Video"
    if _matches(src, SOCIAL_SITES) or med in {"social", "social-network", "social-media", "sm", "social network", "social media"}:
        return "Paid Social" if paid else "Organic Social"
    if med == "organic":
        return "Organic Search"
    if paid:
        return "Paid Search" if "search" in med or med in {"cpc", "ppc"} else "Paid Social" if "social" in med else "Paid Search"
    if med in {"referral", "app", "link"}:
        return "Referral"
    return "Unassigned"


# Google Ads campaign type -> channel. Mapping based on how GA4 usually groups
# Google Ads traffic; not verified for every campaign type.
ADS_CAMPAIGN_TYPE = {
    "search": "Paid Search",
    "shopping": "Paid Shopping",
    "display": "Display",
    "video": "Paid Video",
    "performance max": "Cross-network",
    "demand gen": "Cross-network",
    "discovery": "Cross-network",
    "app": "Cross-network",
    "smart": "Cross-network",
}


def channel_from_ads_campaign_type(campaign_type: str) -> str:
    return ADS_CAMPAIGN_TYPE.get((campaign_type or "").strip().lower(), "Paid Search")
