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
  askShort: string;
  askAbout: string; // {title}
  drawerPlaceholder: string;
  generalLabel: string;
  suggestions: string;
  viewProduct: string;
  closeDrawer: string;
  allDetails: string;
  /** suggested questions by document field ("*" = always) */
  suggest: Record<string, string>;
  // AI Mode (thread, sidebar, cards, compare)
  assistantName: string;
  composerPlaceholder: string;
  askSelected: string; // {n}
  greeting: string;
  greetingSub: string;
  tryAsking: string;
  newChat: string;
  history: string;
  openHistory: string;
  closeHistory: string;
  noChats: string;
  today: string;
  earlier: string;
  deleteChat: string; // {title}
  deleteConfirm: string;
  deleteYes: string;
  cancel: string;
  stepThink: string;
  stepUnderstand: string;
  stepSearch: string; // {q}
  stepFound: string; // {n}
  howSearched: string;
  searchedIn: string; // {t}
  loosened: string; // {label} {reason}
  time: string;
  byMeaning: string;
  showMore: string; // {n}
  select: string;
  selectTitle: string; // {title}
  selected: string; // {n}
  compare: string;
  askThese: string;
  clear: string;
  compareMessage: string;
  maxSelect: string; // {n}
  matches: string; // {m} {t}
  notMet: string; // {label}
  notListed: string; // {label}
  view: string;
  jumpLatest: string;
  price: string;
  rating: string;
  comparing: string; // {n}
  nextSteps: string;
  // unified mode (search + assistant in one surface)
  newSearch: string;
  hint: string;
  /** mode="search" empty state (shown with starters) */
  searchHint: string;
  followUp: string;
  earlierTurns: string; // {n}
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
    refine: "Filters",
    outOfStock: "Out of stock",
    thinking: "Thinking…",
    error: "Something went wrong. Please try again.",
    you: "You",
    assistant: "Assistant",
    conversation: "Conversation",
    products: "Products",
    askShort: "Ask",
    askAbout: "Ask about {title}",
    drawerPlaceholder: "Ask anything about this product…",
    generalLabel: "General tip · not from the seller",
    suggestions: "Suggested questions",
    viewProduct: "View product",
    closeDrawer: "Close",
    allDetails: "All details",
    suggest: { material: "What is it made of?", country_of_origin: "Where is it made?",
               warranty: "Is there a warranty?", care: "How do I take care of it?",
               return_policy: "Can I return it?", "*": "Tell me more about it" },
    assistantName: "AI Mode",
    composerPlaceholder: "Describe what you're looking for…",
    askSelected: "Ask about the {n} selected products…",
    greeting: "What are you looking for today?",
    greetingSub: "Describe it in your own words. I'll search the catalog and help you narrow it down.",
    tryAsking: "Try asking",
    newChat: "New chat",
    history: "Chat history",
    openHistory: "Open chat history",
    closeHistory: "Close chat history",
    noChats: "Your conversations will appear here.",
    today: "Today",
    earlier: "Earlier",
    deleteChat: "Delete conversation: {title}",
    deleteConfirm: "Delete?",
    deleteYes: "Delete",
    cancel: "Cancel",
    stepThink: "Thinking",
    stepUnderstand: "Understanding your request",
    stepSearch: "Searching for “{q}”",
    stepFound: "Looking through {n} products",
    howSearched: "How I searched",
    searchedIn: "Searched in {t}",
    loosened: "Loosened: {label} — {reason}",
    time: "Time",
    byMeaning: "No filters: searched by meaning",
    showMore: "Show {n} more",
    select: "Select",
    selectTitle: "Select {title} to compare",
    selected: "{n} selected",
    compare: "Compare",
    askThese: "Ask about these",
    clear: "Clear",
    compareMessage: "Compare these",
    maxSelect: "You can select up to {n} products.",
    matches: "Matches {m}/{t}",
    notMet: "not {label}",
    notListed: "{label} not listed",
    view: "View",
    jumpLatest: "Jump to latest",
    price: "Price",
    rating: "Rating",
    comparing: "Comparing {n} products",
    nextSteps: "Next steps",
    newSearch: "New search",
    hint: "Results update as you type. Press Enter to ask: it narrows the results and answers questions.",
    searchHint: "Results update as you type, in English or Hinglish. Try one of these:",
    followUp: "Refine or ask a follow-up, e.g. “only leather” or “which is best for school?”",
    earlierTurns: "Conversation ({n})",
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
    refine: "Filters",
    outOfStock: "Stock mein nahi",
    thinking: "Soch raha hoon…",
    error: "Kuch gadbad hui. Dobara try kijiye.",
    you: "Aap",
    assistant: "Assistant",
    conversation: "Baatcheet",
    products: "Products",
    askShort: "Poochho",
    askAbout: "{title} ke baare mein poochho",
    drawerPlaceholder: "Is product ke baare mein kuch bhi poochhiye…",
    generalLabel: "General tip · seller ki taraf se nahi",
    suggestions: "Sujhaye gaye sawal",
    viewProduct: "Product dekhein",
    closeDrawer: "Band karein",
    allDetails: "Saari details",
    suggest: { material: "Ye kis cheez se bana hai?", country_of_origin: "Kahan bana hai?",
               warranty: "Warranty hai kya?", care: "Iski dekhbhal kaise karein?",
               return_policy: "Return ho sakta hai?", "*": "Iske baare mein aur bataiye" },
    assistantName: "AI Mode",
    composerPlaceholder: "Bataiye aapko kya chahiye…",
    askSelected: "Chune hue {n} products ke baare mein poochhiye…",
    greeting: "Aaj kya dhoondh rahe hain?",
    greetingSub: "Apne shabdon mein bataiye. Main catalog mein dhoondh kar options chhaantne mein madad karunga.",
    tryAsking: "Aise poochh ke dekhiye",
    newChat: "Nayi chat",
    history: "Purani chats",
    openHistory: "Purani chats kholo",
    closeHistory: "Purani chats band karo",
    noChats: "Aapki baatcheet yahan dikhegi.",
    today: "Aaj",
    earlier: "Pehle",
    deleteChat: "Chat delete karo: {title}",
    deleteConfirm: "Delete karein?",
    deleteYes: "Haan, delete",
    cancel: "Rehne do",
    stepThink: "Soch raha hoon",
    stepUnderstand: "Aapki baat samajh raha hoon",
    stepSearch: "“{q}” dhoondh raha hoon",
    stepFound: "{n} products dekh raha hoon",
    howSearched: "Maine kaise dhoondha",
    searchedIn: "{t} mein dhoondha",
    loosened: "Thoda dheela kiya: {label} — {reason}",
    time: "Samay",
    byMeaning: "Koi filter nahi: matlab se dhoondha",
    showMore: "{n} aur dikhao",
    select: "Chuno",
    selectTitle: "Compare ke liye chuno: {title}",
    selected: "{n} chune",
    compare: "Compare karo",
    askThese: "Inke baare mein poochho",
    clear: "Hatao",
    compareMessage: "Inko compare karo",
    maxSelect: "Ek saath {n} products tak chun sakte hain.",
    matches: "{m}/{t} match",
    notMet: "{label} nahi",
    notListed: "{label} listed nahi",
    view: "Dekho",
    jumpLatest: "Neeche latest par jao",
    price: "Daam",
    rating: "Rating",
    comparing: "{n} products ki tulna",
    nextSteps: "Aage kya karein",
    newSearch: "Naya search",
    hint: "Type karte hi results badalte hain. Enter dabaiye: results chhaant kar sawalon ka jawab milega.",
    searchHint: "Type karte hi results badalte hain, English ya Hinglish mein. Inmein se koi try kijiye:",
    followUp: "Aur chhaantiye ya poochhiye, jaise “sirf leather” ya “school ke liye kaunsa best hai?”",
    earlierTurns: "Baatcheet ({n})",
  },
};

export const fmt = (s: string, vars: Record<string, string | number>) =>
  s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
