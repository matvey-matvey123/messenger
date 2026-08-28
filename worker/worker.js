// Кокаколик — Cloudflare Worker
// Отдаёт фронтенд из GitHub Pages, а /api и /uploads проксирует на PythonAnywhere.
// Вставьте этот код в облачный редактор Cloudflare (Workers > Create > name: kokacolik > Edit code > Deploy).

const FRONT = 'https://matvey-matvey123.github.io/messenger';
const BACK = 'https://matveymatveyg.pythonanywhere.com';

const BACKEND_PREFIXES = ['/api', '/uploads'];

export default {
  async fetch(request) {
    const url = new URL(request.url);

    const isBackend = BACKEND_PREFIXES.some(
      (p) => url.pathname === p || url.pathname.startsWith(p + '/')
    );

    if (!isBackend) {
      // Фронтенд из GitHub Pages
      const target = FRONT + url.pathname + url.search;
      const resp = await fetch(target, {
        method: 'GET',
        redirect: 'follow',
        headers: { 'user-agent': 'Mozilla/5.0' },
      });
      return new Response(resp.body, {
        status: resp.status,
        statusText: resp.statusText,
        headers: resp.headers,
      });
    }

    // API / вложения — на PythonAnywhere (с cookie сессии туда и обратно)
    const target = BACK + url.pathname + url.search;
    const headers = new Headers(request.headers);
    headers.delete('origin');
    headers.delete('referer');

    const init = {
      method: request.method,
      headers,
      redirect: 'follow',
    };
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      init.body = request.body;
    }

    const resp = await fetch(target, init);
    return new Response(resp.body, {
      status: resp.status,
      statusText: resp.statusText,
      headers: resp.headers,
    });
  },
};