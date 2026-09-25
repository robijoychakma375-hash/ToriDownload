// Intercept obvious direct file links before Chrome creates a download item.
// Unrecognized links keep the browser's ordinary onCreated fallback.
// Wait for the saved preference; a previously chosen OFF must never be
// temporarily treated as ON while this page loads.
let enabled = false;
let toriOnly = true;
chrome.storage.local.get({enabled:true,toriOnly:true}).then(state => {
  enabled = !!state.enabled;
  toriOnly = !!state.toriOnly;
});
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.enabled) enabled = !!changes.enabled.newValue;
  if (area === 'local' && changes.toriOnly) toriOnly = !!changes.toriOnly.newValue;
});

const FILE_PATH = /\.(?:zip|rar|7z|tar|gz|bz2|xz|iso|pdf|exe|msi|msix|apk|dmg|deb|rpm|docx?|xlsx?|pptx?|csv|txt|epub|torrent|mp3|flac|wav|mp4|mkv|avi|mov|webm)(?:$)/i;
const replaying = new WeakSet();

document.addEventListener('click', event => {
  if (!enabled || event.defaultPrevented || !event.isTrusted || event.button !== 0 ||
      event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const anchor = event.target.closest?.('a[href]');
  if (!anchor || replaying.has(anchor)) return;
  const target = (anchor.getAttribute('target') || '').toLowerCase();
  if (target && target !== '_self') return;
  let url;
  try { url = new URL(anchor.href); } catch (_) { return; }
  if (!['http:', 'https:'].includes(url.protocol) ||
      (!anchor.hasAttribute('download') && !FILE_PATH.test(url.pathname))) return;

  event.preventDefault();
  event.stopImmediatePropagation();
  const address = url.href;
  const proposedName = anchor.getAttribute('download') || '';
  function showFailure() {
    const notice = document.createElement('div');
    notice.textContent = 'Tori could not take this download. Open the app or switch off Tori only in the extension.';
    Object.assign(notice.style, {
      position:'fixed',top:'16px',right:'16px',zIndex:'2147483647',
      maxWidth:'340px',padding:'14px 18px',background:'#14252d',color:'#fff',
      border:'2px solid #d34949',borderRadius:'10px',font:'14px system-ui'
    });
    (document.body || document.documentElement).appendChild(notice);
    setTimeout(() => notice.remove(), 7000);
  }
  function browserFallback() {
    if (toriOnly) return showFailure();
    // Suppress this replay in the browser-download event listener. If the app
    // declined the file, Chrome should handle it normally, with page cookies.
    const replay = () => {
      if (!anchor.isConnected) {
        const replacement = document.createElement('a');
        replacement.href = address;
        if (anchor.hasAttribute('download')) replacement.download = proposedName;
        (document.body || document.documentElement).appendChild(replacement);
        replacement.click();
        replacement.remove();
      } else {
        replaying.add(anchor);
        try { anchor.click(); } finally { replaying.delete(anchor); }
      }
    };
    try {
      chrome.runtime.sendMessage({type:'tori-browser-fallback', url:address}, replay);
    } catch (_) { replay(); }
  }
  function ask(message) {
    return new Promise(resolve => {
      try {
        chrome.runtime.sendMessage(message, response => {
          resolve(chrome.runtime.lastError ? null : response);
        });
      } catch (_) { resolve(null); }
    });
  }
  (async () => {
    const started = await ask({type:'tori-preclick', url:address, filename:proposedName});
    if (!started?.id) return browserFallback();
    for (let attempt = 0; attempt < 125; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 950));
      const status = await ask({type:'tori-offer-status', id:started.id});
      if (status?.result === 'accepted' || status?.result === 'declined') return;
      if (status?.result !== 'pending' && status?.result !== 'checking') return browserFallback();
    }
    browserFallback();
  })().catch(browserFallback);
}, true);
