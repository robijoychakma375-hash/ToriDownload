async function createOffer(url, requireAuto = false, filename = '', kind = 'file') {
  if (!url || !/^https?:\/\//i.test(url)) return null;
  const {enabled} = await chrome.storage.local.get({enabled:true});
  if (requireAuto && !enabled) return null;
  try {
    const response = await fetch('http://127.0.0.1:8765/offer', {
      method:'POST', headers:{'Content-Type':'application/json','X-Tori-Connector':chrome.runtime.id},
      body:JSON.stringify({url,filename,verify:kind === 'file',kind}), signal:AbortSignal.timeout(8000)
    });
    if (!response.ok) return null;
    const {id} = await response.json();
    return /^[\w-]{12,80}$/.test(id || '') ? id : null;
  } catch (_) { return null; }
}
async function getOfferResult(id) {
  try {
    const check = await fetch('http://127.0.0.1:8765/offer/'+id, {
      headers:{'X-Tori-Connector':chrome.runtime.id}, signal:AbortSignal.timeout(5000)
    });
    return check.ok ? (await check.json()).result : 'fallback';
  } catch (_) { return 'fallback'; }
}
async function send(url, requireAuto = false, filename = '') {
  const id = await createOffer(url, requireAuto, filename);
  if (!id) return 'fallback';
  try {
    for (let tries = 0; tries < 125; tries++) {
      await new Promise(resolve => setTimeout(resolve, 950));
      const result = await getOfferResult(id);
      if (['accepted','declined','fallback'].includes(result)) return result;
      // A pending event may last two minutes; touch an extension API so the
      // Manifest V3 worker stays awake while the user chooses.
      if (tries % 12 === 0) await chrome.storage.local.get('enabled');
    }
    return 'fallback';
  } catch (_) { return 'fallback'; }
}
// A file intentionally returned to Chrome must not get intercepted again.
const browserFallbacks = new Map();
function suppressBrowserFallback(url) {
  const previous = browserFallbacks.get(url);
  browserFallbacks.set(url, {count:(previous?.count || 0) + 1, until:Date.now()+15000});
}
function consumeBrowserFallback(item) {
  for (const url of [item.url, item.finalUrl]) {
    const entry = browserFallbacks.get(url);
    if (!entry) continue;
    browserFallbacks.delete(url);
    if (Date.now() > entry.until) continue;
    if (entry.count > 1) browserFallbacks.set(url, {...entry, count:entry.count-1});
    return true;
  }
  return false;
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!sender.tab || !/^https?:\/\//i.test(sender.url || '') || !message) return;
  if (message.type === 'tori-offer-status') {
    if (!/^[\w-]{12,80}$/.test(message.id || '')) return;
    getOfferResult(message.id).then(result => respond({result}));
    return true;
  }
  if (typeof message.url !== 'string' || !/^https?:\/\//i.test(message.url)) return;
  if (message.type === 'tori-video') {
    createOffer(message.url, false, typeof message.filename === 'string' ? message.filename : '', 'video')
      .then(id => respond({id})).catch(() => respond({id:null}));
    return true;
  }
  if (message.type === 'tori-browser-fallback') {
    suppressBrowserFallback(message.url);
    respond({ok:true});
    return;
  }
  if (message.type === 'tori-preclick') {
    // A new click is never a continuation of an earlier browser fallback.
    browserFallbacks.delete(message.url);
    createOffer(message.url, true, typeof message.filename === 'string' ? message.filename : '')
      .then(id => respond({id})).catch(() => respond({id:null}));
    return true;
  }
});
let pendingUpdate = Promise.resolve();
function changePending(change) {
  pendingUpdate = pendingUpdate.then(async () => {
    const {pendingHandoffs={}} = await chrome.storage.local.get({pendingHandoffs:{}});
    change(pendingHandoffs);
    await chrome.storage.local.set({pendingHandoffs});
  });
  return pendingUpdate;
}
async function recoverHandoffs(force = false) {
  const {pendingHandoffs={}} = await chrome.storage.local.get({pendingHandoffs:{}});
  const {toriOnly=true} = await chrome.storage.local.get({toriOnly:true});
  for (const [key, since] of Object.entries(pendingHandoffs)) {
    if (!force && Date.now()-since < 140000) continue;
    try {
      if (toriOnly) {
        await chrome.downloads.cancel(Number(key));
        await chrome.downloads.erase({id:Number(key)});
      } else await chrome.downloads.resume(Number(key));
    } catch (_) { /* Already completed or cancelled. */ }
    await changePending(state => { delete state[key]; });
  }
}
async function updateConnectionBadge() {
  let connected = false;
  try {
    const response = await fetch('http://127.0.0.1:8765/health', {signal:AbortSignal.timeout(1500)});
    connected = response.ok;
  } catch (_) { /* Desktop app is closed. */ }
  await chrome.action.setBadgeText({text:connected ? 'ON' : 'OFF'});
  await chrome.action.setBadgeBackgroundColor({color:connected ? '#16845b' : '#c43d3d'});
  await chrome.action.setTitle({title:connected ? 'Tori Download connected' : 'Tori Download disconnected'});
}
async function browserFilename(item) {
  if (item.filename) return item.filename;
  try {
    const results = await chrome.downloads.search({id:item.id});
    if (results[0]?.filename) return results[0].filename;
  } catch (_) { /* Filename may not have been assigned yet. */ }
  return await new Promise(resolve => {
    const finish = name => {
      clearTimeout(timer);
      chrome.downloads.onChanged.removeListener(changed);
      resolve(name || '');
    };
    const changed = update => {
      if (update.id === item.id && update.filename?.current) finish(update.filename.current);
    };
    chrome.downloads.onChanged.addListener(changed);
    const timer = setTimeout(async () => {
      try {
        const latest = await chrome.downloads.search({id:item.id});
        finish(latest[0]?.filename);
      } catch (_) { finish(''); }
    }, 1200);
  });
}
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'recover-paused-downloads') {
    recoverHandoffs();
    updateConnectionBadge();
  }
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create('recover-paused-downloads',{periodInMinutes:1});
  recoverHandoffs(true);
  updateConnectionBadge();
});
chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.get(['enabled','toriOnly']).then(({enabled,toriOnly}) => {
    return chrome.storage.local.set({
      ...(enabled === undefined ? {enabled:true} : {}),
      ...(toriOnly === undefined ? {toriOnly:true} : {})
    });
  });
  chrome.contextMenus.create({id:'freja-download',title:'Download with Tori',contexts:['link']});
  chrome.alarms.create('recover-paused-downloads',{periodInMinutes:1});
  recoverHandoffs(true);
  updateConnectionBadge();
});
chrome.contextMenus.onClicked.addListener(async (info) => {
  if (info.menuItemId === 'freja-download' && info.linkUrl) {
    const result = await send(info.linkUrl);
    const {toriOnly=true} = await chrome.storage.local.get({toriOnly:true});
    if (result === 'fallback' && !toriOnly) {
      suppressBrowserFallback(info.linkUrl);
      try { await chrome.downloads.download({url:info.linkUrl}); } catch (_) { /* Link is unavailable. */ }
    }
  }
});
chrome.downloads.onCreated.addListener(async item => {
  const {enabled,toriOnly} = await chrome.storage.local.get({enabled:true,toriOnly:true});
  if (!toriOnly && consumeBrowserFallback(item)) return;
  if (!enabled || !/^https?:\/\//i.test(item.finalUrl || item.url || '')) return;
  if (toriOnly) {
    // onCreated fires after Chrome begins: cancel before contacting the app.
    // A finished browser download must remain visible and must not be offered
    // again, since erasing its history would conceal a second copy on disk.
    try { await chrome.downloads.cancel(item.id); } catch (_) { return; }
    let latest;
    try { [latest] = await chrome.downloads.search({id:item.id}); } catch (_) { return; }
    if (!latest || latest.state === 'complete' || latest.state === 'in_progress') return;
    try { await chrome.downloads.erase({id:item.id}); } catch (_) { /* Best effort. */ }
    await send(item.finalUrl || item.url, true, item.filename || latest.filename || '');
    return;
  }
  await changePending(state => { state[item.id] = Date.now(); });
  try {
    await chrome.downloads.pause(item.id);
  } catch (_) {
    await changePending(state => { delete state[item.id]; });
    return;
  }
  const result = await send(item.finalUrl || item.url, true, await browserFilename(item));
  try {
    if (result === 'accepted' || result === 'declined') {
      await chrome.downloads.cancel(item.id);
      // Chrome already created this download, so remove only its canceled
      // history entry. This does not affect the desktop app's download.
      try { await chrome.downloads.erase({id:item.id}); } catch (_) { /* History cleanup is best effort. */ }
    }
    else await chrome.downloads.resume(item.id);
    await changePending(state => { delete state[item.id]; });
  } catch (_) { /* Recovery alarm will try to resume if it remains paused. */ }
});
