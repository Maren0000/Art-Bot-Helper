// ==UserScript==
// @name         Art Bot Helper
// @namespace    https://github.com/Maren0000/Art-Bot-Helper
// @version      1.1.0
// @description  Post art from Twitter/X and Pixiv straight into the Discord art forums via Maren's Art Bot.
// @homepageURL  https://github.com/Maren0000/Art-Bot-Helper
// @updateURL    https://raw.githubusercontent.com/Maren0000/Art-Bot-Helper/main/userscript/artbot-helper.user.js
// @downloadURL  https://raw.githubusercontent.com/Maren0000/Art-Bot-Helper/main/userscript/artbot-helper.user.js
// @match        https://x.com/*
// @match        https://twitter.com/*
// @match        https://www.pixiv.net/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @connect      *
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Twitter's DOM churns constantly — every selector we depend on lives here.
  // -------------------------------------------------------------------------
  const SELECTORS = {
    tweetArticle: 'article[data-testid="tweet"]',
    tweetImage: 'img[src*="pbs.twimg.com/media"]',
    tweetText: '[data-testid="tweetText"]',
    userName: '[data-testid="User-Name"]',
  };

  const CLIENT_TIMEOUT_MS = 120000; // > server's 90s detection long-poll
  const MAX_ATTEMPTS = 5;
  const BASE_RETRY_MS = 5000;
  const MAX_RETRY_MS = 300000;
  const PERSIST_IMAGE_LIMIT = 8 * 1024 * 1024; // don't bloat GM storage past ~8MB per item
  const POSTED_CLEAR_MS = 10000;

  // Where new releases live; also the @updateURL, so opening it in a script
  // manager triggers the update/install dialog directly.
  const UPDATE_URL = 'https://raw.githubusercontent.com/Maren0000/Art-Bot-Helper/main/userscript/artbot-helper.user.js';
  const UPDATE_CHECK_MS = 24 * 60 * 60 * 1000;

  // -------------------------------------------------------------------------
  // Settings + queue persistence
  // -------------------------------------------------------------------------
  const settings = {
    get apiBase() { return (GM_getValue('apiBase') || '').replace(/\/+$/, ''); },
    set apiBase(v) { GM_setValue('apiBase', v.trim()); },
    // Long-lived credential from /api/auth/exchange; access tokens are minted
    // from it on demand and only they are sent on normal API requests.
    get refreshToken() { return GM_getValue('refreshToken') || ''; },
    set refreshToken(v) { GM_setValue('refreshToken', (v || '').trim()); },
    get accessToken() { return GM_getValue('accessToken') || ''; },
    set accessToken(v) { GM_setValue('accessToken', v || ''); },
    get accessExp() { return GM_getValue('accessExp') || 0; }, // unix seconds
    set accessExp(v) { GM_setValue('accessExp', v || 0); },
    get linkedAs() { return GM_getValue('linkedAs') || ''; },
    set linkedAs(v) { GM_setValue('linkedAs', v || ''); },
  };

  function isLinked() { return !!settings.refreshToken; }

  function unlink() {
    settings.refreshToken = '';
    settings.accessToken = '';
    settings.accessExp = 0;
    settings.linkedAs = '';
    metaCache = null;
  }

  // In-memory image bytes per item id (ArrayBuffer). Small images are also
  // persisted as base64 so the queue survives reloads; big ones are not.
  const imageCache = new Map();

  let queue = [];
  try { queue = JSON.parse(GM_getValue('queue') || '[]'); } catch (e) { queue = []; }
  // Rehydrate persisted images; items whose bytes are gone need re-capture.
  for (const item of queue) {
    if (item.imageB64) {
      imageCache.set(item.id, b64ToBuffer(item.imageB64));
    } else if (item.platform === 'twitter' && ['pending', 'detecting'].includes(item.state)) {
      item.state = 'error';
      item.error = { code: 'recaptured_needed', message: 'Image lost after page reload — re-capture this tweet.' };
    }
    if (item.state === 'detecting') item.state = 'pending';
    if (item.state === 'posting') item.state = 'awaiting_confirm';
  }

  function persistQueue() {
    GM_setValue('queue', JSON.stringify(queue));
  }

  function bufferToB64(buf) {
    let bin = '';
    const bytes = new Uint8Array(buf);
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(bin);
  }

  function b64ToBuffer(b64) {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes.buffer;
  }

  // -------------------------------------------------------------------------
  // API client (GM_xmlhttpRequest — CORS-exempt)
  // -------------------------------------------------------------------------
  let metaCache = null;

  function rawRequest(method, path, { json, formData, timeout, auth } = {}) {
    return new Promise((resolve, reject) => {
      const headers = {};
      if (auth) headers.Authorization = 'Bearer ' + auth;
      let data;
      if (json !== undefined) {
        headers['Content-Type'] = 'application/json';
        data = JSON.stringify(json);
      } else if (formData !== undefined) {
        data = formData; // browser sets the multipart boundary header itself
      }
      GM_xmlhttpRequest({
        method,
        url: settings.apiBase + path,
        headers,
        data,
        timeout: timeout || CLIENT_TIMEOUT_MS,
        ontimeout: () => reject({ kind: 'network', message: 'Request timed out.' }),
        onerror: () => reject({ kind: 'network', message: 'Network error — is the server reachable?' }),
        onload: (resp) => {
          let body = {};
          try { body = JSON.parse(resp.responseText); } catch (e) { /* non-JSON error page */ }
          if (resp.status >= 200 && resp.status < 300) return resolve(body);
          reject({
            kind: 'http',
            status: resp.status,
            code: body.code || 'http_' + resp.status,
            message: body.message || ('Server returned HTTP ' + resp.status),
            missing: body.missing,
            existing_post: body.existing_post,
          });
        },
      });
    });
  }

  // Single in-flight refresh shared by concurrent callers.
  let refreshing = null;

  function refreshAccess() {
    if (refreshing) return refreshing;
    refreshing = rawRequest('POST', '/api/auth/refresh', {
      json: { refresh_token: settings.refreshToken },
      timeout: 15000,
    }).then((resp) => {
      settings.accessToken = resp.access_token;
      settings.accessExp = Math.floor(Date.now() / 1000) + (resp.access_expires_in || 3600);
      if (resp.guild_name) settings.linkedAs = (resp.user_name ? resp.user_name + ' @ ' : '') + resp.guild_name;
      return settings.accessToken;
    }).catch((err) => {
      if (err.kind === 'http' && err.status === 401) {
        // Refresh token expired/revoked or the server key rotated: re-link.
        throw { kind: 'config', code: err.code, message: 'Link expired or revoked — run /token in Discord and re-link in settings (⚙).' };
      }
      throw err;
    }).finally(() => { refreshing = null; });
    return refreshing;
  }

  async function ensureAccess() {
    if (!settings.apiBase) throw { kind: 'config', message: 'Set the API URL in settings (⚙) first.' };
    if (!isLinked()) throw { kind: 'config', message: 'Not linked — run /token in Discord and link in settings (⚙).' };
    if (settings.accessToken && Date.now() / 1000 < settings.accessExp - 60) return settings.accessToken;
    return refreshAccess();
  }

  async function apiRequest(method, path, opts = {}) {
    let token = await ensureAccess();
    try {
      return await rawRequest(method, path, Object.assign({}, opts, { auth: token }));
    } catch (err) {
      // Access token died mid-flight (clock skew, key rotation): refresh once and retry.
      if (err.kind === 'http' && err.status === 401 && err.code === 'token_expired') {
        settings.accessToken = '';
        settings.accessExp = 0;
        token = await ensureAccess();
        return await rawRequest(method, path, Object.assign({}, opts, { auth: token }));
      }
      throw err;
    }
  }

  function fetchBytes(url) {
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method: 'GET',
        url,
        responseType: 'arraybuffer',
        timeout: 60000,
        ontimeout: () => reject(new Error('Image download timed out.')),
        onerror: () => reject(new Error('Failed to download image.')),
        onload: (resp) => resp.status === 200 ? resolve(resp.response) : reject(new Error('Image download failed (HTTP ' + resp.status + ').')),
      });
    });
  }

  // -------------------------------------------------------------------------
  // Page capture
  // -------------------------------------------------------------------------
  function isTwitter() { return /(^|\.)(twitter|x)\.com$/.test(location.hostname); }
  function isPixiv() { return /(^|\.)pixiv\.net$/.test(location.hostname); }

  function captureContext() {
    if (isTwitter()) {
      const m = location.pathname.match(/^\/([A-Za-z0-9_]+)\/status\/(\d+)/);
      if (!m) return { error: 'Open a tweet permalink (…/status/…) to capture from it.' };
      const [, handle, tweetId] = m;
      const canonical = 'https://x.com/' + handle + '/status/' + tweetId;

      // Find the article that belongs to this status id (quoted/reply tweets
      // render as articles too — match on the permalink inside).
      let article = null;
      for (const a of document.querySelectorAll(SELECTORS.tweetArticle)) {
        if (a.querySelector('a[href*="/status/' + tweetId + '"]') || location.pathname.includes(tweetId)) {
          article = a;
          break;
        }
      }
      if (!article) article = document.querySelector(SELECTORS.tweetArticle);
      if (!article) return { error: 'Could not find the tweet on this page (try scrolling to it).' };

      const imgs = [...article.querySelectorAll(SELECTORS.tweetImage)];
      if (!imgs.length) return { error: 'No images found in this tweet.' };
      const images = imgs.map((img) => {
        const u = new URL(img.src);
        u.searchParams.set('name', 'orig'); // full-resolution original
        return { thumb: img.src, orig: u.href, format: u.searchParams.get('format') || 'jpg' };
      });

      const nameEl = article.querySelector(SELECTORS.userName);
      const textEl = article.querySelector(SELECTORS.tweetText);
      return {
        platform: 'twitter',
        url: canonical,
        author_handle: handle,
        author_name: nameEl ? nameEl.innerText.split('\n')[0] : handle,
        text: textEl ? textEl.innerText : '',
        images,
        id: tweetId,
      };
    }

    if (isPixiv()) {
      const m = location.pathname.match(/\/artworks\/(\d+)/);
      if (!m) return { error: 'Open a pixiv artwork page (…/artworks/…) to capture from it.' };
      const ctx = { platform: 'pixiv', url: 'https://www.pixiv.net/artworks/' + m[1], id: m[1], loading: true };
      loadPixivPages(ctx);
      return ctx;
    }

    return { error: 'Unsupported page.' };
  }

  // Pixiv's own ajax API (same origin, user's session) lists every page of an
  // artwork with thumbnails — submission itself stays link-only.
  async function loadPixivPages(ctx) {
    try {
      const resp = await fetch('/ajax/illust/' + ctx.id + '/pages?lang=en', { credentials: 'same-origin' });
      const data = await resp.json();
      if (data.error) throw new Error(data.message || 'pixiv returned an error');
      ctx.images = data.body.map((page, i) => ({
        thumb: (page.urls && (page.urls.small || page.urls.thumb_mini)) || '',
        num: i + 1,
      }));
      ctx.loading = false;
    } catch (err) {
      ctx.error = 'Could not load the artwork pages: ' + (err.message || err);
    }
    if (captureState === ctx) render();
  }

  // -------------------------------------------------------------------------
  // Queue engine — serial: one in-flight request at a time
  // -------------------------------------------------------------------------
  let processing = false;
  let retryTimer = null;

  function newItem(base) {
    return Object.assign({
      id: 'q' + Date.now() + Math.random().toString(36).slice(2, 7),
      idemKey: crypto.randomUUID(),
      state: 'pending',
      attempts: 0,
      nextRetryAt: 0,
      submissionId: null,
      detected: null,
      edits: {},
      error: null,
    }, base);
  }

  function scheduleRetry(item) {
    item.attempts += 1;
    if (item.attempts >= MAX_ATTEMPTS) {
      item.state = 'error';
      item.error = item.error || { message: 'Gave up after ' + MAX_ATTEMPTS + ' attempts.' };
      item.error.manualRetry = true;
      return;
    }
    const delay = Math.min(BASE_RETRY_MS * Math.pow(2, item.attempts - 1), MAX_RETRY_MS);
    item.nextRetryAt = Date.now() + delay;
  }

  function retryable(err) {
    return err.kind === 'network' || (err.kind === 'http' && (err.status >= 500 || err.status === 429));
  }

  async function submitItem(item) {
    item.state = 'detecting';
    render();
    let resp;
    if (item.platform === 'pixiv') {
      resp = await apiRequest('POST', '/api/submissions', {
        json: {
          platform: 'pixiv',
          url: item.url,
          image_num: item.imageNum || null,
          idempotency_key: item.idemKey,
        },
      });
    } else {
      const buf = imageCache.get(item.id);
      if (!buf) throw { kind: 'config', message: 'Image bytes lost — re-capture this tweet.' };
      const fd = new FormData();
      fd.append('image', new Blob([buf]), 'twt_' + item.meta.id + '_' + (item.imageIdx + 1) + '.' + item.meta.format);
      fd.append('payload', JSON.stringify({
        platform: 'twitter',
        url: item.url,
        author_handle: item.meta.author_handle,
        author_name: item.meta.author_name,
        text: item.meta.text,
        idempotency_key: item.idemKey,
      }));
      resp = await apiRequest('POST', '/api/submissions', { formData: fd });
    }
    // Idempotent replay of an already-confirmed item returns the final result.
    if (resp.thread_links) {
      item.state = 'posted';
      item.result = resp;
      return;
    }
    item.submissionId = resp.submission_id;
    item.detected = resp.detected;
    item.edits.characters = (resp.detected.characters || []).join(',');
    item.edits.forumId = resp.detected.forum ? resp.detected.forum.id : '';
    item.state = 'awaiting_confirm';
    item.attempts = 0;
    // Once uploaded, the server holds the image — free GM storage.
    if (item.imageB64) { delete item.imageB64; }
  }

  async function confirmItem(item) {
    item.state = 'posting';
    render();
    try {
      const resp = await apiRequest('POST', '/api/submissions/' + item.submissionId + '/confirm', {
        json: { characters: item.edits.characters, forum_id: item.edits.forumId },
      });
      item.state = 'posted';
      item.result = resp;
      item.error = null;
      setTimeout(() => {
        queue = queue.filter((q) => q.id !== item.id);
        persistQueue();
        render();
      }, POSTED_CLEAR_MS);
    } catch (err) {
      item.error = err;
      if (err.kind === 'http' && err.status === 404 && err.code === 'submission_not_found') {
        // Server restarted / submission expired: go around again. The
        // idempotency key + server-side phash dedup prevent double posts.
        item.submissionId = null;
        item.state = 'pending';
        scheduleRetry(item);
      } else if (err.kind === 'http' && err.code === 'threads_not_found') {
        item.state = 'awaiting_confirm'; // user fixes characters/forum, retries
      } else if (retryable(err)) {
        item.state = 'awaiting_confirm';
        scheduleRetry(item);
        item.autoConfirm = true;
      } else {
        item.state = 'error';
      }
    }
    persistQueue();
    render();
  }

  async function pump() {
    if (processing) return;
    processing = true;
    try {
      while (true) {
        const now = Date.now();
        const item = queue.find((q) =>
          (q.state === 'pending' && q.nextRetryAt <= now) ||
          (q.state === 'awaiting_confirm' && q.autoConfirm && q.nextRetryAt <= now));
        if (!item) break;
        if (item.state === 'pending') {
          try {
            await submitItem(item);
          } catch (err) {
            item.error = err;
            if (retryable(err)) {
              item.state = 'pending';
              scheduleRetry(item);
            } else {
              item.state = 'error';
            }
          }
        } else {
          item.autoConfirm = false;
          await confirmItem(item);
        }
        persistQueue();
        render();
      }
    } finally {
      processing = false;
    }
    // Wake up again when the earliest retry is due.
    const next = queue
      .filter((q) => (q.state === 'pending' || q.autoConfirm) && q.nextRetryAt > Date.now())
      .map((q) => q.nextRetryAt);
    clearTimeout(retryTimer);
    if (next.length) retryTimer = setTimeout(pump, Math.max(500, Math.min(...next) - Date.now()));
  }

  // -------------------------------------------------------------------------
  // UI — shadow DOM corner widget
  // -------------------------------------------------------------------------
  const host = document.createElement('div');
  host.id = 'artbot-helper-host';
  const shadow = host.attachShadow({ mode: 'open' });
  document.body.appendChild(host);

  const style = document.createElement('style');
  style.textContent = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    .fab {
      position: fixed; bottom: 18px; right: 18px; z-index: 2147483647;
      width: 44px; height: 44px; border-radius: 50%;
      background: #5865F2; color: #fff; border: none; cursor: pointer;
      font-size: 20px; line-height: 44px; text-align: center;
      box-shadow: 0 2px 10px rgba(0,0,0,.35);
    }
    .badge {
      position: absolute; top: -4px; right: -4px; min-width: 18px; height: 18px;
      border-radius: 9px; background: #ED4245; color: #fff;
      font-size: 11px; line-height: 18px; padding: 0 4px; display: none;
    }
    .panel {
      position: fixed; bottom: 72px; right: 18px; z-index: 2147483647;
      width: 340px; max-height: 70vh; overflow-y: auto;
      background: #1e1f22; color: #dbdee1; border-radius: 10px;
      box-shadow: 0 4px 24px rgba(0,0,0,.5); padding: 10px; display: none;
      font-size: 13px;
    }
    .panel.open { display: block; }
    .row { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
    .row h3 { flex: 1; margin: 0; font-size: 14px; color: #fff; }
    button.small {
      background: #4e5058; border: none; color: #fff; border-radius: 5px;
      padding: 4px 8px; cursor: pointer; font-size: 12px;
    }
    button.small.primary { background: #5865F2; }
    button.small.danger { background: #da373c; }
    button.small:disabled { opacity: .5; cursor: default; }
    input, select {
      width: 100%; background: #111214; color: #dbdee1;
      border: 1px solid #3f4147; border-radius: 5px; padding: 5px 6px; font-size: 12px;
    }
    label { display: block; margin: 6px 0 2px; color: #949ba4; font-size: 11px; }
    .item { background: #2b2d31; border-radius: 8px; padding: 8px; margin-bottom: 8px; }
    .item .head { display: flex; align-items: center; gap: 8px; cursor: pointer; }
    .item img.thumb { width: 36px; height: 36px; object-fit: cover; border-radius: 5px; background: #111; }
    .item .title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .status { font-size: 11px; }
    .status.ok { color: #23a55a; }
    .status.err { color: #f23f43; }
    .status.busy { color: #f0b232; }
    .body { margin-top: 8px; display: none; }
    .item.expanded .body { display: block; }
    .links a { color: #00a8fc; display: block; font-size: 12px; word-break: break-all; }
    .muted { color: #80848e; font-size: 11px; }
    .settings { border-bottom: 1px solid #3f4147; margin-bottom: 8px; padding-bottom: 8px; display: none; }
    .settings.open { display: block; }
    .update { background: #2b2d31; border: 1px solid #f0b232; border-radius: 8px; padding: 6px 8px; margin-bottom: 8px; }
    .update a { color: #f0b232; text-decoration: none; font-size: 12px; }
    .thumbs { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
    .thumbs img { width: 56px; height: 56px; object-fit: cover; border-radius: 6px; cursor: pointer; border: 2px solid transparent; }
    .thumbs img:hover { border-color: #5865F2; }
    .empty { text-align: center; color: #80848e; padding: 12px 0; }
  `;
  shadow.appendChild(style);

  const fab = document.createElement('button');
  fab.className = 'fab';
  fab.title = 'Art Bot Helper';
  fab.innerHTML = '🎨<span class="badge"></span>';
  shadow.appendChild(fab);

  const panel = document.createElement('div');
  panel.className = 'panel';
  shadow.appendChild(panel);

  fab.addEventListener('click', () => {
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) render();
  });

  GM_registerMenuCommand('Art Bot: open panel', () => panel.classList.add('open'));
  GM_registerMenuCommand('Art Bot: check for updates', () => checkForUpdate(true));

  // -------------------------------------------------------------------------
  // Update check — the script manager auto-updates via @updateURL, but a
  // daily in-panel banner is a friendlier reminder (and works even when the
  // manager's update interval is long or updates are off).
  // -------------------------------------------------------------------------
  const currentVersion = (typeof GM_info !== 'undefined' && GM_info.script && GM_info.script.version) || '0';
  let updateAvailable = GM_getValue('updateAvailable') || '';

  function cmpVersions(a, b) {
    const pa = String(a).split('.').map(Number);
    const pb = String(b).split('.').map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      const d = (pa[i] || 0) - (pb[i] || 0);
      if (d) return d;
    }
    return 0;
  }

  // If the user already updated past the remembered version, drop the banner.
  if (updateAvailable && cmpVersions(currentVersion, updateAvailable) >= 0) {
    updateAvailable = '';
    GM_setValue('updateAvailable', '');
  }

  function checkForUpdate(force) {
    if (!force && Date.now() - (GM_getValue('lastUpdateCheck') || 0) < UPDATE_CHECK_MS) return;
    GM_setValue('lastUpdateCheck', Date.now());
    GM_xmlhttpRequest({
      method: 'GET',
      url: UPDATE_URL + '?t=' + Date.now(), // bust the raw.githubusercontent cache
      timeout: 30000,
      onload: (resp) => {
        const m = resp.responseText.match(/@version\s+([\d.]+)/);
        if (!m) return;
        updateAvailable = cmpVersions(m[1], currentVersion) > 0 ? m[1] : '';
        GM_setValue('updateAvailable', updateAvailable);
        render();
      },
      onerror: () => {},
      ontimeout: () => {},
    });
  }

  let settingsOpen = !settings.apiBase || !isLinked();
  let captureState = null; // holds twitter/pixiv image-picker context

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function statusLine(item) {
    switch (item.state) {
      case 'pending': return ['busy', item.nextRetryAt > Date.now() ? 'Retrying ' + new Date(item.nextRetryAt).toLocaleTimeString() + '… (attempt ' + (item.attempts + 1) + ')' : 'Queued…'];
      case 'detecting': return ['busy', 'Detecting characters… (can take ~30s)'];
      case 'awaiting_confirm': return item.error ? ['err', errText(item)] : ['busy', 'Review & post'];
      case 'posting': return ['busy', 'Posting…'];
      case 'posted': return ['ok', 'Posted!'];
      case 'error': return ['err', errText(item)];
      default: return ['busy', item.state];
    }
  }

  function errText(item) {
    if (!item.error) return 'Error';
    let t = item.error.message || 'Error';
    if (item.error.missing && item.error.missing.length) t += ' Missing: ' + item.error.missing.join(', ');
    return t;
  }

  function render() {
    const badge = fab.querySelector('.badge');
    const active = queue.filter((q) => q.state !== 'posted').length;
    badge.style.display = active ? 'block' : 'none';
    badge.textContent = active;

    if (!panel.classList.contains('open')) return;

    const forums = metaCache ? metaCache.forums : [];
    const linkControls = isLinked() ? `
        <div class="row" style="margin-top:8px">
          <span class="muted" style="flex:1">Linked: ${esc(settings.linkedAs || 'unknown')}</span>
          <button class="small primary" data-act="test">Test connection</button>
          <button class="small danger" data-act="unlink">Unlink</button>
        </div>
        <div class="muted" data-role="testresult">${metaCache ? 'Connected to ' + esc(metaCache.guild_name) : ''}</div>
    ` : `
        <label>Setup token (from /token in Discord — valid 5 min)</label>
        <input data-set="setupToken" type="password" placeholder="abt1.…">
        <div class="row" style="margin-top:8px">
          <button class="small primary" data-act="link">Link account</button>
          <span class="muted" data-role="testresult"></span>
        </div>
    `;
    panel.innerHTML = `
      <div class="row">
        <h3>Art Bot Helper</h3>
        <button class="small" data-act="settings">⚙</button>
        <button class="small primary" data-act="capture">Capture from this page</button>
      </div>
      ${updateAvailable ? `
      <div class="update">
        <a href="${esc(UPDATE_URL)}" target="_blank">⬆ Update available (v${esc(updateAvailable)}) — click to install</a>
      </div>` : ''}
      <div class="settings ${settingsOpen ? 'open' : ''}">
        <label>API URL</label>
        <input data-set="apiBase" placeholder="https://artbot.example.com" value="${esc(settings.apiBase)}">
        ${linkControls}
      </div>
      <div data-role="capture"></div>
      <div data-role="list"></div>
    `;

    const list = panel.querySelector('[data-role="list"]');
    if (!queue.length) {
      list.innerHTML = '<div class="empty">Queue is empty.<br>Open a tweet or pixiv artwork and hit Capture.</div>';
    } else {
      list.innerHTML = queue.map((item) => {
        const [cls, text] = statusLine(item);
        const forumOpts = forums.map((f) =>
          `<option value="${esc(f.id)}" ${item.edits && item.edits.forumId === f.id ? 'selected' : ''}>${esc(f.name)}</option>`).join('');
        const canEdit = item.state === 'awaiting_confirm';
        return `
        <div class="item ${item.expanded ? 'expanded' : ''}" data-id="${esc(item.id)}">
          <div class="head" data-act="toggle">
            <img class="thumb" src="${esc(item.thumb || '')}" onerror="this.style.visibility='hidden'">
            <div style="flex:1;min-width:0">
              <div class="title">${esc(item.platform)} · ${esc(item.url)}</div>
              <div class="status ${cls}">${esc(text)}</div>
            </div>
            <button class="small danger" data-act="remove">✕</button>
          </div>
          <div class="body">
            ${item.state === 'posted' && item.result ? `
              <div class="links">${item.result.thread_links.map((l) => `<a href="${esc(l)}" target="_blank">${esc(l)}</a>`).join('')}</div>
              ${item.result.note ? `<div class="muted">${esc(item.result.note.replace(/\*\*/g, ''))}</div>` : ''}
            ` : ''}
            ${item.error && item.error.existing_post ? `<div class="links"><a href="${esc(item.error.existing_post)}" target="_blank">Existing post</a></div>` : ''}
            ${canEdit ? `
              <label>Characters (comma separated)</label>
              <input data-edit="characters" value="${esc(item.edits.characters)}">
              <label>Forum (series - safety level)</label>
              <select data-edit="forumId">
                <option value="">— pick a forum —</option>
                ${forumOpts}
              </select>
              ${item.detected ? `<div class="muted" style="margin-top:4px">Detected: ${esc((item.detected.characters || []).join(', ') || 'nothing')}${item.detected.series ? ' · ' + esc(item.detected.series) : ''}${item.detected.safety ? ' · ' + esc(item.detected.safety) : ''}</div>` : ''}
              <div class="row" style="margin-top:8px">
                <button class="small primary" data-act="post">Post</button>
              </div>
            ` : ''}
            ${item.state === 'error' && (!item.error || item.error.code !== 'duplicate') ? `
              <div class="row" style="margin-top:8px"><button class="small primary" data-act="retry">Retry</button></div>
            ` : ''}
          </div>
        </div>`;
      }).join('');
    }

    wireEvents();
    renderCapture();
  }

  function renderCapture() {
    const box = panel.querySelector('[data-role="capture"]');
    if (!captureState) { box.innerHTML = ''; return; }
    if (captureState.error) {
      box.innerHTML = `<div class="item"><div class="status err">${esc(captureState.error)}</div></div>`;
      return;
    }
    if (captureState.platform === 'twitter') {
      box.innerHTML = `
        <div class="item expanded">
          <div class="title">Pick image(s) from @${esc(captureState.author_handle)}</div>
          <div class="thumbs">
            ${captureState.images.map((img, i) => `<img src="${esc(img.thumb)}" title="Image ${i + 1}" data-pick="${i}">`).join('')}
          </div>
          <div class="row" style="margin-top:6px"><button class="small" data-act="cancelcapture">Cancel</button></div>
        </div>`;
      box.querySelectorAll('[data-pick]').forEach((el) => el.addEventListener('click', () => pickTwitterImage(+el.dataset.pick)));
      box.querySelector('[data-act="cancelcapture"]').addEventListener('click', () => { captureState = null; render(); });
    } else {
      if (captureState.loading) {
        box.innerHTML = `
          <div class="item expanded">
            <div class="title">Pixiv artwork #${esc(captureState.id)}</div>
            <div class="status busy">Loading pages…</div>
            <div class="row" style="margin-top:6px"><button class="small" data-act="cancelcapture">Cancel</button></div>
          </div>`;
        box.querySelector('[data-act="cancelcapture"]').addEventListener('click', () => { captureState = null; render(); });
        return;
      }
      box.innerHTML = `
        <div class="item expanded">
          <div class="title">Pixiv artwork #${esc(captureState.id)} — pick image (${captureState.images.length})</div>
          <div class="thumbs">
            ${captureState.images.map((img) => `<img src="${esc(img.thumb)}" title="Image ${img.num}" data-pick="${img.num}">`).join('')}
          </div>
          <div class="row" style="margin-top:6px"><button class="small" data-act="cancelcapture">Cancel</button></div>
        </div>`;
      box.querySelectorAll('[data-pick]').forEach((el) => el.addEventListener('click', () => {
        const num = +el.dataset.pick;
        const img = captureState.images[num - 1];
        queue.push(newItem({
          platform: 'pixiv',
          url: captureState.url,
          imageNum: num > 1 ? num : null,
          thumb: img ? img.thumb : '',
        }));
        captureState = null;
        persistQueue(); render(); pump();
      }));
      box.querySelector('[data-act="cancelcapture"]').addEventListener('click', () => { captureState = null; render(); });
    }
  }

  async function pickTwitterImage(idx) {
    const ctx = captureState;
    const img = ctx.images[idx];
    captureState = null;
    const item = newItem({
      platform: 'twitter',
      url: ctx.url,
      thumb: img.thumb,
      imageIdx: idx,
      meta: { id: ctx.id, author_handle: ctx.author_handle, author_name: ctx.author_name, text: ctx.text, format: img.format },
    });
    item.state = 'pending';
    item.stateNote = 'Downloading image…';
    queue.push(item);
    persistQueue(); render();
    try {
      const buf = await fetchBytes(img.orig);
      imageCache.set(item.id, buf);
      if (buf.byteLength <= PERSIST_IMAGE_LIMIT) item.imageB64 = bufferToB64(buf);
      persistQueue();
      pump();
    } catch (err) {
      item.state = 'error';
      item.error = { message: err.message };
      persistQueue(); render();
    }
  }

  function wireEvents() {
    panel.querySelector('[data-act="settings"]').addEventListener('click', () => {
      settingsOpen = !settingsOpen; render();
    });
    panel.querySelector('[data-act="capture"]').addEventListener('click', () => {
      captureState = captureContext(); render();
    });
    const linkBtn = panel.querySelector('[data-act="link"]');
    if (linkBtn) linkBtn.addEventListener('click', async () => {
      settings.apiBase = panel.querySelector('[data-set="apiBase"]').value;
      const setupToken = panel.querySelector('[data-set="setupToken"]').value.trim();
      const out = panel.querySelector('[data-role="testresult"]');
      if (!settings.apiBase) { out.textContent = 'Enter the API URL first.'; return; }
      if (!setupToken) { out.textContent = 'Paste the setup token from /token.'; return; }
      out.textContent = 'Linking…';
      try {
        const resp = await rawRequest('POST', '/api/auth/exchange', {
          json: { setup_token: setupToken },
          timeout: 15000,
        });
        settings.refreshToken = resp.refresh_token;
        settings.accessToken = resp.access_token;
        settings.accessExp = Math.floor(Date.now() / 1000) + (resp.access_expires_in || 3600);
        settings.linkedAs = (resp.user_name ? resp.user_name + ' @ ' : '') + (resp.guild_name || '');
        metaCache = await apiRequest('GET', '/api/meta', { timeout: 15000 });
        settingsOpen = false;
        render();
        pump();
      } catch (err) {
        out.textContent = err.message;
      }
    });

    const testBtn = panel.querySelector('[data-act="test"]');
    if (testBtn) testBtn.addEventListener('click', async () => {
      settings.apiBase = panel.querySelector('[data-set="apiBase"]').value;
      const out = panel.querySelector('[data-role="testresult"]');
      out.textContent = 'Testing…';
      try {
        metaCache = await apiRequest('GET', '/api/meta', { timeout: 15000 });
        out.textContent = 'Connected to ' + metaCache.guild_name;
      } catch (err) {
        out.textContent = err.message;
      }
    });

    const unlinkBtn = panel.querySelector('[data-act="unlink"]');
    if (unlinkBtn) unlinkBtn.addEventListener('click', () => {
      unlink();
      settingsOpen = true;
      render();
    });

    panel.querySelectorAll('.item[data-id]').forEach((el) => {
      const item = queue.find((q) => q.id === el.dataset.id);
      if (!item) return;
      el.querySelector('[data-act="toggle"]').addEventListener('click', (ev) => {
        if (ev.target.closest('[data-act="remove"]')) return;
        item.expanded = !item.expanded; render();
      });
      el.querySelector('[data-act="remove"]').addEventListener('click', () => {
        if (item.submissionId && ['awaiting_confirm'].includes(item.state)) {
          apiRequest('DELETE', '/api/submissions/' + item.submissionId, { timeout: 15000 }).catch(() => {});
        }
        imageCache.delete(item.id);
        queue = queue.filter((q) => q.id !== item.id);
        persistQueue(); render();
      });
      el.querySelectorAll('[data-edit]').forEach((input) => {
        input.addEventListener('change', () => {
          item.edits[input.dataset.edit] = input.value;
          persistQueue();
        });
      });
      const postBtn = el.querySelector('[data-act="post"]');
      if (postBtn) postBtn.addEventListener('click', () => {
        item.edits.characters = el.querySelector('[data-edit="characters"]').value;
        item.edits.forumId = el.querySelector('[data-edit="forumId"]').value;
        if (!item.edits.characters.trim()) { item.error = { message: 'Enter at least one character.' }; render(); return; }
        if (!item.edits.forumId) { item.error = { message: 'Pick a forum channel.' }; render(); return; }
        item.error = null;
        persistQueue();
        confirmItem(item);
      });
      const retryBtn = el.querySelector('[data-act="retry"]');
      if (retryBtn) retryBtn.addEventListener('click', () => {
        item.attempts = 0;
        item.nextRetryAt = 0;
        item.error = null;
        item.state = item.submissionId ? 'awaiting_confirm' : 'pending';
        persistQueue(); render(); pump();
      });
    });
  }

  // Preload forum list if linked, then resume any persisted queue work.
  if (settings.apiBase && isLinked()) {
    apiRequest('GET', '/api/meta', { timeout: 15000 })
      .then((m) => { metaCache = m; render(); })
      .catch(() => {});
  }
  render();
  pump();
  checkForUpdate(false);
})();
