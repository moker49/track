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

async function openShow(showId, parentView = currentView) {
  detailParentView = parentView === "archive" ? "archive" : "watching";
  if (detailRequest) detailRequest.abort();
  detailRequest = new AbortController();

  renderDetailSkeleton();
  scrollPositions.detail = 0;
  showView("detail");

  try {
    const response = await fetch(`/api/shows/${showId}`, {
      headers: { "X-Requested-With": "Track" },
      signal: detailRequest.signal,
    });
    if (!response.ok) throw new Error("Could not load show");
    views.get("detail").innerHTML = await response.text();
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
  closeShowMenus(menu);
  menu.hidden = !willOpen;
  button.setAttribute("aria-expanded", String(willOpen));
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

document.addEventListener("click", (event) => {
  const navButton = event.target.closest("[data-nav-view]");
  if (navButton) {
    closeShowMenus();
    if (detailRequest) detailRequest.abort();
    showView(navButton.dataset.navView);
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

  if (event.target.closest("[data-detail-back]")) {
    closeShowMenus();
    if (detailRequest) detailRequest.abort();
    showView(detailParentView);
    return;
  }

  const retryButton = event.target.closest("[data-retry-show]");
  if (retryButton) {
    openShow(retryButton.dataset.retryShow, detailParentView);
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
});

document.addEventListener("submit", (event) => {
  if (event.target.matches("[data-view-search]")) event.preventDefault();
});

document.addEventListener("change", async (event) => {
  const checkbox = event.target.closest(".episode-checkbox");
  if (!checkbox) return;

  const episode = checkbox.closest(".episode");
  const wantedState = checkbox.checked;
  checkbox.disabled = true;

  try {
    const response = await fetch(`/api/episodes/${episode.dataset.episodeId}/watched`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ watched: wantedState }),
    });
    if (!response.ok) throw new Error("Could not update episode");
    const data = await response.json();

    episode.classList.toggle("is-watched", data.watched);
    updateProgress(document.querySelector("[data-progress-summary]"), data);

    const season = episode.closest(".season");
    const checked = season.querySelectorAll(".episode-checkbox:checked").length;
    const total = season.querySelectorAll(".episode-checkbox").length;
    season.querySelector(".season-title small").textContent = `${checked} of ${total}`;

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
  } catch (_error) {
    checkbox.checked = !wantedState;
    showSnackbar("Couldn't save. Try again.");
  } finally {
    checkbox.disabled = false;
  }
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
