const views = new Map(
  [...document.querySelectorAll("[data-view]")].map((view) => [view.dataset.view, view]),
);

async function revealAppWhenIconsAreReady() {
  if (document.fonts) {
    const iconFonts = Promise.all([
      document.fonts.load(
        '24px "Material Symbols Rounded"',
        "filter_list more_vert resume event tv done_all arrow_forward menu account_circle arrow_back close",
      ),
      document.fonts.load(
        '24px "Material Symbols Rounded Filled"',
        "resume event tv",
      ),
    ]);
    await Promise.race([
      iconFonts.catch(() => undefined),
      new Promise((resolve) => window.setTimeout(resolve, 4000)),
    ]);
  }
  window.requestAnimationFrame(() => {
    document.documentElement.classList.remove("app-booting");
  });
}

revealAppWhenIconsAreReady();
const navButtons = [...document.querySelectorAll("[data-nav-view]")];
const globalSearchBar = document.querySelector("[data-global-search-bar]");
const globalSearchInput = document.querySelector("[data-global-search]");
const searchMenuButton = document.querySelector("[data-search-menu]");
const searchBackButton = document.querySelector("[data-search-back]");
const searchProfileButton = document.querySelector("[data-search-profile]");
const searchClearButton = document.querySelector("[data-clear-search]");
const searchTextMeasureContext = document.createElement("canvas").getContext("2d");
const scrollPositions = { backlog: 0, upcoming: 0, tv: 0, detail: 0 };
const removeDialog = document.querySelector("[data-remove-dialog]");
const datePicker = document.querySelector("[data-date-picker]");
const libraryFilterDialog = document.querySelector("[data-library-filter-dialog]");
const imageViewer = document.querySelector("[data-image-viewer]");
const imageViewerImage = imageViewer?.querySelector("[data-image-viewer-image]");
const imageViewerStage = imageViewer?.querySelector("[data-image-viewer-stage]");
const snackbar = document.querySelector(".snackbar");
const libraryViewPreferences = {
  tv: {
    states: new Set(["ACTIVE"]),
    tags: new Set(),
    sortField: "name",
    sortDirection: "asc",
  },
};
const searchQueries = { backlog: "", upcoming: "", tv: "" };
const showDetailCache = new Map();
const showSeasonsCache = new Map();
const showRefreshRequests = new Map();
const pendingWatchChanges = new WeakSet();
const hydratedLibraryViews = new Set();
let currentView = "backlog";
let detailParentView = "backlog";
let detailRequest = null;
let pendingRemoveShowId = null;
let datePickerTarget = null;
let datePickerSelectedDate = null;
let datePickerMonth = new Date();
let libraryFilterView = null;
let libraryFilterDraft = null;
let tvSearchTimer = null;
let tvSearchRequest = null;
let tvSearchPending = false;
let tvSearchComplete = false;
let tvSearchError = "";
let snackbarAction = null;

if (!window.history.state?.trackApp) {
  window.history.replaceState({ trackApp: true, view: "backlog" }, "");
}

function writeHistory(state, mode = "push") {
  const method = mode === "replace" ? "replaceState" : "pushState";
  window.history[method]({ trackApp: true, ...state }, "");
}

function openImageViewer(trigger) {
  if (!imageViewer || !imageViewerImage || !imageViewerStage) return;
  imageViewerStage.setAttribute("aria-busy", "true");
  imageViewerStage.classList.remove("is-loaded", "has-error");
  imageViewerImage.alt = trigger.dataset.fullImageAlt || "Large image";
  imageViewerImage.src = trigger.dataset.fullImageSrc;
  imageViewer.showModal();
}

imageViewerImage?.addEventListener("load", () => {
  imageViewerStage?.classList.add("is-loaded");
  imageViewerStage?.removeAttribute("aria-busy");
});

imageViewerImage?.addEventListener("error", () => {
  imageViewerStage?.classList.add("has-error");
  imageViewerStage?.removeAttribute("aria-busy");
});

function updateActiveNav(navView) {
  navButtons.forEach((button) => {
    const active = button.dataset.navView === navView;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function syncSearchChrome() {
  const hasText = Boolean(globalSearchInput?.value);
  if (searchMenuButton) searchMenuButton.hidden = hasText;
  if (searchBackButton) searchBackButton.hidden = !hasText;
  if (searchProfileButton) searchProfileButton.hidden = hasText;
  if (searchClearButton) searchClearButton.hidden = !hasText;
  const filterButton = globalSearchBar?.querySelector("[data-open-library-filter]");
  if (filterButton) filterButton.hidden = currentView !== "tv" || hasText;
}

function syncSearchTextPosition() {
  if (!globalSearchInput || !searchTextMeasureContext || !globalSearchInput.clientWidth) return;
  const style = window.getComputedStyle(globalSearchInput);
  searchTextMeasureContext.font = style.font
    || `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
  const text = globalSearchInput.value || globalSearchInput.placeholder;
  const letterSpacing = Number.parseFloat(style.letterSpacing) || 0;
  const textWidth = searchTextMeasureContext.measureText(text).width
    + Math.max(0, text.length - 1) * letterSpacing;
  const centeredInset = Math.max(20, (globalSearchInput.clientWidth - textWidth) / 2);
  globalSearchInput.style.setProperty("--search-text-centered-inset", `${centeredInset}px`);
  globalSearchInput.classList.add("search-text-positioned");
}

function syncGlobalSearch() {
  if (!globalSearchBar || !globalSearchInput) return;
  const isDetail = currentView === "detail";
  globalSearchBar.hidden = isDetail;
  if (isDetail) return;

  const settings = {
    backlog: { placeholder: "Search queue", label: "Search queue episodes" },
    upcoming: { placeholder: "Search upcoming", label: "Search upcoming episodes" },
    tv: { placeholder: "Search TV", label: "Search TV shows" },
  }[currentView];
  if (!settings) return;
  globalSearchInput.placeholder = settings.placeholder;
  globalSearchInput.setAttribute("aria-label", settings.label);
  globalSearchInput.value = searchQueries[currentView];
  syncSearchChrome();
  syncSearchTextPosition();
}

function showView(viewName, historyMode = null) {
  if (!views.has(viewName) || viewName === currentView) return;

  if (currentView === "backlog" && viewName !== "backlog") {
    clearCaughtUpScheduleItems();
  }
  scrollPositions[currentView] = window.scrollY;
  views.forEach((view, name) => {
    const active = name === viewName;
    view.hidden = !active;
    view.classList.toggle("is-active", active);
  });

  updateActiveNav(viewName === "detail" ? detailParentView : viewName);
  currentView = viewName;
  syncGlobalSearch();
  const titles = {
    backlog: "Queue · Track",
    upcoming: "Upcoming · Track",
    tv: "TV · Track",
    detail: "Track",
  };
  document.title = titles[viewName] || "Track";
  window.scrollTo({ top: scrollPositions[viewName] || 0, behavior: "auto" });
  if (["backlog", "upcoming"].includes(viewName)) {
    refreshScheduleContent().catch(() => undefined);
  }
  if (historyMode && viewName !== "detail") {
    writeHistory({ view: viewName }, historyMode);
  }
}

function catalogCard(show) {
  const article = document.createElement("article");
  article.className = "popular-card";
  article.dataset.tmdbId = show.tmdb_id;
  if (show.show_id) article.dataset.showId = show.show_id;
  article.tabIndex = 0;
  article.setAttribute("role", "link");
  article.setAttribute("aria-label", `Open details for ${show.name}`);

  const poster = document.createElement("div");
  poster.className = "mini-poster";
  const initial = document.createElement("span");
  initial.textContent = show.name.charAt(0);
  if (show.poster_path) {
    const fallbackTemplate = document.createElement("template");
    fallbackTemplate.dataset.mediaFallbackTemplate = "";
    fallbackTemplate.content.append(initial);
    poster.append(fallbackTemplate);
  } else {
    poster.append(initial);
  }
  if (show.poster_path) {
    poster.classList.add("has-media-image");
    const image = document.createElement("img");
    image.src = `/media/poster/w185/${encodeURIComponent(show.poster_path.replace(/^\//, ""))}`;
    image.alt = "";
    image.loading = "lazy";
    image.decoding = "async";
    image.dataset.mediaImage = "";
    poster.append(image);
  }

  const copy = document.createElement("div");
  copy.className = "popular-card-copy";
  const title = document.createElement("h3");
  title.textContent = show.name;
  const meta = document.createElement("p");
  meta.textContent = show.first_air_date?.slice(0, 4) || "Release date unknown";
  const overview = document.createElement("p");
  overview.className = "catalog-overview";
  overview.textContent = show.overview;
  copy.append(title, meta, overview);
  article.append(poster, copy);
  if (show.show_id) article.classList.add("is-cached");
  copy.append(catalogActions());
  return article;
}

function settleMediaImage(image, loaded) {
  const container = image.closest(".has-media-image");
  if (!container) return;
  if (loaded) {
    container.classList.add("is-image-loaded");
    return;
  }
  container.classList.remove("has-media-image", "is-image-loaded");
  image.remove();
  const fallbackTemplate = container.querySelector("template[data-media-fallback-template]");
  if (fallbackTemplate) {
    container.append(fallbackTemplate.content.cloneNode(true));
    fallbackTemplate.remove();
  }
  container.querySelectorAll("[data-media-fallback]").forEach((fallback) => {
    fallback.hidden = false;
  });
}

function inspectCompletedMediaImage(image) {
  if (!image.complete) return;
  settleMediaImage(image, image.naturalWidth > 0);
}

function inspectMediaImages(root) {
  if (root.matches?.("img[data-media-image]")) inspectCompletedMediaImage(root);
  root.querySelectorAll?.("img[data-media-image]").forEach(inspectCompletedMediaImage);
}

function catalogActions() {
  const actions = document.createElement("div");
  actions.className = "popular-card-actions";
  [["ACTIVE", "Add to Active"], ["ARCHIVED", "Archive"]].forEach(([state, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "catalog-action";
    if (state === "ARCHIVED") button.classList.add("catalog-action-secondary");
    button.dataset.importState = state;
    button.textContent = label;
    actions.append(button);
  });
  return actions;
}

function syncTvSearchPresentation() {
  const view = views.get("tv");
  if (!view) return;
  const query = searchQueries.tv.trim();
  const addSection = view.querySelector("[data-tv-add-section]");
  const addResults = view.querySelector("[data-tv-add-results]");
  const loading = view.querySelector("[data-tv-search-loading]");
  const credit = view.querySelector("[data-tv-search-credit]");
  const empty = view.querySelector("[data-tv-search-empty]");
  const error = view.querySelector("[data-tv-search-error]");
  const addCount = addResults.querySelectorAll(".popular-card").length;
  const localCount = [...view.querySelectorAll("[data-state-section] .show-card")]
    .filter((card) => !card.hidden).length;

  if (!query) {
    addSection.hidden = true;
    empty.hidden = true;
    error.hidden = true;
    return;
  }

  addSection.hidden = !tvSearchPending && addCount === 0;
  loading.hidden = !tvSearchPending;
  addResults.hidden = tvSearchPending;
  credit.hidden = tvSearchPending || addCount === 0;
  addSection.querySelector("[data-tv-add-count]").textContent = addCount;
  error.hidden = !tvSearchError;
  if (tvSearchError) {
    error.querySelector("[data-tv-search-error-copy]").textContent = tvSearchError;
  }
  empty.hidden = tvSearchPending
    || !tvSearchComplete
    || Boolean(tvSearchError)
    || localCount + addCount > 0;
}

function clearTvCatalogResults() {
  const results = views.get("tv")?.querySelector("[data-tv-add-results]");
  if (results) results.replaceChildren();
}

function renderTvCatalogResults(results) {
  const available = results.filter((show) => !show.is_tracked);
  views.get("tv").querySelector("[data-tv-add-results]")
    .replaceChildren(...available.map(catalogCard));
  syncTvSearchPresentation();
}

async function searchTvCatalog(query) {
  if (tvSearchRequest) tvSearchRequest.abort();
  tvSearchRequest = new AbortController();
  tvSearchPending = true;
  tvSearchComplete = false;
  tvSearchError = "";
  clearTvCatalogResults();
  syncTvSearchPresentation();
  try {
    const response = await fetch(`/api/tv/search?q=${encodeURIComponent(query)}`, {
      signal: tvSearchRequest.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not search TMDB");
    if (searchQueries.tv.trim() !== query) return;
    tvSearchPending = false;
    tvSearchComplete = true;
    renderTvCatalogResults(data.results);
  } catch (error) {
    if (error.name === "AbortError") return;
    tvSearchPending = false;
    tvSearchComplete = true;
    tvSearchError = error.message;
    syncTvSearchPresentation();
  }
}

function appendLibraryCard(data) {
  if (!data.newly_tracked || !data.card_html) return;
  const existing = document.querySelector(`.show-card[data-show-id="${data.show_id}"]`);
  if (existing) return;
  const template = document.createElement("template");
  template.innerHTML = data.card_html.trim();
  document.querySelector(`[data-show-list="${data.state}"]`)?.append(template.content);
}

async function importCatalogShow(card, state, trigger) {
  const actions = card.querySelectorAll(".catalog-action");
  actions.forEach((button) => { button.disabled = true; });
  try {
    const hasLocalShow = Boolean(card.dataset.showId);
    const url = hasLocalShow
      ? `/api/shows/${card.dataset.showId}/state`
      : `/api/tv/shows/${card.dataset.tmdbId}/import`;
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not add show");
    invalidateShowCache(data.show_id, true);
    appendLibraryCard(data);
    card.remove();
    syncStateSections();
    filterAllShowViews();
    syncTvSearchPresentation();
  } catch (error) {
    actions.forEach((button) => { button.disabled = false; });
    showSnackbar(error.message);
  }
}

async function previewCatalogShow(card, historyMode = "push") {
  if (card.classList.contains("is-loading")) return;
  const cachedShowId = card.dataset.showId;
  const hasCachedDetails = Boolean(cachedShowId);
  card.classList.add("is-loading");
  card.setAttribute("aria-busy", "true");
  card.querySelectorAll(".catalog-action").forEach((button) => { button.disabled = true; });
  if (hasCachedDetails) await openShow(cachedShowId, "tv", true, historyMode);
  else {
    detailParentView = "tv";
    if (historyMode) {
      writeHistory({
        view: "detail",
        detailType: "catalog",
        tmdbId: card.dataset.tmdbId,
        parentView: "tv",
      }, historyMode);
    }
    prepareDetailLoad("Show details");
  }
  if (hasCachedDetails) {
    card.classList.remove("is-loading");
    card.removeAttribute("aria-busy");
    card.querySelectorAll(".catalog-action").forEach((button) => { button.disabled = false; });
    return;
  }
  if (currentView !== "detail") {
    card.classList.remove("is-loading");
    card.removeAttribute("aria-busy");
    card.querySelectorAll(".catalog-action").forEach((button) => { button.disabled = false; });
    return;
  }
  try {
    const response = await fetch(`/api/tv/shows/${card.dataset.tmdbId}/import`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: null }),
      signal: detailRequest.signal,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not open show");
    card.dataset.showId = data.show_id;
    if (data.is_tracked) card.remove();
    else card.classList.add("is-cached");
    invalidateShowCache(data.show_id, true);
    openShow(data.show_id, "tv", false, "replace");
  } catch (error) {
    if (error.name === "AbortError") return;
    card.querySelectorAll(".catalog-action").forEach((button) => { button.disabled = false; });
    if (!hasCachedDetails) {
      showView("tv", "replace");
      views.get("detail").replaceChildren();
    }
    showSnackbar(error.message);
  } finally {
    card.classList.remove("is-loading");
    card.removeAttribute("aria-busy");
  }
}

async function trackDetailShow(showElement, state, trigger) {
  trigger.disabled = true;
  try {
    const response = await fetch(`/api/shows/${showElement.dataset.showId}/state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not add show");
    invalidateShowCache(data.show_id);
    appendLibraryCard(data);
    document.querySelectorAll(`.popular-card[data-tmdb-id="${showElement.dataset.tmdbId}"]`)
      .forEach((card) => card.remove());
    syncStateSections();
    filterAllShowViews();
    syncTvSearchPresentation();
    openShow(data.show_id, "tv", true, "replace");
  } catch (error) {
    trigger.disabled = false;
    showSnackbar(error.message);
  }
}

function renderDetailSkeleton(title = "Show details") {
  const detailView = views.get("detail");
  const template = document.querySelector("#detail-skeleton-template");
  detailView.replaceChildren(template.content.cloneNode(true));
  detailView.querySelector("[data-detail-skeleton-title]").textContent = title;
}

function parseIsoDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function toIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatDisplayDate(value) {
  const date = parseIsoDate(value);
  if (!date) return value;
  const month = new Intl.DateTimeFormat(undefined, { month: "short" }).format(date);
  const day = date.getDate();
  const year = date.getFullYear() === new Date().getFullYear()
    ? ""
    : `, ${date.getFullYear()}`;
  return `${month} ${day}${year}`;
}

function formatDisplayDates(root = document) {
  root.querySelectorAll("[data-display-date]").forEach((time) => {
    time.textContent = formatDisplayDate(time.dateTime);
  });
}

function waitForScheduleAnimation(card) {
  return new Promise((resolve) => {
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      resolve();
    };
    card.querySelector(".schedule-timeline-content")
      ?.addEventListener("animationend", finish, { once: true });
    window.setTimeout(finish, 240);
  });
}

function syncCatchUpEmptyState() {
  const view = views.get("backlog");
  const cards = view.querySelectorAll('[data-schedule-mode="catch-up"]');
  const empty = view.querySelector("[data-catch-up-empty]");
  if (empty) empty.hidden = cards.length > 0;
  filterSchedule();
}

function clearCaughtUpScheduleItems() {
  const view = views.get("backlog");
  view.querySelectorAll('[data-schedule-mode="catch-up"].is-caught-up')
    .forEach((card) => card.remove());
  syncCatchUpEmptyState();
}

function showCaughtUpScheduleState(card, data, action) {
  card.classList.remove("is-leaving");
  card.classList.add("is-caught-up", "is-entering");

  if (action === "watch") {
    const percent = card.querySelector(".schedule-timeline-marker strong");
    const count = card.querySelector(".schedule-timeline-marker span");
    const progress = card.querySelector(".schedule-timeline-progress .progress-track span");
    if (percent) percent.textContent = `${data.percent}%`;
    if (count) count.textContent = `${data.watched_count}/${data.episode_count}`;
    if (progress) progress.style.width = `${data.percent}%`;
  }

  const actions = card.querySelector(".schedule-timeline-actions");
  if (actions) {
    actions.innerHTML = `
      <span class="schedule-caught-up-icon material-symbols-rounded"
        role="img" aria-label="Caught up">done_all</span>`;
  }
  window.setTimeout(() => card.classList.remove("is-entering"), 240);
}

async function refreshScheduleContent() {
  const response = await fetch("/api/schedule", {
    headers: { "X-Requested-With": "Track" },
  });
  if (!response.ok) throw new Error("Could not refresh Schedule");
  const template = document.createElement("template");
  template.innerHTML = (await response.text()).trim();
  ["backlog", "upcoming"].forEach((viewName) => {
    const incoming = template.content.querySelector(`[data-schedule-content="${viewName}"]`);
    const current = views.get(viewName)?.querySelector(`[data-schedule-content="${viewName}"]`);
    if (incoming && current) current.replaceWith(incoming);
    formatDisplayDates(views.get(viewName));
    filterSchedule(viewName);
  });
}

async function undoScheduleSkip(episodeId) {
  const response = await fetch(`/api/episodes/${episodeId}/skip`, { method: "DELETE" });
  if (!response.ok) throw new Error("Could not undo skip");
  await refreshScheduleContent();
  showSnackbar("Skip undone");
}

async function processScheduleEpisode(card, action) {
  const episodeId = card.dataset.episodeId;
  const showId = card.dataset.showId;
  const buttons = card.querySelectorAll("[data-schedule-action]");
  let processed = false;
  buttons.forEach((button) => { button.disabled = true; });

  try {
    const response = action === "watch"
      ? await fetch(`/api/episodes/${episodeId}/watch-count`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "increment" }),
      })
      : await fetch(`/api/episodes/${episodeId}/skip`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Could not ${action} episode`);
    processed = true;
    if (action === "watch") applyShowProgress(data);

    const nextResponse = await fetch(`/api/schedule/shows/${showId}/catch-up`, {
      headers: { "X-Requested-With": "Track" },
    });
    if (!nextResponse.ok && nextResponse.status !== 204) {
      throw new Error("Could not load the next episode");
    }
    const nextHtml = nextResponse.status === 204 ? "" : await nextResponse.text();
    card.classList.add("is-leaving");
    await waitForScheduleAnimation(card);

    if (nextHtml.trim()) {
      const template = document.createElement("template");
      template.innerHTML = nextHtml.trim();
      const nextCard = template.content.firstElementChild;
      nextCard.classList.add("is-entering");
      card.replaceWith(nextCard);
      formatDisplayDates(nextCard);
      filterSchedule();
      window.setTimeout(() => nextCard.classList.remove("is-entering"), 240);
    } else if (
      action === "watch"
      && data.episode_count > 0
      && data.watched_count === data.episode_count
    ) {
      showCaughtUpScheduleState(card, data, action);
    } else {
      await refreshScheduleContent();
    }

    if (action === "skip") {
      showSnackbar("Episode skipped", {
        actionLabel: "Undo",
        onAction: () => undoScheduleSkip(episodeId),
      });
    } else {
      showSnackbar("Episode watched");
    }
  } catch (error) {
    if (processed) {
      await refreshScheduleContent().catch(() => undefined);
      showSnackbar("Episode processed; Schedule was refreshed");
    } else {
      card.classList.remove("is-leaving");
      buttons.forEach((button) => { button.disabled = false; });
      showSnackbar(error.message);
    }
  }
}

function finishDetailLoad({ resetScroll = true } = {}) {
  const detailView = views.get("detail");
  formatDisplayDates(detailView);
  const title = detailView.querySelector("[data-detail-title]")?.dataset.detailTitle;
  if (title) document.title = `${title} \u00B7 Track`;
  if (resetScroll) window.scrollTo({ top: 0, behavior: "auto" });
}

function invalidateShowCache(showId, includeSeasons = false) {
  showDetailCache.delete(String(showId));
  if (includeSeasons) showSeasonsCache.delete(String(showId));
}

function cacheCurrentSeasons(showId) {
  const detailShow = views.get("detail").querySelector(`[data-detail-show][data-show-id="${showId}"]`);
  const seasonList = detailShow?.querySelector("[data-season-list]");
  if (seasonList && !seasonList.querySelector("[data-season-loading]")) {
    const cachedList = seasonList.cloneNode(true);
    enableWatchControls(cachedList);
    showSeasonsCache.set(String(showId), cachedList.innerHTML);
  }
}

function enableWatchControls(root) {
  root.querySelectorAll("[data-episode-watch], [data-season-watch]")
    .forEach((control) => { control.disabled = false; });
}

function replaceLibraryCard(showId, cardHtml) {
  if (!cardHtml) return;
  const currentCard = document.querySelector(`.show-card[data-show-id="${showId}"]`);
  if (!currentCard) return;
  const template = document.createElement("template");
  template.innerHTML = cardHtml.trim();
  currentCard.replaceWith(template.content);
  syncStateSections();
  filterAllShowViews();
}

async function fetchRefreshedShowFragments(showId) {
  const overviewResponse = await fetch(`/api/shows/${showId}`, {
    headers: { "X-Requested-With": "Track" },
  });
  if (!overviewResponse.ok) throw new Error("Could not load refreshed show");
  const overviewHtml = await overviewResponse.text();

  const seasonsResponse = await fetch(`/api/shows/${showId}/seasons`, {
    headers: { "X-Requested-With": "Track" },
  });
  if (!seasonsResponse.ok) throw new Error("Could not load refreshed seasons");
  const seasonsHtml = await seasonsResponse.text();

  const cacheKey = String(showId);
  showDetailCache.set(cacheKey, overviewHtml);
  showSeasonsCache.set(cacheKey, seasonsHtml);

  const currentShow = views.get("detail")
    .querySelector(`[data-detail-show][data-show-id="${showId}"]`);
  if (!currentShow) return;
  const openSeasonIds = new Set(
    [...currentShow.querySelectorAll("details.season[open]")]
      .map((season) => season.dataset.seasonId),
  );

  const template = document.createElement("template");
  template.innerHTML = overviewHtml.trim();
  const nextSeasonList = template.content.querySelector("[data-season-list]");
  nextSeasonList.innerHTML = seasonsHtml;
  nextSeasonList.removeAttribute("aria-busy");
  openSeasonIds.forEach((seasonId) => {
    const season = nextSeasonList.querySelector(`[data-season-id="${seasonId}"]`);
    if (season) season.open = true;
  });
  views.get("detail").replaceChildren(template.content);
  finishDetailLoad({ resetScroll: false });
}

async function refreshShowMetadata(showId, { force = false, trigger = null } = {}) {
  const cacheKey = String(showId);
  if (showRefreshRequests.has(cacheKey)) return showRefreshRequests.get(cacheKey);
  if (trigger) trigger.disabled = true;

  const refreshRequest = (async () => {
    const response = await fetch(`/api/shows/${showId}/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not refresh show");

    if (data.refreshed) {
      await fetchRefreshedShowFragments(showId);
      replaceLibraryCard(showId, data.card_html);
    } else {
      const cachedOverview = showDetailCache.get(cacheKey);
      if (cachedOverview) {
        showDetailCache.set(
          cacheKey,
          cachedOverview.replace('data-metadata-refresh-due="true"', 'data-metadata-refresh-due="false"'),
        );
      }
      const currentShow = views.get("detail")
        .querySelector(`[data-detail-show][data-show-id="${showId}"]`);
      if (currentShow) currentShow.dataset.metadataRefreshDue = "false";
    }
    if (force) showSnackbar(data.refreshed ? "Show refreshed" : "Show is up to date");
    return data;
  })();

  showRefreshRequests.set(cacheKey, refreshRequest);
  try {
    return await refreshRequest;
  } catch (error) {
    if (force) showSnackbar(error.message);
    return null;
  } finally {
    showRefreshRequests.delete(cacheKey);
    if (trigger) trigger.disabled = false;
  }
}

function refreshShowIfDue(showId) {
  const currentShow = views.get("detail")
    .querySelector(`[data-detail-show][data-show-id="${showId}"]`);
  if (currentShow?.dataset.metadataRefreshDue === "true") {
    refreshShowMetadata(showId);
  }
}

async function loadShowSeasons(showId, signal) {
  const cacheKey = String(showId);
  const detailShow = views.get("detail").querySelector(`[data-detail-show][data-show-id="${showId}"]`);
  const seasonList = detailShow?.querySelector("[data-season-list]");
  if (!seasonList) return;

  if (showSeasonsCache.has(cacheKey)) {
    seasonList.innerHTML = showSeasonsCache.get(cacheKey);
    enableWatchControls(seasonList);
    seasonList.removeAttribute("aria-busy");
    formatDisplayDates(seasonList);
    return;
  }

  try {
    const response = await fetch(`/api/shows/${showId}/seasons`, {
      headers: { "X-Requested-With": "Track" },
      signal,
    });
    if (!response.ok) throw new Error("Could not load seasons");
    const html = await response.text();
    showSeasonsCache.set(cacheKey, html);
    const currentList = views.get("detail")
      .querySelector(`[data-detail-show][data-show-id="${showId}"] [data-season-list]`);
    if (!currentList) return;
    currentList.innerHTML = html;
    enableWatchControls(currentList);
    currentList.removeAttribute("aria-busy");
    formatDisplayDates(currentList);
  } catch (error) {
    if (error.name === "AbortError") return;
    const currentList = views.get("detail")
      .querySelector(`[data-detail-show][data-show-id="${showId}"] [data-season-list]`);
    if (!currentList) return;
    currentList.innerHTML = `
      <div class="season-load-error">
        <span>Couldn't load seasons and episodes.</span>
        <button type="button" data-retry-seasons="${showId}">Try again</button>
      </div>`;
    currentList.removeAttribute("aria-busy");
  }
}

function prepareDetailLoad(title) {
  if (detailRequest) detailRequest.abort();
  detailRequest = new AbortController();
  renderDetailSkeleton(title);
  scrollPositions.detail = 0;
  if (currentView === "detail") window.scrollTo({ top: 0, behavior: "auto" });
  else showView("detail");
}

async function openShow(
  showId,
  parentView = currentView,
  showSkeleton = true,
  historyMode = "push",
) {
  detailParentView = ["backlog", "upcoming", "tv"].includes(parentView)
    ? parentView
    : "backlog";
  if (historyMode) {
    writeHistory({
      view: "detail",
      detailType: "show",
      showId: String(showId),
      parentView: detailParentView,
    }, historyMode);
  }
  if (showSkeleton) prepareDetailLoad("Show details");
  else {
    if (detailRequest) detailRequest.abort();
    detailRequest = new AbortController();
  }

  const cacheKey = String(showId);
  if (showDetailCache.has(cacheKey)) {
    views.get("detail").innerHTML = showDetailCache.get(cacheKey);
    finishDetailLoad();
    loadShowSeasons(showId, detailRequest.signal).finally(() => refreshShowIfDue(showId));
    return;
  }

  try {
    const response = await fetch(`/api/shows/${showId}`, {
      headers: { "X-Requested-With": "Track" },
      signal: detailRequest.signal,
    });
    if (!response.ok) throw new Error("Could not load show");
    const html = await response.text();
    showDetailCache.set(cacheKey, html);
    views.get("detail").innerHTML = html;
    finishDetailLoad();
    loadShowSeasons(showId, detailRequest.signal).finally(() => refreshShowIfDue(showId));
  } catch (error) {
    if (error.name === "AbortError") return;
    views.get("detail").innerHTML = `
      <header class="detail-app-bar">
        <button class="icon-button" type="button" data-detail-back aria-label="Back">
          <span class="material-symbols-rounded" aria-hidden="true">arrow_back</span>
        </button>
        <span>Show details</span>
      </header>
      <div class="empty-state detail-error">
        <span class="empty-icon material-symbols-rounded" aria-hidden="true">cloud_off</span>
        <h2>Couldn't load this show</h2>
        <p>Check the connection and try again.</p>
        <button class="filled-button" type="button" data-retry-show="${showId}">Try again</button>
      </div>`;
  }
}

async function openEpisode(episodeId, historyMode = "push") {
  const activeHistoryState = window.history.state;
  const previousWasShow = historyMode
    ? Boolean(
      activeHistoryState?.trackApp
      && activeHistoryState.view === "detail"
      && activeHistoryState.detailType === "show"
    )
    : Boolean(activeHistoryState?.previousWasShow);

  if (historyMode) {
    writeHistory({
      view: "detail",
      detailType: "episode",
      episodeId: String(episodeId),
      parentView: detailParentView,
      previousWasShow,
    }, historyMode);
  }
  prepareDetailLoad("Episode details");

  try {
    const response = await fetch(`/api/episodes/${episodeId}`, {
      headers: { "X-Requested-With": "Track" },
      signal: detailRequest.signal,
    });
    if (!response.ok) throw new Error("Could not load episode");
    const episodeTemplate = document.createElement("template");
    episodeTemplate.innerHTML = await response.text();
    if (previousWasShow) {
      episodeTemplate.content.querySelector("[data-episode-show-open]")?.remove();
    }
    views.get("detail").replaceChildren(episodeTemplate.content);
    finishDetailLoad();
  } catch (error) {
    if (error.name === "AbortError") return;
    views.get("detail").innerHTML = `
      <header class="detail-app-bar">
        <button class="icon-button" type="button" data-detail-back aria-label="Back">
          <span class="material-symbols-rounded" aria-hidden="true">arrow_back</span>
        </button>
        <span>Episode details</span>
      </header>
      <div class="empty-state detail-error">
        <span class="empty-icon material-symbols-rounded" aria-hidden="true">cloud_off</span>
        <h2>Couldn't load this episode</h2>
        <p>Check the connection and try again.</p>
        <button class="filled-button" type="button" data-retry-episode="${episodeId}">Try again</button>
      </div>`;
  }
}

function syncActivityCount(log) {
  if (!log) return;
  const count = log.querySelectorAll(".activity-item").length;
  const countElement = log.querySelector("[data-activity-count]");
  const labelElement = log.querySelector("[data-activity-count-label]");
  if (countElement) countElement.textContent = count;
  if (labelElement) labelElement.textContent = count === 1 ? "entry" : "entries";
}

function sortActivityItems(log) {
  const list = log?.querySelector("[data-activity-list]");
  if (!list) return;
  [...list.querySelectorAll(".activity-item")]
    .sort((a, b) => {
      const dateOrder = (b.dataset.sortDate || "").localeCompare(a.dataset.sortDate || "");
      if (dateOrder) return dateOrder;
      return (b.dataset.addedAt || "").localeCompare(a.dataset.addedAt || "");
    })
    .forEach((item) => list.append(item));
}

function addActivityItem({
  type,
  title,
  occurredAt,
  seasonId = null,
  recordId = null,
  watchKind = null,
  addedAt = null,
}) {
  const log = views.get("detail").querySelector("[data-activity-log]");
  const list = log?.querySelector("[data-activity-list]");
  if (!list || !occurredAt) return;

  list.querySelector("[data-activity-empty]")?.remove();
  const item = document.createElement("li");
  item.className = "activity-item";
  item.dataset.activityType = type;
  item.dataset.sortDate = occurredAt;
  if (seasonId) item.dataset.seasonId = seasonId;
  if (recordId) {
    item.dataset.watchRecordId = recordId;
    item.dataset.watchKind = watchKind;
    item.dataset.addedAt = addedAt;
    item.dataset.watchDate = "";
  }

  const icon = document.createElement("span");
  icon.className = "material-symbols-rounded activity-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = {
    archived: "archive",
    activated: "play_arrow",
    season_watched: "done_all",
  }[type] || "history";

  const copy = document.createElement("span");
  copy.className = "activity-copy";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const time = document.createElement("time");
  time.dateTime = occurredAt;
  time.dataset.displayDate = "";
  time.textContent = formatDisplayDate(occurredAt);
  copy.append(heading, time);

  if (recordId) {
    const button = document.createElement("button");
    button.className = "activity-item-button";
    button.type = "button";
    button.dataset.watchLogEntry = "";
    button.setAttribute("aria-label", `Set date for ${title}`);
    const editIcon = document.createElement("span");
    editIcon.className = "material-symbols-rounded activity-edit-icon";
    editIcon.setAttribute("aria-hidden", "true");
    editIcon.textContent = "edit_calendar";
    button.append(icon, copy, editIcon);
    item.append(button);
  } else {
    item.append(icon, copy);
  }
  list.prepend(item);
  formatDisplayDates(item);
  sortActivityItems(log);
  syncActivityCount(log);
}

function removeSeasonActivity(recordId) {
  const log = views.get("detail").querySelector("[data-activity-log]");
  log?.querySelector(`.activity-item[data-watch-kind="season"][data-watch-record-id="${recordId}"]`)?.remove();
  syncActivityCount(log);
}

function renderDatePicker() {
  if (!datePicker) return;
  datePicker.querySelector("[data-date-picker-selection]").textContent =
    datePickerSelectedDate ? formatDisplayDate(toIsoDate(datePickerSelectedDate)) : "No date set";
  datePicker.querySelector("[data-date-picker-month]").textContent =
    new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" })
      .format(datePickerMonth);

  const grid = datePicker.querySelector("[data-date-picker-grid]");
  grid.replaceChildren();
  const year = datePickerMonth.getFullYear();
  const month = datePickerMonth.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayIso = toIsoDate(new Date());
  const selectedIso = datePickerSelectedDate ? toIsoDate(datePickerSelectedDate) : null;

  for (let index = 0; index < firstWeekday; index += 1) {
    grid.append(document.createElement("span"));
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = new Date(year, month, day);
    const isoDate = toIsoDate(date);
    const button = document.createElement("button");
    button.className = "date-picker-day";
    button.type = "button";
    button.dataset.datePickerDay = isoDate;
    button.textContent = day;
    button.setAttribute("role", "gridcell");
    button.setAttribute("aria-label", formatDisplayDate(isoDate));
    button.classList.toggle("is-today", isoDate === todayIso);
    button.classList.toggle("is-selected", isoDate === selectedIso);
    button.setAttribute("aria-selected", String(isoDate === selectedIso));
    grid.append(button);
  }
}

function openWatchDatePicker(item) {
  if (!datePicker) return;
  datePickerTarget = item;
  datePickerSelectedDate = parseIsoDate(item.dataset.watchDate);
  const visibleDate = datePickerSelectedDate || parseIsoDate(item.dataset.sortDate) || new Date();
  datePickerMonth = new Date(visibleDate.getFullYear(), visibleDate.getMonth(), 1);
  renderDatePicker();
  datePicker.showModal();
}

function shiftDatePickerMonth(offset) {
  datePickerMonth = new Date(
    datePickerMonth.getFullYear(),
    datePickerMonth.getMonth() + offset,
    1,
  );
  renderDatePicker();
}

async function saveWatchDate() {
  if (!datePickerTarget) return;
  const saveButton = datePicker.querySelector("[data-date-picker-save]");
  saveButton.disabled = true;
  const watchDate = datePickerSelectedDate ? toIsoDate(datePickerSelectedDate) : null;
  try {
    const response = await fetch(
      `/api/watch-history/${datePickerTarget.dataset.watchKind}/${datePickerTarget.dataset.watchRecordId}/date`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ watch_date: watchDate }),
      },
    );
    if (!response.ok) throw new Error("Could not update watch date");
    const data = await response.json();
    datePickerTarget.dataset.watchDate = data.watch_date || "";
    datePickerTarget.dataset.addedAt = data.added_at;
    datePickerTarget.dataset.sortDate = data.display_date;
    const time = datePickerTarget.querySelector("[data-display-date]");
    time.dateTime = data.display_date;
    formatDisplayDates(datePickerTarget);
    sortActivityItems(datePickerTarget.closest("[data-activity-log]"));
    const detailShow = datePickerTarget.closest("[data-detail-show]");
    if (detailShow) invalidateShowCache(detailShow.dataset.showId);
    datePicker.close();
  } catch (_error) {
    showSnackbar("Couldn't update the watch date. Try again.");
  } finally {
    saveButton.disabled = false;
  }
}

function syncLibraryFilterDialog() {
  if (!libraryFilterDialog || !libraryFilterDraft) return;
  libraryFilterDialog.querySelectorAll("[data-filter-state]").forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(libraryFilterDraft.states.has(button.dataset.filterState)),
    );
  });
  libraryFilterDialog.querySelectorAll("[data-filter-tag]").forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(libraryFilterDraft.tags.has(button.dataset.filterTag)),
    );
  });
  libraryFilterDialog.querySelectorAll("[data-sort-field]").forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.sortField === libraryFilterDraft.sortField),
    );
  });
  libraryFilterDialog.querySelectorAll("[data-sort-direction]").forEach((button) => {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.sortDirection === libraryFilterDraft.sortDirection),
    );
  });
}

function openLibraryFilter(viewName) {
  const preferences = libraryViewPreferences[viewName];
  if (!libraryFilterDialog || !preferences) return;
  globalSearchInput?.blur();
  libraryFilterView = viewName;
  libraryFilterDraft = {
    states: new Set(preferences.states),
    tags: new Set(preferences.tags),
    sortField: preferences.sortField,
    sortDirection: preferences.sortDirection,
  };
  syncLibraryFilterDialog();
  libraryFilterDialog.showModal();
}

function updateLibraryFilterButton(viewName) {
  const preferences = libraryViewPreferences[viewName];
  const button = document.querySelector(`[data-open-library-filter="${viewName}"]`);
  if (!preferences || !button) return;
  const defaultStates = preferences.states.size === 1 && preferences.states.has("ACTIVE");
  const customized = !defaultStates || preferences.tags.size > 0;
  button.classList.toggle("has-active-filter", customized);
}

function applyLibraryFilterDraft() {
  if (!libraryFilterView || !libraryFilterDraft) return;
  libraryViewPreferences[libraryFilterView] = {
    states: new Set(libraryFilterDraft.states),
    tags: new Set(libraryFilterDraft.tags),
    sortField: libraryFilterDraft.sortField,
    sortDirection: libraryFilterDraft.sortDirection,
  };
  updateLibraryFilterButton(libraryFilterView);
  filterShowView(views.get(libraryFilterView));
  libraryFilterDialog.close();
}

function closeShowMenus(exceptMenu = null) {
  document.querySelectorAll("[data-show-menu]").forEach((menu) => {
    if (menu === exceptMenu) return;
    menu.hidden = true;
    menu.parentElement.querySelector("[data-show-menu-button]")
      ?.setAttribute("aria-expanded", "false");
  });
}

function toggleShowMenu(button) {
  const menu = button.parentElement.querySelector("[data-show-menu]")
    || button.closest("[data-show-id]")?.querySelector("[data-show-menu]");
  if (!menu) return;
  const willOpen = menu.hidden;
  closeWatchMenus();
  closeShowMenus(menu);
  menu.hidden = !willOpen;
  button.setAttribute("aria-expanded", String(willOpen));
}

function closeWatchMenus(exceptMenu = null) {
  document.querySelectorAll("[data-watch-menu]").forEach((menu) => {
    if (menu !== exceptMenu) menu.hidden = true;
  });
}

function toggleWatchMenu(control) {
  const menu = control.parentElement.querySelector("[data-watch-menu]");
  if (!menu) return;
  const willOpen = menu.hidden;
  closeShowMenus();
  closeWatchMenus(menu);
  menu.hidden = !willOpen;
}

function syncProgressState(showElement) {
  const watchedCount = Number(showElement.dataset.watchedCount);
  const episodeCount = Number(showElement.dataset.episodeCount);
  if (!Number.isFinite(watchedCount) || !Number.isFinite(episodeCount)) return;

  let progressState = "started";
  let progressLabel = "Watching";
  if (watchedCount === 0) {
    progressState = "not-started";
    progressLabel = "New";
  } else if (episodeCount > 0 && watchedCount >= episodeCount) {
    progressState = "finished";
    progressLabel = "Finished";
  } else if (showElement.dataset.showState === "ARCHIVED") {
    progressLabel = "Stopped";
  }

  showElement.dataset.progressState = progressState;
  const tag = showElement.querySelector("[data-progress-tag]");
  if (tag) tag.textContent = progressLabel;
}

function updateShowRepresentations(showId, state, moveLabel, moveIcon) {
  document.querySelectorAll(`[data-show-id="${showId}"]`).forEach((showElement) => {
    showElement.dataset.showState = state;
    showElement.querySelectorAll('[data-show-action="move"]').forEach((moveButton) => {
      moveButton.dataset.targetState = state === "ARCHIVED" ? "ACTIVE" : "ARCHIVED";
      moveButton.querySelector("[data-move-label]").textContent = moveLabel;
      moveButton.querySelector(".material-symbols-rounded").textContent = moveIcon;
    });
    syncProgressState(showElement);
  });
}

function syncStateSections() {
  document.querySelectorAll("[data-state-section]").forEach((section) => {
    const count = section.querySelectorAll(".show-card").length;
    section.querySelector("[data-state-count]").textContent = count;
    section.querySelector("[data-state-empty]").hidden = count > 0;
  });
}

async function moveShow(showElement, targetState, actionButton) {
  const showId = showElement.dataset.showId;
  actionButton.disabled = true;
  try {
    const response = await fetch(`/api/shows/${showId}/state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: targetState }),
    });
    if (!response.ok) throw new Error("Could not move show");
    const data = await response.json();
    invalidateShowCache(showId);

    const card = document.querySelector(`.show-card[data-show-id="${showId}"]`);
    document.querySelector(`[data-show-list="${data.state}"]`)?.append(card);
    updateShowRepresentations(showId, data.state, data.move_label, data.move_icon);
    if (currentView === "detail"
      && views.get("detail").querySelector(`[data-detail-show][data-show-id="${showId}"]`)) {
      addActivityItem({
        type: data.activity_type,
        title: data.activity_title,
        occurredAt: data.changed_at,
      });
    }
    detailParentView = "tv";
    if (currentView === "detail") updateActiveNav(detailParentView);
    syncStateSections();
    filterAllShowViews();
    showSnackbar(data.state === "ARCHIVED" ? "Show archived" : "Show made active");
  } catch (_error) {
    showSnackbar("Couldn't move this show. Try again.");
  } finally {
    actionButton.disabled = false;
  }
}

function requestShowRemoval(showElement) {
  pendingRemoveShowId = showElement.dataset.showId;
  const showName = showElement.querySelector("h1, h3")?.textContent.trim() || "this show";
  removeDialog.querySelector("h2").textContent = `Remove ${showName}?`;
  removeDialog.showModal();
}

async function confirmShowRemoval() {
  if (!pendingRemoveShowId) return;
  const showId = pendingRemoveShowId;
  const showRepresentation = document.querySelector(`[data-show-id="${showId}"]`);
  const tmdbId = showRepresentation?.dataset.tmdbId;
  const confirmButton = removeDialog.querySelector("[data-confirm-remove]");
  confirmButton.disabled = true;
  try {
    const response = await fetch(`/api/shows/${showId}`, { method: "DELETE" });
    if (!response.ok) throw new Error("Could not remove show");
    invalidateShowCache(showId);
    document.querySelector(`.show-card[data-show-id="${showId}"]`)?.remove();
    if (tmdbId) {
      document.querySelectorAll(`.popular-card[data-tmdb-id="${tmdbId}"]`).forEach((card) => {
        card.classList.add("is-cached");
        card.dataset.showId = showId;
      });
    }
    if (views.get("detail").querySelector(`[data-show-id="${showId}"]`)) {
      showView(detailParentView, "replace");
      views.get("detail").replaceChildren();
    }
    syncStateSections();
    filterAllShowViews();
    if (searchQueries.tv.trim()) searchTvCatalog(searchQueries.tv.trim());
    removeDialog.close();
    pendingRemoveShowId = null;
    showSnackbar("Show removed from your library");
  } catch (_error) {
    showSnackbar("Couldn't remove this show. Try again.");
  } finally {
    confirmButton.disabled = false;
  }
}

function setWatchControl(control, watchCount, mixed = false) {
  control.dataset.watchCount = watchCount;
  control.setAttribute("aria-checked", mixed ? "mixed" : String(watchCount > 0));
  const check = control.querySelector("[data-watch-check]");
  const mixedIcon = control.querySelector("[data-watch-mixed]");
  const counter = control.querySelector("[data-watch-counter]");
  if (check) check.hidden = mixed || watchCount > 1;
  if (mixedIcon) mixedIcon.hidden = !mixed;
  if (counter) {
    counter.hidden = mixed || watchCount <= 1;
    counter.textContent = watchCount;
  }
}

function syncSeasonFromEpisodes(season) {
  const episodes = [...season.querySelectorAll(".episode")];
  const counts = episodes.map((episode) => Number(episode.dataset.watchCount));
  const watchedCount = counts.filter((count) => count > 0).length;
  const minimumWatchCount = counts.length ? Math.min(...counts) : 0;
  season.dataset.episodeCount = episodes.length;
  season.dataset.watchedCount = watchedCount;
  season.dataset.minWatchCount = minimumWatchCount;
  if (season.dataset.progressCounted !== "false") {
    season.querySelector(".season-title small").textContent = `${watchedCount} of ${episodes.length}`;
  }
  const mixed = watchedCount > 0 && watchedCount < episodes.length;
  const displayedCount = watchedCount === episodes.length ? minimumWatchCount : 0;
  setWatchControl(season.querySelector("[data-season-watch]"), displayedCount, mixed);
}

function updateEpisodeWatchUi(episode, watchCount, syncSeason = true) {
  episode.dataset.watchCount = watchCount;
  episode.classList.toggle("is-watched", watchCount > 0);
  setWatchControl(episode.querySelector("[data-episode-watch]"), watchCount);
  if (syncSeason) syncSeasonFromEpisodes(episode.closest(".season"));
}

function applyShowProgress(data) {
  invalidateShowCache(data.show_id, true);
  updateProgress(document.querySelector("[data-progress-summary]"), data);
  const showCard = document.querySelector(`.show-card[data-show-id="${data.show_id}"]`);
  if (showCard) {
    showCard.dataset.watchedCount = data.watched_count;
    showCard.dataset.episodeCount = data.episode_count;
    showCard.querySelector("[data-card-progress-copy]").textContent =
      `${data.watched_count} of ${data.episode_count}`;
    const cardProgress = showCard.querySelector("[data-card-progress]");
    cardProgress.setAttribute("aria-valuenow", data.percent);
    cardProgress.querySelector("span").style.width = `${data.percent}%`;
    showCard.querySelector(".progress-copy strong").textContent = `${data.percent}%`;
    syncProgressState(showCard);
  }

  const detailShow = document.querySelector(`[data-detail-show][data-show-id="${data.show_id}"]`);
  if (detailShow) {
    detailShow.dataset.watchedCount = data.watched_count;
    detailShow.dataset.episodeCount = data.episode_count;
    syncProgressState(detailShow);
  }
  filterAllShowViews();
}

async function changeEpisodeWatchCount(episode, action, trigger) {
  if (pendingWatchChanges.has(episode)) return;
  pendingWatchChanges.add(episode);
  try {
    const response = await fetch(`/api/episodes/${episode.dataset.episodeId}/watch-count`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    if (!response.ok) throw new Error("Could not update episode");
    const data = await response.json();
    updateEpisodeWatchUi(episode, data.watch_count);
    applyShowProgress(data);
    cacheCurrentSeasons(data.show_id);
  } catch (_error) {
    showSnackbar("Couldn't update this episode. Try again.");
  } finally {
    pendingWatchChanges.delete(episode);
  }
}

async function changeSeasonWatchCount(season, action, trigger) {
  if (pendingWatchChanges.has(season)) return;
  pendingWatchChanges.add(season);
  try {
    const response = await fetch(`/api/seasons/${season.dataset.seasonId}/watch-count`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    if (!response.ok) throw new Error("Could not update season");
    const data = await response.json();
    data.episodes.forEach((episodeData) => {
      const episode = season.querySelector(`[data-episode-id="${episodeData.episode_id}"]`);
      if (episode) updateEpisodeWatchUi(episode, episodeData.watch_count, false);
    });
    syncSeasonFromEpisodes(season);
    applyShowProgress(data);
    if (action === "increment") {
      addActivityItem({
        type: "season_watched",
        title: `${data.season_name} watched`,
        occurredAt: data.season_watched_at,
        seasonId: String(data.season_id),
        recordId: String(data.season_watch_record_id),
        watchKind: "season",
        addedAt: data.season_watched_at,
      });
    } else {
      removeSeasonActivity(String(data.season_watch_record_id));
    }
    cacheCurrentSeasons(data.show_id);
  } catch (_error) {
    showSnackbar("Couldn't update this season. Try again.");
  } finally {
    pendingWatchChanges.delete(season);
  }
}

document.addEventListener("click", (event) => {
  const imageTrigger = event.target.closest("[data-full-image-src]");
  if (imageTrigger) {
    event.preventDefault();
    openImageViewer(imageTrigger);
    return;
  }

  if (event.target.closest("[data-image-viewer-close]")) {
    imageViewer?.close();
    return;
  }

  const snackbarActionButton = event.target.closest("[data-snackbar-action]");
  if (snackbarActionButton) {
    const action = snackbarAction;
    snackbar.hidden = true;
    snackbarAction = null;
    if (action) Promise.resolve(action()).catch((error) => showSnackbar(error.message));
    return;
  }

  const scheduleAction = event.target.closest("[data-schedule-action]");
  if (scheduleAction) {
    processScheduleEpisode(
      scheduleAction.closest("[data-schedule-card]"),
      scheduleAction.dataset.scheduleAction,
    );
    return;
  }

  const scheduleEpisodeOpen = event.target.closest("[data-schedule-episode-open]");
  if (scheduleEpisodeOpen) {
    detailParentView = currentView === "upcoming" ? "upcoming" : "backlog";
    openEpisode(scheduleEpisodeOpen.closest("[data-episode-id]").dataset.episodeId);
    return;
  }

  const importButton = event.target.closest("[data-import-state]");
  if (importButton) {
    importCatalogShow(
      importButton.closest("[data-tmdb-id]"),
      importButton.dataset.importState,
      importButton,
    );
    return;
  }

  const trackShowButton = event.target.closest("[data-track-show-state]");
  if (trackShowButton) {
    trackDetailShow(
      trackShowButton.closest("[data-detail-show]"),
      trackShowButton.dataset.trackShowState,
      trackShowButton,
    );
    return;
  }

  const catalogCardElement = event.target.closest(".popular-card[data-tmdb-id]");
  if (catalogCardElement && !event.target.closest("button")) {
    previewCatalogShow(catalogCardElement);
    return;
  }

  if (event.target.closest("[data-tv-search-retry]")) {
    const query = searchQueries.tv.trim();
    if (query) searchTvCatalog(query);
    return;
  }

  const watchLogEntry = event.target.closest("[data-watch-log-entry]");
  if (watchLogEntry) {
    openWatchDatePicker(watchLogEntry.closest("[data-watch-record-id]"));
    return;
  }

  const datePickerDay = event.target.closest("[data-date-picker-day]");
  if (datePickerDay) {
    datePickerSelectedDate = parseIsoDate(datePickerDay.dataset.datePickerDay);
    renderDatePicker();
    return;
  }

  if (event.target.closest("[data-date-picker-previous]")) {
    shiftDatePickerMonth(-1);
    return;
  }

  if (event.target.closest("[data-date-picker-next]")) {
    shiftDatePickerMonth(1);
    return;
  }

  if (event.target.closest("[data-date-picker-clear]")) {
    datePickerSelectedDate = null;
    renderDatePicker();
    return;
  }

  if (event.target.closest("[data-date-picker-cancel]")) {
    datePicker.close();
    return;
  }

  if (event.target.closest("[data-date-picker-save]")) {
    saveWatchDate();
    return;
  }

  const openFilterButton = event.target.closest("[data-open-library-filter]");
  if (openFilterButton) {
    openLibraryFilter(openFilterButton.dataset.openLibraryFilter);
    return;
  }

  const filterStateButton = event.target.closest("[data-filter-state]");
  if (filterStateButton && libraryFilterDraft) {
    const state = filterStateButton.dataset.filterState;
    if (libraryFilterDraft.states.has(state)) {
      if (libraryFilterDraft.states.size > 1) libraryFilterDraft.states.delete(state);
    } else {
      libraryFilterDraft.states.add(state);
    }
    syncLibraryFilterDialog();
    return;
  }

  const filterTagButton = event.target.closest("[data-filter-tag]");
  if (filterTagButton && libraryFilterDraft) {
    const tag = filterTagButton.dataset.filterTag;
    if (libraryFilterDraft.tags.has(tag)) libraryFilterDraft.tags.delete(tag);
    else libraryFilterDraft.tags.add(tag);
    syncLibraryFilterDialog();
    return;
  }

  const sortFieldButton = event.target.closest("[data-sort-field]");
  if (sortFieldButton && libraryFilterDraft) {
    libraryFilterDraft.sortField = sortFieldButton.dataset.sortField;
    syncLibraryFilterDialog();
    return;
  }

  const sortDirectionButton = event.target.closest("[data-sort-direction]");
  if (sortDirectionButton && libraryFilterDraft) {
    libraryFilterDraft.sortDirection = sortDirectionButton.dataset.sortDirection;
    syncLibraryFilterDialog();
    return;
  }

  if (event.target.closest("[data-library-filter-cancel]")) {
    libraryFilterDialog.close();
    return;
  }

  if (event.target.closest("[data-library-filter-apply]")) {
    applyLibraryFilterDraft();
    return;
  }

  const navButton = event.target.closest("[data-nav-view]");
  if (navButton) {
    closeShowMenus();
    closeWatchMenus();
    if (detailRequest) detailRequest.abort();
    showView(navButton.dataset.navView, "push");
    return;
  }

  const watchAction = event.target.closest("[data-watch-action]");
  if (watchAction) {
    if (watchAction.closest("summary")) event.preventDefault();
    const wrapper = watchAction.closest(".watch-control-wrap");
    const episode = wrapper.closest(".episode");
    const season = wrapper.closest(".season");
    closeWatchMenus();
    if (episode) changeEpisodeWatchCount(episode, watchAction.dataset.watchAction, watchAction);
    else changeSeasonWatchCount(season, watchAction.dataset.watchAction, watchAction);
    return;
  }

  const episodeControl = event.target.closest("[data-episode-watch]");
  if (episodeControl) {
    const episode = episodeControl.closest(".episode");
    if (Number(episode.dataset.watchCount) === 0) {
      changeEpisodeWatchCount(episode, "increment", episodeControl);
    } else {
      toggleWatchMenu(episodeControl);
    }
    return;
  }

  const seasonControl = event.target.closest("[data-season-watch]");
  if (seasonControl) {
    event.preventDefault();
    const season = seasonControl.closest(".season");
    if (Number(season.dataset.watchedCount) === 0) {
      changeSeasonWatchCount(season, "increment", seasonControl);
    } else {
      toggleWatchMenu(seasonControl);
    }
    return;
  }

  const menuButton = event.target.closest("[data-show-menu-button]");
  if (menuButton) {
    toggleShowMenu(menuButton);
    return;
  }

  const showAction = event.target.closest("[data-show-action]");
  if (showAction) {
    const showElement = showAction.closest("[data-show-id]");
    closeShowMenus();
    if (showAction.dataset.showAction === "move") {
      moveShow(showElement, showAction.dataset.targetState, showAction);
    } else if (showAction.dataset.showAction === "refresh") {
      refreshShowMetadata(showElement.dataset.showId, { force: true, trigger: showAction });
    } else {
      requestShowRemoval(showElement);
    }
    return;
  }

  if (event.target.closest("[data-cancel-remove]")) {
    removeDialog.close();
    pendingRemoveShowId = null;
    return;
  }

  if (event.target.closest("[data-confirm-remove]")) {
    confirmShowRemoval();
    return;
  }

  const detailBackButton = event.target.closest("[data-detail-back]");
  if (detailBackButton) {
    closeShowMenus();
    closeWatchMenus();
    if (detailRequest) detailRequest.abort();
    if (window.history.state?.trackApp && window.history.state.view === "detail") {
      window.history.back();
    } else if (detailBackButton.dataset.backShowId) {
      openShow(detailBackButton.dataset.backShowId, detailParentView, true, null);
    } else {
      showView(detailParentView);
    }
    return;
  }

  const retryButton = event.target.closest("[data-retry-show]");
  if (retryButton) {
    openShow(retryButton.dataset.retryShow, detailParentView, true, null);
    return;
  }

  const retrySeasonsButton = event.target.closest("[data-retry-seasons]");
  if (retrySeasonsButton) {
    const showId = retrySeasonsButton.dataset.retrySeasons;
    showSeasonsCache.delete(String(showId));
    const seasonList = retrySeasonsButton.closest("[data-season-list]");
    seasonList.innerHTML = `
      <div class="season-background-loading" data-season-loading aria-label="Loading seasons and episodes">
        <span class="skeleton-block skeleton-season"></span>
        <span class="skeleton-block skeleton-season"></span>
        <span class="skeleton-block skeleton-season"></span>
      </div>`;
    seasonList.setAttribute("aria-busy", "true");
    loadShowSeasons(showId, detailRequest.signal);
    return;
  }

  const retryEpisodeButton = event.target.closest("[data-retry-episode]");
  if (retryEpisodeButton) {
    openEpisode(retryEpisodeButton.dataset.retryEpisode, null);
    return;
  }

  const episodeShowLink = event.target.closest("[data-episode-show-open]");
  if (episodeShowLink) {
    openShow(episodeShowLink.dataset.showId, detailParentView);
    return;
  }

  const episodeOpenButton = event.target.closest("[data-open-episode]");
  if (episodeOpenButton) {
    openEpisode(episodeOpenButton.closest("[data-episode-id]").dataset.episodeId);
    return;
  }

  const showOpenButton = event.target.closest("[data-show-open]");
  if (showOpenButton) {
    const showCard = showOpenButton.closest("[data-show-id]");
    openShow(showCard.dataset.showId, "tv");
    return;
  }

  closeShowMenus();
  closeWatchMenus();
});

document.addEventListener("keydown", (event) => {
  const card = event.target.closest(".popular-card[data-tmdb-id]");
  if (!card || event.target.closest("button") || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  previewCatalogShow(card);
});

document.addEventListener("error", (event) => {
  if (event.target.matches?.("img[data-media-image]")) settleMediaImage(event.target, false);
}, true);

document.addEventListener("load", (event) => {
  if (event.target.matches?.("img[data-media-image]")) settleMediaImage(event.target, true);
}, true);

document.querySelectorAll("img[data-media-image]").forEach(inspectCompletedMediaImage);

new MutationObserver((mutations) => {
  mutations.forEach((mutation) => mutation.addedNodes.forEach(inspectMediaImages));
}).observe(document.documentElement, { childList: true, subtree: true });

document.addEventListener("submit", (event) => {
  if (event.target.matches("[data-view-search]")) event.preventDefault();
});

function updateProgress(progress, data) {
  if (!progress) return;
  progress.querySelector("[data-progress-copy]").textContent =
    `${data.watched_count} of ${data.episode_count}`;
  const bar = progress.querySelector(".progress-track");
  bar.setAttribute("aria-valuenow", data.percent);
  bar.querySelector("span").style.width = `${data.percent}%`;
}

function filterSchedule(viewName = currentView) {
  if (!["backlog", "upcoming"].includes(viewName)) return;
  const view = views.get(viewName);
  if (!view) return;
  const query = searchQueries[viewName].trim().toLocaleLowerCase();

  view.querySelectorAll("[data-schedule-panel]").forEach((panel) => {
    const cards = [...panel.querySelectorAll("[data-schedule-card]")];
    let visibleCount = 0;
    cards.forEach((card) => {
      const visible = !query || card.dataset.scheduleSearchText?.includes(query);
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    panel.querySelectorAll("[data-upcoming-month]").forEach((month) => {
      month.hidden = ![...month.querySelectorAll("[data-schedule-card]")]
        .some((card) => !card.hidden);
    });

    const empty = panel.querySelector("[data-schedule-empty]");
    const noResults = panel.querySelector("[data-schedule-no-results]");
    if (empty) empty.hidden = cards.length > 0;
    if (noResults) noResults.hidden = !query || visibleCount > 0 || cards.length === 0;
  });
}

function filterShowView(view) {
  if (!view) return;
  const preferences = libraryViewPreferences[view.dataset.view];
  if (!preferences) return;
  const query = searchQueries[view.dataset.view].trim().toLocaleLowerCase();
  const searching = view.dataset.view === "tv" && Boolean(query);
  view.querySelectorAll("[data-state-section]").forEach((section) => {
    const state = section.dataset.stateSection;
    const stateSelected = searching || preferences.states.has(state);
    const list = section.querySelector(".show-list");
    const cards = [...section.querySelectorAll(".show-card")];

    if (hydratedLibraryViews.has(view.dataset.view)) {
      cards.sort((first, second) => {
        const firstValue = first.dataset[preferences.sortField] || "";
        const secondValue = second.dataset[preferences.sortField] || "";
        const comparison = firstValue.localeCompare(secondValue, undefined, {
          numeric: true,
          sensitivity: "base",
        });
        if (comparison !== 0) {
          return preferences.sortDirection === "asc" ? comparison : -comparison;
        }
        return Number(first.dataset.showId) - Number(second.dataset.showId);
      });
      cards.forEach((card) => list.append(card));
    }

    let visibleCount = 0;
    cards.forEach((card) => {
      const matchesSearch = card.dataset.showName.includes(query);
      const matchesTags = searching || preferences.tags.size === 0
        || preferences.tags.has(card.dataset.progressState);
      const visible = stateSelected && matchesSearch && matchesTags;
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    section.hidden = searching ? visibleCount === 0 : !stateSelected;
    const count = section.querySelector("[data-state-count]");
    if (count) count.textContent = searching ? visibleCount : cards.length;
  });
  hydratedLibraryViews.add(view.dataset.view);
  if (view.dataset.view === "tv") syncTvSearchPresentation();
}

function filterAllShowViews() {
  filterShowView(views.get("tv"));
}

globalSearchInput?.addEventListener("input", () => {
  if (currentView === "detail") return;
  syncSearchChrome();
  syncSearchTextPosition();
  const query = globalSearchInput.value;
  searchQueries[currentView] = query;
  if (["backlog", "upcoming"].includes(currentView)) {
    filterSchedule(currentView);
  } else if (currentView === "tv") {
    filterShowView(views.get(currentView));
    clearTimeout(tvSearchTimer);
    if (tvSearchRequest) tvSearchRequest.abort();
    tvSearchPending = false;
    tvSearchComplete = false;
    tvSearchError = "";
    clearTvCatalogResults();
    if (query.trim()) {
      tvSearchTimer = setTimeout(() => searchTvCatalog(query.trim()), 350);
    } else {
      syncTvSearchPresentation();
    }
  }
});

searchClearButton?.addEventListener("click", () => {
  globalSearchInput.value = "";
  globalSearchInput.dispatchEvent(new Event("input", { bubbles: true }));
  globalSearchInput.focus();
});

searchBackButton?.addEventListener("click", () => {
  globalSearchInput.value = "";
  globalSearchInput.dispatchEvent(new Event("input", { bubbles: true }));
  globalSearchInput.blur();
});

window.addEventListener("resize", syncSearchTextPosition);
document.fonts?.ready.then(syncSearchTextPosition);

filterAllShowViews();
filterSchedule("backlog");
filterSchedule("upcoming");
formatDisplayDates(document);
syncGlobalSearch();

removeDialog?.addEventListener("close", () => {
  pendingRemoveShowId = null;
});

datePicker?.addEventListener("close", () => {
  datePickerTarget = null;
  datePickerSelectedDate = null;
});

libraryFilterDialog?.addEventListener("close", () => {
  globalSearchInput?.blur();
  libraryFilterView = null;
  libraryFilterDraft = null;
});

imageViewer?.addEventListener("click", (event) => {
  if (event.target === imageViewer) imageViewer.close();
});

imageViewer?.addEventListener("close", () => {
  imageViewerImage?.removeAttribute("src");
  imageViewerStage?.classList.remove("is-loaded", "has-error");
});

function restoreHistoryState(state) {
  if (!state?.trackApp) return;
  closeShowMenus();
  closeWatchMenus();
  if (detailRequest) detailRequest.abort();

  const legacyViews = { schedule: "backlog", watching: "tv", archive: "tv", discover: "tv" };
  const restoredView = legacyViews[state.view] || state.view;
  if (restoredView !== "detail") {
    showView(restoredView);
    return;
  }

  const restoredParent = legacyViews[state.parentView] || state.parentView;
  detailParentView = ["backlog", "upcoming", "tv"].includes(restoredParent)
    ? restoredParent
    : "backlog";
  if (state.detailType === "show" && state.showId) {
    openShow(state.showId, detailParentView, true, null);
  } else if (state.detailType === "episode" && state.episodeId) {
    openEpisode(state.episodeId, null);
  } else if (state.detailType === "catalog" && state.tmdbId) {
    const card = document.querySelector(`.popular-card[data-tmdb-id="${state.tmdbId}"]`);
    if (card) previewCatalogShow(card, null);
    else showView("tv");
  } else {
    showView(detailParentView);
  }
}

window.addEventListener("popstate", (event) => {
  restoreHistoryState(event.state);
});

if (window.history.state?.trackApp && window.history.state.view !== "backlog") {
  restoreHistoryState(window.history.state);
}

function showSnackbar(message, { actionLabel = "", onAction = null } = {}) {
  if (!snackbar || !actionLabel || !onAction) return;
  const copy = snackbar.querySelector("[data-snackbar-copy]");
  const actionButton = snackbar.querySelector("[data-snackbar-action]");
  copy.textContent = message;
  actionButton.textContent = actionLabel;
  actionButton.hidden = false;
  snackbarAction = onAction;
  snackbar.hidden = false;
  clearTimeout(showSnackbar.timer);
  showSnackbar.timer = setTimeout(() => {
    snackbar.hidden = true;
    snackbarAction = null;
  }, 5000);
}
