/* Offline shell only. Data is always fetched from the server, because a stale
   suggestion list is worse than no list. */
var CACHE = "trolley-v1";
var SHELL = ["/", "/static/app.js", "/static/styles.css", "/static/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE).then(function (cache) { return cache.addAll(SHELL); }));
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (key) { return key !== CACHE; }).map(function (key) {
      return caches.delete(key);
    }));
  }));
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.indexOf("/api/") === 0) return;
  event.respondWith(
    fetch(event.request).catch(function () { return caches.match(event.request); })
  );
});
