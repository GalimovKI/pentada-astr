import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

import pyarrow.parquet as pq

paths = dict(emails="emails.parquet", train="tasks_train.parquet", eval="tasks_eval.parquet")
rows = {key: pq.read_table(path).to_pylist() for key, path in paths.items()}
emails = {row["message_id"]: row for row in rows["emails"]}
dates = {
    mid: datetime.fromisoformat(row["date"]).date() if row["date"] else None
    for mid, row in emails.items()
}
assert len(emails) == len(rows["emails"])

def addresses(row):
    return {address.casefold() for address in (row["from"], *row["to"], *row["cc"], *row["bcc"]) if address}

mailboxes = defaultdict(set)
for mid, email in emails.items():
    for address in addresses(email):
        mailboxes[address].add(mid)

calendar = re.compile(
    r"\b(?:yesterday|today|tomorrow|last (?:week|month|year)|"
    r"(?:earlier|this) (?:week|month|year)|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}|"
    r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December))\b"
)

def stats(tasks):
    counts = Counter()
    before_sizes = []
    ages = []
    previous_day_sizes = []
    previous_day_recalls = []
    for task in tasks:
        mids = set(task["message_ids"])
        inbox = mailboxes[task["inbox_address"].casefold()]
        asof = date.fromisoformat(task["query_date"])
        diff = [(asof - dates[mid]).days for mid in mids if dates.get(mid) is not None]
        counts["source_pairs"] += len(mids)
        counts["duplicate_source_pairs"] += len(task["message_ids"]) - len(mids)
        counts["missing_source_pairs"] += len(mids - emails.keys())
        counts["out_of_mailbox_pairs"] += len((mids & emails.keys()) - inbox)
        counts["unknown_date_pairs"] += sum(mid in dates and dates[mid] is None for mid in mids)
        counts["future_pairs"] += sum(days < 0 for days in diff)
        counts["same_day_pairs"] += diff.count(0)
        counts["previous_day_pairs"] += diff.count(1)
        counts["queries_with_future_source"] += any(days < 0 for days in diff)
        counts["queries_with_same_day_source"] += 0 in diff
        counts["queries_all_sources_previous_day"] += len(diff) == len(mids) and bool(diff) and all(days == 1 for days in diff)
        counts["queries_with_one_source"] += len(mids) == 1
        cue = bool(calendar.search(task["question"]))
        counts["queries_with_calendar_cue"] += cue
        counts["queries_no_detected_cue_all_sources_previous_day"] += (
            not cue and len(diff) == len(mids) and bool(diff) and all(days == 1 for days in diff)
        )
        previous_day_sizes.append(sum(dates[mid] == asof - timedelta(days=1) for mid in inbox))
        previous_day_recalls.append(diff.count(1) / len(mids))
        before_sizes.append(sum(dates[mid] is not None and dates[mid] < asof for mid in inbox))
        ages.extend(diff)
    return {
        "tasks": len(tasks),
        "task_mailboxes": len({t["inbox_address"].casefold() for t in tasks}),
        "query_ids_unique": len({t["id"] for t in tasks}),
        "levels": dict(sorted(Counter(t["level"] for t in tasks).items())),
        **counts,
        "strict_prior_mailbox_candidates_min_median_max": [min(before_sizes), median(before_sizes), max(before_sizes)],
        "previous_day_mailbox_candidates_min_median_max": [
            min(previous_day_sizes), median(previous_day_sizes), max(previous_day_sizes)
        ],
        "previous_day_only_macro_recall_ceiling": sum(previous_day_recalls) / len(previous_day_recalls),
        "source_age_days_min_median_max": [min(ages), median(ages), max(ages)],
    }

lookups = [t for t in rows["eval"] if t["level"] == 0]
def unique_values(tasks, key):
    return set().union(*(set(key(t)) for t in tasks))

def overlap(key):
    return len(unique_values(rows["train"], key) & unique_values(rows["eval"], key))

summary = {
    "sha256": {key: hashlib.sha256(Path(path).read_bytes()).hexdigest() for key, path in paths.items()},
    "unique_messages": len(emails),
    "messages_with_send_date": sum(val is not None for val in dates.values()),
    "send_date_range": [str(min(dates.values())), str(max(dates.values()))],
    "cross_split_overlap": {
        "inboxes": overlap(lambda t: [t["inbox_address"].casefold()]),
        "source_messages": overlap(lambda t: t["message_ids"]),
        "task_ids": overlap(lambda t: [t["id"]]),
    },
    "eval": stats(rows["eval"]),
    "eval_level_0": stats(lookups),
}
print(json.dumps(summary, indent=2))
