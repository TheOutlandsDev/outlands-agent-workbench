"use strict";
const token=document.querySelector('meta[name="workbench-token"]').content;
const $=id=>document.getElementById(id);
let configuration=null,selected=null,current=null,polling=false,busy=false,initialized=false,setupDraft=null;
const friendly={REVIEW_READY:"Ready for review",RUNNING:"Running",STOP_REQUESTED:"Stop requested",FAILED:"Failed",REFUSED:"Refused",INTERRUPTED:"Interrupted",UNCERTAIN:"Uncertain",RECOVERY_REQUIRED:"Needs inspection"};
const errors={SOURCE_HASH_CHANGED:"Source files changed. Update the configured task hashes before starting.",UNCERTAIN_REQUEST_HELD:"A model request has an unresolved outcome. Inspect the private state before another run.",TASK_ACTIVE_OR_UNRESOLVED:"A task is running or needs inspection before another can start.",SCRIPTED_DEMO_ONLY:"The scripted exercise requires its original demo goal and files.",REVIEW_REQUIRED:"Accept a completed patch before exporting it.",RESULT_CHANGED:"The result changed. Inspect the run before recording a new review.",PATCH_CHANGED:"The patch no longer matches the recorded evidence.",ORIGINAL_SOURCE_CHANGED:"Original source changed after this run. The patch cannot be exported against that source.",SESSION_REQUIRED:"The local session changed. Reload this page.",PROJECT_SCOPE_CHANGED:"The project configuration changed. Inspect the original run scope.",WORKSPACE_ACTIVE_OR_UNRESOLVED:"A Git workspace is running or needs inspection. Its private records are preserved.",WORKSPACE_NEEDS_INSPECTION:"Inspect the existing workspace and worker log before deciding how to recover. It will not be recreated automatically.",GIT_CONTROL_FILE_REFUSED:"Git control files cannot be included in a review workspace.",WORKSPACE_BYTES_CHANGED:"Workspace files changed after verification. Inspect the workspace before continuing."};
function node(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function showError(error){$('alert').textContent=errors[error.message]||error.message.replaceAll('_',' ').toLowerCase();$('alert').hidden=false;}
function clearError(){$('alert').hidden=true;}
async function api(path,body){const options={headers:{'X-Workbench-Token':token}};if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}const r=await fetch(path,options);const value=await r.json();if(!r.ok)throw new Error(value.error||'REQUEST_REFUSED');return value;}
function stateClass(state){return state==='REVIEW_READY'?'good':['FAILED','REFUSED','UNCERTAIN','INTERRUPTED','RECOVERY_REQUIRED'].includes(state)?'bad':'';}
function projectChanged(){const p=configuration.projects.find(p=>p.id===$('project').value);if(!p)return;const demo=$('model').querySelector('option[value="scripted-demo"]');demo.disabled=!p.scripted_available;if(demo.disabled&&$('model').value==='scripted-demo')$('model').value=configuration.models[0]||'';$('goal').value=p.goal;const files=$('scope-files');files.replaceChildren(...p.files.map(name=>node('span',name+(p.editable.includes(name)?' · editable':' · protected'),'file-chip'+(p.editable.includes(name)?' editable':''))));$('scope-note').textContent=p.checks.length+' named check'+(p.checks.length===1?'':'s')+' · Edits stay in a private copy';modelChanged();}
function modelChanged(){$('goal').readOnly=$('model').value==='scripted-demo';if($('goal').readOnly){const p=configuration.projects.find(p=>p.id===$('project').value);if(p)$('goal').value=p.goal;}}
function setAdmission(reason){const blocked=Boolean(reason);$('admission').hidden=!blocked;$('admission').textContent=reason?(errors[reason]||reason.replaceAll('_',' ').toLowerCase()):'';for(const id of ['start','project','model','goal'])$(id).disabled=blocked||busy||(id==='start'&&!$('model').value);}
function renderHistory(rows){$('history-count').textContent=String(rows.length);if(!rows.length){$('history').replaceChildren(node('p','Your runs will appear here.','empty-small'));return;}$('history').replaceChildren(...rows.map(row=>{const b=node('button',undefined,'history-item'+(row.id===selected?' selected':''));b.append(node('strong',row.project_name),node('small',(friendly[row.state]||row.state)+' · '+row.id.slice(0,6)));b.addEventListener('click',()=>{selected=row.id;current=null;refresh();});return b;}));}
function renderRun(v){const changed=!current||current.id!==v.id;current=v;$('welcome').hidden=true;$('run-panel').hidden=false;$('run-project').textContent=v.project_name.toUpperCase();$('run-title').textContent='Task '+v.id.slice(0,8);$('run-meta').textContent=v.goal;$('run-state').textContent=friendly[v.state]||v.state;$('run-state').className='state-pill '+stateClass(v.state);$('stop').disabled=!['RUNNING','STOP_REQUESTED'].includes(v.state)||v.state==='STOP_REQUESTED';$('budget-label').textContent=v.turns+' / '+v.max_turns+' model turns';$('budget-bar').max=v.max_turns;$('budget-bar').value=v.turns;$('run-mode').textContent=v.backend==='scripted-demo'?'SCRIPTED · NO INFERENCE':v.model;$('plan').replaceChildren(...(v.plan.length?v.plan.map(s=>node('li',s)):[node('li','Waiting for the agent’s plan.','muted')]));$('events').replaceChildren(...v.events.map(e=>{const li=node('li');li.append(node('span',e.text),node('small','#'+String(e.index).padStart(2,'0')+' · '+e.kind.replaceAll('_',' ')));return li;}));$('activity-empty').hidden=v.events.length>0;$('diff').textContent=v.patch||'The patch will appear after the task finishes.';
  $('checks').replaceChildren(...v.checks.map(c=>{const card=node('section',undefined,'check-card');const heading=node('div',undefined,'check-heading');heading.append(node('strong',c.label),node('span',c.exit_code===0?'PASS':'FAIL','state-pill '+(c.exit_code===0?'good':'bad')));card.append(heading,node('p',(c.tests_ran||0)+' tests · exit '+c.exit_code+(c.timed_out?' · timed out':''),'muted'),node('pre',c.output||'No output','code-view'));return card;}));
  $('result-hash').textContent=v.result_sha256||'Pending';$('patch-hash').textContent=v.patch_sha256||'Pending';const ready=v.state==='REVIEW_READY'&&Boolean(v.result_sha256)&&!v.pending_events;$('accept').disabled=!ready||busy;$('reject').disabled=!ready||busy;
  if(changed)$('review-note').value=v.review?v.review.note:'';
  const accepted=v.review&&v.review.verdict==='accepted'&&v.review.result_sha256===v.result_sha256&&v.review.patch_sha256===v.patch_sha256;$('export').disabled=!ready||!accepted||busy;renderWorkspace(v,ready,accepted);$('review-status').textContent=v.review?'Review '+v.review.verdict+'. '+(accepted?'Export is ready. Source has not been changed.':'Export remains unavailable.'):'Available after a completed task and an accepted review.';setAdmission(v.admission_block);
}
async function refresh(){if(polling)return;polling=true;try{const rows=await api('/api/history');if(!initialized){selected=rows.length?rows[0].id:null;initialized=true;}renderHistory(rows);if(selected){renderRun(await api('/api/run/'+selected));}else{$('run-panel').hidden=true;$('welcome').hidden=false;const cfg=await api('/api/config');setAdmission(cfg.admission_block);}}catch(error){showError(error);}finally{polling=false;}}
async function submitReview(verdict){if(!current)return;clearError();busy=true;try{await api('/api/review',{id:current.id,result_sha256:current.result_sha256,patch_sha256:current.patch_sha256,verdict,note:$('review-note').value});await refresh();}catch(error){showError(error);}finally{busy=false;if(current)renderRun(current);}}
$('task-form').addEventListener('submit',async event=>{event.preventDefault();clearError();busy=true;setAdmission(null);try{const value=await api('/api/start',{project:$('project').value,model:$('model').value,goal:$('goal').value});selected=value.id;current=null;await refresh();}catch(error){showError(error);}finally{busy=false;await refresh();}});
$('new-task').addEventListener('click',()=>{selected=null;current=null;clearError();$('run-panel').hidden=true;$('welcome').hidden=false;$('goal').focus();refresh();});
$('project').addEventListener('change',projectChanged);$('model').addEventListener('change',modelChanged);
$('stop').addEventListener('click',async()=>{if(!current)return;clearError();try{await api('/api/stop',{id:current.id});await refresh();}catch(error){showError(error);}});
$('accept').addEventListener('click',()=>submitReview('accepted'));$('reject').addEventListener('click',()=>submitReview('rejected'));
$('export').addEventListener('click',async()=>{if(!current)return;clearError();try{const r=await fetch('/api/export/'+current.id,{headers:{'X-Workbench-Token':token}});if(!r.ok){const e=await r.json();throw new Error(e.error);}const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download='outlands-patch-'+current.id+'.diff';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){showError(error);}});
document.querySelectorAll('[data-pane]').forEach(button=>button.addEventListener('click',()=>{for(const b of document.querySelectorAll('[data-pane]')){const active=b===button;b.setAttribute('aria-selected',String(active));$(b.dataset.pane+'-pane').hidden=!active;}}));
function renderProjects(id){$('project').replaceChildren(...configuration.projects.map(p=>{const o=node('option',p.name);o.value=p.id;return o;}));if(id)$('project').value=id;projectChanged();}
async function boot(){try{configuration=await api('/api/config');const scripted=node('option','Scripted exercise · no inference');scripted.value='scripted-demo';$('model').replaceChildren(scripted,...configuration.models.map(m=>{const o=node('option',m);o.value=m;return o;}));renderProjects();$('setup-language').querySelector('option[value="java"]').disabled=!configuration.java_available;await refresh();setInterval(refresh,1500);}catch(error){showError(error);}}
boot();

function setupInvalidate(){setupDraft=null;$('setup-review').hidden=true;}
function setupLines(id){return $(id).value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);}
$('setup-open').addEventListener('click',()=>{$('setup-panel').hidden=false;$('setup-source').focus();});
$('setup-close').addEventListener('click',()=>{$('setup-panel').hidden=true;});
$('setup-form').addEventListener('input',setupInvalidate);
$('setup-language').addEventListener('change',()=>{setupInvalidate();const java=$('setup-language').value==='java';$('setup-check-label').textContent=java?'Protected test main class':'Protected test module';$('setup-check').placeholder=java?'example.ExampleTest':'test_example.py';});
$('setup-form').addEventListener('submit',async event=>{
  event.preventDefault();clearError();setupInvalidate();$('setup-preview').disabled=true;
  try{
    const scope=await api('/api/project-preview',{id:$('setup-id').value,name:$('setup-name').value,source:$('setup-source').value,language:$('setup-language').value,files:setupLines('setup-files'),editable:setupLines('setup-editable'),check:$('setup-check').value,goal:$('setup-goal').value});
    setupDraft=scope.draft;$('setup-summary').textContent=scope.name+' · '+scope.files.length+' selected files · '+scope.total_bytes+' bytes · '+scope.max_turns+' model turns';
    $('setup-scope').replaceChildren(...scope.files.map(f=>{const li=node('li');li.append(node('strong',f.path+' · '+(f.editable?'editable':'protected')),node('code',f.sha256),node('small',f.bytes+' bytes'));return li;}));
    $('setup-review').hidden=false;
  }catch(error){showError(error);}finally{$('setup-preview').disabled=false;}
});
$('setup-save').addEventListener('click',async()=>{
  if(!setupDraft)return;clearError();$('setup-save').disabled=true;
  try{const project=await api('/api/project-save',{draft:setupDraft});configuration=await api('/api/config');renderProjects(project.id);setupInvalidate();$('setup-panel').hidden=true;await refresh();}
  catch(error){showError(error);}finally{$('setup-save').disabled=false;}
});

function renderWorkspace(v,ready,accepted){
  const w=v.workspace;
  $('workspace-create').disabled=!ready||!accepted||busy||Boolean(w)||Boolean(v.admission_block);
  $('workspace-stop').disabled=!w||w.status!=='PREPARING'||!w.owned_active;
  $('workspace-state').textContent=w?(w.status==='VERIFIED'?'Checks passed':w.status==='PREPARING'?'Preparing':'Needs inspection'):'Not created';
  $('workspace-state').className='state-pill '+(w&&w.status==='VERIFIED'?'good':w&&w.status==='FAILED'?'bad':'');
  $('workspace-note').textContent=!w?'Available after an accepted patch review.':w.status==='PREPARING'?'Creating the review branch and checking the applied patch. No model inference is used.':w.status==='VERIFIED'?'Verified when created. Inspect this directory in your editor; later edits need their own checks and review.':'The operation stopped or failed. Workspace files and logs are preserved; inspect them before recovery.';
  $('workspace-details').hidden=!w||w.status!=='VERIFIED';
  $('workspace-branch').textContent=w&&w.branch||'';$('workspace-path').textContent=w&&w.path||'';$('workspace-head').textContent=w&&w.baseline_commit||'';
}
$('workspace-create').addEventListener('click',async()=>{
  if(!current)return;clearError();busy=true;renderRun(current);
  try{await api('/api/workspace',{id:current.id,result_sha256:current.result_sha256,patch_sha256:current.patch_sha256});await refresh();}
  catch(error){showError(error);}finally{busy=false;if(current)renderRun(current);}
});
$('workspace-stop').addEventListener('click',async()=>{
  if(!current)return;clearError();
  try{await api('/api/workspace-stop',{id:current.id});await refresh();}catch(error){showError(error);}
});
