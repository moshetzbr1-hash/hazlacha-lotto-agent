#!/usr/bin/env python3
"""
Double Lotto Israel tracking agent.

What it does:
- Fetches the latest Lotto/Double Lotto result from the official Pais Lotto page.
- Stores structured history in CSV and JSON.
- Deduplicates by draw_id when available, otherwise by draw_date.
- Writes operation/error logs.
- Generates a statistical report with frequencies, pairs, triples, trends over 60/120/365 days,
  hot/cold deviation from expectation, and candidate sets using a single explicit algorithm.

Important:
- Lottery draws are random. This script only describes historical frequencies; it does not predict
  or improve odds.
- Pais states that web-published results are for convenience and the binding results are the
  supervised protocol.
"""

from __future__ import annotations

import argparse
import csv
import html
import itertools
import json
import math
import re
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Jerusalem")
DEFAULT_SOURCE_URL = "https://www.pais.co.il/lotto/"
MAIN_RANGE = range(1, 38)
STRONG_RANGE = range(1, 8)

HE_MONTHS = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
    "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}


@dataclass(frozen=True)
class DrawRecord:
    source: str
    draw_id: str
    draw_date: str
    draw_time: str
    numbers: list[int]
    strong_number: int | None
    fetched_at: str
    source_url: str


def log(msg: str, level: str = "INFO", log_path: Path = Path("lotto_agent.log")) -> None:
    stamp = datetime.now(TZ).isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"{stamp}\t{level}\t{msg}\n")


def fetch_url(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; DoubleLottoAgent/1.0; +local)",
            "Accept-Language": "he-IL,he;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return data.decode(charset, errors="replace")


def html_to_text(raw_html: str) -> str:
    raw_html = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw_html)
    raw_html = re.sub(r"(?is)<style.*?>.*?</style>", " ", raw_html)
    text = re.sub(r"(?s)<[^>]+>", "\n", raw_html)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_hebrew_date(text: str) -> str | None:
    # Supports: "מיום שלישי 28 באפריל 2026 בשעה 23:16"
    m = re.search(r"(\d{1,2})\s+ב([א-ת]+)\s+(\d{4})", text)
    if not m:
        return None
    day = int(m.group(1))
    month = HE_MONTHS.get(m.group(2))
    year = int(m.group(3))
    if not month:
        return None
    return date(year, month, day).isoformat()


def parse_latest_lotto(raw_html: str, source_url: str = DEFAULT_SOURCE_URL) -> DrawRecord:
    text = html_to_text(raw_html)

    draw_id_match = re.search(r"תוצאות\s+הגרל(?:ת|ה)\s+לוטו\s+מס[׳'`’]?\s*(\d+)", text)
    if not draw_id_match:
        draw_id_match = re.search(r"תוצאות\s+הגרלה\s+מס[׳'`’]?\s*(\d+)", text)
    if not draw_id_match:
        raise ValueError("Could not parse draw_id from official page")
    draw_id = draw_id_match.group(1)

    date_match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text)
    if date_match:
        draw_date = datetime.strptime(date_match.group(1), "%d/%m/%Y").date().isoformat()
    else:
        draw_date = parse_hebrew_date(text)
    if not draw_date:
        raise ValueError("Could not parse draw_date from official page")

    time_match = re.search(r"בשעה\s*(\d{1,2}:\d{2})", text) or re.search(r"שעה\s*(\d{1,2}:\d{2})", text)
    draw_time = time_match.group(1) if time_match else ""

    strong_number = None

    # Main page format: "... תוצאת הגרלה לוטו ... 3 7 12 18 24 27 המספר החזק 5 ..."
    main_segment = None
    m = re.search(r"תוצאת\s+הגרלה\s+לוטו(.*?)(?:המספר\s+החזק)", text, flags=re.S)
    if m:
        main_segment = m.group(1)
        nums = [int(x) for x in re.findall(r"\b\d{1,2}\b", main_segment) if 1 <= int(x) <= 37]
        # The phrase may appear twice, but the actual six numbers are the final six in the segment.
        numbers = nums[-6:]
        strong_m = re.search(r"המספר\s+החזק\s*(\d{1,2})", text)
        if strong_m:
            s = int(strong_m.group(1))
            if s in STRONG_RANGE:
                strong_number = s
    else:
        # CurrentLotto.aspx format often places the strong number immediately before the label,
        # and the six main numbers after it.
        before_after = re.search(r"שעה\s*\d{1,2}:\d{2}\s*(\d{1,2})\s*המספר\s+החזק(.*?)(?:הגרלת\s+הלוטו|טבלת\s+זכיות)", text, flags=re.S)
        if not before_after:
            raise ValueError("Could not locate Lotto result segment")
        s = int(before_after.group(1))
        strong_number = s if s in STRONG_RANGE else None
        after = before_after.group(2)
        nums = [int(x) for x in re.findall(r"\b\d{1,2}\b", after) if 1 <= int(x) <= 37]
        # In the detailed page, numbers can appear as "1. 3 2. 7 ..."; remove ordinal labels if present.
        # Keep values that follow ordinal labels by taking every second value when pattern is clearly present.
        ordinal_pairs = re.findall(r"\b[1-6]\s*[.)]?\s*(\d{1,2})\b", after)
        if len(ordinal_pairs) >= 6:
            numbers = [int(x) for x in ordinal_pairs[:6]]
        else:
            numbers = nums[:6]

    if len(numbers) != 6 or any(n not in MAIN_RANGE for n in numbers):
        raise ValueError(f"Could not parse six valid main numbers; got {numbers}")
    if len(set(numbers)) != 6:
        raise ValueError(f"Parsed duplicate main numbers; got {numbers}")

    return DrawRecord(
        source="official_site",
        draw_id=draw_id,
        draw_date=draw_date,
        draw_time=draw_time,
        numbers=sorted(numbers),
        strong_number=strong_number,
        fetched_at=datetime.now(TZ).isoformat(timespec="seconds"),
        source_url=source_url,
    )


def load_history(json_path: Path) -> list[DrawRecord]:
    if not json_path.exists():
        return []
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return [DrawRecord(**x) for x in data]


def save_history(records: list[DrawRecord], csv_path: Path, json_path: Path) -> None:
    records = sorted(records, key=lambda r: (r.draw_date, int(r.draw_id) if str(r.draw_id).isdigit() else 0))
    json_path.write_text(json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = [
        "source", "draw_id", "draw_date", "draw_time",
        "n1", "n2", "n3", "n4", "n5", "n6",
        "strong_number", "fetched_at", "source_url"
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            row = {
                "source": r.source,
                "draw_id": r.draw_id,
                "draw_date": r.draw_date,
                "draw_time": r.draw_time,
                **{f"n{i+1}": n for i, n in enumerate(r.numbers)},
                "strong_number": r.strong_number if r.strong_number is not None else "",
                "fetched_at": r.fetched_at,
                "source_url": r.source_url,
            }
            writer.writerow(row)


def upsert_record(records: list[DrawRecord], new_record: DrawRecord) -> tuple[list[DrawRecord], bool]:
    by_key: dict[str, DrawRecord] = {}
    for r in records:
        key = r.draw_id or r.draw_date
        by_key[key] = r
    key = new_record.draw_id or new_record.draw_date
    existed = key in by_key
    by_key[key] = new_record
    return list(by_key.values()), not existed


def filter_window(records: list[DrawRecord], days: int, as_of: date | None = None) -> list[DrawRecord]:
    if not records:
        return []
    if as_of is None:
        as_of = max(datetime.fromisoformat(r.draw_date).date() for r in records)
    cutoff = as_of - timedelta(days=days)
    return [r for r in records if cutoff <= datetime.fromisoformat(r.draw_date).date() <= as_of]


def main_freq(records: Iterable[DrawRecord]) -> Counter[int]:
    c = Counter()
    for r in records:
        c.update(r.numbers)
    return c


def combo_freq(records: Iterable[DrawRecord], k: int) -> Counter[tuple[int, ...]]:
    c = Counter()
    for r in records:
        c.update(itertools.combinations(sorted(r.numbers), k))
    return c


def strong_freq(records: Iterable[DrawRecord]) -> Counter[int]:
    c = Counter()
    for r in records:
        if r.strong_number is not None:
            c[r.strong_number] += 1
    return c


def z_score(actual: int, n_draws: int, p: float) -> float:
    if n_draws <= 0:
        return 0.0
    exp = n_draws * p
    var = n_draws * p * (1 - p)
    return (actual - exp) / math.sqrt(var) if var > 0 else 0.0


def number_table(records: list[DrawRecord]) -> list[dict]:
    n = len(records)
    freq = main_freq(records)
    exp = n * 6 / 37 if n else 0
    return [
        {
            "number": num,
            "count": freq[num],
            "expected": round(exp, 3),
            "deviation": round(freq[num] - exp, 3),
            "z_score": round(z_score(freq[num], n, 6 / 37), 3),
        }
        for num in MAIN_RANGE
    ]


def make_candidate_sets(records: list[DrawRecord]) -> dict:
    """Consistent Weighted Recent Frequency Algorithm v1."""
    if len(records) < 20:
        return {
            "method": "Consistent Weighted Recent Frequency Algorithm v1",
            "status": "insufficient_data",
            "reason": "Need at least 20 draws before generating data-backed candidate sets.",
            "sets": [],
        }

    windows = {60: filter_window(records, 60), 120: filter_window(records, 120), 365: filter_window(records, 365)}
    tables = {d: {row["number"]: row["z_score"] for row in number_table(rs)} for d, rs in windows.items()}
    freq120 = main_freq(windows[120])
    pairs120 = combo_freq(windows[120], 2)
    strong120 = strong_freq(windows[120])

    scores = {}
    for n in MAIN_RANGE:
        z60 = max(-2.5, min(2.5, tables[60].get(n, 0.0)))
        z120 = max(-2.5, min(2.5, tables[120].get(n, 0.0)))
        z365 = max(-2.5, min(2.5, tables[365].get(n, 0.0)))
        scores[n] = 0.50 * z120 + 0.30 * z60 + 0.20 * z365

    pool = [n for n, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:14]]

    # Pair support not from a single set only: prefer numbers with at least two supporting pairs
    # among the recent 120-day pool when data exists.
    def set_score(s: tuple[int, ...]) -> float:
        base = sum(scores[n] for n in s)
        pair_bonus = sum(math.log1p(pairs120[tuple(sorted(p))]) for p in itertools.combinations(s, 2))
        # Soft balance constraints
        odd = sum(n % 2 for n in s)
        balance_penalty = 0.25 * abs(odd - 3)
        decade_count = len({(n - 1) // 10 for n in s})
        spread_bonus = 0.15 * decade_count
        return base + 0.10 * pair_bonus + spread_bonus - balance_penalty

    candidates = []
    used_pairs = set()
    for comb in sorted(itertools.combinations(pool, 6), key=set_score, reverse=True):
        odd = sum(n % 2 for n in comb)
        if odd not in (2, 3, 4):
            continue
        if len({(n - 1) // 10 for n in comb}) < 3:
            continue
        comb_pairs = set(itertools.combinations(comb, 2))
        if len(used_pairs & comb_pairs) > 4:
            continue
        candidates.append(list(comb))
        used_pairs |= comb_pairs
        if len(candidates) == 6:
            break

    strong_pool = [n for n, _ in strong120.most_common()] or list(STRONG_RANGE)
    sets = []
    for i, s in enumerate(candidates):
        strong = strong_pool[i % len(strong_pool)]
        sets.append({"numbers": s, "strong_number": strong})

    return {
        "method": (
            "Consistent Weighted Recent Frequency Algorithm v1: score = "
            "0.50*z120 + 0.30*z60 + 0.20*z365, z clipped to ±2.5; "
            "then balance odd/even, spread across decades, and limit repeated pairs across sets."
        ),
        "status": "ok",
        "sets": sets,
    }


def stats_report(records: list[DrawRecord], windows: list[int] = [60, 120, 365]) -> dict:
    if not records:
        return {
            "status": "empty_history",
            "message": "No draws available.",
            "windows": {},
            "candidate_sets": make_candidate_sets(records),
        }

    sorted_records = sorted(records, key=lambda r: r.draw_date)
    data_range = {"from": sorted_records[0].draw_date, "to": sorted_records[-1].draw_date}
    report = {
        "status": "ok",
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "data_range": data_range,
        "total_draws": len(sorted_records),
        "calculation_method": {
            "main_frequency": "Count appearances of each main number in a draw; each draw contributes six appearances.",
            "strong_frequency": "Count appearances of the strong number; each draw contributes one strong number.",
            "pairs_triples": "Count unordered combinations within each draw.",
            "hot_cold": "Deviation and z-score against expected probability: main=6/37 per draw, strong=1/7 per draw.",
        },
        "windows": {},
        "candidate_sets": make_candidate_sets(sorted_records),
    }

    for days in windows:
        rs = filter_window(sorted_records, days)
        report["windows"][str(days)] = {
            "days": days,
            "draw_count": len(rs),
            "range": {
                "from": min((r.draw_date for r in rs), default=None),
                "to": max((r.draw_date for r in rs), default=None),
            },
            "main_numbers": number_table(rs),
            "strong_numbers": [
                {
                    "strong_number": n,
                    "count": strong_freq(rs)[n],
                    "expected": round(len(rs) / 7, 3),
                    "deviation": round(strong_freq(rs)[n] - len(rs) / 7, 3),
                    "z_score": round(z_score(strong_freq(rs)[n], len(rs), 1 / 7), 3),
                }
                for n in STRONG_RANGE
            ],
            "top_pairs": [
                {"pair": list(pair), "count": count}
                for pair, count in combo_freq(rs, 2).most_common(20)
            ],
            "top_triples": [
                {"triple": list(triple), "count": count}
                for triple, count in combo_freq(rs, 3).most_common(20)
            ],
        }
    return report


def write_report(records: list[DrawRecord], path: Path) -> None:
    report = stats_report(records)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Wrote stats report to {path}")


def run_fetch(args: argparse.Namespace) -> None:
    log_path = Path(args.log)
    csv_path = Path(args.csv)
    json_path = Path(args.json)
    try:
        raw = fetch_url(args.source_url)
        record = parse_latest_lotto(raw, args.source_url)
        records = load_history(json_path)
        records, inserted = upsert_record(records, record)
        save_history(records, csv_path, json_path)
        log(
            f"{'Inserted' if inserted else 'Updated'} draw_id={record.draw_id} "
            f"date={record.draw_date} numbers={record.numbers} strong={record.strong_number}",
            log_path=log_path,
        )
    except Exception as exc:
        log(f"Fetch/update failed: {exc}", "ERROR", log_path=log_path)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Israel Double Lotto tracking agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    fetch = sub.add_parser("fetch", help="Fetch latest result and update local history")
    fetch.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    fetch.add_argument("--csv", default="lotto_history.csv")
    fetch.add_argument("--json", default="lotto_history.json")
    fetch.add_argument("--log", default="lotto_agent.log")
    fetch.set_defaults(func=run_fetch)

    report = sub.add_parser("report", help="Generate statistical report JSON")
    report.add_argument("--json", default="lotto_history.json")
    report.add_argument("--out", default="lotto_stats_report.json")
    report.add_argument("--log", default="lotto_agent.log")
    def report_func(args: argparse.Namespace) -> None:
        records = load_history(Path(args.json))
        write_report(records, Path(args.out))
    report.set_defaults(func=report_func)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
