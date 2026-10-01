const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.attributes = new Map(); this.style = {};
    this.dataset = {}; this.hidden = false; this.textContent = ''; this.clientWidth = 600;
    this.clientHeight = 220; this.isConnected = true; this.listeners = new Map();
    const classes = new Set();
    this.classList = { add: (...names) => names.forEach(name => classes.add(name)), remove: (...names) => names.forEach(name => classes.delete(name)), contains: name => classes.has(name), toggle(name, force) { const next = force ?? !classes.has(name); next ? classes.add(name) : classes.delete(name); return next; } };
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  append(...children) { children.forEach(child => { child.parent = this; this.children.push(child); }); }
  replaceChildren(...children) { this.children = []; this.append(...children); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); this.isConnected = false; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return { classList:this.classList }; }
  getClientRects() { return [1]; }
  getBoundingClientRect() { return { left:0, top:0, width:this.clientWidth, height:this.clientHeight }; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  removeEventListener(name) { this.listeners.delete(name); }
}

function harness({ now = '2026-09-30T09:01:00+08:00', fetch } = {}) {
  const nodes = new Map(), intervals = [], listeners = new Map(), windowListeners = new Map(), charts = [];
  const clock = { now:Date.parse(now) };
  class ClockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock.now])); }
    static now() { return clock.now; }
    getHours() { return this.getUTCHours(); } getMinutes() { return this.getUTCMinutes(); } getSeconds() { return this.getUTCSeconds(); }
    getTimezoneOffset() { return 0; }
    toLocaleTimeString(locale, options = {}) { return super.toLocaleTimeString(locale, { timeZone:'UTC', ...options }); }
    toLocaleDateString(locale, options = {}) { return super.toLocaleDateString(locale, { timeZone:'UTC', ...options }); }
  }
  const get = selector => { if (!nodes.has(selector)) nodes.set(selector, new Element()); return nodes.get(selector); };
  const view = get('#activity-index-view'); view.querySelector = get;
  const document = {
    hidden:false, documentElement:new Element(), body:{ dataset:{ page:'focus-kline' } },
    getElementById:id => id === 'activity-index-view' ? view : null,
    querySelector:get, querySelectorAll:() => [],
    createElement:tag => new Element(tag), createElementNS:(_ns, tag) => new Element(tag),
    addEventListener(name, callback) { listeners.set(name, callback); }, removeEventListener(name) { listeners.delete(name); },
    dispatchEvent(event) { listeners.get(event.type)?.(event); },
  };
  const library = {
    LineSeries:{}, CandlestickSeries:{}, ColorType:{ Solid:0 }, LineStyle:{ Dashed:2, Dotted:1 },
    createChart() { throw new Error('Intraday must use proportional wall-clock geometry, not business indexes'); },
  };
  const window = {
    LightweightCharts:library, DashboardDetails:{ register() {} }, ResizeObserver:class {},
    location:{ href:'https://dashboard.test/focus-kline' }, history:{ replaceState() {} },
    setInterval(fn, delay) { const id = intervals.length + 1; intervals.push({ fn, delay, id }); return id; }, clearInterval() {},
    setTimeout() { return 1; }, clearTimeout() {}, requestAnimationFrame:fn => { fn(); return 1; },
    addEventListener(name, callback) { windowListeners.set(name, callback); }, removeEventListener(name) { windowListeners.delete(name); },
  };
  const context = vm.createContext({
    Date:ClockDate, Intl, document, window, URL, AbortController, console,
    CustomEvent:class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
    fetch:fetch || (async () => { throw new Error('Unexpected network request'); }),
    getComputedStyle:() => ({ fontFamily:'Arial', getPropertyValue:() => '' }),
    ResizeObserver:class { observe() {} disconnect() {} }, MutationObserver:class { observe() {} disconnect() {} },
    requestAnimationFrame:window.requestAnimationFrame, cancelAnimationFrame() {},
    setInterval:window.setInterval, clearInterval:window.clearInterval,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/static/index-market.js'), 'utf8'), context, { filename:'index-market.js' });
  const create = window.IndexMarket.createChart;
  window.IndexMarket.createChart = (...args) => { const chart = create(...args); charts.push(chart); return chart; };
  return { context, document, window, clock, nodes, get, intervals, listeners, windowListeners, charts, Market:window.IndexMarket };
}

const sessions = [
  { name:'am', start:'2026-09-30T08:15:17+08:00', end:'2026-09-30T12:00:23+08:00' },
  { name:'pm', start:'2026-09-30T13:45:11+08:00', end:'2026-09-30T20:30:49+08:00' },
];
module.exports = { harness, Element, sessions };
