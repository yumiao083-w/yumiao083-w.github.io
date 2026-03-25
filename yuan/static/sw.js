// Service Worker — 袁朗语音通话 PWA
const CACHE_NAME = 'yuanlang-voice-v1';
const APP_SHELL = [
  '/voice',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/manifest.json'
];

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(APP_SHELL);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(name) { return name !== CACHE_NAME; })
             .map(function(name) { return caches.delete(name); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(event) {
  var url = new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) return;
  if (event.request.headers.get('Accept') === 'text/event-stream') return;

  event.respondWith(
    caches.match(event.request).then(function(cached) {
      if (cached) {
        fetch(event.request).then(function(response) {
          if (response && response.status === 200) {
            caches.open(CACHE_NAME).then(function(cache) {
              cache.put(event.request, response);
            });
          }
        }).catch(function(){});
        return cached;
      }
      return fetch(event.request).then(function(response) {
        if (response && response.status === 200 && url.origin === self.location.origin) {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, clone);
          });
        }
        return response;
      });
    })
  );
});
