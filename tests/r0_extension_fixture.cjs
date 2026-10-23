// Execute the actual service worker with in-memory Chrome/WebSocket APIs.
// Input/output are synthetic fixture data; never emit the source's token.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const tabs = new Map((input.tabs || []).map(tab => [tab.id, tab]));
const failIds = new Set(input.failRemoveIds || []);
const retainIds = new Set(input.retainRemoveIds || []);
const messages = [], sockets = [], attempted = [], removed = [];
let now = 0, tokenSequence = 0, queryCount = 0;
let currentStep = {};
const storageData = {...(input.profileStorage || {})};
const storageCalls = [];
function event() {
  const callbacks = [];
  return {addListener(fn) {callbacks.push(fn);}, removeListener() {},
    emit(...args) {callbacks.forEach(fn => fn(...args));}};
}
const listener = {addListener() {}, removeListener() {}};
const updated = event(), removedEvent = event(), attached = event(), detached = event();
const replaced = event();
class Socket {
  static OPEN = 1;
  constructor() {this.readyState = 1; sockets.push(this);}
  send(raw) {messages.push(JSON.parse(raw));}
}
const context = vm.createContext({
  URL, WebSocket: Socket, performance: {now: () => now},
  crypto: {randomUUID: () => `00000000-0000-4000-8000-${String(++tokenSequence).padStart(12, '0')}`},
  console: {log(){}, warn(){}, error(){}},
  setTimeout(){}, setInterval(){}, clearInterval(){},
  chrome: {
    storage: {local: {
      async setAccessLevel(value) {
        storageCalls.push({operation: 'access', value});
        if (input.storageFailure === 'access') throw new Error('fixture_storage_failed');
      },
      async get(key) {
        storageCalls.push({operation: 'get', key});
        if (input.storageFailure === 'get') throw new Error('fixture_storage_failed');
        if (input.storageFailure === 'readback' && storageCalls.some(c => c.operation === 'set')) return {};
        return {[key]: storageData[key]};
      },
      async set(value) {
        storageCalls.push({operation: 'set', value});
        if (input.storageFailure === 'set') throw new Error('fixture_storage_failed');
        Object.assign(storageData, value);
      },
    }},
    tabs: {
      async query(options) {
        if (options.url) return [];
        queryCount++;
        if ((currentStep.failQueryCalls || []).includes(queryCount)) throw new Error('fixture_read_failed');
        return [...tabs.values()].map(t => ({...t}));
      },
      async get(id) {
        const tab = tabs.get(id);
        if (!tab) throw new Error('fixture_tab_missing');
        if (currentStep.changeOnGet?.id === id) {
          Object.assign(tab, currentStep.changeOnGet.patch);
          updated.emit(id, currentStep.changeOnGet.patch);
        }
        return {...tab};
      },
      async remove(id) {
        attempted.push(id);
        if (failIds.has(id)) throw new Error('fixture_remove_rejected');
        if (!retainIds.has(id)) {tabs.delete(id); removedEvent.emit(id);}
        removed.push(id);
        if (currentStep.changeAfterRemove?.afterId === id) {
          const change = currentStep.changeAfterRemove;
          Object.assign(tabs.get(change.id), change.patch);
          updated.emit(change.id, change.patch);
        }
      },
      onCreated: listener, onRemoved: removedEvent, onUpdated: updated,
      onAttached: attached, onDetached: detached,
      onReplaced: replaced,
    },
    runtime: {onStartup: listener, onInstalled: listener},
    alarms: {create(){}, onAlarm: listener},
  },
});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome_extension/background.js'), 'utf8'), context);
(async () => {
  await new Promise(resolve => setImmediate(resolve)); // await worker's async storage startup
  if (input.mode === 'hello' || input.mode === 'identity') {
    sockets[0]?.onopen();
    const hello = messages.find(msg => msg.type === 'HELLO');
    // Keys only. Authentication material remains inside the fixture VM.
    if (input.mode === 'hello') {
      process.stdout.write(JSON.stringify({helloKeys: Object.keys(hello || {}).sort()}));
      return;
    }
    const identity = value => value ? {profileId: value.profileId, sessionId: value.sessionId,
      protocolVersion: value.protocolVersion} : null;
    const first = identity(hello);
    if (sockets.length) {
      if (input.restartWorker) {
        const restarted = vm.createContext({URL, WebSocket: Socket, chrome: context.chrome,
          performance: context.performance, crypto: context.crypto, console: context.console,
          setTimeout(){}, setInterval(){}, clearInterval(){}});
        vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome_extension/background.js'), 'utf8'), restarted);
        await new Promise(resolve => setImmediate(resolve));
      } else await context.connect();
      sockets.at(-1).onopen();
    }
    await new Promise(resolve => setImmediate(resolve));
    const beforeStale = messages.length;
    if (input.staleCallbacks && sockets.length > 1) {
      sockets[0].onopen();
      sockets[0].onmessage({data: JSON.stringify({action: 'GET_TABS', request_id: 'stale'})});
      sockets[0].onclose();
      await new Promise(resolve => setImmediate(resolve));
    }
    process.stdout.write(JSON.stringify({connected: sockets.length > 0, first,
      second: identity(messages.filter(msg => msg.type === 'HELLO').at(-1)),
      storageData, storageCalls, socketCount: sockets.length, staleMessagesAdded: messages.length - beforeStale}));
    return;
  }
  const responses = [];
  for (const [index, item] of (input.commands || []).entries()) {
    currentStep = item.command ? item : {command: item};
    now += currentStep.advanceMs || 0;
    if (currentStep.tabs) {
      const incoming = new Map(currentStep.tabs.map(t => [t.id, t]));
      for (const [id, old] of tabs) {
        if (!incoming.has(id)) {removedEvent.emit(id); continue;}
        const fresh = incoming.get(id);
        if (JSON.stringify(old) !== JSON.stringify(fresh)) updated.emit(id, {status: 'complete'});
      }
      tabs.clear(); for (const [id, tab] of incoming) tabs.set(id, {...tab});
    }
    for (const eventInfo of currentStep.events || []) {
      if (eventInfo.kind === 'attached') attached.emit(eventInfo.id);
      else if (eventInfo.kind === 'detached') detached.emit(eventInfo.id);
      else if (eventInfo.kind === 'replaced') replaced.emit(eventInfo.addedId, eventInfo.id);
      else updated.emit(eventInfo.id, eventInfo.changeInfo);
    }
    if (currentStep.reconnect) await context.connect();
    if (currentStep.reopen) sockets.at(-1).onopen();
    let command = currentStep.command;
    if (currentStep.previewFrom !== undefined) {
      const preview = responses[currentStep.previewFrom];
      command = {previewToken: preview.previewToken, tabIds: preview.tabIds, ...command};
    }
    const rid = `r0-fixture-${index}`;
    if (currentStep.concurrentCopies) {
      const rids = Array.from({length: currentStep.concurrentCopies}, (_, i) => `${rid}-${i}`);
      await Promise.all(rids.map(request_id => context.handleCommand({...command, request_id})));
      responses.push(rids.map(id => messages.find(msg => msg.request_id === id)));
    } else {
      await context.handleCommand({...command, request_id: rid});
      responses.push(messages.find(msg => msg.request_id === rid));
    }
  }
  process.stdout.write(JSON.stringify({responses, attemptedRemoveIds: attempted,
    successfulRemoveIds: removed, remainingTabs: [...tabs.values()]}));
})().catch(error => {console.error(error.name); process.exitCode = 1;});
