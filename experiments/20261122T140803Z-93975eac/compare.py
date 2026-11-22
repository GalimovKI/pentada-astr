"""Compare two output folders from check.py without re-running the engine."""
import json
from pathlib import Path
import sys


def read(path):
    return json.loads(path.read_text())


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def abbreviate(rows):
    return {"total":len(rows), "matched_primary":sum(x["primary_match"] for x in rows.values()),
            "matched_any_variant":sum(x["expected"] in x["variants"] for x in rows.values())}


def compare(base, candidate):
    outcome = {}
    for kind in ("public","typo"):
        left, right = base/kind,candidate/kind
        pred1,pred2=[read_jsonl(p/"predictions.jsonl") for p in (left,right)]
        per1,per2=[read_jsonl(p/"per_query.jsonl") for p in (left,right)]
        text1,text2=[read(p/"wording.json") for p in (left,right)]
        assert len(pred1)==len(pred2)==len(text1)==len(text2)==len(per1)==len(per2)==99
        ids = [r["query_id"] for r in pred1]
        assert all([r["query_id"] for r in rows] == ids for rows in (pred2, per1, per2, text1, text2))
        changed_metrics = [a["query_id"] for a, b in zip(per1, per2, strict=True)
                           if a["metrics"] != b["metrics"]]
        changes=[]
        for w,r1,r2 in zip(text1,per1,per2,strict=True):
            n1,n2=[r["metrics"]["10"]["ndcg"] for r in (r1,r2)]
            if abs(n1-n2)>1e-12:
                changes.append({"query_id":w["query_id"], "query":w["input"], "prev":n1,"candidate":n2})
        outcome[kind] = {
            "same_rankings":sum(p==q for p,q in zip(pred1,pred2)), "count":len(per1),
            "same_primary_wording":sum(p["primary"]==q["primary"] for p,q in zip(text1,text2)),
            "receipt_day_preserved":[sum(r["receipt_preserved"] for r in w) for w in (text1,text2)],
            "spelling_restored":[sum(r["corrected"]==r["original"] for r in w) for w in (text1,text2)],
            "metrics":[read(p/"metrics.json")["by_k"]["10"] for p in (left,right)],
            "failed_queries":[read(p/"metrics.json")["failed_queries"] for p in (left,right)],
            "ndcg_changes":changes,
            "changed_query_metrics_at_any_k": changed_metrics,
        }
    for fn in ("probes","extra_forms"):
        both=[read(p/(fn+".json")) for p in (base,candidate)]
        by_key = lambda rows: {(r.get("base",r.get("reference")),r.get("surface",r.get("variant"))):r for r in rows}
        indexed=list(map(by_key,both))
        shared=indexed[0].keys() & indexed[1].keys()
        outcome[fn] = {
            "cases":len(shared),
            "eligible":[sum(rows[k].get("eligible",rows[k].get("nonempty",False)) for k in shared) for rows in indexed],
            "matched":[sum(rows[k]["same"] for k in shared) for rows in indexed],
            "changes":[{"pair":k, "baseline":indexed[0][k]["same"],"candidate":indexed[1][k]["same"]}
                       for k in sorted(shared) if indexed[0][k]["same"]!=indexed[1][k]["same"]],
        }
    outcome["input_controls"]=[sum(k==v["spelling"]==v["primary"] for k,v in read(p/"controls.json").items())
                               for p in (base,candidate)]
    outcome["phrases"]=[{k:abbreviate(v) for k,v in read(p/"phrases.json").items()} for p in (base,candidate)]
    return outcome


if __name__ == "__main__":
    result=compare(Path(sys.argv[1]),Path(sys.argv[2]))
    print(json.dumps(result,ensure_ascii=False,indent=2))
