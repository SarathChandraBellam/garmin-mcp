/* Built-in SAMPLE data for ?demo=1. Every value here is generated from fixed formulas around a
   fixed sample date: it is not anyone's Garmin data and is never sent anywhere. The shapes match
   the app-only tools' structured output, so the views render exactly as they do with real data. */
const Demo = (() => {
  const TODAY = "2026-06-14";
  const TZ = "UTC";
  const DAY = 86400000;
  const toN = (iso) => Math.round(Date.parse(iso + "T00:00:00Z") / DAY);
  const toIso = (n) => new Date(n * DAY).toISOString().slice(0, 10);
  const add = (iso, d) => toIso(toN(iso) + d);
  const T = toN(TODAY);
  const r2 = (v, d) => (v === null ? null : Math.round(v * Math.pow(10, d === undefined ? 1 : d)) / Math.pow(10, d === undefined ? 1 : d));
  /* deterministic noise in [-1, 1] */
  function noise(n, salt) {
    let h = (n * 374761393 + salt * 668265263) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    h = (h ^ (h >>> 16)) >>> 0;
    return (h / 4294967295) * 2 - 1;
  }
  const smooth = (n, salt) => (noise(n, salt) * 0.5 + noise(n - 1, salt) * 0.3 + noise(n - 2, salt) * 0.2);
  const dow = (n) => (new Date(n * DAY).getUTCDay()); // 0 Sun .. 6 Sat

  function windowFor(period) {
    const p = period || "last_7d";
    const m = /^last_(\d+)d$/.exec(p);
    let start = TODAY, end = TODAY;
    if (m) start = add(TODAY, -(Number(m[1]) - 1));
    else if (p === "yesterday") start = end = add(TODAY, -1);
    else if (p === "this_week") start = add(TODAY, -((dow(T) + 6) % 7));
    else if (p === "last_week") { end = add(TODAY, -((dow(T) + 6) % 7) - 1); start = add(end, -6); }
    else if (p === "this_month") start = TODAY.slice(0, 8) + "01";
    else if (p === "last_month") { end = add(TODAY.slice(0, 8) + "01", -1); start = end.slice(0, 8) + "01"; }
    else if (p === "ytd") start = TODAY.slice(0, 5) + "01-01";
    return { start, end, days: toN(end) - toN(start) + 1, period: p, timezone: TZ, timezone_source: "default" };
  }
  const before = (w) => {
    const end = add(w.start, -1), start = add(end, -(w.days - 1));
    return { start, end, days: w.days, period: "custom", timezone: TZ, timezone_source: "default" };
  };
  const dates = (w) => Array.from({ length: w.days }, (_, i) => add(w.start, i));

  /* ---- daily wellness metrics ---- */
  const METRICS = {
    steps: ["steps", true, (n) => 8600 + 28 * (n - T + 120) * 0.3 + [1900, -600, 300, -200, 900, 400, 3400][dow(n)] + 1700 * smooth(n, 1)],
    resting_hr: ["bpm", false, (n) => 53.5 - 0.01 * (n - T + 90) + 1.6 * smooth(n, 2) + (dow(n) === 1 ? 0.8 : 0)],
    hrv: ["ms", true, (n) => 61 + 5 * Math.sin(n / 9) + 4.5 * smooth(n, 3)],
    stress: ["0-100", false, (n) => 29 + 7 * Math.sin(n / 6 + 1) + 6 * smooth(n, 4) + (dow(n) === 0 || dow(n) === 6 ? -6 : 2)],
    body_battery: ["0-100", true, (n) => 74 + 9 * Math.sin(n / 7 + 2) + 8 * smooth(n, 5)],
    sleep_hours: ["hours", true, (n) => sleepNight(n).total_h],
    sleep_score: ["0-100", true, (n) => sleepNight(n).score],
    intensity_minutes: ["minutes", true, (n) => Math.max(0, 34 + 26 * smooth(n, 6) + (acts(n) ? 28 : -18))],
    calories: ["kcal", true, (n) => 2280 + 220 * smooth(n, 7) + (acts(n) ? 420 : 0)],
    weight_kg: ["kg", null, (n) => (n % 3 === 0 ? 72.6 - 0.012 * (n - T + 120) + 0.25 * smooth(n, 8) : null)],
    vo2max: ["ml/kg/min", true, (n) => (acts(n) && /run/.test(acts(n).type) ? 49.2 + 0.006 * (n - T + 120) + 0.3 * smooth(n, 9) : null)],
  };
  const OVERVIEW = ["sleep_hours", "resting_hr", "hrv", "stress", "body_battery", "steps"];
  const LABELS = { steps: "Steps", resting_hr: "Resting HR", hrv: "Overnight HRV", stress: "Stress", body_battery: "Body Battery",
    sleep_hours: "Sleep", sleep_score: "Sleep score", intensity_minutes: "Intensity minutes", calories: "Calories", weight_kg: "Weight", vo2max: "VO2 max" };
  function value(metric, n) {
    const v = METRICS[metric][2](n);
    if (v === null || v === undefined) return null;
    const unit = METRICS[metric][0];
    const clamp = unit === "0-100" ? Math.max(5, Math.min(100, v)) : v;
    return unit === "steps" || unit === "kcal" ? Math.round(clamp) : r2(clamp, unit === "hours" || unit === "kg" ? 2 : 1);
  }
  function stats(metric, w, withDaily) {
    const ds = dates(w);
    const daily = ds.map((d) => ({ date: d, value: value(metric, toN(d)), partial: d === TODAY }));
    const used = daily.filter((x) => x.value !== null && !(x.partial && METRICS[metric][0] === "steps"));
    const vals = used.map((x) => x.value);
    const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
    let slope = null;
    if (vals.length > 2) {
      const xs = used.map((x) => toN(x.date)), mx = xs.reduce((a, b) => a + b, 0) / xs.length;
      const num = xs.reduce((a, x, i) => a + (x - mx) * (vals[i] - avg), 0), den = xs.reduce((a, x) => a + (x - mx) ** 2, 0);
      slope = den ? num / den : 0;
    }
    const trend = slope === null ? null : Math.abs(slope * ds.length) < Math.abs(avg) * 0.03 ? "flat" : slope > 0 ? "up" : "down";
    const best = used.slice().sort((a, b) => b.value - a.value)[0];
    const worst = used.slice().sort((a, b) => a.value - b.value)[0];
    return {
      metric, unit: METRICS[metric][0], days_with_data: vals.length, missing_days: ds.length - vals.length,
      average: r2(avg, 2), minimum: vals.length ? Math.min(...vals) : null, maximum: vals.length ? Math.max(...vals) : null,
      total: vals.length ? r2(vals.reduce((a, b) => a + b, 0), 1) : null, stdev: null, slope_per_day: r2(slope, 3), trend,
      best_day: best || null, worst_day: worst || null, daily: withDaily ? daily : null,
    };
  }
  function overview(period) {
    const w = windowFor(period), pw = before(w);
    const metrics = OVERVIEW.map((m) => {
      const s = stats(m, w, true), p = stats(m, pw, false);
      const change = s.average !== null && p.average !== null ? r2(s.average - p.average, 2) : null;
      return Object.assign(s, { previous_average: p.average, change, change_pct: change !== null && p.average ? r2((change / p.average) * 100, 1) : null });
    });
    return { window: w, previous_window: pw, metrics, summary: "Sample wellness overview.", notes: ["Sample data"] };
  }

  /* ---- activities ---- */
  const PLAN = [ // by weekday: [type, name, km, min, start]
    ["lap_swimming", "Pool swim", 1.8, 42, "07:10"], ["running", "Morning run", 8.2, 44, "06:45"], ["strength_training", "Strength session", null, 40, "18:20"],
    ["cycling", "Lunch ride", 24, 58, "12:15"], ["running", "Tempo run", 9.6, 46, "06:50"], null, ["trail_running", "Trail run", 14.5, 92, "08:30"],
  ];
  const WEEKEND_RIDE = ["cycling", "Long ride", 62, 148, "09:00"];
  function acts(n) {
    let p = PLAN[dow(n)];
    if (dow(n) === 6 && Math.floor(n / 7) % 2 === 0) p = WEEKEND_RIDE;
    if (!p && noise(n, 12) > 0.2) p = ["walking", "Evening walk", 4.6, 55, "19:05"];
    if (!p || noise(n, 11) < -0.75) return null; // a few rest days
    const [type, name, km, min, start] = p;
    const f = 1 + 0.12 * noise(n, 13);
    const distance = km === null ? null : r2(km * f, 2);
    const duration = r2(min * (1 + 0.1 * noise(n, 14)), 1);
    const hrBase = { running: 148, trail_running: 142, cycling: 132, lap_swimming: 128, walking: 98, strength_training: 112 }[type];
    const avgHr = Math.round(hrBase + 6 * noise(n, 15));
    const z = { running: [4, 18, 46, 24, 8], trail_running: [6, 30, 40, 18, 6], cycling: [10, 40, 35, 12, 3], lap_swimming: [12, 46, 32, 8, 2],
      walking: [70, 26, 4, 0, 0], strength_training: [38, 40, 18, 4, 0] }[type];
    const zs = z.map((pct, i) => Math.round((duration * 60 * pct) / 100 * (1 + 0.1 * noise(n, 20 + i))));
    return {
      activity_id: 7000000 + n, name, type, start_local: `${toIso(n)} ${start}:00`, start_gmt: null,
      distance_km: distance, duration_min: duration, moving_min: r2(duration * 0.96, 1),
      calories: Math.round(duration * ({ walking: 5, strength_training: 6, lap_swimming: 8 }[type] || 10.5)),
      avg_hr: avgHr, max_hr: avgHr + 22, avg_speed_kmh: distance ? r2(distance / (duration / 60), 2) : null,
      elevation_gain_m: { trail_running: 540, cycling: distance ? Math.round(distance * 9) : 0, running: 60, walking: 25 }[type] || null,
      steps: null, training_effect: null, body_battery_change: -Math.round(duration / 6), hr_zone_secs: zs,
    };
  }
  function activitiesIn(w) {
    const out = [];
    for (let n = toN(w.end); n >= toN(w.start); n--) { const a = acts(n); if (a) out.push(a); }
    return out;
  }
  function group(key, list) {
    const g = { key, count: list.length, distance_km: 0, duration_min: 0, moving_min: 0, elevation_gain_m: 0, calories: 0, hr_zone_min: [0, 0, 0, 0, 0] };
    for (const a of list) {
      g.distance_km += a.distance_km || 0; g.duration_min += a.duration_min || 0; g.moving_min += a.moving_min || 0;
      g.elevation_gain_m += a.elevation_gain_m || 0; g.calories += a.calories || 0;
      a.hr_zone_secs.forEach((s, i) => { g.hr_zone_min[i] += s / 60; });
    }
    for (const k of ["distance_km", "duration_min", "moving_min", "elevation_gain_m", "calories"]) g[k] = r2(g[k], 1);
    g.hr_zone_min = g.hr_zone_min.map((v) => r2(v, 1));
    return g;
  }
  function activitySummary(period) {
    const w = windowFor(period || "last_30d"), list = activitiesIn(w);
    const types = [...new Set(list.map((a) => a.type))];
    const groups = types.map((t) => group(t, list.filter((a) => a.type === t))).sort((a, b) => b.duration_min - a.duration_min);
    return { window: w, group_by: "type", totals: group("all", list), groups, longest: null, fastest: null, activities: null, summary: "Sample activities.", notes: [] };
  }
  function activityPage(period, offset) {
    const w = windowFor(period || "last_30d"), list = activitiesIn(w), o = offset || 0;
    return { window: w, offset: o, limit: 20, items: list.slice(o, o + 20), has_more: list.length > o + 20, summary: "Sample page." };
  }
  function activityDetail(id) {
    const n = id - 7000000, a = acts(n);
    if (!a) throw new Error("Sample activity not found");
    const splits = [];
    if (a.distance_km) {
      const lap = /cycl/.test(a.type) ? 5 : /swim/.test(a.type) ? 0.5 : 1;
      const count = Math.min(12, Math.floor(a.distance_km / lap));
      const pace = a.duration_min / a.distance_km;
      for (let i = 0; i < count; i++) {
        const f = 1 + 0.05 * noise(n * 31 + i, 40) - (i === count - 1 ? 0.04 : 0);
        const dur = lap * pace * f;
        splits.push({ index: i + 1, distance_km: lap, duration_min: r2(dur, 2), avg_hr: Math.round(a.avg_hr - 6 + i * 1.1 + 2 * noise(n + i, 41)),
          avg_speed_kmh: r2(lap / (dur / 60), 2), elevation_gain_m: a.elevation_gain_m ? Math.round(a.elevation_gain_m / Math.max(1, count) * (1 + noise(n + i, 42) * 0.4)) : 0 });
      }
    }
    return { activity: a, hr_zone_min: a.hr_zone_secs.map((s) => r2(s / 60, 1)), splits,
      summary: `${a.name} (sample).`, notes: splits.length ? [] : ["No splits recorded for this sample activity."] };
  }

  /* ---- sleep ---- */
  function sleepNight(n) {
    const weekend = dow(n) === 0 || dow(n) === 6;
    const bed = 23 * 60 - 18 + 24 * smooth(n, 30) + (weekend ? 34 : 0); // minutes after midnight of the evening before
    const total = 7.25 + 0.55 * smooth(n, 31) + (weekend ? 0.45 : 0) + (dow(n) === 2 ? -0.5 : 0);
    const deep = total * (0.17 + 0.03 * noise(n, 32)), rem = total * (0.22 + 0.04 * noise(n, 33));
    const awake = 0.22 + 0.12 * Math.abs(noise(n, 34));
    const light = total - deep - rem;
    const wake = bed + (total + awake) * 60;
    const hhmm = (m) => { const x = ((Math.round(m) % 1440) + 1440) % 1440; return String(Math.floor(x / 60)).padStart(2, "0") + ":" + String(x % 60).padStart(2, "0"); };
    return { date: toIso(n), total_h: r2(total, 2), deep_h: r2(deep, 2), light_h: r2(light, 2), rem_h: r2(rem, 2), awake_h: r2(awake, 2),
      score: Math.round(Math.max(48, Math.min(96, 60 + (total - 6) * 11 + (deep / total - 0.15) * 120 + 4 * noise(n, 35)))),
      need_h: 8, bedtime: hhmm(bed), wake_time: hhmm(wake) };
  }
  function sleepSeries(period, withDaily) {
    const w = windowFor(period || "last_30d");
    const nights = dates(w).map((d) => sleepNight(toN(d)));
    const avg = (k) => r2(nights.reduce((a, x) => a + x[k], 0) / nights.length, 2);
    const mins = nights.map((x) => { const [h, m] = x.bedtime.split(":").map(Number); return (h < 12 ? h + 24 : h) * 60 + m; });
    const mb = mins.reduce((a, b) => a + b, 0) / mins.length;
    const spread = Math.sqrt(mins.reduce((a, b) => a + (b - mb) ** 2, 0) / mins.length);
    const hhmm = (m) => { const x = Math.round(m) % 1440; return String(Math.floor(x / 60)).padStart(2, "0") + ":" + String(x % 60).padStart(2, "0"); };
    const wakeMins = nights.map((x) => { const [h, m] = x.wake_time.split(":").map(Number); return h * 60 + m; });
    const total = avg("total_h");
    return { window: w, nights: nights.length, avg_total_h: total, avg_deep_h: avg("deep_h"), avg_light_h: avg("light_h"), avg_rem_h: avg("rem_h"),
      avg_awake_h: avg("awake_h"), stage_pct: {}, avg_score: Math.round(avg("score")), avg_bedtime: hhmm(mb),
      avg_wake_time: hhmm(wakeMins.reduce((a, b) => a + b, 0) / wakeMins.length), bedtime_spread_min: Math.round(spread), wake_spread_min: null,
      avg_need_h: 8, sleep_debt_h: r2(nights.reduce((a, x) => a + Math.max(0, 8 - x.total_h), 0), 1),
      daily: withDaily ? nights : null, summary: "Sample sleep.", notes: [] };
  }

  /* ---- trends ---- */
  function trendData(metric, pa, pb) {
    const m = METRICS[metric] ? metric : "steps";
    const wa = windowFor(pa || "last_30d"), wb = pb ? windowFor(pb) : before(wa);
    const a = stats(m, wa, true), b = stats(m, wb, true);
    const change = a.average !== null && b.average !== null ? r2(a.average - b.average, 2) : null;
    return { metric: m, unit: METRICS[m][0], window_a: wa, window_b: wb, a: Object.assign({}, a, { daily: null }), b: Object.assign({}, b, { daily: null }),
      a_daily: a.daily, b_daily: b.daily, change, change_pct: change !== null && b.average ? r2((change / b.average) * 100, 1) : null, summary: "Sample trend." };
  }

  const PICKER = [["last_1d", "Today"], ["last_7d", "Last 7 days"], ["last_15d", "Last 15 days"], ["last_30d", "Last 30 days"], ["last_90d", "Last 90 days"],
    ["this_week", "This week"], ["last_week", "Last week"], ["this_month", "This month"], ["last_month", "Last month"], ["ytd", "Year to date"]];

  const TOOLS = {
    dashboard_data: (a) => overview(a.period || "last_7d"),
    get_wellness_overview: (a) => overview(a.period || "last_7d"),
    activity_page: (a) => activityPage(a.period, a.offset),
    get_activity_summary: (a) => activitySummary(a.period),
    activity_detail: (a) => activityDetail(a.activity_id),
    sleep_series: (a) => sleepSeries(a.period || "last_30d", true),
    get_sleep_analysis: (a) => sleepSeries(a.period || "last_7d", false),
    trend_data: (a) => trendData(a.metric, a.period_a, a.period_b),
  };
  function call(name, args) {
    return new Promise((resolve, reject) => setTimeout(() => {
      try {
        if (!TOOLS[name]) throw new Error("No sample data for " + name);
        resolve(JSON.parse(JSON.stringify(TOOLS[name](args || {}))));
      } catch (e) { reject(e); }
    }, 320));
  }
  function opening(app) {
    switch (app) {
      case "garmin-dashboard": return Object.assign(overview("last_7d"), {});
      case "garmin-activities": return activitySummary("last_30d");
      case "garmin-sleep": return sleepSeries("last_7d", false);
      case "garmin-trends": {
        const t = trendData("steps", "this_month", "last_month");
        return { metric: t.metric, unit: t.unit, window_a: t.window_a, window_b: t.window_b, a: t.a, b: t.b, change: t.change, change_pct: t.change_pct, summary: t.summary };
      }
      case "garmin-period-picker": return { question: "Which time window should I look at?", options: PICKER.map(([value, label]) => ({ value, label })), summary: "" };
      default: return null;
    }
  }
  return { call, opening, TODAY, LABELS };
})();
