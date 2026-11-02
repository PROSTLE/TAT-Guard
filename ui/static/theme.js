// Runs before the page paints, so a dark theme never flashes light. A file, because the security policy allows no inline script.
try { if (localStorage.getItem("tg_theme") === "dark") document.documentElement.dataset.theme = "dark"; } catch (e) { /* storage unavailable */ }
