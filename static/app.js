const views = new Map(
  [...document.querySelectorAll("[data-view]")].map((view) => [view.dataset.view, view]),
);
const navButtons = [...document.querySelectorAll("[data-nav-view]")];
const scrollPositions = { shows: 0, discover: 0, detail: 0 };
const removeDialog = document.querySelector("[data-remove-dialog]");
let currentView = "shows";
let detailRequest = null;
let pendingRemoveShowId = null;

function showView(viewName) {
  if (!views.has(viewName) || viewName === currentView) return;

  scrollPositions[currentView] = window.scrollY;
  views.forEach((view, name) => {
    const active = name === viewName;
    view.hidden = !active;
    view.classList.toggle("is-active", active);
  });

  const navView = viewName === "detail" ? "shows" : viewName;
  navButtons.forEach((button) => {
    const active = button.dataset.navView === navView;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });

  currentView = viewName;
  document.title = viewName === "discover" ? "Discover · Track" : "Track";
  window.scrollTo({ top: scrollPositions[viewName] || 0, behavior: "auto" });
}

function renderDetailSkeleton() {
  const detailView = views.get("detail");
  const template = document.querySelector("#detail-skeleton-template");
  detailView.replaceChildren(template.content.cloneNode(true));
}

async function openShow(showId) {
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
        <button class="icon-button" type="button" data-detail-back aria-label="Back to My Shows">
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
  });
}

function syncStateSections() {
  document.querySelectorAll("[data-state-section]").forEach((section) => {
    const state = section.dataset.stateSection;
    const count = section.querySelectorAll(".show-card").length;
    section.querySelector("[data-state-count]").textContent = count;
    section.querySelector("[data-state-empty]").hidden = count > 0;
    if (state === "ARCHIVED") section.hidden = count === 0;
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
    syncStateSections();
    filterLibrary();
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
      showView("shows");
      views.get("detail").replaceChildren();
    }
    syncStateSections();
    filterLibrary();
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
    showView("shows");
    return;
  }

  const retryButton = event.target.closest("[data-retry-show]");
  if (retryButton) {
    openShow(retryButton.dataset.retryShow);
    return;
  }

  const showOpenButton = event.target.closest("[data-show-open]");
  if (showOpenButton) {
    openShow(showOpenButton.closest("[data-show-id]").dataset.showId);
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

    updateProgress(document.querySelector("[data-progress-summary]"), data);

    const season = episode.closest(".season");
    const checked = season.querySelectorAll(".episode-checkbox:checked").length;
    const total = season.querySelectorAll(".episode-checkbox").length;
    season.querySelector(".season-title small").textContent = `${checked} of ${total}`;

    const showCard = document.querySelector(`[data-show-id="${data.show_id}"]`);
    if (showCard) {
      showCard.querySelector("[data-card-progress-copy]").textContent =
        `${data.watched_count} of ${data.episode_count}`;
      const cardProgress = showCard.querySelector("[data-card-progress]");
      cardProgress.setAttribute("aria-valuenow", data.percent);
      cardProgress.querySelector("span").style.width = `${data.percent}%`;
      showCard.querySelector(".progress-copy strong").textContent = `${data.percent}%`;
      showCard.querySelector("[data-progress-tag]").textContent = data.watched_count === 0
        ? "Haven't started"
        : data.watched_count >= data.episode_count ? "Finished" : "In progress";
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

function filterLibrary() {
  const query = document.querySelector("[data-library-search]")
    ?.value.trim().toLocaleLowerCase() || "";
  const cards = [...document.querySelectorAll("[data-view='shows'] .show-card")];
  let visibleCount = 0;
  cards.forEach((card) => {
    const visible = card.dataset.showName.includes(query);
    card.hidden = !visible;
    if (visible) visibleCount += 1;
  });
  const noResults = document.querySelector("[data-library-no-results]");
  if (noResults) noResults.hidden = visibleCount > 0 || cards.length === 0;
}

document.querySelector("[data-library-search]")?.addEventListener("input", filterLibrary);

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

function showSnackbar(message) {
  const snackbar = document.querySelector(".snackbar");
  if (!snackbar) return;
  snackbar.textContent = message;
  snackbar.hidden = false;
  clearTimeout(showSnackbar.timer);
  showSnackbar.timer = setTimeout(() => { snackbar.hidden = true; }, 2600);
}
