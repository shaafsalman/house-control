// Day / night, from the clock. Everything that looks different by day listens here:
// the CSS (html[data-tod] and --day), and the 3D scene (world.setDaylight).
// For testing: ?tod=day or ?tod=night forces one; ?tod=14.5 pretends it is 14:30.
const params = new URLSearchParams(location.search);

const ramp = (x, a, b) => Math.min(1, Math.max(0, (x - a) / (b - a)));

/** 0 = night … 1 = day. Dawn 05:30–07:00, dusk 17:30–19:00. */
export function dayFactor(date = new Date()) {
  const forced = params.get('tod');
  if (forced === 'day') return 1;
  if (forced === 'night') return 0;
  const hour = forced !== null && !Number.isNaN(Number(forced)) ? Number(forced) : date.getHours() + date.getMinutes() / 60;
  return ramp(hour, 5.5, 7) * (1 - ramp(hour, 17.5, 19));
}

/** Calls `apply(k)` now and every minute, and keeps the page's data-tod / --day in step. */
export function watchDaylight(apply = () => {}) {
  const run = () => {
    const k = dayFactor();
    const root = document.documentElement;
    root.dataset.tod = k > 0.5 ? 'day' : 'night';
    root.style.setProperty('--day', k.toFixed(3));
    apply(k);
    window.dispatchEvent(new CustomEvent('daylight', { detail: k }));
  };
  run();
  const timer = setInterval(run, 60_000);
  return () => clearInterval(timer);
}
