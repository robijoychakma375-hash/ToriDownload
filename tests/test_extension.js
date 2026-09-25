const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function scenario(result, enabledValue = true, toriOnly = true) {
  let onCreated, onStartup, onMessage, onContextClick;
  const calls = [];
  let badge;
  const state = {pendingHandoffs:{},toriOnly};
  if (enabledValue !== null) state.enabled = enabledValue;
  const chrome = {
    storage:{local:{
      async get(defaults){return {...(typeof defaults === 'object' ? defaults : {}),...state}},
      async set(values){Object.assign(state,values)}
    }},
    downloads:{
      onCreated:{addListener(fn){onCreated=fn}},
      async pause(id){calls.push(['pause',id])},
      async download(options){calls.push(['browser-download',options.url]);return 10},
      async cancel(id){calls.push(['cancel',id])},
      async erase(query){calls.push(['erase',query.id])},
      async resume(id){calls.push(['resume',id])},
      async search(){return [{filename:'test.zip',state:'interrupted'}]}
    },
    runtime:{id:'fabmofikglnnbbobdhfcnlcneebfffhn',onMessage:{addListener(fn){onMessage=fn}},
      onInstalled:{addListener(){}},onStartup:{addListener(fn){onStartup=fn}}},
    contextMenus:{onClicked:{addListener(fn){onContextClick=fn}},create(){}},
    alarms:{onAlarm:{addListener(){}},create(){}},
    action:{async setBadgeText(value){badge=value.text},async setBadgeBackgroundColor(){},async setTitle(){}}
  };
  const fetch = async url => {
    if (url.endsWith('/health')) return {ok:true};
    if (url.endsWith('/offer')) return {ok:true,json:async()=>({id:'offer-ticket-1234'})};
    if (url.includes('/offer/')) return {ok:true,json:async()=>({result})};
    throw new Error('Unexpected URL: '+url);
  };
  vm.runInNewContext(fs.readFileSync('extension/background.js','utf8'),{
    chrome, Date, JSON, RegExp, setTimeout, fetch,
    AbortSignal:{timeout(){return undefined}}
  });
  await onCreated({id:7,url:'https://example.org/test.zip'});
  const expected = enabledValue === false ? [] : toriOnly
    ? [['cancel',7],['erase',7]] : result === 'fallback'
      ? [['pause',7],['resume',7]] : [['pause',7],['cancel',7],['erase',7]];
  assert.deepEqual(calls,expected);
  assert.deepEqual(state.pendingHandoffs,{});
  const sender = {tab:{id:1},url:'https://example.org/page'};
  let messageResult;
  assert.equal(onMessage({type:'tori-preclick',url:'https://example.org/file.zip'},sender,
    value => {messageResult=value}),true);
  for (let i=0;i<20 && !messageResult;i++) await new Promise(r=>setTimeout(r,60));
  assert.equal(!!messageResult.id,enabledValue !== false);
  let videoResult;
  assert.equal(onMessage({type:'tori-video',url:'https://example.org/watch?v=1',filename:'Sample.mp4'},sender,
    value => {videoResult=value}),true);
  for (let i=0;i<20 && !videoResult;i++) await new Promise(r=>setTimeout(r,0));
  assert.ok(videoResult.id,'video button should create a desktop confirmation');
  if (messageResult.id) {
    let polled;
    onMessage({type:'tori-offer-status',id:messageResult.id},sender,value => {polled=value});
    for (let i=0;i<20 && !polled;i++) await new Promise(r=>setTimeout(r,0));
    assert.equal(polled.result,result);
  }
  onMessage({type:'tori-browser-fallback',url:'https://example.org/file.zip'},sender,()=>{});
  const before = calls.length;
  await onCreated({id:9,url:'https://example.org/file.zip'});
  assert.equal(calls.length,before+(enabledValue !== false && toriOnly ? 2 : 0),
    'Tori only must intercept stale fallback markers; normal browser fallback must stay available');
  if (enabledValue !== false) {
    let retry;
    onMessage({type:'tori-preclick',url:'https://example.org/file.zip'},sender,value=>{retry=value});
    for (let i=0;i<20 && !retry;i++) await new Promise(r=>setTimeout(r,0));
    const beforeRetry = calls.length;
    await onCreated({id:11,url:'https://example.org/file.zip'});
    assert.ok(calls.length > beforeRetry,'a new click must clear the stale fallback for the same URL');
  }
  state.pendingHandoffs = {'8':Date.now()-180000};
  onStartup();
  for (let i=0;i<10 && state.pendingHandoffs['8'];i++) await new Promise(r=>setTimeout(r,0));
  assert.deepEqual(calls.at(-1),toriOnly ? ['erase',8] : ['resume',8]);
  assert.deepEqual(state.pendingHandoffs,{});
  assert.equal(badge,'ON');
  await onContextClick({menuItemId:'freja-download',linkUrl:'https://example.org/from-menu.zip'});
  assert.equal(calls.some(call=>call[0] === 'browser-download'),result === 'fallback' && !toriOnly);
}

async function preclickScenario(result, enabledValue = true, toriOnly = true) {
  const url = 'https://files.example.org/report.zip';
  let listener, prevented = false, replayCount = 0, offerCount = 0, noticeCount = 0;
  const anchor = {
    href:url, isConnected:true,
    getAttribute(name){return name === 'target' ? '' : name === 'download' ? 'report.zip' : null},
    hasAttribute(name){return name === 'download'},
    click(){replayCount++}
  };
  const chrome = {
    storage:{local:{get:async defaults=>({...defaults,...(enabledValue === null ? {} : {enabled:enabledValue}),toriOnly})},onChanged:{addListener(){}}},
    runtime:{sendMessage(message,callback){
      if (message.type === 'tori-preclick') { offerCount++; callback({id:'ticket-1234567890'}); }
      else if (message.type === 'tori-offer-status') callback({result:offerCount > 1 ? 'accepted' : result});
      else callback({ok:true});
    },lastError:null}
  };
  const document = {addEventListener(type,callback){listener=callback},
    createElement(){return {style:{},remove(){}}},body:{appendChild(){noticeCount++}}};
  vm.runInNewContext(fs.readFileSync('extension/preclick.js','utf8'), {
    chrome,document,URL,WeakSet,setTimeout:callback=>setTimeout(callback,0)
  });
  await new Promise(r=>setTimeout(r,0));
  listener({target:{closest:()=>anchor},isTrusted:true,button:0,defaultPrevented:false,
    preventDefault(){prevented=true},stopImmediatePropagation(){}});
  for (let i=0;i<10 && offerCount && result === 'fallback' && !replayCount;i++)
    await new Promise(r=>setTimeout(r,0));
  assert.equal(prevented,enabledValue !== false);
  assert.equal(replayCount,enabledValue === false || result !== 'fallback' || toriOnly ? 0 : 1);
  assert.equal(noticeCount,enabledValue !== false && result === 'fallback' && toriOnly ? 1 : 0);
  if (result === 'declined' && enabledValue !== false) {
    listener({target:{closest:()=>anchor},isTrusted:true,button:0,defaultPrevented:false,
      preventDefault(){},stopImmediatePropagation(){}});
    await new Promise(r=>setTimeout(r,10));
    assert.equal(offerCount,2,'Cancel must let the same link ask Tori again and accept it');
    assert.equal(replayCount,0);
  }
}

async function videoOverlayScenario(media, host, expected) {
  let click, sent;
  const video = {currentSrc:media,getBoundingClientRect:()=>({left:10,top:20,right:510,bottom:320})};
  const document = {
    readyState:'complete', documentElement:{appendChild(node){node.isConnected=true}},
    body:{appendChild(node){node.isConnected=true}},
    createElement(){return {style:{},isConnected:false,setAttribute(){},
      addEventListener(type,listener){if(type==='click')click=listener}}},
    querySelectorAll(){return [video]},
  };
  const chrome = {runtime:{async sendMessage(message){sent=message;return {id:'offer-ticket-1234'}}}};
  vm.runInNewContext(fs.readFileSync('extension/video_overlay.js','utf8'),{
    chrome,document,location:{hostname:host,href:`https://${host}/watch?id=4`},
    innerWidth:1000,innerHeight:700,setInterval(){},setTimeout(){},addEventListener(){}
  });
  assert.ok(click,'video button should be mounted');
  await click({preventDefault(){},stopPropagation(){}});
  assert.equal(sent.type,'tori-video');
  assert.equal(sent.url,expected);
}

Promise.all([
  scenario('accepted'), scenario('declined'), scenario('fallback'), scenario('accepted',null), scenario('accepted',false),scenario('fallback',true,false),
  preclickScenario('accepted'), preclickScenario('declined'), preclickScenario('fallback'), preclickScenario('fallback',true,false), preclickScenario('accepted',false),
  videoOverlayScenario('blob:https://youtube.com/stream','www.youtube.com','https://www.youtube.com/watch?id=4'),
  videoOverlayScenario('https://files.example.org/movie.mp4','example.org','https://files.example.org/movie.mp4')
]).then(()=>console.log('Browser confirmation and fallback tests passed'))
  .catch(error=>{console.error(error);process.exitCode=1});
