const views = new Map(
  [...document.querySelectorAll("[data-view]")].map((view) => [view.dataset.view, view]),
);
const navButtons = [...document.querySelectorAll("[data-nav-view]")];
const scrollPositions = { watching: 0, archive: 0, discover: 0, detail: 0 };
const removeDialog = document.querySelector("[data-remove-dialog]");
const datePicker = document.querySelector("[data-date-picker]");
let currentView = "watching";
let detailParentView = "watching";
let detailRequest = null;
let pendingRemoveShowId = null;
let datePickerTarget = null;
let datePickerSelectedDate = null;
let datePickerMonth = new Date();

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

function finishDetailLoad() {
  const detailView = views.get("detail");
  formatDisplayDates(detailView);
  const title = detailView.querySelector("[data-detail-title]")?.dataset.detailTitle;
  if (title) document.title = `${title} \u00B7 Track`;
  window.scrollTo({ top: 0, behavior: "auto" });
}

function prepareDetailLoad(title) {
  if (detailRequest) detailRequest.abort();
  detailRequest = new AbortController();
  renderDetailSkeleton(title);
  scrollPositions.detail = 0;
  if (currentView === "detail") window.scrollTo({ top: 0, behavior: "auto" });
  else showView("detail");
}

async function openShow(showId, parentView = currentView) {
  detailParentView = parentView === "archive" ? "archive" : "watching";
  prepareDetailLoad("Show details");

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
  prepareDetailLoad("Episode details");

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
    unarchived: "unarchive",
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
    datePicker.close();
  } catch (_error) {
    showSnackbar("Couldn't update the watch date. Try again.");
  } finally {
    saveButton.disabled = false;
  }
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
        recordId: String(data.season_watch_record_id),
        watchKind: "season",
        addedAt: data.season_watched_at,
      });
    } else {
      removeSeasonActivity(String(data.season_watch_record_id));
    }
  } catch (_error) {
    showSnackbar("Couldn't update this season. Try again.");
  } finally {
    trigger.disabled = false;
  }
}

document.addEventListener("click", (event) => {
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

datePicker?.addEventListener("close", () => {
  datePickerTarget = null;
  datePickerSelectedDate = null;
});

function showSnackbar(message) {
  const snackbar = document.querySelector(".snackbar");
  if (!snackbar) return;
  snackbar.textContent = message;
  snackbar.hidden = false;
  clearTimeout(showSnackbar.timer);
  showSnackbar.timer = setTimeout(() => { snackbar.hidden = true; }, 2600);
}
