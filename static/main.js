// static/main.js

const BASE_WEIGHTS = {
  hazardous_substances: 0.4,
  circularity: 0.4,
  certification: 0.2,
};

const state = {
  currentStep: 1,
  categories: [],
  metricsMeta: [],
  selectedCategory: null,
  requiredMetrics: [],
  emphasisMetric: null,
  weights: {},
  results: [],
};
let modalLastFocus = null;

// ---------- Utilities ----------
function qs(selector) {
  return document.querySelector(selector);
}

function qsa(selector) {
  return Array.from(document.querySelectorAll(selector));
}

const gradeClassMap = {
  Excellent: "grade-excellent",
  Pass: "grade-pass",
  Fail: "grade-fail",
  "Missing data": "grade-missing",
};

let modalElement = null;
let modalBody = null;
let modalCloseBtn = null;

function getGradeClass(label) {
  return gradeClassMap[label] || "grade-pass";
}

function safeText(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return value;
}

function formatScore(score, digits = 0) {
  if (typeof score !== "number" || Number.isNaN(score)) return "—";
  return score.toFixed(digits);
}

function setStep(step) {
  state.currentStep = step;
  qsa(".step-panel").forEach((panel) => {
    panel.classList.toggle("hidden", panel.id !== `step-${step}`);
  });

  qsa(".step-indicator").forEach((el) => {
    const s = Number(el.dataset.step);
    el.classList.toggle("active", s === step);
    el.classList.toggle("completed", s < step);
  });
}

function formatMetricLabel(metricId) {
  const meta = state.metricsMeta.find((m) => m.id === metricId);
  return meta ? meta.label : metricId;
}

// Compute default weights with an optional emphasis metric.
function computeWeights(emphasisMetric) {
  const weights = { ...BASE_WEIGHTS };
  if (emphasisMetric && weights[emphasisMetric] !== undefined) {
    weights[emphasisMetric] += 0.05;
    const total = Object.values(weights).reduce((sum, value) => sum + value, 0);
    Object.keys(weights).forEach((key) => {
      weights[key] = Number((weights[key] / total).toFixed(3));
    });
  }
  return weights;
}

// ---------- Step 1: load categories & render ----------
async function loadFilters() {
  try {
    const res = await fetch("/api/filters");
    const data = await res.json();
    if (!data.success) {
      console.error("Failed to load filters", data);
      return;
    }
    state.categories = data.data.categories || [];
    state.metricsMeta = data.data.metrics || [];
    renderCategoryCards();
    renderMetricChecklist();
  } catch (e) {
    console.error("Error loading filters", e);
  }
}

function renderCategoryCards() {
  const container = qs("#category-list");
  container.innerHTML = "";

  if (!state.categories.length) {
    container.innerHTML =
      '<p class="empty-tip">No categories detected in the dataset yet. Please verify the JSON configuration.</p>';
    return;
  }

  state.categories.forEach((cat) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "category-card";
    card.textContent = cat;

    card.addEventListener("click", () => {
      state.selectedCategory = cat;
      // highlight selection
      qsa(".category-card").forEach((c) =>
        c.classList.toggle("selected", c === card),
      );
      qs("#to-step-2").disabled = false;
    });

    container.appendChild(card);
  });
}

// ---------- Step 2: metric selection ----------
function renderMetricChecklist() {
  const container = qs("#metric-checklist");
  container.innerHTML = "";

  if (!state.metricsMeta.length) {
    container.innerHTML =
      '<p class="empty-tip">No environmental metrics available. Please double-check /api/filters.</p>';
    return;
  }

  state.metricsMeta.forEach((m) => {
    const item = document.createElement("label");
    item.className = "metric-item";
    item.innerHTML = `
      <input type="checkbox" value="${m.id}" />
      <div class="metric-text">
        <div class="metric-label">${m.label}</div>
        <div class="metric-desc">${m.description || ""}</div>
      </div>
    `;
    const checkbox = item.querySelector("input");
    checkbox.addEventListener("change", () => {
      state.requiredMetrics = getSelectedMetrics();
    });
    container.appendChild(item);
  });
}

function getSelectedMetrics() {
  return qsa("#metric-checklist input:checked").map((el) => el.value);
}

function clearMetricSelections() {
  qsa("#metric-checklist input:checked").forEach((el) => {
    el.checked = false;
  });
  state.requiredMetrics = [];
  state.emphasisMetric = null;
}

// ---------- Step 3: emphasis selection ----------
function renderEmphasisOptions() {
  const container = qs("#metric-emphasis-list");
  container.innerHTML = "";

  const noneOption = document.createElement("label");
  noneOption.className = "emphasis-option";
  noneOption.innerHTML = `
    <input type="radio" name="metric-emphasis" value="" ${
      !state.emphasisMetric ? "checked" : ""
    } />
    <span>No additional emphasis</span>
  `;
  noneOption.querySelector("input").addEventListener("change", () => {
    state.emphasisMetric = null;
  });
  container.appendChild(noneOption);

  state.requiredMetrics.forEach((id) => {
    const option = document.createElement("label");
    option.className = "emphasis-option";
    option.innerHTML = `
      <input type="radio" name="metric-emphasis" value="${id}" ${
        state.emphasisMetric === id ? "checked" : ""
      } />
      <span>${formatMetricLabel(id)}</span>
    `;
    option.querySelector("input").addEventListener("change", (event) => {
      state.emphasisMetric = event.target.value;
    });
    container.appendChild(option);
  });
}

function handleStep2Next() {
  state.requiredMetrics = getSelectedMetrics();
  state.emphasisMetric = null;
  renderEmphasisOptions();
  setStep(3);
}

function skipOrderingAndCalculate() {
  const emphasis =
    state.requiredMetrics.length >= 2 ? state.emphasisMetric : null;
  state.weights = computeWeights(emphasis);
  fetchRecommendations();
}

// ---------- Step 4: results ----------
function updateSummaryPanel() {
  // category summary
  qs("#summary-category").textContent = state.selectedCategory || "Not selected";

  // required metrics
  const requiredUl = qs("#summary-required-metrics");
  requiredUl.innerHTML = "";
  state.requiredMetrics.forEach((id) => {
    const li = document.createElement("li");
    li.textContent = formatMetricLabel(id);
    requiredUl.appendChild(li);
  });

  // weight summary
  const weightsUl = qs("#summary-weights");
  weightsUl.innerHTML = "";
  Object.entries(state.weights).forEach(([id, w]) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="weight-metric">${formatMetricLabel(
      id,
    )}</span><span class="weight-value">${(w * 100).toFixed(0)}%</span>`;
    weightsUl.appendChild(li);
  });
}

function renderResults() {
  const container = qs("#results-container");
  container.innerHTML = "";

  qs("#result-count").textContent = `Found ${state.results.length} materials (sorted by total score, ≥80 = Excellent).`;

  if (!state.results.length) {
    container.innerHTML =
      '<p class="empty-tip">No materials matched your filters. Try fewer “must be excellent” constraints.</p>';
    return;
  }

  state.results.forEach((item) => {
    const card = document.createElement("article");
    card.className = "material-card";
    card.tabIndex = 0;

    const title =
      item.product_name || item.product_code || `Material #${item.id || ""}`;
    const manufacturer = item.manufacturer_name || "";
    const cats = (item.categories || []).join(" / ");
    const gradeLabel = item.total_label || "—";
    const gradeClass = getGradeClass(gradeLabel);
    const imageBlock = item.image_url
      ? `<img src="${item.image_url}" alt="${title}" />`
      : '<span class="image-placeholder">none</span>';

    card.innerHTML = `
      <div class="material-card-image">${imageBlock}</div>
      <div class="material-card-body">
        <header class="material-card-header">
          <div>
            <h4 class="material-title">${title}</h4>
            <div class="material-manufacturer">${
              manufacturer ? manufacturer : "&nbsp;"
            }</div>
          </div>
          <span class="badge grade-badge ${gradeClass}">${gradeLabel}</span>
        </header>
        <div class="material-meta-line">${cats || "Category not provided"}</div>

        <div class="score-row">
          <div class="score-main">
            <span class="score-label">Total sustainability score</span>
            <span class="score-value">${formatScore(item.total_score, 1)}</span>
          </div>
          <div class="score-sub">
            <span>Hazardous substances: ${formatScore(item.hazardous_substances_score)}</span>
            <span>CLSI: ${formatScore(
              item.circularity_lifespan_score,
            )}</span>
            <span>Certifications: ${formatScore(item.certification_score)}</span>
          </div>
        </div>

        <footer class="material-card-footer">
          <button class="btn-link card-detail-btn">View details</button>
        </footer>
      </div>
    `;

    const openDetail = () => {
      if (item.id != null) {
        openMaterialModal(item.id);
      }
    };

    card.addEventListener("click", openDetail);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDetail();
      }
    });
    card.querySelector(".card-detail-btn").addEventListener("click", (event) => {
      event.stopPropagation();
      openDetail();
    });

    container.appendChild(card);
  });
}

// ---------- Material detail modal ----------
async function openMaterialModal(materialId) {
  if (!materialId || !modalElement || !modalBody) return;
  modalLastFocus = document.activeElement;
  modalElement.classList.remove("hidden");
  document.body.classList.add("modal-open");
  modalBody.innerHTML = '<div class="modal-loading">Loading material details...</div>';
  modalCloseBtn?.focus();

  try {
    const res = await fetch(`/api/material/${materialId}`);
    const data = await res.json();
    if (!data.success) {
      modalBody.innerHTML = `<p class="modal-error">Unable to load material: ${data.error || "Unknown error"}</p>`;
      return;
    }
    modalBody.innerHTML = renderMaterialDetailContent(data.item || {});
  } catch (error) {
    console.error("Failed to load material detail", error);
    modalBody.innerHTML = '<p class="modal-error">Unable to load details, please try again later.</p>';
  }
}

function closeMaterialModal() {
  if (!modalElement) return;
  modalElement.classList.add("hidden");
  document.body.classList.remove("modal-open");
  if (modalLastFocus && typeof modalLastFocus.focus === "function") {
    modalLastFocus.focus();
  }
}

function renderMaterialDetailContent(item) {
  const title = item.product_name || item.product_code || `Material #${item.id || ""}`;
  const manufacturer = safeText(item.manufacturer_name, "—");
  const cats = (item.categories || []).join(" / ") || "Category not provided";
  const description = safeText(item.product_description, "No description available.");
  const gradeLabel = item.total_label || "—";
  const gradeClass = getGradeClass(gradeLabel);
  const imageBlock = item.image_url
    ? `<img src="${item.image_url}" alt="${title}" />`
    : '<span class="image-placeholder large">none</span>';

  const certificationList =
    (item.certifications || [])
      .map((cert) => `<li>${safeText(cert.certification, "Unnamed certification")}</li>`)
      .join("") || "<li>No certification data</li>";

  return `
    <div class="modal-header">
      <div>
        <h3>${title}</h3>
        <p>${manufacturer}</p>
      </div>
      <span class="badge grade-badge ${gradeClass}">${gradeLabel}</span>
    </div>
    <div class="modal-body-grid">
      <div class="modal-image">${imageBlock}</div>
      <div class="modal-info">
        <p><strong>Category:</strong> ${cats}</p>
        <p><strong>Description:</strong> ${description}</p>
      </div>
    </div>
    <div class="modal-score-grid">
      <div>
        <div class="score-label">Total score</div>
        <div class="score-value">${formatScore(item.total_score, 1)}</div>
      </div>
      <div>
        <div class="score-label">Hazardous substances</div>
        <div class="score-value">${formatScore(item.hazardous_substances_score)}</div>
      </div>
      <div>
        <div class="score-label">Circularity & lifetime (CLSI)</div>
        <div class="score-value">${formatScore(item.circularity_lifespan_score)}</div>
      </div>
      <div>
        <div class="score-label">Certifications</div>
        <div class="score-value">${formatScore(item.certification_score)}</div>
      </div>
    </div>
    <div class="modal-section">
      <h4>Hazardous substances</h4>
      <p>VOC: ${safeText(item.volatile_organic_compounds, "Not provided")}</p>
      <p>Substances of concern: ${safeText(item.substances_of_concern, "Not provided")}</p>
    </div>
    <div class="modal-section">
      <h4>Circularity & lifetime (CLSI)</h4>
      <p>Recycled content: ${safeText(item.recycled_content_percentage, "Not provided")}</p>
      <p>Recyclable fraction: ${safeText(item.recyclable_percentage, "Not provided")}</p>
      <p>Reuse potential: ${safeText(item.reusable, "Not provided")}</p>
      <p>Expected lifetime (years): ${safeText(item.expected_lifespan_years, "Not provided")}</p>
    </div>
    <div class="modal-section">
      <h4>Certifications & LCA</h4>
      <p>Independent LCA: ${safeText(item.independent_lca, "Not provided")}</p>
      <ul class="detail-list">${certificationList}</ul>
    </div>
  `;
}

// ---------- API interactions ----------
async function fetchRecommendations() {
  const payload = {
    category: state.selectedCategory,
    required_metrics: state.requiredMetrics,
    weights: state.weights,
  };

  try {
    const res = await fetch("/api/recommend", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.success) {
      alert("Unable to compute results, please try again later.");
      return;
    }
    state.results = data.items || [];
    updateSummaryPanel();
    renderResults();
    setStep(4);
  } catch (e) {
    console.error("Failed to call recommendation API", e);
    alert("Unable to compute results, please try again later.");
  }
}

// ---------- Event bindings ----------
document.addEventListener("DOMContentLoaded", () => {
  // Initialize filters (categories + metrics)
  loadFilters();

  // Step 1 -> Step 2
  qs("#to-step-2").addEventListener("click", () => {
    if (!state.selectedCategory) return;
    setStep(2);
  });

  // Step 2 -> Step 1
  qs("#back-to-1").addEventListener("click", () => {
    setStep(1);
  });

  // Step 2 -> Step 3
  qs("#to-step-3").addEventListener("click", () => {
    handleStep2Next();
  });

  qs("#skip-step-2").addEventListener("click", () => {
    clearMetricSelections();
    skipOrderingAndCalculate();
  });

  // Step 3 -> Step 2
  qs("#back-to-2").addEventListener("click", () => {
    setStep(2);
  });

  // Step 3 -> Step 4 (trigger calculation)
  qs("#to-step-4").addEventListener("click", () => {
    if (!state.requiredMetrics.length) {
      alert("Unable to compute: please select at least one metric in Step 2.");
      return;
    }
    state.weights = computeWeights(state.emphasisMetric);
    fetchRecommendations();
  });

  qs("#skip-step-3").addEventListener("click", () => {
    state.emphasisMetric = null;
    skipOrderingAndCalculate();
  });

  // Step 4 -> Step 3 (adjust weights)
  qs("#back-to-3").addEventListener("click", () => {
    if (state.requiredMetrics.length >= 2) {
      renderEmphasisOptions();
      setStep(3);
    } else {
      setStep(2);
    }
  });

  // Step 4 -> Step 1 (restart flow)
  qs("#back-to-1-shortcut").addEventListener("click", () => {
    setStep(1);
  });

  modalElement = qs("#material-modal");
  modalBody = qs("#material-modal-body");
  modalCloseBtn = qs("#modal-close-btn");
  const modalBackdrop = modalElement?.querySelector(".modal-backdrop");
  modalCloseBtn?.addEventListener("click", (event) => {
    event.stopPropagation();
    closeMaterialModal();
  });
  modalBackdrop?.addEventListener("click", closeMaterialModal);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modalElement && !modalElement.classList.contains("hidden")) {
      closeMaterialModal();
    }
  });

  // Start on Step 1
  setStep(1);
});
