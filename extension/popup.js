const button = document.getElementById('capture');
const onlyButton = document.getElementById('tori-only');
const connection = document.getElementById('connection');
const status = document.getElementById('status');
function showToggle(enabled) {
  button.querySelector('span').textContent = `Auto capture: ${enabled ? 'ON' : 'OFF'}`;
  button.classList.toggle('on', enabled);
  button.setAttribute('aria-pressed', String(enabled));
}
chrome.storage.local.get({enabled:true}, state => showToggle(state.enabled));
function showOnly(enabled) {
  onlyButton.querySelector('span').textContent = `Tori only: ${enabled ? 'ON' : 'OFF'}`;
  onlyButton.classList.toggle('on', enabled);
  onlyButton.setAttribute('aria-pressed', String(enabled));
}
chrome.storage.local.get({toriOnly:true}, state => showOnly(state.toriOnly));
onlyButton.addEventListener('click', async () => {
  const {toriOnly} = await chrome.storage.local.get({toriOnly:true});
  await chrome.storage.local.set({toriOnly:!toriOnly});
  showOnly(!toriOnly);
});
button.addEventListener('click', async () => {
  const {enabled} = await chrome.storage.local.get({enabled:true});
  await chrome.storage.local.set({enabled:!enabled});
  showToggle(!enabled);
});
async function checkConnection() {
  let connected = false;
  try {
    const response = await fetch('http://127.0.0.1:8765/health', {signal:AbortSignal.timeout(1500)});
    connected = response.ok;
  } catch (_) { /* App is closed. */ }
  connection.classList.toggle('connected', connected);
  connection.classList.toggle('disconnected', !connected);
  status.textContent = connected ? 'Connected to desktop app' : 'Disconnected — open Tori app';
  await chrome.action.setBadgeText({text:connected ? 'ON':'OFF'});
  await chrome.action.setBadgeBackgroundColor({color:connected ? '#16845b':'#c43d3d'});
  await chrome.action.setTitle({title:connected ? 'Tori Download connected':'Tori Download disconnected'});
}
checkConnection();
setInterval(checkConnection, 4000);
