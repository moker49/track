const views = new Map(
  [...document.querySelectorAll("[data-view]")].map((view) => [view.dataset.view, view]),
);
const navButtons = [...document.querySelectorAll("[data-nav-view]")];
const scrollPositions = { watching: 0, archive: 0, discover: 0, detail: 0 };
const removeDialog = document.querySelector("[data-remove-dialog]");
let currentView = "watching";
let detailParentView = "watching";
let detailRequest = null;
let pendingRemoveShowId = null;

function updateActiveNav(navView) {
  navButtons.forEach((button) => {
    const active = button.dataset.navView === navView;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function showView(viewName) {
  if (!views.has(viewName) || viewName === currentView) return;

  scrollPositions[currentView] = window.scrollY;
  views.forEach((view, name) => {
    const active = name === viewName;
    view.hidden = !active;
    view.classList.toggle("is-active", active);
  });

  updateActiveNav(viewName === "detail" ? detailParentView : viewName);
  currentView = viewName;
  const titles = {
    watching: "Watching · Track",
    archive: "Archive · Track",
    discover: "Discover · Track",
    detail: "Track",
  };
  document.title = titles[viewName] || "Track";
  window.scrollTo({ top: scrollPositions[viewName] || 0, behavior: "auto" });
}

function renderDetailSkeleton() {
  const detailView = views.get("detail");
  const template = document.querySelector("#detail-skeleton-template");
  detailView.replaceChildren(template.content.cloneNode(true));
}

function formatLocalTimes(root = document) {
  root.querySelectorAll("[data-local-datetime]").forEach((time) => {
    const date = new Date(time.dateTime);
    if (Number.isNaN(date.getTime())) return;
    time.textContent = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(date);
  });
}

function finishDetailLoad() {
  const detailView = views.get("detail");
  formatLocalTimes(detailView);
  const title = detailView.querySelector("[data-detail-title]")?.dataset.detailTitle;
  if (title) document.title = `${title} \u00B7 Track`;
  window.scrollTo({ top: 0, behavior: "auto" });
}

function prepareDetailLoad() {
  if (detailRequest) detailRequest.abort();
  detailRequest = new AbortController();
  renderDetailSkeleton();
  scrollPositions.detail = 0;
  if (currentView === "detail") window.scrollTo({ top: 0, behavior: "auto" });
  else showView("detail");
}

async function openShow(showId, parentView = currentView) {
  detailParentView = parentView === "archive" ? "archive" : "watching";
  prepareDetailLoad();

  try {
    const response = await fetch(`/api/shows/${showId}`, {
      headers: { "X-Requested-With": "Track" },
      signal: detailRequest.signal,
    });
    if (!response.ok) throw new Error("Could not load show");
    views.get("detail").innerHTML = await response.text();
    finishDetailLoad();
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

async function openEpisode(episodeId) {
  prepareDetailLoad();

  try {
    const response = await fetch(`/api/episodes/${episodeId}`, {
      headers: { "X-Requested-With": "Track" },
      signal: detailRequest.signal,
    });
    if (!response.ok) throw new Error("Could not load episode");
    views.get("detail").innerHTML = await response.text();
    finishDetailLoad();
  } catch (error) {
    if (error.name === "AbortError") return;
    views.get("detail").innerHTML = `
      <header class="detail-app-bar">
        <button class="icon-button" type="button" data-detail-back aria-label="Back">
          <span class="material-symbols-rounded" aria-hidden="true">arrow_back</span>
        </button>
        <span>Episode</span>
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
  log.querySelector("[data-activity-count]").textContent = count;
  log.querySelector("[data-activity-count-label]").textContent = count === 1 ? "entry" : "entries";
}

function addActivityItem({ type, title, occurredAt, seasonId = null }) {
  const log = views.get("detail").querySelector("[data-activity-log]");
  const list = log?.querySelector("[data-activity-list]");
  if (!list || !occurredAt) return;

  list.querySelector("[data-activity-empty]")?.remove();
  const item = document.createElement("li");
  item.className = "activity-item";
  item.dataset.activityType = type;
  if (seasonId) item.dataset.seasonId = seasonId;

  const icon = document.createElement("span");
  icon.className = "material-symbols-rounded activity-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = {
    archived: "archive",
    unarchived: "unarchive",
    season_watched: "done_all",
  }[type] || "history";

  const copy = document.createElement("span");
  copy.className = "activity-copy";
  const heading = document.createElement("strong");
  heading.textContent = title;
  const time = document.createElement("time");
  time.dateTime = occurredAt;
  time.dataset.localDatetime = "";
  time.textContent = occurredAt;
  copy.append(heading, time);
  item.append(icon, copy);
  list.prepend(item);
  formatLocalTimes(item);
  syncActivityCount(log);
}

function removeLatestSeasonActivity(seasonId) {
  const log = views.get("detail").querySelector("[data-activity-log]");
  log?.querySelector(`.activity-item[data-activity-type="season_watched"][data-season-id="${seasonId}"]`)?.remove();
  syncActivityCount(log);
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

  let progressState = "in-progress";
  let progressLabel = "In progress";
  if (watchedCount === 0) {
    progressState = "not-started";
    progressLabel = "Haven't started";
  } else if (episodeCount > 0 && watchedCount >= episodeCount) {
    progressState = "finished";
    progressLabel = "Finished";
  } else if (showElement.dataset.showState === "ARCHIVED") {
    progressState = "stopped";
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
    const detailStateLabel = showElement.querySelector("[data-show-state-label]");
    if (detailStateLabel) {
      detailStateLabel.textContent = state === "ARCHIVED" ? "Archived" : "Watching";
    }
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
    detailParentView = data.state === "ARCHIVED" ? "archive" : "watching";
    if (currentView === "detail") updateActiveNav(detailParentView);
    syncStateSections();
    filterAllShowViews();
    showSnackbar(data.state === "ARCHIVED" ? "Show archived" : "Show returned to watching");
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
  const confirmButton = removeDialog.querySelector("[data-confirm-remove]");
  confirmButton.disabled = true;
  try {
    const response = await fetch(`/api/shows/${showId}`, { method: "DELETE" });
    if (!response.ok) throw new Error("Could not remove show");
    document.querySelector(`.show-card[data-show-id="${showId}"]`)?.remove();
    if (views.get("detail").querySelector(`[data-show-id="${showId}"]`)) {
      showView(detailParentView);
      views.get("detail").replaceChildren();
    }
    syncStateSections();
    filterAllShowViews();
    removeDialog.close();
    pendingRemoveShowId = null;
    showSnackbar("Show removed");
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
  season.querySelector(".season-title small").textContent = `${watchedCount} of ${episodes.length}`;
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
}

async function changeEpisodeWatchCount(episode, action, trigger) {
  trigger.disabled = true;
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
  } catch (_error) {
    showSnackbar("Couldn't update this episode. Try again.");
  } finally {
    trigger.disabled = false;
  }
}

async function changeSeasonWatchCount(season, action, trigger) {
  trigger.disabled = true;
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
      });
    } else {
      removeLatestSeasonActivity(String(data.season_id));
    }
  } catch (_error) {
    showSnackbar("Couldn't update this season. Try again.");
  } finally {
    trigger.disabled = false;
  }
}

document.addEventListener("click", (event) => {
  const navButton = event.target.closest("[data-nav-view]");
  if (navButton) {
    closeShowMenus();
    closeWatchMenus();
    if (detailRequest) detailRequest.abort();
    showView(navButton.dataset.navView);
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
    if (detailBackButton.dataset.backShowId) {
      openShow(detailBackButton.dataset.backShowId, detailParentView);
    } else {
      showView(detailParentView);
    }
    return;
  }

  const retryButton = event.target.closest("[data-retry-show]");
  if (retryButton) {
    openShow(retryButton.dataset.retryShow, detailParentView);
    return;
  }

  const retryEpisodeButton = event.target.closest("[data-retry-episode]");
  if (retryEpisodeButton) {
    openEpisode(retryEpisodeButton.dataset.retryEpisode);
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
    const parentView = showCard.dataset.showState === "ARCHIVED" ? "archive" : "watching";
    openShow(showCard.dataset.showId, parentView);
    return;
  }

  closeShowMenus();
  closeWatchMenus();
});

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

function filterShowView(input) {
  const view = input?.closest("[data-view]");
  if (!view) return;
  const query = input.value.trim().toLocaleLowerCase();
  const cards = [...view.querySelectorAll(".show-card")];
  let visibleCount = 0;
  cards.forEach((card) => {
    const visible = card.dataset.showName.includes(query);
    card.hidden = !visible;
    if (visible) visibleCount += 1;
  });
  const noResults = view.querySelector("[data-library-no-results]");
  if (noResults) noResults.hidden = visibleCount > 0 || cards.length === 0;
}

function filterAllShowViews() {
  document.querySelectorAll("[data-show-search]").forEach(filterShowView);
}

document.querySelectorAll("[data-show-search]").forEach((input) => {
  input.addEventListener("input", () => filterShowView(input));
});

document.querySelector("[data-discover-search]")?.addEventListener("input", (event) => {
  const query = event.target.value.trim();
  const notice = document.querySelector("[data-discover-notice]");
  notice.hidden = !query;
  notice.querySelector("[data-discover-copy]").textContent = query
    ? `“${query}” will return remote results once the API is connected.`
    : "";
});

document.querySelectorAll(".app-bar-search").forEach((searchForm) => {
  const input = searchForm.querySelector('input[type="search"]');
  const clearButton = searchForm.querySelector("[data-clear-search]");
  if (!input || !clearButton) return;

  const syncClearButton = () => {
    clearButton.hidden = input.value.length === 0;
  };

  input.addEventListener("input", syncClearButton);
  clearButton.addEventListener("click", () => {
    input.value = "";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  });
  syncClearButton();
});

removeDialog?.addEventListener("close", () => {
  pendingRemoveShowId = null;
});

function showSnackbar(message) {
  const snackbar = document.querySelector(".snackbar");
  if (!snackbar) return;
  snackbar.textContent = message;
  snackbar.hidden = false;
  clearTimeout(showSnackbar.timer);
  showSnackbar.timer = setTimeout(() => { snackbar.hidden = true; }, 2600);
}
