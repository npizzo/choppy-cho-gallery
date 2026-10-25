"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  let snapshot = null;
  let selectedCase = "pilot";
  let selectedClip = "surface_startup";
  const stateLabels = {
    awaiting_sync: "Awaiting first sync",
    partial: "Partial output",
    outputs_available: "Outputs available"
  };
  const finite = (n) => typeof n === "number" && Number.isFinite(n);
  const number = (n, digits = 3) => finite(n) ? Number(n.toPrecision(digits)).toLocaleString("en", {maximumSignificantDigits: digits}) : "—";
  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function assetPath(value) {
    if (typeof value !== "string" || !/^(media|data)\/[A-Za-z0-9_./-]+$/.test(value)) return null;
    if (value.split("/").some((p) => p === ".." || p === "." || p === "")) return null;
    return value;
  }
  function applyStatus(el, value) {
    const state = Object.hasOwn(stateLabels, value) ? value : "awaiting_sync";
    el.className = `status ${state}`;
    el.textContent = stateLabels[state];
  }
  function resourceLink(title, path) {
    const src = assetPath(path);
    if (!src) return null;
    const a = node("a", "", title);
    a.href = src;
    return a;
  }
  function pauseMovies() {
    document.querySelectorAll("video").forEach((video) => video.pause());
  }
  function renderSnapshot(data) {
    snapshot = data;
    applyStatus($("campaign-status"), data.status);
    $("campaign-title").textContent = data.title || "Choppy waves + Cho";
    $("campaign-description").textContent = data.status_text || "The latest simulation output has not yet been synchronized.";
    const cases = data.cases.filter((entry) => entry && ["pilot", "prescribed"].includes(entry.id));
    if (!cases.some((entry) => entry.id === selectedCase)) selectedCase = cases[0]?.id || "pilot";
    const ready = cases.filter((entry) => entry.status === "outputs_available").length;
    $("result-count").textContent = ready ? `${ready} of ${cases.length} cases with outputs`
      : cases.some((entry) => entry.status === "partial") ? "Partial output available" : "Outputs not yet imported";
    const experiment = data.experiment || {};
    const stat = (id, value, unit) => {
      if (!finite(value)) return;
      $(id).replaceChildren(document.createTextNode(number(value)), node("span", "", unit));
    };
    stat("wavelength", finite(experiment.wavelength_m) ? experiment.wavelength_m * 100 : null, "cm");
    stat("steepness", experiment.initial_steepness, "");
    stat("viscosity", experiment.damping_multiplier, "× molecular");
    stat("duration", experiment.duration_s, "s");
    const controls = $("case-controls");
    controls.replaceChildren();
    for (const entry of cases) {
      const button = node("button", "", entry.id === "pilot" ? "Two-way parent / current" : "Prescribed parent");
      button.type = "button";
      button.setAttribute("aria-pressed", String(entry.id === selectedCase));
      button.addEventListener("click", () => {
        selectedCase = entry.id;
        renderSnapshot(snapshot);
      });
      controls.append(button);
    }
    const notes = $("notes");
    if (Array.isArray(data.notes) && data.notes.length) {
      notes.replaceChildren(...data.notes.filter((item) => typeof item === "string").map((item) => node("li", "", item)));
    }
    const date = new Date(data.updated_at);
    const validDate = typeof data.updated_at === "string" && Number.isFinite(date.valueOf());
    const stale = validDate && Date.now() - date.valueOf() > 24 * 60 * 60 * 1000;
    $("sync-status").textContent = validDate
      ? `Snapshot published ${new Intl.DateTimeFormat(undefined, {dateStyle: "medium", timeStyle: "short"}).format(date)}${stale ? " · Over 24 hours old" : ""}.`
      : "No Unity output has been imported. This is the initial publication record.";
    $("sync-status").parentElement.classList.toggle("stale", stale);
    renderCase(cases.find((entry) => entry.id === selectedCase));
  }
  function renderCase(entry) {
    pauseMovies();
    if (!entry) return;
    $("case-title").textContent = entry.title;
    $("case-description").textContent = entry.description;
    $("diagnostic-case").textContent = entry.title;
    applyStatus($("case-status"), entry.status);
    $("case-notice").textContent = entry.status_text || "Output has not yet been synchronized.";
    const videos = Array.isArray(entry.videos) ? entry.videos.filter((video) => video && assetPath(video.src)) : [];
    const surfaces = videos.filter((video) => ["surface_startup", "surface_late", "surface_evolution"].includes(video.id));
    if (!surfaces.some((video) => video.id === selectedClip)) selectedClip = surfaces[0]?.id || "surface_startup";
    const clip = $("surface-clip");
    clip.replaceChildren(...surfaces.map((video) => {
      const option = node("option", "", video.title);
      option.value = video.id;
      return option;
    }));
    clip.value = selectedClip;
    clip.onchange = () => {
      selectedClip = clip.value;
      renderMovie("surface", surfaces.find((video) => video.id === selectedClip));
    };
    renderMovie("surface", surfaces.find((video) => video.id === selectedClip));
    renderMovie("underwater", videos.find((video) => video.id === "underwater"));
    renderMetrics(entry.metrics || {});
    renderFigures(Array.isArray(entry.figures) ? entry.figures : []);
    const downloads = $("downloads");
    downloads.replaceChildren();
    for (const item of entry.downloads || []) {
      const link = resourceLink(item.title, item.src);
      if (link) downloads.append(link);
    }
    downloads.hidden = downloads.childElementCount === 0;
    const notices = $("case-notices");
    notices.replaceChildren(...(entry.notices || []).filter((text) => typeof text === "string").map((text) => node("p", "", text)));
    notices.hidden = notices.childElementCount === 0;
  }
  function renderMovie(kind, item) {
    const stage = $(`${kind}-stage`);
    stage.querySelectorAll("video").forEach((video) => video.pause());
    stage.replaceChildren();
    stage.classList.toggle("has-video", Boolean(item));
    const tools = $(`${kind}-tools`);
    tools.querySelectorAll(".speed-label, .speed-select").forEach((el) => el.remove());
    tools.hidden = !item;
    const caption = $(`${kind}-caption`);
    caption.replaceChildren();
    if (!item) {
      const placeholder = node("div", "media-placeholder");
      placeholder.append(node("span", "placeholder-label", kind === "surface" ? "SURFACE" : "MEAN FLOW"));
      placeholder.append(node("h4", "", kind === "surface" ? "Waiting for the first surface movie" : "Waiting for the first underwater movie"));
      placeholder.append(node("p", "", "This output has not yet been imported from Unity."));
      stage.append(placeholder);
      caption.textContent = kind === "surface"
        ? "A fixed laboratory view, with the physical proportions of the surface preserved."
        : "The current is resolved below a flat mean surface; the moving wave surface is reconstructed separately.";
      return;
    }
    const video = node("video");
    video.controls = true;
    video.playsInline = true;
    video.preload = "none";
    video.src = assetPath(item.src);
    video.setAttribute("aria-label", item.title || (kind === "surface" ? "Surface evolution" : "Underwater mean-flow evolution"));
    const poster = assetPath(item.poster);
    if (poster) video.poster = poster;
    video.append(node("p", "", "Your browser does not support embedded video. Use the movie link below."));
    video.addEventListener("error", () => {
      if (stage.querySelector(".asset-error")) return;
      video.hidden = true;
      stage.append(node("p", "asset-error", "The movie could not be loaded. Use the movie link below to open it directly, or refresh the published snapshot."));
    });
    stage.append(video);
    const speedLabel = node("label", "speed-label", "Playback");
    speedLabel.htmlFor = `${kind}-speed`;
    const speed = node("select", "speed-select");
    speed.id = `${kind}-speed`;
    for (const rate of [0.25, 0.5, 1, 2]) {
      const option = node("option", "", `${rate}×`);
      option.value = String(rate);
      option.selected = rate === 1;
      speed.append(option);
    }
    speed.addEventListener("change", () => { video.playbackRate = Number(speed.value); });
    tools.append(speedLabel, speed);
    const pieces = [];
    if (Array.isArray(item.physical_interval_s) && item.physical_interval_s.length === 2 && item.physical_interval_s.every(finite)) {
      pieces.push(`Physical time ${number(item.physical_interval_s[0])}–${number(item.physical_interval_s[1])} s`);
    }
    if (finite(item.physical_playback_speed) && item.physical_playback_speed > 0) {
      const rate = item.physical_playback_speed;
      pieces.push(rate < 1 ? `${number(1 / rate)}× slower than physical time at 1× playback` : rate === 1 ? "Physical speed at 1× playback" : `${number(rate)}× physical speed at 1× playback`);
    } else {
      pieces.push("Use the movie time label to follow physical time");
    }
    caption.append(document.createTextNode(`${pieces.join(" · ")}.`));
    const link = resourceLink("Open movie ↗", item.src);
    if (link) caption.append(link);
  }
  function renderMetrics(metrics) {
    const target = $("metrics");
    target.replaceChildren();
    const rows = [
      ["final_parent_mss", "Parent MSS"],
      ["final_cho_disturbance_mss", "Cho disturbance MSS"],
      ["final_total_mss", "Combined surface MSS"]
    ];
    if (!rows.some(([key]) => finite(metrics[key]))) { target.hidden = true; return; }
    target.hidden = false;
    for (const [key, title] of rows) {
      const card = node("div", "metric");
      card.append(node("div", "metric-label", title));
      card.append(node("div", "metric-value", number(metrics[key])));
      card.append(node("div", "metric-note", finite(metrics[key]) ? "At the last imported sample" : "Not available in this snapshot"));
      target.append(card);
    }
  }
  function renderFigures(figures) {
    const target = $("figures");
    target.replaceChildren();
    for (const item of figures) {
      const src = assetPath(item.src);
      if (!src) continue;
      const figure = node("figure", "figure-card");
      const link = resourceLink("", src);
      link.className = "figure-image";
      const img = node("img");
      img.src = src;
      img.alt = item.caption ? `${item.title}. ${item.caption}` : item.title;
      img.loading = "lazy";
      img.addEventListener("error", () => {
        link.replaceChildren(node("span", "asset-error", "This figure could not be loaded. Open the linked file or refresh the snapshot."));
      });
      link.append(img);
      const caption = node("figcaption");
      caption.append(node("h3", "", item.title));
      if (item.caption) caption.append(node("p", "", item.caption));
      figure.append(link, caption);
      target.append(figure);
    }
    $("empty-diagnostics").hidden = target.childElementCount > 0;
  }
  async function refresh() {
    const button = $("refresh-button");
    button.disabled = true;
    $("data-error").hidden = true;
    try {
      const response = await fetch("data/campaign.json", {cache: "no-store"});
      if (!response.ok) throw new Error("The published snapshot could not be retrieved.");
      const data = await response.json();
      if (data.schema_version !== 1 || !Array.isArray(data.cases)) throw new Error("The published snapshot has an unsupported format.");
      renderSnapshot(data);
    } catch (error) {
      $("data-error").textContent = `${error.message} ${snapshot ? "The last successfully loaded snapshot remains visible." : "No simulation result can be inferred from this publication error."}`;
      $("data-error").hidden = false;
      $("sync-status").textContent = snapshot ? "Refresh failed; showing the previously loaded snapshot." : "Published snapshot unavailable.";
    } finally {
      button.disabled = false;
    }
  }
  $("refresh-button").addEventListener("click", refresh);
  refresh();
})();
