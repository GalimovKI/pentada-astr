"""Time one warm, sequential retrieval request at a time on the public benchmark."""
import argparse
import json
from dataclasses import replace
from pathlib import Path
from time import perf_counter

import numpy as np
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

from extract import messages_for, validate_object
from mailsearch.encoder import Encoder
from mail_search.ingestion.dataset import load_dataset
from retrieve import MailIndex, prepared_query


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "index", "chunks", "repairs", "qwen", "output"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    ds = load_dataset(args.archive)
    facts = {}
    for folder in (args.chunks, args.repairs):
        for path in sorted(folder.glob("*.jsonl")):
            with path.open() as f:
                for row in map(json.loads, f):
                    facts[row["id"]] = row
    with np.load(args.index) as idx:
        if list(idx["ids"]) != sorted(ds.documents):
            raise ValueError("Embedding index mismatch")
        index = MailIndex(ds.documents, facts, idx["vectors"])
    encoder = Encoder("e5", "cuda")
    tokenizer = AutoTokenizer.from_pretrained(args.qwen, local_files_only=True)
    llm = LLM(model=str(args.qwen), dtype="bfloat16", max_model_len=16384, seed=0,
              gpu_memory_utilization=.30, kv_cache_memory_bytes=8*1024**3, max_num_seqs=96,
              max_num_batched_tokens=8192, enable_prefix_caching=True, enforce_eager=True)
    sampling = SamplingParams(temperature=0, max_tokens=512, seed=0)

    def timed(q):
        start = perf_counter()
        item = dict(kind="query", id=q.query_id, query_date=q.query_date.isoformat(), text=q.query)
        prompt = tokenizer.apply_chat_template(messages_for(item), tokenize=False,
                                               add_generation_prompt=True, enable_thinking=False)
        answer = llm.generate([prompt], sampling, use_tqdm=False)[0].outputs[0]
        failed = False
        try:
            fields = validate_object(answer.text, item)
        except (ValueError, TypeError):
            fields, failed = {}, True
        extracted = perf_counter()
        vector = encoder.encode([prepared_query(q)], query=True)[0]
        embedded = perf_counter()
        ranking = index.search(q, vector, fields)["full"]
        end = perf_counter()
        return dict(query_id=q.query_id, qwen_ms=1000*(extracted-start), e5_ms=1000*(embedded-extracted),
                    ranking_ms=1000*(end-embedded), total_ms=1000*(end-start),
                    output_tokens=len(answer.token_ids), invalid=failed, ranking=ranking)

    for text in ("Письмо от Анны про договор","Покажи вчерашнее письмо про оплату","Чек за покупку"):
        timed(replace(ds.queries[0], query=text))
    rows = [timed(q) for q in ds.queries]
    results = {}
    for field in ("qwen_ms", "e5_ms", "ranking_ms", "total_ms"):
        values = np.array([r[field] for r in rows])
        quantiles = np.percentile(values, [50,95,99], method="inverted_cdf")
        results[field] = dict(mean=float(values.mean()), **dict(zip(("p50","p95","p99"),quantiles.tolist())))
    with args.output.open("x") as f:
        json.dump(dict(summary=results, rows=rows), f, ensure_ascii=False)


if __name__ == "__main__":
    main()
