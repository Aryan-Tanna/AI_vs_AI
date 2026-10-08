# D-055 reranker evaluation (known-item, n=40, seed 7, pool 30, top_k 5)

| search | reranker | recall@k | MRR@k | mean s/query | mean result tokens |
| --- | --- | --- | --- | --- | --- |
| authority | Xenova/ms-marco-MiniLM-L-6-v2 | 0.78 | 0.63 | 9.00 | 1630 |
| authority | none | 0.80 | 0.71 | 1.00 | 1553 |
| similar | Xenova/ms-marco-MiniLM-L-6-v2 | 0.68 | 0.52 | 19.22 | 1638 |
| similar | none | 0.75 | 0.57 | 1.66 | 1499 |
