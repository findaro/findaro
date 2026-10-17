/* zerch site — small progressive enhancements. Every page works without this file. */
(function () {
  "use strict";
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* private mode / blocked storage: fine, just don't remember */ }
    return null;
  }

  /* ---------- mobile nav ---------- */
  var toggle = $(".nav-toggle");
  var nav = $("#site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && nav.classList.contains("open")) {
        nav.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.focus();
      }
    });
  }

  /* ---------- currency toggle (INR default) ---------- */
  var CUR_KEY = "zerch-currency";
  function setCurrency(cur) {
    $$(".currency button").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-currency") === cur ? "true" : "false");
    });
    $$("[data-inr]").forEach(function (el) {
      el.textContent = el.getAttribute(cur === "usd" ? "data-usd" : "data-inr");
    });
  }
  if ($(".currency")) {
    var saved = store(CUR_KEY);
    setCurrency(saved === "usd" ? "usd" : "inr");
    $$(".currency button").forEach(function (b) {
      b.addEventListener("click", function () {
        var cur = b.getAttribute("data-currency");
        setCurrency(cur);
        store(CUR_KEY, cur);
      });
    });
  }

  /* ---------- hero: query → understood plan ---------- */
  // Chip labels mirror what /v1/search returns in `understood.chips` (soft = boost/sort, not a hard filter).
  var EXAMPLES = [
    { q: "kaale joote 1000 ke andar", chips: [["Under ₹1,000"], ["Black"]], lang: "Hinglish", text: "black shoes" },
    { q: "sasta pressure cooker", chips: [["Pressure Cookers", 1], ["Lower prices first", 1]], lang: "Hinglish", text: "pressure cooker" },
    { q: "cotton kurta for men under 800", chips: [["Under ₹800"], ["Cotton"], ["Men"]], lang: "English", text: "cotton kurta" },
    { q: "gents chappal 500 se kam", chips: [["Under ₹500"], ["Men"]], lang: "Hinglish", text: "men chappal" }
  ];
  var qtext = $("#qtext");
  if (qtext) {
    var chipsEl = $("#qchips"), langEl = $("#qlang"), semEl = $("#qsem");
    var i = 0;
    var show = function (typed) { qtext.textContent = typed; };
    var renderChips = function (ex) {
      chipsEl.textContent = "";
      ex.chips.forEach(function (chip, n) {
        var label = chip[0];
        var c = document.createElement("span");
        c.className = "chip" + (chip[1] ? " soft" : "");
        c.style.animationDelay = (n * 90) + "ms";
        c.textContent = label + " ";
        var x = document.createElement("span");
        x.className = "x"; x.setAttribute("aria-hidden", "true"); x.textContent = "×";
        c.appendChild(x);
        chipsEl.appendChild(c);
      });
      langEl.textContent = ex.lang;
      semEl.textContent = "“" + ex.text + "”";
    };
    if (reduceMotion) {
      show(EXAMPLES[0].q); renderChips(EXAMPLES[0]);
    } else {
      var run = function () {
        var ex = EXAMPLES[i % EXAMPLES.length];
        var n = 0;
        chipsEl.textContent = "";
        var tick = setInterval(function () {
          n++;
          show(ex.q.slice(0, n));
          if (n >= ex.q.length) {
            clearInterval(tick);
            setTimeout(function () { renderChips(ex); }, 250);
            setTimeout(function () { i++; run(); }, 3600);
          }
        }, 55);
      };
      run();
    }
  }

  /* ---------- live demo ---------- */
  var demo = $("zerch-search#demo-widget");
  $$(".try button[data-q]").forEach(function (b) {
    b.addEventListener("click", function () {
      var el = $("zerch-search#demo-widget");
      if (!el || typeof el.search !== "function") {
        var fb = $("#demo-fallback");
        if (fb) fb.classList.add("show");
        return;
      }
      el.setAttribute("mode", b.getAttribute("data-mode") === "ai" ? "ai" : "search");
      el.search(b.getAttribute("data-q"));
      el.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
    });
  });
  if (demo) {
    window.addEventListener("load", function () {
      setTimeout(function () {
        if (!window.customElements || !window.customElements.get("zerch-search")) {
          var fb = $("#demo-fallback");
          if (fb) fb.classList.add("show");
        }
      }, 3000);
    });
  }

  /* ---------- code tabs ---------- */
  $$("[role=tablist]").forEach(function (list) {
    var tabs = $$("[role=tab]", list);
    function select(tab) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on ? "true" : "false");
        t.tabIndex = on ? 0 : -1;
        var panel = document.getElementById(t.getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      });
    }
    tabs.forEach(function (t, idx) {
      t.addEventListener("click", function () { select(t); });
      t.addEventListener("keydown", function (e) {
        var d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!d) return;
        var next = tabs[(idx + d + tabs.length) % tabs.length];
        select(next); next.focus(); e.preventDefault();
      });
    });
  });

  /* ---------- copy buttons ---------- */
  if (navigator.clipboard) {
    $$("pre").forEach(function (pre) {
      if (pre.closest(".no-copy")) return;
      var wrap = document.createElement("div");
      wrap.className = "codeblock";
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
      var btn = document.createElement("button");
      btn.type = "button"; btn.className = "copy"; btn.textContent = "Copy";
      btn.setAttribute("aria-label", "Copy code");
      btn.addEventListener("click", function () {
        navigator.clipboard.writeText(pre.innerText).then(function () {
          btn.textContent = "Copied";
          setTimeout(function () { btn.textContent = "Copy"; }, 1500);
        });
      });
      wrap.appendChild(btn);
    });
  }

  /* ---------- request access form ---------- */
  var form = $("#access-form");
  if (form) {
    var PLANS = ["free", "starter", "growth", "enterprise", "self-host", "not-sure"];
    try {
      var plan = new URLSearchParams(location.search).get("plan");
      if (plan && PLANS.indexOf(plan.toLowerCase()) !== -1) form.plan.value = plan.toLowerCase();
    } catch (e) { /* old browser: leave the default */ }

    var status = $("#form-status");
    var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
    var rules = {
      name: function (v) { return v.length >= 2 ? "" : "Please tell us your name."; },
      email: function (v) { return EMAIL.test(v) ? "" : "Please enter a valid work email."; },
      company: function (v) { return v.length >= 2 ? "" : "Please enter your company name."; },
      website: function (v) {
        if (!v) return "";
        return /^(https?:\/\/)?[^\s.]+\.[^\s]{2,}$/i.test(v) ? "" : "That doesn't look like a website address.";
      },
      catalog_size: function (v) { return v ? "" : "Please pick a catalog size."; },
      plan: function (v) { return v ? "" : "Please pick a plan."; },
      message: function (v) { return v.length <= 2000 ? "" : "Please keep the message under 2,000 characters."; }
    };
    function check(name) {
      var input = form.elements[name];
      var msg = rules[name](input.value.trim());
      var err = document.getElementById(name + "-err");
      input.setAttribute("aria-invalid", msg ? "true" : "false");
      if (err) err.textContent = msg;
      return !msg;
    }
    Object.keys(rules).forEach(function (name) {
      form.elements[name].addEventListener("blur", function () {
        if (form.elements[name].value) check(name);
      });
    });

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      status.textContent = ""; status.className = "form-status";
      var firstBad = null;
      Object.keys(rules).forEach(function (name) {
        if (!check(name) && !firstBad) firstBad = form.elements[name];
      });
      if (firstBad) { firstBad.focus(); return; }

      var body = {};
      ["name", "email", "company", "website", "catalog_size", "plan", "message", "company_url_hp"].forEach(function (k) {
        body[k] = (form.elements[k].value || "").trim();
      });
      var btn = $("button[type=submit]", form);
      btn.disabled = true; btn.textContent = "Sending…";

      fetch("/api/request-access", {
        method: "POST",
        headers: { "content-type": "application/json", accept: "application/json" },
        body: JSON.stringify(body)
      }).then(function (res) {
        if (res.ok) {
          form.hidden = true;
          var thanks = $("#form-thanks");
          thanks.hidden = false;
          var who = $("#thanks-email");
          if (who) who.textContent = body.email;
          thanks.focus();
          return;
        }
        status.className = "form-status error";
        status.textContent = res.status === 429
          ? "Too many requests from your network just now. Please try again in a few minutes."
          : "Something went wrong on our side and your request wasn't sent. Please try again in a moment.";
        status.focus();
      }).catch(function () {
        status.className = "form-status error";
        status.textContent = "We couldn't reach the server. Check your connection and try again.";
        status.focus();
      }).then(function () {
        btn.disabled = false; btn.textContent = "Request access";
      });
    });
  }

  /* ---------- docs menu: collapsed on small screens ---------- */
  var docsMenu = $(".docs-nav details");
  if (docsMenu && window.matchMedia && window.matchMedia("(max-width: 860px)").matches) docsMenu.open = false;

  /* ---------- footer year ---------- */
  $$("[data-year]").forEach(function (el) { el.textContent = String(new Date().getFullYear()); });
})();
