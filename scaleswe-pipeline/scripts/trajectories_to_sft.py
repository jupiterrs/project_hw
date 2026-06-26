"""Convert AweAgent trajectory output to SFT training data (OpenAI messages format)."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path


def convert_aweagent_trajectory(record: dict) -> dict | None:
    if not record.get("success", False):
        return None
    messages_raw = record.get("messages", [])
    if not messages_raw:
        return None
    messages = []
    for msg in messages_raw:
        role = msg.get("role", "")
        content = msg.get("content")
        if role == "tool":
            role = "user"
        if content is None and msg.get("tool_calls"):
            parts = []
            for tc in msg["tool_calls"]:
                func = tc.get("function", tc)
                args = func.get("arguments", "")
                parts.append(f"<tool>\n{args}\n</tool>")
            content = "\n".join(parts)
        if content is None:
            content = ""
        messages.append({"role": role, "content": content})
    if not messages:
        return None
    return {"messages": messages}


def convert_distilled_parquet(record: dict) -> dict | None:
    messages_raw = record.get("messages", [])
    if not messages_raw:
        return None
    messages = []
    for msg in messages_raw:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if content is None:
            content = ""
        if role == "tool":
            role = "user"
        messages.append({"role": role, "content": content})
    if not messages:
        return None
    return {"messages": messages}


def process_file(input_path: str, output_path: str, fmt: str) -> None:
    path = Path(input_path)
    if fmt == "auto":
        fmt = "parquet" if path.suffix == ".parquet" else "jsonl"
    if fmt == "parquet":
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        records = table.to_pylist()
        converter = convert_distilled_parquet
    else:
        records = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        converter = convert_aweagent_trajectory
    total = len(records)
    converted = 0
    skipped = 0
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as out:
        for record in records:
            result = converter(record)
            if result is None:
                skipped += 1
                continue
            out.write(json.dumps(result, ensure_ascii=False) + "\n")
            converted += 1
    print(f"Done: {converted}/{total} trajectories converted, {skipped} skipped")


def main():
    parser = argparse.ArgumentParser(description="Convert trajectories to SFT format")
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--output", "-o", required=True)
    parser.add_argument("--format", "-f", choices=["auto", "jsonl", "parquet"], default="auto")
    args = parser.parse_args()
    process_file(args.input, args.output, args.format)


if __name__ == "__main__":
    main()
