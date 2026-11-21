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
    manifest = args.out / "manifest.json"
    if manifest.exists():
        if json.loads(manifest.read_text()) != signature:
            raise ValueError("Existing chunks belong to a different run")
    else:
        manifest.write_text(json.dumps(signature))
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = LLM(model=str(args.model), dtype="bfloat16", max_model_len=16384, seed=0,
                gpu_memory_utilization=args.gpu_fraction, max_num_seqs=96, max_num_batched_tokens=8192,
                enable_prefix_caching=True, enforce_eager=True)
    sampling = SamplingParams(temperature=0, max_tokens=512, seed=0)
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
        responses = model.generate(prompts, sampling, use_tqdm=False)
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
