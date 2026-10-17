const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const subjects = ['数学', '英语', '政治', '408'].map(name => ({ name }));
const history = [
  { id:1, subject:'数学', exam_date:'2026-10-01', score:60, target:100 },
  { id:2, subject:'英语', exam_date:'2026-10-02', score:80, target:100 },
  { id:3, subject:'数学', exam_date:'2026-10-03', score:72, target:100 },
  { id:4, subject:'政治', exam_date:'2026-10-03', score:90, target:100 },
  { id:5, subject:'408', exam_date:'2026-10-04', score:85, target:100 },
];

function harness(file) {
  const canvas = { hidden:false, getBoundingClientRect:() => ({ left:50, top:80, width:360, height:144 }) };
  const detail = { hidden:true, innerHTML:'', textContent:'', style:{} }, empty = { hidden:true };
  const nodes = { '#score-chart':canvas, '#score-chart-detail':detail, '#score-chart-empty':empty };
  const document = { documentElement:{dataset:{theme:'light'},classList:{contains:() => false}},
    body:{dataset:{},classList:{}}, querySelector:s => nodes[s] || null,
    querySelectorAll:() => [], addEventListener() {} };
  class Chart {
    static defaults = {font:{}};
    constructor(canvas, config) { Object.assign(this, config); this.canvas=canvas; this.width=600; this.height=240; }
    isPointInArea(e) { return e.x>=0 && e.x<=600 && e.y>=0 && e.y<=240; }
    destroy() { this.destroyed=true; }
    update() { this.updated=true; }
  }
  const window = { Chart, addEventListener() {}, location:{origin:'https://example.test'},
    DashboardDetails:{register() {}}, matchMedia:() => ({matches:false}) };
  const sandbox = vm.createContext({window,document,Chart,console,navigator:{},
    getComputedStyle:() => ({ getPropertyValue:n => n === '--muted' ? '#777777' : '#dddddd' })});
  const source = fs.readFileSync(path.join(__dirname,'..',file),'utf8');
  vm.runInContext(source.replace(/\}\)\(\);\s*$/, 'globalThis.scoreTest={state,renderScoreChart,syncScoreChartTheme,scoreChartPosition};})();'),sandbox);
  const api = sandbox.scoreTest;
  api.state.dashboard = {subjects,focus:{active:null}};
  return {api,canvas,document,detail,empty};
}

for (const file of ['app/static/app.js','android/app/src/main/assets/dashboard/app.js']) {
  test(`${file}: interleaved subjects connect only their valid scores`, () => {
    const {api} = harness(file);
    api.renderScoreChart(history);
    const chart = api.state.scoreChart;
    const math = chart.data.datasets.find(d => d.label === '数学');
    assert.deepEqual(Array.from(math.data),[60,null,72,null]);
    assert.equal(math.spanGaps,true);
    assert.equal(chart.options.interaction.axis,'x');
    assert.equal(chart.data.datasets.find(d => d.label === '英语').data.filter(v => v !== null).length,1);
  });

  test(`${file}: viewport mouse and touch coordinates map through CSS zoom`, () => {
    const {api,canvas} = harness(file);
    api.renderScoreChart(history);
    const chart = api.state.scoreChart, plugin = chart.plugins[0];
    for (const scale of [0.6,0.75,1,1.4]) {
      canvas.getBoundingClientRect = () => ({left:50,top:80,width:600*scale,height:240*scale});
      for (const native of [{clientX:50+300*scale,clientY:80+120*scale},
        {touches:[{clientX:50+300*scale,clientY:80+120*scale}]},
        {changedTouches:[{clientX:50+300*scale,clientY:80+120*scale}]}]) {
        const event={native,x:1,y:2}; plugin.beforeEvent(chart,{event});
        assert.equal(event.x,300); assert.equal(event.y,120);
      }
    }
  });

  test(`${file}: grayscale and shapes stay assigned when the date window or theme changes`, () => {
    const {api,document} = harness(file);
    api.renderScoreChart(history);
    const before = new Map(api.state.scoreChart.data.datasets.map(d => [d.label,d.pointStyle]));
    assert.equal(new Set(before.values()).size,4);
    const light = api.state.scoreChart.data.datasets.map(d => d.borderColor);
    assert.equal(new Set(light).size,4);
    light.forEach(color => assert.match(color,/^#([\da-f]{2})\1\1$/));
    document.documentElement.dataset.theme='dark'; api.syncScoreChartTheme(true);
    api.state.scoreChart.data.datasets.forEach((d,index) => {
      assert.equal(d.pointStyle,before.get(d.label));
      assert.notEqual(d.borderColor,light[index]);
      assert.match(d.borderColor,/^#([\da-f]{2})\1\1$/);
    });
    api.renderScoreChart(history.filter(item => item.subject === '英语'));
    assert.equal(api.state.scoreChart.data.datasets[0].pointStyle,before.get('英语'));
  });

  test(`${file}: invalid data and cleared charts leave no stale tooltip`, () => {
    const {api,detail,empty,canvas} = harness(file);
    api.renderScoreChart([...history,{subject:'数学',exam_date:'2026-10-03',score:'bad',target:100}]);
    assert.equal(api.state.scoreChart.data.datasets[0].data[2],72);
    detail.hidden=false; api.renderScoreChart([]);
    assert.equal(detail.hidden,true); assert.equal(canvas.hidden,true); assert.equal(empty.hidden,false);
    assert.equal(api.state.scoreChart,null);
  });
}
