# Working with Apple Music Export Files

## Export format

Apple Music exports library and playlist data as tab-separated values (TSV), not CSV. The delimiter is a tab character (`\t`), so treat the file as TSV when parsing. Column headers are on the first row.

## Character encoding

Apple Music exports are UTF-16 LE with CR (`\r`) line endings — a legacy format from the iTunes era. Convert to UTF-8 before loading:

```python
df = pd.read_csv("export.txt", sep="\t", encoding="utf-16", lineterminator="\r")
```

## Key columns

- **Name** — track title
- **Artist**, **Album Artist** — may differ; use Album Artist for grouping
- **Album** — album name
- **Genre** — user-assigned; inconsistent across libraries
- **Time** — duration in seconds
- **Year** — release year (integer, may be missing)
- **Plays** — play count; blank means zero, not missing
- **My Rating** — 0–100 in steps of 20 (20=1 star … 100=5 stars); blank means unrated
- **Date Added**, **Last Played** — locale-formatted strings, not ISO 8601; parse carefully
- **Location** — absolute file path on the exporting machine; not portable

## Common gotchas

- **Plays is blank, not 0** for unplayed tracks — fill with 0 before any numeric analysis.
- **My Rating is blank** for unrated tracks — distinct from a 1-star rating; treat separately.
- **Genre is freeform** — the same genre may appear as "Rock", "rock", "Alt Rock", "Alternative & Punk". Normalise before grouping.
- **Compilations** appear with varying Artist values per track; Album Artist is more reliable for grouping.
- **Time is in seconds** — divide by 60 for minutes or 3600 for hours.
- **Duplicate tracks** can appear if a song is in iCloud and also local; deduplicate on (Name, Artist, Album) if needed.

## Parsing dates

Apple Music date strings are locale-dependent and not ISO 8601. A typical US export looks like `3/6/26, 8:27/PM` — note the slash before AM/PM, which is non-standard and will trip up most date parsers. A robust approach:

```python
from dateutil import parser as dateutil_parser

def parse_apple_date(s):
    if not isinstance(s, str) or not s.strip():
        return None
    # Replace the slash before AM/PM that Apple inserts
    s = s.replace("/AM", " AM").replace("/PM", " PM")
    try:
        return dateutil_parser.parse(s)
    except Exception:
        return None

df["Date Added"] = df["Date Added"].apply(parse_apple_date)
df["Last Played"] = df["Last Played"].apply(parse_apple_date)
```

Two-digit years (e.g. `26`) are interpreted as 2026 by `dateutil` when they are ≤ the current year's last two digits; verify this assumption if your export predates 2000.

## Rating analysis

My Rating uses a 0–100 scale in steps of 20, mapping to stars as follows:

| My Rating | Stars |
|-----------|-------|
| 20        | ★     |
| 40        | ★★    |
| 60        | ★★★   |
| 80        | ★★★★  |
| 100       | ★★★★★ |
| blank     | unrated |

Blank and 0 are both present in exports and both mean "unrated" — treat them identically. To convert to a 1–5 star integer:

```python
df["Stars"] = (df["My Rating"].fillna(0).astype(int) / 20).replace(0, pd.NA).astype("Int64")
```

This gives a nullable integer column where unrated tracks are `<NA>` rather than 0.

## Play count analysis

Play count analysis is straightforward once blanks are filled, but watch for recency bias: Apple Music resets play counts when you re-add a track or restore from backup. A track with 0 plays may be newly added or may have had its history wiped. Use Date Added together with Plays to distinguish new tracks from tracks with lost history.

Useful derived columns:

```python
df["Plays"] = df["Plays"].fillna(0).astype(int)
df["Days Since Added"] = (pd.Timestamp.now() - df["Date Added"]).dt.days
df["Plays Per Day"] = df["Plays"] / df["Days Since Added"].clip(lower=1)
```

`Plays Per Day` is a better engagement metric than raw play count for comparing tracks added at different times.

## Genre normalisation

Genre values are user-editable freeform strings. Common normalisation steps:

```python
genre_map = {
    "alternative & punk": "Alternative",
    "alt rock": "Alternative",
    "classic rock": "Rock",
    "r&b/soul": "R&B",
    "hip-hop/rap": "Hip-Hop",
}

df["Genre Normalised"] = (
    df["Genre"]
    .str.strip()
    .str.lower()
    .map(genre_map)
    .fillna(df["Genre"].str.strip())
)
```

For large libraries it is worth inspecting `df["Genre"].value_counts()` before committing to a map, as personal libraries vary widely.
