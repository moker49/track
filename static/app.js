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
    const progress = document.querySelector("[data-progress-summary]");
    if (progress) {
      progress.querySelector("[data-progress-copy]").textContent =
        `${data.watched_count} of ${data.episode_count}`;
      const bar = progress.querySelector(".progress-track");
      bar.setAttribute("aria-valuenow", data.percent);
      bar.querySelector("span").style.width = `${data.percent}%`;
    }

    const season = episode.closest(".season");
    const checked = season.querySelectorAll(".episode-checkbox:checked").length;
    const total = season.querySelectorAll(".episode-checkbox").length;
    season.querySelector(".season-title small").textContent = `${checked} of ${total}`;
    showSnackbar(data.watched ? "Episode marked watched" : "Episode marked unwatched");
  } catch (_error) {
    checkbox.checked = !wantedState;
    showSnackbar("Couldn't save. Try again.");
  } finally {
    checkbox.disabled = false;
  }
});

document.querySelector("[data-library-search]")?.addEventListener("input", (event) => {
  const query = event.target.value.trim().toLocaleLowerCase();
  document.querySelectorAll(".show-card").forEach((card) => {
    card.hidden = !card.dataset.showName.includes(query);
  });
});

function showSnackbar(message) {
  const snackbar = document.querySelector(".snackbar");
  if (!snackbar) return;
  snackbar.textContent = message;
  snackbar.hidden = false;
  clearTimeout(showSnackbar.timer);
  showSnackbar.timer = setTimeout(() => { snackbar.hidden = true; }, 2600);
}
