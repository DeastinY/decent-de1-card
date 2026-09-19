/*
 * decent-de1-card — Decent DE1 hero card.
 * The machine is a Cycles render of Decent's official DE1PRO CAD model. Live data is layered on top:
 * the tablet screen is a perspective-mapped HTML panel, the water in the base crossfades between
 * pre-rendered levels. See README.md for configuration and render/ for how the images are made.
 */
const ASSETS = __ASSETS__;

// Machine entities default to `<domain>.<prefix><suffix>`; everything else is opt-in.
const MACHINE = {
  state: ["sensor", "machine_state"],
  substate: ["sensor", "machine_substate"],
  temperature: ["sensor", "group_temperature"],
  water_level: ["sensor", "water_level"],
  profile: ["sensor", "profile"],
  shot_running: ["binary_sensor", "shot_running"],
};
const OPTIONAL = ["shots_today", "shots_week", "shots_month", "shots_total", "last_shot", "last_cleaning", "cleaning_due", "descale_due"];
const DEFAULTS = { name: "Decent DE1", water_full_mm: 48, water_low_mm: 10 };
const OFF_STATES = ["sleep", "disconnected", "unavailable", "unknown"];

const num = (s) => {
  const v = parseFloat(s?.state);
  return Number.isFinite(v) ? v : null;
};
// input_datetime ("2026-09-17 13:16:48", local) or timestamp sensors (ISO with offset)
const toDate = (s) => (s && !["unknown", "unavailable"].includes(s.state) ? new Date(s.state.replace(" ", "T")) : null);
// Donetick-style chores keep the date in `next_due_date`; otherwise the state is the due date.
const dueDate = (s) => (s ? new Date(s.attributes?.next_due_date ?? s.state.replace(" ", "T")) : null);

function ago(date) {
  if (!date || isNaN(date)) return "—";
  const m = Math.round((Date.now() - date) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

function due(date) {
  if (!date || isNaN(date)) return { text: "—", level: "" };
  const d = (date - Date.now()) / 86400000;
  if (d < 0) {
    const n = Math.max(1, Math.round(-d));
    return { text: `${n} day${n === 1 ? "" : "s"} overdue`, level: "bad" };
  }
  if (d < 1) return { text: "today", level: "warn" };
  if (d < 45) {
    const n = Math.round(d);
    return { text: `in ${n} day${n === 1 ? "" : "s"}`, level: d < 2 ? "warn" : "" };
  }
  return { text: `in ${Math.round(d / 30)} months`, level: "" };
}

// Projective transform mapping the rectangle (0,0,w,h) onto a quad, as a CSS matrix3d.
function quadMatrix(w, h, [x0, y0], [x1, y1], [x2, y2], [x3, y3]) {
  const dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3;
  const dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3;
  const den = dx1 * dy2 - dx2 * dy1;
  const g = (dx3 * dy2 - dx2 * dy3) / den;
  const hh = (dx1 * dy3 - dx3 * dy1) / den;
  const a = x1 - x0 + g * x1, b = x3 - x0 + hh * x3, c = x0;
  const d = y1 - y0 + g * y1, e = y3 - y0 + hh * y3, f = y0;
  const m = [a / w, d / w, 0, g / w, b / h, e / h, 0, hh / h, 0, 0, 1, 0, c, f, 0, 1];
  return `matrix3d(${m.map((v) => +v.toFixed(8)).join(",")})`;
}

const STYLE = `
  :host { display: block; --water: #2f86cc; }
  [hidden] { display: none !important; }
  ha-card { overflow: hidden; }
  .wrap { container-type: inline-size; }
  .card {
    display: grid; grid-template-columns: 1fr; position: relative;
    font-family: var(--ha-font-family-body, inherit); color: var(--primary-text-color);
  }
  .stage {
    position: relative; padding: 22px 18px 6px;
    background:
      radial-gradient(50% 55% at 50% 50%, color-mix(in srgb, var(--primary-text-color) 6%, transparent), transparent 75%);
  }
  .machine { position: relative; width: 100%; max-width: 400px; margin: 0 auto; aspect-ratio: var(--ar); cursor: pointer; }
  .machine img { position: absolute; display: block; user-select: none; -webkit-user-drag: none; }
  .machine .base { inset: 0; width: 100%; height: 100%; }
  .machine .water { opacity: 0; transition: opacity .7s ease; }

  .screen {
    position: absolute; left: 0; top: 0; width: 400px; height: 250px; transform-origin: 0 0;
    border-radius: 6px; overflow: hidden; pointer-events: none; opacity: 0; transition: opacity .8s ease;
    background: radial-gradient(120% 90% at 30% 0%, #1d2430, #0b0e13 70%);
    color: #fff; font-family: var(--ha-font-family-body, inherit);
    display: flex; flex-direction: column; align-items: center; justify-content: center;
  }
  .on .screen { opacity: .96; }
  .screen .s-state { font-size: 21px; letter-spacing: .22em; text-transform: uppercase; opacity: .6; }
  .screen .s-temp { font-size: 112px; font-weight: 250; line-height: 1; letter-spacing: -.02em; margin: 6px 0 12px; font-variant-numeric: tabular-nums; }
  .screen .s-temp small { font-size: 56px; opacity: .6; margin-left: 2px; vertical-align: top; }
  .screen .s-bar { width: 56%; height: 6px; border-radius: 3px; background: rgba(255,255,255,.1); overflow: hidden; }
  .screen .s-bar i { display: block; height: 100%; width: 0; border-radius: 3px; background: linear-gradient(90deg, #7f93ad, #f6a23a, #ff5a1f); transition: width 1s ease; }
  .screen .s-profile { font-size: 20px; opacity: .5; margin-top: 14px; }

  .callout {
    position: absolute; transform: translate(-100%, -50%); display: flex; align-items: center; gap: 8px;
    pointer-events: auto; cursor: pointer; white-space: nowrap;
  }
  .callout .pill {
    display: flex; align-items: baseline; gap: 6px; padding: 5px 10px; border-radius: 999px;
    background: color-mix(in srgb, var(--card-background-color, var(--ha-card-background, #fff)) 78%, transparent);
    backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
    box-shadow: 0 1px 2px rgba(0,0,0,.08), 0 0 0 1px color-mix(in srgb, var(--primary-text-color) 8%, transparent);
  }
  .callout b { font-size: 15px; font-weight: 500; font-variant-numeric: tabular-nums; }
  .callout span { font-size: 11px; color: var(--secondary-text-color); }
  .callout .line { width: 26px; height: 1px; background: color-mix(in srgb, var(--primary-text-color) 30%, transparent); }
  .callout .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--water); box-shadow: 0 0 0 3px color-mix(in srgb, var(--water) 25%, transparent); }
  .callout.low .dot { background: var(--error-color, #db4437); box-shadow: 0 0 0 3px color-mix(in srgb, var(--error-color, #db4437) 25%, transparent); }
  .callout.low b { color: var(--error-color, #db4437); }

  .info { padding: 4px 22px 22px; display: grid; gap: 18px; align-content: center; }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .name { font-size: 16px; font-weight: 500; }
  .status { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; color: var(--secondary-text-color); cursor: pointer; }
  .status i { width: 8px; height: 8px; border-radius: 50%; background: var(--dot, #7f93ad); box-shadow: 0 0 0 3px color-mix(in srgb, var(--dot, #7f93ad) 22%, transparent); }

  .shots { display: grid; grid-template-columns: auto 1fr; align-items: end; gap: 4px 22px; }
  .today { cursor: pointer; }
  .today .n { font-size: 64px; font-weight: 200; line-height: .9; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
  .today .l { font-size: 12px; color: var(--secondary-text-color); margin-top: 6px; }
  .mini { display: grid; grid-template-columns: repeat(3, auto); justify-content: space-between; gap: 18px; padding-bottom: 4px; white-space: nowrap; }
  .mini div { cursor: pointer; }
  .mini .n { font-size: 20px; font-weight: 400; font-variant-numeric: tabular-nums; }
  .mini .l { font-size: 11px; color: var(--secondary-text-color); margin-top: 2px; }

  .care { display: grid; gap: 2px; border-top: 1px solid var(--divider-color, rgba(127,127,127,.2)); padding-top: 10px; }
  .row { display: flex; align-items: center; gap: 12px; padding: 7px 0; cursor: pointer; }
  .row ha-icon { --mdc-icon-size: 18px; color: var(--secondary-text-color); }
  .row .k { flex: 1; font-size: 13px; color: var(--secondary-text-color); }
  .row .v { font-size: 14px; font-variant-numeric: tabular-nums; }
  .warn { color: var(--warning-color, #ffa600) !important; }
  .bad { color: var(--error-color, #db4437) !important; }

  @container (min-width: 700px) {
    .card { grid-template-columns: minmax(0, 1.25fr) minmax(280px, 1fr); }
    .stage { padding: 26px 10px 18px 26px; }
    .info { padding: 26px 30px 26px 8px; }
    .machine { max-width: 440px; }
  }
`;

class DecentDe1Card extends HTMLElement {
  setConfig(config) {
    if (!config || (!config.prefix && !config.state)) {
      throw new Error("Set `prefix` (e.g. decent_de1_) or at least the `state` entity");
    }
    const c = { ...DEFAULTS, ...config };
    for (const [key, [domain, suffix]] of Object.entries(MACHINE)) {
      if (!c[key] && config.prefix) c[key] = `${domain}.${config.prefix}${suffix}`;
    }
    this._config = c;
    this._sig = "";
    if (this._root) this._applyVisibility();
  }

  static getStubConfig(hass) {
    const id = Object.keys(hass?.states || {}).find((e) => e.startsWith("sensor.") && e.endsWith("machine_state"));
    return id ? { prefix: id.slice("sensor.".length, -"machine_state".length) } : { prefix: "decent_de1_" };
  }
  getCardSize() { return 8; }
  getGridOptions() { return { columns: 12, min_columns: 6 }; }

  connectedCallback() {
    if (this._ro && this._machine) this._ro.observe(this._machine);
  }
  disconnectedCallback() {
    this._ro?.disconnect();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._root) this._build();
    const keys = Object.values(this._config).filter((v) => typeof v === "string" && v.includes("."));
    const sig = keys.map((k) => hass.states[k]?.last_updated + hass.states[k]?.state).join("|");
    if (sig === this._sig) return;
    this._sig = sig;
    this._update();
  }

  _build() {
    const A = ASSETS;
    const root = (this._root = this.attachShadow({ mode: "open" }));
    const wb = A.water_box;
    const waterBox = `left:${wb[0] * 100}%;top:${wb[1] * 100}%;width:${wb[2] * 100}%;height:${wb[3] * 100}%`;
    root.innerHTML = `
      <style>${STYLE}</style>
      <ha-card><div class="wrap">
        <div class="card" id="card">
          <div class="stage">
            <div class="machine" id="machine" data-entity="state" style="--ar:${A.w}/${A.h}">
              <img class="base" alt="Decent DE1" src="data:image/webp;base64,${A.base}">
              <img class="water" id="water-a" alt="" style="${waterBox}">
              <img class="water" id="water-b" alt="" style="${waterBox}">
              <div class="screen" id="screen">
                <div class="s-state" id="s-state"></div>
                <div class="s-temp" id="s-temp"></div>
                <div class="s-bar"><i id="s-bar"></i></div>
                <div class="s-profile" id="s-profile"></div>
              </div>
              <div class="callout" id="water-callout" data-entity="water_level" style="left:${A.tank[0] * 100 - 1}%;top:${A.tank[1] * 100}%">
                <div class="pill"><b id="water-pct"></b><span>water</span></div><div class="line"></div><div class="dot"></div>
              </div>
            </div>
          </div>
          <div class="info">
            <div class="head">
              <div class="name" id="name"></div>
              <div class="status" data-entity="state"><i></i><span id="status"></span></div>
            </div>
            <div class="shots" id="shots">
              <div class="today" data-entity="shots_today"><div class="n" id="today"></div><div class="l" id="today-l">shots today</div></div>
              <div class="mini">
                <div data-entity="shots_week"><div class="n" id="week"></div><div class="l">this week</div></div>
                <div data-entity="shots_month"><div class="n" id="month"></div><div class="l">this month</div></div>
                <div data-entity="shots_total"><div class="n" id="total"></div><div class="l">all time</div></div>
              </div>
            </div>
            <div class="care">
              <div class="row" data-entity="last_shot"><ha-icon icon="mdi:coffee-outline"></ha-icon><div class="k">Last shot</div><div class="v" id="lastshot"></div></div>
              <div class="row" data-entity="last_cleaning"><ha-icon icon="mdi:spray-bottle"></ha-icon><div class="k">Last cleaning</div><div class="v" id="cleaned"></div></div>
              <div class="row" data-entity="cleaning_due"><ha-icon icon="mdi:calendar-refresh"></ha-icon><div class="k">Next cleaning</div><div class="v" id="cleandue"></div></div>
              <div class="row" data-entity="descale_due"><ha-icon icon="mdi:water-opacity"></ha-icon><div class="k">Descale</div><div class="v" id="descale"></div></div>
            </div>
          </div>
        </div>
      </div></ha-card>`;
    root.querySelectorAll("[data-entity]").forEach((el) =>
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const entityId = this._config[el.dataset.entity];
        if (!entityId) return;
        this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
      })
    );
    this._$ = (id) => root.getElementById(id);
    this._machine = this._$("machine");
    this._ro = new ResizeObserver(() => this._placeScreen());
    this._ro.observe(this._machine);
    this._applyVisibility();
  }

  // Optional rows only show when their entity is configured.
  _applyVisibility() {
    const c = this._config;
    this._root.querySelectorAll("[data-entity]").forEach((el) => {
      if (OPTIONAL.includes(el.dataset.entity)) el.hidden = !c[el.dataset.entity];
    });
    this._$("shots").hidden = !["shots_today", "shots_week", "shots_month", "shots_total"].some((k) => c[k]);
    this._root.querySelector(".care").hidden = !["last_shot", "last_cleaning", "cleaning_due", "descale_due"].some((k) => c[k]);
    this._$("water-callout").hidden = !c.water_level;
  }

  _placeScreen() {
    const r = this._machine.getBoundingClientRect();
    if (!r.width) return;
    const s = ASSETS.screen;
    const px = ([x, y]) => [x * r.width, y * r.height];
    this._$("screen").style.transform = quadMatrix(400, 250, px(s.tl), px(s.tr), px(s.br), px(s.bl));
    // keep the water callout inside the card on narrow layouts
    const callout = this._$("water-callout");
    callout.style.marginLeft = "0px";
    const stage = this._machine.parentElement.getBoundingClientRect();
    const overflow = stage.left + 10 - callout.getBoundingClientRect().left;
    if (overflow > 0) callout.style.marginLeft = `${overflow}px`;
  }

  _update() {
    const c = this._config;
    const s = (k) => this._hass.states[c[k]];
    const $ = this._$;
    const card = $("card");

    $("name").textContent = c.name;
    const state = s("state")?.state ?? "unavailable";
    const sub = s("substate")?.state;
    const off = OFF_STATES.includes(String(state).toLowerCase());
    const running = s("shot_running")?.state === "on";
    const heating = !off && /heating/.test(sub || "");
    const pretty = (x) => String(x).replace(/([a-z])([A-Z])/g, "$1 $2");
    let status = off ? (String(state).toLowerCase() === "sleep" ? "Sleeping" : pretty(state)) : [pretty(state), sub && sub !== "?" ? sub : null].filter(Boolean).join(" · ");
    $("status").textContent = status.charAt(0).toUpperCase() + status.slice(1);
    card.classList.toggle("on", !off);

    const t = num(s("temperature"));
    card.style.setProperty("--dot", off ? "#7f93ad" : running ? "#ff7a2e" : heating ? "#f6a23a" : "#34c77b");
    $("s-state").textContent = running ? "Pouring" : heating ? "Heating" : pretty(state);
    $("s-temp").innerHTML = t == null ? "—" : `${t.toFixed(1)}<small>°</small>`;
    $("s-bar").style.width = `${t == null ? 0 : Math.max(0, Math.min(1, (t - 20) / 73)) * 100}%`;
    const profile = s("profile")?.state;
    $("s-profile").textContent = profile && !["unknown", "unavailable"].includes(profile) ? profile : "";
    this._placeScreen();

    const ws = s("water_level");
    const mm = num(ws);
    const isPct = ws?.attributes?.unit_of_measurement === "%";
    const pct = mm == null ? 0 : Math.max(0, Math.min(1, isPct ? mm / 100 : mm / c.water_full_mm));
    const step = Math.round(pct * 10) * 10;
    if (this._step !== step) {
      this._step = step;
      const prev = this._front;
      const next = (this._front = $(prev?.id === "water-a" ? "water-b" : "water-a"));
      next.src = `data:image/webp;base64,${ASSETS.levels[step]}`;
      next.style.opacity = "1";
      if (prev) prev.style.opacity = "0";
    }
    $("water-pct").textContent = mm == null ? "—" : `${Math.round(pct * 100)}%`;
    $("water-callout").classList.toggle("low", mm != null && (isPct ? mm < (c.water_low_percent ?? 20) : mm < c.water_low_mm));

    const int = (k) => {
      const v = num(s(k));
      return v == null ? "—" : Math.round(v).toLocaleString();
    };
    $("today").textContent = int("shots_today");
    $("week").textContent = int("shots_week");
    $("month").textContent = int("shots_month");
    $("total").textContent = int("shots_total");
    const today = num(s("shots_today"));
    const lc = toDate(s("last_shot"));
    $("today-l").textContent = `shot${today === 1 ? "" : "s"} today`;
    $("lastshot").textContent = ago(lc);

    $("cleaned").textContent = ago(toDate(s("last_cleaning")));
    for (const [key, id] of [["cleaning_due", "cleandue"], ["descale_due", "descale"]]) {
      const d = due(dueDate(s(key)));
      $(id).textContent = d.text;
      $(id).className = `v ${d.level}`;
    }
  }
}

customElements.define("decent-de1-card", DecentDe1Card);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "decent-de1-card",
  name: "Decent DE1",
  description: "Rendered Decent DE1 with live temperature on the tablet and the real water level in the base.",
  preview: true,
  documentationURL: "https://github.com/DeastinY/decent-de1-card",
});
