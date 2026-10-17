/* findaro site — small progressive enhancements. Every page works without this file. */
(function () {
  "use strict";
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

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
  var CUR_KEY = "findaro-currency";
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
