"""Resume greedy offline extraction at atomic chunk boundaries. One writer per directory."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from extract import REVISION, messages_for, validate_object


def main():
    from vllm import LLM, SamplingParams
    from transformers import AutoTokenizer

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("model", type=Path)
    p.add_argument("inputs", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--repair-from", type=Path, help="Retry only invalid rows using constrained JSON generation")
    p.add_argument("--chunk", type=int, default=512)
    p.add_argument("--gpu-fraction", type=float, default=0.30)
    args = p.parse_args()
    if args.chunk <= 0:
        p.error("chunk must be positive")
    raw = args.inputs.read_bytes()
    items = [json.loads(line) for line in raw.splitlines()]
    args.out.mkdir(parents=True, exist_ok=True)
    signature = dict(input_sha256=hashlib.sha256(raw).hexdigest(), model_revision=REVISION, chunk=args.chunk,
                     extractor_sha256=hashlib.sha256(Path(__file__).with_name("extract.py").read_bytes()).hexdigest())
    if args.repair_from:
        original = {}
        for path in sorted(args.repair_from.glob("*.jsonl")):
            for line in path.read_text().splitlines():
                row = json.loads(line)
                if row["id"] in original:
                    raise ValueError("Duplicate source ID")
                original[row["id"]] = row
        if set(original) != {row["id"] for row in items}:
            raise ValueError("Source extraction incomplete")
        items = [row for row in items if "error" in original[row["id"]]]
        signature["repair_ids"] = [row["id"] for row in items]
    manifest = args.out / "manifest.json"
    if manifest.exists():
        if json.loads(manifest.read_text()) != signature:
            raise ValueError("Existing chunks belong to a different run")
    else:
        manifest.write_text(json.dumps(signature))
    if not items:
        return
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = LLM(model=str(args.model), dtype="bfloat16", max_model_len=16384, seed=0,
                gpu_memory_utilization=args.gpu_fraction, kv_cache_memory_bytes=8 * 1024**3, max_num_seqs=96, max_num_batched_tokens=8192,
                enable_prefix_caching=True, enforce_eager=True)
    sampling = SamplingParams(temperature=0, max_tokens=512, seed=0)
    if args.repair_from:
        from vllm.sampling_params import StructuredOutputsParams
        sender = {"type": ["string", "null"]}
        list_of_strings = {"type": "array", "items": {"type": "string"}}
        roles = ("event","deadline","receipt","unknown")
        specs = {"letter": {"sender": sender, **dict.fromkeys(roles, list_of_strings)},
                 "query": {"sender": sender, "dates": {"type":"array","items":list_of_strings}}}
        guided = {}
        for kind, fields in specs.items():
            schema = {"type":"object","properties":fields,"required":list(fields),"additionalProperties":False}
            guided[kind] = SamplingParams(temperature=0, seed=0, max_tokens=1024,
                                          structured_outputs=StructuredOutputsParams(json=schema))
    start = time.monotonic()
    for pos in range(0, len(items), args.chunk):
        dest = args.out / f"{pos:06d}.jsonl"
        batch = items[pos:pos + args.chunk]
        if dest.exists():
            if [json.loads(s)["id"] for s in dest.read_text().splitlines()] != [r["id"] for r in batch]:
                raise ValueError(f"Invalid saved chunk {dest}")
            continue
        prompts = [tokenizer.apply_chat_template(messages_for(r), tokenize=False, add_generation_prompt=True,
                                                enable_thinking=False) for r in batch]
        params = [guided[r["kind"]] for r in batch] if args.repair_from else sampling
        responses = model.generate(prompts, params, use_tqdm=False)
        temp = dest.with_suffix(".partial")
        with temp.open("w") as f:
            for row, response in zip(batch, responses, strict=True):
                output = response.outputs[0]
                result = {k:v for k,v in row.items() if k != "text"}
                try:
                    result.update(validate_object(output.text, row))
                except (TypeError, ValueError) as exc:
                    result.update(error=str(exc), raw=output.text)
                result["finish_reason"] = output.finish_reason
                f.write(json.dumps(result,ensure_ascii=False)+"\n")
        temp.replace(dest)
        print(f"processed {pos + len(batch)}/{len(items)}, elapsed {time.monotonic()-start:.0f}s", flush=True)


if __name__ == "__main__":
    main()
