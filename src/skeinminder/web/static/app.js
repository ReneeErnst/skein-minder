// app.js — phase controller, SSE consumer, card renderer for SkeinMinder web UI.

const _STATUS_TEXT = {
  supervisor:            "Interpreting your goal…",
  project_first_filter:  "Filtering your stash…",
  stash_first_filter:    "Filtering your stash…",
  assess_filter_quality: "Checking filter quality…",
  low_confidence_output: "Few matches found — reviewing options…",
  pattern_search:        "Searching Ravelry patterns…",
  recommend:             "Writing recommendations…",
  format_output:         "Finishing up…",
};

let _currentStreamId = null;
let _currentEventSource = null;

function _setPhase(phase) {
  document.body.className = "phase-" + phase;
}

function _submitGoal() {
  const goal = document.getElementById("goal-input").value.trim();
  if (!goal) return;

  _setPhase("running");
  initGraph();
  document.getElementById("status-text").textContent = "Starting…";

  fetch("/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal }),
  })
    .then((r) => r.json())
    .then((data) => {
      _currentStreamId = data.stream_id;
      _openStream(_currentStreamId);
    })
    .catch((err) => _showError("Failed to start: " + err.message));
}

function _openStream(streamId) {
  if (_currentEventSource) _currentEventSource.close();
  _currentEventSource = new EventSource("/stream/" + streamId);
  _currentEventSource.onmessage = _handleEvent;
  _currentEventSource.onerror = () => _showError("Connection lost.");
}

function _handleEvent(e) {
  const data = JSON.parse(e.data);

  if (data.type === "node_start") {
    setNodeState(data.node, "active");
    const text = _STATUS_TEXT[data.node];
    if (text) document.getElementById("status-text").textContent = text;
  } else if (data.type === "node_complete") {
    setNodeState(data.node, "complete");
  } else if (data.type === "result") {
    if (_currentEventSource) _currentEventSource.close();
    _renderCards(data.recommendations);
    _setPhase("results");
  } else if (data.type === "error") {
    _showError(data.message);
  } else if (data.type === "node_awaiting_approval") {
    _showApprovalModal(data.message, _currentStreamId);
  }
}

function _renderCards(recommendations) {
  const container = document.getElementById("cards-container");
  container.innerHTML = "";

  recommendations.forEach((rec, i) => {
    const card = document.createElement("div");
    card.className = "card result-card";
    card.style.animationDelay = `${i * 150}ms`;

    const photoHtml = rec.photo_url
      ? `<img class="pattern-photo" src="${rec.photo_url}" alt="${rec.pattern_name || "Pattern photo"}" loading="lazy">`
      : "";

    const titleHtml =
      rec.pattern_name && rec.pattern_url
        ? `<h3><a href="${rec.pattern_url}" target="_blank" rel="noopener">${rec.pattern_name}</a></h3>`
        : `<h3>${rec.title || "Recommendation"}</h3>`;

    const risksHtml =
      rec.risks && rec.risks.length > 0
        ? "<ul class='risks'>" + rec.risks.map((r) => `<li>${r}</li>`).join("") + "</ul>"
        : "";

    card.innerHTML = `${photoHtml}${titleHtml}<p class="rationale">${rec.rationale}</p>${risksHtml}`;
    container.appendChild(card);
  });
}

function _showError(message) {
  document.getElementById("status-text").textContent = "Error: " + message;
  document.body.classList.add("phase-error");
}

function _showApprovalModal(message, streamId) {
  const modal = document.getElementById("approval-modal");
  document.getElementById("approval-message").textContent = message;
  modal.classList.remove("hidden");

  document.getElementById("approve-btn").onclick = () => {
    modal.classList.add("hidden");
    fetch("/approve/" + streamId, { method: "POST" });
  };
  document.getElementById("cancel-btn").onclick = () => {
    modal.classList.add("hidden");
    fetch("/cancel/" + streamId, { method: "POST" });
    _setPhase("input");
  };
}

function _loadLastRun() {
  fetch("/replay")
    .then((r) => {
      if (!r.ok) throw new Error("No previous run saved");
      return r.json();
    })
    .then((data) => {
      _renderCards(data.recommendations);
      _setPhase("results");
    })
    .catch((err) => alert("Could not load last run: " + err.message));
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("submit-btn").addEventListener("click", _submitGoal);
  document.getElementById("goal-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      _submitGoal();
    }
  });
  document.getElementById("run-again-btn").addEventListener("click", () => _setPhase("input"));
  document.getElementById("load-last-run").addEventListener("click", (e) => {
    e.preventDefault();
    _loadLastRun();
  });
});
