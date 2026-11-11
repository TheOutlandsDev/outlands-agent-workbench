"use strict";
const token=document.querySelector('meta[name="workbench-token"]').content;
const $=id=>document.getElementById(id);
let configuration=null,selected=null,current=null,polling=false,busy=false,initialized=false,setupDraft=null;
let contextRunId=null,contextSnapshot=null;
let admissionReason=null,projectRefreshDraft=null,projectRefreshProject=null,projectRefreshBusy=false,projectRefreshSequence=0,revisionSequence=0;
const friendly={REVIEW_READY:"Ready for review",RUNNING:"Running",STOP_REQUESTED:"Stop requested",FAILED:"Failed",REFUSED:"Refused",INTERRUPTED:"Interrupted",UNCERTAIN:"Uncertain",RECOVERY_REQUIRED:"Needs inspection"};
const errors={REFRESH_FIELDS:"The refresh request did not contain the required project and default goal.",REVISION_LIMIT:"This project has reached its saved revision limit. Inspect the preserved revision chain before continuing.",REVISION_RECORD_CHANGED:"A saved revision record changed. Inspect the preserved project history before continuing.",REFRESH_SNAPSHOT_LIMIT:"The selected source exceeds the refresh snapshot size bound.",REFRESH_UTF8:"Selected source could not be read as valid UTF-8 text.",REFRESH_NO_CHANGES:"No selected file hashes or default task goal changed. There is no new revision to save.",REFRESH_SOURCE_CHANGED:"Selected source changed after the preview. Review a new refresh before saving.",PROJECT_TASK_CHANGED:"The current project task changed. Reload the project and review a new refresh.",CONFIG_CHANGED:"Project configuration changed. Reload the project and review a new refresh.",DRAFT_EXPIRED:"The reviewed draft expired. Review a new refresh before saving.",PROJECT_UNKNOWN:"The selected project is no longer available. Reload the project list.",SOURCE_HASH_CHANGED:"Source files changed. Update the configured task hashes before starting.",MODEL_REQUEST_ACTIVE:"A model request is active. Another run cannot start while this request is in progress.",UNCERTAIN_REQUEST_HELD:"A model request has an unresolved outcome. Inspect the private state before another run.",TASK_ACTIVE_OR_UNRESOLVED:"A task is running or needs inspection before another can start.",SCRIPTED_DEMO_ONLY:"The scripted exercise requires its original demo goal and files.",REVIEW_REQUIRED:"Accept a completed patch before exporting it.",RESULT_CHANGED:"The result changed. Inspect the run before recording a new review.",PATCH_CHANGED:"The patch no longer matches the recorded evidence.",ORIGINAL_SOURCE_CHANGED:"Original source changed after this run. The patch cannot be exported against that source.",SESSION_REQUIRED:"The local session changed. Reload this page.",PROJECT_SCOPE_CHANGED:"The project configuration changed. Inspect the original run scope.",WORKSPACE_ACTIVE_OR_UNRESOLVED:"A Git workspace is running or needs inspection. Its private records are preserved.",WORKSPACE_NEEDS_INSPECTION:"Inspect the existing workspace and worker log before deciding how to recover. It will not be recreated automatically.",GIT_CONTROL_FILE_REFUSED:"Git control files cannot be included in a review workspace.",WORKSPACE_BYTES_CHANGED:"Workspace files changed after verification. Inspect the workspace before continuing."};
const diagnosticStates={ACTIVE:"Request active",UNCERTAIN:"Outcome uncertain",COMPLETE:"Ready for review",FAILED:"Request failed",NOT_STARTED:"Not started",NEEDS_INSPECTION:"Needs inspection"};
const diagnosticHolds={ACTIVE_REQUEST:"A model request is active. New model work remains blocked while it is in progress.",UNRESOLVED:"A request outcome is unresolved. Inspect the preserved private state before any recovery decision.",UNASSOCIATED:"A request hold is present but cannot be linked to this run. New tasks remain blocked.",ABSENT:"No request hold is recorded."};
const diagnosticCompletion={RECORDED:"Response recorded",UNKNOWN:"Provider completion unknown",NOT_APPLICABLE:"Not applicable"};
const diagnosticPhases={PREPARE:"Preparing request",SEND:"Sending request",HEADER:"Waiting for response headers",BODY:"Reading response body",VALIDATE:"Validating response",COMPLETE:"Complete",UNKNOWN:"Not recorded"};
const diagnosticStatuses={ACTIVE:"Active",RECORDED:"Recorded",ERROR:"Error",INTERRUPTED:"Interrupted",UNKNOWN:"Not recorded"};
const diagnosticCategories={TIMEOUT:"Timeout",CONNECTION:"Connection error",HTTP_PROTOCOL:"HTTP or protocol error",REFUSED:"Request refused",OS_ERROR:"Operating system error",EXECUTION:"Execution error",INTERRUPTED:"Interrupted"};
const diagnosticReasons={EXECUTION_ERROR:"The request could not finish executing.",PLAN_REQUIRED:"The model did not provide the required plan.",PROVIDER_SEND_TIMEOUT:"The configured timeout expired while sending the request.",PROVIDER_HEADER_TIMEOUT:"The configured timeout expired while waiting for response headers.",PROVIDER_BODY_TIMEOUT:"The configured timeout expired while reading the response body.",PROVIDER_HTTP:"The provider returned an HTTP error.",PROVIDER_INCOMPLETE:"The provider response was incomplete.",REQUEST_SIZE_LIMIT:"The serialized request exceeded the request-size ceiling. This chat request was not sent.",RESPONSE_LIMIT:"The response exceeded the configured size limit.",JSON_LIMIT:"The JSON response exceeded a configured parsing limit.",INVALID_JSON:"The response did not contain valid JSON.",DUPLICATE_JSON_KEY:"The JSON response contained a duplicate key.",JSON_CONSTANT:"The JSON response contained an unsupported constant.",MODEL_MESSAGE:"The model response did not meet the required message format.",MODEL_CONTENT:"The model response did not meet the required content format.",MODEL_CALL:"The model supplied an invalid tool call.",ONE_TOOL_PER_TURN:"The model supplied more than one tool call in a turn.",UNKNOWN_TOOL:"The model requested an unsupported tool.",FINAL_REQUIRED:"The model did not provide the required final response.",FINAL_CHECKS_FAILED:"The final checks failed.",CHECK_EXECUTION_FAILED:"A configured check could not complete.",OWNER_INTERRUPT:"The owner requested interruption.",TURN_BUDGET_EXHAUSTED:"The model request budget was exhausted.",SESSION_TIME_LIMIT:"The task reached its configured time limit.",CONTEXT_LIMIT:"The task reached its configured context limit.",CONTEXT_QUERY:"The source search query did not meet the literal-query requirements.",CONTEXT_FILES:"The source search did not name a valid selected file set.",CONTEXT_PATH:"The source tool did not name a valid declared path.",CONTEXT_SNAPSHOT_LIMIT:"The selected source snapshot exceeded its size bound.",CONTEXT_UTF8:"The selected source could not be read as valid UTF-8 text.",CONTEXT_RANGE:"The focused read requested an invalid or excessive line range.",CHECKS_PASSED:"The recorded checks passed.",STALE_EDIT_HASH:"The file changed since it was read. Read it again before editing.",SOURCE_HASH_CHANGED:"The selected source hashes changed.",ORIGINAL_SOURCE_CHANGED:"Original source changed after the run."};
const diagnosticNotes={LEGACY_REQUEST_DETAILS:"This older run has no detailed request measurements. Missing values are shown as Not recorded.",INVALID_DIAGNOSTICS:"Some diagnostic records need inspection. Missing details have not been reconstructed.",EVENT_LIMIT:"The diagnostic event limit was reached; the request list may be incomplete.",PROVIDER_COMPLETION_UNKNOWN:"Provider completion is unknown. A timeout or interruption does not establish whether the provider completed the request.",HOLD_RETAINED:"The request hold remains in place. These observations do not authorize clearing it.",HOLD_UNASSOCIATED:"A request hold is present but cannot be linked to this run. New tasks remain blocked.",REQUEST_ACTIVE:"A model request is active. Its final outcome has not been recorded.",REQUEST_SIZE_REFUSED:"This chat request was not sent; no new hold was created. Prior requests remain recorded, and any existing hold retains its separately recorded status.",SCRIPTED_NO_INFERENCE:"This scripted exercise did not use model inference.",UNRECOGNIZED_REASON:"The private record contains a reason that cannot be shown here. Inspect the preserved records.",MISSING_REQUEST_FINISH:"A request start has no matching finish record. Its outcome needs inspection."};
function node(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function diagnosticText(labels,value){return typeof value==='string'&&Object.prototype.hasOwnProperty.call(labels,value)?labels[value]:null;}
function diagnosticInteger(value){return Number.isSafeInteger(value)&&value>=0?value.toLocaleString('en-US'):'Not recorded';}
function diagnosticElapsed(value){return Number.isSafeInteger(value)&&value>=0?(value/1000).toLocaleString('en-US',{maximumFractionDigits:3})+' s':'Not recorded';}
function diagnosticTimeout(value){const text=diagnosticInteger(value);return text==='Not recorded'?text:text+' s';}
function diagnosticBytes(value){const text=diagnosticInteger(value);return text==='Not recorded'?text:text+' bytes';}
function diagnosticStarted(value){if(!Number.isSafeInteger(value)||value<0)return 'Not recorded';const date=new Date(value);return Number.isNaN(date.getTime())?'Not recorded':date.toISOString().replace('T',' ').replace('Z',' UTC');}
function diagnosticList(rows,className){const list=node('dl',undefined,className||'diagnostic-facts');for(const [label,value] of rows){const pair=node('div');pair.append(node('dt',label),node('dd',value));list.append(pair);}return list;}
function requestSizePreflight(v){const preflight=v.diagnostics&&v.diagnostics.preflight;return preflight&&preflight.reason==='REQUEST_SIZE_LIMIT'?preflight:null;}
function renderDiagnostics(v){
  const d=v.diagnostics;
  const container=$('diagnostics');
  const sameRun=container.dataset.runId===v.id;
  const openMetrics=new Set([...container.querySelectorAll('details[open]')].map(details=>details.dataset.requestIndex));
  container.dataset.runId=v.id;
  if(!d||d.version!==1){
    $('diagnostics-summary-state').textContent='Not recorded';
    $('diagnostics-summary-state').className='state-pill';
    $('diagnostics-summary-text').textContent='Detailed request timing, phase and provider completion are not recorded for this run.';
    container.replaceChildren(node('p','Diagnostics are not recorded for this run. No timing, byte counts or provider outcome have been reconstructed.','muted'));
    return;
  }
  const preflight=requestSizePreflight(v);
  const state=preflight?'Chat request not sent':diagnosticText(diagnosticStates,d.state)||'Needs inspection';
  const completion=diagnosticText(diagnosticCompletion,d.provider_completion)||'Not recorded';
  const hold=diagnosticText(diagnosticHolds,d.hold)||'The request hold status is not recorded.';
  const reason=diagnosticText(diagnosticReasons,d.reason);
  $('diagnostics-summary-state').textContent=state;
  $('diagnostics-summary-state').className='state-pill '+(preflight||['UNCERTAIN','FAILED','NEEDS_INSPECTION'].includes(d.state)?'bad':'');
  const outcome=preflight?'Serialized request: '+diagnosticBytes(preflight.request_bytes)+'; ceiling: '+diagnosticBytes(preflight.limit_bytes)+'. This chat request was not sent.':d.provider_completion==='UNKNOWN'?'Provider completion is unknown; a missing response does not prove the provider stopped.':completion+'.';
  $('diagnostics-summary-text').textContent=(preflight?[outcome,hold]:[reason,hold,outcome]).filter(Boolean).join(' ');
  const budget=d.budget||{};
  const used=budget.used;
  const budgetText=Number.isSafeInteger(used)&&used>=0&&Number.isSafeInteger(budget.limit)&&budget.limit>=0?diagnosticInteger(used)+' / '+diagnosticInteger(budget.limit)+' requests / turns':'Not recorded';
  const requests=Array.isArray(d.requests)?d.requests.filter(request=>request&&typeof request==='object'):[];
  const facts=diagnosticList([['Run diagnostic state',state],['Request hold',d.hold==='ACTIVE_REQUEST'?'Active request':d.hold==='UNRESOLVED'?'Unresolved':d.hold==='UNASSOCIATED'?'Present, unassociated':d.hold==='ABSENT'?'Absent':'Not recorded'],[preflight&&requests.length?'Latest attempted request':'Provider completion',completion],['Model request budget',budgetText],['Configured request timeout',diagnosticTimeout(budget.per_request_seconds)]]);
  const children=[facts];
  if(preflight){
    const card=node('section',undefined,'diagnostic-preflight');
    card.append(node('h3','Request-size preflight'),diagnosticList([['Serialized request',diagnosticBytes(preflight.request_bytes)],['Request-size ceiling',diagnosticBytes(preflight.limit_bytes)],['Chat request sent',preflight.chat_request_sent===false?'No':'Not recorded'],['New hold from this refusal',preflight.new_hold_created===false?'No':'Not recorded']]));
    children.push(card);
  }
  if(reason&&!preflight)children.push(node('p','Recorded reason: '+reason,'diagnostic-reason'));
  const notes=Array.isArray(d.notes)?d.notes:[];
  const noteTexts=[...new Set(notes.map(code=>diagnosticText(diagnosticNotes,code)).filter(Boolean))];
  if(preflight&&!notes.includes('REQUEST_SIZE_REFUSED'))noteTexts.push(diagnosticNotes.REQUEST_SIZE_REFUSED);
  if(d.legacy&&!notes.includes('LEGACY_REQUEST_DETAILS'))noteTexts.unshift(diagnosticNotes.LEGACY_REQUEST_DETAILS);
  if(noteTexts.length){const list=node('ul',undefined,'diagnostic-notes');list.append(...noteTexts.map(text=>node('li',text)));children.push(list);}
  children.push(node('h3','Model requests','diagnostic-requests-title'));
  if(!requests.length){
    children.push(node('p',preflight?'No chat request was sent for this refused candidate.':d.state==='NOT_STARTED'?'No model request has started.':d.legacy?'Detailed request entries were not recorded for this older run.':'No detailed request entries are recorded.','muted'));
  }else{
    const list=node('ol',undefined,'diagnostic-requests');
    for(const [index,request] of requests.entries()){
      const card=node('li',undefined,'diagnostic-request');
      const heading=node('div',undefined,'diagnostic-request-heading');
      const turn=diagnosticInteger(request.turn);
      heading.append(node('h4',turn==='Not recorded'?'Turn not recorded':'Turn '+turn),node('span',diagnosticText(diagnosticStatuses,request.status)||'Not recorded','state-pill '+(['ERROR','INTERRUPTED'].includes(request.status)?'bad':'')));
      card.append(heading,diagnosticList([['Phase',diagnosticText(diagnosticPhases,request.phase)||'Not recorded'],['Elapsed',diagnosticElapsed(request.elapsed_ms)],['Configured timeout',diagnosticTimeout(request.timeout_seconds)],['Request size',diagnosticBytes(request.request_bytes)],['Started (UTC)',diagnosticStarted(request.started_at_ms)],['Provider completion',diagnosticText(diagnosticCompletion,request.provider_completion)||'Not recorded']]));
      const category=diagnosticText(diagnosticCategories,request.error_category);
      const requestReason=diagnosticText(diagnosticReasons,request.reason);
      if(category)card.append(node('p','Error category: '+category,'diagnostic-category'));
      if(requestReason)card.append(node('p','Reason: '+requestReason,'diagnostic-reason'));
      const metrics=request.metrics||{};
      const countRows=[['Provider prompt count',metrics.prompt_eval_count],['Provider output count',metrics.eval_count]].filter(([,value])=>typeof value==='number'&&Number.isFinite(value)&&value>=0).map(([label,value])=>[label,String(value)]);
      if(countRows.length){const details=node('details',undefined,'diagnostic-metrics');details.dataset.requestIndex=String(index);details.open=sameRun&&openMetrics.has(String(index));details.append(node('summary','Local provider counts'),node('p','Optional provider observations, separate from the model request budget.','muted'),diagnosticList(countRows));card.append(details);}
      list.append(card);
    }
    children.push(list);
  }
  container.replaceChildren(...children);
}
function contextRange(start,end){return Number.isSafeInteger(start)&&start>0&&Number.isSafeInteger(end)&&end>=start?'Lines '+diagnosticInteger(start)+'–'+diagnosticInteger(end):'No lines returned';}
function contextHash(path,sha256){return diagnosticList([['Selected file',typeof path==='string'?path:'Not recorded'],['SHA-256',typeof sha256==='string'?sha256:'Not recorded']],'context-file-facts');}
function contextExcerpt(lines,key){const excerpt=node('pre',lines.join('\n'),'code-view context-excerpt');excerpt.dataset.contextKey=key;return excerpt;}
function renderContext(v){
  const container=$('context-results');
  const entries=Array.isArray(v.context)?v.context.filter(entry=>entry&&['search_text','read_lines'].includes(entry.kind)&&entry.result&&typeof entry.result==='object').slice(-8):[];
  const snapshot=JSON.stringify(entries);
  if(contextRunId===v.id&&contextSnapshot===snapshot)return;
  const positions=contextRunId===v.id?new Map([...container.querySelectorAll('[data-context-key]')].map(excerpt=>[excerpt.dataset.contextKey,{top:excerpt.scrollTop,left:excerpt.scrollLeft}])):new Map();
  contextRunId=v.id;contextSnapshot=snapshot;
  if(!entries.length){container.replaceChildren(node('p','No search or focused-read results are recorded for this run. Older runs may not include source context.','muted context-empty'));return;}
  const list=node('ol',undefined,'context-results');
  for(const [position,entry] of entries.entries()){
    const result=entry.result;
    const card=node('li',undefined,'context-card');
    const heading=node('div',undefined,'context-heading');
    const resultIndex=diagnosticInteger(entry.index);
    heading.append(node('h4',entry.kind==='search_text'?'Project search':'Focused read'),node('span',resultIndex==='Not recorded'?'Tool result':'Tool result #'+resultIndex,'muted'));
    card.append(heading);
    const key=(resultIndex==='Not recorded'?'position:'+position:'index:'+String(entry.index))+':'+entry.kind;
    if(entry.kind==='search_text'){
      card.append(node('p','Query: '+(typeof result.query==='string'?result.query:'Not recorded'),'context-query'),diagnosticList([['Selected files searched',diagnosticInteger(result.files_searched)],['Matches found',diagnosticInteger(result.total_matches)],['Match ceiling',diagnosticInteger(result.limit)],['Tool output ceiling',diagnosticBytes(result.byte_limit)]],'context-facts'));
      if(result.truncated)card.append(node('p','Search results are incomplete. A match or output limit was reached; more matches may exist.','context-notice'));
      const matches=Array.isArray(result.matches)?result.matches:[];
      if(!matches.length)card.append(node('p',result.truncated?'No match excerpts were returned within the output limit.':'No matches were returned.','muted'));
      const fileGroups=new Map();
      for(const [matchIndex,match] of matches.entries()){
        if(!match||typeof match!=='object')continue;
        const fileKey=JSON.stringify([match.path,match.sha256]);
        let matchCard=fileGroups.get(fileKey);
        if(!matchCard){matchCard=node('section',undefined,'context-match');matchCard.append(contextHash(match.path,match.sha256));fileGroups.set(fileKey,matchCard);card.append(matchCard);}
        const hit=node('div',undefined,'context-hit');
        const line=diagnosticInteger(match.line_number),column=diagnosticInteger(match.column);
        hit.append(node('p','Line '+line+' · column '+column,'context-location'),contextExcerpt([line+' | '+(typeof match.text==='string'?match.text:'')],key+':'+matchIndex));
        if(match.truncated)hit.append(node('p','This matching line is truncated; the full line is not shown.','context-notice'));
        matchCard.append(hit);
      }
    }else{
      card.append(contextHash(result.path,result.sha256),diagnosticList([['Requested range',contextRange(result.requested_start,result.requested_end)],['Returned range',contextRange(result.start_line,result.end_line)],['Total source lines',diagnosticInteger(result.total_lines)],['Tool output ceiling',diagnosticBytes(result.byte_limit)]],'context-facts'));
      if(result.truncated)card.append(node('p','Read excerpt is incomplete. An output or line limit was reached.','context-notice'));
      const lines=Array.isArray(result.lines)?result.lines.filter(line=>line&&typeof line==='object'):[];
      if(lines.length)card.append(contextExcerpt(lines.map(line=>diagnosticInteger(line.line_number)+' | '+(typeof line.text==='string'?line.text:'')+(line.truncated?'  [line truncated]':'')),key));
      else card.append(node('p','No source lines were returned.','muted'));
      if(lines.some(line=>line.truncated))card.append(node('p','Marked lines are truncated; their full contents are not shown.','context-notice'));
      card.append(node('p',result.end_of_file===true?'End of file reached.':result.end_of_file===false?'This excerpt does not reach the end of the file.':'End-of-file status was not recorded.','muted context-end'));
    }
    list.append(card);
  }
  container.replaceChildren(list);
  for(const excerpt of container.querySelectorAll('[data-context-key]')){const position=positions.get(excerpt.dataset.contextKey);if(position){excerpt.scrollTop=position.top;excerpt.scrollLeft=position.left;}}
}
function showError(error){$('alert').textContent=errors[error.message]||error.message.replaceAll('_',' ').toLowerCase();$('alert').hidden=false;}
function clearError(){$('alert').hidden=true;}
async function api(path,body){const options={headers:{'X-Workbench-Token':token}};if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}const r=await fetch(path,options);const value=await r.json();if(!r.ok)throw new Error(value.error||'REQUEST_REFUSED');return value;}
function stateClass(state){return state==='REVIEW_READY'?'good':['FAILED','REFUSED','UNCERTAIN','INTERRUPTED','RECOVERY_REQUIRED'].includes(state)?'bad':'';}
function projectChanged(){const p=configuration.projects.find(p=>p.id===$('project').value);if(!p)return;const demo=$('model').querySelector('option[value="scripted-demo"]');demo.disabled=!p.scripted_available;if(demo.disabled&&$('model').value==='scripted-demo')$('model').value=configuration.models[0]||'';$('goal').value=p.goal;const files=$('scope-files');files.replaceChildren(...p.files.map(name=>node('span',name+(p.editable.includes(name)?' · editable':' · protected'),'file-chip'+(p.editable.includes(name)?' editable':''))));$('scope-note').textContent=p.checks.length+' named check'+(p.checks.length===1?'':'s')+' · Edits stay in a private copy';modelChanged();resetProjectRefresh(p);}
function modelChanged(){$('goal').readOnly=$('model').value==='scripted-demo';if($('goal').readOnly){const p=configuration.projects.find(p=>p.id===$('project').value);if(p)$('goal').value=p.goal;}}
function setAdmission(reason){const blocked=Boolean(reason);if(blocked&&admissionReason!==reason)invalidateProjectRefresh();admissionReason=reason||null;$('admission').hidden=!blocked;$('admission').textContent=reason?(errors[reason]||reason.replaceAll('_',' ').toLowerCase()):'';for(const id of ['start','project','model','goal'])$(id).disabled=blocked||busy||projectRefreshBusy||(id==='start'&&!$('model').value);setProjectRefreshControls();}
function renderHistory(rows){$('history-count').textContent=String(rows.length);if(!rows.length){$('history').replaceChildren(node('p','Your runs will appear here.','empty-small'));return;}$('history').replaceChildren(...rows.map(row=>{const b=node('button',undefined,'history-item'+(row.id===selected?' selected':''));b.append(node('strong',row.project_name),node('small',(friendly[row.state]||row.state)+' · '+row.id.slice(0,6)));b.addEventListener('click',()=>{selected=row.id;current=null;refresh();});return b;}));}
function renderRun(v){const changed=!current||current.id!==v.id;current=v;$('welcome').hidden=true;$('run-panel').hidden=false;$('run-project').textContent=v.project_name.toUpperCase();$('run-title').textContent='Task '+v.id.slice(0,8);$('run-meta').textContent=v.goal;$('run-state').textContent=friendly[v.state]||v.state;$('run-state').className='state-pill '+stateClass(v.state);$('stop').disabled=!['RUNNING','STOP_REQUESTED'].includes(v.state)||v.state==='STOP_REQUESTED';$('budget-label').textContent=v.turns+' / '+v.max_turns+' model turns';$('budget-bar').max=v.max_turns;$('budget-bar').value=v.turns;$('run-mode').textContent=v.backend==='scripted-demo'?'SCRIPTED · NO INFERENCE':v.model;renderDiagnostics(v);renderContext(v);$('plan').replaceChildren(...(v.plan.length?v.plan.map(s=>node('li',s)):[node('li','Waiting for the agent’s plan.','muted')]));$('events').replaceChildren(...v.events.map(e=>{const li=node('li');li.append(node('span',e.text),node('small','#'+String(e.index).padStart(2,'0')+' · '+e.kind.replaceAll('_',' ')));return li;}));$('activity-empty').hidden=v.events.length>0;$('diff').textContent=v.patch||'The patch will appear after the task finishes.';
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
function activatePane(button){for(const b of document.querySelectorAll('[data-pane]')){const active=b===button;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;$(b.dataset.pane+'-pane').hidden=!active;}}
document.querySelectorAll('[data-pane]').forEach(button=>{button.addEventListener('click',()=>activatePane(button));button.addEventListener('keydown',event=>{const tabs=[...document.querySelectorAll('[data-pane]')];const index=tabs.indexOf(button);let next;if(event.key==='ArrowRight')next=tabs[(index+1)%tabs.length];else if(event.key==='ArrowLeft')next=tabs[(index+tabs.length-1)%tabs.length];else if(event.key==='Home')next=tabs[0];else if(event.key==='End')next=tabs[tabs.length-1];if(next){event.preventDefault();activatePane(next);next.focus();}});});
function renderProjects(id){$('project').replaceChildren(...configuration.projects.map(p=>{const o=node('option',p.name);o.value=p.id;return o;}));if(id)$('project').value=id;projectChanged();}
async function boot(){try{configuration=await api('/api/config');const scripted=node('option','Scripted exercise · no inference');scripted.value='scripted-demo';$('model').replaceChildren(scripted,...configuration.models.map(m=>{const o=node('option',m);o.value=m;return o;}));renderProjects();setAdmission(configuration.admission_block);$('setup-language').querySelector('option[value="java"]').disabled=!configuration.java_available;await refresh();setInterval(refresh,1500);}catch(error){showError(error);}}
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

function selectedProjectConfiguration(){return configuration&&configuration.projects.find(project=>project.id===$('project').value);}
function invalidateProjectRefresh(){projectRefreshDraft=null;projectRefreshSequence++;$('refresh-review').hidden=true;}
function setProjectRefreshStatus(text){$('refresh-status').textContent=text||'';$('refresh-status').hidden=!text;}
function setProjectRefreshControls(){
  const project=selectedProjectConfiguration();
  const blocked=Boolean(admissionReason);
  const disabled=!project||blocked||busy||projectRefreshBusy;
  $('refresh-open').disabled=!project||projectRefreshBusy;
  $('refresh-close').disabled=projectRefreshBusy;
  $('refresh-goal').disabled=disabled;
  $('refresh-preview').disabled=disabled||!$('refresh-goal').value.trim();
  $('refresh-save').disabled=disabled||!projectRefreshDraft||projectRefreshDraft.project!==project.id||projectRefreshDraft.goal!==$('refresh-goal').value;
  $('refresh-admission').hidden=!blocked;
  $('refresh-admission').textContent=blocked?(errors[admissionReason]||'New project revisions are currently blocked.')+' Revision history remains available.':'';
}
function renderRefreshChecks(container,checks){
  const rows=Array.isArray(checks)?checks.map(value=>[typeof value==='string'?value:'Check',typeof value==='string'?null:value]):checks&&typeof checks==='object'?Object.entries(checks):[];
  container.replaceChildren(...(rows.length?rows.map(([name,command])=>{const item=node('li');item.append(node('strong',name));if(command!==null)item.append(node('code',typeof command==='string'?command:JSON.stringify(command)));return item;}):[node('li','No checks recorded.','muted')]));
}
function resetProjectRefresh(project){
  invalidateProjectRefresh();revisionSequence++;
  projectRefreshProject=project.id;
  $('refresh-project-name').textContent=project.name+' · '+project.id;
  $('refresh-goal').value=project.goal;
  $('refresh-current-hash').textContent=project.task_sha256||'Not recorded';
  $('refresh-files').replaceChildren(...project.files.map(path=>node('span',path+' · '+(project.editable.includes(path)?'editable':'protected'),'file-chip'+(project.editable.includes(path)?' editable':''))));
  renderRefreshChecks($('refresh-checks'),project.checks);
  $('revision-history').replaceChildren(node('p','Open refresh to load revision history.','muted'));
  $('revision-history-limit').textContent='Read-only history';
  $('revision-history-truncated').hidden=true;
  setProjectRefreshStatus('');setProjectRefreshControls();
  if(!$('refresh-panel').hidden)loadProjectRevisions(project.id);
}
async function loadProjectRevisions(projectId){
  const sequence=++revisionSequence;
  $('revision-history').replaceChildren(node('p','Loading saved revisions…','muted'));
  try{
    const history=await api('/api/project-revisions/'+encodeURIComponent(projectId));
    if(sequence!==revisionSequence||projectRefreshProject!==projectId)return;
    $('refresh-current-hash').textContent=history.task_sha256||'Not recorded';
    $('revision-history-limit').textContent='Up to '+diagnosticInteger(history.limit)+' saved revisions';
    $('revision-history-truncated').hidden=!history.truncated;
    const revisions=Array.isArray(history.revisions)?history.revisions:[];
    if(!revisions.length){$('revision-history').replaceChildren(node('p','No saved revisions.','muted'));return;}
    const list=node('ol',undefined,'revision-list');
    for(const revision of revisions){
      const card=node('li',undefined,'revision-card');
      const heading=node('div',undefined,'revision-heading');
      heading.append(node('h4',revision.id));
      if(revision.current)heading.append(node('span','Current','state-pill good'));
      card.append(heading,diagnosticList([['Saved (UTC)',diagnosticStarted(revision.created*1000)],['Changed file hashes',diagnosticInteger(revision.files_changed)],['Default goal changed',revision.goal_changed===true?'Yes':revision.goal_changed===false?'No':'Not recorded']]),diagnosticList([['Parent task SHA-256',revision.parent_task_sha256||'Not recorded'],['Task SHA-256',revision.task_sha256||'Not recorded']],'context-file-facts revision-hashes'));
      list.append(card);
    }
    $('revision-history').replaceChildren(list);
  }catch(error){
    if(sequence!==revisionSequence||projectRefreshProject!==projectId)return;
    $('refresh-current-hash').textContent='Unavailable · project state needs inspection';
    invalidateProjectRefresh();setProjectRefreshControls();
    $('revision-history').replaceChildren(node('p',errors[error.message]||'Revision history could not be loaded. Inspect the private project records.','muted'));
    $('revision-history-limit').textContent='History unavailable';
    $('revision-history-truncated').hidden=true;
  }
}
function renderProjectRefreshPreview(scope){
  const files=Array.isArray(scope.files)?scope.files:[];
  $('refresh-summary').textContent=diagnosticInteger(scope.files_changed)+' selected file hashes changed · Default goal '+(scope.goal_changed?'changed':'unchanged')+' · '+diagnosticInteger(files.length)+' selected files · '+diagnosticBytes(scope.total_bytes);
  $('refresh-review-facts').replaceChildren(diagnosticList([['Parent task SHA-256',scope.parent_task_sha256],['New task SHA-256',scope.task_sha256]],'context-file-facts refresh-task-hashes'),node('h3','Reviewed default goal'),node('pre',scope.goal,'refresh-reviewed-goal'),diagnosticList([['Model-turn limit',diagnosticInteger(scope.max_turns)],['Per-request timeout',diagnosticTimeout(scope.request_seconds)]],'diagnostic-facts refresh-budget'));
  $('refresh-scope').replaceChildren(...files.map(file=>{
    const item=node('li');
    const heading=node('div',undefined,'refresh-file-heading');
    heading.append(node('strong',file.path+' · '+(file.editable?'editable':'protected')),node('span',file.changed?'Hash changed':'Unchanged','state-pill'+(file.changed?'':' good')));
    item.append(heading,diagnosticList([['Configured SHA-256',file.old_sha256],['Current source SHA-256',file.sha256],['Current source size',diagnosticBytes(file.bytes)]],'context-file-facts'));
    return item;
  }));
  renderRefreshChecks($('refresh-review-checks'),scope.checks);
  $('refresh-review').hidden=false;
}
$('refresh-open').addEventListener('click',()=>{
  const project=selectedProjectConfiguration();if(!project||projectRefreshBusy)return;
  clearError();$('refresh-panel').hidden=false;$('refresh-open').setAttribute('aria-expanded','true');resetProjectRefresh(project);
  if(!$('refresh-goal').disabled)$('refresh-goal').focus();
});
$('refresh-close').addEventListener('click',()=>{
  if(projectRefreshBusy)return;invalidateProjectRefresh();revisionSequence++;$('refresh-panel').hidden=true;$('refresh-open').setAttribute('aria-expanded','false');setProjectRefreshControls();$('refresh-open').focus();
});
$('refresh-goal').addEventListener('input',()=>{invalidateProjectRefresh();setProjectRefreshStatus('');setProjectRefreshControls();});
$('refresh-form').addEventListener('submit',async event=>{
  event.preventDefault();const project=selectedProjectConfiguration();if(!project||admissionReason||busy||projectRefreshBusy)return;
  clearError();invalidateProjectRefresh();setProjectRefreshStatus('');
  const sequence=projectRefreshSequence,projectId=project.id,goal=$('refresh-goal').value;
  projectRefreshBusy=true;setAdmission(admissionReason);
  try{
    const scope=await api('/api/project-refresh-preview',{project:projectId,goal});
    if(sequence!==projectRefreshSequence||projectRefreshProject!==projectId||$('project').value!==projectId||$('refresh-goal').value!==goal||admissionReason||$('refresh-panel').hidden)return;
    projectRefreshDraft={draft:scope.draft,project:projectId,goal};renderProjectRefreshPreview(scope);
  }catch(error){if(sequence===projectRefreshSequence){invalidateProjectRefresh();showError(error);}}
  finally{projectRefreshBusy=false;setAdmission(admissionReason);}
});
$('refresh-save').addEventListener('click',async()=>{
  const draft=projectRefreshDraft;
  if(!draft||admissionReason||busy||projectRefreshBusy||draft.project!==$('project').value||draft.goal!==$('refresh-goal').value)return;
  clearError();projectRefreshBusy=true;setAdmission(admissionReason);
  let saved=false;
  try{
    const result=await api('/api/project-refresh-save',{draft:draft.draft});saved=true;invalidateProjectRefresh();
    setProjectRefreshStatus('Task revision '+result.revision+' saved. No inference started and no source files were written.');
    configuration=await api('/api/config');renderProjects(result.id);setAdmission(configuration.admission_block);
    setProjectRefreshStatus('Task revision '+result.revision+' saved. No inference started and no source files were written.');
  }catch(error){invalidateProjectRefresh();showError(error);if(saved)setProjectRefreshStatus('The task revision was saved. Reload the page to load the current project configuration.');}
  finally{projectRefreshBusy=false;setAdmission(admissionReason);}
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
