import { ref } from 'vue';

const STORAGE_KEY = 'force-app.theme';

// Single reactive source of truth for the app's light/dark theme, replacing the ad hoc DOM-attribute
// reads/writes that used to be duplicated in main.ts and GeneralSettings.vue. Canvas/WebGL components
// that don't repaint from CSS alone (LiveForcePlot, FinishedForcePlot, ...) watch() this ref to redraw
// with the new palette instead of staying stuck on whatever was current at their last draw.
export const theme = ref<'dark' | 'light'>(
	(localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'),
);

export function applyTheme(t: 'dark' | 'light') {
	theme.value = t;
	if (t === 'light') document.documentElement.setAttribute('data-theme', 'light');
	else document.documentElement.removeAttribute('data-theme');
	localStorage.setItem(STORAGE_KEY, t);
}

// Sync the DOM attribute immediately at module load (before Vue mounts), so there's no dark->light
// flash on a page that starts in light mode.
if (theme.value === 'light') document.documentElement.setAttribute('data-theme', 'light');
