const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const icons=fs.readFileSync('app/static/status-icons.js','utf8');
function context(){
  const root={classList:{contains:()=>true},dataset:{viewportMode:'portrait'}};
  const document={documentElement:root,addEventListener(){},querySelector(){return null;}};
  const window={addEventListener(){},DashboardController:{getData:()=>({})}};
  const ctx=vm.createContext({window,document});vm.runInContext(icons,ctx);return {ctx,window};
}
test('completion icons share a theme-colored fixed canvas without font glyphs',()=>{
  const {window}=context();
  for(const completed of [true,false]){
    const svg=window.StatusIcons.completion(completed);
    assert.match(svg,/viewBox="0 0 24 24"/);assert.match(svg,/stroke="currentColor"/);
    assert.match(svg,/width="16" height="16"/);assert.match(svg,/aria-hidden="true"/);
    assert.doesNotMatch(svg,/[✓✔√]/);
  }
  assert.equal(fs.readFileSync('android/app/src/main/assets/dashboard/status-icons.js','utf8'),icons);
});
test('a successful checkin slider renders the shared vector and preserves its accessible state',()=>{
  const {ctx,window}=context();
  const source=fs.readFileSync('app/static/focus-entry.js','utf8').replace(/\}\)\(\);\s*$/,'window.paintRuleForTest=paintRule;})();');
  vm.runInContext(source,ctx);
  const label={},thumb={setAttribute(name,value){this[name]=value;}},attrs={};
  const track={dataset:{},querySelector:s=>s==='.drag-thumb'?thumb:label,setAttribute(name,value){attrs[name]=value;}};
  window.paintRuleForTest(track,{id:1,name:'拉伸',completed_at:'2026-10-24T12:00:00Z'});
  assert.equal(thumb.innerHTML,window.StatusIcons.completion());assert.equal(thumb['aria-label'],'拉伸已完成');assert.equal(attrs['aria-disabled'],'true');
});
test('plan and checkin settlement marks reuse the same vector with accessible labels',()=>{
  const {ctx,window}=context();vm.runInContext(fs.readFileSync('android/app/src/main/assets/dashboard/app-pages.js','utf8'),ctx);
  const html=window.AppPages.dailyReportHtml({date:'2026-10-24',total_seconds:0,daily_tasks:{total:1,completed:1,tasks:[{title:'数学',completed:true,focus_seconds:0}]},checkins:{total:1,completed:1,items:[{name:'拉伸',completed:true}]}});
  assert.equal((html.match(/class="completion-icon"/g)||[]).length,2);
  assert.match(html,/aria-label="已完成"/);assert.doesNotMatch(html,/[✓✔√]/);
});
