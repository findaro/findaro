/** UI strings. Override any of them with `el.strings = { … }`; pick defaults with the `locale` attribute. */
export interface Strings {
  placeholder: string;
  askPlaceholder: string;
  modeLabel: string;
  search: string;
  ask: string;
  send: string;
  results: string; // {n}
  withClose: string; // {n} exact, {c} close
  loading: string;
  noMatch: string; // {q}
  noMatchHint: string;
  weak: string;
  close: string;
  removeFilter: string; // {label}
  understood: string;
  refine: string;
  outOfStock: string;
  thinking: string;
  error: string;
  you: string;
  assistant: string;
  conversation: string;
  products: string;
}

export const STRINGS: Record<string, Strings> = {
  en: {
    placeholder: "Search products…",
    askPlaceholder: "Ask anything, e.g. “cheaper ones” or “is the second one leather?”",
    modeLabel: "Search mode",
    search: "Search",
    ask: "Ask AI",
    send: "Send",
    results: "{n} results",
    withClose: "{n} exact · {c} close matches",
    loading: "Searching…",
    noMatch: "No products match “{q}”.",
    noMatchHint: "Try fewer words, remove a filter, or ask the AI.",
    weak: "No exact match. Showing the closest products.",
    close: "Close match",
    removeFilter: "Remove filter: {label}",
    understood: "Understood",
    refine: "Refine",
    outOfStock: "Out of stock",
    thinking: "Thinking…",
    error: "Something went wrong. Please try again.",
    you: "You",
    assistant: "Assistant",
    conversation: "Conversation",
    products: "Products",
  },
  "hi-en": {
    placeholder: "Products dhoondhiye…",
    askPlaceholder: "Poochhiye, jaise “aur sasta” ya “dusra wala leather ka hai?”",
    modeLabel: "Search ka tareeka",
    search: "Search",
    ask: "AI se poochho",
    send: "Bhejo",
    results: "{n} results",
    withClose: "{n} exact · {c} kareeb ke",
    loading: "Dhoondh rahe hain…",
    noMatch: "“{q}” se matching koi product nahi mila.",
    noMatchHint: "Kam shabdon mein try kijiye, filter hataiye, ya AI se poochhiye.",
    weak: "Exact match nahi mila. Sabse kareeb ke products.",
    close: "Kareeb",
    removeFilter: "Filter hatao: {label}",
    understood: "Samjha",
    refine: "Aur chuniye",
    outOfStock: "Stock mein nahi",
    thinking: "Soch raha hoon…",
    error: "Kuch gadbad hui. Dobara try kijiye.",
    you: "Aap",
    assistant: "Assistant",
    conversation: "Baatcheet",
    products: "Products",
  },
};

export const fmt = (s: string, vars: Record<string, string | number>) =>
  s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
