const views = new Map(
  [...document.querySelectorAll("[data-view]")].map((view) => [view.dataset.view, view]),
);

const TRACKING_STATE = Object.freeze({ ACTIVE: "ACTIVE", ARCHIVED: "ARCHIVED" });
const PROGRESS_STATE = Object.freeze({
  NEW: "not-started",
  STARTED: "started",
  CAUGHT_UP: "caught-up",
  FINISHED: "finished",
});

function progressPresentation(trackingState, watchedCount, episodeCount, seriesStatus) {
  if (watchedCount <= 0) return { state: PROGRESS_STATE.NEW, label: "New" };
  if (episodeCount > 0 && watchedCount >= episodeCount) {
    const terminalStatuses = new Set(["ended", "canceled", "cancelled"]);
    if (!terminalStatuses.has(String(seriesStatus || "").trim().toLocaleLowerCase())) {
      return { state: PROGRESS_STATE.CAUGHT_UP, label: "Caught up" };
    }
    return { state: PROGRESS_STATE.FINISHED, label: "Finished" };
  }
  return {
    state: PROGRESS_STATE.STARTED,
    label: trackingState === TRACKING_STATE.ARCHIVED ? "Stopped" : "Watching",
  };
}

let resolveAppShellReady;
const appShellReady = new Promise((resolve) => { resolveAppShellReady = resolve; });

async function revealAppWhenIconsAreReady() {
  if (document.fonts) {
    const iconFonts = Promise.all([
      document.fonts.load(
        '24px "Material Symbols Rounded"',
        "filter_list expand_more check_box arrow_upward arrow_downward more_vert resume event tv movie video_library done_all arrow_forward menu account_circle arrow_back close",
      ),
      document.fonts.load(
        '24px "Material Symbols Rounded Filled"',
        "resume event tv movie",
      ),
    ]);
    await Promise.race([
      iconFonts.catch(() => undefined),
      new Promise((resolve) => window.setTimeout(resolve, 4000)),
    ]);
  }
  window.requestAnimationFrame(() => {
    document.documentElement.classList.remove("app-booting");
    resolveAppShellReady();
  });
}

revealAppWhenIconsAreReady();
const navButtons = [...document.querySelectorAll("[data-nav-view]")];
const appContent = document.querySelector(".app-content");
const bottomChrome = document.querySelector(".bottom-chrome");
const globalSearchBar = document.querySelector("[data-global-search-bar]");
const globalSearchInput = document.querySelector("[data-global-search]");
const searchMenuButton = document.querySelector("[data-search-menu]");
const searchBackButton = document.querySelector("[data-search-back]");
const searchProfileButton = document.querySelector("[data-search-profile]");
const searchClearButton = document.querySelector("[data-clear-search]");
const tvViewToggle = document.querySelector("[data-tv-view-toggle]");
const searchTextMeasureContext = document.createElement("canvas").getContext("2d");
if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";
const scrollPositions = { backlog: 0, upcoming: 0, tv: 0, movies: 0, detail: 0, profile: 0 };
const removeDialog = document.querySelector("[data-remove-dialog]");
const finishedArchiveDialog = document.querySelector("[data-finished-archive-dialog]");
const datePicker = document.querySelector("[data-date-picker]");
const imageViewer = document.querySelector("[data-image-viewer]");
const imageViewerMedia = imageViewer?.querySelector("[data-image-viewer-media]");
const imageViewerPreview = imageViewer?.querySelector("[data-image-viewer-preview]");
const imageViewerImage = imageViewer?.querySelector("[data-image-viewer-image]");
const imageViewerStage = imageViewer?.querySelector("[data-image-viewer-stage]");
const menuScrim = document.querySelector("[data-menu-scrim]");
const tvControlBar = document.querySelector("[data-tv-control-bar]");
const menuIsolatedElements = new Set();
const floatingMenuAnimations = new WeakMap();
let menuScrollLockPosition = null;
const snackbar = document.querySelector(".snackbar");
const libraryViewPreferences = {
  backlog: {
    state: TRACKING_STATE.ACTIVE,
    progress: "",
    sortField: "lastWatched",
    sortDirection: "desc",
    mediaTypes: ["tv"],
  },
  upcoming: {
    state: TRACKING_STATE.ACTIVE,
    progress: "",
    sortField: "releaseDate",
    sortDirection: "asc",
    mediaTypes: ["tv", "archive"],
  },
  tv: {
    state: TRACKING_STATE.ACTIVE,
    progress: "",
    sortField: "name",
    sortDirection: "asc",
    layout: "list",
    mediaTypes: ["tv"],
  },
  movies: {
    state: TRACKING_STATE.ACTIVE,
    progress: "",
    sortField: "name",
    sortDirection: "asc",
    mediaTypes: ["movies"],
    layout: "list",
  },
};
const searchQueries = { backlog: "", upcoming: "", tv: "", movies: "" };
const librarySearchUpdates = { tv: false, movies: false };
restoreTvLayout();
const showDetailCache = new Map();
const movieDetailCache = new Map();
const showSeasonsCache = new Map();
const seasonEpisodesCache = new Map();
const seasonEpisodeRequests = new Map();
const seasonLoadTasks = new WeakMap();
const seasonEpisodePrefetchQueue = [];
const queuedSeasonEpisodePrefetches = new Set();
const seasonEpisodeHydrationTargets = new Map();
let activeSeasonEpisodePrefetches = 0;
let seasonEpisodeCacheGeneration = 0;
const episodeDetailCache = new Map();
const episodeDetailRequests = new Map();
const mediaImagePreloads = new Map();
const showRefreshRequests = new Map();
const pendingWatchChanges = new WeakSet();
const hydratedLibraryViews = new Set();
const revealedViewAnimations = new Set();
const tvRevealAnimationHandlers = new WeakMap();
const scheduleRevealAnimationHandlers = new WeakMap();
const detailRevealAnimationHandlers = new WeakMap();
let currentView = "backlog";
let detailParentView = "backlog";
let profileParentView = "backlog";
let diaryRevision = 0;
let renderedDiaryRevision = 0;
let diaryRequest = null;
let diaryPageRequest = null;
let diaryPageObserver = null;
let diaryPageAbortController = null;
let renderedStatisticsRevision = 0;
let statisticsRequest = null;
let detailRequest = null;
let pendingRemoveShowId = null;
let pendingRemoveMovieId = null;
let pendingFinishedArchiveShowId = null;
let datePickerTarget = null;
let datePickerSelectedDate = null;
let datePickerMonth = new Date();
let datePickerYearVisible = false;
let lastEpisodeDetailScrollY = 0;
let lastProfileScrollY = 0;
let profileChromeVisualOffset = 0;
let profileChromeHandoffClone = null;
let episodeNavigationPending = false;
let tvSearchTimer = null;
let tvSearchRequest = null;
let tvSearchPending = false;
let tvSearchComplete = false;
let tvSearchError = "";
let movieSearchTimer = null;
let movieSearchRequest = null;
let movieSearchPending = false;
let movieSearchComplete = false;
let movieSearchError = "";
let tvLayoutTransitionTimer = null;
let tvDropdownHistoryActive = false;
let snackbarAction = null;
let backgroundPrimaryViewHydrationStarted = false;
let scheduleViewsHydrated = false;
let scheduleCalendarDate = toIsoDate(new Date());
let imageViewerAspectRatio = null;
let imageViewerClosing = false;
if (!window.history.state?.trackApp) {
  window.history.replaceState({ trackApp: true, view: "backlog" }, "");
}

function writeHistory(state, mode = "push") {
  const method = mode === "replace" ? "replaceState" : "pushState";
  window.history[method]({ trackApp: true, ...state }, "");
}

function sizeImageViewerLayers() {
  if (!imageViewerStage || !imageViewerAspectRatio) return;
  const availableWidth = imageViewerStage.clientWidth;
  const availableHeight = imageViewerStage.clientHeight;
  if (!availableWidth || !availableHeight) return;

  let width = availableWidth;
  let height = width / imageViewerAspectRatio;
  if (height > availableHeight) {
    height = availableHeight;
    width = height * imageViewerAspectRatio;
  }
  imageViewerStage.style.setProperty("--image-viewer-width", `${width}px`);
  imageViewerStage.style.setProperty("--image-viewer-height", `${height}px`);
}

function clearImageViewerMotion() {
  imageViewerMedia?.getAnimations().forEach((animation) => animation.cancel());
}

function openImageViewer(trigger) {
  if (!imageViewer || !imageViewerMedia || !imageViewerPreview || !imageViewerImage || !imageViewerStage) return;
  clearImageViewerMotion();
  const currentImage = trigger.querySelector("img[data-media-image]");
  const previewSource = currentImage?.currentSrc || currentImage?.src || "";
  const currentBounds = currentImage?.getBoundingClientRect();
  imageViewerAspectRatio = currentImage?.naturalWidth && currentImage?.naturalHeight
    ? currentImage.naturalWidth / currentImage.naturalHeight
    : currentBounds?.width && currentBounds?.height
      ? currentBounds.width / currentBounds.height
      : null;
  imageViewerStage.setAttribute("aria-busy", "true");
  imageViewerStage.classList.remove("is-loaded", "has-error", "has-preview");
  imageViewerPreview.toggleAttribute("hidden", !previewSource);
  if (previewSource) {
    imageViewerPreview.src = previewSource;
    imageViewerStage.classList.add("has-preview");
  } else {
    imageViewerPreview.removeAttribute("src");
  }
  imageViewerImage.alt = trigger.dataset.fullImageAlt || "Large image";
  imageViewerClosing = false;
  imageViewer.classList.remove("is-closing");
  imageViewer.classList.add("is-opening");
  document.documentElement.classList.add("image-viewer-open");
  imageViewer.showModal();
  sizeImageViewerLayers();
  if (currentBounds?.width && currentBounds?.height
    && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const targetBounds = imageViewerMedia.getBoundingClientRect();
    const translateX = currentBounds.left + (currentBounds.width / 2)
      - targetBounds.left - (targetBounds.width / 2);
    const translateY = currentBounds.top + (currentBounds.height / 2)
      - targetBounds.top - (targetBounds.height / 2);
    imageViewerMedia.animate(
      [
        {
          transform: `translate(${translateX}px, ${translateY}px) scale(${currentBounds.width / targetBounds.width}, ${currentBounds.height / targetBounds.height})`,
        },
        { transform: "translate(0, 0) scale(1, 1)" },
      ],
      { duration: 240, easing: "cubic-bezier(0.2, 0, 0, 1)" },
    );
  }
  imageViewerImage.src = trigger.dataset.fullImageSrc;
}

function closeImageViewer() {
  if (!imageViewer?.open || imageViewerClosing) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    imageViewer.close();
    return;
  }
  imageViewerClosing = true;
  imageViewer.classList.remove("is-opening");
  imageViewer.classList.add("is-closing");
  const finishClose = (event) => {
    if (event.target !== imageViewer || event.animationName !== "image-viewer-exit") return;
    imageViewer.removeEventListener("animationend", finishClose);
    imageViewer.close();
  };
  imageViewer.addEventListener("animationend", finishClose);
}

imageViewerImage?.addEventListener("load", async () => {
  const loadedSource = imageViewerImage.currentSrc;
  try {
    await imageViewerImage.decode();
  } catch (_error) {
    // A completed load can still be painted when explicit decoding is unavailable.
  }
  window.requestAnimationFrame(() => {
    if (!imageViewer?.open || imageViewerImage.currentSrc !== loadedSource) return;
    imageViewerStage?.classList.add("is-loaded");
    imageViewerStage?.removeAttribute("aria-busy");
  });
});

imageViewerImage?.addEventListener("error", () => {
  imageViewerStage?.classList.add("has-error");
  imageViewerStage?.removeAttribute("aria-busy");
});

imageViewerImage?.addEventListener("transitionend", (event) => {
  if (event.propertyName !== "opacity" || !imageViewerStage?.classList.contains("is-loaded")) return;
  imageViewerPreview?.setAttribute("hidden", "");
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
  const hasDedicatedAppBar = ["detail", "profile"].includes(currentView);
  globalSearchBar.hidden = hasDedicatedAppBar;
  if (hasDedicatedAppBar) return;

  const settings = {
    backlog: { placeholder: "Search queue", label: "Search queue episodes" },
    upcoming: { placeholder: "Search upcoming", label: "Search upcoming episodes" },
    tv: { placeholder: "Search TV", label: "Search TV shows" },
    movies: { placeholder: "Search movies", label: "Search movies" },
  }[currentView];
  if (!settings) return;
  globalSearchInput.placeholder = settings.placeholder;
  globalSearchInput.setAttribute("aria-label", settings.label);
  globalSearchInput.value = searchQueries[currentView];
  syncTvLayout();
  syncSearchChrome();
  syncSearchTextPosition();
}

function syncTvLayout() {
  ["tv", "movies"].forEach((name) => {
    const view = views.get(name);
    if (view) view.dataset.tvLayout = libraryViewPreferences[name].layout === "compact" ? "compact" : "list";
  });
  const isCompact = libraryViewPreferences[currentView]?.layout === "compact";
  if (!tvViewToggle) return;
  const visible = ["tv", "movies"].includes(currentView);
  tvViewToggle.hidden = !visible;
  tvViewToggle.setAttribute("aria-pressed", String(isCompact));
  tvViewToggle.setAttribute("aria-label", isCompact
    ? "Switch to list view"
    : "Switch to compact poster view");
  tvViewToggle.querySelector(".material-symbols-rounded").textContent = isCompact
    ? "view_list"
    : "grid_view";
}

function restoreTvLayout() {
  try {
    if (window.localStorage.getItem("track.tv-layout") === "compact") {
      libraryViewPreferences.tv.layout = "compact";
    }
    if (window.localStorage.getItem("track.movies-layout") === "compact") {
      libraryViewPreferences.movies.layout = "compact";
    }
  } catch (_error) {
    // Storage can be unavailable in private browsing contexts.
  }
}

function toggleTvLayout() {
  if (tvLayoutTransitionTimer) return;
  const preferences = libraryViewPreferences[currentView];
  const tvView = views.get(currentView);
  const applyLayout = () => {
    preferences.layout = preferences.layout === "compact" ? "list" : "compact";
    try {
      window.localStorage.setItem(`track.${currentView}-layout`, preferences.layout);
    } catch (_error) {
      // The selected layout remains active for the current session.
    }
    tvView?.classList.add("is-restarting-layout");
    tvView?.classList.remove("is-switching-layout");
    tvLayoutTransitionTimer = null;
    syncTvLayout();
    window.requestAnimationFrame(() => {
      clearTvFirstReveal(tvView);
      // Let the browser commit the cleared animation state before replaying it.
      window.requestAnimationFrame(() => {
        tvView?.classList.remove("is-restarting-layout");
        staggerTvFirstReveal(tvView);
      });
    });
  };

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    applyLayout();
    return;
  }
  tvView?.classList.add("is-switching-layout");
  tvLayoutTransitionTimer = window.setTimeout(applyLayout, 75);
}

function selectProfileTab(tabName, { focus = false } = {}) {
  const profileView = views.get("profile");
  const selectedTabs = profileView?.querySelectorAll(`[data-profile-tab="${tabName}"]`);
  const selectedTab = selectedTabs?.[0];
  if (!profileView || !selectedTab) return;
  const retainDiaryPosition = tabName === "diary" && window.scrollY > 0;
  document.querySelectorAll("[data-profile-tab]").forEach((tab) => {
    const selected = tab.dataset.profileTab === tabName;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  profileView.querySelectorAll("[data-profile-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.profilePanel !== tabName;
  });
  if (tabName === "statistics" && renderedStatisticsRevision !== diaryRevision) {
    refreshStatisticsContent();
  }
  if (retainDiaryPosition) {
    const chrome = profileView.querySelector(".profile-top-app-bar");
    spawnProfileChromeHandoff(chrome);
    lastProfileScrollY = window.scrollY;
  } else {
    scrollPositions.profile = 0;
    resetProfileChromePosition();
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  if (focus) selectedTab.focus();
}

async function refreshDiaryContent() {
  if (diaryRequest) return diaryRequest;
  const panel = views.get("profile")?.querySelector('[data-profile-panel="diary"]');
  if (!panel) return undefined;
  const requestedRevision = diaryRevision;
  panel.setAttribute("aria-busy", "true");
  diaryRequest = (async () => {
    const response = await fetch("/api/profile/diary", {
      headers: { "X-Requested-With": "Track" },
    });
    if (!response.ok) throw new Error("Could not refresh diary");
    panel.innerHTML = await response.text();
    renderedDiaryRevision = requestedRevision;
    initializeDiaryPagination();
  })().catch(() => undefined).finally(() => {
    panel.removeAttribute("aria-busy");
    diaryRequest = null;
  });
  return diaryRequest;
}

function disconnectDiaryPagination() {
  diaryPageObserver?.disconnect();
  diaryPageAbortController?.abort();
  diaryPageObserver = null;
  diaryPageRequest = null;
  diaryPageAbortController = null;
}

function mergeDiaryPage(content, fragment) {
  const timeline = content.querySelector(".schedule-timeline");
  const trigger = fragment.querySelector("[data-diary-page-trigger]");
  const incomingMonths = [...fragment.querySelectorAll("[data-diary-month]")];
  if (!timeline || !trigger) return;

  let triggerPlaced = false;
  incomingMonths.forEach((month) => {
    const existingMonth = [...timeline.querySelectorAll("[data-diary-month]")]
      .find((candidate) => candidate.dataset.diaryMonth === month.dataset.diaryMonth);
    if (existingMonth) {
      const list = existingMonth.querySelector(".schedule-timeline-list");
      if (!triggerPlaced) {
        list.append(trigger);
        triggerPlaced = true;
      }
      month.querySelectorAll("[data-schedule-card]").forEach((card) => list.append(card));
      return;
    }
    if (!triggerPlaced) {
      timeline.append(trigger);
      triggerPlaced = true;
    }
    timeline.append(month);
  });
  if (!triggerPlaced) timeline.append(trigger);

  content.dataset.diaryPage = fragment.dataset.diaryPage;
  content.dataset.diaryHasMore = fragment.dataset.diaryHasMore;
}

async function loadNextDiaryPage(triggerPage) {
  const content = views.get("profile")?.querySelector("[data-diary-content]");
  if (!content || content.dataset.diaryHasMore !== "true" || diaryPageRequest) return;
  if (Number(content.dataset.diaryPage) !== triggerPage) return;

  const controller = new AbortController();
  diaryPageAbortController = controller;
  diaryPageRequest = (async () => {
    const response = await fetch(`/api/profile/diary?page=${triggerPage + 1}`, {
      headers: { "X-Requested-With": "Track" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("Could not load more diary entries");
    const template = document.createElement("template");
    template.innerHTML = (await response.text()).trim();
    const fragment = template.content.querySelector("[data-diary-page-fragment]");
    if (fragment) mergeDiaryPage(content, fragment);
  })().catch((error) => {
    if (error.name === "AbortError") return;
    const trigger = content.querySelector(`[data-diary-page-trigger="${triggerPage}"]`);
    if (trigger) window.setTimeout(() => observeDiaryPageTrigger(trigger), 1000);
  }).finally(() => {
    if (diaryPageAbortController !== controller) return;
    diaryPageRequest = null;
    diaryPageAbortController = null;
    if (content.dataset.diaryHasMore === "true") {
      observeDiaryPageTrigger(
        content.querySelector(`[data-diary-page-trigger="${content.dataset.diaryPage}"]`),
      );
    }
  });
  return diaryPageRequest;
}

function observeDiaryPageTrigger(trigger) {
  if (!diaryPageObserver || !trigger || trigger.dataset.diaryObserved === "true") return;
  trigger.dataset.diaryObserved = "true";
  diaryPageObserver.observe(trigger);
}

function initializeDiaryPagination() {
  disconnectDiaryPagination();
  const content = views.get("profile")?.querySelector("[data-diary-content]");
  if (!content || content.dataset.diaryHasMore !== "true") return;
  diaryPageObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const trigger = entry.target;
      diaryPageObserver.unobserve(trigger);
      trigger.dataset.diaryObserved = "false";
      loadNextDiaryPage(Number(trigger.dataset.diaryPageTrigger));
    });
  });
  observeDiaryPageTrigger(content.querySelector("[data-diary-page-trigger]"));
}

async function refreshStatisticsContent() {
  if (statisticsRequest) return statisticsRequest;
  const panel = views.get("profile")?.querySelector('[data-profile-panel="statistics"]');
  if (!panel) return undefined;
  const requestedRevision = diaryRevision;
  panel.setAttribute("aria-busy", "true");
  statisticsRequest = (async () => {
    const response = await fetch("/api/profile/statistics", {
      headers: scheduleRequestHeaders({ "X-Requested-With": "Track" }),
    });
    if (!response.ok) throw new Error("Could not refresh statistics");
    panel.innerHTML = await response.text();
    renderedStatisticsRevision = requestedRevision;
  })().catch(() => undefined).finally(() => {
    panel.removeAttribute("aria-busy");
    statisticsRequest = null;
  });
  return statisticsRequest;
}

function transitionProfileView(change, direction) {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!document.startViewTransition || reduceMotion) {
    change();
    return Promise.resolve();
  }

  const root = document.documentElement;
  root.classList.add(`profile-transition-${direction}`);
  const transition = document.startViewTransition(change);
  return transition.finished.catch(() => undefined).finally(() => {
    root.classList.remove(`profile-transition-${direction}`);
  });
}

function resetProfileChromePosition() {
  const chrome = views.get("profile")?.querySelector(".profile-top-app-bar");
  profileChromeHandoffClone?.remove();
  profileChromeHandoffClone = null;
  profileChromeVisualOffset = 0;
  lastProfileScrollY = window.scrollY;
  chrome?.style.removeProperty("transform");
}

function spawnProfileChromeHandoff(chrome) {
  if (profileChromeHandoffClone) return;
  const clone = chrome.cloneNode(true);
  clone.classList.add("profile-chrome-handoff-clone");
  clone.style.removeProperty("transform");
  clone.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
  document.body.append(clone);
  profileChromeHandoffClone = clone;
  profileChromeVisualOffset = 0;
  chrome.style.removeProperty("transform");
}

function keepProfileChromeAtViewportEdge() {
  const chrome = views.get("profile")?.querySelector(".profile-top-app-bar");
  const currentScrollY = window.scrollY;
  if (!chrome || currentView !== "profile") {
    lastProfileScrollY = currentScrollY;
    return;
  }

  const observedDirection = currentScrollY > lastProfileScrollY ? "down"
    : currentScrollY < lastProfileScrollY ? "up"
      : null;
  const direction = observedDirection;
  const upwardDistance = direction === "up" ? lastProfileScrollY - currentScrollY : 0;
  if (profileChromeHandoffClone) {
    if (direction === "down") {
      const top = chrome.getBoundingClientRect().top;
      profileChromeVisualOffset = -top;
      chrome.style.transform = `translateY(${profileChromeVisualOffset}px)`;
      profileChromeHandoffClone.remove();
      profileChromeHandoffClone = null;
    }
    lastProfileScrollY = currentScrollY;
    return;
  }

  if (direction === "up") {
    const bottom = chrome.getBoundingClientRect().bottom;
    if (bottom < 0) {
      profileChromeVisualOffset -= bottom;
      chrome.style.transform = `translateY(${profileChromeVisualOffset}px)`;
    }
    // Mobile browsers can apply an inertial scroll step before dispatching the
    // next scroll event. Predict one additional upward step—not a whole
    // header—so the clone is ready for a fast crossing without appearing as
    // soon as the original begins to re-enter.
    const handoffBuffer = upwardDistance * 2;
    if (chrome.getBoundingClientRect().top >= -handoffBuffer) {
      spawnProfileChromeHandoff(chrome);
    }
  }
  lastProfileScrollY = currentScrollY;
}

function openProfileFromTrigger(_trigger) {
  profileParentView = ["backlog", "upcoming", "tv"].includes(currentView)
    ? currentView
    : "backlog";
  scrollPositions.profile = 0;
  transitionProfileView(() => showView("profile", "push"), "enter");
}

function leaveProfile() {
  if (window.history.state?.trackApp && window.history.state.view === "profile") {
    window.history.back();
  } else {
    transitionProfileView(() => showView(profileParentView), "return");
  }
}

function showView(viewName, historyMode = null) {
  if (!views.has(viewName) || viewName === currentView) return;

  if (currentView === "backlog" && viewName !== "backlog") {
    clearCaughtUpScheduleItems();
  }
  if (["backlog", "upcoming"].includes(currentView) && viewName !== currentView) {
    clearScheduleFirstReveal(views.get(currentView));
  }
  if (currentView === "tv" && viewName !== "tv") {
    clearTvFirstReveal(views.get("tv"));
  }
  const firstScheduleReveal = ["backlog", "upcoming"].includes(viewName)
    && !revealedViewAnimations.has(viewName);
  const firstTvReveal = viewName === "tv"
    && !revealedViewAnimations.has(`tv:${libraryViewPreferences.tv.state}`);
  const firstScheduleDataReady = firstScheduleReveal && scheduleViewsHydrated;
  const targetScrollY = scrollPositions[viewName] || 0;
  if (firstScheduleReveal) {
    revealedViewAnimations.add(viewName);
    if (!firstScheduleDataReady) {
      views.get(viewName).classList.add("schedule-first-reveal-pending");
    }
  }
  scrollPositions[currentView] = window.scrollY;
  views.forEach((view, name) => {
    const active = name === viewName;
    view.hidden = !active;
    view.classList.toggle("is-active", active);
  });

  // Restore the destination's scroll position before its sticky chrome becomes
  // visible. Otherwise a returning Profile view can briefly reveal the global
  // app bar at the Profile scroll offset, then shift it into place.
  window.scrollTo({ top: targetScrollY, behavior: "auto" });

  updateActiveNav(viewName === "detail"
    ? (detailParentView === "profile" ? profileParentView : detailParentView)
    : viewName === "profile" ? profileParentView
      : viewName);
  currentView = viewName;
  const profileOpen = viewName === "profile";
  if (bottomChrome) bottomChrome.hidden = profileOpen;
  appContent?.classList.toggle("is-profile-view", profileOpen);
  if (profileOpen) resetProfileChromePosition();
  else resetProfileChromePosition();
  syncGlobalSearch();
  syncTvControlVisibility();
  if (viewName === "tv") {
    window.requestAnimationFrame(() => {
      revealTvStateOnce(views.get("tv"));
      if (!firstTvReveal) return;
      window.requestAnimationFrame(() => {
        if (currentView !== "tv") return;
        scrollPositions.tv = 0;
        window.scrollTo({ top: 0, behavior: "auto" });
      });
    });
  }
  if (viewName === "profile" && renderedDiaryRevision !== diaryRevision) {
    refreshDiaryContent();
  }
  if (viewName === "profile"
    && views.get("profile")?.querySelector('[data-profile-tab="statistics"]')
      ?.getAttribute("aria-selected") === "true"
    && renderedStatisticsRevision !== diaryRevision) {
    refreshStatisticsContent();
  }
  const titles = {
    backlog: "Queue · Track",
    upcoming: "Upcoming · Track",
    tv: "TV · Track",
    movies: "Movies · Track",
    detail: "Track",
    profile: "Profile · Track",
  };
  document.title = titles[viewName] || "Track";
  if (["backlog", "upcoming"].includes(viewName)) {
    if (firstScheduleDataReady) {
      staggerScheduleFirstReveal(views.get(viewName));
    } else {
      const scheduleRefresh = refreshScheduleContent().catch(() => undefined);
      if (firstScheduleReveal) {
        scheduleRefresh.finally(() => {
          if (currentView === viewName) staggerScheduleFirstReveal(views.get(viewName));
          else clearScheduleFirstReveal(views.get(viewName));
        });
      }
    }
  }
  if (historyMode && viewName !== "detail") {
    const state = viewName === "profile"
      ? { view: viewName, parentView: profileParentView }
      : { view: viewName };
    writeHistory(state, historyMode);
  }
}

function catalogCard(show) {
  const article = document.createElement("article");
  article.className = "popular-card";
  article.dataset.tmdbId = show.tmdb_id;
  article.dataset.catalogType = currentView;
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

function settleMediaImage(image, loaded, reveal = false) {
  const container = image.closest(".has-media-image");
  if (!container) return;
  if (loaded) {
    if (reveal && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      image.classList.add("media-image-reveal");
      image.addEventListener("animationend", () => {
        image.classList.remove("media-image-reveal");
      }, { once: true });
    }
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
  if (!image.complete) {
    image.dataset.mediaImagePending = "";
    return;
  }
  settleMediaImage(image, image.naturalWidth > 0);
}

function inspectMediaImages(root) {
  if (root.matches?.("img[data-media-image]")) inspectCompletedMediaImage(root);
  root.querySelectorAll?.("img[data-media-image]").forEach(inspectCompletedMediaImage);
}

function catalogActions() {
  const actions = document.createElement("div");
  actions.className = "popular-card-actions";
  [[TRACKING_STATE.ACTIVE, "Add"], [TRACKING_STATE.ARCHIVED, "Archive"]]
    .forEach(([state, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "catalog-action";
      if (state === TRACKING_STATE.ARCHIVED) button.classList.add("catalog-action-secondary");
      button.dataset.importState = state;
      button.textContent = label;
      actions.append(button);
    });
  return actions;
}

function markCatalogTracked(card, state, recordId = null) {
  card.classList.add("is-cached");
  if (recordId) {
    if (card.dataset.catalogType === "movies") card.dataset.movieId = recordId;
    else card.dataset.showId = recordId;
  }
  const icon = document.createElement("span");
  icon.className = "catalog-tracked-icon material-symbols-rounded";
  icon.textContent = state === TRACKING_STATE.ARCHIVED ? "archive" : "check_circle";
  icon.title = state === TRACKING_STATE.ARCHIVED ? "Archived" : "Added";
  card.querySelector(".popular-card-actions")?.replaceChildren(icon);
  if (card.dataset.catalogType in librarySearchUpdates) {
    librarySearchUpdates[card.dataset.catalogType] = true;
  }
}

function syncTvSearchPresentation() {
  const view = views.get("tv");
  if (!view) return;
  const query = searchQueries.tv.trim();
  const addSection = view.querySelector("[data-tv-add-section]");
  const addResults = view.querySelector("[data-tv-add-results]");
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

  addSection.hidden = addCount === 0;
  addResults.hidden = false;
  credit.hidden = addCount === 0;
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
  const cards = available.map(catalogCard);
  views.get("tv").querySelector("[data-tv-add-results]").replaceChildren(...cards);
  staggerTvSlices(cards);
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
    if (card.dataset.catalogType === "movies") {
      const response = await fetch(`/api/movies/${card.dataset.tmdbId}/import`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not add movie");
      markCatalogTracked(card, state, String(data.movie_id));
      return;
    }
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
    markCatalogTracked(card, state, String(data.show_id));
    syncTvSearchPresentation();
  } catch (error) {
    actions.forEach((button) => { button.disabled = false; });
    showSnackbar(error.message);
  }
}

function syncMovieSearchPresentation() {
  const view = views.get("movies");
  if (!view) return;
  const section = view.querySelector("[data-movie-add-section]");
  const results = view.querySelector("[data-movie-add-results]");
  const empty = view.querySelector("[data-movie-search-empty]");
  const error = view.querySelector("[data-movie-search-error]");
  const query = searchQueries.movies.trim();
  const addCount = results?.querySelectorAll(".popular-card").length || 0;
  const localCount = [...view.querySelectorAll("[data-state-section] .show-card")]
    .filter((card) => !card.hidden).length;

  if (!query) {
    if (section) section.hidden = true;
    if (empty) empty.hidden = true;
    if (error) error.hidden = true;
    return;
  }
  if (section) section.hidden = addCount === 0;
  if (results) results.hidden = false;
  if (error) {
    error.hidden = !movieSearchError;
    if (movieSearchError) error.querySelector("[data-movie-search-error-copy]").textContent = movieSearchError;
  }
  if (empty) empty.hidden = movieSearchPending
    || !movieSearchComplete
    || Boolean(movieSearchError)
    || localCount + addCount > 0;
}

async function searchMovieCatalog(query) {
  movieSearchRequest?.abort();
  movieSearchRequest = new AbortController();
  movieSearchPending = true;
  movieSearchComplete = false;
  movieSearchError = "";
  const results = views.get("movies")?.querySelector("[data-movie-add-results]");
  results?.replaceChildren();
  syncMovieSearchPresentation();
  try {
    const response = await fetch(`/api/movies/search?q=${encodeURIComponent(query)}`, { signal: movieSearchRequest.signal });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not search TMDB");
    if (searchQueries.movies.trim() !== query) return;
    movieSearchPending = false;
    movieSearchComplete = true;
    const cards = data.results.map(catalogCard);
    results?.replaceChildren(...cards);
    staggerTvSlices(cards);
  } catch (error) {
    if (error.name === "AbortError") return;
    movieSearchPending = false;
    movieSearchComplete = true;
    movieSearchError = error.message;
  }
  syncMovieSearchPresentation();
}

async function refreshMoviesContent() {
  const response = await fetch("/api/movies", { headers: { "X-Requested-With": "Track" } });
  if (!response.ok) throw new Error("Could not refresh movies");
  const template = document.createElement("template");
  template.innerHTML = (await response.text()).trim();
  views.get("movies")?.replaceChildren(template.content);
  filterShowView(views.get("movies"));
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
    document.querySelectorAll(`.popular-card[data-tmdb-id="${showElement.dataset.tmdbId}"]`)
      .forEach((card) => markCatalogTracked(card, state, String(data.show_id)));
    syncTvSearchPresentation();
    openShow(data.show_id, "tv", true, "replace");
  } catch (error) {
    trigger.disabled = false;
    showSnackbar(error.message);
  }
}

function renderDetailLoading(title) {
  const detailView = views.get("detail");
  const template = document.querySelector("#detail-loading-template");
  detailView.replaceChildren(template.content.cloneNode(true));
  detailView.querySelector("[data-detail-loading-title]").textContent = title;
  const loadingLabel = `Loading ${title.toLowerCase()}`;
  const loading = detailView.querySelector(".detail-loading");
  loading.setAttribute("aria-label", loadingLabel);
  loading.querySelector("[data-detail-loading-label]").textContent = loadingLabel;
}

function staggerDetailSlices(sections, startIndex = 0) {
  sections.filter(Boolean).forEach((section, index) => {
    section.classList.add("detail-slice-reveal");
    section.style.setProperty("--detail-slice-delay", `${(startIndex + index) * 25}ms`);
    const finishReveal = (event) => {
      if (event.target !== section || event.animationName !== "detail-slice-reveal") return;
      section.classList.remove("detail-slice-reveal");
      section.style.removeProperty("--detail-slice-delay");
      section.removeEventListener("animationend", finishReveal);
      detailRevealAnimationHandlers.delete(section);
    };
    detailRevealAnimationHandlers.set(section, finishReveal);
    section.addEventListener("animationend", finishReveal);
  });
}

function clearDetailSliceReveals(root) {
  root?.querySelectorAll(".detail-slice-reveal").forEach((section) => {
    const finishReveal = detailRevealAnimationHandlers.get(section);
    if (finishReveal) section.removeEventListener("animationend", finishReveal);
    detailRevealAnimationHandlers.delete(section);
    section.classList.remove("detail-slice-reveal");
    section.style.removeProperty("--detail-slice-delay");
  });
}

function staggerTvSlices(slices) {
  const tvSliceStaggerMs = 55;
  const tvLayoutStaggerMs = libraryViewPreferences.tv.layout === "compact"
    ? tvSliceStaggerMs / 2
    : tvSliceStaggerMs;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  slices.filter(Boolean).forEach((slice, index) => {
    slice.classList.add("tv-slice-reveal");
    slice.style.setProperty("--detail-slice-delay", `${index * tvLayoutStaggerMs}ms`);
    const finishReveal = (event) => {
      if (event.target !== slice || event.animationName !== "detail-slice-reveal") return;
      slice.classList.remove("tv-slice-reveal");
      slice.style.removeProperty("--detail-slice-delay");
      slice.removeEventListener("animationend", finishReveal);
      tvRevealAnimationHandlers.delete(slice);
    };
    tvRevealAnimationHandlers.set(slice, finishReveal);
    slice.addEventListener("animationend", finishReveal);
  });
}

function staggerTvFirstReveal(view) {
  const slices = [];
  view.querySelectorAll(":scope > .page-section:not([hidden])").forEach((section) => {
    slices.push(section.querySelector(":scope > .section-heading"));
    slices.push(...section.querySelectorAll(":scope > .show-list > .show-card:not([hidden])"));
    slices.push(...section.querySelectorAll(":scope > .popular-grid > .popular-card:not([hidden])"));
    slices.push(...section.querySelectorAll(":scope > .empty-state:not([hidden])"));
  });
  slices.push(...view.querySelectorAll(":scope > .empty-state:not([hidden])"));
  staggerTvSlices(slices);
  hydrateOtherPrimaryViews("tv");
}

function revealTvStateOnce(view) {
  if (!view || currentView !== "tv" || searchQueries.tv.trim()) return;
  const state = libraryViewPreferences.tv.state;
  const revealKey = `tv:${state}`;
  if (revealedViewAnimations.has(revealKey)) return;
  revealedViewAnimations.add(revealKey);
  staggerTvFirstReveal(view);
}

function clearTvFirstReveal(view) {
  view.querySelectorAll(".tv-slice-reveal").forEach((slice) => {
    const finishReveal = tvRevealAnimationHandlers.get(slice);
    if (finishReveal) slice.removeEventListener("animationend", finishReveal);
    tvRevealAnimationHandlers.delete(slice);
    slice.classList.remove("tv-slice-reveal");
    slice.style.removeProperty("--detail-slice-delay");
  });
}

function staggerScheduleFirstReveal(view) {
  const scheduleItemStaggerMs = 65;
  clearScheduleFirstReveal(view);
  const items = [...view.querySelectorAll("[data-schedule-card]:not([hidden])")];
  const emptyState = view.querySelector(
    "[data-schedule-empty]:not([hidden]), [data-schedule-no-results]:not([hidden])",
  );
  hydrateOtherPrimaryViews(view.dataset.view);

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (!items.length) {
    if (emptyState) {
      emptyState.classList.add("schedule-empty-reveal");
      const finishEmptyReveal = (event) => {
        if (event.target !== emptyState || event.animationName !== "schedule-item-reveal") return;
        emptyState.classList.remove("schedule-empty-reveal");
        emptyState.removeEventListener("animationend", finishEmptyReveal);
        scheduleRevealAnimationHandlers.delete(emptyState);
      };
      scheduleRevealAnimationHandlers.set(emptyState, finishEmptyReveal);
      emptyState.addEventListener("animationend", finishEmptyReveal);
    }
    return;
  }

  view.classList.add("schedule-rail-reveal");
  const finishRailReveal = (event) => {
    if (event.animationName !== "schedule-rail-reveal") return;
    view.classList.remove("schedule-rail-reveal");
    view.removeEventListener("animationend", finishRailReveal);
    scheduleRevealAnimationHandlers.delete(view);
  };
  scheduleRevealAnimationHandlers.set(view, finishRailReveal);
  view.addEventListener("animationend", finishRailReveal);

  items.forEach((item, index) => {
    item.classList.add("schedule-item-reveal");
    item.style.setProperty("--schedule-item-delay", `${index * scheduleItemStaggerMs}ms`);
    const content = item.querySelector(".schedule-timeline-content");
    const finishItemReveal = (event) => {
      if (event.target !== content || event.animationName !== "schedule-item-reveal") return;
      item.classList.remove("schedule-item-reveal");
      item.style.removeProperty("--schedule-item-delay");
      item.removeEventListener("animationend", finishItemReveal);
      scheduleRevealAnimationHandlers.delete(item);
    };
    scheduleRevealAnimationHandlers.set(item, finishItemReveal);
    item.addEventListener("animationend", finishItemReveal);
  });
}

function clearScheduleFirstReveal(view) {
  if (!view) return;
  const finishRailReveal = scheduleRevealAnimationHandlers.get(view);
  if (finishRailReveal) view.removeEventListener("animationend", finishRailReveal);
  scheduleRevealAnimationHandlers.delete(view);
  view.classList.remove("schedule-first-reveal-pending", "schedule-rail-reveal");
  view.querySelectorAll(".schedule-item-reveal, .schedule-empty-reveal").forEach((slice) => {
    const finishReveal = scheduleRevealAnimationHandlers.get(slice);
    if (finishReveal) slice.removeEventListener("animationend", finishReveal);
    scheduleRevealAnimationHandlers.delete(slice);
    slice.classList.remove("schedule-item-reveal", "schedule-empty-reveal");
    slice.style.removeProperty("--schedule-item-delay");
  });
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

function scheduleRequestHeaders(extraHeaders = {}) {
  return {
    ...extraHeaders,
    "X-Track-Local-Date": toIsoDate(new Date()),
  };
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
  card.classList.remove("is-watch-confirming", "is-revealing-actions");
  delete card.dataset.scheduleConfirmation;
  card.classList.add("is-caught-up");
  card.dataset.progress = data.percent;
  card.dataset.lastWatched = data.last_watched_at || "";
  card.dataset.progressState = progressPresentation(
    card.dataset.trackingState,
    data.watched_count,
    data.episode_count,
    card.dataset.showStatus,
  ).state;

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
  playScheduleAdvanceTransition(card);
}

function playScheduleAdvanceTransition(card) {
  card.classList.remove("is-advancing");
  void card.offsetWidth;
  card.classList.add("is-advancing");
  window.setTimeout(() => card.classList.remove("is-advancing"), 320);
}

function showScheduleActionConfirmation(card) {
  const watchedCount = Number(card.dataset.watchedCount);
  const episodeCount = Number(card.dataset.episodeCount);
  const nextWatchedCount = Math.min(watchedCount + 1, episodeCount);
  const nextPercent = episodeCount
    ? Math.round((nextWatchedCount / episodeCount) * 100)
    : 0;
  const marker = card.querySelector(".schedule-timeline-marker");
  const progress = card.querySelector(".schedule-timeline-progress");
  const progressFill = progress?.querySelector(".progress-track span");
  const snapshot = {
    watchedCount,
    percent: marker?.querySelector("strong")?.textContent,
    count: marker?.querySelector("span")?.textContent,
    progressLabel: progress?.getAttribute("aria-label"),
    progressWidth: progressFill?.style.width,
  };

  card.classList.add("is-watch-confirming");
  card.dataset.scheduleConfirmation = "watch";
  card.dataset.watchedCount = nextWatchedCount;
  card.dataset.progress = nextPercent;
  if (marker?.querySelector("strong")) {
    marker.querySelector("strong").textContent = `${nextPercent}%`;
  }
  if (marker?.querySelector("span")) {
    marker.querySelector("span").textContent = `${nextWatchedCount}/${episodeCount}`;
  }
  progress?.setAttribute(
    "aria-label",
    `${nextWatchedCount} of ${episodeCount} episodes watched`,
  );
  if (progressFill) progressFill.style.width = `${nextPercent}%`;
  return snapshot;
}

function restoreScheduleActionConfirmation(card, snapshot) {
  if (!snapshot) return;
  const marker = card.querySelector(".schedule-timeline-marker");
  const progress = card.querySelector(".schedule-timeline-progress");
  card.classList.remove("is-watch-confirming", "is-revealing-actions");
  delete card.dataset.scheduleConfirmation;
  card.dataset.watchedCount = snapshot.watchedCount;
  card.dataset.progress = Number.parseInt(snapshot.percent, 10) || 0;
  if (marker?.querySelector("strong")) marker.querySelector("strong").textContent = snapshot.percent;
  if (marker?.querySelector("span")) marker.querySelector("span").textContent = snapshot.count;
  if (snapshot.progressLabel) progress?.setAttribute("aria-label", snapshot.progressLabel);
  const progressFill = progress?.querySelector(".progress-track span");
  if (progressFill) progressFill.style.width = snapshot.progressWidth;
}

function revealScheduleActions(card) {
  card.classList.add("is-revealing-actions");
  card.classList.remove("is-watch-confirming");
  window.setTimeout(() => {
    card.querySelectorAll("[data-schedule-action]")
      .forEach((button) => { button.disabled = false; });
    delete card.dataset.scheduleProcessing;
    card.classList.remove("is-revealing-actions");
    delete card.dataset.scheduleConfirmation;
  }, 360);
}

function advanceScheduleCard(card, nextCard, { revealActions = false } = {}) {
  card.dataset.episodeId = nextCard.dataset.episodeId;
  card.dataset.scheduleSearchText = nextCard.dataset.scheduleSearchText;
  card.dataset.watchedCount = nextCard.dataset.watchedCount;
  card.dataset.episodeCount = nextCard.dataset.episodeCount;
  [
    "trackingState", "progressState", "showStatus", "name", "dateAdded",
    "releaseDate", "lastWatched", "progress",
  ].forEach((key) => { card.dataset[key] = nextCard.dataset[key] || ""; });

  const currentOpen = card.querySelector(".schedule-timeline-open");
  const nextOpen = nextCard.querySelector(".schedule-timeline-open");
  if (currentOpen && nextOpen) {
    currentOpen.setAttribute("aria-label", nextOpen.getAttribute("aria-label"));
  }

  const currentLines = card.querySelectorAll("[data-schedule-advance-line]");
  const nextLines = nextCard.querySelectorAll("[data-schedule-advance-line]");
  currentLines.forEach((line, index) => {
    if (nextLines[index]) line.textContent = nextLines[index].textContent;
  });

  const currentMarker = card.querySelector(".schedule-timeline-marker");
  const nextMarker = nextCard.querySelector(".schedule-timeline-marker");
  if (currentMarker && nextMarker) currentMarker.replaceChildren(...nextMarker.childNodes);

  const currentProgress = card.querySelector(".schedule-timeline-progress");
  const nextProgress = nextCard.querySelector(".schedule-timeline-progress");
  if (currentProgress && nextProgress) {
    currentProgress.setAttribute("aria-label", nextProgress.getAttribute("aria-label"));
    const currentFill = currentProgress.querySelector(".progress-track span");
    const nextFill = nextProgress.querySelector(".progress-track span");
    if (currentFill && nextFill) currentFill.style.width = nextFill.style.width;
  }

  playScheduleAdvanceTransition(card);
  if (revealActions) {
    window.setTimeout(() => revealScheduleActions(card), 90);
  }
}

async function refreshScheduleContent({ preserveView = null, background = false } = {}) {
  scheduleCalendarDate = toIsoDate(new Date());
  const response = await fetch("/api/schedule", {
    headers: scheduleRequestHeaders({ "X-Requested-With": "Track" }),
  });
  if (!response.ok) throw new Error("Could not refresh Schedule");
  const template = document.createElement("template");
  template.innerHTML = (await response.text()).trim();
  ["backlog", "upcoming"].forEach((viewName) => {
    if (viewName === preserveView || (background && viewName === currentView)) return;
    const incoming = template.content.querySelector(`[data-schedule-content="${viewName}"]`);
    const current = views.get(viewName)?.querySelector(`[data-schedule-content="${viewName}"]`);
    if (incoming && current) current.replaceWith(incoming);
    formatDisplayDates(views.get(viewName));
    filterSchedule(viewName);
  });
  scheduleViewsHydrated = true;
}

function refreshScheduleForLocalDayChange() {
  const localDate = toIsoDate(new Date());
  if (localDate === scheduleCalendarDate) return;
  scheduleCalendarDate = localDate;
  scheduleViewsHydrated = false;
  refreshScheduleContent().catch(() => undefined);
}

async function refreshTvContent({ background = false } = {}) {
  const response = await fetch("/api/tv", {
    headers: { "X-Requested-With": "Track" },
  });
  if (!response.ok) throw new Error("Could not refresh TV");
  if (background && currentView === "tv") return;
  const view = views.get("tv");
  if (!view) return;
  const template = document.createElement("template");
  template.innerHTML = (await response.text()).trim();
  view.replaceChildren(template.content);
  filterShowView(view);
}

async function flushSearchLibraryUpdates(viewName) {
  if (!librarySearchUpdates[viewName]) return;
  librarySearchUpdates[viewName] = false;
  try {
    if (viewName === "tv") await refreshTvContent();
    else await refreshMoviesContent();
  } catch (_error) {
    librarySearchUpdates[viewName] = true;
    showSnackbar(`Couldn't refresh ${viewName === "tv" ? "TV" : "movies"}. Try again.`);
  }
}

function hydrateOtherPrimaryViews(currentPrimaryView = null) {
  if (backgroundPrimaryViewHydrationStarted) return;
  backgroundPrimaryViewHydrationStarted = true;
  appShellReady.then(() => {
    window.requestAnimationFrame(() => {
      const hydrationTasks = [];
      if (currentPrimaryView !== "tv") {
        hydrationTasks.push(refreshTvContent({ background: true }));
      }
      if (!scheduleViewsHydrated) {
        if (!["backlog", "upcoming"].includes(currentPrimaryView)) {
          hydrationTasks.push(refreshScheduleContent({ background: true }));
        } else {
          hydrationTasks.push(refreshScheduleContent({
            preserveView: currentPrimaryView,
            background: true,
          }));
        }
      }
      Promise.allSettled(hydrationTasks);
    });
  });
}

async function processScheduleEpisode(card, action) {
  if (card.dataset.scheduleProcessing === "true") return;
  card.dataset.scheduleProcessing = "true";

  const episodeId = card.dataset.episodeId;
  const showId = card.dataset.showId;
  const buttons = card.querySelectorAll("[data-schedule-action]");
  let processed = false;
  const actionConfirmation = action === "watch"
    ? showScheduleActionConfirmation(card)
    : null;
  const progressStartedAt = performance.now();
  buttons.forEach((button) => { button.disabled = true; });

  try {
    const response = action === "watch"
      ? await fetch(`/api/episodes/${episodeId}/watch-count`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "increment" }),
      })
      : await fetch(`/api/episodes/${episodeId}/skip`, {
        method: "POST",
        headers: scheduleRequestHeaders(),
      });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `Could not ${action} episode`);
    processed = true;
    if (action === "watch") {
      invalidateWatchCaches({ showId, episodeId });
      applyShowProgress(data);
      maybeOpenFinishedArchiveDialog(data);
    }

    const nextResponse = await fetch(`/api/schedule/shows/${showId}/catch-up`, {
      headers: scheduleRequestHeaders({ "X-Requested-With": "Track" }),
    });
    if (!nextResponse.ok && nextResponse.status !== 204) {
      throw new Error("Could not load the next episode");
    }
    const nextHtml = nextResponse.status === 204 ? "" : await nextResponse.text();
    if (action === "watch") {
      const revealDelay = Math.max(120, 260 - (performance.now() - progressStartedAt));
      await new Promise((resolve) => window.setTimeout(resolve, revealDelay));
    }
    if (nextHtml.trim()) {
      const template = document.createElement("template");
      template.innerHTML = nextHtml.trim();
      const nextCard = template.content.firstElementChild;
      advanceScheduleCard(card, nextCard, { revealActions: action === "watch" });
      filterSchedule();
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
      window.setTimeout(() => {
        delete card.dataset.scheduleProcessing;
        buttons.forEach((button) => { button.disabled = false; });
      }, 250);
    } else if (!nextHtml.trim()) {
      delete card.dataset.scheduleProcessing;
      buttons.forEach((button) => { button.disabled = false; });
    }
  } catch (error) {
    if (processed) {
      await refreshScheduleContent().catch(() => undefined);
      showSnackbar("Episode processed; Schedule was refreshed");
    } else {
      restoreScheduleActionConfirmation(card, actionConfirmation);
      showSnackbar(error.message);
    }
    delete card.dataset.scheduleProcessing;
    buttons.forEach((button) => { button.disabled = false; });
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
  if (includeSeasons) {
    showSeasonsCache.delete(String(showId));
    clearSeasonEpisodeCaches();
  }
}

function invalidateEpisodeCache(episodeId) {
  episodeDetailCache.delete(String(episodeId));
}

function invalidateWatchCaches({ showId, episodeId = null, allEpisodes = false }) {
  diaryRevision += 1;
  if (allEpisodes) episodeDetailCache.clear();
  else if (episodeId !== null) invalidateEpisodeCache(episodeId);
  invalidateShowCache(showId, true);
}

function setSeasonEpisodesCache(seasonId, html) {
  const cacheKey = String(seasonId);
  seasonEpisodesCache.set(cacheKey, html);
}

function deleteSeasonEpisodesCache(seasonId) {
  const cacheKey = String(seasonId);
  seasonEpisodeCacheGeneration += 1;
  seasonEpisodesCache.delete(cacheKey);
  seasonEpisodeHydrationTargets.delete(cacheKey);
  queuedSeasonEpisodePrefetches.delete(cacheKey);
  for (let index = seasonEpisodePrefetchQueue.length - 1; index >= 0; index -= 1) {
    if (seasonEpisodePrefetchQueue[index] === cacheKey) {
      seasonEpisodePrefetchQueue.splice(index, 1);
    }
  }
}

function clearSeasonEpisodeCaches() {
  seasonEpisodeCacheGeneration += 1;
  seasonEpisodesCache.clear();
  seasonEpisodeHydrationTargets.clear();
  queuedSeasonEpisodePrefetches.clear();
  seasonEpisodePrefetchQueue.length = 0;
}

function cacheCurrentSeasons(showId) {
  const detailShow = views.get("detail").querySelector(`[data-detail-show][data-show-id="${showId}"]`);
  const seasonList = detailShow?.querySelector("[data-season-list]");
  if (seasonList) {
    const cachedList = seasonList.cloneNode(true);
    enableWatchControls(cachedList);
    cachedList.querySelectorAll("details.season").forEach((season) => {
      season.removeAttribute("open");
      season.dataset.episodesLoaded = "false";
      season.querySelector("[data-season-episodes]")?.replaceChildren();
    });
    showSeasonsCache.set(String(showId), cachedList.innerHTML);
  }
}

function cacheCurrentSeasonEpisodes(season) {
  if (season?.dataset.episodesLoaded !== "true") return;
  const episodeList = season.querySelector("[data-season-episodes]");
  if (!episodeList) return;
  const cachedList = episodeList.cloneNode(true);
  enableWatchControls(cachedList);
  setSeasonEpisodesCache(season.dataset.seasonId, cachedList.innerHTML);
}

function enableWatchControls(root) {
  root.querySelectorAll("[data-episode-watch], [data-season-watch]")
    .forEach((control) => { control.disabled = false; });
}

function requestSeasonEpisodes(seasonId) {
  const cacheKey = String(seasonId);
  const cachedEpisodes = seasonEpisodesCache.get(cacheKey);
  if (cachedEpisodes !== undefined) return Promise.resolve(cachedEpisodes);
  const existingRequest = seasonEpisodeRequests.get(cacheKey);
  if (existingRequest) return existingRequest;

  const requestGeneration = seasonEpisodeCacheGeneration;
  const request = fetch(`/api/seasons/${cacheKey}/episodes`, {
    headers: { "X-Requested-With": "Track" },
  }).then(async (response) => {
    if (!response.ok) throw new Error("Could not load episodes");
    const html = await response.text();
    if (requestGeneration !== seasonEpisodeCacheGeneration) {
      const staleError = new Error("Episode data changed while loading");
      staleError.name = "StaleSeasonEpisodesError";
      throw staleError;
    }
    setSeasonEpisodesCache(cacheKey, html);
    return html;
  }).finally(() => {
    if (seasonEpisodeRequests.get(cacheKey) === request) {
      seasonEpisodeRequests.delete(cacheKey);
    }
  });
  seasonEpisodeRequests.set(cacheKey, request);
  return request;
}

function scheduleSeasonEpisodeHydration(seasonId) {
  const cacheKey = String(seasonId);
  const season = seasonEpisodeHydrationTargets.get(cacheKey);
  const html = seasonEpisodesCache.get(cacheKey);
  const hydrationGeneration = seasonEpisodeCacheGeneration;
  if (!season || html === undefined) return;
  if (season.dataset.episodesLoaded === "true") {
    seasonEpisodeHydrationTargets.delete(cacheKey);
    return;
  }

  const hydrateWhenIdle = (deadline = null) => {
    if (deadline && !deadline.didTimeout && deadline.timeRemaining() < 8) {
      window.requestIdleCallback(hydrateWhenIdle, { timeout: 1200 });
      return;
    }
    if (
      hydrationGeneration !== seasonEpisodeCacheGeneration
      || !season.isConnected
      || seasonEpisodeHydrationTargets.get(cacheKey) !== season
      || seasonEpisodesCache.get(cacheKey) !== html
      || season.dataset.episodesLoaded === "true"
    ) return;
    renderSeasonEpisodes(season, html, false);
    seasonEpisodeHydrationTargets.delete(cacheKey);
  };
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(hydrateWhenIdle, { timeout: 1200 });
  } else {
    window.setTimeout(hydrateWhenIdle, 80);
  }
}

function pumpSeasonEpisodePrefetchQueue() {
  while (activeSeasonEpisodePrefetches < 3 && seasonEpisodePrefetchQueue.length) {
    const seasonId = seasonEpisodePrefetchQueue.shift();
    queuedSeasonEpisodePrefetches.delete(seasonId);
    if (seasonEpisodesCache.has(seasonId)) {
      scheduleSeasonEpisodeHydration(seasonId);
      continue;
    }
    activeSeasonEpisodePrefetches += 1;
    requestSeasonEpisodes(seasonId)
      .then(() => {
        scheduleSeasonEpisodeHydration(seasonId);
      })
      .catch(() => undefined)
      .finally(() => {
        activeSeasonEpisodePrefetches -= 1;
        pumpSeasonEpisodePrefetchQueue();
      });
  }
}

function prefetchShowSeasonEpisodes(detailShow) {
  const seasons = [...detailShow.querySelectorAll("details.season[data-season-id]")];
  if (!seasons.length) return;
  seasonEpisodeHydrationTargets.clear();
  queuedSeasonEpisodePrefetches.clear();
  seasonEpisodePrefetchQueue.length = 0;
  const regularSeasons = seasons.filter((season) => season.dataset.progressCounted !== "false");
  const likelySeason = regularSeasons.find(
    (season) => Number(season.dataset.watchedCount) < Number(season.dataset.episodeCount),
  ) || regularSeasons.at(-1) || seasons[0];
  const orderedSeasons = [
    likelySeason,
    ...regularSeasons.filter((season) => season !== likelySeason),
    ...seasons.filter((season) => season.dataset.progressCounted === "false"),
  ];
  orderedSeasons.forEach((season) => {
    seasonEpisodeHydrationTargets.set(String(season.dataset.seasonId), season);
  });
  [...orderedSeasons].reverse().forEach((season) => {
    const seasonId = String(season.dataset.seasonId);
    if (seasonEpisodesCache.has(seasonId)) {
      scheduleSeasonEpisodeHydration(seasonId);
      return;
    }
    if (queuedSeasonEpisodePrefetches.has(seasonId)) return;
    queuedSeasonEpisodePrefetches.add(seasonId);
    seasonEpisodePrefetchQueue.unshift(seasonId);
  });
  pumpSeasonEpisodePrefetchQueue();
}

function renderSeasonEpisodes(season, html, animate) {
  const episodeList = season.querySelector("[data-season-episodes]");
  if (!episodeList) return;
  episodeList.innerHTML = html;
  season.dataset.episodesLoaded = "true";
  if (seasonEpisodeHydrationTargets.get(String(season.dataset.seasonId)) === season) {
    seasonEpisodeHydrationTargets.delete(String(season.dataset.seasonId));
  }
  enableWatchControls(episodeList);
  formatDisplayDates(episodeList);
  if (animate && episodeList.children.length) {
    episodeList.classList.add("season-episodes-reveal");
    episodeList.addEventListener("animationend", () => {
      episodeList.classList.remove("season-episodes-reveal");
    }, { once: true });
  }
}

function loadSeasonEpisodes(season) {
  if (!season || season.dataset.episodesLoaded === "true") return Promise.resolve();
  const existingTask = seasonLoadTasks.get(season);
  if (existingTask) return existingTask;
  const task = performSeasonEpisodeLoad(season)
    .finally(() => seasonLoadTasks.delete(season));
  seasonLoadTasks.set(season, task);
  return task;
}

async function performSeasonEpisodeLoad(season) {
  if (!season || season.dataset.episodesLoaded === "true") return;
  const seasonId = String(season.dataset.seasonId);
  const cachedEpisodes = seasonEpisodesCache.get(seasonId);
  if (cachedEpisodes !== undefined) {
    renderSeasonEpisodes(season, cachedEpisodes, false);
    return;
  }

  const episodeList = season.querySelector("[data-season-episodes]");
  episodeList.innerHTML = `
    <div class="season-episodes-loading" role="status" aria-label="Loading episodes">
      <span class="sr-only">Loading episodes</span>
    </div>`;

  try {
    renderSeasonEpisodes(season, await requestSeasonEpisodes(seasonId), true);
  } catch (error) {
    if (error.name === "StaleSeasonEpisodesError") {
      await performSeasonEpisodeLoad(season);
      return;
    }
    episodeList.innerHTML = `
      <div class="season-episodes-error">
        <span>Couldn't load episodes.</span>
        <button type="button" data-retry-season-episodes>Try again</button>
      </div>`;
  }
}

async function restoreShowDetailContext(showId, context) {
  if (!context) return;
  const detailShow = views.get("detail")
    .querySelector(`[data-detail-show][data-show-id="${showId}"]`);
  if (!detailShow) return;

  const seasonsToRestore = (context.openSeasonIds || []).map((seasonId) => {
    const season = detailShow.querySelector(`[data-season-id="${seasonId}"]`);
    if (season) season.open = true;
    return season;
  });
  await Promise.all(seasonsToRestore.filter(Boolean).map(loadSeasonEpisodes));

  const returnedEpisode = context.returnEpisodeId
    ? detailShow.querySelector(`[data-episode-id="${context.returnEpisodeId}"]`)
    : null;
  window.requestAnimationFrame(() => {
    if (Number.isFinite(Number(context.detailScrollY))) {
      window.scrollTo({ top: Number(context.detailScrollY), behavior: "auto" });
    }
    if (!returnedEpisode) return;
    returnedEpisode.classList.add("is-returned-to");
    returnedEpisode.addEventListener("animationend", () => {
      returnedEpisode.classList.remove("is-returned-to");
    }, { once: true });
  });
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
  clearSeasonEpisodeCaches();

  const currentShow = views.get("detail")
    .querySelector(`[data-detail-show][data-show-id="${showId}"]`);
  if (!currentShow) return;
  const openSeasonIds = new Set(
    [...currentShow.querySelectorAll("details.season[open]")]
      .map((season) => season.dataset.seasonId),
  );
  const detailScrollY = window.scrollY;

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
  restoreShowDetailContext(showId, {
    openSeasonIds: [...openSeasonIds],
    detailScrollY,
  });
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
      invalidateWatchCaches({ showId, allEpisodes: true });
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

function prepareDetailLoad(title) {
  if (detailRequest) detailRequest.abort();
  detailRequest = new AbortController();
  renderDetailLoading(title);
  scrollPositions.detail = 0;
  if (currentView === "detail") window.scrollTo({ top: 0, behavior: "auto" });
  else showView("detail");
}

async function openShow(
  showId,
  parentView = currentView,
  showSkeleton = true,
  historyMode = "push",
  returnContext = null,
) {
  const cacheKey = String(showId);
  detailParentView = ["backlog", "upcoming", "tv", "movies", "profile"].includes(parentView)
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
  const cachedOverview = showDetailCache.get(cacheKey);
  const cachedSeasons = showSeasonsCache.get(cacheKey);
  if (cachedOverview && cachedSeasons) {
    if (detailRequest) detailRequest.abort();
    detailRequest = null;
    if (currentView !== "detail") showView("detail");
    renderShowDetail(cachedOverview, cachedSeasons, false, returnContext);
    refreshShowIfDue(showId);
    return;
  }

  if (showSkeleton) prepareDetailLoad("Show details");
  else {
    if (detailRequest) detailRequest.abort();
    detailRequest = new AbortController();
    if (currentView !== "detail") showView("detail");
  }

  try {
    const fetchFragment = async (url, errorMessage) => {
      const response = await fetch(url, {
        headers: { "X-Requested-With": "Track" },
        signal: detailRequest.signal,
      });
      if (!response.ok) throw new Error(errorMessage);
      return response.text();
    };
    const [overviewHtml, seasonsHtml] = await Promise.all([
      cachedOverview
        ? Promise.resolve(cachedOverview)
        : fetchFragment(`/api/shows/${showId}`, "Could not load show"),
      cachedSeasons
        ? Promise.resolve(cachedSeasons)
        : fetchFragment(`/api/shows/${showId}/seasons`, "Could not load seasons"),
    ]);
    showDetailCache.set(cacheKey, overviewHtml);
    showSeasonsCache.set(cacheKey, seasonsHtml);
    renderShowDetail(overviewHtml, seasonsHtml, true, returnContext);
    refreshShowIfDue(showId);
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

function renderShowDetail(showHtml, seasonsHtml, animate, returnContext = null) {
  const showTemplate = document.createElement("template");
  showTemplate.innerHTML = showHtml;
  const detailShow = showTemplate.content.querySelector("[data-detail-show]");
  const hero = detailShow.querySelector(".hero");
  const detailContent = detailShow.querySelector(".detail-content");
  const seasonList = detailContent.querySelector("[data-season-list]");
  const activity = detailContent.querySelector("[data-activity-log]");
  seasonList.innerHTML = seasonsHtml;
  seasonList.removeAttribute("aria-busy");
  (returnContext?.openSeasonIds || []).forEach((seasonId) => {
    const season = seasonList.querySelector(`[data-season-id="${seasonId}"]`);
    if (season) season.open = true;
  });
  if (animate) {
    const slices = [
      hero,
      ...[...detailContent.children]
        .filter((section) => section !== seasonList && section !== activity),
      ...seasonList.querySelectorAll(":scope > .season"),
      activity,
    ];
    staggerDetailSlices(slices);
  }
  views.get("detail").replaceChildren(showTemplate.content);
  enableWatchControls(views.get("detail"));
  finishDetailLoad();
  restoreShowDetailContext(detailShow.dataset.showId, returnContext);
  prefetchShowSeasonEpisodes(detailShow);
  if (animate) hydrateOtherPrimaryViews();
}

async function openMovie(movieId, parentView = "movies", historyMode = "push") {
  detailParentView = ["backlog", "upcoming", "tv", "movies", "profile"].includes(parentView)
    ? parentView : "movies";
  if (historyMode) {
    writeHistory({ view: "detail", detailType: "movie", movieId: String(movieId), parentView: detailParentView }, historyMode);
  }
  const cacheKey = String(movieId);
  const cached = movieDetailCache.get(cacheKey);
  if (cached) {
    if (detailRequest) detailRequest.abort();
    detailRequest = null;
    if (currentView !== "detail") showView("detail");
    renderMovieDetail(cached, false);
    return;
  }
  prepareDetailLoad("Movie details");
  try {
    const response = await fetch(`/api/movies/${movieId}`, {
      headers: { "X-Requested-With": "Track" }, signal: detailRequest.signal,
    });
    if (!response.ok) throw new Error("Could not load movie");
    const movieHtml = await response.text();
    movieDetailCache.set(cacheKey, movieHtml);
    renderMovieDetail(movieHtml, true);
  } catch (error) {
    if (error.name === "AbortError") return;
    views.get("detail").innerHTML = `<header class="detail-app-bar"><button class="icon-button" type="button" data-detail-back aria-label="Back"><span class="material-symbols-rounded" aria-hidden="true">arrow_back</span></button><span>Movie details</span></header><div class="empty-state detail-error"><span class="empty-icon material-symbols-rounded" aria-hidden="true">cloud_off</span><h2>Couldn't load this movie</h2><p>Check the connection and try again.</p><button class="filled-button" type="button" data-retry-movie="${movieId}">Try again</button></div>`;
  }
}

function renderMovieDetail(movieHtml, animate) {
  const template = document.createElement("template");
  template.innerHTML = movieHtml;
  const detailMovie = template.content.querySelector("[data-detail-movie]");
  if (animate) staggerDetailSlices([detailMovie.querySelector(".hero"), ...detailMovie.querySelectorAll(".detail-content > *")]);
  views.get("detail").replaceChildren(template.content);
  finishDetailLoad();
}

async function previewCatalogMovie(card, historyMode = "push") {
  if (card.classList.contains("is-loading")) return;
  const movieId = card.dataset.movieId;
  if (movieId) {
    openMovie(movieId, "movies", historyMode);
    return;
  }
  card.classList.add("is-loading");
  card.setAttribute("aria-busy", "true");
  card.querySelectorAll(".catalog-action").forEach((button) => { button.disabled = true; });
  if (historyMode) {
    writeHistory({ view: "detail", detailType: "movieCatalog", tmdbId: card.dataset.tmdbId, parentView: "movies" }, historyMode);
  }
  prepareDetailLoad("Movie details");
  try {
    const response = await fetch(`/api/movies/tmdb/${card.dataset.tmdbId}/preview`, {
      headers: { "X-Requested-With": "Track" }, signal: detailRequest.signal,
    });
    if (!response.ok) throw new Error("Could not load movie");
    renderMovieDetail(await response.text(), true);
  } catch (error) {
    if (error.name !== "AbortError") showSnackbar(error.message);
    if (currentView === "detail") showView("movies", "replace");
  } finally {
    card.classList.remove("is-loading");
    card.removeAttribute("aria-busy");
    card.querySelectorAll(".catalog-action").forEach((button) => { button.disabled = false; });
  }
}

async function trackDetailMovie(movieElement, state, trigger) {
  trigger.disabled = true;
  try {
    const response = await fetch(`/api/movies/${movieElement.dataset.tmdbId}/import`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not add movie");
    document.querySelectorAll(`.popular-card[data-tmdb-id="${movieElement.dataset.tmdbId}"]`)
      .forEach((card) => markCatalogTracked(card, state, String(data.movie_id)));
    openMovie(data.movie_id, "movies", "replace");
  } catch (error) {
    trigger.disabled = false;
    showSnackbar(error.message);
  }
}

async function openEpisode(episodeId, historyMode = "push") {
  const cacheKey = String(episodeId);
  const activeHistoryState = window.history.state;
  const previousWasShow = historyMode
    ? Boolean(
      activeHistoryState?.trackApp
      && activeHistoryState.view === "detail"
      && activeHistoryState.detailType === "show"
    )
    : Boolean(activeHistoryState?.previousWasShow);

  if (historyMode && previousWasShow) {
    const currentShow = views.get("detail").querySelector("[data-detail-show]");
    const openSeasonIds = [...currentShow.querySelectorAll("details.season[open]")]
      .map((season) => season.dataset.seasonId);
    window.history.replaceState({
      ...activeHistoryState,
      openSeasonIds,
      returnEpisodeId: String(episodeId),
      detailScrollY: window.scrollY,
    }, "");
  }

  if (historyMode) {
    writeHistory({
      view: "detail",
      detailType: "episode",
      episodeId: String(episodeId),
      parentView: detailParentView,
      previousWasShow,
    }, historyMode);
  }

  if (detailRequest) detailRequest.abort();
  const cachedEpisode = episodeDetailCache.get(cacheKey);
  if (cachedEpisode) {
    detailRequest = null;
    scrollPositions.detail = 0;
    if (currentView === "detail") window.scrollTo({ top: 0, behavior: "auto" });
    else showView("detail");
    renderEpisodeDetail(cachedEpisode, previousWasShow, false);
    return;
  }

  detailRequest = new AbortController();
  renderDetailLoading("Episode details");
  scrollPositions.detail = 0;
  if (currentView === "detail") window.scrollTo({ top: 0, behavior: "auto" });
  else showView("detail");

  try {
    const response = await fetch(`/api/episodes/${episodeId}`, {
      headers: { "X-Requested-With": "Track" },
      signal: detailRequest.signal,
    });
    if (!response.ok) throw new Error("Could not load episode");
    const episodeHtml = await response.text();
    episodeDetailCache.set(cacheKey, episodeHtml);
    renderEpisodeDetail(episodeHtml, previousWasShow, true);
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

function requestEpisodeDetailHtml(episodeId) {
  const cacheKey = String(episodeId);
  if (episodeDetailCache.has(cacheKey)) {
    return Promise.resolve(episodeDetailCache.get(cacheKey));
  }
  if (episodeDetailRequests.has(cacheKey)) return episodeDetailRequests.get(cacheKey);

  const request = fetch(`/api/episodes/${episodeId}`, {
    headers: { "X-Requested-With": "Track" },
  }).then(async (response) => {
    if (!response.ok) throw new Error("Could not load episode");
    const episodeHtml = await response.text();
    episodeDetailCache.set(cacheKey, episodeHtml);
    return episodeHtml;
  }).finally(() => episodeDetailRequests.delete(cacheKey));
  episodeDetailRequests.set(cacheKey, request);
  return request;
}

function preloadMediaImage(source) {
  const absoluteSource = new URL(source, document.baseURI).href;
  if (mediaImagePreloads.has(absoluteSource)) return mediaImagePreloads.get(absoluteSource);

  const preload = new Promise((resolve) => {
    const image = new Image();
    let settled = false;
    const settle = async () => {
      if (settled) return;
      settled = true;
      try {
        await image.decode();
      } catch (_error) {
        // A failed image is also settled; the normal media fallback handles it.
      }
      resolve();
    };
    image.addEventListener("load", settle, { once: true });
    image.addEventListener("error", settle, { once: true });
    image.src = absoluteSource;
    if (image.complete) settle();
  });
  mediaImagePreloads.set(absoluteSource, preload);
  return preload;
}

function preloadEpisodeDetailImages(episodeHtml) {
  const template = document.createElement("template");
  template.innerHTML = episodeHtml;
  const sources = [...template.content.querySelectorAll("img[data-media-image][src]")]
    .map((image) => image.getAttribute("src"));
  return Promise.all(sources.map(preloadMediaImage));
}

function preloadAdjacentEpisodeDetails(detailEpisode) {
  detailEpisode?.querySelectorAll("[data-adjacent-episode][data-episode-id]")
    .forEach((button) => {
      requestEpisodeDetailHtml(button.dataset.episodeId)
        .then(preloadEpisodeDetailImages)
        .catch(() => undefined);
    });
}

function animateEpisodePageEntry(detailView, direction) {
  if (!direction || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const page = detailView.querySelector("[data-episode-page-content]");
  if (!page) return;
  const startPosition = direction === "next" ? "18%" : "-18%";
  page.animate(
    [
      { transform: `translateX(${startPosition})`, opacity: 0 },
      { transform: "translateX(0)", opacity: 1 },
    ],
    { duration: 180, easing: "ease-out" },
  );
}

async function navigateAdjacentEpisode(button) {
  if (episodeNavigationPending || !button.dataset.episodeId) return;
  const detailView = views.get("detail");
  const detailEpisode = button.closest("[data-detail-episode]");
  const page = detailEpisode?.querySelector("[data-episode-page-content]");
  if (!detailEpisode || !page) return;

  episodeNavigationPending = true;
  const direction = button.dataset.adjacentEpisode;
  const targetEpisodeId = button.dataset.episodeId;
  const previousWasShow = Boolean(window.history.state?.previousWasShow);
  const exitPosition = direction === "next" ? "-18%" : "18%";
  const exitAnimation = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? null
    : page.animate(
      [
        { transform: "translateX(0)", opacity: 1 },
        { transform: `translateX(${exitPosition})`, opacity: 0 },
      ],
      { duration: 140, easing: "ease-in", fill: "both" },
    );

  try {
    const [episodeHtml] = await Promise.all([
      requestEpisodeDetailHtml(targetEpisodeId),
      exitAnimation?.finished.catch(() => undefined) || Promise.resolve(),
    ]);
    writeHistory({
      view: "detail",
      detailType: "episode",
      episodeId: String(targetEpisodeId),
      parentView: detailParentView,
      previousWasShow,
    }, "replace");
    scrollPositions.detail = 0;
    window.scrollTo({ top: 0, behavior: "auto" });
    lastEpisodeDetailScrollY = 0;
    renderEpisodeDetail(episodeHtml, previousWasShow, true, direction);
  } catch (_error) {
    exitAnimation?.cancel();
    showSnackbar("Couldn't load this episode.", {
      actionLabel: "Retry",
      onAction: () => navigateAdjacentEpisode(button),
    });
  } finally {
    episodeNavigationPending = false;
  }
}

function fitEpisodeDetailTitle(detailView) {
  const title = detailView.querySelector("[data-responsive-episode-title]");
  if (!title) return;
  title.classList.remove("long-title");
  const lineHeight = Number.parseFloat(getComputedStyle(title).lineHeight);
  if (Number.isFinite(lineHeight) && title.scrollHeight > (lineHeight * 2) + 1) {
    title.classList.add("long-title");
  }
}

function renderEpisodeDetail(episodeHtml, previousWasShow, animate, entryDirection = null) {
  const episodeTemplate = document.createElement("template");
  episodeTemplate.innerHTML = episodeHtml;
  if (previousWasShow) {
    episodeTemplate.content.querySelector("[data-episode-show-open]")?.remove();
  }
  if (animate) {
    const episodeHero = episodeTemplate.content.querySelector(".episode-hero");
    const episodeContent = episodeTemplate.content.querySelector(".episode-detail-content");
    staggerDetailSlices([episodeHero, ...episodeContent.children]);
  }
  views.get("detail").replaceChildren(episodeTemplate.content);
  fitEpisodeDetailTitle(views.get("detail"));
  const detailEpisode = views.get("detail").querySelector("[data-detail-episode]");
  lastEpisodeDetailScrollY = window.scrollY;
  preloadAdjacentEpisodeDetails(detailEpisode);
  animateEpisodePageEntry(views.get("detail"), entryDirection);
  finishDetailLoad();
  if (animate) hydrateOtherPrimaryViews();
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
    activated: "resume",
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

  const calendar = datePicker.querySelector(".date-picker-calendar");
  const yearToggle = datePicker.querySelector("[data-date-picker-year-toggle]");
  const yearGrid = datePicker.querySelector("[data-date-picker-years]");
  const dayGrid = datePicker.querySelector("[data-date-picker-days]");
  calendar.classList.toggle("is-year-view", datePickerYearVisible);
  yearToggle.setAttribute("aria-expanded", String(datePickerYearVisible));
  yearGrid.setAttribute("aria-hidden", String(!datePickerYearVisible));
  yearGrid.inert = !datePickerYearVisible;
  dayGrid.setAttribute("aria-hidden", String(datePickerYearVisible));
  dayGrid.inert = datePickerYearVisible;

  const grid = datePicker.querySelector("[data-date-picker-grid]");
  grid.replaceChildren();
  const year = datePickerMonth.getFullYear();
  const month = datePickerMonth.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayIso = toIsoDate(new Date());
  const selectedIso = datePickerSelectedDate ? toIsoDate(datePickerSelectedDate) : null;

  if (datePickerYearVisible) {
    yearGrid.replaceChildren();
    const finalYear = Math.max(new Date().getFullYear() + 10, year);
    for (let optionYear = 2000; optionYear <= finalYear; optionYear += 1) {
      const button = document.createElement("button");
      button.className = "date-picker-year";
      button.type = "button";
      button.dataset.datePickerYear = optionYear;
      button.textContent = optionYear;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", String(optionYear === year));
      button.classList.toggle("is-selected", optionYear === year);
      yearGrid.append(button);
    }
    const selectedYear = yearGrid.querySelector(".is-selected");
    if (selectedYear) {
      yearGrid.scrollTop = selectedYear.offsetTop
        - ((yearGrid.clientHeight - selectedYear.offsetHeight) / 2);
    }
  }

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
  datePickerYearVisible = false;
  renderDatePicker();
  datePicker.showModal();
}

function shiftDatePickerMonth(offset) {
  datePickerYearVisible = false;
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
    const detailEpisode = datePickerTarget.closest("[data-detail-episode]");
    if (detailEpisode) invalidateEpisodeCache(detailEpisode.dataset.episodeId);
    const detailMovie = datePickerTarget.closest("[data-detail-movie]");
    if (detailMovie) movieDetailCache.delete(detailMovie.dataset.movieId);
    if (["episode", "movie"].includes(data.watch_kind)) diaryRevision += 1;
    datePicker.close();
  } catch (_error) {
    showSnackbar("Couldn't update the watch date. Try again.");
  } finally {
    saveButton.disabled = false;
  }
}

const progressFilterLabels = {
  "": "All",
  [PROGRESS_STATE.NEW]: "New",
  [PROGRESS_STATE.STARTED]: "Started",
  [PROGRESS_STATE.CAUGHT_UP]: "Caught-up",
};

const sortFieldLabels = {
  name: "Name",
  dateAdded: "Added",
  releaseDate: "Released",
  lastWatched: "Watched",
  progress: "Progress",
};

const libraryViewDefaults = {
  backlog: { progress: "", sortField: "lastWatched", sortDirection: "desc", mediaTypes: ["tv"] },
  upcoming: { progress: "", sortField: "releaseDate", sortDirection: "asc", mediaTypes: ["tv", "archive"] },
  tv: { progress: "", sortField: "name", sortDirection: "asc", mediaTypes: ["tv"] },
  movies: { progress: "", sortField: "name", sortDirection: "asc", mediaTypes: ["movies"] },
};

function mediaTypeLabel(mediaTypes, defaultMediaTypes) {
  const selected = new Set(mediaTypes);
  if (selected.size === defaultMediaTypes.length
    && defaultMediaTypes.every((type) => selected.has(type))) return "Library";
  if (selected.has("tv") && selected.has("movies")) return selected.has("archive") ? "All+" : "All";
  if (selected.has("tv")) return selected.has("archive") ? "TV+" : "TV";
  if (selected.has("movies")) return selected.has("archive") ? "Movies+" : "Movies";
  return selected.has("archive") ? "Archive" : "None";
}

function hasDefaultMediaTypes(mediaTypes, defaultMediaTypes) {
  return mediaTypes.length === defaultMediaTypes.length
    && defaultMediaTypes.every((type) => mediaTypes.includes(type));
}

function syncTvControlBar(view = views.get(currentView)) {
  if (!view || !tvControlBar) return;
  const viewName = view.dataset.view;
  const preferences = libraryViewPreferences[viewName];
  const defaults = libraryViewDefaults[viewName];
  if (!preferences || !defaults) return;
  const progressLabel = tvControlBar.querySelector("[data-tv-progress-label]");
  const mediaLabel = tvControlBar.querySelector("[data-tv-media-label]");
  const sortLabel = tvControlBar.querySelector("[data-tv-sort-label]");
  const sortIcon = tvControlBar.querySelector("[data-tv-sort-icon]");
  const mediaIsDefault = hasDefaultMediaTypes(preferences.mediaTypes, defaults.mediaTypes);
  if (mediaLabel) {
    const label = mediaTypeLabel(preferences.mediaTypes, defaults.mediaTypes);
    const hasPlus = label.endsWith("+");
    mediaLabel.replaceChildren(document.createTextNode(hasPlus ? label.slice(0, -1) : label));
    if (hasPlus) {
      const plus = document.createElement("span");
      plus.className = "tv-media-label-plus";
      plus.textContent = "+";
      mediaLabel.append(plus);
    }
  }
  if (progressLabel) {
    progressLabel.textContent = progressFilterLabels[preferences.progress];
  }
  if (sortLabel) {
    sortLabel.textContent = sortFieldLabels[preferences.sortField];
  }
  if (sortIcon) {
    sortIcon.textContent = preferences.sortDirection === "asc"
      ? "arrow_upward"
      : "arrow_downward";
  }
  [
    ["media", !mediaIsDefault],
    ["filter", preferences.progress !== defaults.progress],
    ["sort", preferences.sortField !== defaults.sortField
      || preferences.sortDirection !== defaults.sortDirection],
  ].forEach(([control, isActive]) => {
    tvControlBar.querySelector(`[data-tv-dropdown-toggle="${control}"] > .material-symbols-rounded:not(.tv-dropdown-chevron)`)
      ?.classList.toggle("is-control-active", isActive);
  });

  tvControlBar.querySelectorAll("[data-tv-media-option]").forEach((button) => {
    const type = button.dataset.tvMediaOption;
    const excluded = (viewName === "tv" && type === "movies")
      || (viewName === "movies" && type === "tv");
    button.hidden = excluded;
    const selected = preferences.mediaTypes.includes(type);
    button.classList.toggle("is-unselected-default", defaults.mediaTypes.includes(type) && !selected);
    button.setAttribute("aria-checked", String(selected));
    button.querySelector(".tv-dropdown-selection").classList.toggle("is-hidden", !selected);
  });

  tvControlBar.querySelectorAll("[data-tv-progress-option]").forEach((button) => {
    const selected = button.dataset.tvProgressOption === preferences.progress;
    button.classList.toggle("is-unselected-default", button.dataset.tvProgressOption === defaults.progress && !selected);
    button.setAttribute("aria-checked", String(selected));
    button.querySelector(".tv-dropdown-selection").classList.toggle("is-hidden", !selected);
  });
  tvControlBar.querySelectorAll("[data-tv-sort-option]").forEach((button) => {
    const selected = button.dataset.tvSortOption === preferences.sortField;
    button.classList.toggle("is-unselected-default", button.dataset.tvSortOption === defaults.sortField && !selected);
    const sortLocked = viewName === "upcoming";
    button.disabled = sortLocked;
    button.setAttribute("aria-disabled", String(sortLocked));
    button.setAttribute("aria-checked", String(selected));
    const indicator = button.querySelector(".tv-dropdown-selection");
    indicator.classList.toggle("is-hidden", !selected);
    indicator.textContent = preferences.sortDirection === "asc"
      ? "arrow_upward"
      : "arrow_downward";
  });
}

function syncTvControlVisibility() {
  if (!tvControlBar) return;
  const visible = ["backlog", "upcoming", "tv", "movies"].includes(currentView)
    && !searchQueries[currentView].trim();
  tvControlBar.hidden = !visible;
  appContent?.classList.toggle("has-library-controls", visible);
  if (visible) syncTvControlBar(views.get(currentView));
  if (!visible) closeTvDropdowns();
}

function showFloatingMenu(menu, trigger) {
  menu.getAnimations().forEach((animation) => animation.cancel());
  floatingMenuAnimations.delete(menu);
  menu.hidden = false;
  if (typeof menu.showPopover !== "function") return;
  menu.style.position = "fixed";
  menu.style.inset = "auto";
  menu.style.margin = "0";
  menu.showPopover();
  const bounds = menu.getBoundingClientRect();
  const triggerBounds = trigger.getBoundingClientRect();
  const viewportInset = 16;
  const menuWidth = Math.min(bounds.width, window.innerWidth - (viewportInset * 2));
  const left = Math.max(
    viewportInset,
    Math.min(triggerBounds.right - menuWidth, window.innerWidth - menuWidth - viewportInset),
  );
  const desiredTop = menu.matches("[data-tv-dropdown-menu]")
    ? triggerBounds.top - bounds.height - 8
    : triggerBounds.bottom + 4;
  const top = Math.max(
    viewportInset,
    Math.min(desiredTop, window.innerHeight - bounds.height - viewportInset),
  );
  menu.style.top = `${top}px`;
  menu.style.left = `${left}px`;
  menu.style.width = `${menuWidth}px`;
  const collapsedScale = Math.min(1, 48 / Math.max(bounds.height, 48));
  const transformOrigin = top < triggerBounds.top ? "bottom right" : "top right";
  menu.dataset.menuCollapsedScale = String(collapsedScale);
  menu.style.transformOrigin = transformOrigin;
  const animation = menu.animate([
    { opacity: 0, transform: `scaleY(${collapsedScale})` },
    { opacity: 1, transform: "scaleY(1)" },
  ], {
    duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 120,
    easing: "cubic-bezier(0.2, 0, 0, 1)",
    fill: "both",
  });
  const animationState = { animation, direction: "open" };
  floatingMenuAnimations.set(menu, animationState);
  animation.finished.then(() => {
    if (floatingMenuAnimations.get(menu) !== animationState) return;
    floatingMenuAnimations.delete(menu);
    animation.cancel();
  }).catch(() => undefined);
}

function hideFloatingMenu(menu) {
  if (menu.hidden) return;
  const currentAnimation = floatingMenuAnimations.get(menu);
  if (currentAnimation?.direction === "close") return;
  currentAnimation?.animation.cancel();
  const computedStyle = window.getComputedStyle(menu);
  const collapsedScale = Number(menu.dataset.menuCollapsedScale) || 1;
  const animation = menu.animate([
    { opacity: computedStyle.opacity, transform: computedStyle.transform },
    { opacity: 0, transform: `scaleY(${collapsedScale})` },
  ], {
    duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 1 : 90,
    easing: "cubic-bezier(0.4, 0, 1, 1)",
    fill: "both",
  });
  const animationState = { animation, direction: "close" };
  floatingMenuAnimations.set(menu, animationState);
  animation.finished.then(() => {
    if (floatingMenuAnimations.get(menu) !== animationState) return;
    floatingMenuAnimations.delete(menu);
    if (typeof menu.hidePopover === "function" && menu.matches(":popover-open")) {
      menu.hidePopover();
    }
    menu.hidden = true;
    delete menu.dataset.menuCollapsedScale;
    ["position", "inset", "margin", "top", "left", "width", "transform-origin"].forEach((property) => {
      menu.style.removeProperty(property);
    });
    animation.cancel();
    syncMenuScrim();
  }).catch(() => undefined);
}

function preserveMenuScrollPosition(position) {
  const restore = () => window.scrollTo({
    left: position.x,
    top: position.y,
    behavior: "instant",
  });
  restore();
  window.requestAnimationFrame(restore);
}

function pushTvDropdownHistory() {
  if (tvDropdownHistoryActive) return;
  window.history.pushState({ ...window.history.state, trackApp: true, tvDropdownOpen: true }, "");
  tvDropdownHistoryActive = true;
}

function clearTvDropdownHistory() {
  if (!tvDropdownHistoryActive) return;
  tvDropdownHistoryActive = false;
  if (window.history.state?.tvDropdownOpen) window.history.back();
}

function closeTvDropdowns(exceptMenu = null, { preserveHistory = false } = {}) {
  document.querySelectorAll("[data-tv-dropdown-menu]").forEach((menu) => {
    if (menu === exceptMenu) return;
    hideFloatingMenu(menu);
    menu.parentElement.querySelector("[data-tv-dropdown-toggle]")
      ?.setAttribute("aria-expanded", "false");
  });
  if (!exceptMenu && !preserveHistory) clearTvDropdownHistory();
  syncMenuScrim();
}

function toggleTvDropdown(button) {
  const scrollPosition = { x: window.scrollX, y: window.scrollY };
  const menu = button.parentElement.querySelector("[data-tv-dropdown-menu]");
  if (!menu) return;
  const willOpen = menu.hidden;
  globalSearchInput?.blur();
  closeShowMenus();
  closeWatchMenus();
  closeTvDropdowns(menu, { preserveHistory: true });
  if (willOpen) menuScrollLockPosition = scrollPosition;
  if (willOpen) {
    pushTvDropdownHistory();
    showFloatingMenu(menu, button);
  } else {
    hideFloatingMenu(menu);
    clearTvDropdownHistory();
  }
  button.setAttribute("aria-expanded", String(willOpen));
  syncMenuScrim();
  preserveMenuScrollPosition(scrollPosition);
}

function closeShowMenus(exceptMenu = null) {
  document.querySelectorAll("[data-show-menu], [data-movie-menu]").forEach((menu) => {
    if (menu === exceptMenu) return;
    hideFloatingMenu(menu);
    menu.parentElement.querySelector("[data-show-menu-button], [data-movie-menu-button]")
      ?.setAttribute("aria-expanded", "false");
  });
  syncMenuScrim();
}

function clearMenuIsolation() {
  menuIsolatedElements.forEach((element) => {
    element.inert = false;
  });
  menuIsolatedElements.clear();
}

function isolateOpenMenu(openMenu) {
  let activeBranch = openMenu;
  while (activeBranch && activeBranch !== document.body) {
    const parent = activeBranch.parentElement;
    if (!parent) break;
    [...parent.children].forEach((sibling) => {
      if (sibling === activeBranch || sibling === menuScrim || sibling.inert) return;
      sibling.inert = true;
      menuIsolatedElements.add(sibling);
    });
    activeBranch = parent;
  }
}

function syncMenuScrim() {
  if (!menuScrim) return;
  const openMenu = document.querySelector(
    "[data-show-menu]:not([hidden]), [data-movie-menu]:not([hidden]), [data-watch-menu]:not([hidden]), [data-movie-watch-menu]:not([hidden]), [data-watch-log-menu]:not([hidden]), [data-season-diary-menu]:not([hidden]), [data-tv-dropdown-menu]:not([hidden])",
  );
  const menuOpen = Boolean(openMenu);
  clearMenuIsolation();
  menuScrim.hidden = !menuOpen;
  document.documentElement.classList.toggle("menu-open", menuOpen);
  document.body.classList.toggle("menu-open", menuOpen);
  if (openMenu && !openMenu.contains(document.activeElement)) {
    openMenu.querySelector("button:not([disabled])")?.focus({ preventScroll: true });
  }
  if (openMenu) isolateOpenMenu(openMenu);
  if (!menuOpen) menuScrollLockPosition = null;
}

function preventOpenMenuScroll(event) {
  if (!menuScrim?.hidden) event.preventDefault();
}

document.addEventListener("wheel", preventOpenMenuScroll, { passive: false });
document.addEventListener("touchmove", preventOpenMenuScroll, { passive: false });
window.addEventListener("scroll", () => {
  if (!menuScrollLockPosition) return;
  if (window.scrollX === menuScrollLockPosition.x
    && window.scrollY === menuScrollLockPosition.y) return;
  window.scrollTo({
    left: menuScrollLockPosition.x,
    top: menuScrollLockPosition.y,
    behavior: "instant",
  });
}, { passive: true });

function toggleShowMenu(button) {
  const scrollPosition = { x: window.scrollX, y: window.scrollY };
  const menu = button.parentElement.querySelector("[data-show-menu]")
    || button.closest("[data-show-id]")?.querySelector("[data-show-menu]");
  if (!menu) return;
  const willOpen = menu.hidden;
  clearTvFirstReveal(views.get("tv"));
  clearDetailSliceReveals(views.get("detail"));
  closeWatchMenus();
  closeShowMenus(menu);
  if (willOpen) menuScrollLockPosition = scrollPosition;
  if (willOpen) showFloatingMenu(menu, button);
  else hideFloatingMenu(menu);
  button.setAttribute("aria-expanded", String(willOpen));
  syncMenuScrim();
  preserveMenuScrollPosition(scrollPosition);
}

function syncDiaryHiddenIcon(item) {
  const dateRow = item?.querySelector(".activity-date-row");
  if (!dateRow) return;
  const existing = dateRow.querySelector(".activity-diary-hidden-icon");
  if (item.dataset.showInDiary !== "0") {
    existing?.remove();
    return;
  }
  if (existing) return;
  const icon = document.createElement("span");
  icon.className = "material-symbols-rounded activity-diary-hidden-icon";
  icon.setAttribute("role", "img");
  icon.setAttribute("aria-label", "Hidden from diary");
  icon.title = "Hidden from diary";
  icon.textContent = "visibility_off";
  dateRow.append(icon);
}

function toggleMovieMenu(button) {
  const scrollPosition = { x: window.scrollX, y: window.scrollY };
  const menu = button.parentElement.querySelector("[data-movie-menu]")
    || button.closest("[data-movie-id]")?.querySelector("[data-movie-menu]");
  if (!menu) return;
  const willOpen = menu.hidden;
  clearDetailSliceReveals(views.get("detail"));
  closeWatchMenus();
  closeShowMenus(menu);
  if (willOpen) {
    menuScrollLockPosition = scrollPosition;
    showFloatingMenu(menu, button);
  } else hideFloatingMenu(menu);
  button.setAttribute("aria-expanded", String(willOpen));
  syncMenuScrim();
  preserveMenuScrollPosition(scrollPosition);
}

function closeWatchMenus(exceptMenu = null) {
  document.querySelectorAll("[data-watch-menu], [data-movie-watch-menu]").forEach((menu) => {
    if (menu !== exceptMenu) hideFloatingMenu(menu);
  });
  syncMenuScrim();
}

function toggleWatchMenu(control) {
  const scrollPosition = { x: window.scrollX, y: window.scrollY };
  const menu = control.parentElement.querySelector("[data-watch-menu], [data-movie-watch-menu]");
  if (!menu) return;
  const willOpen = menu.hidden;
  clearDetailSliceReveals(views.get("detail"));
  closeShowMenus();
  closeWatchMenus(menu);
  if (willOpen) menuScrollLockPosition = scrollPosition;
  if (willOpen) showFloatingMenu(menu, control);
  else hideFloatingMenu(menu);
  syncMenuScrim();
  preserveMenuScrollPosition(scrollPosition);
}

function closeWatchLogMenus(exceptMenu = null) {
  document.querySelectorAll("[data-watch-log-menu], [data-season-diary-menu]").forEach((menu) => {
    if (menu !== exceptMenu) hideFloatingMenu(menu);
  });
  syncMenuScrim();
}

function updateMovieWatchUi(detailMovie, watchCount) {
  detailMovie.dataset.watchCount = watchCount;
  detailMovie.dataset.progressState = watchCount > 0 ? "finished" : "not-started";
  const tag = detailMovie.querySelector("[data-movie-progress-tag]");
  if (tag) tag.textContent = watchCount > 0 ? "Watched" : "New";
  const control = detailMovie.querySelector("[data-movie-detail-watch]");
  if (!control) return;
  control.dataset.watchCount = watchCount;
  control.querySelector("[data-movie-detail-watch-count]").textContent = watchCount;
  control.querySelector("[data-movie-detail-watch-label]").textContent = watchCount === 1 ? "watch" : "watches";
}

async function changeMovieWatchCount(detailMovie, action) {
  if (pendingWatchChanges.has(detailMovie)) return;
  pendingWatchChanges.add(detailMovie);
  try {
    const response = await fetch(`/api/movies/${detailMovie.dataset.movieId}/watch-count`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }),
    });
    if (!response.ok) throw new Error("Could not update movie");
    const data = await response.json();
    movieDetailCache.delete(String(data.movie_id));
    updateMovieWatchUi(detailMovie, data.watch_count);
    if (data.action === "increment") {
      addActivityItem({
        type: "watched", title: "Watched", occurredAt: data.changed_at,
        recordId: String(data.watch_record_id), watchKind: "movie", addedAt: data.changed_at,
      });
    } else {
      const log = detailMovie.querySelector("[data-activity-log]");
      log?.querySelector(`.activity-item[data-watch-kind="movie"][data-watch-record-id="${data.watch_record_id}"]`)?.remove();
      if (log && !log.querySelector(".activity-item")) {
        const empty = document.createElement("li");
        empty.className = "activity-empty";
        empty.dataset.activityEmpty = "";
        empty.textContent = "This movie has not been watched yet.";
        log.querySelector("[data-activity-list]")?.append(empty);
      }
      syncActivityCount(log);
    }
    diaryRevision += 1;
    refreshMoviesContent();
  } catch (_error) {
    showSnackbar("Couldn't update this movie. Try again.");
  } finally {
    pendingWatchChanges.delete(detailMovie);
  }
}

async function setMovieWatchedWithoutDiary(detailMovie, watched) {
  if (pendingWatchChanges.has(detailMovie)) return;
  pendingWatchChanges.add(detailMovie);
  try {
    const response = await fetch(`/api/movies/${detailMovie.dataset.movieId}/watched`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ watched }),
    });
    if (!response.ok) throw new Error("Could not update movie");
    const data = await response.json();
    movieDetailCache.delete(String(data.movie_id));
    updateMovieWatchUi(detailMovie, data.watch_count);
    refreshMoviesContent();
  } catch (_error) {
    showSnackbar("Couldn't update this movie. Try again.");
  } finally {
    pendingWatchChanges.delete(detailMovie);
  }
}

async function setShowWatchedWithoutDiary(showElement, watched) {
  try {
    const response = await fetch(`/api/shows/${showElement.dataset.showId}/watched`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ watched }),
    });
    if (!response.ok) throw new Error("Could not update show");
    const data = await response.json();
    showDetailCache.delete(String(data.show_id));
    showSeasonsCache.delete(String(data.show_id));
    await Promise.all([refreshTvContent(), openShow(data.show_id, detailParentView, false, null)]);
  } catch (_error) {
    showSnackbar("Couldn't update this show. Try again.");
  }
}

async function moveMovie(movieElement, targetState, actionButton) {
  actionButton.disabled = true;
  try {
    const response = await fetch(`/api/movies/${movieElement.dataset.movieId}/state`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state: targetState }),
    });
    if (!response.ok) throw new Error("Could not move movie");
    movieDetailCache.delete(String(movieElement.dataset.movieId));
    await refreshMoviesContent();
    if (currentView === "detail") openMovie(movieElement.dataset.movieId, detailParentView, null);
    showSnackbar(targetState === TRACKING_STATE.ARCHIVED ? "Movie archived" : "Movie made active");
  } catch (_error) {
    showSnackbar("Couldn't move this movie. Try again.");
  } finally {
    actionButton.disabled = false;
  }
}

async function removeMovie(movieElement, actionButton) {
  actionButton.disabled = true;
  try {
    const response = await fetch(`/api/movies/${movieElement.dataset.movieId}`, { method: "DELETE" });
    if (!response.ok) throw new Error("Could not remove movie");
    movieDetailCache.delete(String(movieElement.dataset.movieId));
    await refreshMoviesContent();
    if (currentView === "detail") showView(detailParentView, "replace");
    showSnackbar("Movie removed from your library");
  } catch (_error) {
    showSnackbar("Couldn't remove this movie. Try again.");
  } finally {
    actionButton.disabled = false;
  }
}

async function confirmMovieRemoval() {
  if (!pendingRemoveMovieId) return;
  const movieId = pendingRemoveMovieId;
  const movieElement = views.get("detail").querySelector(`[data-detail-movie][data-movie-id="${movieId}"]`)
    || document.querySelector(`[data-movie-id="${movieId}"]`);
  removeDialog.close();
  pendingRemoveMovieId = null;
  if (movieElement) await removeMovie(movieElement, removeDialog.querySelector("[data-confirm-remove]"));
}

function syncProgressState(showElement) {
  const watchedCount = Number(showElement.dataset.watchedCount);
  const episodeCount = Number(showElement.dataset.episodeCount);
  if (!Number.isFinite(watchedCount) || !Number.isFinite(episodeCount)) return;

  const progress = progressPresentation(
    showElement.dataset.showState,
    watchedCount,
    episodeCount,
    showElement.dataset.showStatus,
  );

  showElement.dataset.progressState = progress.state;
  const tag = showElement.querySelector("[data-progress-tag]");
  if (tag) tag.textContent = progress.label;
}

function updateShowRepresentations(showId, state, moveLabel, moveIcon) {
  document.querySelectorAll(`[data-show-id="${showId}"]`).forEach((showElement) => {
    showElement.dataset.showState = state;
    if (showElement.hasAttribute("data-tracking-state")) {
      showElement.dataset.trackingState = state;
    }
    showElement.querySelectorAll('[data-show-action="move"]').forEach((moveButton) => {
      moveButton.dataset.targetState = state === TRACKING_STATE.ARCHIVED
        ? TRACKING_STATE.ACTIVE
        : TRACKING_STATE.ARCHIVED;
      moveButton.querySelector("[data-move-label]").textContent = moveLabel;
      moveButton.querySelector(".material-symbols-rounded").textContent = moveIcon;
    });
    syncProgressState(showElement);
  });
}

function syncStateSections() {
  document.querySelectorAll("[data-state-section]").forEach((section) => {
    const count = section.querySelectorAll(".show-card").length;
    const countElement = section.querySelector("[data-state-count]");
    if (countElement) countElement.textContent = count;
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
    filterSchedule("backlog");
    filterSchedule("upcoming");
    showSnackbar(data.state === "ARCHIVED" ? "Show archived" : "Show made active");
    return true;
  } catch (_error) {
    showSnackbar("Couldn't move this show. Try again.");
    return false;
  } finally {
    actionButton.disabled = false;
  }
}

function maybeOpenFinishedArchiveDialog(data) {
  if (!data.became_finished || !finishedArchiveDialog || finishedArchiveDialog.open) return;
  pendingFinishedArchiveShowId = String(data.show_id);
  const showName = finishedArchiveDialog.querySelector("[data-finished-archive-show]");
  if (showName) showName.textContent = data.show_name || "This show";
  finishedArchiveDialog.showModal();
}

async function confirmArchiveFinishedShow() {
  if (!pendingFinishedArchiveShowId) return;
  const showId = pendingFinishedArchiveShowId;
  const confirmButton = finishedArchiveDialog.querySelector("[data-confirm-finished-archive]");
  const showElement = document.querySelector(`[data-show-id="${showId}"]`)
    || { dataset: { showId } };
  const moved = await moveShow(showElement, TRACKING_STATE.ARCHIVED, confirmButton);
  if (!moved) return;
  finishedArchiveDialog.close();
  pendingFinishedArchiveShowId = null;
}

function requestShowRemoval(showElement) {
  pendingRemoveShowId = showElement.dataset.showId;
  const showName = showElement.querySelector("h1, h3")?.textContent.trim() || "this show";
  removeDialog.querySelector("h2").textContent = `Remove ${showName}?`;
  removeDialog.querySelector("p").textContent = "This removes the show from TV. Its metadata and watch history stay saved.";
  removeDialog.showModal();
  document.documentElement.classList.add("remove-dialog-open");
}

function requestMovieRemoval(movieElement) {
  pendingRemoveMovieId = movieElement.dataset.movieId;
  const movieName = movieElement.querySelector("h1, h3")?.textContent.trim() || "this movie";
  removeDialog.querySelector("h2").textContent = `Remove ${movieName}?`;
  removeDialog.querySelector("p").textContent = "This removes the movie from Movies. Its metadata and watch history stay saved.";
  removeDialog.showModal();
  document.documentElement.classList.add("remove-dialog-open");
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
    removeDialog.close();
    pendingRemoveShowId = null;
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

function updateSeasonWatchSummary(season, episodeCount, watchedCount, minimumWatchCount) {
  season.dataset.episodeCount = episodeCount;
  season.dataset.watchedCount = watchedCount;
  season.dataset.minWatchCount = minimumWatchCount;
  if (season.dataset.progressCounted !== "false") {
    season.querySelector(".season-title small").textContent = `${watchedCount} of ${episodeCount}`;
  }
  const mixed = watchedCount > 0 && watchedCount < episodeCount;
  const displayedCount = watchedCount === episodeCount ? minimumWatchCount : 0;
  setWatchControl(season.querySelector("[data-season-watch]"), displayedCount, mixed);
}

function syncSeasonFromEpisodes(season) {
  const episodes = [...season.querySelectorAll(".episode")];
  const counts = episodes.map((episode) => Number(episode.dataset.watchCount));
  const watchedCount = counts.filter((count) => count > 0).length;
  const minimumWatchCount = counts.length ? Math.min(...counts) : 0;
  updateSeasonWatchSummary(season, episodes.length, watchedCount, minimumWatchCount);
}

function updateEpisodeWatchUi(episode, watchCount, syncSeason = true) {
  episode.dataset.watchCount = watchCount;
  episode.classList.toggle("is-watched", watchCount > 0);
  setWatchControl(episode.querySelector("[data-episode-watch]"), watchCount);
  if (syncSeason) syncSeasonFromEpisodes(episode.closest(".season"));
}

function applyShowProgress(data) {
  updateProgress(document.querySelector("[data-progress-summary]"), data);
  const showCard = document.querySelector(`.show-card[data-show-id="${data.show_id}"]`);
  if (showCard) {
    showCard.dataset.watchedCount = data.watched_count;
    showCard.dataset.episodeCount = data.episode_count;
    showCard.dataset.progress = data.percent;
    showCard.dataset.lastWatched = data.last_watched_at || "";
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
    invalidateWatchCaches({
      showId: data.show_id,
      episodeId: episode.dataset.episodeId,
    });
    updateEpisodeWatchUi(episode, data.watch_count);
    applyShowProgress(data);
    maybeOpenFinishedArchiveDialog(data);
    cacheCurrentSeasonEpisodes(episode.closest(".season"));
    cacheCurrentSeasons(data.show_id);
  } catch (_error) {
    showSnackbar("Couldn't update this episode. Try again.");
  } finally {
    pendingWatchChanges.delete(episode);
  }
}

function updateEpisodeDetailWatchUi(detailEpisode, watchCount) {
  detailEpisode.dataset.watchCount = watchCount;
  const control = detailEpisode.querySelector("[data-episode-detail-watch]");
  if (!control) return;
  control.dataset.watchCount = watchCount;
  control.querySelector("[data-episode-detail-watch-count]").textContent = watchCount;
  control.querySelector("[data-episode-detail-watch-label]").textContent =
    watchCount === 1 ? "watch" : "watches";
}

function removeEpisodeWatchActivity(recordId) {
  if (!recordId) return;
  const log = views.get("detail").querySelector("[data-activity-log]");
  const list = log?.querySelector("[data-activity-list]");
  list?.querySelector(`.activity-item[data-watch-kind="episode"][data-watch-record-id="${recordId}"]`)?.remove();
  if (list && !list.querySelector(".activity-item")) {
    const empty = document.createElement("li");
    empty.className = "activity-empty";
    empty.dataset.activityEmpty = "";
    empty.textContent = "This episode has not been watched yet.";
    list.append(empty);
  }
  syncActivityCount(log);
}

async function changeEpisodeDetailWatchCount(detailEpisode, action) {
  if (pendingWatchChanges.has(detailEpisode)) return;
  pendingWatchChanges.add(detailEpisode);
  try {
    const response = await fetch(`/api/episodes/${detailEpisode.dataset.episodeId}/watch-count`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    if (!response.ok) throw new Error("Could not update episode");
    const data = await response.json();
    invalidateWatchCaches({
      showId: data.show_id,
      episodeId: detailEpisode.dataset.episodeId,
    });
    updateEpisodeDetailWatchUi(detailEpisode, data.watch_count);
    applyShowProgress(data);
    maybeOpenFinishedArchiveDialog(data);
    if (data.action === "increment") {
      addActivityItem({
        type: "watched",
        title: "Watched",
        occurredAt: data.changed_at,
        recordId: String(data.watch_record_id),
        watchKind: "episode",
        addedAt: data.changed_at,
      });
    } else {
      removeEpisodeWatchActivity(data.watch_record_id);
    }
  } catch (_error) {
    showSnackbar("Couldn't update this episode. Try again.");
  } finally {
    pendingWatchChanges.delete(detailEpisode);
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
    invalidateWatchCaches({ showId: data.show_id, allEpisodes: true });
    if (season.dataset.episodesLoaded === "true") {
      data.episodes.forEach((episodeData) => {
        const episode = season.querySelector(`[data-episode-id="${episodeData.episode_id}"]`);
        if (episode) updateEpisodeWatchUi(episode, episodeData.watch_count, false);
      });
      syncSeasonFromEpisodes(season);
    } else {
      deleteSeasonEpisodesCache(season.dataset.seasonId);
      updateSeasonWatchSummary(
        season,
        data.season_episode_count,
        data.season_watched_count,
        data.season_min_watch_count,
      );
    }
    applyShowProgress(data);
    maybeOpenFinishedArchiveDialog(data);
    cacheCurrentSeasonEpisodes(season);
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

document.addEventListener("toggle", (event) => {
  const season = event.target.closest?.("details.season[data-season-id]");
  if (season?.open) loadSeasonEpisodes(season);
}, true);

document.addEventListener("pointerdown", (event) => {
  if (event.target.closest(".profile-chrome-handoff-clone [data-profile-back]")) {
    event.preventDefault();
  }
}, true);

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-menu-scrim]")) {
    closeShowMenus();
    closeWatchMenus();
    closeWatchLogMenus();
    closeTvDropdowns();
    return;
  }

  const profileTrigger = event.target.closest("[data-search-profile]");
  if (profileTrigger) {
    openProfileFromTrigger(profileTrigger);
    return;
  }

  if (event.target.closest("[data-profile-back]")) {
    event.preventDefault();
    leaveProfile();
    return;
  }

  const profileTab = event.target.closest("[data-profile-tab]");
  if (profileTab) {
    selectProfileTab(profileTab.dataset.profileTab);
    return;
  }

  const statisticsShow = event.target.closest("[data-stats-show-open]");
  if (statisticsShow) {
    detailParentView = "profile";
    openShow(statisticsShow.dataset.statsShowOpen, "profile");
    return;
  }

  const imageTrigger = event.target.closest("[data-full-image-src]");
  if (imageTrigger) {
    event.preventDefault();
    openImageViewer(imageTrigger);
    return;
  }

  if (event.target.closest("[data-image-viewer-close]")) {
    closeImageViewer();
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
    detailParentView = ["upcoming", "profile"].includes(currentView)
      ? currentView
      : "backlog";
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

  const trackMovieButton = event.target.closest("[data-track-movie-state]");
  if (trackMovieButton) {
    trackDetailMovie(
      trackMovieButton.closest("[data-detail-movie]"),
      trackMovieButton.dataset.trackMovieState,
      trackMovieButton,
    );
    return;
  }

  const catalogCardElement = event.target.closest(".popular-card[data-tmdb-id]");
  if (catalogCardElement && !event.target.closest("button")) {
    if (catalogCardElement.dataset.catalogType === "movies") previewCatalogMovie(catalogCardElement);
    else previewCatalogShow(catalogCardElement);
    return;
  }

  if (event.target.closest("[data-tv-search-retry]")) {
    const query = searchQueries.tv.trim();
    if (query) searchTvCatalog(query);
    return;
  }

  const watchLogMenuButton = event.target.closest("[data-watch-log-menu-button]");
  if (watchLogMenuButton) {
    const item = watchLogMenuButton.closest("[data-watch-record-id]");
    const menu = item?.querySelector("[data-watch-log-menu]");
    if (menu) {
      const diaryLabel = menu.querySelector("[data-watch-log-diary-action] span:last-child");
      const diaryIcon = menu.querySelector("[data-watch-log-diary-action] .material-symbols-rounded");
      if (diaryLabel) diaryLabel.textContent = item.dataset.showInDiary === "0" ? "Show in diary" : "Hide from diary";
      if (diaryIcon) diaryIcon.textContent = item.dataset.showInDiary === "0" ? "visibility" : "visibility_off";
      closeWatchLogMenus(menu);
      if (menu.hidden) {
        menuScrollLockPosition = { x: window.scrollX, y: window.scrollY };
        showFloatingMenu(menu, watchLogMenuButton);
      }
      else hideFloatingMenu(menu);
      syncMenuScrim();
    }
    return;
  }

  const watchLogSetDate = event.target.closest("[data-watch-log-set-date]");
  if (watchLogSetDate) {
    const item = watchLogSetDate.closest("[data-watch-record-id]");
    hideFloatingMenu(watchLogSetDate.closest("[data-watch-log-menu]"));
    syncMenuScrim();
    if (item) openWatchDatePicker(item);
    return;
  }

  const watchLogDiaryAction = event.target.closest("[data-watch-log-diary-action]");
  if (watchLogDiaryAction) {
    const item = watchLogDiaryAction.closest("[data-watch-record-id]");
    hideFloatingMenu(watchLogDiaryAction.closest("[data-watch-log-menu]"));
    syncMenuScrim();
    if (!item) return;
    const visible = item.dataset.showInDiary === "0";
    fetch(`/api/watch-history/${item.dataset.watchKind}/${item.dataset.watchRecordId}/diary`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ show_in_diary: visible }),
    }).then((response) => response.ok ? response.json() : Promise.reject())
      .then(() => {
        item.dataset.showInDiary = visible ? "1" : "0";
        syncDiaryHiddenIcon(item);
        diaryRevision += 1;
      })
      .catch(() => showSnackbar("Couldn't update the diary setting. Try again."));
    return;
  }

  const datePickerDay = event.target.closest("[data-date-picker-day]");
  if (datePickerDay) {
    datePickerSelectedDate = parseIsoDate(datePickerDay.dataset.datePickerDay);
    renderDatePicker();
    return;
  }

  const datePickerYear = event.target.closest("[data-date-picker-year]");
  if (datePickerYear) {
    datePickerMonth = new Date(
      Number(datePickerYear.dataset.datePickerYear),
      datePickerMonth.getMonth(),
      1,
    );
    datePickerYearVisible = false;
    renderDatePicker();
    return;
  }

  if (event.target.closest("[data-date-picker-year-toggle]")) {
    datePickerYearVisible = !datePickerYearVisible;
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

  const tvDropdownToggle = event.target.closest("[data-tv-dropdown-toggle]");
  if (tvDropdownToggle) {
    toggleTvDropdown(tvDropdownToggle);
    return;
  }

  const progressOption = event.target.closest("[data-tv-progress-option]");
  if (progressOption) {
    const preferences = libraryViewPreferences[currentView];
    if (!preferences) return;
    preferences.progress = progressOption.dataset.tvProgressOption;
    if (["backlog", "upcoming"].includes(currentView)) filterSchedule(currentView);
    else if (["tv", "movies"].includes(currentView)) filterShowView(views.get(currentView));
    else syncTvControlBar(views.get(currentView));
    return;
  }

  const mediaOption = event.target.closest("[data-tv-media-option]");
  if (mediaOption) {
    const preferences = libraryViewPreferences[currentView];
    if (!preferences) return;
    const type = mediaOption.dataset.tvMediaOption;
    preferences.mediaTypes = preferences.mediaTypes.includes(type)
      ? preferences.mediaTypes.filter((value) => value !== type)
      : [...preferences.mediaTypes, type];
    if (["backlog", "upcoming"].includes(currentView)) filterSchedule(currentView);
    else if (["tv", "movies"].includes(currentView)) filterShowView(views.get(currentView));
    syncTvControlBar(views.get(currentView));
    return;
  }

  if (event.target.closest("[data-tv-view-toggle]")) {
    toggleTvLayout();
    return;
  }

  const sortOption = event.target.closest("[data-tv-sort-option]");
  if (sortOption) {
    if (currentView === "upcoming") return;
    const preferences = libraryViewPreferences[currentView];
    if (!preferences) return;
    const nextField = sortOption.dataset.tvSortOption;
    if (preferences.sortField === nextField) {
      preferences.sortDirection = preferences.sortDirection === "asc" ? "desc" : "asc";
    } else {
      preferences.sortField = nextField;
      preferences.sortDirection = nextField === "name" ? "asc" : "desc";
    }
    if (currentView === "backlog") filterSchedule(currentView);
    else if (["tv", "movies"].includes(currentView)) filterShowView(views.get(currentView));
    else syncTvControlBar(views.get(currentView));
    return;
  }

  const libraryStateButton = event.target.closest("[data-tv-library-state]");
  if (libraryStateButton) {
    const preferences = libraryViewPreferences[currentView];
    if (!preferences) return;
    const nextState = libraryStateButton.dataset.tvLibraryState;
    if (preferences.state === nextState) return;
    preferences.state = nextState;
    if (currentView === "tv") {
      clearTvFirstReveal(views.get("tv"));
      filterShowView(views.get("tv"));
    } else {
      filterSchedule(currentView);
    }
    scrollPositions[currentView] = 0;
    window.scrollTo({ top: 0, behavior: "auto" });
    if (currentView === "tv") revealTvStateOnce(views.get("tv"));
    return;
  }

  const scheduleShowOpen = event.target.closest("[data-schedule-show-open]");
  if (scheduleShowOpen) {
    const card = scheduleShowOpen.closest("[data-schedule-card]");
    const openSeasonIds = card.dataset.seasonIds.split(",").filter(Boolean);
    const parentView = currentView === "profile" ? "profile" : "upcoming";
    detailParentView = parentView;
    openShow(card.dataset.showId, parentView, true, "push", {
      openSeasonIds,
      detailScrollY: 0,
    });
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
    const detailEpisode = wrapper.closest("[data-detail-episode]");
    closeWatchMenus();
    if (episode) changeEpisodeWatchCount(episode, watchAction.dataset.watchAction, watchAction);
    else if (season) changeSeasonWatchCount(season, watchAction.dataset.watchAction, watchAction);
    else if (detailEpisode) changeEpisodeDetailWatchCount(detailEpisode, watchAction.dataset.watchAction);
    return;
  }

  const episodeDetailControl = event.target.closest("[data-episode-detail-watch]");
  if (episodeDetailControl) {
    const detailEpisode = episodeDetailControl.closest("[data-detail-episode]");
    if (Number(detailEpisode.dataset.watchCount) === 0) {
      changeEpisodeDetailWatchCount(detailEpisode, "increment");
    } else {
      toggleWatchMenu(episodeDetailControl);
    }
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

  const movieMenuButton = event.target.closest("[data-movie-menu-button]");
  if (movieMenuButton) {
    toggleMovieMenu(movieMenuButton);
    return;
  }

  const seasonDiaryMenuButton = event.target.closest("[data-season-diary-menu-button]");
  if (seasonDiaryMenuButton) {
    const item = seasonDiaryMenuButton.closest("[data-watch-record-id]");
    const menu = item?.querySelector("[data-season-diary-menu]");
    if (menu) {
      const actionLabel = menu.querySelector("[data-season-diary-action] span:last-child");
      const actionIcon = menu.querySelector("[data-season-diary-action] .material-symbols-rounded");
      if (actionLabel) actionLabel.textContent = item.dataset.seasonDiaryState === "shown" ? "Hide from diary" : "Show in diary";
      if (actionIcon) actionIcon.textContent = item.dataset.seasonDiaryState === "shown" ? "visibility_off" : "visibility";
      closeWatchLogMenus(menu);
      if (menu.hidden) {
        menuScrollLockPosition = { x: window.scrollX, y: window.scrollY };
        showFloatingMenu(menu, seasonDiaryMenuButton);
      }
      else hideFloatingMenu(menu);
      syncMenuScrim();
    }
    return;
  }

  const seasonDiaryAction = event.target.closest("[data-season-diary-action]");
  if (seasonDiaryAction) {
    const item = seasonDiaryAction.closest("[data-watch-record-id]");
    const menu = seasonDiaryAction.closest("[data-season-diary-menu]");
    if (menu) hideFloatingMenu(menu);
    syncMenuScrim();
    if (!item) return;
    fetch(`/api/seasons/${item.dataset.seasonId}/diary`, { method: "PATCH" })
      .then((response) => response.ok ? response.json() : Promise.reject())
      .then((data) => {
        item.closest("[data-activity-log]")?.querySelectorAll(`[data-season-id="${data.season_id}"]`)
          .forEach((entry) => {
            entry.dataset.seasonDiaryState = data.show_in_diary ? "shown" : "hidden";
          });
        diaryRevision += 1;
      })
      .catch(() => showSnackbar("Couldn't update the diary setting. Try again."));
    return;
  }

  if (event.target.closest("[data-movie-search-retry]")) {
    const query = searchQueries.movies.trim();
    if (query) searchMovieCatalog(query);
    return;
  }

  const diaryMovieOpen = event.target.closest("[data-diary-movie-open]");
  if (diaryMovieOpen) {
    openMovie(diaryMovieOpen.closest("[data-movie-id]").dataset.movieId, "profile");
    return;
  }

  const movieWatchAction = event.target.closest("[data-movie-watch-action]");
  if (movieWatchAction) {
    const detailMovie = movieWatchAction.closest("[data-detail-movie]");
    closeWatchMenus();
    if (detailMovie) {
      const action = movieWatchAction.dataset.movieWatchAction;
      if (action === "mark-watched" || action === "mark-unwatched") {
        setMovieWatchedWithoutDiary(detailMovie, action === "mark-watched");
      } else {
        changeMovieWatchCount(detailMovie, action);
      }
    }
    return;
  }

  const movieWatchControl = event.target.closest("[data-movie-detail-watch]");
  if (movieWatchControl) {
    const detailMovie = movieWatchControl.closest("[data-detail-movie]");
    if (detailMovie) toggleWatchMenu(movieWatchControl);
    return;
  }

  const movieAction = event.target.closest("[data-movie-action]");
  if (movieAction) {
    const movieElement = movieAction.closest("[data-movie-id]");
    closeShowMenus();
    if (movieAction.dataset.movieAction === "move") moveMovie(movieElement, movieAction.dataset.targetState, movieAction);
    else requestMovieRemoval(movieElement);
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
    } else if (showAction.dataset.showAction === "mark-watched") {
      setShowWatchedWithoutDiary(showElement, showAction.dataset.watched === "true");
    } else {
      requestShowRemoval(showElement);
    }
    return;
  }

  if (event.target.closest("[data-cancel-remove]")) {
    removeDialog.close();
    pendingRemoveShowId = null;
    pendingRemoveMovieId = null;
    return;
  }

  if (event.target.closest("[data-confirm-remove]")) {
    if (pendingRemoveMovieId) confirmMovieRemoval();
    else confirmShowRemoval();
    return;
  }

  if (event.target.closest("[data-cancel-finished-archive]")) {
    finishedArchiveDialog.close();
    pendingFinishedArchiveShowId = null;
    return;
  }

  if (event.target.closest("[data-confirm-finished-archive]")) {
    confirmArchiveFinishedShow();
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

  const retryEpisodeButton = event.target.closest("[data-retry-episode]");
  if (retryEpisodeButton) {
    openEpisode(retryEpisodeButton.dataset.retryEpisode, null);
    return;
  }

  const retrySeasonEpisodes = event.target.closest("[data-retry-season-episodes]");
  if (retrySeasonEpisodes) {
    const season = retrySeasonEpisodes.closest(".season");
    deleteSeasonEpisodesCache(season.dataset.seasonId);
    loadSeasonEpisodes(season);
    return;
  }

  const episodeShowLink = event.target.closest("[data-episode-show-open]");
  if (episodeShowLink) {
    openShow(episodeShowLink.dataset.showId, detailParentView);
    return;
  }

  const adjacentEpisodeButton = event.target.closest("[data-adjacent-episode]");
  if (adjacentEpisodeButton) {
    navigateAdjacentEpisode(adjacentEpisodeButton);
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

  const movieOpenButton = event.target.closest("[data-movie-open]");
  if (movieOpenButton) {
    const movieCard = movieOpenButton.closest("[data-movie-id]");
    openMovie(movieCard.dataset.movieId, "movies");
    return;
  }

  closeShowMenus();
  closeWatchMenus();
  closeTvDropdowns();
});

document.addEventListener("keydown", (event) => {
  const scrollKeys = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " "]);
  if (menuScrim && !menuScrim.hidden && scrollKeys.has(event.key)) {
    if (event.key !== " " || !event.target.closest("button")) event.preventDefault();
  }
  if (event.key === "Escape" && menuScrim && !menuScrim.hidden) {
    closeShowMenus();
    closeWatchMenus();
    closeTvDropdowns();
    return;
  }

  const profileTab = event.target.closest("[data-profile-tab]");
  if (profileTab && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
    event.preventDefault();
    const tabs = [...profileTab.parentElement.querySelectorAll("[data-profile-tab]")];
    const currentIndex = tabs.indexOf(profileTab);
    const nextIndex = event.key === "Home" ? 0
      : event.key === "End" ? tabs.length - 1
        : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    selectProfileTab(tabs[nextIndex].dataset.profileTab, { focus: true });
    return;
  }
  const card = event.target.closest(".popular-card[data-tmdb-id]");
  if (!card || event.target.closest("button") || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  if (card.dataset.catalogType === "movies") previewCatalogMovie(card);
  else previewCatalogShow(card);
});

document.addEventListener("error", (event) => {
  if (event.target.matches?.("img[data-media-image]")) settleMediaImage(event.target, false);
}, true);

document.addEventListener("load", (event) => {
  if (event.target.matches?.("img[data-media-image]")) {
    const reveal = event.target.hasAttribute("data-media-image-pending");
    event.target.removeAttribute("data-media-image-pending");
    settleMediaImage(event.target, true, reveal);
  }
}, true);

document.querySelectorAll("img[data-media-image]").forEach(inspectCompletedMediaImage);

new MutationObserver((mutations) => {
  mutations.forEach((mutation) => mutation.addedNodes.forEach(inspectMediaImages));
}).observe(document.documentElement, { childList: true, subtree: true });

document.addEventListener("submit", (event) => {
  if (!event.target.matches("[data-view-search]")) return;
  event.preventDefault();
  if (!["tv", "movies"].includes(currentView)) return;
  const query = searchQueries[currentView].trim();
  if (!query) return;
  globalSearchInput?.blur();
  if (currentView === "tv") searchTvCatalog(query);
  else searchMovieCatalog(query);
});

function updateProgress(progress, data) {
  if (!progress) return;
  progress.querySelector("[data-progress-copy]").textContent =
    `${data.watched_count}/${data.episode_count}`;
  progress.querySelector("[data-progress-percent]").textContent = `${data.percent}%`;
  const bar = progress.querySelector(".progress-track");
  bar.setAttribute("aria-valuenow", data.percent);
  bar.querySelector("span").style.width = `${data.percent}%`;
}

function filterSchedule(viewName = currentView) {
  if (!["backlog", "upcoming"].includes(viewName)) return;
  const view = views.get(viewName);
  if (!view) return;
  const query = searchQueries[viewName].trim().toLocaleLowerCase();
  const preferences = libraryViewPreferences[viewName];
  const searching = Boolean(query);

  view.querySelectorAll("[data-schedule-panel]").forEach((panel) => {
    const cards = [...panel.querySelectorAll("[data-schedule-card]")];
    if (viewName === "backlog") {
      const list = panel.querySelector(".schedule-timeline-list");
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
      const matchesSearch = !query || card.dataset.scheduleSearchText?.includes(query);
      const matchesState = searching || (card.dataset.trackingState === TRACKING_STATE.ACTIVE
        ? preferences.mediaTypes.includes("tv")
        : preferences.mediaTypes.includes("archive"));
      const matchesProgress = searching || !preferences.progress
        || card.dataset.progressState === preferences.progress
        || (
          card.dataset.progressState === PROGRESS_STATE.FINISHED
          && preferences.progress === PROGRESS_STATE.CAUGHT_UP
        );
      const visible = matchesSearch && matchesState && matchesProgress;
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    panel.querySelectorAll("[data-upcoming-month]").forEach((month) => {
      month.hidden = ![...month.querySelectorAll("[data-schedule-card]")]
        .some((card) => !card.hidden);
    });

    const empty = panel.querySelector("[data-schedule-empty]");
    const noResults = panel.querySelector("[data-schedule-no-results]");
    if (empty) empty.hidden = searching || visibleCount > 0;
    if (noResults) noResults.hidden = !query || visibleCount > 0 || cards.length === 0;
  });
  if (viewName === currentView) syncTvControlVisibility();
}

function filterShowView(view) {
  if (!view) return;
  const preferences = libraryViewPreferences[view.dataset.view];
  if (!preferences) return;
  const query = searchQueries[view.dataset.view].trim().toLocaleLowerCase();
  const searching = ["tv", "movies"].includes(view.dataset.view) && Boolean(query);
  view.classList.toggle("is-searching", searching);
  view.querySelectorAll("[data-state-section]").forEach((section) => {
    const state = section.dataset.stateSection;
    const stateSelected = searching || (state === TRACKING_STATE.ACTIVE
      ? preferences.mediaTypes.includes(view.dataset.view === "movies" ? "movies" : "tv")
      : preferences.mediaTypes.includes("archive"));
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
      const matchesProgress = searching || !preferences.progress
        || card.dataset.progressState === preferences.progress
        || (
          card.dataset.progressState === PROGRESS_STATE.FINISHED
          && preferences.progress === PROGRESS_STATE.CAUGHT_UP
        );
      const visible = stateSelected && matchesSearch && matchesProgress;
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    section.hidden = searching ? visibleCount === 0 : !stateSelected;
    const count = section.querySelector("[data-state-count]");
    if (count) count.textContent = searching ? visibleCount : cards.length;
  });
  if (view.dataset.view === currentView) syncTvControlVisibility();
  hydratedLibraryViews.add(view.dataset.view);
  if (view.dataset.view === "tv") syncTvSearchPresentation();
  if (view.dataset.view === "movies") syncMovieSearchPresentation();
}

function filterAllShowViews() {
  filterShowView(views.get("tv"));
}

globalSearchInput?.addEventListener("input", () => {
  if (currentView === "detail") return;
  syncSearchChrome();
  syncSearchTextPosition();
  const query = globalSearchInput.value;
  const previousQuery = searchQueries[currentView];
  searchQueries[currentView] = query;
  if (["backlog", "upcoming"].includes(currentView)) {
    filterSchedule(currentView);
  } else if (currentView === "tv") {
    filterShowView(views.get(currentView));
    if (!query.trim()) {
      window.requestAnimationFrame(() => revealTvStateOnce(views.get("tv")));
    }
    clearTimeout(tvSearchTimer);
    if (tvSearchRequest) tvSearchRequest.abort();
    tvSearchPending = false;
    tvSearchComplete = false;
    tvSearchError = "";
    clearTvCatalogResults();
    syncTvSearchPresentation();
    if (previousQuery.trim() && !query.trim()) flushSearchLibraryUpdates("tv");
  } else if (currentView === "movies") {
    filterShowView(views.get("movies"));
    clearTimeout(movieSearchTimer);
    movieSearchRequest?.abort();
    movieSearchPending = false;
    movieSearchComplete = false;
    movieSearchError = "";
    views.get("movies")?.querySelector("[data-movie-add-results]")?.replaceChildren();
    syncMovieSearchPresentation();
    if (previousQuery.trim() && !query.trim()) flushSearchLibraryUpdates("movies");
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

window.addEventListener("resize", () => {
  syncSearchTextPosition();
  fitEpisodeDetailTitle(views.get("detail"));
});

window.addEventListener("focus", refreshScheduleForLocalDayChange);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") refreshScheduleForLocalDayChange();
});

window.addEventListener("scroll", () => {
  const currentScrollY = window.scrollY;
  if (currentView === "detail") {
    const switcher = views.get("detail")?.querySelector("[data-episode-navigation]");
    if (!switcher) return;
    if (currentScrollY > lastEpisodeDetailScrollY) switcher.classList.add("is-scroll-hidden");
    else if (currentScrollY < lastEpisodeDetailScrollY) switcher.classList.remove("is-scroll-hidden");
    lastEpisodeDetailScrollY = currentScrollY;
    return;
  }
  if (currentView === "profile") keepProfileChromeAtViewportEdge();
}, { passive: true });
const finishInitialSearchTextPosition = () => {
  syncSearchTextPosition();
  window.requestAnimationFrame(() => {
    document.documentElement.classList.add("search-text-position-animation-ready");
  });
};
if (document.fonts?.ready) document.fonts.ready.then(finishInitialSearchTextPosition);
else finishInitialSearchTextPosition();

filterAllShowViews();
filterSchedule("backlog");
filterSchedule("upcoming");
formatDisplayDates(document);
syncGlobalSearch();
initializeDiaryPagination();

removeDialog?.addEventListener("close", () => {
  pendingRemoveShowId = null;
  pendingRemoveMovieId = null;
  document.documentElement.classList.remove("remove-dialog-open");
});

removeDialog?.addEventListener("click", (event) => {
  if (event.target === removeDialog) removeDialog.close();
});

finishedArchiveDialog?.addEventListener("close", () => {
  pendingFinishedArchiveShowId = null;
});

datePicker?.addEventListener("close", () => {
  datePickerTarget = null;
  datePickerSelectedDate = null;
  datePickerYearVisible = false;
});

imageViewer?.addEventListener("click", (event) => {
  if (event.target === imageViewer || event.target === imageViewerStage) closeImageViewer();
});

imageViewer?.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeImageViewer();
});

imageViewer?.addEventListener("close", () => {
  document.documentElement.classList.remove("image-viewer-open");
  clearImageViewerMotion();
  imageViewerPreview?.removeAttribute("src");
  imageViewerPreview?.removeAttribute("hidden");
  imageViewerImage?.removeAttribute("src");
  imageViewerStage?.classList.remove("is-loaded", "has-error", "has-preview");
  imageViewerStage?.style.removeProperty("--image-viewer-width");
  imageViewerStage?.style.removeProperty("--image-viewer-height");
  imageViewer?.classList.remove("is-opening", "is-closing");
  imageViewerAspectRatio = null;
  imageViewerClosing = false;
});

window.addEventListener("resize", () => {
  if (imageViewer?.open) sizeImageViewerLayers();
});

function restoreHistoryState(state) {
  if (!state?.trackApp) return;
  closeShowMenus();
  closeWatchMenus();
  if (detailRequest) detailRequest.abort();

  const legacyViews = { schedule: "backlog", watching: "tv", archive: "tv", discover: "tv" };
  const restoredView = legacyViews[state.view] || state.view;
  if (restoredView === "profile") {
    const restoredParent = legacyViews[state.parentView] || state.parentView;
    profileParentView = ["backlog", "upcoming", "tv", "movies"].includes(restoredParent)
      ? restoredParent
      : "backlog";
    showView("profile");
    return;
  }
  if (restoredView !== "detail") {
    if (currentView === "profile") {
      transitionProfileView(() => showView(restoredView), "return");
    } else {
      showView(restoredView);
    }
    return;
  }

  const restoredParent = legacyViews[state.parentView] || state.parentView;
  detailParentView = ["backlog", "upcoming", "tv", "movies", "profile"].includes(restoredParent)
    ? restoredParent
    : "backlog";
  if (state.detailType === "show" && state.showId) {
    openShow(state.showId, detailParentView, true, null, state);
  } else if (state.detailType === "movie" && state.movieId) {
    openMovie(state.movieId, detailParentView, null);
  } else if (state.detailType === "episode" && state.episodeId) {
    openEpisode(state.episodeId, null);
  } else if (state.detailType === "catalog" && state.tmdbId) {
    const card = document.querySelector(`.popular-card[data-tmdb-id="${state.tmdbId}"]`);
    if (card) previewCatalogShow(card, null);
    else showView("tv");
  } else if (state.detailType === "movieCatalog" && state.tmdbId) {
    const card = document.querySelector(`.popular-card[data-tmdb-id="${state.tmdbId}"]`);
    if (card) previewCatalogMovie(card, null);
    else showView("movies");
  } else {
    showView(detailParentView);
  }
}

window.addEventListener("popstate", (event) => {
  if (tvDropdownHistoryActive) {
    tvDropdownHistoryActive = false;
    closeTvDropdowns(null, { preserveHistory: true });
  }
  restoreHistoryState(event.state);
});

if (window.history.state?.trackApp && window.history.state.view !== "backlog") {
  restoreHistoryState(window.history.state);
}

if (["backlog", "upcoming"].includes(currentView)
  && !revealedViewAnimations.has(currentView)) {
  revealedViewAnimations.add(currentView);
  staggerScheduleFirstReveal(views.get(currentView));
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
