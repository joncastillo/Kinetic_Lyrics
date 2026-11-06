const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('src/frontend/studio-models.js', 'utf8');
const functions = source.slice(source.indexOf('function pipelineHistoryBusy('), source.indexOf('const PIPELINE_STEPS='));
class Element {
  constructor(tag, text = '') { this.tag = tag; this.textContent = text; this.children = []; this.disabled = false; }
  append(...children) { this.children.push(...children); }
  add(child) { this.append(child); }
  replaceChildren() { this.children = []; }
  contains(target) { return this.children.includes(target); }
  setAttribute(name, value) { this[name] = value; }
  toggleAttribute(name, on) { this[name] = on; }
}
const host = new Element('div');
const calls = [], selected = [];
const context = vm.createContext({
  jobId: 'song', busy: false, uploading: false, document: {activeElement: null},
  $: () => host, node: (tag, cls, text) => new Element(tag, text),
  Option: function(text, value) { return Object.assign(new Element('option', text), {value}); },
  api: async (...args) => calls.push(args), setJob: id => selected.push(id), poll() {},
  toast: message => { throw Error(message); },
});
vm.runInContext(functions, context);
(async () => {
  context.renderPipelineHistory({status: 'complete', pipeline_history: {active: 2, sequences: [
    {id: 1, reason: 'Original'}, {id: 2, reason: 'Selected timing v1'},
  ]}});
  const select = host.children[0].children[0];
  assert.equal(select['aria-label'], 'Saved pipeline version');
  assert.equal(select.children[0].selected, true);
  await context.selectPipelineVersion({node: 'timing', version: 1});
  assert.equal(calls[0][0], '/api/jobs/song/pipeline-version');
  assert.deepEqual(calls[0][1], {node: 'timing', version: 1});
  assert.deepEqual(selected, ['song']);
  assert.equal(context.pipelineHistoryBusy({status: 'review'}), true);
  assert.equal(context.pipelineHistoryBusy({status: 'complete', queued_actions: [{action: 'patch'}]}), true);
  assert.equal(context.pipelineHistoryBusy({status: 'complete'}), false);
  context.uploading = true;
  assert.equal(context.pipelineHistoryBusy({status: 'complete'}), true);
  console.log('Pipeline version controls passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
