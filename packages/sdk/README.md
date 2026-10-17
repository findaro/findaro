# @findaro/sdk

Headless client for findaro AI search. TypeScript, zero runtime dependencies, ESM + UMD.

```ts
import { createClient } from "@findaro/sdk";

const findaro = createClient({ projectId: "prj_…", searchKey: "fdr_search_…", baseUrl: "http://localhost:8000" });

const res = await findaro.search("kaale joote 1000 ke andar");
res.understood?.chips;   // [{ label: "Under ₹1,000", remove: [...] }, { label: "Black", ... }]
await findaro.search({ query: "kaale joote 1000 ke andar", patch: res.understood!.chips[1].remove });

for await (const ev of findaro.chat("sasta wala", { sessionId })) {
  if (ev.type === "text") process.stdout.write(ev.data.delta);
}
```

Types are generated from the API's OpenAPI spec (`openapi.json`).
