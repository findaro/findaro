# @zerch/sdk

Headless client for zerch AI search. TypeScript, zero runtime dependencies, ESM + UMD.

```ts
import { createClient } from "@zerch/sdk";

const zerch = createClient({ projectId: "prj_…", searchKey: "zk_search_…", baseUrl: "http://localhost:8000" });

const res = await zerch.search("kaale joote 1000 ke andar");
res.understood?.chips;   // [{ label: "Under ₹1,000", remove: [...] }, { label: "Black", ... }]
await zerch.search({ query: "kaale joote 1000 ke andar", patch: res.understood!.chips[1].remove });

for await (const ev of zerch.chat("sasta wala", { sessionId })) {
  if (ev.type === "text") process.stdout.write(ev.data.delta);
}
```

Types are generated from the API's OpenAPI spec (`openapi.json`).
