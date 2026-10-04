"""Build the dense index for the reference DB (BM25 is built in memory at load time).

  python -m lexarena.retrieval.build_index --dense       # one-off, CPU: a few minutes for bge-small (384 dims)
  python -m lexarena.retrieval.build_index --query "acknowledgment in balance sheet section 18" --cutoff 2022-01-01
"""
import argparse
import datetime as dt
import json

from lexarena.config import Settings
from lexarena.retrieval.dense import DEFAULT_MODEL, DenseIndex
from lexarena.retrieval.search import ReferenceIndex


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dense", action="store_true")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--query")
    p.add_argument("--cutoff", default=dt.date.today().isoformat())
    args = p.parse_args()
    s = Settings()
    idx = ReferenceIndex.load(s.reference_path, s.index_dir)
    print(f"{len(idx.cases)} cases, {len(idx.units)} units, dense={'yes' if idx.dense else 'no'}")
    if args.dense:
        texts = [u.text for u in idx.units]
        vecs = DenseIndex.build(texts, args.model)
        DenseIndex.save(s.index_dir, vecs, texts, args.model)
        print("saved", vecs.shape, "to", s.index_dir)
    if args.query:
        for h in idx.search(args.query, cutoff=dt.date.fromisoformat(args.cutoff)):
            print(json.dumps({k: (v[:160] if isinstance(v, str) else v) for k, v in h.to_dict().items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
