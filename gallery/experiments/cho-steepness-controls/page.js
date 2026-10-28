"use strict";

// Display saved analyzer output only. Never substitute short validation checks.
const byId = id => document.getElementById(id);
const finite = value => typeof value === "number" && Number.isFinite(value);
const number = value => finite(value) ? value.toPrecision(4) : "—";
const percent = value => finite(value) ? `${(100 * value).toFixed(1)}%` : "—";
const change = (total, parent) => finite(total) && finite(parent) && parent > 0
  ? `${total >= parent ? "+" : ""}${(100 * (total / parent - 1)).toFixed(1)}%` : "—";

function addRow(id, values) {
  const row = document.createElement("tr");
  values.forEach(value => {
    const cell = document.createElement("td");
    cell.textContent = value;
    row.appendChild(cell);
  });
  byId(id).appendChild(row);
}

function revealImage(id, file, revision) {
  const element = byId(id);
  element.addEventListener("error", () => {
    element.hidden = true;
    const note = document.createElement("p");
    note.className = "pending";
    note.textContent = "This plot has not been published yet. Saved numeric results are shown below.";
    element.parentNode.insertBefore(note, element);
  }, {once: true});
  element.src = `plots/${file}?v=${encodeURIComponent(revision)}`;
}

function showData(report, revision) {
  if (!report || !Array.isArray(report.controls) || !Array.isArray(report.bridges) || !Array.isArray(report.missing)) {
    throw new Error("Saved analysis has an unsupported format.");
  }
  const scope = String(report.scope || "");
  if (/validation|preview/i.test(scope) || report.controls.some(c => /validation[\\/]/i.test(String(c.path)))) {
    throw new Error("Only validation-preview diagnostics are available. Production results are still pending.");
  }
  const controls = report.controls;
  const bridges = report.bridges;
  if (report.late_refinement?.passed) {
    const checks=Object.values(report.late_refinement.cases);
    const worst=Math.max(...checks.map(c=>c.capillary_mss_relative_error));
    byId("late-checks").textContent=`Targeted numerical check: doubling spatial resolution and halving time and background intervals over 5.5–6.0 s changes the final capillary MSS by at most ${(100*worst).toFixed(3)}% in the ka = 0.32 and 0.40 phase-corrected cases. Both grids restart from the same saved state; this checks the late evolution, not the complete six-second trajectory or the physical model.`;
    byId("late-checks").hidden=false;
  }
  const incomplete = report.missing.length > 0 || controls.length < 8 || bridges.length < 2;
  const status = byId("status");
  status.textContent = `${controls.length}/8 steepness controls and ${bridges.length}/2 exact-Stokes pressure comparisons have saved results.${incomplete ? " The comparison is incomplete; missing cases are not shown." : " All planned cases are represented in the saved analysis."}`;
  status.classList.toggle("warning", incomplete);
  if (scope) {
    byId("saved-scope").textContent = scope;
    byId("saved-scope").hidden = false;
  }

  if (controls.length) {
    const sorted = [...controls].sort((a, b) => a.steepness - b.steepness || String(a.phase).localeCompare(String(b.phase)));
    for (const entry of sorted) {
      const m = entry.late_mean || {};
      const interval = entry.late_interval_s || [];
      const phase = {linear: "Linear phase", stokes_phase: "Stokes phase correction"}[entry.phase] || String(entry.phase);
      addRow("sweep-rows", [number(entry.steepness), phase,
        interval.length === 2 && interval.every(finite) ? `${interval[0].toFixed(2)}–${interval[1].toFixed(2)}` : "—",
        number(m.all_parent_mss), number(m.all_total_mss), change(m.all_total_mss, m.all_parent_mss),
        number(m.capillary_parent_mss), number(m.capillary_total_mss),
        m.all_total_mss > 0 ? percent(m.capillary_total_mss / m.all_total_mss) : "—"]);
    }
    byId("sweep-pending").hidden = true;
    byId("sweep-results").hidden = false;
    revealImage("sweep-plot", "mss_steepness.png", revision);
    revealImage("diagnostics-plot", "control_diagnostics.png", revision);
  }

  if (bridges.length) {
    for (const entry of [...bridges].sort((a, b) => a.projection === b.projection ? 0 : a.projection === "legacy" ? -1 : 1)) {
      const m = entry.late_mean || {};
      const label = {legacy: "Cho pressure derivative", gc: "GC pressure projection"}[entry.projection] || String(entry.projection);
      addRow("bridge-rows", [label, number(entry.cfg?.tEnd), number(m.mss_parent), number(m.mss_total),
        change(m.mss_total, m.mss_parent), number(m.mss_short_parent), number(m.mss_short_total),
        m.mss_total > 0 ? percent(m.mss_short_total / m.mss_total) : "—"]);
    }
    byId("bridge-pending").hidden = true;
    byId("bridge-results").hidden = false;
    revealImage("bridge-plot", "stokes_bridge_mss.png", revision);
    const ratio = bridges[0].source_power_ratios?.capillary_arclength_slope_weighted_gc_over_legacy;
    if (finite(ratio)) {
      byId("source-ratio").textContent = `For this fixed parent, the capillary-band, slope-weighted source power with the GC projection is ${number(ratio)} times that of the Cho pressure derivative. This is a source-spectrum ratio in arclength coordinates, not a predicted surface-MSS ratio.`;
      byId("source-ratio").hidden = false;
    }
  }
}

async function loadResults() {
  try {
    const response = await fetch("plots/analysis.json", {cache: "no-store"});
    if (!response.ok) throw new Error("Saved production diagnostics have not been published yet.");
    const report = await response.json();
    showData(report, response.headers.get("last-modified") || "saved");
  } catch (error) {
    byId("status").textContent = `${error.message || "Saved diagnostics could not be loaded."} The experiment design is shown below; no result is inferred.`;
    byId("status").classList.add("warning");
  }
}

loadResults();
