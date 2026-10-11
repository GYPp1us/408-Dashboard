/* Local APK WebView asset checks. Native bridge is simulated; ROM rendering is
   deliberately left to the release APK's owner. Run android_v07_fixture.py first. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = 'http://127.0.0.1:43130';
const output = path.resolve(process.env.MUTSUMI_UI_VALIDATION_OUTPUT || '.tmp/v07');
fs.mkdirSync(output, { recursive: true });

async function nativeBridge() {
  if (location.origin !== 'http://127.0.0.1:43130') return;
  let runtime = JSON.parse(localStorage.getItem('v07-native-fixture') || '{"mode":"idle","revision":0}');
  const clock = seconds => [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, Math.floor(seconds) % 60].map(n => String(Math.max(0, n)).padStart(2, '0')).join(':');
  const persist = () => localStorage.setItem('v07-native-fixture', JSON.stringify(runtime));
  const update = payload => {
    const identity = p => `${p.mode}:${p.sessionId}:${p.pausedAtEpochMs}:${p.restStartedAtEpochMs}`;
    const same = identity(runtime) === identity(payload);
    const revision = runtime.revision + (same ? 0 : 1);
    runtime = { ...(same ? runtime : {}), ...payload, revision, observedAt:Date.now() }; persist();
  };
  const view = () => {
    const now = Date.now(), state = { ...runtime };
    state.elapsedSeconds = Number(state.elapsedSeconds || 0) + (state.mode === 'focusing' ? Math.floor((now - state.observedAt) / 1000) : 0);
    state.nextReminderAt = state.snooze || (state.mode === 'paused' ? state.pausedAtEpochMs + 300000 : 0);
    state.reminder = state.mode === 'paused' && !state.dismissed && now >= state.nextReminderAt ? 'PAUSED' : '';
    state.reminderToken = state.reminder ? `fixture:${state.sessionId}:${state.nextReminderAt}` : '';
    state.title = ({focusing:'专注中', paused:state.reminder ? '暂停超时' : '专注已暂停', rest:'主动休息', ended:'本段专注已结束', settled:'今日已结算', idle:'准备开始专注'})[state.mode];
    const restElapsed = Math.max(0, Math.floor((now - (state.restStartedAtEpochMs || now)) / 1000));
    state.timer = clock(state.mode === 'rest' ? state.restTargetSeconds > 0 ? Math.max(0, state.restTargetSeconds - restElapsed) : restElapsed : state.elapsedSeconds);
    state.detail = state.mode === 'paused' ? `有效 ${state.timer} · 暂停 ${clock((now-state.pausedAtEpochMs)/1000)} · ${state.reminder ? '暂停超时' : '下次提醒 ' + clock((state.nextReminderAt-now)/1000) + ' 后'}`
      : state.mode === 'rest' ? `休息${state.restTargetSeconds > 0 ? '剩余' : '时长'} ${state.timer} · 不催促专注` : `有效专注 ${state.timer}`;
    return state;
  };
  const fromServer = session => ({mode:session.ended_at ? 'ended' : session.paused_at ? 'paused' : 'focusing',
    sessionId:session.id, subject:session.subject, elapsedSeconds:session.effective_seconds,
    startedAtEpochMs:Date.parse(session.started_at), pausedAtEpochMs:Date.parse(session.paused_at) || 0,
    endedAtEpochMs:Date.parse(session.ended_at) || 0, plannedSeconds:session.planned_minutes * 60,
    focusItemId:session.focus_item_id, restStartedAtEpochMs:0});
  window.__setNative = payload => update({ ...runtime, ...payload, busy:false, retryAction:'', message:'', dismissed:false, snooze:0 });
  window.__nativeActions = [];
  window.MutsumiAndroid = {
    getDisplayOrientation: () => innerWidth > innerHeight ? 'landscape' : 'portrait',
    getFocusRuntime: () => JSON.stringify(view()),
    getFocusDestination: () => '', clearFocusDestination: () => {},
    setAppearance: () => {}, imagePickerOwnsBack: () => false,
    openFocusSettings: () => { window.__settingsOpened = true; },
    clearFocusState: () => update({mode:'idle', sessionId:0, elapsedSeconds:0, restStartedAtEpochMs:0}),
    syncFocusState: raw => {
      const payload = JSON.parse(raw);
      if (runtime.busy || payload.revision !== runtime.revision) return;
      if (payload.mode === 'idle' && ['rest','ended'].includes(runtime.mode)) return;
      update(payload);
    },
    performFocusAction: async (action, revision, token) => {
      if (runtime.busy || revision !== runtime.revision || token && token !== view().reminderToken) return;
      window.__nativeActions.push(action);
      if (action === 'snooze') { runtime.snooze = Date.now() + 300000; runtime.message = '已设置 5 分钟后再提醒'; persist(); }
      else if (action === 'dismiss') { runtime.dismissed = true; persist(); }
      else if (action === 'endRest') update({mode:'idle', sessionId:0, elapsedSeconds:0, restStartedAtEpochMs:0});
      else {
        runtime.busy = true; window.MutsumiWeb?.refresh();
        if (window.__nativeFailure) {
          runtime.busy = false; runtime.retryAction = `com.mutsumi.focus.${action.toUpperCase()}`;
          runtime.message = '操作未确认，请检查网络后重试'; persist();
        } else {
          const response = await fetch(`/api/focus/${action === 'end' ? 'end' : 'pause'}`, {
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({session_id:runtime.sessionId, paused:action === 'pause'})});
          const result = await response.json();
          if (!response.ok) throw new Error(JSON.stringify(result));
          update(fromServer(result.session));
        }
      }
      window.MutsumiWeb?.refresh();
    },
  };
}

(async () => {
  const browser = await chromium.launch({ headless:true, channel:'chrome' });
  const context = await browser.newContext({ viewport:{width:412,height:915}, isMobile:true, hasTouch:true,
    userAgent:'Mozilla/5.0 Chrome/130.0.0.0 Mobile MutsumiFocus/0.7.0' });
  const errors = [];
  try {
    await context.addInitScript(nativeBridge);
    const login = await context.request.post(base + '/login', { form:{identifier:'androidowner', password:'Emulator-only-2026'} });
    assert(login.ok());
    await context.request.post(base + '/api/_test/scenario', { data:{scenario:'idle'} });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + '/androidowner');
    await page.waitForFunction(() => window.MutsumiWeb && document.querySelector('#focus-modes .mode'));
    const layout = await page.evaluate(() => ({
      width:innerWidth, overflow:document.documentElement.scrollWidth - innerWidth,
      controls:document.querySelector('#dashboard-controls').getBoundingClientRect().top,
      time:document.querySelector('.time-grid').getBoundingClientRect().top,
      buttonHeight:document.querySelector('#open-focus-launch').getBoundingClientRect().height,
      scale:window.MutsumiViewport.scale,
      logicalWidth:window.MutsumiViewport.logicalWidth,
      panelRadius:getComputedStyle(document.querySelector('#dashboard-controls')).borderRadius,
      goalRadius:getComputedStyle(document.querySelector('#native-focus-goal')).borderRadius,
    }));
    assert(layout.controls < layout.time, 'Focus controls must precede time cards');
    assert(layout.overflow <= 1, `Horizontal overflow ${layout.overflow}`);
    assert.equal(layout.scale, 0.6, 'Portrait home must use the requested 60% canvas');
    assert(Math.abs(layout.logicalWidth * layout.scale - layout.width) < 1, 'Scaled canvas must still fill the phone width');
    assert(Math.abs(layout.buttonHeight - 48 * 0.6) < 1, 'Existing 48px focus control must render at 60%');
    assert.equal(layout.panelRadius, '8px');
    assert.equal(layout.goalRadius, '7px');
    assert(await page.locator('.native-chart-toggle').isVisible(), 'Chart expansion must remain visible');
    assert(await page.locator('.native-stat-toggle').isVisible(), 'Statistics expansion must remain visible');
    await page.screenshot({path:path.join(output,'portrait-idle.png'), fullPage:false});

    await page.locator('#native-focus-goal').selectOption('25');
    await page.locator('#open-focus-launch').click();
    await page.locator('#submit-focus-launch').click();
    await page.waitForFunction(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode === 'focusing');
    assert.equal(await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).plannedSeconds), 1500);
    await page.screenshot({path:path.join(output,'portrait-focusing.png'), fullPage:false});
    await page.locator('#toggle-focus-pause').click();
    await page.waitForFunction(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode === 'paused');
    const frozen = await page.locator('#focus-timer').innerText();
    await page.waitForTimeout(1100);
    assert.equal(await page.locator('#focus-timer').innerText(), frozen);

    const scenario = await context.request.post(base + '/api/_test/scenario', {data:{scenario:'paused5min', seconds_before:-2}});
    const payload = await scenario.json();
    await page.evaluate(payload => { __setNative(payload.native_state); MutsumiWeb.refresh(); }, payload);
    await page.waitForFunction(() => document.querySelector('#native-runtime-reminder')?.textContent.includes('暂停满'));
    await page.locator('#native-runtime-actions').getByText('再等 5 分钟', {exact:true}).click();
    await page.waitForFunction(() => !JSON.parse(MutsumiAndroid.getFocusRuntime()).reminder);
    const deadline = await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).nextReminderAt);
    await page.reload();
    await page.waitForFunction(() => window.MutsumiWeb);
    assert.equal(await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).nextReminderAt), deadline);
    await page.waitForTimeout(400);
    const glass = await page.evaluate(() => {
      const card = document.querySelector('#native-runtime-card'), style = getComputedStyle(card);
      return {background:style.backgroundColor, blur:style.backdropFilter, radius:style.borderRadius,
        position:style.position, bounds:card.getBoundingClientRect().toJSON(),
        buttonHeight:card.querySelector('button').getBoundingClientRect().height};
    });
    assert(glass.blur.includes('blur(10px)'), 'Pause panel must blur the underlying content');
    assert.equal(glass.position, 'absolute', 'Glass panel must actually cover content inside the focus column');
    assert.equal(glass.radius, '8px');
    assert(Math.abs(glass.buttonHeight - 34 * .6) < 1, 'New action proportions must use the existing 34px controls');
    console.log('Pause surface', await page.evaluate(() => ({ opacity:getComputedStyle(document.querySelector('#active-mode-view')).opacity, filter:getComputedStyle(document.querySelector('#active-mode-view')).filter, overlayHidden:document.querySelector('#focus-state-overlay').hidden })));
    await page.screenshot({path:path.join(output,'portrait-paused-snoozed.png'), fullPage:false});
    await page.locator('.native-chart-toggle').click();
    await page.setViewportSize({width:412,height:480});
    await page.locator('#dashboard-activity').scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    assert(await page.locator('#native-focus-dock').isVisible(), 'Bottom focus actions must stay available while reading charts');
    await page.locator('#native-dock-details').click();
    assert.equal(await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode), 'paused');
    await page.locator('#native-runtime-details').getByText('关闭', {exact:true}).click();
    await page.setViewportSize({width:412,height:915});
    await page.locator('#dashboard-controls').scrollIntoViewIfNeeded();
    await page.evaluate(() => { window.__nativeFailure = true; });
    await page.locator('#native-runtime-actions').getByText('继续专注', {exact:true}).click();
    await page.waitForFunction(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).retryAction);
    assert.equal(await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode), 'paused');
    await page.evaluate(() => { window.__nativeFailure = false; });
    await page.locator('#native-runtime-actions').getByText('重试', {exact:true}).click();
    await page.waitForFunction(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode === 'focusing');
    await page.evaluate(() => MutsumiWeb.navigateFocus('details'));
    assert(await page.locator('#native-runtime-details').isVisible());
    await page.screenshot({path:path.join(output,'portrait-focus-details.png'), fullPage:false});
    assert.equal(await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode), 'focusing');
    await page.locator('#native-runtime-details').getByText('关闭', {exact:true}).click();
    await page.evaluate(() => MutsumiAndroid.performFocusAction('end', JSON.parse(MutsumiAndroid.getFocusRuntime()).revision, ''));
    await page.waitForFunction(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode === 'ended');
    await page.locator('#native-rest-goal').selectOption('15');
    await page.locator('#start-rest').click();
    await page.waitForFunction(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode === 'rest');
    const restStarted = await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).restStartedAtEpochMs);
    await page.reload();
    await page.waitForFunction(() => window.MutsumiWeb);
    assert.equal(await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).restStartedAtEpochMs), restStarted);
    assert.equal(await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).restTargetSeconds), 900);
    await page.screenshot({path:path.join(output,'portrait-rest.png'), fullPage:false});
    await page.setViewportSize({width:915,height:412});
    await page.waitForFunction(() => document.documentElement.dataset.viewportMode === 'wide');
    await page.waitForTimeout(400);
    await page.screenshot({path:path.join(output,'landscape-rest.png'), fullPage:false});
    await page.setViewportSize({width:412,height:915});
    await page.waitForFunction(() => document.documentElement.dataset.viewportMode === 'portrait');
    await page.evaluate(() => MutsumiWeb.endRest());
    await page.waitForFunction(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode === 'idle');
    const beforeSettlement = await (await context.request.get(base + '/api/dashboard')).json();
    const settlementResponse = await context.request.post(base + '/api/daily-settlement', {
      data:{expected_date:beforeSettlement.now.slice(0,10), session_id:null}});
    assert(settlementResponse.ok(), await settlementResponse.text());
    await page.evaluate(() => MutsumiWeb.refresh());
    await page.waitForFunction(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).mode === 'settled');
    assert.equal(await page.evaluate(() => JSON.parse(MutsumiAndroid.getFocusRuntime()).reminder), '');
    await page.evaluate(() => MutsumiWeb.navigateFocus('summary'));
    assert(await page.locator('.daily-report-dialog').isVisible());
    await page.keyboard.press('Escape');
    await page.locator('.settings-link').click();
    await page.waitForFunction(() => window.MutsumiWeb && document.querySelector('.native-settings-entry'));
    await page.locator('.native-settings-entry button').click();
    assert(await page.evaluate(() => window.__settingsOpened));
    assert.equal(await page.evaluate(() => MutsumiViewport.scale), 1, 'Settings must retain its own scale');
    await page.locator('#new-subject-name').fill('旋转后保留草稿');
    await page.setViewportSize({width:915,height:412});
    await page.setViewportSize({width:412,height:915});
    assert.equal(await page.locator('#new-subject-name').inputValue(), '旋转后保留草稿');
    await page.waitForTimeout(400);
    await page.screenshot({path:path.join(output,'portrait-settings.png'), fullPage:true});
    await page.setViewportSize({width:320,height:720});
    await page.evaluate(() => {
      document.documentElement.dataset.theme = 'dark';
      document.documentElement.dataset.themeMode = 'dark';
      document.documentElement.dataset.themePalette = 'ocean';
    });
    await page.waitForTimeout(250);
    console.log('Narrow overflow', await page.evaluate(() => ({width:innerWidth, scroll:document.documentElement.scrollWidth,
      elements:[...document.querySelectorAll('*')].filter(el=>el.getBoundingClientRect().right > innerWidth+1 && el.getBoundingClientRect().width).slice(0,12).map(el=>({tag:el.tagName,id:el.id,cls:el.className,right:el.getBoundingClientRect().right,width:el.getBoundingClientRect().width}))})));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Narrow dark settings must not overflow');
    await page.screenshot({path:path.join(output,'narrow-dark-settings.png'), fullPage:true});
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output,'web-validation.json'), JSON.stringify({passed:true,layout,glass,checks:[
      'portrait order and touch targets','planned focus','pause freezes effective time','snooze shared deadline and reload',
      'failed resume retains state and offers retry','details does not resume','target rest and reload',
      'sticky bottom actions and chart expansion','landscape and portrait','settings integrated and draft retained','320px dark ocean layout','real settlement stops reminder and opens report'],errors},null,2));
    console.log(`PASS: APK WebView assets, screenshots and report in ${output}`);
  } finally { await context.close(); await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
