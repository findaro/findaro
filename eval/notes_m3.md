### M4 re-measurement (2026-10-08): chat on local Ollama, groundedness reviewed by hand

**Setup.** OpenAI credits ran out during M4, so this run uses local `llama3.1:8b` through Ollama for answers
and unclear-turn classification. That is free, but slower and weaker than gpt-4.1-mini. No paid API calls were
made. Groundedness wasn't judged by an LLM: I (Claude, the author of this system) reviewed all 68 non-chit-chat
answers by hand against the fields of the products on screen. Claim-by-claim verdicts are in
`eval/chat_review_m4.md`.

| Target | Result | |
|---|---|---|
| Groundedness ≥ 97% (every claim supported by the shown products' fields) | **66/68 = 97.1%** (48/50 model-written answers, 18/18 fallbacks) | ✅ met, just |
| 0 numeric errors | **0**: every number comes from a server-filled slot | ✅ met |
| Clarifier rate (question only for category, budget, weak match) | 8/71 turns (11%, was 19/71); recall 75%, precision 100% | |
| Negation scope ("slim fit, black nahi") | c24 nDCG 0.33 → 1.00; tests cover English and Hinglish forms | ✅ |
| Results event p95 ≤ 150 ms | 63 ms | ✅ met |
| First text token p95 ≤ 1.2 s | 6.7 s (local 8B model; the target assumed Haiku) | ❌ missed |

**How the numbers are made safe.**
- The model writes `{price:ID}`-style slots, and the server fills them from that product.
- Every sentence is checked before it streams, and dropped whole if it:
  - contains a number the model wrote itself;
  - puts a slot on a product the sentence doesn't cite;
  - names a product type that doesn't fit the cited product;
  - names an attribute value the cited product doesn't have, or another product's brand;
  - makes an uncited claim;
  - makes an "all/sabhi/both" claim that isn't true for every product it covers;
  - makes a stock claim that isn't true;
  - makes a comparison (English or Hindi) not backed by the fact computed in code.
- All checks run in code at no cost; `tests/test_slots.py` has a test for each.

**The two remaining failures** are both broad claims the checks don't parse:
- "sabhi cable ke price alag-alag hain" (every cable has a different price): three cost ₹549;
- "the products are all vegetarian and available": one is out of stock.

**Caveats.**
- *Checks built from the eval itself.* Most checks were written after reading failures on these same 25
  conversations, so 97% is a dev-set number. Expect lower on new conversations.
- *Fallbacks.* 18 of 68 answers are the plain fallback ("Top result: [ID]"), used when every sentence the 8B model
  wrote was dropped. They're grounded, but not helpful.
- *Not independent.* The reviewer is the system's author. The per-answer file exists so a person can spot-check it.
- *The conversations are still `needs_review`.*
