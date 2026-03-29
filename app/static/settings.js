/* Prunarr — Settings Page (ES2024+) */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const fetchJson = async (url, opts) => {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
};

// --- State ---

let schema = {};
let currentSettings = {};
let dirty = false;

// --- Weight colors ---

const WEIGHT_COLORS = {
    weight_ratings: "#3b82f6",
    weight_engagement: "#22c55e",
    weight_recency: "#f59e0b",
    weight_breadth: "#a855f7",
    weight_continuing: "#ec4899",
};

const WEIGHT_LABELS = {
    weight_ratings: "Ratings",
    weight_engagement: "Engagement",
    weight_recency: "Recency",
    weight_breadth: "Breadth",
    weight_continuing: "Continuing",
};

const TIER_COLORS = {
    strong_delete: "var(--tier-strong-delete)",
    delete: "var(--tier-delete)",
    consider: "var(--tier-consider)",
    keep: "var(--tier-keep)",
    strong_keep: "var(--tier-strong-keep)",
};

// --- Load settings ---

const loadSettings = async () => {
    const data = await fetchJson("/api/settings");
    schema = data.schema;
    currentSettings = data.settings;
    populateForm();
    updateWeightBar();
    updateTierVisual();
    renderGeneralSettings();
};

// --- Populate form fields ---

const populateForm = () => {
    for (const [key, value] of Object.entries(currentSettings)) {
        const el = document.getElementById(key);
        if (!el) continue;

        const meta = schema[key];
        if (!meta) continue;

        if (meta.type === "bool") {
            el.checked = value === true || value === "true";
        } else if (el.type === "range") {
            el.value = value;
            const valSpan = document.getElementById(`${key}_val`);
            if (valSpan) valSpan.textContent = value;
        } else if (meta.type === "password") {
            // Never populate password fields with the masked/hashed value.
            // Leave the field empty; show placeholder if a value is configured.
            el.value = "";
            const hasValue = value && String(value).length > 0;
            el.placeholder = hasValue ? "configured (leave blank to keep)" : meta.placeholder;
        } else {
            el.value = value ?? "";
        }
    }
};

// --- General settings (dynamic) ---

const renderGeneralSettings = () => {
    const container = $("#generalSettings");
    const generalKeys = Object.entries(schema).filter(([, meta]) => meta.group === "general");

    container.innerHTML = generalKeys.map(([key, meta]) => {
        const value = currentSettings[key];

        if (meta.type === "bool") {
            const checked = value === true || value === "true";
            return `<div class="form-group toggle-group">
                <label for="${key}">${escapeHtml(meta.label)}</label>
                <label class="toggle">
                    <input type="checkbox" id="${key}" name="${key}" ${checked ? "checked" : ""}>
                    <span class="toggle-slider"></span>
                </label>
            </div>`;
        }

        if (meta.type === "password") {
            const hasValue = value && String(value).length > 0;
            const placeholder = hasValue ? "configured (leave blank to keep)" : escapeHtml(meta.placeholder);
            return `<div class="form-group">
                <label for="${key}">${escapeHtml(meta.label)}</label>
                <div class="password-wrapper">
                    <input type="password" id="${key}" name="${key}" placeholder="${placeholder}" value="">
                    <button type="button" class="password-toggle" aria-label="Toggle visibility">
                        <svg class="eye-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        <svg class="eye-off-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" style="display:none"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                    </button>
                </div>
            </div>`;
        }

        return `<div class="form-group">
            <label for="${key}">${escapeHtml(meta.label)}</label>
            <input type="text" id="${key}" name="${key}" placeholder="${escapeHtml(meta.placeholder)}" value="${escapeHtml(String(value ?? ""))}">
        </div>`;
    }).join("");

    // Re-attach toggle listeners for dynamically rendered password toggles
    attachPasswordToggles(container);
};

// --- Weight bar visualization ---

const updateWeightBar = () => {
    const bar = $("#weightBar");
    const keys = ["weight_ratings", "weight_engagement", "weight_recency", "weight_breadth", "weight_continuing"];

    let total = 0;
    const segments = keys.map((key) => {
        const val = parseInt(document.getElementById(key)?.value ?? "0", 10) || 0;
        total += val;
        return { key, val };
    });

    bar.innerHTML = segments
        .filter((s) => s.val > 0)
        .map((s) => {
            const pct = total > 0 ? (s.val / total) * 100 : 0;
            return `<div class="weight-segment" style="width:${pct}%;background:${WEIGHT_COLORS[s.key]}" title="${WEIGHT_LABELS[s.key]}: ${s.val}">
                ${pct >= 8 ? `<span>${WEIGHT_LABELS[s.key]} ${s.val}</span>` : ""}
            </div>`;
        })
        .join("");

    // Update sum display
    const sumValue = $("#weightSumValue");
    const sumStatus = $("#weightSumStatus");
    sumValue.textContent = total;

    if (total === 100) {
        sumStatus.textContent = "";
        sumStatus.className = "weight-sum-status";
        sumValue.classList.remove("error");
    } else {
        sumStatus.textContent = total > 100 ? `(${total - 100} over)` : `(${100 - total} under)`;
        sumStatus.className = "weight-sum-status error";
        sumValue.classList.add("error");
    }
};

// --- Tier visual ---

const updateTierVisual = () => {
    const visual = $("#tierVisual");

    const sd = parseInt($("#tier_strong_delete")?.value ?? "20", 10);
    const de = parseInt($("#tier_delete")?.value ?? "40", 10);
    const co = parseInt($("#tier_consider")?.value ?? "60", 10);
    const ke = parseInt($("#tier_keep")?.value ?? "80", 10);

    // Update range value displays
    $("#tier_strong_delete_val").textContent = sd;
    $("#tier_delete_val").textContent = de;
    $("#tier_consider_val").textContent = co;
    $("#tier_keep_val").textContent = ke;

    const tiers = [
        { label: "Strong Delete", range: `0 - ${sd}`, color: TIER_COLORS.strong_delete, width: sd },
        { label: "Delete", range: `${sd + 1} - ${de}`, color: TIER_COLORS.delete, width: de - sd },
        { label: "Consider", range: `${de + 1} - ${co}`, color: TIER_COLORS.consider, width: co - de },
        { label: "Keep", range: `${co + 1} - ${ke}`, color: TIER_COLORS.keep, width: ke - co },
        { label: "Strong Keep", range: `${ke + 1} - 100`, color: TIER_COLORS.strong_keep, width: 100 - ke },
    ];

    visual.innerHTML = `
        <div class="tier-bar">
            ${tiers.map((t) => `<div class="tier-segment" style="width:${t.width}%;background:${t.color}" title="${t.label}: ${t.range}">
                ${t.width >= 10 ? `<span class="tier-seg-label">${t.label}</span>` : ""}
            </div>`).join("")}
        </div>
        <div class="tier-ranges">
            ${tiers.map((t) => `<span class="tier-range-item"><span class="tier-dot" style="background:${t.color}"></span>${t.label}: ${t.range}</span>`).join("")}
        </div>`;
};

// --- Password toggle ---

const attachPasswordToggles = (root = document) => {
    for (const btn of root.querySelectorAll(".password-toggle")) {
        if (btn.dataset.bound) continue;
        btn.dataset.bound = "1";
        btn.addEventListener("click", () => {
            const wrapper = btn.closest(".password-wrapper");
            const input = wrapper?.querySelector("input");
            if (!input) return;
            const show = input.type === "password";
            input.type = show ? "text" : "password";
            const eyeOn = btn.querySelector(".eye-icon");
            const eyeOff = btn.querySelector(".eye-off-icon");
            if (eyeOn) eyeOn.style.display = show ? "none" : "";
            if (eyeOff) eyeOff.style.display = show ? "" : "none";
        });
    }
};

// --- Test connection ---

const testConnection = async (service) => {
    const urlInput = $(`#${service}_url`);
    const keyInput = $(`#${service}_api_key`);
    const btn = $(`.test-btn[data-service="${service}"]`);
    const spinner = btn?.querySelector(".test-spinner");
    const result = btn?.querySelector(".test-result");
    const label = btn?.querySelector(".test-label");

    if (!urlInput?.value || !keyInput?.value) {
        showToast("URL and API key are required", "error");
        return;
    }

    label.hidden = true;
    spinner.hidden = false;
    result.hidden = true;
    btn.disabled = true;

    try {
        const data = await fetchJson("/api/settings/test-connection", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                service,
                url: urlInput.value,
                api_key: keyInput.value,
            }),
        });

        result.hidden = false;
        spinner.hidden = true;

        if (data.success) {
            result.textContent = "\u2713";
            result.className = "test-result success";
        } else {
            result.textContent = "\u2717";
            result.className = "test-result failure";
            result.title = data.message;
            showToast(data.message, "error");
        }
    } catch (err) {
        result.hidden = false;
        spinner.hidden = true;
        result.textContent = "\u2717";
        result.className = "test-result failure";
        result.title = err.message;
        showToast(`Connection test failed: ${err.message}`, "error");
    } finally {
        btn.disabled = false;
        // Reset after 5 seconds
        setTimeout(() => {
            label.hidden = false;
            result.hidden = true;
        }, 5000);
    }
};

// --- Save ---

const saveSettings = async () => {
    const saveBtn = $("#saveBtn");
    const saveLabel = saveBtn.querySelector(".save-label");
    const saveSpinner = saveBtn.querySelector(".save-spinner");

    // Collect all values
    const payload = {};

    for (const [key, meta] of Object.entries(schema)) {
        const el = document.getElementById(key);
        if (!el) continue;

        if (meta.type === "bool") {
            payload[key] = el.checked;
        } else if (meta.type === "number") {
            payload[key] = parseInt(el.value, 10) || 0;
        } else if (meta.type === "password") {
            // Only include password fields when the user typed a new value
            if (el.value) {
                payload[key] = el.value;
            }
        } else {
            payload[key] = el.value;
        }
    }

    // Validate weight sum
    const weightKeys = ["weight_ratings", "weight_engagement", "weight_recency", "weight_breadth", "weight_continuing"];
    const weightSum = weightKeys.reduce((sum, k) => sum + (payload[k] || 0), 0);
    if (weightSum !== 100) {
        showToast(`Scoring weights must sum to 100 (currently ${weightSum})`, "error");
        return;
    }

    saveLabel.hidden = true;
    saveSpinner.hidden = false;
    saveBtn.disabled = true;

    try {
        const data = await fetchJson("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        currentSettings = data.settings;
        dirty = false;
        showToast("Settings saved successfully", "success");
    } catch (err) {
        showToast(`Save failed: ${err.message}`, "error");
    } finally {
        saveLabel.hidden = false;
        saveSpinner.hidden = true;
        saveBtn.disabled = false;
    }
};

// --- Toast ---

const showToast = (message, type = "info") => {
    const toast = $("#toast");
    const msg = $("#toastMessage");

    msg.textContent = message;
    toast.className = `toast ${type}`;
    toast.hidden = false;

    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
        toast.hidden = true;
    }, 4000);
};

// --- Utility ---

const escapeHtml = (str) =>
    str?.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;") ?? "";

// --- Event listeners ---

// Password toggles
attachPasswordToggles();

// Test buttons
for (const btn of $$(".test-btn")) {
    btn.addEventListener("click", () => testConnection(btn.dataset.service));
}

// Weight inputs — live update bar
for (const input of $$("#weightsGrid input[type=number]")) {
    input.addEventListener("input", () => {
        updateWeightBar();
        dirty = true;
    });
}

// Tier sliders — live update visual
for (const input of $$(".tier-input input[type=range]")) {
    input.addEventListener("input", () => {
        updateTierVisual();
        dirty = true;
    });
}

// Track dirty state on all inputs
document.addEventListener("input", () => { dirty = true; });

// Save button
$("#saveBtn").addEventListener("click", saveSettings);

// Spinner animations
const style = document.createElement("style");
style.textContent = `.test-spinner svg, .save-spinner svg { animation: rotate 1s linear infinite; }`;
document.head.appendChild(style);

// --- Init ---
await loadSettings();
