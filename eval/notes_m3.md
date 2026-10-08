### Analysis

**Model choice.** The brief asks for claude-haiku-4-5. No Anthropic key was available, so Rohit approved OpenAI.
The same 71-turn eval was run with three chat models:

| Model | First token p95 | Groundedness |
|---|---:|---:|
| gpt-4.1-mini (default) | 915–1,109 ms | 88–90% |
| gpt-4o-mini | 1,009 ms | 84% |
| gpt-5.4-mini (reasoning `none`) | 1,237–1,456 ms | 93–96% |

gpt-5.4-mini grounds best but misses the 1.2 s first-token target, so the default is gpt-4.1-mini. Two prompt
changes closed most of the grounding gap:
- the model sees every product on screen, not just the top 5;
- comparisons ("cheapest", "highest rated") are computed in code and handed to the model as facts.

Set `ZERCH_CHAT_MODEL=gpt-5.4-mini` to prefer grounding over latency.

**Known-problem fixes from M2.**
- *match_quality:* now also uses planner evidence (did the rules recognise a catalog value or category, or did the
  user confirm one in chat) and how many query words the top results actually contain. Synonym expansions count,
  and missing words only lower the quality when the catalog has never seen them.
  - Result: 18/20 out-of-catalog queries get `none`/`weak`, and 0 in-catalog queries get `none`.
  - Still `good`: "laptop" (laptop bags) and "washing machine" (laundry organisers).
- *Backfill:* "saree under rs 1000" now shows the one saree under ₹1,000, then sarees just over budget, cheapest
  first. It used to show tea and bellies. Rules:
  - Filler and backfill stay inside the category the lexical matches agree on.
  - Category votes are weighted by lexical score, so a weak fuzzy match can't redirect it.
  - Price segment: 0.900 → 0.954.

**Remaining failures.**
- *Turn type ("type c wala").* "type c" isn't recognised as USB-C, so it's treated as a new search. That
  needs a synonym the packs don't have; it wasn't added to avoid tuning on the eval.
- *Groundedness (judge-flagged answers, about 10%), three kinds:*
  - Category slips: calling a neckband "earbuds", because "bluetooth earbuds" retrieval includes neckbands.
  - Inference beyond the fields: "10W typically means no fast charging".
  - A few judge disagreements. For example, "slightly over budget" for ₹1,299 is correct relative to the
    original ₹1,000 budget, but the judge only sees the relaxed ₹1,300 cap.
- *Clarifier recall 75%.* "dal" doesn't trigger a category question. The query also matches a spice ("dal
  tadka masala"), so no single parent category covers 90% of the results.
- *Clarifier frequency.* It asks on 19/71 turns. Bare category queries ("water bottle", "jeans") get an
  attribute question ("Any preference for color?") when results spread evenly. The brief's rule allows it.
  Whether it's wanted is a product call for review.

**Caveats.**
- *The conversations aren't independent.* They were written by the same model that built the rules, and are
  marked `needs_review`. Several were checked while iterating (turn classification, refinement rules), so the
  turn-type and plan numbers are dev-set numbers, not holdout numbers.
- *The judge is an LLM too* (gpt-5.5), not human review.
- *Latency is client-measured* against Docker on a laptop. First-token time is dominated by the OpenAI API, about
  700 ms at p50.
