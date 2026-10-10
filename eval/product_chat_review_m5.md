# M5 product conversation — hand review

Run: `eval/results/product-chat-20261010T211704.json` (`eval/run_product_chat.py`, seed 7). 12 demo products,
4 questions each (48 turns, English and Hinglish, one session per product). Chat model: local Ollama
`llama3.1:8b`. No paid calls. Reviewed by reading every answer and general tip against the product's listing.

| | |
|---|---|
| False claims about the product (facts part) | **0 / 48** |
| Answers that are correct and useful | 41 / 48 |
| Honest fallbacks ("couldn't answer reliably", nothing false) | 2 (AU-00343 origin, GR-00262 returns; both unlisted) |
| Grounded but weak (speculative tail or general advice in the facts part) | 5 |
| General tips shown | 21, none naming the product, a brand or a number |
| Automatic scorer | 40 / 48: every ✗ was a scorer miss (e.g. "7 din", "nahi di", quoting the listing's own "perfect for…") or one of the fallbacks above |
| First token | p50 593 ms, p95 886 ms |

Weak answers worth improving later:
- HK-00299 (suitability): "melamine products can be prone to scratches and fading when exposed to water" is general
  advice that landed in the facts part instead of the labeled "General:" line.
- AU-00203 (suitability): "…designed for daily car usage, which might imply some level of durability" (a guess).
- AP-00166 (suitability): "festival ke liye hai, roz use ke liye nahin" is an inference from "perfect for festive
  wear and special occasions", not the seller's words.
- EL-00032 general tip: "PVC can be damaged by water and heat" is generic and doubtful.
- GR-00262 (returns, 3rd run): the model described the product instead of answering; nothing false.

Fixed during this review (each with a unit test in `tests/test_slots.py`):
- return-policy answers were dropped as suitability verdicts ("You can return it within 10 days" with a 10-day
  return listed); after-sale words are now checked against the listing instead;
- "10-day replacement" restated as "you can return it", and "size exchange" as "return kar sakte hain", are dropped;
  the fallback quotes the listed policy;
- "The description doesn't mention rain" was read as "description is missing";
- "it's best to check…" was read as a ranking ("best");
- an answer that is only a question back ("Kya problem hai?") no longer counts as an answer;
- an invented origin guessed from the currency ("price is in rupees, so probably made in India") is dropped.

Earlier run of the same set before these fixes: 38/48 automatic, 13 fallbacks, several false return promises.
