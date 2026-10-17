"use strict";(()=>{var z=class extends Error{constructor(t,r,s){super(t);this.status=r;this.code=s;this.name="ZerchError"}},C=c=>c instanceof Error&&c.name==="AbortError",F=c=>c instanceof TypeError;function U(c){let e=new AbortController;return c&&(c.aborted?e.abort(c.reason):c.addEventListener("abort",()=>e.abort(c.reason),{once:!0})),e}function M(c){let e=(c.baseUrl||"http://localhost:8000").replace(/\/+$/,""),t=c.fetch||globalThis.fetch.bind(globalThis),r={};function s(n,l={}){l.cancelPrevious!==!1&&r[n]?.abort();let g=U(l.signal);return r[n]=g,g}async function o(n,l,g,m="application/json"){let x={method:"POST",signal:g,headers:{authorization:`Bearer ${c.searchKey}`,"content-type":"application/json",accept:m},body:JSON.stringify(l)},f;try{f=await t(e+n,x)}catch(d){if(C(d)||!F(d)||g.aborted)throw d;f=await t(e+n,x)}if(!f.ok){let d="http_error",u=`${f.status} ${f.statusText}`;try{let b=await f.json();d=b?.error?.code??d,u=b?.error?.message??u}catch{}throw new z(u,f.status,d)}return f}async function a(n,l={}){let g=typeof n=="string"?{query:n}:n,m=s("search",l);try{return await(await o("/v1/search",g,m.signal)).json()}finally{r.search===m&&(r.search=void 0)}}function p(n,l={}){let g=s("chat",l),m=[],x=null,f=!1,d=null,u={sessionId:l.sessionId??null,text:"",general:"",plan:null,results:null,clarify:null,done:null},b=h=>{switch(h.type){case"session":u.sessionId=h.data.session_id,l.onSession?.(h.data);break;case"plan":u.plan=h.data,l.onPlan?.(h.data);break;case"results":u.results=h.data,l.onResults?.(h.data);break;case"clarify":u.clarify=h.data,l.onClarify?.(h.data);break;case"text":h.data.part==="general"?u.general+=h.data.delta:u.text+=h.data.delta,l.onText?.(h.data,u.text);break;case"done":u.done=h.data,l.onDone?.(h.data);break}m.push(h),x?.()},A=(async()=>{let h={message:n,session_id:l.sessionId??null};l.patch&&(h.patch=l.patch),l.productIds?.length&&(h.product_ids=l.productIds);let T=await o("/v1/chat",h,g.signal,"text/event-stream");if(!T.body)throw new z("streaming not supported by this fetch",0,"no_stream");let O=T.body.getReader(),q=new TextDecoder,v="";for(;;){let{value:j,done:$}=await O.read();if($)break;v+=q.decode(j,{stream:!0});let S;for(;(S=v.indexOf(`

`))>=0;){let N=v.slice(0,S);v=v.slice(S+2);let I="message",E="";for(let k of N.split(`
`))k.startsWith("event:")?I=k.slice(6).trim():k.startsWith("data:")&&(E+=k.slice(5).trim());E&&b({type:I,data:JSON.parse(E)})}}})().catch(h=>{d=h,C(h)||l.onError?.(h instanceof Error?h:new Error(String(h)))}).finally(()=>{f=!0,r.chat===g&&(r.chat=void 0),x?.()}).then(()=>{if(d)throw d;return u});return A.catch(()=>{}),{result:A,cancel:()=>g.abort(),async*[Symbol.asyncIterator](){for(;;){if(m.length){yield m.shift();continue}if(f){if(d&&!C(d))throw d;return}await new Promise(h=>x=h),x=null}}}}return{projectId:c.projectId,search:a,chat:p}}function _(c,e=250){let t,r=(...s)=>new Promise((o,a)=>{t&&clearTimeout(t),t=setTimeout(()=>{try{o(c(...s))}catch(p){a(p)}},e)});return r.cancel=()=>t&&clearTimeout(t),r}var P={en:{placeholder:"Search products\u2026",askPlaceholder:"Ask anything, e.g. \u201Ccheaper ones\u201D or \u201Cis the second one leather?\u201D",modeLabel:"Search mode",search:"Search",ask:"Ask AI",send:"Send",results:"{n} results",withClose:"{n} exact \xB7 {c} close matches",loading:"Searching\u2026",noMatch:"No products match \u201C{q}\u201D.",noMatchHint:"Try fewer words, remove a filter, or ask the AI.",weak:"No exact match. Showing the closest products.",close:"Close match",removeFilter:"Remove filter: {label}",understood:"Understood",refine:"Filters",outOfStock:"Out of stock",thinking:"Thinking\u2026",error:"Something went wrong. Please try again.",you:"You",assistant:"Assistant",conversation:"Conversation",products:"Products",askShort:"Ask",askAbout:"Ask about {title}",drawerPlaceholder:"Ask anything about this product\u2026",generalLabel:"General tip \xB7 not from the seller",suggestions:"Suggested questions",viewProduct:"View product",closeDrawer:"Close",allDetails:"All details",suggest:{material:"What is it made of?",country_of_origin:"Where is it made?",warranty:"Is there a warranty?",care:"How do I take care of it?",return_policy:"Can I return it?","*":"Tell me more about it"}},"hi-en":{placeholder:"Products dhoondhiye\u2026",askPlaceholder:"Poochhiye, jaise \u201Caur sasta\u201D ya \u201Cdusra wala leather ka hai?\u201D",modeLabel:"Search ka tareeka",search:"Search",ask:"AI se poochho",send:"Bhejo",results:"{n} results",withClose:"{n} exact \xB7 {c} kareeb ke",loading:"Dhoondh rahe hain\u2026",noMatch:"\u201C{q}\u201D se matching koi product nahi mila.",noMatchHint:"Kam shabdon mein try kijiye, filter hataiye, ya AI se poochhiye.",weak:"Exact match nahi mila. Sabse kareeb ke products.",close:"Kareeb",removeFilter:"Filter hatao: {label}",understood:"Samjha",refine:"Filters",outOfStock:"Stock mein nahi",thinking:"Soch raha hoon\u2026",error:"Kuch gadbad hui. Dobara try kijiye.",you:"Aap",assistant:"Assistant",conversation:"Baatcheet",products:"Products",askShort:"Poochho",askAbout:"{title} ke baare mein poochho",drawerPlaceholder:"Is product ke baare mein kuch bhi poochhiye\u2026",generalLabel:"General tip \xB7 seller ki taraf se nahi",suggestions:"Sujhaye gaye sawal",viewProduct:"Product dekhein",closeDrawer:"Band karein",allDetails:"Saari details",suggest:{material:"Ye kis cheez se bana hai?",country_of_origin:"Kahan bana hai?",warranty:"Warranty hai kya?",care:"Iski dekhbhal kaise karein?",return_policy:"Return ho sakta hai?","*":"Iske baare mein aur bataiye"}}},y=(c,e)=>c.replace(/\{(\w+)\}/g,(t,r)=>String(e[r]??""));var D=`
:host {
  --zerch-accent: #ff6a00;
  --zerch-accent-ink: #ffffff;
  --zerch-bg: #ffffff;
  --zerch-surface: #f5f5f6;
  --zerch-fg: #18181b;
  --zerch-muted: #71717a;
  --zerch-border: #e4e4e7;
  --zerch-chip-bg: #f4f4f5;
  --zerch-chip-fg: #18181b;
  --zerch-warn: #a16207;
  --zerch-radius: 12px;
  --zerch-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --zerch-card-min: 160px;
  --zerch-ph-l: 92%;
  --zerch-ph-s: 55%;
  display: block;
  color: var(--zerch-fg);
  font: 15px/1.45 var(--zerch-font);
  container-type: inline-size;
}
@media (prefers-color-scheme: dark) {
  :host(:not([theme="light"])) {
    --zerch-bg: #111113; --zerch-surface: #1b1b1f; --zerch-fg: #ececef; --zerch-muted: #a1a1aa;
    --zerch-border: #2e2e33; --zerch-chip-bg: #232328; --zerch-chip-fg: #ececef; --zerch-warn: #eab308;
    --zerch-ph-l: 20%;
    --zerch-ph-s: 18%;
  }
}
:host([theme="dark"]) {
  --zerch-bg: #111113; --zerch-surface: #1b1b1f; --zerch-fg: #ececef; --zerch-muted: #a1a1aa;
  --zerch-border: #2e2e33; --zerch-chip-bg: #232328; --zerch-chip-fg: #ececef; --zerch-warn: #eab308;
  --zerch-ph-l: 20%;
  --zerch-ph-s: 18%;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
.root { background: var(--zerch-bg); display: grid; gap: 14px; }
button { font: inherit; color: inherit; cursor: pointer; }
:focus-visible { outline: 2px solid var(--zerch-accent); outline-offset: 2px; }

/* search bar: [Search | Ask AI] [input] [button] in one pill */
.box { display: flex; align-items: center; gap: 6px; padding: 5px; min-width: 0;
       border: 1px solid var(--zerch-border); border-radius: 999px; background: var(--zerch-bg);
       box-shadow: 0 1px 2px rgb(0 0 0 / .05); }
.box:focus-within { border-color: var(--zerch-accent); }
.modes { display: inline-flex; flex: none; background: var(--zerch-surface); border-radius: 999px; padding: 2px; }
.modes button { border: 0; background: none; padding: 6px 12px; border-radius: 999px; font-size: 13px;
                font-weight: 600; color: var(--zerch-muted); white-space: nowrap; }
.modes button[aria-checked="true"] { background: var(--zerch-bg); color: var(--zerch-fg);
                                     box-shadow: 0 1px 2px rgb(0 0 0 / .12); }
.box input { flex: 1; min-width: 0; border: 0; padding: 8px 6px; font: inherit; color: var(--zerch-fg);
             background: transparent; }
.box input:focus { outline: none; }
.box input::placeholder { color: var(--zerch-muted); }
.go { flex: none; border: 0; border-radius: 999px; background: var(--zerch-accent); color: var(--zerch-accent-ink);
      padding: 9px 18px; font-weight: 600; }
@container (max-width: 480px) {
  .box { flex-wrap: wrap; border-radius: 18px; }
  .modes { order: -1; }
  .box input { flex-basis: 100%; order: 1; padding: 8px 10px; }
  .go { margin-left: auto; }
}

/* understood chips + filters toggle, one line */
.row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chip { display: inline-flex; align-items: center; gap: 2px; padding: 3px 4px 3px 12px; border-radius: 999px;
        background: var(--zerch-chip-bg); color: var(--zerch-chip-fg); font-size: 13px; font-weight: 500;
        border: 1px solid var(--zerch-border); }
.chip.boost, .chip.sort { background: transparent; }
.chip button { border: 0; background: none; color: var(--zerch-muted); width: 22px; height: 22px;
               border-radius: 50%; line-height: 1; font-size: 15px; }
.chip button:hover { color: var(--zerch-fg); background: var(--zerch-border); }
.filters-toggle { margin-left: auto; border: 0; background: none; color: var(--zerch-muted); font-size: 13px;
                  font-weight: 600; padding: 4px 6px; }
.filters-toggle:hover { color: var(--zerch-fg); }
.pills { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--zerch-border);
         border-radius: var(--zerch-radius); background: var(--zerch-surface); }
.row-label { font-size: 12px; color: var(--zerch-muted); min-width: 64px; }
.pill { border: 1px solid var(--zerch-border); background: var(--zerch-bg); border-radius: 999px;
        padding: 4px 12px; font-size: 13px; }
.pill:hover { border-color: var(--zerch-fg); }
.pill small { color: var(--zerch-muted); margin-left: 4px; }

.layout { display: grid; gap: 14px; }
.status { font-size: 13px; color: var(--zerch-muted); min-height: 1.2em; margin-bottom: 8px; }
.status.weak { color: var(--zerch-warn); }

/* product grid */
.grid { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px;
        grid-template-columns: repeat(auto-fill, minmax(var(--zerch-card-min), 1fr)); }
.card { display: flex; flex-direction: column; height: 100%; text-decoration: none; color: inherit; border: 0;
        background: none; text-align: left; padding: 0; width: 100%; }
.card .img { border-radius: var(--zerch-radius); }
.card:hover .title { text-decoration: underline; }
.img { aspect-ratio: 4 / 3; width: 100%; object-fit: cover; background: var(--zerch-surface); display: grid;
       place-items: center; font-size: 26px; font-weight: 600; color: var(--zerch-muted); }
.img.ph { background: hsl(var(--h) var(--zerch-ph-s) var(--zerch-ph-l)); color: hsl(var(--h) 30% 50%); }
.body { padding: 8px 2px 0; display: grid; gap: 2px; }
.title { font-size: 14px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
         overflow: hidden; }
.price { font-weight: 700; font-size: 15px; }
.mrp { color: var(--zerch-muted); text-decoration: line-through; font-weight: 400; font-size: 12px;
       margin-left: 6px; }
.meta { font-size: 12px; color: var(--zerch-muted); display: flex; gap: 8px; flex-wrap: wrap; }
.badge { font-size: 11px; font-weight: 600; color: var(--zerch-warn); }

.empty { border: 1px dashed var(--zerch-border); border-radius: var(--zerch-radius); padding: 28px;
         text-align: center; color: var(--zerch-muted); }
.empty strong { display: block; color: var(--zerch-fg); margin-bottom: 4px; }

/* AI answer card, full width above the results */
.panel { border: 1px solid var(--zerch-border); border-radius: var(--zerch-radius); background: var(--zerch-surface);
         padding: 14px 16px; display: grid; gap: 12px; max-height: 50vh; overflow: auto; }
.panel:empty { display: none; }
.msg { display: grid; gap: 4px; }
.msg .who { font-size: 11px; font-weight: 600; color: var(--zerch-muted); text-transform: uppercase;
            letter-spacing: .04em; }
.msg.user .text { font-weight: 600; }
.msg .text { white-space: pre-wrap; }
.mini { display: inline-flex; align-items: center; gap: 6px; vertical-align: middle; max-width: 100%;
        border: 1px solid var(--zerch-border); background: var(--zerch-bg); border-radius: 8px;
        padding: 2px 8px 2px 2px; font-size: 13px; margin: 1px 0; color: inherit; }
.mini .img { width: 26px; height: 26px; aspect-ratio: 1; font-size: 12px; border-radius: 6px; }
.mini span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.clarify { display: grid; gap: 8px; margin-top: 4px; }
.clarify p { margin: 0; font-weight: 600; }
/* "Ask" button on each card */
.cell { position: relative; }
.ask { position: absolute; top: 8px; right: 8px; border: 1px solid var(--zerch-border); border-radius: 999px;
       background: var(--zerch-bg); color: var(--zerch-fg); font-size: 12px; font-weight: 600; padding: 4px 10px;
       box-shadow: 0 1px 3px rgb(0 0 0 / .12); }
.ask:hover { border-color: var(--zerch-accent); color: var(--zerch-accent); }

/* product drawer */
.scrim { position: fixed; inset: 0; background: rgb(0 0 0 / .35); z-index: 2147483000; }
.drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(440px, 100vw); z-index: 2147483001;
          background: var(--zerch-bg); color: var(--zerch-fg); display: grid; grid-template-rows: auto 1fr auto;
          box-shadow: -8px 0 24px rgb(0 0 0 / .18); font: 15px/1.45 var(--zerch-font); }
.dhead { display: flex; align-items: start; gap: 12px; padding: 16px 16px 8px;
         padding-top: calc(16px + env(safe-area-inset-top, 0px)); border-bottom: 1px solid var(--zerch-border); }
.dhead h2 { flex: 1; margin: 0; font-size: 16px; line-height: 1.35; }
.close { border: 0; background: none; font-size: 22px; line-height: 1; color: var(--zerch-muted); padding: 2px 6px; }
.close:hover { color: var(--zerch-fg); }
.dbody { overflow: auto; padding: 14px 16px; display: grid; gap: 14px; align-content: start; }
.summary { display: grid; grid-template-columns: 96px 1fr; gap: 12px; align-items: center; }
.summary .img { aspect-ratio: 1; border-radius: 10px; font-size: 22px; }
.summary .price { font-size: 18px; font-weight: 700; }
.link { font-size: 13px; color: var(--zerch-accent); }
.factsbox { display: grid; gap: 6px; padding: 10px 12px; background: var(--zerch-surface); border-radius: 10px; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; margin: 0; font-size: 13px; }
.factsbox details summary { cursor: pointer; font-size: 13px; font-weight: 600; color: var(--zerch-muted); }
.factsbox details[open] summary { margin-bottom: 6px; }
.facts dt { color: var(--zerch-muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.thread { display: grid; gap: 12px; }
.thread:empty { display: none; }
.general { margin-top: 6px; padding: 8px 10px; border-left: 3px solid var(--zerch-border); background: var(--zerch-surface);
           border-radius: 0 8px 8px 0; font-size: 14px; color: var(--zerch-muted); display: grid; gap: 2px; }
.dfoot { padding: 10px 12px; padding-bottom: calc(10px + env(safe-area-inset-bottom, 0px));
         border-top: 1px solid var(--zerch-border); }
.dfoot .box { box-shadow: none; flex-wrap: nowrap; border-radius: 999px; }
.dfoot .box input { flex: 1 1 auto; order: 0; padding: 8px 10px; }
.dfoot .box .go { margin-left: 0; }

.typing::after { content: "\u258D"; animation: blink 1s steps(1) infinite; }
@keyframes blink { 50% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { /* "Ask" button on each card */
.cell { position: relative; }
.ask { position: absolute; top: 8px; right: 8px; border: 1px solid var(--zerch-border); border-radius: 999px;
       background: var(--zerch-bg); color: var(--zerch-fg); font-size: 12px; font-weight: 600; padding: 4px 10px;
       box-shadow: 0 1px 3px rgb(0 0 0 / .12); }
.ask:hover { border-color: var(--zerch-accent); color: var(--zerch-accent); }

/* product drawer */
.scrim { position: fixed; inset: 0; background: rgb(0 0 0 / .35); z-index: 2147483000; }
.drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(440px, 100vw); z-index: 2147483001;
          background: var(--zerch-bg); color: var(--zerch-fg); display: grid; grid-template-rows: auto 1fr auto;
          box-shadow: -8px 0 24px rgb(0 0 0 / .18); font: 15px/1.45 var(--zerch-font); }
.dhead { display: flex; align-items: start; gap: 12px; padding: 16px 16px 8px;
         padding-top: calc(16px + env(safe-area-inset-top, 0px)); border-bottom: 1px solid var(--zerch-border); }
.dhead h2 { flex: 1; margin: 0; font-size: 16px; line-height: 1.35; }
.close { border: 0; background: none; font-size: 22px; line-height: 1; color: var(--zerch-muted); padding: 2px 6px; }
.close:hover { color: var(--zerch-fg); }
.dbody { overflow: auto; padding: 14px 16px; display: grid; gap: 14px; align-content: start; }
.summary { display: grid; grid-template-columns: 96px 1fr; gap: 12px; align-items: center; }
.summary .img { aspect-ratio: 1; border-radius: 10px; font-size: 22px; }
.summary .price { font-size: 18px; font-weight: 700; }
.link { font-size: 13px; color: var(--zerch-accent); }
.factsbox { display: grid; gap: 6px; padding: 10px 12px; background: var(--zerch-surface); border-radius: 10px; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; margin: 0; font-size: 13px; }
.factsbox details summary { cursor: pointer; font-size: 13px; font-weight: 600; color: var(--zerch-muted); }
.factsbox details[open] summary { margin-bottom: 6px; }
.facts dt { color: var(--zerch-muted); }
.facts dd { margin: 0; overflow-wrap: anywhere; }
.thread { display: grid; gap: 12px; }
.thread:empty { display: none; }
.general { margin-top: 6px; padding: 8px 10px; border-left: 3px solid var(--zerch-border); background: var(--zerch-surface);
           border-radius: 0 8px 8px 0; font-size: 14px; color: var(--zerch-muted); display: grid; gap: 2px; }
.dfoot { padding: 10px 12px; padding-bottom: calc(10px + env(safe-area-inset-bottom, 0px));
         border-top: 1px solid var(--zerch-border); }
.dfoot .box { box-shadow: none; flex-wrap: nowrap; border-radius: 999px; }
.dfoot .box input { flex: 1 1 auto; order: 0; padding: 8px 10px; }
.dfoot .box .go { margin-left: 0; }

.typing::after { animation: none; } }
`;var L={};{let c=typeof document<"u"?document.currentScript:null;if(c?.dataset)for(let[e,t]of Object.entries({project:c.dataset.project,key:c.dataset.key,"base-url":c.dataset.baseUrl,locale:c.dataset.locale,mode:c.dataset.mode}))t&&(L[e]=t)}function i(c,e={},...t){let r=document.createElement(c);for(let[s,o]of Object.entries(e))o==null||o===!1||(s.startsWith("on")&&typeof o=="function"?r.addEventListener(s.slice(2),o):s==="class"?r.className=String(o):r.setAttribute(s,o===!0?"":String(o)));for(let s of t)s!=null&&s!==!1&&r.append(s);return r}var w={};function H(c){if(typeof c!="string"||!c)return null;try{let e=new URL(c,location.href);return e.protocol==="http:"||e.protocol==="https:"?e.href:null}catch{return null}}var R=class extends HTMLElement{static observedAttributes=["mode","locale","placeholder","project","key","base-url"];renderProduct=null;onProductClick=null;strings={};client=null;#d;#i="search";#a="";#l=[];#t=null;#y=!1;#g="";#f=null;#b=[];#v=new Map;#r;#A=_(()=>this.#z(),250);constructor(){super(),this.#d=this.attachShadow({mode:"open"})}connectedCallback(){this.#i=this.#n("mode")==="ai"?"ai":"search",this.#q(),this.#c()}attributeChangedCallback(e){!this.isConnected||!this.#r||(e==="mode"?this.#T(this.#n("mode")==="ai"?"ai":"search"):["project","key","base-url"].includes(e)&&(this.client=null),this.#c())}search(e){this.#r.value=e,this.#I()}get#s(){return{...P[this.#n("locale")||"en"]||P.en,...this.strings}}#n(e){return this.getAttribute(e)??L[e]??null}#w(){if(!this.client){let e=this.#n("key");if(!e||/^YOUR_/i.test(e))throw new Error("zerch-search: set data-key on the script tag (or key=\u2026) to your project's search key");this.client=M({projectId:this.#n("project")||"",searchKey:e,baseUrl:this.#n("base-url")||void 0})}return this.client}#e={};#q(){let e=this.#s;this.#d.innerHTML="",this.#d.append(i("style",{},D)),this.#r=i("input",{type:"search","aria-label":e.placeholder,autocomplete:"off",enterkeyhint:"search",oninput:()=>this.#j(),onkeydown:s=>this.#$(s)});let t=(s,o)=>i("button",{type:"button",role:"radio","data-mode":s,onclick:()=>this.#T(s,!0)},o);this.#e.modes=i("div",{class:"modes",role:"radiogroup","aria-label":e.modeLabel},t("search",e.search),t("ai",e.ask)),this.#e.go=i("button",{class:"go",type:"submit"},e.search);let r=i("form",{class:"box",role:"search",onsubmit:s=>{s.preventDefault(),this.#I()}},this.#e.modes,this.#r,this.#e.go);this.#e.chips=i("div",{class:"row chips",role:"group"}),this.#e.pills=i("div",{class:"pills",id:"zerch-filters"}),this.#e.status=i("div",{class:"status",role:"status","aria-live":"polite"}),this.#e.results=i("div",{}),this.#e.panel=i("div",{class:"panel",role:"log","aria-live":"polite"}),this.#e.layout=i("div",{class:"layout"},this.#e.panel,i("section",{"aria-label":e.products},this.#e.status,this.#e.results)),this.#d.append(i("div",{class:"root",part:"root"},r,this.#e.chips,this.#e.pills,this.#e.layout))}#T(e,t=!1){if(e===this.#i&&this.#e.layout){t&&this.#r.focus();return}this.#i=e,this.#c(),t&&this.#r.focus()}#k=!1;#j(){if(this.#i!=="search")return;let e=this.#r.value.trim();e!==this.#a&&(this.#l=[]),this.#a=e,this.#k=!0,e.length>=2&&this.#A()}#$(e){e.key==="Escape"&&(this.#r.value="",this.#a="",this.#l=[],this.#t=null,this.#c())}#I(){let e=this.#r.value.trim();e&&(this.#i==="ai"?(this.#r.value="",this.#p(e)):(this.#A.cancel(),e!==this.#a&&(this.#l=[]),this.#a=e,this.#k=!1,this.#z()))}async#z(){if(this.#a){this.#y=!0,this.#g="",this.#_();try{let e=await this.#w().search({query:this.#a,patch:this.#l,llm:!this.#k,size:Number(this.#n("size"))||20});this.#N(e)}catch(e){if(e.name==="AbortError")return;this.#S(e)}finally{this.#y=!1,this.#c()}}}#N(e){let t=e.understood;this.#t={total:e.total,hits:e.hits,chips:t?.chips??[],pills:e.pills??[],quality:t?.match_quality??null,close:new Set(t?.close_matches??[]),display:e.display??w,semantic:t?.semantic_text??e.query};for(let r of e.hits)this.#v.set(r.id,r);this.dispatchEvent(new CustomEvent("zerch:results",{detail:e,bubbles:!0,composed:!0}))}#M(e,t){if(this.#i==="ai"&&this.#f){this.#p(t,e);return}this.#l=[...this.#l,...e],this.#z()}#S(e){let t=e instanceof Error?e.message:"";this.#g=t.startsWith("zerch-search:")||e?.status===401?t.startsWith("zerch-search:")?t:"zerch-search: invalid search key (check data-key)":this.#s.error,this.dispatchEvent(new CustomEvent("zerch:error",{detail:e,bubbles:!0,composed:!0}))}#E="";async#p(e,t,r=!1){t||(this.#E=e);let s=!1,o={role:"user",text:e},a={role:"assistant",text:"",pending:!0,clarify:null};this.#b.push(o,a),this.#R();try{let p=this.#w().chat(t?"":e,{sessionId:this.#f,patch:t});for await(let n of p){if(n.type==="session")this.#f=n.data.session_id;else if(n.type==="plan"&&n.data.understood&&this.#t)this.#t.chips=n.data.understood.chips??[];else if(n.type==="results"&&!n.data.unchanged){let l=this.#t;this.#t={total:n.data.total,hits:n.data.items,pills:n.data.pills??[],chips:l?.chips??[],quality:n.data.match_quality??null,close:new Set(n.data.close_matches??[]),display:n.data.display??l?.display??w,semantic:e};for(let g of n.data.items)this.#v.set(g.id,g);this.#D()}else n.type==="plan"&&n.data.understood?this.#t={total:0,hits:[],pills:[],quality:null,close:new Set,display:w,chips:n.data.understood.chips??[],semantic:e}:n.type==="clarify"?a.clarify=n.data:n.type==="text"?a.text+=n.data.delta:n.type==="done"&&(a.pending=!1,s=n.data.reason==="session_expired");this.#C(),this.#R()}}catch(p){p.name!=="AbortError"&&(a.error=!0,a.text=this.#s.error,this.#S(p))}finally{a.pending=!1,this.#c()}s&&t&&!r&&this.#E&&(this.#b.splice(-2,2),this.#f=null,await this.#p(this.#E),await this.#p(e,t,!0))}#c(){let e=this.#s,t=this.#i==="ai";for(let r of this.#e.modes.querySelectorAll("button"))r.setAttribute("aria-checked",String(r.dataset.mode===this.#i));this.#r.placeholder=t?e.askPlaceholder:this.#n("placeholder")||e.placeholder,this.#r.setAttribute("aria-label",this.#r.placeholder),this.#e.go.textContent=t?e.send:e.search,this.#e.layout.classList.toggle("ai",t),this.#e.panel.hidden=!t,this.#e.panel.setAttribute("aria-label",e.conversation),this.#C(),this.#_(),this.#D(),this.#R()}#h=!1;#C(){let e=this.#s,t=this.#t,r=t?.chips??[],s=t?.pills??[],o=!!s.length&&!!t?.hits.length;this.#e.chips.replaceChildren(),this.#e.chips.hidden=!r.length&&!o,this.#e.chips.setAttribute("aria-label",e.understood);for(let a of r)this.#e.chips.append(i("span",{class:`chip ${a.kind}`,title:a.source||void 0},a.label,i("button",{type:"button","aria-label":y(e.removeFilter,{label:a.label}),onclick:()=>this.#M(a.remove??[],`\u2212 ${a.label}`)},"\xD7")));o&&this.#e.chips.append(i("button",{type:"button",class:"filters-toggle","aria-expanded":String(this.#h),"aria-controls":"zerch-filters",onclick:()=>{this.#h=!this.#h,this.#C()}},this.#h?`${e.refine} \u25B4`:`${e.refine} \u25BE`)),this.#e.pills.replaceChildren(),this.#e.pills.hidden=!o||!this.#h;for(let a of s){let p=i("div",{class:"row",role:"group","aria-label":`${e.refine}: ${a.label}`},i("span",{class:"row-label","aria-hidden":"true"},a.label));for(let n of a.values)p.append(i("button",{type:"button",class:"pill",onclick:()=>this.#M(n.patch,n.label)},n.label,i("small",{"aria-hidden":"true"},String(n.count))));this.#e.pills.append(p)}}#_(){let e=this.#s,t=this.#t,r=this.#e.status;r.className="status",this.#g?r.textContent=this.#g:this.#y?r.textContent=e.loading:t?t.quality==="weak"?(r.textContent=e.weak,r.classList.add("weak")):t.close.size?r.textContent=y(e.withClose,{n:t.hits.length-t.close.size,c:t.close.size}):r.textContent=t.hits.length?y(e.results,{n:t.total}):"":r.textContent=""}#D(){let e=this.#s,t=this.#t,r=this.#e.results;if(r.replaceChildren(),!t)return;if(!t.hits.length){r.append(i("div",{class:"empty","data-state":"no-match"},i("strong",{},y(e.noMatch,{q:this.#a||t.semantic})),e.noMatchHint));return}let s=i("ul",{class:"grid",role:"list"});for(let o of t.hits){let a=o.document,p=String((t.display.title&&a[t.display.title])??o.id);s.append(i("li",{class:"cell"},this.#F(o,t),i("button",{type:"button",class:"ask","data-ask":o.id,"aria-label":y(e.askAbout,{title:p}),onclick:n=>this.#K(o,n.currentTarget)},e.askShort)))}r.append(s)}#u=e=>{let t=typeof e=="number"?e:Number(e);if(!Number.isFinite(t))return e==null?"":String(e);let r=this.#t?.display.currency;try{return new Intl.NumberFormat(r==="INR"?"en-IN":void 0,r?{style:"currency",currency:r,maximumFractionDigits:t%1?2:0}:{maximumFractionDigits:2}).format(t)}catch{return String(t)}};#m(e,t){let r=0;for(let a of t)r=(r*31+a.charCodeAt(0))%360;let s=()=>i("div",{class:"img ph","aria-hidden":"true",style:`--h:${r}`},(t.trim()[0]||"?").toUpperCase());if(typeof e!="string"||!e||!/^(https?:)?\/\//i.test(e)&&!e.startsWith("/"))return s();let o=i("img",{class:"img",src:e,alt:"",loading:"lazy",decoding:"async"});return o.addEventListener("error",()=>o.replaceWith(s()),{once:!0}),o}#H(e,t){let r=new CustomEvent("zerch:product-click",{detail:{hit:e},bubbles:!0,composed:!0,cancelable:!0}),s=this.dispatchEvent(r);this.onProductClick?(t.preventDefault(),this.onProductClick(e,t)):s||t.preventDefault()}#F(e,t){let r=t.display,s=e.document;if(this.renderProduct){let u=this.renderProduct(e,{display:r,formatPrice:this.#u});if(typeof u!="string")return u;let b=i("div",{});return b.innerHTML=u,b}let o=this.#s,a=String((r.title&&s[r.title])??e.id),p=H(r.url?s[r.url]:null),n=r.price?s[r.price]:void 0,l=r.compare_at_price?s[r.compare_at_price]:void 0,g=r.rating?s[r.rating]:void 0,m=r.rating_count?s[r.rating_count]:void 0,x=r.in_stock?s[r.in_stock]:void 0,f=i("div",{class:"body"},t.close.has(e.id)?i("span",{class:"badge"},o.close):null,i("span",{class:"title"},a),n!=null?i("span",{class:"price"},this.#u(n),l!=null&&Number(l)>Number(n)?i("span",{class:"mrp"},this.#u(l)):null):null,i("span",{class:"meta"},g!=null?i("span",{},`\u2605 ${g}${m!=null?` (${m})`:""}`):null,x===!1?i("span",{},o.outOfStock):null)),d={class:"card","data-id":e.id,onclick:u=>this.#H(e,u)};return p?i("a",{...d,href:p,target:"_blank",rel:"noopener"},this.#m(r.image?s[r.image]:null,a),f):i("button",{...d,type:"button"},this.#m(r.image?s[r.image]:null,a),f)}#U(e){let t=this.#v.get(e);if(!t)return`[${e}]`;let r=this.#t?.display??w,s=t.document,o=String((r.title&&s[r.title])??e),a=r.price?s[r.price]:void 0;return i("button",{type:"button",class:"mini","data-id":e,onclick:p=>this.#H(t,p)},this.#m(r.image?s[r.image]:null,o),i("span",{},o+(a!=null?` \xB7 ${this.#u(a)}`:"")))}#o=null;#L=new Map;#K(e,t=null){this.#o={hit:e,msgs:[],opener:t},this.#e.drawer||(this.#e.scrim=i("div",{class:"scrim",onclick:()=>this.#P()}),this.#e.drawer=i("div",{class:"drawer",role:"dialog","aria-modal":"true","aria-labelledby":"zd-title",onkeydown:r=>r.key==="Escape"&&this.#P()}),this.#d.append(this.#e.scrim,this.#e.drawer)),this.#e.scrim.hidden=!1,this.#e.drawer.hidden=!1,this.#x(),this.#e.drawer.querySelector("input")?.focus()}#P(){if(!this.#o)return;let e=this.#o.opener;this.#o=null,this.#e.drawer.hidden=!0,this.#e.scrim.hidden=!0,e?.focus()}#W(e,t){let r=new Set([t.id,t.title,t.price,t.compare_at_price,t.image,t.url,t.rating,t.rating_count,t.in_stock,t.currency].filter(Boolean)),s=[];for(let[o,a]of Object.entries(e)){if(r.has(o)||a==null||a===""||typeof a=="object"&&!Array.isArray(a)||t.currency&&a===t.currency)continue;let p=o.replace(/_/g," ").replace(/^./,l=>l.toUpperCase()),n=Array.isArray(a)?a.join(", "):String(a);s.push([p,n.includes(" > ")?n.split(" > ").pop():n])}return s}#x(){let e=this.#o;if(!e)return;let t=this.#s,r=this.#t?.display??w,s=e.hit.document,o=String((r.title&&s[r.title])??e.hit.id),a=r.price?s[r.price]:void 0,p=r.rating?s[r.rating]:void 0,n=r.in_stock?s[r.in_stock]:void 0,l=H(r.url?s[r.url]:null),g=i("div",{class:"thread",role:"log","aria-live":"polite"});for(let d of e.msgs){let u=i("div",{class:`text${d.pending?" typing":""}`},d.role==="assistant"&&d.pending&&!d.text?t.thinking:d.text.replace(/\[[^\]\s]+\]/g,"").trim()),b=i("div",{class:`msg ${d.role}`},i("span",{class:"who"},d.role==="user"?t.you:t.assistant),u);d.general?.trim()&&b.append(i("div",{class:"general"},i("span",{class:"who"},t.generalLabel),d.general.trim())),g.append(b)}let m=i("div",{class:"row suggestions",role:"group","aria-label":t.suggestions});if(!e.msgs.length){let d=new Set;for(let[u,b]of Object.entries(t.suggest))(u==="*"||s[u]!=null)&&!d.has(b)&&(d.add(b),m.append(i("button",{type:"button",class:"pill",onclick:()=>this.#O(b)},b)))}let x=i("input",{type:"text","aria-label":t.drawerPlaceholder,placeholder:t.drawerPlaceholder,autocomplete:"off"}),f=i("form",{class:"box",onsubmit:d=>{d.preventDefault();let u=x.value.trim();u&&this.#O(u)}},x,i("button",{class:"go",type:"submit"},t.send));this.#e.drawer.replaceChildren(i("div",{class:"dhead"},i("h2",{id:"zd-title"},o),i("button",{type:"button",class:"close","aria-label":t.closeDrawer,onclick:()=>this.#P()},"\xD7")),i("div",{class:"dbody"},i("div",{class:"summary"},this.#m(r.image?s[r.image]:null,o),i("div",{},a!=null?i("div",{class:"price"},this.#u(a)):null,i("div",{class:"meta"},p!=null?i("span",{},`\u2605 ${p}`):null,n===!1?i("span",{},t.outOfStock):null),l?i("a",{href:l,target:"_blank",rel:"noopener",class:"link"},t.viewProduct):null)),this.#V(this.#W(s,r)),g,m),i("div",{class:"dfoot"},f)),g.lastElementChild?.scrollIntoView({block:"nearest"})}#V(e){let t=e.filter(([,o])=>o.length<=40).slice(0,6),r=e.filter(o=>!t.includes(o)),s=o=>i("dl",{class:"facts"},...o.flatMap(([a,p])=>[i("dt",{},a),i("dd",{},p)]));return i("div",{class:"factsbox"},t.length?s(t):null,r.length?i("details",{},i("summary",{},this.#s.allDetails),s(r)):null)}async#O(e){let t=this.#o;if(!t)return;let r=t.hit.id,s={role:"assistant",text:"",general:"",pending:!0};t.msgs.push({role:"user",text:e},s),this.#x();try{let o=this.#w().chat(e,{sessionId:this.#L.get(r)??null,productIds:[r],cancelPrevious:!1});for await(let a of o)a.type==="session"?this.#L.set(r,a.data.session_id):a.type==="text"?a.data.part==="general"?s.general+=a.data.delta:s.text+=a.data.delta:a.type==="done"&&(s.pending=!1),this.#o===t&&this.#x()}catch(o){s.text=this.#s.error,this.#S(o)}finally{s.pending=!1,this.#o===t&&(this.#x(),this.#e.drawer.querySelector("input")?.focus())}}#R(){if(this.#i!=="ai")return;let e=this.#s,t=this.#e.panel;t.replaceChildren();for(let[r,s]of this.#b.entries()){let o=i("div",{class:`text${s.pending?" typing":""}`});if(s.role==="assistant"){for(let n of s.text.split(/(\[[^\]\s]+\])/)){let l=/^\[([^\]\s]+)\]$/.exec(n)?.[1];o.append(l?this.#U(l):n)}s.pending&&!s.text&&o.append(e.thinking)}else o.textContent=s.text;let a=i("div",{class:`msg ${s.role}`},i("span",{class:"who"},s.role==="user"?e.you:e.assistant),o),p=s.clarify;if(p&&r===this.#b.length-1){let n=i("div",{class:"row",role:"group","aria-label":p.question});for(let l of p.chips)n.append(i("button",{type:"button",class:"pill","data-clarify":"",onclick:()=>this.#p(l.label,l.patch?.length?l.patch:void 0)},l.label,l.count!=null?i("small",{"aria-hidden":"true"},String(l.count)):null));a.append(i("div",{class:"clarify"},i("p",{},p.question),n))}t.append(a)}t.scrollTop=t.scrollHeight}};typeof customElements<"u"&&!customElements.get("zerch-search")&&customElements.define("zerch-search",R);})();
//# sourceMappingURL=zerch-widget.js.map
