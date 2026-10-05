// Cloudflare Pages Function для Кокаколика.
// Фронтенд отдаётся из GitHub (статика Pages), а /api и /uploads идут на PythonAnywhere.
// Файл должен лежать в корне ветки gh-pages: functions/[[path]].js

const BACK = 'https://matveymatveyg.pythonanywhere.com';
const BACKEND_PREFIXES = ['/api', '/uploads'];

export async function onRequest(context) {
  const url = new URL(context.request.url);

  const isBackend = BACKEND_PREFIXES.some(
    (p) => url.pathname === p || url.pathname.startsWith(p + '/')
  );

  if (!isBackend) {
    return context.next();
  }

  const target = BACK + url.pathname + url.search;
  const headers = new Headers(context.request.headers);
  headers.delete('origin');
  headers.delete('referer');

  const init = {
    method: context.request.method,
    headers,
    redirect: 'follow',
  };
  if (context.request.method !== 'GET' && context.request.method !== 'HEAD') {
    init.body = context.request.body;
  }

  const resp = await fetch(target, init);
  return new Response(resp.body, {
    status: resp.status,
    statusText: resp.statusText,
    headers: resp.headers,
  });
}