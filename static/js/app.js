/* ============================================================
   Personal Finance Advisor Bot - frontend logic
   Vanilla JavaScript + Fetch API. No frameworks.
   ============================================================ */
"use strict";

/* ---------------- helpers ---------------- */

function $(id) { return document.getElementById(id); }

/** Escape untrusted/AI-generated text before inserting into HTML. */
function esc(value) {
  return String(value === null || value === undefined ? "" : value).replace(
    /[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]
  );
}

/** Format a number with thousands separators, no currency symbol. */
function fmt(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatMonth(month) {
  if (!month) return "";
  const [year, mon] = month.split("-").map(Number);
  if (!year || !mon) return month;
  return new Date(year, mon - 1, 1).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

async function getJSON(url) {
  let response;
  try {
    response = await fetch(url);
  } catch (networkError) {
    throw new Error("Could not reach the server. Is the Flask app running?");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || "Something went wrong. Please try again.");
    error.status = response.status;
    throw error;
  }
  return data;
}

async function postJSON(url, payload) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (networkError) {
    throw new Error("Could not reach the server. Is the Flask app running?");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || "Something went wrong. Please try again.");
    error.status = response.status;
    throw error;
  }
  return data;
}

/* ---------------- form handling ---------------- */

function getGoalName() {
  const select = $("goal-select");
  if (select.value === "custom") return $("goal-custom").value.trim();
  return select.value;
}

function collectPayload() {
  const expenses = {};
  document.querySelectorAll("#finance-form [data-category]").forEach((input) => {
    const raw = input.value.trim();
    if (raw === "") return;
    const amount = Number(raw);
    if (Number.isFinite(amount) && amount >= 0) {
      expenses[input.dataset.category] = amount;
    }
  });

  const target = $("goal-target").value.trim();
  const duration = $("goal-duration").value.trim();

  return {
    income: Number($("income").value),
    expenses: expenses,
    goal_name: getGoalName(),
    goal_target_amount: target === "" ? null : Number(target),
    goal_duration_months: duration === "" ? null : Number(duration),
  };
}

function clientSideCheck(payload) {
  if (!Number.isFinite(payload.income) || payload.income <= 0) {
    return "Please enter a monthly income greater than zero.";
  }
  if (!payload.goal_name) {
    return "Please choose or name your financial goal.";
  }
  return null; // server-side validation remains the real authority
}

function showError(message, retryable = false) {
  $("form-error-text").textContent = message;
  $("retry-btn").classList.toggle("hidden", !retryable);
  $("form-error").classList.remove("hidden");
}

function hideError() {
  $("form-error").classList.add("hidden");
  $("retry-btn").classList.add("hidden");
}

function setLoading(isLoading) {
  $("analyse-btn").disabled = isLoading;
  $("loading").classList.toggle("hidden", !isLoading);
}

/* ---------------- rendering ---------------- */

function rateClass(rate) {
  if (rate < 0) return "negative";
  if (rate < 10) return "negative";
  if (rate < 20) return "warn";
  return "good";
}

function renderSnapshot(snapshot) {
  const cards = [
    { label: "Monthly income", value: fmt(snapshot.income), cls: "" },
    { label: "Total expenses", value: fmt(snapshot.total_expenses), cls: "" },
    {
      label: "Remaining income",
      value: fmt(snapshot.remaining_income),
      cls: snapshot.remaining_income < 0 ? "negative" : "good",
    },
    {
      label: "Savings rate",
      value: `${snapshot.savings_rate}%`,
      cls: rateClass(snapshot.savings_rate),
    },
  ];

  $("snapshot-cards").innerHTML = cards
    .map(
      (card) => `
      <div class="stat-card">
        <div class="stat-label">${esc(card.label)}</div>
        <div class="stat-value ${card.cls}">${esc(card.value)}</div>
      </div>`
    )
    .join("");

  const details = [];
  const largest = snapshot.largest_expense_category;
  if (largest) {
    details.push(
      `Largest expense: ${esc(largest.label)} &mdash; ${fmt(largest.amount)} ` +
        `(${largest.percent_of_spending}% of spending)`
    );
  }
  details.push(
    `Discretionary spending: ${fmt(snapshot.discretionary_expenses)} ` +
      `(${snapshot.discretionary_percent_of_income}% of income)`
  );
  const goal = snapshot.goal || {};
  if (goal.monthly_requirement !== null && goal.monthly_requirement !== undefined) {
    details.push(`Goal requirement: ${fmt(goal.monthly_requirement)} per month`);
    details.push(
      goal.on_track
        ? "On current surplus, the goal looks achievable"
        : "Current surplus is not enough for the goal target"
    );
  }
  $("snapshot-details").innerHTML = details.map((d) => `<li>${d}</li>`).join("");
}

function renderBudgetPlan(plan) {
  $("budget-summary").textContent = plan.summary || "";

  const rows = (plan.recommended_allocations || []).map((item) => {
    const delta = Number(item.recommended_amount) - Number(item.current_amount);
    const change =
      Math.abs(delta) < 0.01
        ? "keep"
        : delta < 0
          ? `save ${fmt(-delta)}`
          : `+${fmt(delta)}`;
    return `
      <tr>
        <td><strong>${esc(item.category)}</strong><div class="chip-row"><span class="chip">${esc(change)}</span></div></td>
        <td class="num">${fmt(item.current_amount)}</td>
        <td class="num">${fmt(item.recommended_amount)}</td>
        <td class="reason">${esc(item.reason)}</td>
      </tr>`;
  });

  $("budget-tbody").innerHTML = rows.length
    ? rows.join("")
    : `<tr><td colspan="4" class="reason">No budget allocations were returned.</td></tr>`;
}

function renderSpendingAnalysis(analysis) {
  $("spending-summary").textContent = analysis.summary || "";

  const observations = analysis.observations || [];
  $("spending-observations").innerHTML = observations.length
    ? observations.map((o) => `<li>${esc(o)}</li>`).join("")
    : "<li>No observations were returned.</li>";

  const priorities = analysis.high_priority_categories || [];
  $("spending-priorities").innerHTML = priorities
    .map((c) => `<span class="chip">${esc(c)}</span>`)
    .join("");
}

function renderSuggestions(suggestions) {
  const cards = (suggestions || []).map((s) => {
    const priority = String(s.priority || "medium").toLowerCase();
    return `
      <article class="suggestion-card">
        <div class="suggestion-top">
          <span class="priority-badge priority-${esc(priority)}">${esc(priority)}</span>
          <span class="impact">&asymp; ${fmt(s.estimated_monthly_impact)} / month</span>
        </div>
        <p>${esc(s.suggestion)}</p>
      </article>`;
  });
  $("suggestions-grid").innerHTML = cards.length
    ? cards.join("")
    : '<p class="section-summary">No saving suggestions were returned.</p>';
}

function renderGoalStrategy(strategy, snapshot) {
  const goal = (snapshot && snapshot.goal) || {};
  const stats = [
    { label: "Goal", value: strategy.goal_name || goal.name || "-" },
    {
      label: "Target amount",
      value: Number(strategy.target_amount) > 0 ? fmt(strategy.target_amount) : "Not set",
    },
    {
      label: "Duration",
      value: goal.duration_months ? `${goal.duration_months} months` : "Not set",
    },
    {
      label: "Monthly target",
      value: Number(strategy.monthly_target) > 0 ? fmt(strategy.monthly_target) : "Flexible",
    },
  ];
  $("goal-stats").innerHTML = stats
    .map(
      (s) => `
      <div class="goal-stat">
        <dt>${esc(s.label)}</dt>
        <dd>${esc(s.value)}</dd>
      </div>`
    )
    .join("");
  $("goal-strategy-text").textContent = strategy.strategy || "";
}

function renderInsightsAndWarnings(advice) {
  const insights = advice.key_insights || [];
  $("insights-list").innerHTML = insights.length
    ? insights.map((i) => `<li>${esc(i)}</li>`).join("")
    : "<li>No key insights were returned.</li>";

  const warnings = advice.warnings || [];
  $("warnings-section").classList.toggle("hidden", warnings.length === 0);
  $("warnings-list").innerHTML = warnings.map((w) => `<li>${esc(w)}</li>`).join("");
}

function renderResults(data, noteText) {
  renderSnapshot(data.snapshot);
  renderBudgetPlan(data.advice.budget_plan || {});
  renderSpendingAnalysis(data.advice.spending_analysis || {});
  renderSuggestions(data.advice.saving_suggestions || []);
  renderGoalStrategy(data.advice.goal_strategy || {}, data.snapshot);
  $("monthly-summary").textContent = data.advice.monthly_summary || "";
  renderInsightsAndWarnings(data.advice);

  const note = $("viewing-note");
  note.textContent =
    noteText ||
    `Analysis complete \u2014 saved to history as record #${data.record_id} (${formatMonth(data.month)}).`;
  note.classList.remove("hidden");

  const results = $("results-section");
  results.classList.remove("hidden");
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------------- history ---------------- */

async function loadHistory() {
  const list = $("history-list");
  const empty = $("history-empty");
  try {
    const data = await getJSON("/history");
    const records = data.records || [];
    empty.classList.toggle("hidden", records.length > 0);
    list.innerHTML = records
      .map(
        (r) => `
        <div class="history-item">
          <div class="history-info">
            <strong>${esc(r.goal_name)}</strong>
            <span>${esc(formatMonth(r.month))} &middot; income ${fmt(r.income)} &middot;
              expenses ${fmt(r.total_expenses)} &middot; left ${fmt(r.remaining_income)}
              (${r.savings_rate}%)</span>
          </div>
          <button type="button" class="btn-secondary" data-id="${r.id}">View</button>
        </div>`
      )
      .join("");

    list.querySelectorAll("button[data-id]").forEach((button) => {
      button.addEventListener("click", () => viewRecord(button.dataset.id));
    });
  } catch (error) {
    empty.textContent = "Could not load history. Please refresh the page.";
    empty.classList.remove("hidden");
  }
}

async function viewRecord(id) {
  try {
    const data = await getJSON(`/history/${id}`);
    renderResults(
      data,
      `Viewing saved analysis from ${formatMonth(data.month)} \u2014 record #${data.record_id}.`
    );
  } catch (error) {
    showError(error.message);
  }
}

/* ---------------- wiring ---------------- */

$("goal-select").addEventListener("change", () => {
  const isCustom = $("goal-select").value === "custom";
  $("custom-goal-wrap").classList.toggle("hidden", !isCustom);
  if (isCustom) $("goal-custom").focus();
});

$("finance-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if ($("analyse-btn").disabled) return; // already analysing
  hideError();

  const payload = collectPayload();
  const problem = clientSideCheck(payload);
  if (problem) {
    showError(problem);
    return;
  }

  setLoading(true);
  try {
    const data = await postJSON("/analyse", payload);
    renderResults(data, null);
    await loadHistory();
  } catch (error) {
    // 503 = the AI was briefly unavailable - a retry is likely to succeed.
    showError(error.message, error.status === 503);
  } finally {
    setLoading(false);
  }
});

// "Try again" re-runs the normal submit flow with the current form values.
$("retry-btn").addEventListener("click", () => {
  $("finance-form").requestSubmit();
});

$("refresh-history").addEventListener("click", loadHistory);

// Load any previously saved analyses when the page opens.
loadHistory();
