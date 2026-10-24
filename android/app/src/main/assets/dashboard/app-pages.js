/* APK pages. Session recap adapts to orientation; daily report keeps its existing wide layout. */
(() => {
  'use strict';
  if (window.AppPages) return;
  const root = document.documentElement, $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const duration = value => { const n=Math.max(0,Math.floor(Number(value)||0)); return [Math.floor(n/3600),Math.floor(n/60)%60,n%60].map(v=>String(v).padStart(2,'0')).join(':'); };
  const minutes = value => value > 0 ? `${Math.floor(value/60)}小时${value%60 ? value%60+'分钟':''}`.replace(/^0小时/,'') : '未设时长';
  const portrait = () => root.classList.contains('native-app') && root.dataset.viewportMode === 'portrait';
  const owner = () => document.body.dataset.role !== 'guest' && /^[1-9]\d*$/.test(document.body.dataset.viewerId || '');
  const historyKey='mutsumiAppPage';
  let dialog, content, kind='', historyToken=null, returnFocus=null, generation=0, latest=null, model=null, draft=null, busy=false;
  let initialSession=null, savedSessionId=0;
  const messages={daily_task_changed:'任务已在其他端更新，请确认最新状态后再保存。',focus_session_not_ended:'这段专注尚未结束。',daily_task_not_found:'这个任务已更新或移出，请重新选择。',focus_session_not_found:'暂时找不到这段专注记录。',public_https_push_url_required:'请填写可访问的公网 HTTPS 地址。',https_push_url_required:'接收地址需要使用 HTTPS。',invalid_push_url:'请检查接收地址。',push_not_configured:'请先保存接收地址。',authentication_required:'登录已失效，请重新登录。'};
  async function api(url, options={}) {
    const controller=new AbortController(),deadline=setTimeout(()=>controller.abort(),15000);
    try {
      const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,signal:controller.signal,headers:{'Content-Type':'application/json',...(options.headers||{})}});
      const data=await response.json().catch(()=>{throw Error('读取失败，请稍后重试。');});
      if(!response.ok)throw Error(messages[data.error] || '操作未完成，请稍后重试。');return data;
    }catch(error){if(error.name==='AbortError')throw Error('连接超时，请重新读取后重试。');throw error;}
    finally{clearTimeout(deadline);}
  }
  function install() {
    if(!document.querySelector('link[data-app-pages]')){
      const link=document.createElement('link');link.rel='stylesheet';link.href='/static/app-pages.css';link.dataset.appPages='1';document.head.append(link);
    }
    if(!owner())return;
    const controls=$('#dashboard-controls');
    if(controls&&!controls.querySelector('[data-open-daily-tasks]')){
      const button=document.createElement('button');button.type='button';button.className='app-plan-shortcut ui-button ui-button--quiet';button.dataset.openDailyTasks='1';button.innerHTML='<span>今日计划</span><b data-daily-plan-count>0 / 0</b>';controls.append(button);
    }
    const settings=$('#settings-data-panel') || $('#settings-system-panel') || $('body.page-settings .app-main');
    if(settings&&!settings.querySelector('[data-open-plan-integration]')){
      const section=document.createElement('article');section.className='panel settings-panel app-plan-setting';section.innerHTML='<h2>每日计划与完成同步</h2><p>Agent 上报 · 今日待办 · 结算后推送</p><button type="button" class="ui-button ui-button--secondary" data-open-plan-integration>打开接入设置</button>';settings.append(section);
    }
    if(!dialog){
      dialog=document.createElement('dialog');dialog.id='app-task-page';dialog.className='app-native-page';dialog.setAttribute('aria-labelledby','app-page-title');
      content=document.createElement('div');content.className='app-page-shell';dialog.append(content);document.body.append(dialog);
      dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
      dialog.addEventListener('click',onClick);dialog.addEventListener('change',onChange);
    }
  }
  function data(){return latest||window.DashboardController?.getData()||{};}
  function header(title, subtitle=''){return `<header class="app-page-head"><button type="button" class="ui-button ui-button--quiet" data-app-back aria-label="返回">←</button><div><h1 id="app-page-title">${esc(title)}</h1><p>${esc(subtitle)}</p></div><span class="app-page-clock" data-app-clock></span></header>`;}
  function foot(buttons){return `<footer class="app-page-foot">${buttons}<p class="app-page-message" role="status" data-app-message></p></footer>`;}
  function show(next, trigger){
    install();if(!dialog)return;
    generation++;kind=next;busy=false;
    if(!dialog.open){returnFocus=trigger instanceof HTMLElement?trigger:document.activeElement;dialog.showModal();historyToken=`${Date.now()}-${Math.random().toString(36).slice(2)}`;history.pushState({...history.state,[historyKey]:historyToken},'');}
    dialog.dataset.pageKind=next;
    content.innerHTML=header(next==='session'?'本段结算':next==='integration'?'计划接入与同步':'每日计划')+'<div class="app-page-loading" role="status">正在读取…</div>';
    window.DashboardClock?.refresh();
    return generation;
  }
  function close(fromHistory=false){
    generation++;busy=false;
    if(!dialog?.open)return;
    dialog.close();if(!fromHistory&&historyToken&&history.state?.[historyKey]===historyToken)history.back();historyToken=null;
    const target=returnFocus?.isConnected?returnFocus:$('[data-open-daily-tasks]');target?.focus?.({preventScroll:true});
  }
  function paint(html){
    const scroll=content.querySelector('.app-task-list')?.scrollTop||0;
    content.innerHTML=html;const list=content.querySelector('.app-task-list');if(list)list.scrollTop=scroll;
    tick(window.DashboardClock?.lastFrame() || {nowEpochMs:Date.now()});
  }
  function message(text){const host=content?.querySelector('[data-app-message]');if(host)host.textContent=text;}
  function syncText(sync){return ({pending:'正在同步',sent:'同步成功',failed:sync?.next_attempt_at?'失败，等待重试':'同步失败，可重试',unconfigured:'待配置接收端',cancelled:'结算已撤销',cancelling:'正在撤销同步'})[sync?.status]||'结算后自动推送';}
  function syncBadge(){return `<span class="app-sync-badge" data-task-sync>${esc(syncText(data().island_context?.task_sync))}</span>`;}
  function taskRow(task, radio=false){
    const selected=radio&&Number(draft?.taskId)===task.id;
    return `<${radio?'label':'article'} class="app-task-row${task.completed?' is-complete':''}${selected?' is-selected':''}" data-task-row="${task.id}">${radio?`<input type="radio" name="recap-task" value="${task.id}" ${selected?'checked':''}>`:`<button type="button" class="app-task-complete" data-complete-task="${task.id}" aria-label="${task.completed?'撤销完成':'标记完成'} ${esc(task.title)}" aria-pressed="${task.completed}">${window.StatusIcons.completion(task.completed)}</button>`}<div class="app-task-copy"><strong>${esc(task.title)}</strong><span>${esc(duration(task.focus_seconds))} 已投入${task.target_minutes?' / '+esc(minutes(task.target_minutes)):''} · ${task.focus_records.length} 段</span>${task.note?`<small>${esc(task.note)}</small>`:''}</div><b class="app-task-state" aria-label="${task.completed?'已完成':'进行中'}">${task.completed?(radio?window.StatusIcons.completion():''):'进行中'}</b></${radio?'label':'article'}>`;
  }
  function dateAt(epoch,zone){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(epoch));const p=Object.fromEntries(parts.map(part=>[part.type,part.value]));return `${p.year}-${p.month}-${p.day}`;}
  function clockAt(value,zone){try{return new Intl.DateTimeFormat('zh-CN',{timeZone:zone||'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));}catch(_){return '—';}}
  function renderSession(){
    const session=model.session, tasks=model.catalog.tasks, zone=model.catalog.timezone;
    const assigned=tasks.find(task=>task.id===Number(draft.taskId));
    const effective=Number(session.effective_seconds||0),pause=Number(session.paused_seconds||0);
    paint(header('本段结算',`${model.catalog.date} · ${session.subject||'专注记录'}`)+`
      <main class="app-page-main app-recap-main"><section class="app-card app-recap-hero"><div><span class="app-eyebrow">有效专注</span><strong class="app-duration">${duration(effective)}</strong><p>累计暂停 ${duration(pause)}</p></div><div class="app-recap-rest"><span>已休息</span><strong data-recap-rest>00:00:00</strong><small>从本段结束时计时</small></div><div class="app-session-range"><span><small>开始</small>${esc(clockAt(session.started_at,zone))}</span><i aria-hidden="true"></i><span><small>结束</small>${esc(clockAt(session.ended_at,zone))}</span></div></section>
      <section class="app-recap-plan"><div class="app-section-head"><h2>归入每日任务</h2><span>${model.catalog.completed} / ${model.catalog.total} 已完成</span></div><div class="app-task-list app-card"><label class="app-task-row${!draft.taskId?' is-selected':''}" data-task-row=""><input type="radio" name="recap-task" value="" ${!draft.taskId?'checked':''}><div class="app-task-copy"><strong>暂不归类</strong><span>专注记录仍会完整保留</span></div></label>${tasks.map(task=>taskRow(task,true)).join('')}${!tasks.length?'<p class="app-empty">这一天还没有任务，可由其他系统上报计划。</p>':''}</div></section>
      <label class="app-card app-complete-toggle"><span><strong>此任务已完成</strong><small>未完成时仍会累计本段专注</small></span><span class="app-complete-control"><input type="checkbox" data-session-completed ${draft.completed?'checked':''} ${!assigned?'disabled':''}>${window.StatusIcons.completion()}</span></label></main>`+
      foot('<button type="button" class="ui-button ui-button--primary" data-save-session>保存记录</button><button type="button" class="ui-button ui-button--secondary" data-session-next>保存并继续</button>'));
  }
  async function openSession(session,trigger){
    if(!root.classList.contains('native-app')||!owner())return false;
    initialSession=session;const serial=show('session',trigger);
    try{
      if(!Number.isInteger(Number(session.id))||Number(session.id)<=0)throw Error('暂时没有可归类的专注记录。');
      const [record,today]=await Promise.all([api(`/api/focus/${Number(session.id)}/daily-task`),api('/api/daily-tasks')]);
      const day=dateAt(record.session.started_at,today.timezone);
      const catalog=day===today.date?today:await api(`/api/daily-tasks?date=${day}`);
      if(serial!==generation||!dialog.open)return true;
      model={session:record.session,catalog};draft={taskId:record.task_id||null,completed:catalog.tasks.find(t=>t.id===record.task_id)?.completed||false};
      savedSessionId=0;renderSession();
    }catch(error){if(serial===generation)paint(header('本段结算')+`<main class="app-page-main"><p class="app-empty">${esc(error.message)}</p><button type="button" class="ui-button ui-button--secondary" data-retry-session>重新读取</button></main>`+foot(''));}
    return true;
  }
  async function openTasks(trigger){
    if(!owner())return;
    const serial=show('tasks',trigger);
    try{const catalog=await api('/api/daily-tasks');if(serial!==generation)return;model={catalog};renderTasks();}
    catch(error){if(serial===generation)paint(header('每日计划')+`<main class="app-page-main"><p class="app-empty">${esc(error.message)}</p></main>`+foot('<button type="button" class="ui-button ui-button--secondary" data-retry-tasks>重新读取</button>'));}
  }
  function renderTasks(){const c=model.catalog;paint(header('每日计划',c.date)+`<main class="app-page-main app-plan-main"><section class="app-card app-plan-hero"><div><span class="app-eyebrow">今日完成</span><strong>${c.completed}<small> / ${c.total}</small></strong></div><div><span>累计投入</span><b>${duration(c.focus_seconds)}</b>${syncBadge()}</div><div class="app-plan-track"><i style="width:${c.total?c.completed/c.total*100:0}%"></i></div></section><div class="app-section-head"><h2>今日待办</h2><span>由已接入系统同步</span></div><div class="app-task-list app-card">${c.tasks.map(task=>taskRow(task)).join('')||'<p class="app-empty">今天还没有计划。接入你的 Agent 后，上报的任务会显示在这里。</p>'}</div></main>`+foot('<button type="button" class="ui-button ui-button--secondary" data-open-plan-integration>接入与推送设置</button>'));}
  async function openIntegration(trigger){
    if(!owner())return;
    const serial=show('integration',trigger);
    try{const settings=await api('/api/daily-tasks/push');if(serial!==generation)return;model={settings};renderIntegration();}
    catch(error){if(serial===generation)paint(header('计划接入与同步')+`<main class="app-page-main"><p class="app-empty">${esc(error.message)}</p></main>`+foot('<button type="button" class="ui-button ui-button--secondary" data-retry-integration>重新读取</button>'));}
  }
  function renderIntegration(){const s=model.settings;paint(header('计划接入与同步','每日计划 · Agent 接入')+`<main class="app-page-main app-integration-main"><section class="app-card app-integration-card"><div class="app-section-head"><h2>上报与读取</h2><span>长期有效的独立 key</span></div><p>让 Agent 上报计划、读取今日待办，或同步完成状态。</p><div class="app-copy-actions"><button type="button" class="ui-button ui-button--primary" data-plan-copy="prompt">复制接入 Prompt</button><button type="button" class="ui-button ui-button--secondary" data-plan-copy="link">复制上报链接</button><button type="button" class="ui-button ui-button--quiet" data-plan-rotate>更换 key</button></div><small>Prompt 包含完整协议与本账户鉴权链接。</small></section><section class="app-card app-integration-card"><div class="app-section-head"><h2>结算后主动推送</h2>${syncBadge()}</div><p>每日结算后统一发送任务完成快照，失败会保留并重试。</p><label class="app-input-label">HTTPS 接收地址<input type="url" inputmode="url" data-push-url autocomplete="off" placeholder="https://agent.example/receive" value="${esc(s.url)}"></label><label class="app-input-label">接收端鉴权密钥 <small>可选</small><input type="password" data-push-token autocomplete="new-password" placeholder="${s.has_token?'已配置，留空保留':'未配置，可不填写'}"></label>${s.has_token?'<button type="button" class="ui-button ui-button--quiet" data-clear-push-token>清除已保存的密钥</button>':''}<small>接收方按事件 ID 去重，保存成功后返回 2xx。</small></section><section class="app-card app-integration-state"><span>最近一次同步</span><strong>${esc(syncText(s.sync))}</strong><small>${s.sync?esc(s.sync.date)+' · '+s.sync.completed+' / '+s.sync.total+' 已完成':'还没有结算推送记录'}</small>${s.sync?.status==='failed'?'<button type="button" class="ui-button ui-button--secondary" data-retry-push>立即重试</button>':''}</section></main>`+foot('<button type="button" class="ui-button ui-button--primary" data-save-push>保存推送设置</button>'));}
  async function saveSession(){
    if(busy)return false;
    const serial=generation,task=model.catalog.tasks.find(t=>t.id===Number(draft.taskId));
    if(draft.taskId&&!task){message('原任务已移出，请重新选择归类或暂不归类。');return false;}
    busy=true;let confirmed=false;
    content.querySelectorAll('input,[data-save-session],[data-session-next]').forEach(node=>node.disabled=true);
    message('正在保存…');
    try{
      await api(`/api/focus/${model.session.id}/daily-task`,{method:'PUT',body:JSON.stringify({task_id:task?.id||null,...(task?{completed:draft.completed,expected_revision:task.revision}:{})})});
      if(serial!==generation)return false;
      const updated=await api(`/api/daily-tasks?date=${model.catalog.date}`).catch(()=>null);
      if(serial!==generation)return false;
      if(updated)model.catalog=updated;
      confirmed=true;message('归类与完成状态已保存');
      content.querySelector('[data-save-session]').textContent='记录已保存';window.MutsumiWeb?.refresh?.();
      return true;
    }catch(error){
      if(serial!==generation)return false;
      const updated=await api(`/api/daily-tasks?date=${model.catalog.date}`).catch(()=>null);
      if(serial!==generation)return false;
      if(updated){model.catalog=updated;draft.completed=updated.tasks.find(t=>t.id===Number(draft.taskId))?.completed||false;renderSession();}
      message(error.message);return false;
    }finally{
      if(serial===generation){
        busy=false;content.querySelectorAll('input[name="recap-task"],[data-session-next]').forEach(node=>node.disabled=false);
        const checkbox=content.querySelector('[data-session-completed]');if(checkbox)checkbox.disabled=!model.catalog.tasks.some(t=>t.id===Number(draft.taskId));
        const button=content.querySelector('[data-save-session]');if(button)button.disabled=confirmed;
      }
    }
  }
  async function completeTask(id){if(busy)return;const task=model.catalog.tasks.find(t=>t.id===id);if(!task)return;busy=true;const serial=generation;try{const catalog=await api('/api/daily-tasks/complete',{method:'POST',body:JSON.stringify({task_id:id,completed:!task.completed,expected_revision:task.revision})});if(serial!==generation)return;model.catalog=catalog;renderTasks();message(task.completed?'已恢复为未完成':'已标记完成');window.MutsumiWeb?.refresh?.();}catch(error){if(serial!==generation)return;const updated=await api('/api/daily-tasks').catch(()=>null);if(updated&&serial===generation){model.catalog=updated;renderTasks();}if(serial===generation)message(error.message);}finally{if(serial===generation)busy=false;}}
  async function savePush(){if(busy)return;busy=true;const serial=generation;const token=content.querySelector('[data-push-token]'),body={url:content.querySelector('[data-push-url]').value.trim()};if(token.value||token.dataset.clear==='true')body.token=token.value;try{const settings=await api('/api/daily-tasks/push',{method:'PUT',body:JSON.stringify(body)});if(serial!==generation)return;model.settings=settings;renderIntegration();message(settings.configured?'推送设置已保存':'已保存，结算记录会保留在本地服务端');window.MutsumiWeb?.refresh?.();}catch(error){if(serial===generation)message(error.message);}finally{if(serial===generation)busy=false;}}
  async function copyPlan(action,rotate=false){if(busy)return;busy=true;const serial=generation;try{if(rotate){const confirmed=await window.DashboardController?.confirm?.({title:'更换每日计划 key',message:'更换后旧上报链接将立即失效，需要更新已接入的 Agent。',label:'更换 key'});if(!confirmed)return;}const details=await api('/api/daily-plan-reporter/connection'+(rotate?'/rotate':''),{method:'POST',body:'{}'});if(!rotate)await navigator.clipboard.writeText(action==='prompt'?details.prompt:details.report_url);if(serial===generation)message(rotate?'key 已更换，旧链接已失效。':action==='prompt'?'完整接入 Prompt 已复制。':'上报链接已复制。');}catch(error){if(serial===generation)message(error.message);}finally{if(serial===generation)busy=false;}}
  async function onClick(event){const target=event.target.closest?.('button');if(!target)return;
    if(target.matches('[data-app-back]'))close();
    else if(target.matches('[data-save-session]'))saveSession();
    else if(target.matches('[data-session-next]')){const serial=generation;if(await saveSession()&&serial===generation){close();window.MutsumiWeb?.navigateFocus?.('next');}}
    else if(target.matches('[data-retry-tasks]'))openTasks(target);
    else if(target.matches('[data-retry-integration]'))openIntegration(target);
    else if(target.matches('[data-retry-session]'))openSession(initialSession);
    else if(target.matches('[data-complete-task]'))completeTask(Number(target.dataset.completeTask));
    else if(target.matches('[data-open-plan-integration]'))openIntegration(target);
    else if(target.matches('[data-save-push]'))savePush();
    else if(target.matches('[data-plan-copy]'))copyPlan(target.dataset.planCopy);
    else if(target.matches('[data-plan-rotate]'))copyPlan('',true);
    else if(target.matches('[data-clear-push-token]')){const input=content.querySelector('[data-push-token]');input.value='';input.dataset.clear='true';input.placeholder='保存后将清除密钥';target.hidden=true;}
    else if(target.matches('[data-retry-push]')){try{await api('/api/daily-tasks/push/retry',{method:'POST',body:'{}'});message('已加入重试队列');window.MutsumiWeb?.refresh?.();}catch(error){message(error.message);}}
  }
  function onChange(event){if(kind!=='session')return;const input=event.target;
    if(input.name==='recap-task'){draft.taskId=input.value?Number(input.value):null;const task=model.catalog.tasks.find(t=>t.id===draft.taskId);draft.completed=task?.completed||false;const checkbox=content.querySelector('[data-session-completed]');checkbox.checked=draft.completed;checkbox.disabled=!task;content.querySelectorAll('[data-task-row]').forEach(row=>row.classList.toggle('is-selected',row.dataset.taskRow===input.value));}
    if(input.matches('[data-session-completed]'))draft.completed=input.checked;
    savedSessionId=0;const button=content.querySelector('[data-save-session]');button.disabled=false;button.textContent='保存记录';message('');
  }
  function tick(frame){const epoch=frame.nowEpochMs,zone=model?.catalog?.timezone||data().daily_settlement?.report?.timezone||'Asia/Shanghai';document.querySelectorAll('[data-app-clock]').forEach(node=>{node.textContent=clockAt(epoch,zone);});if(dialog?.open&&kind==='session'&&model?.session?.ended_at){const node=content.querySelector('[data-recap-rest]');if(node)node.textContent=duration((epoch-Date.parse(model.session.ended_at))/1000);}document.querySelectorAll('[data-task-sync]').forEach(node=>{node.textContent=syncText(data().island_context?.task_sync);});}
  function dailyReportHtml(report){
    if(!portrait())return null;
    const tasks=report.daily_tasks,checkins=report.checkins,subjects=report.subject_totals||[],target=Number(report.target_seconds)||0,total=Number(report.total_seconds)||0;
    const completion=target?Math.round(total/target*100):0,index=report.index,change=index?Number(index.return_percent):null;
    const taskRows=tasks?.tasks?.map(task=>`<li><span class="app-report-mark" aria-label="${task.completed?'已完成':'未完成'}">${window.StatusIcons.completion(task.completed)}</span><span>${esc(task.title)}</span><b>${duration(task.focus_seconds)}</b></li>`).join('');
    const checkinRows=checkins?.items?.map(item=>`<span class="${item.completed?'is-done':''}">${esc(item.name)} <b aria-label="${item.completed?'已完成':'未完成'}">${window.StatusIcons.completion(item.completed)}</b></span>`).join('');
    const sync=data().island_context?.task_sync,matching=sync?.date===report.date;
    return `<div class="app-page-shell app-daily-shell">${header('每日结算',report.date).replace('id="app-page-title"','id="daily-report-title"').replace('data-app-back','data-native-report-back')}<main class="app-page-main app-daily-main"><section class="app-card app-daily-hero"><div><span class="app-eyebrow">今日有效专注</span><strong class="app-duration">${duration(total)}</strong><p id="daily-report-caption">${esc(report.username?'@'+report.username:'今日专注记录')} · ${esc(report.first_start?clockAt(report.first_start,report.timezone):'—')} — ${esc(report.last_end?clockAt(report.last_end,report.timezone):'—')}</p></div><div class="app-daily-goal"><strong>${completion}<small>%</small></strong><span>目标 ${duration(target)}</span></div><div class="app-plan-track"><i style="width:${Math.min(completion,100)}%"></i></div></section>
    <section class="app-daily-metrics"><div class="app-card"><span>较昨日</span><b>${report.delta_seconds>0?'+':report.delta_seconds<0?'−':'±'}${duration(Math.abs(Number(report.delta_seconds)||0))}</b></div><div class="app-card"><span>历日排名</span><b>${report.rank?'#'+Number(report.rank):'—'}</b></div><div class="app-card"><span>最长一段</span><b>${report.longest_session_seconds==null?'—':duration(report.longest_session_seconds)}</b></div></section>
    <div class="app-daily-columns"><section class="app-card app-daily-subjects"><h2>时间去向</h2>${subjects.map(item=>`<div><span>${esc(item.subject)}</span><b>${duration(item.seconds)}</b><i><em style="width:${Math.min(100,Math.max(0,Number(item.percent)||0))}%"></em></i></div>`).join('')||'<p class="app-empty">暂无科目明细</p>'}</section><section class="app-card app-daily-index"><h2>专注指数</h2><strong class="${change>0?'is-rise':change<0?'is-fall':''}">${index?Number(index.current).toFixed(3):'—'}</strong><b>${change===null?'未保存快照':(change>=0?'+':'')+change.toFixed(2)+'%'}</b><span>${report.challenge?report.challenge.active_today?'连胜挑战 · ±20%':'普通节奏 · ±10%':'未保存挑战状态'}</span><small>${index?.is_market_closed?'已收盘':'结算时快照'}</small></section></div>
    <section class="app-card app-daily-tasks"><div class="app-section-head"><h2>计划完成</h2><b>${tasks?tasks.completed+' / '+tasks.total:'未记录'}</b></div><ul>${taskRows||'<li class="app-empty">'+(tasks?'今日没有每日任务':'这份历史结算未保存计划明细')+'</li>'}</ul><div class="app-daily-sync"><span ${matching?'data-task-sync':''}>${matching?esc(syncText(sync)):'结算快照'}</span><button type="button" class="ui-button ui-button--quiet" data-native-report-tasks>查看今日待办</button></div></section>
    <section class="app-card app-daily-checkins"><div class="app-section-head"><h2>打卡</h2><b>${checkins?checkins.completed+' / '+checkins.total:'未记录'}</b></div><div>${checkinRows||'<p class="app-empty">没有打卡明细</p>'}</div><small>结算前 24 小时</small></section></main><footer class="app-page-foot app-daily-foot"><span>${esc(report.closing_note||'今天的投入已经收好。')}</span>${window.DashboardController?.canCancelSettlement?.(report.date)?`<button type="button" class="ui-button ui-button--quiet" data-cancel-daily-settlement data-settlement-date="${esc(report.date)}" data-settlement-id="${Number(data().daily_settlement?.id)}" ${window.DashboardController?.isSettlementBusy?.()?'disabled':''}>取消结算</button>`:''}</footer></div>`;
  }
  document.addEventListener('click',event=>{const trigger=event.target.closest?.('[data-open-daily-tasks],[data-open-plan-integration],[data-native-report-back],[data-native-report-tasks]');if(!trigger||!owner())return;if(trigger.matches('[data-native-report-back]'))window.DailyReport?.close();else if(trigger.matches('[data-native-report-tasks],[data-open-daily-tasks]'))openTasks(trigger);else if(!dialog?.contains(trigger))openIntegration(trigger);});
  document.addEventListener('dashboard:updated',event=>{latest=event.detail;install();document.querySelectorAll('[data-daily-plan-count]').forEach(node=>{node.textContent=`${latest.daily_plan?.completed||0} / ${latest.daily_plan?.total||0}`;});});
  document.addEventListener('DOMContentLoaded',()=>{install();window.DashboardClock?.subscribe('app-pages',tick);});
  window.addEventListener('popstate',()=>{if(dialog?.open&&history.state?.[historyKey]!==historyToken)close(true);});
  window.AppPages={openSession,openTasks,openIntegration,dailyReportHtml,isPortrait:portrait};
})();
