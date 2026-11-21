"""Register a TSV subtitle codec on your own registry; no global modifications."""
from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

from reibosub import Cue, FormatRegistry, Subtitle


class TsvCodec:
    def loads(self, text: str) -> Subtitle:
        rows = csv.DictReader(io.StringIO(text), delimiter="\t")
        return Subtitle(tuple(Cue(index=int(row["index"]), start=float(row["start"]), end=float(row["end"]), text=row["text"]) for row in rows))

    def dumps(self, subtitle: Subtitle) -> str:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter="\t")
        writer.writerow(["index", "start", "end", "text"])
        for cue in subtitle:
            writer.writerow([cue.index, cue.start, cue.end, cue.text])
        return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    registry = FormatRegistry()
    registry.register("tsv", TsvCodec())
    source = Subtitle((Cue(1, 0, 2, "自定义格式\n保留多行"),))
    source.save(args.out, format="tsv", registry=registry)
    restored = Subtitle.load(args.out, format="tsv", registry=registry)
    assert restored.cues == source.cues
    print(restored.to_text())


if __name__ == "__main__":
    main()
