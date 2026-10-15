const CACHE_NAME = "huimin-shell-v1.2.0";
const SHELL_ASSETS = [
  "/",
  "/static/css/app.css?v=1.2.0",
  "/static/js/app.js?v=1.2.0",
  "/static/manifest.webmanifest",
  "/static/icons/app-icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)),
    )),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/demo-assets/")) return;
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() => caches.match("/")),
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request)),
  );
});
