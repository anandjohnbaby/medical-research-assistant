const $ = (s) => document.querySelector(s);
const messages = $("#messages"),
  form = $("#form"),
  input = $("#q"),
  sendBtn = $("#send");

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : null);

function showTab(name) {
  document
    .querySelectorAll(".tab")
    .forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["evidence", "claims", "trace"].forEach((n) =>
    $("#tab-" + n).classList.toggle("hidden", n !== name),
  );
}
document
  .querySelectorAll(".tab")
  .forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

function appendInline(parent, text) {
  const re = /\[(\d+)\]/g;
  let last = 0,
    m;
  while ((m = re.exec(text))) {
    if (m.index > last) parent.append(text.slice(last, m.index));
    const n = m[1];
    const a = h("a", "cite", "[" + n + "]");
    a.href = "#ev-" + n;
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      showTab("evidence");
      const card = document.getElementById("ev-" + n);
      if (card) {
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.classList.add("flash");
        setTimeout(() => card.classList.remove("flash"), 1500);
      }
    });
    parent.append(a);
    last = m.index + m[0].length;
  }
  if (last < text.length) parent.append(text.slice(last));
}

function renderAnswer(container, text) {
  let ul = null;
  text.split("\n").forEach((raw) => {
    const line = raw.trim();
    if (!line) {
      ul = null;
      return;
    }
    if (/^[-\u2022*]\s+/.test(line)) {
      if (!ul) {
        ul = h("ul");
        container.append(ul);
      }
      const li = h("li");
      appendInline(li, line.replace(/^[-\u2022*]\s+/, ""));
      ul.append(li);
    } else {
      ul = null;
      const p = h("p");
      const m = line.match(
        /^(Summary|Key findings|Limitations|Verified findings|Note):\s*(.*)$/i,
      );
      if (m) {
        p.append(h("strong", "", m[1] + ": "));
        appendInline(p, m[2]);
      } else appendInline(p, line);
      container.append(p);
    }
  });
}

function renderEvidence(citations, considered) {
  const box = $("#tab-evidence");
  box.replaceChildren();
  if (!citations.length) {
    box.append(h("p", "muted", "No sources were cited for this response."));
    (considered || []).forEach((c) => {
      const card = h("div", "card");
      card.append(h("h4", "", c.title || "Untitled"));
      card.append(
        h(
          "div",
          "muted",
          "Considered but not sufficient: " + (c.study_type || ""),
        ),
      );
      box.append(card);
    });
    return;
  }
  citations.forEach((c) => {
    const card = h("div", "card");
    card.id = "ev-" + c.n;
    const title = h("h4");
    const url = safeUrl(c.url);
    if (url) {
      const a = h("a", "", "[" + c.n + "] " + c.title);
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      title.append(a);
    } else title.textContent = "[" + c.n + "] " + c.title;
    card.append(title);
    const meta = [c.study_type, c.year || null, c.journal, c.source]
      .filter(Boolean)
      .join(" · ");
    card.append(
      h(
        "div",
        "muted",
        meta +
          (c.pmid ? " · PMID " + c.pmid : "") +
          (c.doi ? " · DOI " + c.doi : ""),
      ),
    );
    const tier = h(
      "span",
      "badge " +
        (c.tier <= 2 ? "b-high" : c.tier === 3 ? "b-moderate" : "b-low"),
      "Evidence tier " + c.tier,
    );
    card.append(tier);
    if (c.old)
      card.append(
        h(
          "div",
          "notice",
          "This source is more than 10 years old; newer research may exist.",
        ),
      );
    card.append(h("div", "snippet", c.snippet));
    box.append(card);
  });
}

function renderClaims(claims, verification, conflicts) {
  const box = $("#tab-claims");
  box.replaceChildren();
  if (verification.length) {
    const last = verification[verification.length - 1],
      first = verification[0];
    box.append(
      h(
        "p",
        "muted",
        "First pass: " +
          first.supported +
          "/" +
          first.total +
          " statements verified. " +
          (verification.length > 1
            ? "After correction: " + last.supported + "/" + last.total + "."
            : "No correction was needed."),
      ),
    );
  }
  (conflicts || []).forEach((c) => {
    box.append(
      h(
        "div",
        "notice",
        "Sources disagree: " +
          c.description +
          (c.sources.length ? " (sources " + c.sources.join(", ") + ")" : ""),
      ),
    );
  });
  if (!claims.length) {
    box.append(h("p", "muted", "No claim checks for this response."));
    return;
  }
  claims.forEach((c) => {
    const card = h("div", "card");
    const top = h("div");
    top.append(h("span", "badge b-" + c.verdict.toLowerCase(), c.verdict));
    if (c.removed)
      top.append(h("span", "muted", "  removed from final answer"));
    card.append(top);
    card.append(h("div", c.removed ? "removed" : "", c.text));
    if (c.cited.length)
      card.append(
        h(
          "div",
          "muted",
          "Cites: " + c.cited.map((n) => "[" + n + "]").join(" "),
        ),
      );
    if (c.reason) card.append(h("div", "muted", c.reason));
    if (c.quote) card.append(h("div", "quote", "\u201C" + c.quote + "\u201D"));
    box.append(card);
  });
}

function renderTrace(trace, latency) {
  const box = $("#tab-trace");
  box.replaceChildren();
  const ol = h("ol", "trace");
  trace.forEach((t) => ol.append(h("li", "", t)));
  box.append(ol);
  if (latency)
    box.append(
      h("p", "muted", "Completed in " + (latency / 1000).toFixed(1) + " s"),
    );
}

function addUser(text) {
  const m = h("div", "msg user");
  m.append(h("p", "", text));
  messages.append(m);
  messages.scrollTop = messages.scrollHeight;
}

function addAssistant(data) {
  const m = h(
    "div",
    "msg assistant" + (data.safety.emergency ? " emergency" : ""),
  );
  renderAnswer(m, data.answer);
  if (data.safety.personal_notice)
    m.append(h("div", "notice", data.safety.personal_notice));

  if (data.outcome === "answered" || data.outcome === "insufficient") {
    const meta = h("div", "meta");
    const label = data.confidence.label;
    meta.append(
      h("span", "badge b-" + label.toLowerCase(), "Confidence: " + label),
    );
    if (data.sources_used.length)
      meta.append(h("span", "", "Sources: " + data.sources_used.join(", ")));
    const fb = h("span", "fb");
    ["up", "down"].forEach((r) => {
      const b = h("button", "", r === "up" ? "\uD83D\uDC4D" : "\uD83D\uDC4E");
      b.title = r === "up" ? "Helpful" : "Not helpful";
      b.addEventListener("click", async () => {
        fb.textContent = "Thanks for the feedback";
        fetch("/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ request_id: data.request_id, rating: r }),
        }).catch(() => {});
      });
      fb.append(b);
    });
    meta.append(fb);
    m.append(meta);
    if (data.confidence.reasons && data.confidence.reasons.length)
      m.append(h("div", "muted", data.confidence.reasons.join(" ")));
  }
  if (data.outcome !== "direct") m.append(h("div", "disc", data.disclaimer));
  messages.append(m);
  messages.scrollTop = messages.scrollHeight;
}

async function ask(question) {
  addUser(question);
  const wait = h("div", "msg assistant");
  wait.append(
    h(
      "p",
      "muted",
      "Searching literature, grading evidence and fact-checking the answer... (this can take 15\u201340 seconds)",
    ),
  );
  messages.append(wait);
  messages.scrollTop = messages.scrollHeight;
  sendBtn.disabled = true;
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await r.json();
    wait.remove();
    if (!r.ok) {
      const err = h("div", "msg assistant");
      err.append(h("p", "", "Error: " + (data.detail || "request failed")));
      messages.append(err);
      return;
    }
    addAssistant(data);
    renderEvidence(data.citations, data.considered);
    renderClaims(data.claims, data.verification, data.conflicts);
    renderTrace(data.trace, data.latency_ms);
    showTab(data.citations.length ? "evidence" : "trace");
  } catch (e) {
    wait.remove();
    const err = h("div", "msg assistant");
    err.append(h("p", "", "Network error. Is the server running?"));
    messages.append(err);
  } finally {
    sendBtn.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (q.length < 3) return;
  input.value = "";
  ask(q);
});
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});
document
  .querySelectorAll(".chip")
  .forEach((c) => c.addEventListener("click", () => ask(c.textContent)));

// ---- Admin dialog
const dlg = $("#adminDlg"),
  status = $("#adminStatus");
$("#adminBtn").addEventListener("click", () => dlg.showModal());

async function adminCall(url, opts) {
  status.textContent = "Working...";
  opts.headers = {
    ...(opts.headers || {}),
    "X-Admin-Key": $("#adminKey").value,
  };
  try {
    const r = await fetch(url, opts);
    const d = await r.json();
    status.textContent = r.ok
      ? "Done: " + d.chunks_indexed + " chunks indexed."
      : "Error: " + (d.detail || r.status);
  } catch (e) {
    status.textContent = "Network error.";
  }
}
$("#uploadBtn").addEventListener("click", () => {
  const f = $("#adminFile").files[0];
  if (!f) {
    status.textContent = "Choose a file first.";
    return;
  }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("source_name", $("#srcName").value || "Uploaded document");
  adminCall("/api/ingest", { method: "POST", body: fd });
});
$("#pmBtn").addEventListener("click", () => {
  adminCall("/api/ingest/pubmed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: $("#pmQuery").value,
      max_results: Number($("#pmMax").value) || 20,
    }),
  });
});
