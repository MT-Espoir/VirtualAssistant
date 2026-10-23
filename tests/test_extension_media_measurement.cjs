// Run with node; execute the actual service worker against bounded API fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const messages = [];
const injectedTabs = [];
const listener = { addListener() {}, removeListener() {} };
const tabs = new Map([
  [1, { id: 1, url: 'https://www.youtube.com/watch?v=fixture&secret=hidden', title: 'private title' }],
  [2, { id: 2, url: 'https://www.google.com/private?secret=hidden', audible: true }],
  [3, { id: 3, url: 'https://youtube.com.attacker.example/watch' }],
]);
const video = { paused: true, ended: false, readyState: 4, pause() {this.paused=true;}, play() {this.paused=false;return Promise.resolve();} };
class Socket {
  static OPEN = 1;
  constructor() { this.readyState = 1; }
  send(text) { messages.push(JSON.parse(text)); }
}
const context = vm.createContext({
  crypto: {randomUUID: () => '00000000-0000-4000-8000-000000000001'},
  URL, WebSocket: Socket, console: {log(){},warn(){},error(){}},
  setTimeout(){}, setInterval(){}, clearInterval(){},
  document: {querySelector(selector){return selector==='video'?video:null;}},
  chrome: {
    storage: {local: {
      async setAccessLevel(){},
      async get(){return {aliceBridgeProfileId: '00000000-0000-4000-8000-000000000002'};},
    }},
    tabs: {
      async get(id) {return tabs.get(id);},
      async query() {return [tabs.get(1)];},
      onCreated:listener,onRemoved:listener,onUpdated:listener,
    },
    scripting: {async executeScript({target,func,args=[]}) {
      injectedTabs.push(target.tabId);
      return [{result:func(...args)}];
    }},
    runtime:{onStartup:listener,onInstalled:listener},
    alarms:{create(){},onAlarm:listener},
  },
});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../chrome_extension/background.js'),'utf8'),context);
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  await context.handleCommand({action:'GET_MEDIA_STATE',tabId:1,request_id:'read'});
  const state=messages.pop();
  assert.equal(state.type,'MEDIA_STATE');
  assert.equal(state.paused,true);
  assert.equal(state.isPlaying,false);
  assert.deepEqual(Object.keys(state).sort(),['domain','found','isPlaying','paused','request_id','tabId','type']);
  assert.equal(JSON.stringify(state).includes('hidden'),false);
  assert.equal(JSON.stringify(state).includes('private'),false);
  const before=injectedTabs.length;
  for (const id of [2,3]) {
    await context.handleCommand({action:'GET_MEDIA_STATE',tabId:id,request_id:'blocked'});
    assert.equal(messages.pop().type,'ERROR');
  }
  assert.equal(injectedTabs.length,before);
  await context.handleCommand({action:'CONTROL_MEDIA',mediaAction:'PLAY',tabId:1,request_id:'play'});
  assert.equal(messages.pop().success,true);
  await context.handleCommand({action:'GET_MEDIA_STATE',tabId:1,request_id:'verify'});
  assert.equal(messages.pop().isPlaying,true);
  assert.equal(injectedTabs.at(-1),1);
  console.log('Extension media probe: privacy, exact host checks, explicit targeting and read-after-write passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
