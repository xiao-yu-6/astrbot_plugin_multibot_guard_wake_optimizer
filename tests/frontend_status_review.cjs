const fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert/strict');
const nodes = {};
for (const id of ['render', 'notice', 'save', 'reload', 'status-panel']) {
  nodes[id] = {innerHTML: '', textContent: '', className: '', listeners: {},
    addEventListener(kind, callback) { this.listeners[kind] = callback; }};
}
const stored = {robot_setup: {enabled: true, instances: [{platform_id: 'bot-a', bot_name: 'A'}], groups: [], group_sessions: []},
  guard_options: {}, semantic_options: {semantic_mode: 'regex_only'}};
const status = {enabled: true, instances: 1, groups: 0, sessions: 0, roster_entries: 0, semantic_mode: 'regex_only', archive: {}};
let statusReads = 0, configReads = 0, failure = false, deferred = null, interval, cleared = false;
const listeners = {};
const bridge = {ready: async () => {}, apiGet: async key => {
  if (key === 'models/list') return {providers: []};
  if (key === 'status/get') {
    statusReads++;
    if (failure) throw Error('Unavailable');
    if (deferred) await deferred;
    return structuredClone(status);
  }
  configReads++;
  return structuredClone(stored);
}};
const window = {AstrBotPluginView: bridge, addEventListener(kind, cb) {(listeners[kind] ||= []).push(cb);}, confirm: () => true};
const source = fs.readFileSync(path.join(__dirname, '../views/settings/app.js'), 'utf8');
(async () => {
  const api = await vm.runInNewContext('(async()=>{' + source + '\nreturn {refresh:fetchRuntimeStatus, draft:()=>JSON.stringify(cfg), dirty:()=>dirty};})()', {
    window, document: {getElementById: id => nodes[id]}, console,
    setInterval(cb, delay) {assert.equal(delay, 15000); interval = cb; return 1;},
    clearInterval(id) {assert.equal(id, 1); cleared = true;}
  });
  nodes.render.listeners.change({target: {dataset: {bind: 'robot_setup.instances.0.bot_name'}, value: 'Unsaved name', type: 'text'}});
  assert(api.dirty());
  const draft = api.draft(), form = nodes.render.innerHTML, reads = configReads;
  await api.refresh();
  assert.equal(api.draft(), draft);
  assert.equal(nodes.render.innerHTML, form);
  assert.equal(configReads, reads);
  assert(api.dirty());
  failure = true;
  await api.refresh();
  assert(nodes['status-panel'].innerHTML.includes('实时状态暂不可用'));
  assert.equal(api.draft(), draft);
  assert.equal(nodes.render.innerHTML, form);
  failure = false;
  let release;
  deferred = new Promise(resolve => {release = resolve;});
  const before = statusReads, pending = api.refresh();
  interval();
  await api.refresh();
  assert.equal(statusReads - before, 1, 'Concurrent refreshes must coalesce');
  release();
  await pending;
  assert.equal(api.draft(), draft);
  listeners.beforeunload.at(-1)();
  assert(cleared);
  console.log('FRONTEND STATUS REVIEW PASS: unsaved draft, failure isolation, request coalescing, timer cleanup');
})().catch(error => {console.error(error); process.exitCode = 1;});
