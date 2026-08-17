const views = new Map(
  [...document.querySelectorAll("[data-view]")].map((view) => [view.dataset.view, view]),
);
const navButtons = [...document.querySelectorAll("[data-nav-view]")];
const scrollPositions = { shows: 0, discover: 0, detail: 0 };
let currentView = "shows";
let detailRequest = null;

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

document.addEventListener("click", (event) => {
  const navButton = event.target.closest("[data-nav-view]");
  if (navButton) {
    if (detailRequest) detailRequest.abort();
    showView(navButton.dataset.navView);
    return;
  }

  const showCard = event.target.closest("[data-show-id]");
  if (showCard) {
    openShow(showCard.dataset.showId);
    return;
  }

  if (event.target.closest("[data-detail-back]")) {
    if (detailRequest) detailRequest.abort();
    showView("shows");
    return;
  }

  const retryButton = event.target.closest("[data-retry-show]");
  if (retryButton) openShow(retryButton.dataset.retryShow);
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

document.querySelector("[data-library-search]")?.addEventListener("input", (event) => {
  const query = event.target.value.trim().toLocaleLowerCase();
  const cards = [...document.querySelectorAll("[data-view='shows'] .show-card")];
  let visibleCount = 0;
  cards.forEach((card) => {
    const visible = card.dataset.showName.includes(query);
    card.hidden = !visible;
    if (visible) visibleCount += 1;
  });
  const noResults = document.querySelector("[data-library-no-results]");
  if (noResults) noResults.hidden = visibleCount > 0;
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

function showSnackbar(message) {
  const snackbar = document.querySelector(".snackbar");
  if (!snackbar) return;
  snackbar.textContent = message;
  snackbar.hidden = false;
  clearTimeout(showSnackbar.timer);
  showSnackbar.timer = setTimeout(() => { snackbar.hidden = true; }, 2600);
}
