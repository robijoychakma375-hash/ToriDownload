// One unobtrusive download button near the largest visible HTML5 video.
// The desktop app resolves the page URL when the media src is a blob/stream.
(() => {
  let current = null;
  let hovering = false;
  const button = document.createElement('button');
  button.type = 'button';
  button.title = 'Download video with Tori';
  button.setAttribute('aria-label', 'Download video with Tori');
  button.innerHTML = '<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m-5-5 5 5 5-5M4 17v3h16v-3"/></svg><span style="display:none;white-space:nowrap;font:600 12px Segoe UI,system-ui">Save with Tori</span>';
  Object.assign(button.style, {
    position:'fixed', zIndex:'2147483646', display:'none', alignItems:'center',
    justifyContent:'center', width:'42px', height:'42px', border:'1px solid #5de8c7',
    borderRadius:'11px', background:'#101f2b', color:'#49d2a0', cursor:'pointer', gap:'8px',
    boxShadow:'0 3px 14px #0009', padding:'0'
  });
  function notice(message) {
    const label = document.createElement('div');
    label.textContent = message;
    Object.assign(label.style, {position:'fixed',zIndex:'2147483647',top:'18px',right:'18px',
      maxWidth:'320px',padding:'12px 15px',background:'#14252d',color:'#fff',
      border:'1px solid #49bcff',borderRadius:'9px',font:'13px system-ui'});
    (document.body || document.documentElement).appendChild(label);
    setTimeout(() => label.remove(), 6000);
  }
  function position() {
    if (!document.documentElement || !button.isConnected) return;
    let best = null, area = 0;
    for (const video of document.querySelectorAll('video')) {
      const rect = video.getBoundingClientRect();
      const width = Math.min(rect.right, innerWidth) - Math.max(rect.left, 0);
      const height = Math.min(rect.bottom, innerHeight) - Math.max(rect.top, 0);
      if (width > 180 && height > 100 && width*height > area) {
        best = {video,rect}; area = width*height;
      }
    }
    current = best?.video || null;
    button.style.display = current ? 'flex' : 'none';
    if (best) {
      button.style.left = `${Math.max(6,Math.min(innerWidth-(hovering ? 132 : 48),best.rect.right-(hovering ? 137 : 53)))}px`;
      button.style.top = `${Math.max(6,Math.min(innerHeight-48,best.rect.top+12))}px`;
    }
  }
  button.addEventListener('mouseenter', () => {
    hovering = true;
    button.style.width = '126px';
    button.querySelector('span').style.display = 'inline';
    position();
  });
  button.addEventListener('mouseleave', () => {
    hovering = false;
    button.style.width = '42px';
    button.querySelector('span').style.display = 'none';
    position();
  });
  button.addEventListener('click', async event => {
    event.preventDefault(); event.stopPropagation();
    if (!current) return;
    let media = current.currentSrc || current.src;
    // Manifest/segment URLs belong to the player, not a stand-alone file.
    if (/(^|\.)(youtube\.com|youtu\.be|facebook\.com|fb\.watch)$/i.test(location.hostname) ||
        !/^https?:\/\//i.test(media || '') || /\.(?:m3u8|mpd)(?:[?#]|$)/i.test(media))
      media = location.href;
    if (!/^https?:\/\//i.test(media)) return notice('This video is not available from this page.');
    let title = (document.title || 'Video').replace(/[<>:"/\\|?*\x00-\x1f]/g,'_').trim().slice(0,100);
    const filename = (title || 'Video') + '.mp4';
    button.disabled = true;
    try {
      const response = await chrome.runtime.sendMessage({type:'tori-video',url:media,filename});
      if (!response?.id) return notice('Open Tori Download and try again.');
      notice('Choose a folder in the Tori confirmation window.');
    } catch (_) { notice('Tori is not connected.'); }
    finally { button.disabled = false; }
  });
  function mount() {
    if (!button.isConnected) (document.body || document.documentElement).appendChild(button);
    position();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once:true});
  else mount();
  setInterval(position, 1800);
  addEventListener('scroll', position, {passive:true});
  addEventListener('resize', position);
})();
