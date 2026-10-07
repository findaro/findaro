## Notes on this baseline

- **Where M1 is weak, and what M2 has to fix.** Price-constrained queries score 0.53 nDCG@10 and Hinglish
  queries 0.51. M1 does not parse "under 1000", "500 ke andar" or "sasta" into filters, so it ranks the right
  product type but ignores the price constraint. Hinglish words that the vector model doesn't know (`sarson ka
  tel`, `tar`, `gents chappal`) miss completely.
- **Zero-result rate is 0%** because the vector retriever always returns its nearest neighbours. Low-confidence
  queries therefore show weak results instead of an empty page. M2 should decide when to return nothing.
- **Label noise.** Ground truth comes from the generator's structured attributes, not from the LLM-written
  titles. A small fraction of titles drift: for example, 4 of 100 chargers are titled as "charging cable".
  Expect a few points of noise per query.
- **Reviewed.** Rohit reviewed all 21 Hinglish and natural-language queries on 2026-10-07: 15 approved and
  6 changed, with decisions in `eval/reviews.json`. Only q050 ("gaadi ke liye phone stand", narrowed to
  windshield mounts) changes which documents count as relevant. The other changes add a gender that the
  category already implies.
- Latency at 10k documents is in `eval/latency_10k.md`: server p95 10 ms with query embeddings warm, and 65 ms
  when the query embedding has to be computed (CPU e5-small inside Docker).
