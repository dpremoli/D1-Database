// plotly.js-dist-min ships no type declarations; we use it dynamically and only
// need `newPlot` / `purge`, so treat it as untyped rather than pull in the heavy
// @types/plotly.js package.
declare module 'plotly.js-dist-min';
