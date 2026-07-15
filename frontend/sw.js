const CACHE_NAME = "mrmoney-v1";
const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/app.js",
  "/styles.css",
  "/manifest.json",
  "/icons/icon-192.svg",
  "/icons/icon-512.svg",
];

const API_CACHE = "mrmoney-api-v1";
const API_CACHE_DURATION = 60 * 1000;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME && k !== API_CACHE).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method === "POST") {
    event.respondWith(handleOfflineMutation(request));
    return;
  }
  if (request.method !== "GET") return;

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirstWithCache(request));
    return;
  }

  if (url.pathname === "/sw.js" || url.pathname === "/manifest.json") {
    event.respondWith(networkOnly(request));
    return;
  }

  event.respondWith(cacheFirst(request));
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response("Offline", { status: 503, statusText: "Offline" });
  }
}

async function networkFirstWithCache(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(API_CACHE);
      const entry = { response: response.clone(), timestamp: Date.now() };
      cache.put(request, new Response(JSON.stringify(entry), {
        headers: { "Content-Type": "application/json" },
      }));
    }
    return response;
  } catch {
    const cached = await caches.open(API_CACHE).then((c) => c.match(request));
    if (cached) {
      try {
        const data = JSON.parse(await cached.text());
        if (Date.now() - data.timestamp < API_CACHE_DURATION * 10) {
          return new Response(data.response.body, {
            status: data.response.status,
            headers: data.response.headers,
          });
        }
      } catch { /* ignore */ }
    }
    return new Response(JSON.stringify({ error: "Offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}

async function networkOnly(request) {
  return fetch(request);
}

async function handleOfflineMutation(request) {
  try {
    const response = await fetch(request.clone());
    return response;
  } catch {
    const body = await request.clone().text();
    const pending = JSON.parse(localStorage.getItem("mm_offline_queue") || "[]");
    pending.push({ url: request.url, method: request.method, body, timestamp: Date.now() });
    localStorage.setItem("mm_offline_queue", JSON.stringify(pending));
    return new Response(JSON.stringify({ error: "Offline — request queued" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}
