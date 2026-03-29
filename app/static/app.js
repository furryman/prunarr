/* Prunarr — Modern ES2024+ Frontend */

// --- State ---
const state = {
    currentTab: "movies",
    movies: [],
    shows: [],
    selectedIds: new Set(),
    sorting: "size_desc",
    filtering: "all",
    isScanning: false,
    stats: {},
};

// --- DOM refs ---
const $ = (sel) => document.querySelector(sel);
const grid = $("#mediaGrid");
const emptyState = $("#emptyState");
const actionBar = $("#actionBar");
const selectedCountEl = $("#selectedCount");
const selectedSizeEl = $("#selectedSize");
const scanBtn = $("#scanBtn");
const lastScanEl = $("#lastScanTime");
const deleteDialog = $("#deleteDialog");
const dialogMessage = $("#dialogMessage");
const sortSelect = $("#sortSelect");
const filterSelect = $("#filterSelect");

// --- API helpers ---

const fetchJson = async (url, opts) => {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
};

const fetchMovies = async () => {
    state.movies = await fetchJson("/api/movies");
    if (state.currentTab === "movies") render();
};

const fetchShows = async () => {
    state.shows = await fetchJson("/api/shows");
    if (state.currentTab === "shows") render();
};

const fetchStats = async () => {
    state.stats = await fetchJson("/api/stats");
    renderStats(state.stats);
};

const refreshAll = () => Promise.all([fetchMovies(), fetchShows(), fetchStats()]);

// --- Scan ---

const scan = async () => {
    if (state.isScanning) return;
    state.isScanning = true;
    scanBtn.classList.add("scanning");
    showSkeletons();

    try {
        await fetchJson("/api/scan", { method: "POST" });
        await refreshAll();
    } catch (err) {
        console.error("Scan failed:", err);
    } finally {
        state.isScanning = false;
        scanBtn.classList.remove("scanning");
        lastScanEl.textContent = "Last scan: just now";
    }
};

// --- Render ---

const render = () => {
    const source = state.currentTab === "movies" ? state.movies : state.shows;
    const filtered = filterItems(source, state.filtering);
    const items = sortItems(filtered, state.sorting);

    if (items.length === 0 && state.movies.length === 0 && state.shows.length === 0) {
        grid.innerHTML = "";
        emptyState.hidden = false;
        return;
    }

    emptyState.hidden = true;
    renderCards(items);
    updateActionBar();
};

const renderCards = (items) => {
    if (items.length === 0) {
        grid.innerHTML = '<div class="empty-state"><p>No items match the current filter.</p></div>';
        return;
    }

    grid.innerHTML = items.map((item) => {
        const itemId = getItemId(item);
        const isSelected = state.selectedIds.has(itemId);

        const posterHtml = item.poster_url
            ? `<img src="/api/poster?url=${encodeURIComponent(item.poster_url)}" alt="" loading="lazy">`
            : '<div class="no-poster">No Poster</div>';

        const ratingBadges = [
            item.rt_score != null ? `<span class="rating-badge rt">RT ${item.rt_score}%</span>` : "",
            item.metacritic != null ? `<span class="rating-badge mc">MC ${item.metacritic}</span>` : "",
            item.imdb_score != null ? `<span class="rating-badge imdb">IMDb ${item.imdb_score}</span>` : "",
        ].filter(Boolean).join("");

        const tierLabel = item.tier?.replaceAll("_", " ") ?? "";
        const tierBadge = item.tier
            ? `<div class="tier-badge ${item.tier}">${tierLabel} <span class="tier-score">${item.score}</span></div>`
            : "";

        const metaParts = [
            `<span class="card-size">${escapeHtml(item.size_human)}</span>`,
            item.play_count > 0 ? `${item.play_count} plays` : "Never watched",
            escapeHtml(item.last_played_human),
            item.media_type === "show" && item.episodes > 0 ? `${item.episodes} eps` : "",
        ].filter(Boolean);

        return `<div class="media-card${isSelected ? " selected" : ""}" data-id="${itemId}">
            <input type="checkbox" class="card-checkbox" aria-label="Select ${escapeAttr(item.title)}"${isSelected ? " checked" : ""} data-id="${itemId}">
            <div class="card-poster">${posterHtml}</div>
            <div class="card-info">
                <div class="card-title">${escapeHtml(item.title)}${item.year ? `<span class="card-year">(${item.year})</span>` : ""}</div>
                <div class="card-meta">${metaParts.join('<span class="card-meta-sep">&middot;</span>')}</div>
                ${ratingBadges ? `<div class="rating-badges">${ratingBadges}</div>` : ""}
                ${tierBadge}
                ${item.reason ? `<div class="card-reason" title="${escapeAttr(item.reason)}">${escapeHtml(item.reason)}</div>` : ""}
            </div>
        </div>`;
    }).join("");
};

const renderStats = (stats) => {
    $("#statTotalSize").textContent = stats.total_size_human ?? "--";
    $("#statReclaimable").textContent = stats.reclaimable_size_human ?? "--";
    $("#statMovies").textContent = stats.movies_count ?? "--";
    $("#statShows").textContent = stats.shows_count ?? "--";
};

const showSkeletons = () => {
    grid.innerHTML = Array.from({ length: 6 }, () =>
        `<div class="skeleton-card">
            <div class="skeleton-poster"></div>
            <div class="skeleton-info">
                <div class="skeleton-line long"></div>
                <div class="skeleton-line medium"></div>
                <div class="skeleton-line short"></div>
                <div class="skeleton-line medium"></div>
            </div>
        </div>`
    ).join("");
    emptyState.hidden = true;
};

// --- Sorting ---

const SORT_FNS = {
    size_desc:       (a, b) => (b.size_bytes ?? 0) - (a.size_bytes ?? 0),
    score_asc:       (a, b) => (a.score ?? 0) - (b.score ?? 0),
    name_asc:        (a, b) => (a.title ?? "").localeCompare(b.title ?? ""),
    rating_desc:     (a, b) => avgRating(b) - avgRating(a),
    last_played_asc: (a, b) => (a.last_played ?? 0) - (b.last_played ?? 0),
};

const sortItems = (items, sortKey) => structuredClone(items).sort(SORT_FNS[sortKey] ?? SORT_FNS.size_desc);

function avgRating(item) {
    const vals = [
        item.rt_score != null ? item.rt_score / 100 : null,
        item.metacritic != null ? item.metacritic / 100 : null,
        item.imdb_score != null ? item.imdb_score / 10 : null,
    ].filter((v) => v != null);

    return vals.length === 0 ? 0 : vals.reduce((a, b) => a + b, 0) / vals.length;
}

// --- Filtering ---

const filterItems = (items, tier) => tier === "all" ? items : items.filter((item) => item.tier === tier);

// --- Selection ---

const getItemId = (item) =>
    item.media_type === "movie" ? `movie_${item.radarr_id}` : `show_${item.sonarr_id}`;

const getItemById = (itemId) =>
    [...state.movies, ...state.shows].find((item) => getItemId(item) === itemId) ?? null;

const toggleSelection = (itemId) => {
    if (state.selectedIds.has(itemId)) {
        state.selectedIds.delete(itemId);
    } else {
        state.selectedIds.add(itemId);
    }

    const card = grid.querySelector(`.media-card[data-id="${itemId}"]`);
    if (card) {
        const checked = state.selectedIds.has(itemId);
        card.classList.toggle("selected", checked);
        const cb = card.querySelector(".card-checkbox");
        if (cb) cb.checked = checked;
    }

    updateActionBar();
};

const updateActionBar = () => {
    const count = state.selectedIds.size;
    if (count === 0) {
        actionBar.classList.remove("visible");
        return;
    }

    actionBar.classList.add("visible");

    let totalBytes = 0;
    for (const id of state.selectedIds) {
        totalBytes += getItemById(id)?.size_bytes ?? 0;
    }

    selectedCountEl.textContent = `${count} item${count !== 1 ? "s" : ""} selected`;
    selectedSizeEl.textContent = `(${formatSize(totalBytes)})`;
};

// --- Delete ---

const deleteSelected = () => {
    const count = state.selectedIds.size;
    if (count === 0) return;
    dialogMessage.textContent = `Are you sure you want to delete ${count} item${count !== 1 ? "s" : ""}? This will permanently remove files from disk.`;
    deleteDialog.showModal();
};

const confirmDelete = async () => {
    deleteDialog.close();

    const ids = [...state.selectedIds];
    for (const itemId of ids) {
        const [type, ...rest] = itemId.split("_");
        const apiId = rest.join("_");
        const url = type === "movie" ? `/api/movies/${apiId}` : `/api/shows/${apiId}`;

        try {
            const r = await fetch(url, { method: "DELETE" });
            if (!r.ok) throw new Error(`Delete failed: ${r.status}`);
        } catch (err) {
            console.error(`Delete error for ${itemId}:`, err);
        }
    }

    state.selectedIds.clear();
    await refreshAll();
    updateActionBar();
};

// --- Tab switching ---

const switchTab = (tab) => {
    state.currentTab = tab;
    state.selectedIds.clear();

    for (const btn of document.querySelectorAll(".tab")) {
        btn.classList.toggle("active", btn.dataset.tab === tab);
    }

    if (document.startViewTransition) {
        document.startViewTransition(() => render());
    } else {
        render();
    }
};

// --- Event listeners (no inline handlers) ---

scanBtn.addEventListener("click", scan);

for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
}

sortSelect.addEventListener("change", () => {
    state.sorting = sortSelect.value;
    state.filtering = filterSelect.value;
    render();
});

filterSelect.addEventListener("change", () => {
    state.sorting = sortSelect.value;
    state.filtering = filterSelect.value;
    render();
});

grid.addEventListener("click", (e) => {
    const checkbox = e.target.closest(".card-checkbox");
    if (checkbox) {
        e.stopPropagation();
        toggleSelection(checkbox.dataset.id);
        return;
    }

    const card = e.target.closest(".media-card");
    if (card?.dataset.id) {
        toggleSelection(card.dataset.id);
    }
});

$("#deleteBtn").addEventListener("click", deleteSelected);
$("#dialogCancel").addEventListener("click", () => deleteDialog.close());
$("#dialogConfirm").addEventListener("click", confirmDelete);

// Close dialog on backdrop click
deleteDialog.addEventListener("click", (e) => {
    if (e.target === deleteDialog) deleteDialog.close();
});

// --- Utility ---

const escapeHtml = (str) =>
    str?.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;") ?? "";

const escapeAttr = (str) =>
    str?.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;") ?? "";

const formatSize = (bytes) => {
    if (bytes <= 0) return "0 B";
    if (bytes < 1000) return `${bytes} B`;
    for (const unit of ["KB", "MB", "GB", "TB"]) {
        bytes /= 1000;
        if (bytes < 1000 || unit === "TB") {
            if (bytes >= 100) return `${bytes.toFixed(0)} ${unit}`;
            if (bytes >= 10) return `${bytes.toFixed(1)} ${unit}`;
            return `${bytes.toFixed(2)} ${unit}`;
        }
    }
    return `${bytes.toFixed(1)} TB`;
};

// --- Initial load (top-level await) ---
await refreshAll();
render();
