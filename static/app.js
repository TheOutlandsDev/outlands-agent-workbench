"use strict";
const token=document.querySelector('meta[name="workbench-token"]').content;
const $=id=>document.getElementById(id);
let configuration=null,selected=null,current=null,polling=false,busy=false,initialized=false,setupDraft=null;
let contextRunId=null,contextSnapshot=null;
let comparisonOpen=false,comparisonOpening=false,comparisonBusy=false,comparisonHistoryLoading=false,comparisonSequence=0,comparisonHistorySequence=0,comparisonLeftId="",comparisonRightId="",normalRefreshInFlight=Promise.resolve(),comparisonHistoryReady=false,comparisonOpeningCancel=null,comparisonOpenSequence=0;
let readinessOpen=false,readinessOpening=false,readinessReady=false,readinessBusy=false,readinessProjectId="",readinessSequence=0,readinessOpenSequence=0,readinessOpeningCancel=null;
let bundleOpen=false,bundleOpening=false,bundleBusy=false,bundleRunId=null,bundlePreview=null,bundleSequence=0,bundleOpenSequence=0,bundleOpeningCancel=null;
let projectCheckOpen=false,projectCheckOpening=false,projectCheckReady=false,projectCheckBusy=false,projectCheckProjectId="",projectCheckSequence=0,projectCheckOpenSequence=0,projectCheckOpeningCancel=null;
let bundleWorkspaceOpen=false,bundleWorkspaceOpening=false,bundleWorkspaceReady=false,bundleWorkspacePreviewBusy=false,bundleWorkspaceActionBusy=false,bundleWorkspaceProjectId="",bundleWorkspacePreview=null,bundleWorkspacePreviewSequence=0,bundleWorkspaceOpenSequence=0,bundleWorkspaceOpeningCancel=null,bundleWorkspaceExpiryTimer=null,bundleWorkspacePollTimer=null,bundleWorkspaceHistoryReady=false,bundleWorkspaceHistoryBusy=false,bundleWorkspaceHistorySequence=0,bundleWorkspaceReceiptSequence=0,bundleWorkspaceSelectedId="",bundleWorkspaceReceipts=[],bundleWorkspaceReceipt=null,bundleWorkspaceUncertainCreation=false;
let workspaceRecheckContextSequence=0,workspaceRecheckUncertainWorkspaceId="",workspaceRecheckWorkspaceId="",workspaceRecheckPreview=null,workspaceRecheckPreviewBusy=false,workspaceRecheckPreviewSequence=0,workspaceRecheckExpiryTimer=null,workspaceRecheckHistoryReady=false,workspaceRecheckHistoryBusy=false,workspaceRecheckHistorySequence=0,workspaceRecheckHistorySha=null,workspaceRecheckReceipts=[],workspaceRecheckSelectedId="",workspaceRecheckReceipt=null,workspaceRecheckReceiptSequence=0,workspaceRecheckPollTimer=null,workspaceRecheckUncertainStart=false;
const workspaceRecheckKnown=new Map();
let admissionReason=null,projectRefreshDraft=null,projectRefreshProject=null,projectRefreshBusy=false,projectRefreshSequence=0,revisionSequence=0;
const friendly={REVIEW_READY:"Ready for review",RUNNING:"Running",STOP_REQUESTED:"Stop requested",FAILED:"Failed",REFUSED:"Refused",INTERRUPTED:"Interrupted",UNCERTAIN:"Uncertain",RECOVERY_REQUIRED:"Needs inspection"};
const errors={RECHECK_ACTIVE_OR_UNRESOLVED:"A workspace recheck is active or unresolved. Inspect its retained private records before new execution.",RECHECK_NEEDS_INSPECTION:"Saved workspace recheck records need inspection before new execution.",BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED:"A bundle review workspace is active or unresolved. Inspect its retained private records before another run.",BUNDLE_WORKSPACE_NEEDS_INSPECTION:"Saved bundle workspace records need inspection. No new workspace will be created automatically.",READINESS_PROJECT_UNKNOWN:"The selected configured project is unavailable. Inspect the private project configuration.",READINESS_OUTPUT_LIMIT:"The static readiness report exceeds its bounded response size. Inspect the private project records.",COMPARE_IDS:"Choose two different saved runs.",COMPARE_RUN_UNKNOWN:"A selected saved run is unavailable. Choose another saved run.",COMPARE_STORE_REFUSED:"Saved run records could not be read safely. Inspect the private data store.",COMPARE_RECORD_LIMIT:"The saved comparison records exceed a read limit. Inspect the private records.",COMPARE_OUTPUT_LIMIT:"The saved comparison exceeds the bounded response size. Inspect the private records.",REFRESH_FIELDS:"The refresh request did not contain the required project and default goal.",REVISION_LIMIT:"This project has reached its saved revision limit. Inspect the preserved revision chain before continuing.",REVISION_RECORD_CHANGED:"A saved revision record changed. Inspect the preserved project history before continuing.",REFRESH_SNAPSHOT_LIMIT:"The selected source exceeds the refresh snapshot size bound.",REFRESH_UTF8:"Selected source could not be read as valid UTF-8 text.",REFRESH_NO_CHANGES:"No selected file hashes or default task goal changed. There is no new revision to save.",REFRESH_SOURCE_CHANGED:"Selected source changed after the preview. Review a new refresh before saving.",PROJECT_TASK_CHANGED:"The current project task changed. Reload the project and review a new refresh.",CONFIG_CHANGED:"Project configuration changed. Reload the project and review a new refresh.",DRAFT_EXPIRED:"The reviewed draft expired. Review a new refresh before saving.",PROJECT_UNKNOWN:"The selected project is no longer available. Reload the project list.",SOURCE_HASH_CHANGED:"Source files changed. Update the configured task hashes before starting.",MODEL_REQUEST_ACTIVE:"A model request is active. Another run cannot start while this request is in progress.",UNCERTAIN_REQUEST_HELD:"A model request has an unresolved outcome. Inspect the private state before another run.",TASK_ACTIVE_OR_UNRESOLVED:"A task is running or needs inspection before another can start.",SCRIPTED_DEMO_ONLY:"The scripted exercise requires its original demo goal and files.",REVIEW_REQUIRED:"Accept a completed patch before exporting it.",RESULT_CHANGED:"The result changed. Inspect the run before recording a new review.",PATCH_CHANGED:"The patch no longer matches the recorded evidence.",ORIGINAL_SOURCE_CHANGED:"Original source changed after this run. The patch cannot be exported against that source.",SESSION_REQUIRED:"The local session changed. Reload this page.",PROJECT_SCOPE_CHANGED:"The project configuration changed. Inspect the original run scope.",WORKSPACE_ACTIVE_OR_UNRESOLVED:"A Git workspace is running or needs inspection. Its private records are preserved.",WORKSPACE_NEEDS_INSPECTION:"Inspect the existing workspace and worker log before deciding how to recover. It will not be recreated automatically.",GIT_CONTROL_FILE_REFUSED:"Git control files cannot be included in a review workspace.",WORKSPACE_BYTES_CHANGED:"Workspace files changed after verification. Inspect the workspace before continuing."};
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
function readOnlyPanelActive(){return comparisonOpen||comparisonOpening||readinessOpen||readinessOpening||bundleOpen||bundleOpening||projectCheckOpen||projectCheckOpening||bundleWorkspaceOpen||bundleWorkspaceOpening;}
function stateClass(state){return state==='REVIEW_READY'?'good':['FAILED','REFUSED','UNCERTAIN','INTERRUPTED','RECOVERY_REQUIRED'].includes(state)?'bad':'';}
function projectChanged(){const p=configuration.projects.find(p=>p.id===$('project').value);if(!p)return;const demo=$('model').querySelector('option[value="scripted-demo"]');demo.disabled=!p.scripted_available;if(demo.disabled&&$('model').value==='scripted-demo')$('model').value=configuration.models[0]||'';$('goal').value=p.goal;const files=$('scope-files');files.replaceChildren(...p.files.map(name=>node('span',name+(p.editable.includes(name)?' · editable':' · protected'),'file-chip'+(p.editable.includes(name)?' editable':''))));$('scope-note').textContent=p.checks.length+' named check'+(p.checks.length===1?'':'s')+' · Edits stay in a private copy';modelChanged();resetProjectRefresh(p);}
function modelChanged(){$('goal').readOnly=$('model').value==='scripted-demo';if($('goal').readOnly){const p=configuration.projects.find(p=>p.id===$('project').value);if(p)$('goal').value=p.goal;}}
function setAdmission(reason){const blocked=Boolean(reason);if(blocked&&admissionReason!==reason)invalidateProjectRefresh();admissionReason=reason||null;$('admission').hidden=!blocked;$('admission').textContent=reason?(errors[reason]||reason.replaceAll('_',' ').toLowerCase()):'';for(const id of ['start','project','model','goal'])$(id).disabled=blocked||busy||projectRefreshBusy||(id==='start'&&!$('model').value);setProjectRefreshControls();setComparisonControls();}
function renderHistory(rows){$('history-count').textContent=String(rows.length);if(!rows.length){$('history').replaceChildren(node('p','Your runs will appear here.','empty-small'));return;}$('history').replaceChildren(...rows.map(row=>{const b=node('button',undefined,'history-item'+(row.id===selected?' selected':''));b.append(node('strong',row.project_name),node('small',(friendly[row.state]||row.state)+' · '+row.id.slice(0,6)));b.addEventListener('click',()=>{invalidateBundle('Run selection changed. Close this panel and preview the selected accepted run.');selected=row.id;current=null;setBundleControls();refresh();});return b;}));}
function renderRun(v){const changed=!current||current.id!==v.id;if(bundleRunKey(current)!==bundleRunKey(v))invalidateBundle('Run, review or result changed. Preview the accepted artifact again.');current=v;$('welcome').hidden=true;$('run-panel').hidden=false;$('run-project').textContent=v.project_name.toUpperCase();$('run-title').textContent='Task '+v.id.slice(0,8);$('run-meta').textContent=v.goal;$('run-state').textContent=friendly[v.state]||v.state;$('run-state').className='state-pill '+stateClass(v.state);$('stop').disabled=!['RUNNING','STOP_REQUESTED'].includes(v.state)||v.state==='STOP_REQUESTED';$('budget-label').textContent=v.turns+' / '+v.max_turns+' model turns';$('budget-bar').max=v.max_turns;$('budget-bar').value=v.turns;$('run-mode').textContent=v.backend==='scripted-demo'?'SCRIPTED · NO INFERENCE':v.model;renderDiagnostics(v);renderContext(v);$('plan').replaceChildren(...(v.plan.length?v.plan.map(s=>node('li',s)):[node('li','Waiting for the agent’s plan.','muted')]));$('events').replaceChildren(...v.events.map(e=>{const li=node('li');li.append(node('span',e.text),node('small','#'+String(e.index).padStart(2,'0')+' · '+e.kind.replaceAll('_',' ')));return li;}));$('activity-empty').hidden=v.events.length>0;$('diff').textContent=v.patch||'The patch will appear after the task finishes.';
  $('checks').replaceChildren(...v.checks.map(c=>{const card=node('section',undefined,'check-card');const heading=node('div',undefined,'check-heading');heading.append(node('strong',c.label),node('span',c.exit_code===0?'PASS':'FAIL','state-pill '+(c.exit_code===0?'good':'bad')));card.append(heading,node('p',(c.tests_ran||0)+' tests · exit '+c.exit_code+(c.timed_out?' · timed out':''),'muted'),node('pre',c.output||'No output','code-view'));return card;}));
  $('result-hash').textContent=v.result_sha256||'Pending';$('patch-hash').textContent=v.patch_sha256||'Pending';const ready=v.state==='REVIEW_READY'&&Boolean(v.result_sha256)&&!v.pending_events;$('accept').disabled=!ready||busy;$('reject').disabled=!ready||busy;
  if(changed)$('review-note').value=v.review?v.review.note:'';
  const accepted=v.review&&v.review.verdict==='accepted'&&v.review.result_sha256===v.result_sha256&&v.review.patch_sha256===v.patch_sha256;$('export').disabled=!ready||!accepted||busy;renderWorkspace(v,ready,accepted);$('review-status').textContent=v.review?'Review '+v.review.verdict+'. '+(accepted?'Export is ready. Source has not been changed.':'Export remains unavailable.'):'Available after a completed task and an accepted review.';setAdmission(v.admission_block);
}
async function refresh(){if(polling||readOnlyPanelActive())return;polling=true;let finish;normalRefreshInFlight=new Promise(resolve=>{finish=resolve;});try{const rows=await api('/api/history');if(readOnlyPanelActive())return;if(!initialized){selected=rows.length?rows[0].id:null;initialized=true;}renderHistory(rows);if(selected){const run=await api('/api/run/'+selected);if(readOnlyPanelActive())return;renderRun(run);}else{$('run-panel').hidden=true;$('welcome').hidden=false;const cfg=await api('/api/config');if(readOnlyPanelActive())return;setAdmission(cfg.admission_block);}}catch(error){showError(error);}finally{polling=false;finish();}}
async function submitReview(verdict){if(!current)return;clearError();busy=true;invalidateBundle('Review changed. Preview the accepted artifact again.');setBundleControls();try{await api('/api/review',{id:current.id,result_sha256:current.result_sha256,patch_sha256:current.patch_sha256,verdict,note:$('review-note').value});await refresh();}catch(error){showError(error);}finally{busy=false;if(current)renderRun(current);}}
$('task-form').addEventListener('submit',async event=>{event.preventDefault();clearError();busy=true;setAdmission(null);try{const value=await api('/api/start',{project:$('project').value,model:$('model').value,goal:$('goal').value});selected=value.id;current=null;await refresh();}catch(error){showError(error);}finally{busy=false;await refresh();}});
$('new-task').addEventListener('click',()=>{invalidateBundle();selected=null;current=null;setBundleControls();clearError();$('run-panel').hidden=true;$('welcome').hidden=false;$('goal').focus();refresh();});
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

const comparisonDifferences={PROJECT_DIFFERS:'The saved projects differ.',GOAL_DIFFERS:'The saved goals differ.',FILE_SCOPE_DIFFERS:'The selected file paths differ.',BASELINE_DIFFERS:'The selected baseline file hashes differ.',EDIT_SCOPE_DIFFERS:'The editable file scope differs.',CHECKS_DIFFER:'The fixed check specifications differ.',BUDGETS_DIFFER:'The model-turn or request-timeout limits differ.',INCOMPLETE_RECORDS:'Saved records are incomplete; direct comparability cannot be established.',TASK_FINGERPRINT_MISMATCH:'A saved task does not match its recorded start fingerprint.'};
const comparisonNotes={RECORD_MISSING:'A saved record section is missing. Its values remain Unknown.',RECORD_INVALID:'A saved record section is invalid. Its values have not been reconstructed.',RECORD_LIMIT:'A saved record section exceeded a read limit and is unavailable.',EVENT_LIMIT:'The bounded event history is incomplete; measurements may be unavailable.',PATCH_TRUNCATED:'Patch text is clipped; some saved text is omitted.',LEGACY_TASK_FINGERPRINT:'A legacy run has no recorded start fingerprint. A match has not been reconstructed.',INCOMPLETE_METRICS:'Request measurements are incomplete. Unknown totals and deltas have not been reconstructed.',TASK_FINGERPRINT_MISMATCH:'Saved task bytes differ from the recorded start fingerprint.',PATCH_FINGERPRINT_MISMATCH:'Saved patch bytes differ from the recorded patch fingerprint.',HISTORY_LABEL_TRUNCATED:'Some run labels are shortened; compare to read the saved goal.'};
const comparisonIntegrity={MATCH:'Matches recorded start',NOT_RECORDED:'Start fingerprint not recorded',MISMATCH:'Fingerprint mismatch',UNAVAILABLE:'Unknown'};
function comparisonValue(value){return value===null||value===undefined?'Unknown':String(value);}
function comparisonInteger(value){return Number.isSafeInteger(value)&&value>=0?value.toLocaleString('en-US'):'Unknown';}
function comparisonBytes(value){const text=comparisonInteger(value);return text==='Unknown'?text:text+' bytes';}
function comparisonElapsed(value){return Number.isSafeInteger(value)&&value>=0?(value/1000).toLocaleString('en-US',{maximumFractionDigits:3})+' s':'Unknown';}
function comparisonTime(value){const text=Number.isSafeInteger(value)&&value>=0?diagnosticStarted(value*1000):'Not recorded';return text==='Not recorded'?'Unknown':text;}
function comparisonBoolean(value){return value===true?'Yes':value===false?'No':'Unknown';}
function comparisonPermission(value){return value===true?'Editable':value===false?'Protected':'Unknown';}
function comparisonState(value){return diagnosticText(friendly,value)||'Unknown';}
function comparisonDelta(value,unit){if(!Number.isSafeInteger(value))return 'Unknown';const number=unit==='ms'?value/1000:value;return (value>0?'+':'')+number.toLocaleString('en-US',{maximumFractionDigits:unit==='ms'?3:0})+(unit==='ms'?' s':unit==='bytes'?' bytes':'');}
function comparisonNoteList(codes,labels){
  if(!Array.isArray(codes)||!codes.length)return null;
  const texts=[...new Set(codes.map(code=>diagnosticText(labels||comparisonNotes,code)||'An additional saved-record warning needs inspection.'))];
  const list=node('ul',undefined,'comparison-notes');list.append(...texts.map(text=>node('li',text)));return list;
}
function comparisonDetails(title,children){const details=node('details',undefined,'comparison-section');details.append(node('summary',title),...children);return details;}
function invalidateComparison(text){comparisonSequence++;comparisonBusy=false;$('comparison-result').hidden=true;$('comparison-result').replaceChildren();$('comparison-status').textContent=text||'Choose two different saved runs, then compare.';}
function setComparisonControls(){
  $('comparison-open').disabled=!configuration||readOnlyPanelActive()||busy||projectRefreshBusy;
  $('comparison-open').textContent=comparisonOpening?'Opening comparison…':'Compare runs';
  $('new-task').disabled=readOnlyPanelActive();
  $('setup-open').disabled=readOnlyPanelActive();
  $('comparison-left').disabled=!comparisonOpen||comparisonHistoryLoading||!comparisonHistoryReady||!$('comparison-left').options.length;
  $('comparison-right').disabled=!comparisonOpen||comparisonHistoryLoading||!comparisonHistoryReady||!$('comparison-right').options.length;
  $('comparison-submit').disabled=!comparisonOpen||comparisonHistoryLoading||!comparisonHistoryReady||comparisonBusy||!comparisonLeftId||!comparisonRightId||comparisonLeftId===comparisonRightId;
  setReadinessControls();setBundleControls();setProjectCheckControls();setBundleWorkspaceControls();
}
function comparisonOptions(rows,selectedId){
  const options=rows.map(run=>{const option=node('option',comparisonValue(run.project_name)+' · '+comparisonState(run.state)+' · '+run.id.slice(0,8)+' · '+comparisonValue(run.goal));option.value=run.id;return option;});
  if(selectedId&&!rows.some(run=>run.id===selectedId)){const option=node('option','Previously selected saved run · '+selectedId);option.value=selectedId;options.unshift(option);}
  if(!options.length){const option=node('option','No saved runs available');option.value='';options.push(option);}
  return options;
}
async function loadComparisonHistory(){
  const sequence=++comparisonHistorySequence;
  comparisonHistoryLoading=true;comparisonHistoryReady=false;$('comparison-history-status').textContent='Loading saved run history…';$('comparison-history-notes').replaceChildren();setComparisonControls();
  try{
    const history=await api('/api/comparison-history');
    if(!comparisonOpen||sequence!==comparisonHistorySequence)return;
    comparisonHistoryReady=true;
    const runs=Array.isArray(history.runs)?history.runs.filter(run=>run&&typeof run.id==='string'&&/^[a-f0-9]{16}$/.test(run.id)):[];
    if(!comparisonLeftId)comparisonLeftId=runs.some(run=>run.id===selected)?selected:(runs[0]&&runs[0].id)||'';
    if(!comparisonRightId)comparisonRightId=(runs.find(run=>run.id!==comparisonLeftId)||{}).id||'';
    $('comparison-left').replaceChildren(...comparisonOptions(runs,comparisonLeftId));$('comparison-left').value=comparisonLeftId;
    $('comparison-right').replaceChildren(...comparisonOptions(runs,comparisonRightId));$('comparison-right').value=comparisonRightId;
    $('comparison-history-status').textContent=comparisonInteger(runs.length)+' saved runs listed · return limit '+comparisonInteger(history.limit)+'.';
    const notes=comparisonNoteList(history.notes);if(notes)$('comparison-history-notes').append(notes);
    if(history.truncated)$('comparison-history-notes').prepend(node('p','Saved-run history is partial. Only a bounded set of metadata was inspected; other saved runs may be omitted.','context-notice'));
    if(!runs.length)$('comparison-status').textContent='No saved runs are available to compare.';
    else if(!comparisonRightId)$('comparison-status').textContent='Two different saved runs are needed for comparison.';
  }catch(error){
    if(!comparisonOpen||sequence!==comparisonHistorySequence)return;
    $('comparison-history-status').textContent=errors[error.message]||'Saved-run history could not be loaded. Inspect the private saved records.';
    $('comparison-left').replaceChildren();$('comparison-right').replaceChildren();
  }finally{if(sequence===comparisonHistorySequence){comparisonHistoryLoading=false;setComparisonControls();}}
}
function comparisonCheckRows(rows,title){
  const section=node('section',undefined,'comparison-check-stage');section.append(node('h4',title));
  if(!Array.isArray(rows)||!rows.length){section.append(node('p','Unknown · no saved check results are available.','muted'));return section;}
  for(const check of rows){
    const card=node('section',undefined,'comparison-check');
    card.append(node('h5',comparisonValue(check.name)),diagnosticList([['Kind',comparisonValue(check.kind)],['Exit code',Number.isSafeInteger(check.exit_code)?String(check.exit_code):'Unknown'],['Tests reported',comparisonInteger(check.tests_ran)],['Timed out',comparisonBoolean(check.timed_out)],['Output limited',comparisonBoolean(check.output_limited)],['Infrastructure error',comparisonBoolean(check.infrastructure_error)]],'diagnostic-facts comparison-facts'));
    section.append(card);
  }
  return section;
}
function comparisonRunCard(summary,side){
  const card=node('section',undefined,'comparison-run');
  const heading=node('div',undefined,'comparison-run-heading');heading.append(node('h3',side+' · '+comparisonValue(summary.project_name)),node('span',comparisonState(summary.state),'state-pill'));
  card.append(heading,node('p',comparisonValue(summary.id),'comparison-run-id'),node('h4','Saved goal'),node('p',comparisonValue(summary.goal),'comparison-goal'));
  card.append(node('h4','Recorded outcome'),diagnosticList([['Project',comparisonValue(summary.project)],['Result status',comparisonValue(summary.result_status)],['Recorded reason',diagnosticText(diagnosticReasons,summary.result_reason)||'Unknown'],['Backend',comparisonValue(summary.backend)],['Model',comparisonValue(summary.model)],['Created (UTC)',comparisonTime(summary.created)],['Finished (UTC)',comparisonTime(summary.finished)]],'diagnostic-facts comparison-facts'));
  const metrics=summary.metrics||{};
  card.append(node('h4','Recorded request measurements'),diagnosticList([['Request starts',comparisonInteger(metrics.requests)],['Serialized request-body bytes',comparisonBytes(metrics.request_bytes)],['Recorded request time',comparisonElapsed(metrics.elapsed_ms)],['Byte-measured requests',comparisonInteger(metrics.measured_requests)],['Time-measured requests',comparisonInteger(metrics.elapsed_requests)],['Measurement coverage',metrics.complete===true?'Complete':metrics.complete===false?'Incomplete':'Unknown']],'diagnostic-facts comparison-facts'));
  card.append(comparisonDetails('Task, revision and result fingerprints',[diagnosticList([['Saved task SHA-256',comparisonValue(summary.task_sha256)],['Recorded start task SHA-256',comparisonValue(summary.recorded_task_sha256)],['Configured task revision SHA-256',comparisonValue(summary.project_task_sha256)],['Task integrity',diagnosticText(comparisonIntegrity,summary.task_integrity)||'Unknown'],['Saved result SHA-256',comparisonValue(summary.result_sha256)]],'context-file-facts comparison-hashes')]));
  const checks=node('div',undefined,'comparison-check-specs');
  checks.append(diagnosticList([['Model-turn limit',comparisonInteger(summary.max_turns)],['Per-request timeout',Number.isSafeInteger(summary.request_seconds)&&summary.request_seconds>=0?comparisonInteger(summary.request_seconds)+' s':'Unknown']],'diagnostic-facts comparison-facts'));
  if(Array.isArray(summary.checks)&&summary.checks.length){for(const check of summary.checks){checks.append(node('h5',comparisonValue(check.name)),node('pre',check.spec===null||check.spec===undefined?'Unknown':JSON.stringify(check.spec,null,2),'code-view comparison-spec'));}}else checks.append(node('p','Unknown · no saved check specifications are available.','muted'));
  card.append(comparisonDetails('Fixed task checks and limits',[checks]),comparisonDetails('Baseline and final check results',[comparisonCheckRows(summary.baseline_checks,'Baseline checks'),comparisonCheckRows(summary.final_checks,'Final checks')]));
  const patch=summary.patch||{};
  const patchChildren=[diagnosticList([['Saved patch SHA-256',comparisonValue(patch.sha256)],['Recorded patch SHA-256',comparisonValue(patch.recorded_sha256)],['Matches recorded fingerprint',comparisonBoolean(patch.matches_recorded)]],'context-file-facts comparison-hashes')];
  patchChildren.push(patch.text===null||patch.text===undefined?node('p','Unknown · saved patch text is unavailable.','muted'):node('pre',patch.text||'The saved patch is empty.','code-view comparison-patch'));
  if(patch.truncated)patchChildren.push(node('p','Saved patch display is clipped; some text is omitted.','context-notice'));
  card.append(comparisonDetails('Saved patch',[...patchChildren]));
  const notes=comparisonNoteList(summary.notes);if(notes)card.append(notes);
  return card;
}
function renderComparison(value){
  const container=$('comparison-result');
  const children=[];
  const summary=node('section',undefined,'comparison-summary');
  summary.append(node('h3',value.comparable===true?'Comparable recorded tasks':'Tasks are not directly comparable'),node('p',value.comparable===true?'The saved task evidence agrees on project, goal, selected files, baseline hashes, edit scope, checks and budgets. This does not rank the runs or prove their correctness.':'Differences or incomplete evidence prevent a direct task comparison. Recorded values remain visible below.','muted'));
  const differences=comparisonNoteList(value.differences,comparisonDifferences);if(differences)summary.append(differences);
  const notes=comparisonNoteList(value.notes);if(notes)summary.append(notes);children.push(summary);
  const delta=value.metrics_delta||{};
  const totalsComplete=value.left&&value.left.metrics&&value.left.metrics.complete===true&&value.right&&value.right.metrics&&value.right.metrics.complete===true;
  const deltaSection=node('section',undefined,'comparison-delta');
  deltaSection.append(node('h3','Recorded differences · right minus left'),diagnosticList([['Request starts',comparisonDelta(delta.requests)],['Serialized request-body bytes',comparisonDelta(totalsComplete?delta.request_bytes:null,'bytes')],['Recorded request time',comparisonDelta(totalsComplete?delta.elapsed_ms:null,'ms')]],'diagnostic-facts'),node('p','Unknown measurements stay Unknown. These saved totals do not establish provider completion or model quality.','muted'));children.push(deltaSection);
  const pair=node('div',undefined,'comparison-pair');pair.append(comparisonRunCard(value.left||{},'Left'),comparisonRunCard(value.right||{},'Right'));children.push(pair);
  const files=Array.isArray(value.files)?value.files:[];
  const fileList=node('ul',undefined,'comparison-file-list');
  for(const file of files){
    const item=node('li');item.append(node('h4',comparisonValue(file.path)));
    const pair=node('div',undefined,'comparison-file-pair');
    for(const side of ['left','right']){const section=node('section');section.append(node('h5',side==='left'?'Left':'Right'),diagnosticList([['Baseline SHA-256',comparisonValue(file[side+'_sha256'])],['Edit scope',comparisonPermission(file[side+'_editable'])]],'context-file-facts comparison-hashes'));pair.append(section);}
    item.append(pair);fileList.append(item);
  }
  children.push(comparisonDetails('Selected file hashes and edit scope · '+(files.length?comparisonInteger(files.length)+' paths':'Unknown'),files.length?[fileList]:[node('p','Unknown · selected file evidence is unavailable.','muted')]));
  const difference=value.patch_difference||{};
  const patchChildren=[node('p','Saved patch text compared from left to right. This view does not apply or export either patch.','muted')];
  patchChildren.push(difference.text===null||difference.text===undefined?node('p','Unknown · a saved patch-text comparison is unavailable.','muted'):node('pre',difference.text||'No saved patch-text difference is recorded.','code-view comparison-patch'));
  if(difference.truncated)patchChildren.push(node('p','Patch difference is clipped; some lines or text are omitted.','context-notice'));
  children.push(comparisonDetails('Saved patch-text difference',[...patchChildren]));
  container.replaceChildren(...children);container.hidden=false;
}
$('comparison-open').addEventListener('click',async()=>{
  if(readOnlyPanelActive()||busy||projectRefreshBusy)return;
  const sequence=++comparisonOpenSequence;
  comparisonOpening=true;comparisonHistoryReady=false;invalidateComparison('Waiting for the current live update to finish…');$('comparison-history-status').textContent='Saved history has not been requested yet.';$('comparison-history-notes').replaceChildren();$('comparison-panel').hidden=false;$('normal-workspace').hidden=true;$('comparison-open').setAttribute('aria-expanded','true');setComparisonControls();$('comparison-close').focus();
  const readiness=await new Promise(resolve=>{
    let settled=false;
    const finish=value=>{if(settled)return;settled=true;clearTimeout(timer);if(comparisonOpeningCancel===cancel)comparisonOpeningCancel=null;resolve(value);};
    const cancel=()=>finish('cancelled');
    const timer=setTimeout(()=>finish('timeout'),10000);comparisonOpeningCancel=cancel;
    normalRefreshInFlight.then(()=>finish('ready'));
  });
  if(sequence!==comparisonOpenSequence||!comparisonOpening)return;
  comparisonOpening=false;comparisonOpen=true;setComparisonControls();
  if(readiness!=='ready'){$('comparison-history-status').textContent='The earlier live update did not finish within 10 seconds.';$('comparison-status').textContent='Saved comparison is unavailable. Close this panel to return to the run view.';return;}
  $('comparison-status').textContent='Choose two different saved runs, then compare.';
  await loadComparisonHistory();if(comparisonOpen&&sequence===comparisonOpenSequence&&!$('comparison-left').disabled)$('comparison-left').focus();
});
$('comparison-close').addEventListener('click',()=>{
  comparisonOpenSequence++;if(comparisonOpeningCancel)comparisonOpeningCancel();comparisonOpen=false;comparisonOpening=false;comparisonHistorySequence++;comparisonHistoryLoading=false;comparisonHistoryReady=false;invalidateComparison();$('comparison-panel').hidden=true;$('normal-workspace').hidden=false;$('comparison-open').setAttribute('aria-expanded','false');setComparisonControls();$('comparison-open').focus();refresh();
});
for(const side of ['left','right'])$('comparison-'+side).addEventListener('change',()=>{
  comparisonLeftId=$('comparison-left').value;comparisonRightId=$('comparison-right').value;invalidateComparison('Selection changed. Compare to show the selected saved evidence.');setComparisonControls();
});
$('comparison-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!comparisonOpen||comparisonBusy||comparisonHistoryLoading||!comparisonHistoryReady||!comparisonLeftId||!comparisonRightId||comparisonLeftId===comparisonRightId)return;
  invalidateComparison('Reading saved comparison evidence…');const sequence=comparisonSequence,leftId=comparisonLeftId,rightId=comparisonRightId;comparisonBusy=true;setComparisonControls();
  try{
    const value=await api('/api/compare/'+encodeURIComponent(leftId)+'/'+encodeURIComponent(rightId));
    if(!comparisonOpen||sequence!==comparisonSequence||leftId!==comparisonLeftId||rightId!==comparisonRightId)return;
    if(!value||value.version!==1)throw new Error('COMPARE_RESPONSE');
    renderComparison(value);$('comparison-status').textContent='Showing saved evidence for the selected runs.';
  }catch(error){if(comparisonOpen&&sequence===comparisonSequence)$('comparison-status').textContent=errors[error.message]||'The saved comparison is unavailable. Inspect the private records.';}
  finally{if(sequence===comparisonSequence){comparisonBusy=false;setComparisonControls();}}
});

const readinessStatuses={STATIC_CHECKS_PASSED:'Static checks passed',REFRESH_REQUIRED:'Source refresh required',BLOCKED:'Blocked',NEEDS_INSPECTION:'Needs inspection'};
const readinessEvidenceStatuses={MATCH:'Matches saved fingerprint',CHANGED:'Changed',MISSING:'Missing',UNREADABLE:'Unreadable',LIMIT:'Read limit reached',BINARY:'Binary input refused',UTF8:'Invalid UTF-8 refused',NOT_CHECKED:'Not checked'};
const readinessReasons={CONFIG_CHANGED:'Configuration bytes changed since they were loaded. Source files were not inspected.',CONFIG_UNREADABLE:'Configuration bytes could not be read safely. Source files were not inspected.',TASK_CHANGED:'The saved task bytes changed since they were loaded. Source files were not inspected.',TASK_UNREADABLE:'The saved task could not be read safely. Source files were not inspected.',DEFINITION_INVALID:'The approved task definition needs inspection.',SOURCE_CHANGED:'One or more selected source hashes changed.',SOURCE_MISSING:'A selected source file is missing.',SOURCE_UNREADABLE:'A selected source file could not be read safely.',FILE_LIMIT:'A selected source file exceeded its byte limit.',TOTAL_INPUT_LIMIT:'Selected source exceeds the total byte limit.',BINARY_INPUT:'A selected source file contains binary input.',INVALID_UTF8:'A selected source file is not valid UTF-8.',PREREQUISITE_MISSING:'A required executable is missing.',JDK_NOT_CONFIGURED:'The Java check profile requires a configured JDK.',HOLD_PRESENT:'A saved request hold is present and continues to block new work.',HOLD_UNREADABLE:'A saved hold could not be read safely. Admission remains blocked.',TASK_ACTIVE_OR_UNRESOLVED:'A saved task is active or unresolved.',TASK_UNCERTAIN:'A saved task has an uncertain outcome, even if no hold was observed.',WORKSPACE_ACTIVE_OR_UNRESOLVED:'A saved Git workspace is active or unresolved.',ADMISSION_RECORD_INVALID:'A saved admission record is damaged or unrecognized. Admission needs inspection.',ADMISSION_RECORD_LIMIT:'The saved admission inventory reached a record or byte limit. Admission needs inspection.',ADMISSION_UNAVAILABLE:'Saved admission evidence could not be inspected safely.'};
const readinessPrerequisites={python:'Python',git:'Git',bwrap:'Bubblewrap',prlimit:'prlimit',jdk:'JDK'};
const readinessPresence={AVAILABLE:'Executable present',MISSING:'Missing',NOT_CONFIGURED:'Not configured',NOT_REQUIRED:'Not required',NOT_CHECKED:'Not checked'};
const readinessNotChecked={PROVIDER_AVAILABILITY:'Provider availability',CHECK_EXECUTION:'Check execution',ISOLATION_CAPABILITY:'Isolation capability',JAVA_VERSION:'Java version',MODEL_CONTEXT_FIT:'Model context fit',PROCESS_OWNERSHIP:'Process ownership',WORKSPACE_FRESHNESS:'Workspace freshness',SOURCE_CORRECTNESS:'Source correctness'};
function readinessReasonList(codes){
  if(!Array.isArray(codes)||!codes.length)return null;
  const texts=[...new Set(codes.map(code=>diagnosticText(readinessReasons,code)||'Unrecognized readiness evidence needs inspection. No unknown record details are shown.'))];
  const list=node('ul',undefined,'comparison-notes readiness-reasons');list.append(...texts.map(text=>node('li',text)));return list;
}
function invalidateReadiness(text){readinessSequence++;readinessBusy=false;$('readiness-result').hidden=true;$('readiness-result').replaceChildren();$('readiness-status').textContent=text||'Choose a project, then inspect its static evidence.';}
function setReadinessControls(){
  $('readiness-open').disabled=!configuration||readOnlyPanelActive()||busy||projectRefreshBusy;
  $('readiness-open').textContent=readinessOpening?'Opening readiness…':'Project readiness';
  $('readiness-project').disabled=!readinessOpen||!readinessReady||!$('readiness-project').options.length;
  $('readiness-submit').disabled=!readinessOpen||!readinessReady||readinessBusy||!readinessProjectId;
}
function renderReadinessProjects(){
  const projects=configuration&&Array.isArray(configuration.projects)?configuration.projects:[];
  if(!projects.some(project=>project.id===readinessProjectId))readinessProjectId=projects.some(project=>project.id===$('project').value)?$('project').value:(projects[0]&&projects[0].id)||'';
  $('readiness-project').replaceChildren(...projects.map(project=>{const option=node('option',project.name+' · '+project.id);option.value=project.id;return option;}));$('readiness-project').value=readinessProjectId;
}
function readinessSection(title,children){const section=node('section',undefined,'readiness-section');section.append(node('h3',title),...children);return section;}
function renderReadiness(value){
  const fingerprints=value.fingerprints||{},limits=value.limits||{},admission=value.admission||{};
  const unknownReason=[...(Array.isArray(value.reasons)?value.reasons:[]),...(Array.isArray(admission.reasons)?admission.reasons:[])].some(code=>!diagnosticText(readinessReasons,code));
  const status=unknownReason?'NEEDS_INSPECTION':value.status;
  const summary=node('section',undefined,'readiness-summary');
  const heading=node('div',undefined,'readiness-summary-heading');
  heading.append(node('h3',diagnosticText(readinessStatuses,status)||'Needs inspection'),node('span','STATIC OBSERVATION','state-pill '+(status==='STATIC_CHECKS_PASSED'?'good':status==='BLOCKED'||status==='NEEDS_INSPECTION'?'bad':'')));
  const observed=diagnosticStarted(value.checked_at_ms);
  summary.append(heading,node('p',comparisonValue(value.name)+' · '+comparisonValue(value.project),'readiness-project-name'),diagnosticList([['Observed (UTC)',observed==='Not recorded'?'Unknown':observed],['Total selected source bytes',comparisonBytes(value.total_bytes)]],'diagnostic-facts readiness-facts'),node('p','This dated observation can become stale if files, prerequisites or saved admission records change. It does not authorize running.','muted readiness-stale'));
  const reasons=readinessReasonList(value.reasons);if(reasons)summary.append(reasons);
  const children=[summary,readinessSection('Saved default goal',[node('p',comparisonValue(value.goal),'readiness-goal')])];
  const fingerprintCards=node('div',undefined,'readiness-pair');
  for(const [key,title] of [['config','Configuration fingerprint'],['task','Saved task revision']]){
    const fingerprint=fingerprints[key]||{};
    const card=node('section',undefined,'readiness-evidence-card');card.append(node('h4',title),diagnosticList([['Status',diagnosticText(readinessEvidenceStatuses,fingerprint.status)||'Unknown'],['Saved SHA-256',comparisonValue(fingerprint.expected_sha256)],['Observed SHA-256',comparisonValue(fingerprint.sha256)]],'context-file-facts readiness-hashes'));fingerprintCards.append(card);
  }
  children.push(readinessSection('Exact raw fingerprints',[fingerprintCards]));
  const files=Array.isArray(value.files)?value.files:[];
  const fileList=node('ul',undefined,'readiness-file-list');
  for(const file of files){
    const item=node('li');const heading=node('div',undefined,'readiness-file-heading');heading.append(node('h4',comparisonValue(file.path)),node('span',comparisonPermission(file.editable),'state-pill'));
    item.append(heading,diagnosticList([['Status',diagnosticText(readinessEvidenceStatuses,file.status)||'Unknown'],['Observed size',comparisonBytes(file.bytes)],['Saved SHA-256',comparisonValue(file.expected_sha256)],['Observed SHA-256',comparisonValue(file.sha256)]],'context-file-facts readiness-hashes'));fileList.append(item);
  }
  children.push(readinessSection('Selected source evidence',files.length?[fileList]:[node('p','Unknown · selected source evidence is unavailable.','muted')]));
  const checkChildren=[diagnosticList([['File-count limit',comparisonInteger(limits.max_files)],['Per-file byte limit',comparisonBytes(limits.max_file_bytes)],['Total source byte limit',comparisonBytes(limits.max_total_bytes)],['Model-turn limit',comparisonInteger(limits.max_turns)],['Per-request timeout',Number.isSafeInteger(limits.request_seconds)&&limits.request_seconds>=0?comparisonInteger(limits.request_seconds)+' s':'Unknown']],'diagnostic-facts readiness-facts')];
  if(Array.isArray(value.checks)&&value.checks.length){const checks=node('div',undefined,'readiness-checks');for(const check of value.checks)checks.append(node('h4',comparisonValue(check.name)),node('pre',check.spec===null||check.spec===undefined?'Unknown':JSON.stringify(check.spec,null,2),'code-view comparison-spec'));checkChildren.push(checks);}else checkChildren.push(node('p','Unknown · saved check specifications are unavailable.','muted'));
  children.push(readinessSection('Fixed checks and budgets',checkChildren));
  const prerequisites=node('ul',undefined,'readiness-prerequisites');
  for(const prerequisite of Array.isArray(value.prerequisites)?value.prerequisites:[]){
    const name=diagnosticText(readinessPrerequisites,prerequisite.id);if(!name)continue;
    const item=node('li');item.append(node('h4',name),diagnosticList([['Required for this task',comparisonBoolean(prerequisite.required)],['Presence',diagnosticText(readinessPresence,prerequisite.status)||'Unknown']],'diagnostic-facts readiness-facts'));prerequisites.append(item);
  }
  children.push(readinessSection('Prerequisite presence',[node('p','Presence only. No executable, version command or check was run. Git is optional for coding tasks; a JDK is required for Java check profiles.','muted'),...(prerequisites.children.length?[prerequisites]:[node('p','Unknown · prerequisite evidence is unavailable.','muted')])]));
  const hold=admission.hold==='ABSENT'?'No saved hold observed':admission.hold==='PRESENT'?'Saved hold present':admission.hold==='UNAVAILABLE'?'Unavailable · admission remains blocked':'Unknown';
  const admissionChildren=[diagnosticList([['Saved request hold',hold],['Jobs inspected',comparisonInteger(admission.jobs_inspected)],['Workspace receipts inspected',comparisonInteger(admission.workspaces_inspected)],['Partial inventory',comparisonBoolean(admission.truncated)]],'diagnostic-facts readiness-facts'),node('p','Saved admission evidence only. Process ownership and current workspace freshness were not checked. This inspection changes no hold or saved status.','muted')];
  if(admission.truncated)admissionChildren.push(node('p','Admission inventory is incomplete. Some saved jobs or receipts were not inspected.','context-notice'));
  const admissionReasons=readinessReasonList(admission.reasons);if(admissionReasons)admissionChildren.push(admissionReasons);
  children.push(readinessSection('Saved admission observations',admissionChildren));
  const notChecked=node('ul',undefined,'readiness-not-checked');notChecked.append(...Object.values(readinessNotChecked).map(label=>node('li',label)));
  children.push(readinessSection('Not checked by this inspection',[notChecked]));
  $('readiness-result').replaceChildren(...children);$('readiness-result').hidden=false;
}
$('readiness-open').addEventListener('click',async()=>{
  if(readOnlyPanelActive()||busy||projectRefreshBusy)return;
  const sequence=++readinessOpenSequence;
  readinessOpening=true;readinessReady=false;invalidateReadiness('Waiting for the current live update to finish…');renderReadinessProjects();$('readiness-panel').hidden=false;$('normal-workspace').hidden=true;$('readiness-open').setAttribute('aria-expanded','true');setComparisonControls();$('readiness-close').focus();
  const available=await new Promise(resolve=>{
    let settled=false;
    const finish=value=>{if(settled)return;settled=true;clearTimeout(timer);if(readinessOpeningCancel===cancel)readinessOpeningCancel=null;resolve(value);};
    const cancel=()=>finish('cancelled');
    const timer=setTimeout(()=>finish('timeout'),10000);readinessOpeningCancel=cancel;normalRefreshInFlight.then(()=>finish('ready'));
  });
  if(sequence!==readinessOpenSequence||!readinessOpening)return;
  readinessOpening=false;readinessOpen=true;readinessReady=available==='ready';setComparisonControls();
  if(!readinessReady){$('readiness-status').textContent='The earlier live update did not finish within 10 seconds. Close this panel to return to the run view.';return;}
  $('readiness-status').textContent=readinessProjectId?'Choose a project, then inspect its static evidence.':'No configured project is available for inspection.';
  if(!$('readiness-project').disabled)$('readiness-project').focus();
});
$('readiness-close').addEventListener('click',()=>{
  readinessOpenSequence++;if(readinessOpeningCancel)readinessOpeningCancel();readinessOpen=false;readinessOpening=false;readinessReady=false;invalidateReadiness();$('readiness-panel').hidden=true;$('normal-workspace').hidden=false;$('readiness-open').setAttribute('aria-expanded','false');setComparisonControls();$('readiness-open').focus();refresh();
});
$('readiness-project').addEventListener('change',()=>{readinessProjectId=$('readiness-project').value;invalidateReadiness('Project changed. Inspect to show its static evidence.');setReadinessControls();});
$('readiness-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!readinessOpen||!readinessReady||readinessBusy||!readinessProjectId)return;
  invalidateReadiness('Inspecting the selected project…');const sequence=readinessSequence,projectId=readinessProjectId;readinessBusy=true;setReadinessControls();
  try{
    const value=await api('/api/project-readiness/'+encodeURIComponent(projectId));
    if(!readinessOpen||sequence!==readinessSequence||readinessProjectId!==projectId)return;
    if(!value||value.version!==1||value.project!==projectId)throw new Error('READINESS_RESPONSE');
    renderReadiness(value);$('readiness-status').textContent='Showing a dated static observation for the selected project.';
  }catch(error){if(readinessOpen&&sequence===readinessSequence)$('readiness-status').textContent=errors[error.message]||'Project readiness is unavailable. Inspect the private project records.';}
  finally{if(sequence===readinessSequence){readinessBusy=false;setReadinessControls();}}
});

const bundleErrors={BUNDLE_RECORD_INVALID:'Saved bundle evidence could not be read or validated safely.',BUNDLE_LIMIT:'Bundle evidence exceeds a fixed size or structure limit.',BUNDLE_FINAL_REQUIRED:'Recorded passing independent final checks are required.',BUNDLE_REVIEW_REQUIRED:'An accepted review for these exact result and patch hashes is required.',BUNDLE_NOT_REVIEW_READY:'This saved run is not ready for a reviewed bundle.',BUNDLE_PIN_REQUIRED:'Original task and project revision pins are required. Missing legacy pins are not reconstructed.',BUNDLE_ARTIFACT_CHANGED:'Saved artifact bytes no longer match their recorded hashes.',BUNDLE_INVALID:'The private bundle could not be validated.',BUNDLE_CHANGED:'The bundle changed after preview. Preview it again before downloading.',BUNDLE_HASH_REQUIRED:'A valid displayed bundle SHA-256 is required.',BUNDLE_RUN_UNKNOWN:'The selected saved run is unavailable.',BUNDLE_PROJECT_CHANGED:'Project configuration, task or scope changed. Inspect the private project records.',BUNDLE_RECORD_LIMIT:'Saved bundle evidence exceeds a bounded read limit.',BUNDLE_SOURCE_CHANGED:'Selected source no longer matches the accepted baseline.'};
const bundleMemberNames=['manifest.json','changes.diff','review.json','checks.json','README.txt','SHA256SUMS'];
const bundleNotChecked={CHECK_RERUN:'Check rerun',PROVIDER_COMPLETION:'Provider completion',SOURCE_CORRECTNESS:'Source correctness',GIT_ADOPTION:'Git adoption'};
let bundleReady=false;
function bundleHash(value){return typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);}
function bundleRunKey(value){return value?JSON.stringify([value.id,value.state,value.result_sha256,value.patch_sha256,Boolean(value.pending_events),value.review||null]):null;}
function bundleEligible(value){return Boolean(value&&value.id===selected&&value.state==='REVIEW_READY'&&!value.pending_events&&bundleHash(value.result_sha256)&&bundleHash(value.patch_sha256)&&value.review&&value.review.verdict==='accepted'&&value.review.source_applied===false&&value.review.result_sha256===value.result_sha256&&value.review.patch_sha256===value.patch_sha256);}
function bundleFailure(error){return diagnosticText(bundleErrors,error&&error.message)||diagnosticText(errors,error&&error.message)||'The private bundle is unavailable. Inspect the preserved private records.';}
function invalidateBundle(text){bundleSequence++;bundlePreview=null;bundleBusy=false;$('bundle-result').hidden=true;$('bundle-result').replaceChildren();$('bundle-status').textContent=text||'Preview the accepted artifact before downloading.';}
function setBundleControls(){
  const eligible=bundleEligible(current);
  const sameRun=eligible&&current.id===bundleRunId;
  $('bundle-preview-open').disabled=!eligible||readOnlyPanelActive()||busy||projectRefreshBusy;
  $('bundle-preview').disabled=!bundleOpen||!bundleReady||bundleBusy||!sameRun;
  $('bundle-download').disabled=!bundleOpen||!bundleReady||bundleBusy||!sameRun||!bundlePreview||bundlePreview.key!==bundleRunKey(current)||bundlePreview.id!==current.id;
  $('bundle-review-status').textContent=eligible?'Preview the private archive for these accepted result and patch hashes.':'Requires an accepted review for the current result and patch.';
}
function validBundleSummary(value){
  if(!value||value.version!==1||!bundleHash(value.bundle_sha256)||!Number.isSafeInteger(value.archive_bytes)||value.archive_bytes<=0||value.archive_bytes>2097152||value.member_count!==6||!Array.isArray(value.members)||value.members.length!==6)return false;
  const names=new Set();
  for(const member of value.members){if(!member||!bundleMemberNames.includes(member.path)||names.has(member.path)||!Number.isSafeInteger(member.bytes)||member.bytes<0||!bundleHash(member.sha256))return false;names.add(member.path);}
  const hashes=value.hashes||{};
  if(!['task_sha256','result_sha256','review_record_sha256','final_event_sha256','patch_sha256'].every(key=>bundleHash(hashes[key])))return false;
  if(!value.review||value.review.verdict!=='accepted'||value.review.source_applied!==false||!Array.isArray(value.files)||!value.files.length||value.files.length>32||!Array.isArray(value.checks)||!value.checks.length||value.checks.length>4)return false;
  if(!value.files.every(file=>file&&typeof file.path==='string'&&typeof file.editable==='boolean'&&bundleHash(file.before_sha256)&&bundleHash(file.after_sha256)&&(file.editable||file.before_sha256===file.after_sha256)))return false;
  if(!value.checks.every(check=>check&&typeof check.name==='string'&&check.spec!==null&&check.spec!==undefined&&check.exit_code===0&&Number.isSafeInteger(check.tests_ran)&&check.tests_ran>0&&check.timed_out===false&&check.output_limited===false&&check.infrastructure_error===false))return false;
  return Array.isArray(value.not_checked)&&value.not_checked.length===4&&new Set(value.not_checked).size===4&&value.not_checked.every(code=>Object.prototype.hasOwnProperty.call(bundleNotChecked,code));
}
function renderBundle(value){
  const summary=node('section',undefined,'bundle-summary');
  summary.append(node('h3','Previewed whole archive'),diagnosticList([['Bundle SHA-256',value.bundle_sha256]],'context-file-facts bundle-hashes'),diagnosticList([['Archive size',comparisonBytes(value.archive_bytes)],['Fixed members',comparisonInteger(value.member_count)],['Recorded review',value.review.verdict],['Source applied',comparisonBoolean(value.review.source_applied)]],'diagnostic-facts bundle-facts'),node('p','Download is pinned to this exact archive digest. The controller rebuilds and revalidates the evidence before returning it.','muted'));
  const members=node('ul',undefined,'bundle-member-list');
  for(const member of value.members){const item=node('li');item.append(node('h4',member.path),diagnosticList([['Size',comparisonBytes(member.bytes)],['SHA-256',member.sha256]],'context-file-facts bundle-hashes'));members.append(item);}
  const files=node('ul',undefined,'bundle-file-list');
  for(const file of value.files){const item=node('li');const heading=node('div',undefined,'bundle-file-heading');heading.append(node('h4',comparisonValue(file.path)),node('span',comparisonPermission(file.editable),'state-pill'));item.append(heading,diagnosticList([['Before SHA-256',comparisonValue(file.before_sha256)],['After SHA-256',comparisonValue(file.after_sha256)]],'context-file-facts bundle-hashes'));files.append(item);}
  const checks=node('div',undefined,'bundle-checks');
  for(const check of value.checks){const item=node('section');item.append(node('h4',comparisonValue(check.name)),diagnosticList([['Exit code',Number.isSafeInteger(check.exit_code)?String(check.exit_code):'Unknown'],['Tests reported',comparisonInteger(check.tests_ran)],['Timed out',comparisonBoolean(check.timed_out)],['Output limited',comparisonBoolean(check.output_limited)],['Infrastructure error',comparisonBoolean(check.infrastructure_error)]],'diagnostic-facts bundle-facts'),node('pre',check.spec===null||check.spec===undefined?'Unknown':JSON.stringify(check.spec,null,2),'code-view comparison-spec'));checks.append(item);}
  const recordHashes=diagnosticList([['Task record SHA-256',value.hashes.task_sha256],['Result record SHA-256',value.hashes.result_sha256],['Accepted review record SHA-256',value.hashes.review_record_sha256],['Final-check event SHA-256',value.hashes.final_event_sha256],['Patch SHA-256',value.hashes.patch_sha256]],'context-file-facts bundle-hashes');
  const notChecked=node('ul',undefined,'bundle-not-checked');notChecked.append(...Object.values(bundleNotChecked).map(label=>node('li',label)));
  $('bundle-result').replaceChildren(summary,readinessSection('Six fixed archive members',[members]),readinessSection('Selected file scope',[files]),readinessSection('Recorded passing independent final checks',[node('p','Saved observations only. No check output is included and no checks were rerun for this bundle.','muted'),checks]),readinessSection('Original records pinned by digest',[recordHashes,node('p','Raw task, result, review and final-event records are excluded. Their digests do not reconstruct or authenticate those records.','muted')]),readinessSection('Not checked by this bundle',[notChecked]));
  $('bundle-result').hidden=false;
}
async function previewPrivateBundle(){
  if(!bundleOpen||!bundleReady||bundleBusy||!bundleEligible(current)||current.id!==bundleRunId)return;
  invalidateBundle('Reading and validating the accepted bundle evidence…');
  const sequence=bundleSequence,id=current.id,key=bundleRunKey(current);bundleBusy=true;setBundleControls();
  try{
    const value=await api('/api/bundle-preview/'+encodeURIComponent(id));
    if(!bundleOpen||sequence!==bundleSequence||!bundleEligible(current)||current.id!==id||bundleRunKey(current)!==key)return;
    if(!validBundleSummary(value))throw new Error('BUNDLE_INVALID');
    if(value.hashes.result_sha256!==current.result_sha256||value.hashes.patch_sha256!==current.patch_sha256)throw new Error('BUNDLE_ARTIFACT_CHANGED');
    renderBundle(value);bundlePreview={id,key,sha256:value.bundle_sha256,bytes:value.archive_bytes};$('bundle-status').textContent='Private bundle preview verified. Review its members and preserve the whole archive digest before downloading.';
  }catch(error){if(bundleOpen&&sequence===bundleSequence){invalidateBundle(bundleFailure(error));}}
  finally{if(sequence===bundleSequence){bundleBusy=false;}setBundleControls();}
}
$('bundle-preview-open').addEventListener('click',async()=>{
  if(readOnlyPanelActive()||busy||projectRefreshBusy||!bundleEligible(current))return;
  const sequence=++bundleOpenSequence,key=bundleRunKey(current);bundleRunId=current.id;bundleOpening=true;bundleReady=false;invalidateBundle('Waiting for the current live update to finish…');$('bundle-panel').hidden=false;$('normal-workspace').hidden=true;$('bundle-preview-open').setAttribute('aria-expanded','true');setComparisonControls();$('bundle-close').focus();
  const available=await new Promise(resolve=>{
    let settled=false;
    const finish=value=>{if(settled)return;settled=true;clearTimeout(timer);if(bundleOpeningCancel===cancel)bundleOpeningCancel=null;resolve(value);};
    const cancel=()=>finish('cancelled');const timer=setTimeout(()=>finish('timeout'),10000);bundleOpeningCancel=cancel;normalRefreshInFlight.then(()=>finish('ready'));
  });
  if(sequence!==bundleOpenSequence||!bundleOpening)return;
  bundleOpening=false;bundleOpen=true;bundleReady=available==='ready';setComparisonControls();
  if(!bundleReady){$('bundle-status').textContent='The earlier live update did not finish within 10 seconds. Close this panel to return to the run view.';return;}
  if(!bundleEligible(current)||current.id!==bundleRunId||bundleRunKey(current)!==key){invalidateBundle('Run, review or result changed. Preview the current accepted artifact explicitly.');setBundleControls();return;}
  await previewPrivateBundle();
});
$('bundle-preview').addEventListener('click',previewPrivateBundle);
$('bundle-close').addEventListener('click',()=>{
  bundleOpenSequence++;if(bundleOpeningCancel)bundleOpeningCancel();bundleOpen=false;bundleOpening=false;bundleReady=false;bundleRunId=null;invalidateBundle();$('bundle-panel').hidden=true;$('normal-workspace').hidden=false;$('bundle-preview-open').setAttribute('aria-expanded','false');setComparisonControls();($('bundle-preview-open').disabled?$('review-tab'):$('bundle-preview-open')).focus();refresh();
});
$('review-note').addEventListener('input',()=>{invalidateBundle('Review note changed. Preview the accepted artifact again.');setBundleControls();});
$('bundle-download').addEventListener('click',async()=>{
  const preview=bundlePreview;
  if(!bundleOpen||!bundleReady||bundleBusy||!preview||!bundleEligible(current)||current.id!==preview.id||bundleRunKey(current)!==preview.key)return;
  const sequence=bundleSequence;bundleBusy=true;$('bundle-status').textContent='Revalidating the displayed bundle digest before download…';setBundleControls();
  try{
    const response=await fetch('/api/bundle-export',{method:'POST',headers:{'X-Workbench-Token':token,'Content-Type':'application/json'},body:JSON.stringify({id:preview.id,bundle_sha256:preview.sha256})});
    if(!response.ok){let code='BUNDLE_INVALID';try{const failure=await response.json();if(failure&&typeof failure.error==='string')code=failure.error;}catch(_){}throw new Error(code);}
    if((response.headers.get('Content-Type')||'').split(';')[0].trim()!=='application/zip')throw new Error('BUNDLE_INVALID');
    const archive=await response.blob();
    if(!bundleOpen||sequence!==bundleSequence||bundlePreview!==preview||!bundleEligible(current)||current.id!==preview.id||bundleRunKey(current)!==preview.key)return;
    if(archive.size!==preview.bytes)throw new Error('BUNDLE_CHANGED');
    const url=URL.createObjectURL(archive),link=document.createElement('a');link.href=url;link.download='outlands-reviewed-bundle-'+preview.id+'.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('bundle-status').textContent='Private bundle download started. Preserve the displayed whole archive SHA-256 separately.';
  }catch(error){if(bundleOpen&&sequence===bundleSequence)invalidateBundle(bundleFailure(error));}
  finally{if(sequence===bundleSequence)bundleBusy=false;setBundleControls();}
});

const projectCheckErrors={BUNDLE_CHANGED:'The selected archive does not match the supplied trusted SHA-256.',BUNDLE_HASH_REQUIRED:'The optional trusted archive SHA-256 must contain 64 lowercase hexadecimal characters.',PROJECT_CHECK_TASK_INVALID:'The selected task could not be validated safely.',PROJECT_CHECK_INPUT:'Select a valid private ZIP and, if supplied, a 64-character lowercase SHA-256.',PROJECT_CHECK_LIMIT:'The private ZIP or selected evidence exceeds a fixed limit.',PROJECT_CHECK_OUTPUT_LIMIT:'The selected report exceeds its bounded output size.',PROJECT_CHECK_PROJECT_CHANGED:'Project configuration or task bytes changed. No selected source was inspected.',PROJECT_CHECK_PROJECT_UNKNOWN:'The selected configured project is unavailable.'};
const projectCheckStatuses={BASELINE_MATCH:'Selected bytes match bundle baseline',CANDIDATE_MATCH:'Selected bytes match bundle candidate',MIXED_MATCH:'Selected bytes mix baseline and candidate',DIFFERENT:'Selected bytes differ from the bundle',NEEDS_INSPECTION:'Selected bytes need inspection'};
const projectCheckFileStatuses={UNCHANGED:'Unchanged in baseline and candidate',BASELINE:'Matches baseline bytes',CANDIDATE:'Matches candidate bytes',CHANGED:'Selected bytes differ',MISSING:'Missing',UNREADABLE:'Unreadable',LIMIT:'Read limit reached',BINARY:'Binary input refused',UTF8:'Invalid UTF-8 refused',NOT_CHECKED:'Not checked',OUT_OF_SCOPE:'Outside selected task scope'};
const projectCheckReasons={FORMAT_MISMATCH:'Task formats differ.',SCOPE_MISMATCH:'Selected path sets differ. Archive paths were not adopted into project scope.',PERMISSIONS_MISMATCH:'Editable/protected permissions differ.',CHECKS_MISMATCH:'Fixed check specifications differ.',BUDGETS_MISMATCH:'Model-turn or request-timeout budgets differ.',SOURCE_CHANGED:'Selected source bytes differ from the bundle observations.',SOURCE_MISSING:'A selected source file is missing.',SOURCE_UNREADABLE:'A selected source file could not be read safely.',FILE_LIMIT:'A selected file exceeded its size limit.',TOTAL_INPUT_LIMIT:'Selected source exceeds the total eligibility limit.',BINARY_INPUT:'Selected source contains binary input.',INVALID_UTF8:'Selected source is not valid UTF-8.',MIXED_BASELINE_CANDIDATE:'Selected files contain a mixture of baseline and candidate bytes.'};
const projectCheckNotChecked={TASK_GOAL:'Task goal',CHECK_RERUN:'Check rerun',PROVIDER_COMPLETION:'Provider completion',SOURCE_CORRECTNESS:'Source correctness',PATCH_APPLICABILITY:'Patch applicability',GIT_ADOPTION:'Git adoption'};
function projectCheckFile(){return $('project-check-file').files&&$('project-check-file').files[0]||null;}
function projectCheckValidFile(file){return Boolean(file&&Number.isSafeInteger(file.size)&&file.size>=1&&file.size<=2097152);}
function projectCheckValidPin(pin){return !pin||bundleHash(pin);}
function projectCheckFailure(error){return diagnosticText(projectCheckErrors,error&&error.message)||diagnosticText(bundleErrors,error&&error.message)||diagnosticText(errors,error&&error.message)||'The bundle/project inspection is unavailable. Inspect the private inputs and records.';}
function invalidateProjectCheck(text){projectCheckSequence++;projectCheckBusy=false;$('project-check-result').hidden=true;$('project-check-result').replaceChildren();$('project-check-status').textContent=text||'Select a project and a private ZIP, then check explicitly.';}
function setProjectCheckControls(){
  $('project-check-open').disabled=!configuration||readOnlyPanelActive()||busy||projectRefreshBusy;
  $('project-check-open').textContent=projectCheckOpening?'Opening project check…':'Check bundle against project';
  const enabled=projectCheckOpen&&projectCheckReady;
  for(const id of ['project-check-project','project-check-file','project-check-sha'])$(id).disabled=!enabled;
  $('project-check-submit').disabled=!enabled||projectCheckBusy||!projectCheckProjectId||!projectCheckValidFile(projectCheckFile())||!projectCheckValidPin($('project-check-sha').value);
}
function renderProjectCheckProjects(){
  const projects=configuration&&Array.isArray(configuration.projects)?configuration.projects:[];
  if(!projects.some(project=>project.id===projectCheckProjectId))projectCheckProjectId=projects.some(project=>project.id===$('project').value)?$('project').value:(projects[0]&&projects[0].id)||'';
  $('project-check-project').replaceChildren(...projects.map(project=>{const option=node('option',project.name+' · '+project.id);option.value=project.id;return option;}));$('project-check-project').value=projectCheckProjectId;
}
function validProjectCheckWrapper(value,projectId){
  const report=value&&value.comparison;
  if(!value||value.version!==1||!value.project||value.project.id!==projectId||typeof value.project.name!=='string'||!Number.isSafeInteger(value.checked_at_ms)||value.checked_at_ms<0||!bundleHash(value.config_sha256)||!bundleHash(value.task_sha256)||!report||report.version!==1||!bundleHash(report.bundle_sha256)||report.task_sha256!==value.task_sha256||!diagnosticText(projectCheckStatuses,report.status))return false;
  if(!report.profile||!['format','scope','permissions','checks','budgets'].every(key=>typeof report.profile[key]==='boolean'))return false;
  if(!Array.isArray(report.files)||report.files.length>32||!Array.isArray(report.bundle_only)||report.bundle_only.length>32||!Array.isArray(report.project_only)||report.project_only.length>32||!Array.isArray(report.permission_differences)||report.permission_differences.length>32)return false;
  if(!Array.isArray(report.reasons)||!report.reasons.every(code=>diagnosticText(projectCheckReasons,code))||!Array.isArray(report.not_checked)||report.not_checked.length!==6||new Set(report.not_checked).size!==6||!report.not_checked.every(code=>Object.prototype.hasOwnProperty.call(projectCheckNotChecked,code)))return false;
  return report.files.every(file=>file&&typeof file.path==='string'&&typeof file.editable==='boolean'&&diagnosticText(projectCheckFileStatuses,file.status));
}
function renderProjectCheck(value){
  const report=value.comparison,profile=report.profile;
  const summary=node('section',undefined,'project-check-summary');
  summary.append(node('h3',projectCheckStatuses[report.status]),node('p',value.project.name+' · '+value.project.id,'project-check-project-name'),diagnosticList([['Observed (UTC)',diagnosticStarted(value.checked_at_ms)],['Total selected bytes',comparisonBytes(report.total_bytes)],['Configured task pins match current bytes',comparisonBoolean(report.task_pins_match)]],'diagnostic-facts project-check-facts'),node('p','Configured task pins are separate from bundle matching. This dated, sequential observation can become stale; it authorizes neither Run nor patch application.','muted'));
  const reasons=comparisonNoteList(report.reasons,projectCheckReasons);if(reasons)summary.append(reasons);
  const hashes=diagnosticList([['Supplied bundle SHA-256',report.bundle_sha256],['Selected task SHA-256',value.task_sha256],['Selected configuration SHA-256',value.config_sha256]],'context-file-facts project-check-hashes');
  const profileFacts=diagnosticList([['Task format',profile.format?'Matches':'Differs'],['Selected path set',profile.scope?'Matches':'Differs'],['Edit permissions on shared paths',profile.permissions?'Match':'Differ'],['Check specifications',profile.checks?'Match':'Differ'],['Budgets',profile.budgets?'Match':'Differ']],'diagnostic-facts project-check-facts');
  const differences=node('div',undefined,'project-check-differences');
  for(const [title,paths] of [['Bundle-only paths',report.bundle_only],['Project-only paths',report.project_only]]){const section=node('section');section.append(node('h4',title));if(paths.length){const list=node('ul');list.append(...paths.map(path=>node('li',path)));section.append(list);}else section.append(node('p','None recorded.','muted'));differences.append(section);}
  const permissions=node('ul',undefined,'project-check-permissions');
  for(const difference of report.permission_differences){const item=node('li');item.append(node('h4',comparisonValue(difference.path)),diagnosticList([['Bundle scope',comparisonPermission(difference.bundle_editable)],['Selected project scope',comparisonPermission(difference.project_editable)]],'diagnostic-facts project-check-facts'));permissions.append(item);}
  const files=node('ul',undefined,'project-check-file-list');
  for(const file of report.files){const item=node('li');const heading=node('div',undefined,'project-check-file-heading');heading.append(node('h4',file.path),node('span',projectCheckFileStatuses[file.status],'state-pill'));item.append(heading,diagnosticList([['Bundle scope',comparisonPermission(file.editable)],['Selected project scope',comparisonPermission(file.project_editable)],['Observed size',comparisonBytes(file.bytes)],['Configured task pin matches current',comparisonBoolean(file.task_pin_match)]],'diagnostic-facts project-check-facts'),diagnosticList([['Bundle before SHA-256',comparisonValue(file.before_sha256)],['Bundle after SHA-256',comparisonValue(file.after_sha256)],['Selected configured SHA-256',comparisonValue(file.project_sha256)],['Current observed SHA-256',comparisonValue(file.current_sha256)]],'context-file-facts project-check-hashes'));files.append(item);}
  const notChecked=node('ul',undefined,'project-check-not-checked');notChecked.append(...Object.values(projectCheckNotChecked).map(label=>node('li',label)));
  const limits=report.limits||{};
  $('project-check-result').replaceChildren(summary,readinessSection('Observed fingerprints',[hashes]),readinessSection('Profile comparison',[profileFacts,differences,...(permissions.children.length?[node('h4','Permission differences'),permissions]:[])]),readinessSection('Selected-byte file observations',files.children.length?[files]:[node('p','Selected file observations are unavailable.','muted')]),readinessSection('Inspection limits',[diagnosticList([['Selected file limit',comparisonInteger(limits.max_files)],['Per-file byte limit',comparisonBytes(limits.max_file_bytes)],['Total eligibility limit',comparisonBytes(limits.max_total_bytes)],['Archive byte limit',comparisonBytes(limits.max_archive_bytes)]],'diagnostic-facts project-check-facts')]),readinessSection('Not checked by this comparison',[notChecked,node('p','Relative file/check names remain private project information. The unsigned bundle and task fingerprints are not authenticity evidence. No files were extracted, applied or written.','muted')]));
  $('project-check-result').hidden=false;
}
$('project-check-open').addEventListener('click',async()=>{
  if(readOnlyPanelActive()||busy||projectRefreshBusy)return;
  const sequence=++projectCheckOpenSequence;projectCheckOpening=true;projectCheckReady=false;invalidateProjectCheck('Waiting for the current live update to finish…');renderProjectCheckProjects();$('project-check-file').value='';$('project-check-sha').value='';$('project-check-panel').hidden=false;$('normal-workspace').hidden=true;$('project-check-open').setAttribute('aria-expanded','true');setComparisonControls();$('project-check-close').focus();
  const available=await new Promise(resolve=>{let settled=false;const finish=value=>{if(settled)return;settled=true;clearTimeout(timer);if(projectCheckOpeningCancel===cancel)projectCheckOpeningCancel=null;resolve(value);};const cancel=()=>finish('cancelled');const timer=setTimeout(()=>finish('timeout'),10000);projectCheckOpeningCancel=cancel;normalRefreshInFlight.then(()=>finish('ready'));});
  if(sequence!==projectCheckOpenSequence||!projectCheckOpening)return;
  projectCheckOpening=false;projectCheckOpen=true;projectCheckReady=available==='ready';setComparisonControls();
  if(!projectCheckReady){$('project-check-status').textContent='The earlier live update did not finish within 10 seconds. Close this panel to return to the run view.';return;}
  $('project-check-status').textContent=projectCheckProjectId?'Select a private ZIP and submit explicitly. Selecting inputs does not upload them.':'No configured project is available.';
  if(!$('project-check-project').disabled)$('project-check-project').focus();
});
$('project-check-close').addEventListener('click',()=>{projectCheckOpenSequence++;if(projectCheckOpeningCancel)projectCheckOpeningCancel();projectCheckOpen=false;projectCheckOpening=false;projectCheckReady=false;invalidateProjectCheck();$('project-check-file').value='';$('project-check-sha').value='';$('project-check-panel').hidden=true;$('normal-workspace').hidden=false;$('project-check-open').setAttribute('aria-expanded','false');setComparisonControls();$('project-check-open').focus();refresh();});
function projectCheckInputsChanged(){projectCheckProjectId=$('project-check-project').value;const file=projectCheckFile(),pin=$('project-check-sha').value;invalidateProjectCheck(file&&!projectCheckValidFile(file)?'The private ZIP must contain 1 byte–2 MiB. No new upload was made.':!projectCheckValidPin(pin)?'Use 64 lowercase hexadecimal characters for the trusted SHA-256, or leave it empty. No new upload was made.':'Inputs changed. Check explicitly to inspect the selected project.');setProjectCheckControls();}
$('project-check-form').addEventListener('input',projectCheckInputsChanged);$('project-check-form').addEventListener('change',projectCheckInputsChanged);
$('project-check-form').addEventListener('submit',async event=>{
  event.preventDefault();const file=projectCheckFile(),pin=$('project-check-sha').value,projectId=projectCheckProjectId;
  if(!projectCheckOpen||!projectCheckReady||projectCheckBusy||!projectId||!projectCheckValidFile(file)||!projectCheckValidPin(pin))return;
  invalidateProjectCheck('Sending the selected private ZIP for this explicit read-only check…');const sequence=projectCheckSequence;projectCheckBusy=true;setProjectCheckControls();
  try{
    const headers={'X-Workbench-Token':token,'Content-Type':'application/zip'};if(pin)headers['X-Bundle-SHA256']=pin;
    const response=await fetch('/api/bundle-project-check/'+encodeURIComponent(projectId),{method:'POST',headers,body:file});
    const value=await response.json();
    if(!projectCheckOpen||sequence!==projectCheckSequence||projectId!==projectCheckProjectId||file!==projectCheckFile()||pin!==$('project-check-sha').value)return;
    if(!response.ok)throw new Error(value&&typeof value.error==='string'?value.error:'PROJECT_CHECK_INPUT');
    if(!validProjectCheckWrapper(value,projectId))throw new Error('PROJECT_CHECK_INPUT');
    renderProjectCheck(value);$('project-check-status').textContent='Showing a dated comparison of the selected bytes. No task checks were executed.';
  }catch(error){if(projectCheckOpen&&sequence===projectCheckSequence)$('project-check-status').textContent=projectCheckFailure(error);}
  finally{if(sequence===projectCheckSequence){projectCheckBusy=false;setProjectCheckControls();}}
});

const bundleWorkspaceStatuses={PREPARING:'Preparing',VERIFIED:'Checks passed when created',FAILED:'Failed · inspect retained records',INTERRUPTED:'Interrupted · inspect retained records'};
const bundleWorkspaceErrors={BUNDLE_WORKSPACE_INPUT:'The bundle workspace input could not be read safely.',BUNDLE_WORKSPACE_PATCH_INVALID:'The candidate patch could not be prepared safely.',BUNDLE_WORKSPACE_CANDIDATE_CHANGED:'The reconstructed candidate did not match its saved hashes.',BUNDLE_WORKSPACE_LIMIT:'The selected files or worker records exceeded a bounded workspace limit.',BUNDLE_WORKSPACE_REQUEST_CHANGED:'The pinned worker request changed. Inspect retained records.',BUNDLE_WORKSPACE_SOURCE_CHANGED:'Selected source changed after preview. Inspect it before continuing.',BUNDLE_WORKSPACE_SCOPE_CHANGED:'The private worktree file scope changed. Inspect retained records.',BUNDLE_WORKSPACE_GIT_CHANGED:'The private worktree Git state changed. Inspect retained records.',BUNDLE_WORKSPACE_GIT_FAILED:'The private Git workspace operation failed. Inspect retained records.',BUNDLE_WORKSPACE_CHECKS_FAILED:'The private worktree check rerun failed. Inspect retained output.',BUNDLE_WORKSPACE_EXECUTION_FAILED:'The private worktree operation failed. Inspect retained records.',BUNDLE_WORKSPACE_NEEDS_INSPECTION:'Saved bundle workspace records need inspection before creation.',JDK_REQUIRED:'The configured Java JDK is required to rerun this project’s fixed checks.',NO_OWNED_ACTIVE_BUNDLE_WORKSPACE:'This session does not own an active worker for that workspace.',BUNDLE_WORKSPACE_ID:'The selected private workspace ID is invalid.',BUNDLE_WORKSPACE_PROJECT_UNKNOWN:'The selected configured project is unavailable.',BUNDLE_WORKSPACE_PROJECT_CHANGED:'Project configuration or saved task changed. Inspect them before previewing again.',BUNDLE_WORKSPACE_INPUT_LIMIT:'The private ZIP must contain 1 byte–2 MiB.',BUNDLE_WORKSPACE_OUTPUT_LIMIT:'The workspace response exceeded the bounded display limit.',BUNDLE_WORKSPACE_RECORD_INVALID:'A saved private workspace record needs inspection.',BUNDLE_WORKSPACE_RECORD_LIMIT:'Saved workspace history exceeds the bounded inspection limit.',BUNDLE_WORKSPACE_START_FAILED:'The private worker did not start. Inspect retained records.',BUNDLE_WORKSPACE_INTERRUPTED:'The private worker ended before a final result was recorded.',PROJECT_UNKNOWN:'The selected configured project is unavailable.',PROJECT_CHANGED:'The selected project changed since preview. Inspect it before continuing.',PATCH_INVALID:'The candidate patch could not be prepared safely.',REQUEST_CHANGED:'The pinned worker request changed. Inspect retained records.',CHECKS_FAILED:'The private worktree check rerun failed. Inspect retained output.',EXECUTION_FAILED:'The private worktree operation failed. Inspect retained records.',GIT_FAILED:'The private Git workspace operation failed. Inspect retained records.',SOURCE_CHANGED:'Selected source changed after preview. Inspect it before continuing.',BUNDLE_WORKSPACE_BASELINE_REQUIRED:'Selected source must match the bundle baseline before a review workspace can be created.',BUNDLE_WORKSPACE_PREVIEW_REQUIRED:'Preview this bundle against the selected project before creation.',BUNDLE_WORKSPACE_PREVIEW_EXPIRED:'The pinned preview expired. Preview explicitly again before deciding to create.',BUNDLE_WORKSPACE_PREVIEW_CHANGED:'Preview evidence changed. Inspect the selected inputs and preview again.',BUNDLE_WORKSPACE_ACTIVE_OR_UNRESOLVED:'A private workspace is active or unresolved. Inspect its retained records.',BUNDLE_WORKSPACE_UNKNOWN:'The selected private workspace is unavailable.',BUNDLE_WORKSPACE_NOT_OWNED:'This session does not own an active worker for that workspace.',BUNDLE_WORKSPACE_FIELDS:'The workspace request did not match the required pinned preview.'};
function bundleWorkspaceFailure(error){return diagnosticText(bundleWorkspaceErrors,error&&error.message)||diagnosticText(projectCheckErrors,error&&error.message)||diagnosticText(bundleErrors,error&&error.message)||diagnosticText(errors,error&&error.message)||'The bundle workspace operation could not complete. Inspect the retained private records.';}
function bundleWorkspaceId(value){return typeof value==='string'&&/^[0-9a-f]{16}$/.test(value);}
function bundleWorkspaceFile(){return $('bundle-workspace-file').files&&$('bundle-workspace-file').files[0]||null;}
function clearBundleWorkspacePoll(){if(bundleWorkspacePollTimer!==null)clearTimeout(bundleWorkspacePollTimer);bundleWorkspacePollTimer=null;}
function invalidateBundleWorkspacePreview(text){bundleWorkspacePreviewSequence++;bundleWorkspacePreview=null;bundleWorkspacePreviewBusy=false;if(bundleWorkspaceExpiryTimer!==null)clearTimeout(bundleWorkspaceExpiryTimer);bundleWorkspaceExpiryTimer=null;$('bundle-workspace-preview-result').replaceChildren();$('bundle-workspace-preview-result').hidden=true;$('bundle-workspace-preview-status').textContent=text||'Select a project and private ZIP, then preview explicitly.';}
function bundleWorkspaceUnresolved(){return bundleWorkspaceReceipts.some(receipt=>receipt.status!=='VERIFIED')||Boolean(bundleWorkspaceReceipt&&bundleWorkspaceReceipt.status!=='VERIFIED');}
function bundleWorkspaceAdmissionObserved(){return Boolean(configuration&&Object.prototype.hasOwnProperty.call(configuration,'admission_block'));}
function setBundleWorkspaceControls(){
  const enabled=bundleWorkspaceOpen&&bundleWorkspaceReady;
  $('bundle-workspace-open').disabled=!configuration||readOnlyPanelActive()||busy||projectRefreshBusy||bundleWorkspaceActionBusy;
  $('bundle-workspace-open').textContent=bundleWorkspaceOpening?'Opening bundle workspace…':'Bundle review workspace';
  for(const id of ['bundle-workspace-project','bundle-workspace-file','bundle-workspace-sha'])$(id).disabled=!enabled||bundleWorkspaceActionBusy;
  $('bundle-workspace-preview-submit').disabled=!enabled||bundleWorkspaceActionBusy||bundleWorkspacePreviewBusy||!bundleWorkspaceProjectId||!projectCheckValidFile(bundleWorkspaceFile())||!projectCheckValidPin($('bundle-workspace-sha').value);
  const observed=bundleWorkspaceAdmissionObserved(),unresolved=bundleWorkspaceUnresolved(),recheckBlocked=workspaceRecheckUnresolved(),expired=bundleWorkspacePreview&&bundleWorkspacePreview.expires_at_ms<=Date.now();
  $('bundle-workspace-create').disabled=!enabled||bundleWorkspaceActionBusy||bundleWorkspacePreviewBusy||!bundleWorkspacePreview||expired||!observed||Boolean(admissionReason)||!bundleWorkspaceHistoryReady||unresolved||recheckBlocked||bundleWorkspaceUncertainCreation;
  $('bundle-workspace-admission').textContent=!observed?'Global admission has not been observed. Creation remains unavailable.':admissionReason?'Last observed global admission: blocked. '+(diagnosticText(errors,admissionReason)||'Inspect the private records.'):recheckBlocked?'A workspace recheck is active, failed or unresolved. New creation remains blocked for inspection.':unresolved?'Saved bundle workspace state is active, failed or unresolved. Creation remains blocked for inspection.':bundleWorkspaceUncertainCreation?'A creation outcome needs inspection. Refresh workspace history to inspect saved state before another decision.':!bundleWorkspaceHistoryReady?'Workspace history has not been inspected. Creation remains unavailable.':'Last observed global admission: no blocker recorded. This can become stale; the server rechecks all guards when you create.';
  $('bundle-workspace-history-refresh').disabled=!enabled||bundleWorkspaceHistoryBusy||bundleWorkspaceActionBusy;
  $('bundle-workspace-history-select').disabled=!enabled||bundleWorkspaceHistoryBusy||bundleWorkspaceActionBusy||!bundleWorkspaceReceipts.length;
  $('bundle-workspace-stop').disabled=!enabled||bundleWorkspaceActionBusy||!bundleWorkspaceReceipt||bundleWorkspaceReceipt.status!=='PREPARING'||bundleWorkspaceReceipt.owned_active!==true;setWorkspaceRecheckControls();
}
function renderBundleWorkspaceProjects(){const projects=configuration&&configuration.projects||[];if(!projects.some(project=>project.id===bundleWorkspaceProjectId))bundleWorkspaceProjectId=projects.some(project=>project.id===$('project').value)?$('project').value:(projects[0]&&projects[0].id)||'';$('bundle-workspace-project').replaceChildren(...projects.map(project=>{const option=node('option',project.name+' · '+project.id);option.value=project.id;return option;}));$('bundle-workspace-project').value=bundleWorkspaceProjectId;}
function validBundleWorkspacePreview(value,projectId){return Boolean(value&&value.version===1&&bundleWorkspaceId(value.preview_id)&&bundleHash(value.preview_sha256)&&value.project&&value.project.id===projectId&&bundleHash(value.bundle_sha256)&&bundleHash(value.task_sha256)&&bundleHash(value.config_sha256)&&bundleHash(value.patch_sha256)&&Number.isSafeInteger(value.expires_at_ms)&&value.expires_at_ms>Date.now()&&value.workspace_ready===true&&value.comparison&&value.comparison.version===1&&value.comparison.status==='BASELINE_MATCH'&&value.comparison.profile&&['format','scope','permissions','checks','budgets'].every(key=>value.comparison.profile[key]===true)&&Array.isArray(value.files)&&value.files.length>0&&value.files.length<=32&&value.files.every(file=>file&&typeof file.path==='string'&&typeof file.editable==='boolean'&&bundleHash(file.before_sha256)&&bundleHash(file.after_sha256)&&(file.editable||file.before_sha256===file.after_sha256)));}
function renderBundleWorkspacePreview(value){
  const summary=node('section',undefined,'bundle-workspace-preview-summary');summary.append(node('h3','Pinned baseline preview'),node('p',comparisonValue(value.project.name)+' · '+value.project.id,'readiness-project-name'),diagnosticList([['Selected bytes',projectCheckStatuses[value.comparison.status]],['Preview expires (UTC)',diagnosticStarted(value.expires_at_ms)],['Configured task pins match source',comparisonBoolean(value.comparison.task_pins_match)]],'diagnostic-facts project-check-facts'),diagnosticList([['Preview SHA-256',value.preview_sha256],['Bundle SHA-256',value.bundle_sha256],['Patch SHA-256',value.patch_sha256],['Selected task SHA-256',value.task_sha256],['Selected config SHA-256',value.config_sha256]],'context-file-facts bundle-workspace-hashes'),node('p','Preview is read-only and expires after five minutes. Creation consumes these exact pins and reruns checks only in the new private worktree.','muted'));
  const list=node('ul',undefined,'bundle-file-list');for(const file of value.files){const item=node('li');item.append(node('h4',file.path),diagnosticList([['Scope',comparisonPermission(file.editable)],['Baseline SHA-256',file.before_sha256],['Candidate SHA-256',file.after_sha256]],'context-file-facts bundle-workspace-hashes'));list.append(item);}
  $('bundle-workspace-preview-result').replaceChildren(summary,readinessSection('Selected private worktree scope',[list]));$('bundle-workspace-preview-result').hidden=false;
}
function validBundleWorkspaceReceipt(value){return Boolean(value&&value.version===1&&bundleWorkspaceId(value.id)&&typeof value.project_id==='string'&&diagnosticText(bundleWorkspaceStatuses,value.status)&&value.source_applied===false);}
function renderBundleWorkspaceHistoryOptions(){const options=bundleWorkspaceReceipts.map(receipt=>{const option=node('option',receipt.project_id+' · '+bundleWorkspaceStatuses[receipt.status]+' · '+receipt.id.slice(0,8));option.value=receipt.id;return option;});if(!options.length){const option=node('option','No private bundle workspaces recorded');option.value='';options.push(option);}$('bundle-workspace-history-select').replaceChildren(...options);$('bundle-workspace-history-select').value=bundleWorkspaceSelectedId;}
function rememberBundleWorkspaceReceipt(receipt){const index=bundleWorkspaceReceipts.findIndex(value=>value.id===receipt.id);if(index<0)bundleWorkspaceReceipts.unshift(receipt);else bundleWorkspaceReceipts[index]={...bundleWorkspaceReceipts[index],...receipt};renderBundleWorkspaceHistoryOptions();}
function renderBundleWorkspaceReceipt(receipt){
  syncWorkspaceRecheckWorkspace(receipt);bundleWorkspaceReceipt=receipt;
  const heading=node('div',undefined,'bundle-workspace-receipt-heading');heading.append(node('h3','Selected private workspace'),node('span',bundleWorkspaceStatuses[receipt.status],'state-pill '+(receipt.status==='VERIFIED'?'good':receipt.status==='FAILED'||receipt.status==='INTERRUPTED'?'bad':'')));
  const children=[heading,diagnosticList([['Workspace ID',receipt.id],['Project',receipt.project_id],['Created (UTC)',Number.isSafeInteger(receipt.created)?diagnosticStarted(receipt.created*1000):'Not recorded'],['Finished (UTC)',Number.isSafeInteger(receipt.finished)?diagnosticStarted(receipt.finished*1000):'Not recorded'],['Owned active worker',comparisonBoolean(receipt.owned_active)],['Applied to original source',comparisonBoolean(receipt.source_applied)]],'diagnostic-facts project-check-facts'),node('p',receipt.status==='PREPARING'?(receipt.owned_active===true?'The owned worker is preparing the private worktree and rerunning checks.':'Preparing was saved, but this session does not own an active worker. Inspect retained records; no status polling or recovery will start.'):(receipt.status==='VERIFIED'?'Checks passed when this workspace was created. Candidate changes remain uncommitted. Later edits need their own checks and review.':'The operation failed or was interrupted. Private files and logs are retained; inspect them before deciding what to do next.'),'muted'),diagnosticList([['Private worktree path',comparisonValue(receipt.path)],['Review branch',comparisonValue(receipt.branch)],['Baseline commit',comparisonValue(receipt.baseline_commit)],['Bundle SHA-256',comparisonValue(receipt.bundle_sha256)],['Preview SHA-256',comparisonValue(receipt.preview_sha256)]],'context-file-facts bundle-workspace-hashes')];
  if(receipt.reason)children.push(node('p','Recorded reason: '+bundleWorkspaceFailure({message:receipt.reason}),'muted'));
  const checks=receipt.checks&&typeof receipt.checks==='object'&&!Array.isArray(receipt.checks)?Object.entries(receipt.checks):[];
  if(checks.length){const results=node('div',undefined,'bundle-workspace-checks');for(const [name,raw] of checks){const check=raw&&typeof raw==='object'?raw:{};const card=node('section',undefined,'check-card');card.append(node('h4',name),diagnosticList([['Exit code',Number.isSafeInteger(check.exit_code)?String(check.exit_code):'Unknown'],['Tests reported',comparisonInteger(check.tests_ran)],['Timed out',comparisonBoolean(check.timed_out)],['Output limited',comparisonBoolean(check.output_limited)],['Infrastructure error',comparisonBoolean(check.infrastructure_error)]],'diagnostic-facts project-check-facts'),node('pre',typeof check.output==='string'?check.output:'No check output recorded.','code-view'));if(check.display_truncated===true)card.append(node('p','Receipt display truncated; full output kept privately.','muted'));results.append(card);}children.push(readinessSection('Observed worktree check reruns',[results]));}else children.push(node('p','No worktree check results are recorded yet.','muted'));
  $('bundle-workspace-receipt').replaceChildren(...children);$('bundle-workspace-receipt').hidden=false;rememberBundleWorkspaceReceipt(receipt);setBundleWorkspaceControls();
}
function scheduleBundleWorkspacePoll(){clearBundleWorkspacePoll();const receipt=bundleWorkspaceReceipt;if(bundleWorkspaceOpen&&bundleWorkspaceReady&&receipt&&receipt.id===bundleWorkspaceSelectedId&&receipt.status==='PREPARING'&&receipt.owned_active===true){const id=receipt.id;bundleWorkspacePollTimer=setTimeout(()=>{bundleWorkspacePollTimer=null;if(bundleWorkspaceOpen&&bundleWorkspaceSelectedId===id&&bundleWorkspaceReceipt&&bundleWorkspaceReceipt.status==='PREPARING'&&bundleWorkspaceReceipt.owned_active===true)loadBundleWorkspaceReceipt(id);},1500);}}
async function loadBundleWorkspaceReceipt(id){
  clearBundleWorkspacePoll();const sequence=++bundleWorkspaceReceiptSequence;
  try{const receipt=await api('/api/bundle-workspace/'+encodeURIComponent(id));if(!bundleWorkspaceOpen||sequence!==bundleWorkspaceReceiptSequence||bundleWorkspaceSelectedId!==id)return;if(!validBundleWorkspaceReceipt(receipt)||receipt.id!==id)throw new Error('BUNDLE_WORKSPACE_RESPONSE');renderBundleWorkspaceReceipt(receipt);$('bundle-workspace-history-status').textContent='Showing the selected workspace receipt.';scheduleBundleWorkspacePoll();}
  catch(error){if(bundleWorkspaceOpen&&sequence===bundleWorkspaceReceiptSequence){$('bundle-workspace-history-status').textContent=bundleWorkspaceFailure(error)+' Status polling stopped.';bundleWorkspaceReceipt=null;syncWorkspaceRecheckWorkspace(null);$('bundle-workspace-receipt').hidden=true;bundleWorkspaceHistoryReady=false;setBundleWorkspaceControls();}}
}
async function loadBundleWorkspaceHistory(){
  if(!bundleWorkspaceOpen||!bundleWorkspaceReady||bundleWorkspaceHistoryBusy)return;
  const sequence=++bundleWorkspaceHistorySequence;bundleWorkspaceHistoryBusy=true;clearBundleWorkspacePoll();$('bundle-workspace-history-status').textContent='Reading saved bundle workspace history…';setBundleWorkspaceControls();
  try{const value=await api('/api/bundle-workspaces');if(!bundleWorkspaceOpen||sequence!==bundleWorkspaceHistorySequence)return;if(!value||value.version!==1||!Array.isArray(value.workspaces)||value.workspaces.length>200||!value.workspaces.every(validBundleWorkspaceReceipt))throw new Error('BUNDLE_WORKSPACE_RESPONSE');bundleWorkspaceReceipts=value.workspaces;bundleWorkspaceHistoryReady=true;if(!bundleWorkspaceReceipts.some(receipt=>receipt.id===bundleWorkspaceSelectedId))bundleWorkspaceSelectedId=(bundleWorkspaceReceipts[0]&&bundleWorkspaceReceipts[0].id)||'';if(!bundleWorkspaceUnresolved())bundleWorkspaceUncertainCreation=false;renderBundleWorkspaceHistoryOptions();$('bundle-workspace-history-status').textContent=bundleWorkspaceReceipts.length+' saved private workspaces.';if(bundleWorkspaceSelectedId)await loadBundleWorkspaceReceipt(bundleWorkspaceSelectedId);else{bundleWorkspaceReceipt=null;syncWorkspaceRecheckWorkspace(null);$('bundle-workspace-receipt').hidden=true;}}
  catch(error){if(bundleWorkspaceOpen&&sequence===bundleWorkspaceHistorySequence){bundleWorkspaceHistoryReady=false;$('bundle-workspace-history-status').textContent=bundleWorkspaceFailure(error);}}
  finally{if(sequence===bundleWorkspaceHistorySequence){bundleWorkspaceHistoryBusy=false;setBundleWorkspaceControls();}}
}
$('bundle-workspace-open').addEventListener('click',async()=>{
  if(readOnlyPanelActive()||busy||projectRefreshBusy||bundleWorkspaceActionBusy)return;
  const sequence=++bundleWorkspaceOpenSequence;bundleWorkspaceOpening=true;bundleWorkspaceReady=false;bundleWorkspaceHistoryReady=false;invalidateBundleWorkspacePreview('Waiting for the current live update to finish…');renderBundleWorkspaceProjects();$('bundle-workspace-file').value='';$('bundle-workspace-sha').value='';$('bundle-workspace-panel').hidden=false;$('normal-workspace').hidden=true;$('bundle-workspace-open').setAttribute('aria-expanded','true');setComparisonControls();$('bundle-workspace-close').focus();
  const available=await new Promise(resolve=>{let settled=false;const finish=value=>{if(settled)return;settled=true;clearTimeout(timer);if(bundleWorkspaceOpeningCancel===cancel)bundleWorkspaceOpeningCancel=null;resolve(value);};const cancel=()=>finish('cancelled');const timer=setTimeout(()=>finish('timeout'),10000);bundleWorkspaceOpeningCancel=cancel;normalRefreshInFlight.then(()=>finish('ready'));});
  if(sequence!==bundleWorkspaceOpenSequence||!bundleWorkspaceOpening)return;bundleWorkspaceOpening=false;bundleWorkspaceOpen=true;bundleWorkspaceReady=available==='ready';setComparisonControls();if(!bundleWorkspaceReady){$('bundle-workspace-preview-status').textContent='The earlier live update did not finish within 10 seconds. Close this panel to return to the run view.';return;}$('bundle-workspace-preview-status').textContent='Select a private ZIP and preview explicitly. Selecting inputs starts no upload or worker.';await loadBundleWorkspaceHistory();if(bundleWorkspaceOpen&&sequence===bundleWorkspaceOpenSequence&&!$('bundle-workspace-project').disabled)$('bundle-workspace-project').focus();
});
$('bundle-workspace-close').addEventListener('click',()=>{bundleWorkspaceOpenSequence++;if(bundleWorkspaceOpeningCancel)bundleWorkspaceOpeningCancel();bundleWorkspaceOpen=false;bundleWorkspaceOpening=false;bundleWorkspaceReady=false;bundleWorkspaceHistorySequence++;bundleWorkspaceReceiptSequence++;bundleWorkspaceHistoryBusy=false;clearBundleWorkspacePoll();closeWorkspaceRecheck();invalidateBundleWorkspacePreview();$('bundle-workspace-file').value='';$('bundle-workspace-sha').value='';$('bundle-workspace-panel').hidden=true;$('normal-workspace').hidden=false;$('bundle-workspace-open').setAttribute('aria-expanded','false');setComparisonControls();if(!bundleWorkspaceActionBusy)$('bundle-workspace-open').focus();refresh();});
function bundleWorkspaceInputsChanged(){invalidateWorkspaceRecheckPreview('Workspace inputs changed. Inspect the selected workspace explicitly again.');bundleWorkspaceProjectId=$('bundle-workspace-project').value;const file=bundleWorkspaceFile(),pin=$('bundle-workspace-sha').value;invalidateBundleWorkspacePreview(file&&!projectCheckValidFile(file)?'The private ZIP must contain 1 byte–2 MiB. No new preview was sent.':!projectCheckValidPin(pin)?'Use 64 lowercase hexadecimal characters for the optional trusted SHA-256. No new preview was sent.':'Inputs changed. Preview explicitly before deciding to create a workspace.');setBundleWorkspaceControls();}
$('bundle-workspace-form').addEventListener('input',bundleWorkspaceInputsChanged);$('bundle-workspace-form').addEventListener('change',bundleWorkspaceInputsChanged);
$('bundle-workspace-form').addEventListener('submit',async event=>{
  event.preventDefault();const file=bundleWorkspaceFile(),pin=$('bundle-workspace-sha').value,projectId=bundleWorkspaceProjectId;if(!bundleWorkspaceOpen||!bundleWorkspaceReady||bundleWorkspacePreviewBusy||bundleWorkspaceActionBusy||!projectId||!projectCheckValidFile(file)||!projectCheckValidPin(pin))return;invalidateWorkspaceRecheckPreview('A new creation preview was requested. Inspect the selected workspace again before a recheck.');invalidateBundleWorkspacePreview('Reading the bundle and selected baseline for a pinned preview…');const sequence=bundleWorkspacePreviewSequence;bundleWorkspacePreviewBusy=true;setBundleWorkspaceControls();
  try{const headers={'X-Workbench-Token':token,'Content-Type':'application/zip'};if(pin)headers['X-Bundle-SHA256']=pin;const response=await fetch('/api/bundle-workspace-preview/'+encodeURIComponent(projectId),{method:'POST',headers,body:file});const value=await response.json();if(!bundleWorkspaceOpen||sequence!==bundleWorkspacePreviewSequence||projectId!==bundleWorkspaceProjectId||file!==bundleWorkspaceFile()||pin!==$('bundle-workspace-sha').value)return;if(!response.ok)throw new Error(value&&typeof value.error==='string'?value.error:'BUNDLE_WORKSPACE_RESPONSE');if(!validBundleWorkspacePreview(value,projectId))throw new Error('BUNDLE_WORKSPACE_RESPONSE');bundleWorkspacePreview=value;renderBundleWorkspacePreview(value);$('bundle-workspace-preview-status').textContent='Baseline preview recorded. Review its pins, scope and admission observation before creation.';bundleWorkspaceExpiryTimer=setTimeout(()=>{if(bundleWorkspacePreview===value){invalidateBundleWorkspacePreview('The pinned preview expired. Preview explicitly again before deciding to create.');setBundleWorkspaceControls();}},Math.max(0,value.expires_at_ms-Date.now()));}
  catch(error){if(bundleWorkspaceOpen&&sequence===bundleWorkspacePreviewSequence)invalidateBundleWorkspacePreview(bundleWorkspaceFailure(error));}finally{if(sequence===bundleWorkspacePreviewSequence)bundleWorkspacePreviewBusy=false;setBundleWorkspaceControls();}
});
$('bundle-workspace-create').addEventListener('click',async()=>{
  const preview=bundleWorkspacePreview;if($('bundle-workspace-create').disabled||!preview||preview.expires_at_ms<=Date.now()||bundleWorkspaceActionBusy)return;invalidateBundleWorkspacePreview('Creating the private review workspace from the consumed preview…');bundleWorkspaceActionBusy=true;setBundleWorkspaceControls();
  try{const receipt=await api('/api/bundle-workspace-create',{preview_id:preview.preview_id,preview_sha256:preview.preview_sha256});if(!validBundleWorkspaceReceipt(receipt))throw new Error('BUNDLE_WORKSPACE_RESPONSE');rememberBundleWorkspaceReceipt(receipt);bundleWorkspaceSelectedId=receipt.id;bundleWorkspaceUncertainCreation=false;if(bundleWorkspaceOpen){bundleWorkspaceReceiptSequence++;renderBundleWorkspaceReceipt(receipt);$('bundle-workspace-preview-status').textContent='Preview consumed. The private worker reruns checks without applying changes to the original project.';scheduleBundleWorkspacePoll();}}
  catch(error){bundleWorkspaceUncertainCreation=true;if(bundleWorkspaceOpen)$('bundle-workspace-preview-status').textContent=bundleWorkspaceFailure(error)+' The preview was consumed; inspect workspace history before another decision.';}
  finally{bundleWorkspaceActionBusy=false;setComparisonControls();}
});
$('bundle-workspace-history-refresh').addEventListener('click',loadBundleWorkspaceHistory);
$('bundle-workspace-history-select').addEventListener('change',()=>{clearBundleWorkspacePoll();bundleWorkspaceReceiptSequence++;bundleWorkspaceSelectedId=$('bundle-workspace-history-select').value;bundleWorkspaceReceipt=null;syncWorkspaceRecheckWorkspace(null);$('bundle-workspace-receipt').hidden=true;setBundleWorkspaceControls();if(bundleWorkspaceSelectedId)loadBundleWorkspaceReceipt(bundleWorkspaceSelectedId);});
$('bundle-workspace-stop').addEventListener('click',async()=>{const receipt=bundleWorkspaceReceipt;if(!bundleWorkspaceOpen||!receipt||receipt.status!=='PREPARING'||receipt.owned_active!==true||bundleWorkspaceActionBusy)return;bundleWorkspaceActionBusy=true;clearBundleWorkspacePoll();setBundleWorkspaceControls();try{await api('/api/bundle-workspace-stop',{id:receipt.id});if(bundleWorkspaceOpen&&bundleWorkspaceSelectedId===receipt.id)await loadBundleWorkspaceReceipt(receipt.id);}catch(error){if(bundleWorkspaceOpen)$('bundle-workspace-history-status').textContent=bundleWorkspaceFailure(error)+' Private records are retained.';}finally{bundleWorkspaceActionBusy=false;setComparisonControls();}});

const workspaceRecheckStatuses={PREPARING:'Recheck preparing',VERIFIED:'Recheck passed when recorded',FAILED:'Recheck failed · inspect retained records',INTERRUPTED:'Recheck interrupted · inspect retained records'};
const workspaceRecheckErrors={RECHECK_INPUT:'The recheck request did not match the required bounded input.',RECHECK_RECORD_INVALID:'A saved recheck or workspace record needs inspection.',RECHECK_LIMIT:'The workspace snapshot or records exceed the recheck limit.',RECHECK_OUTPUT_LIMIT:'The recheck response exceeds its bounded display limit.',RECHECK_CREATION_REQUIRED:'Select a bundle workspace whose original creation was verified.',RECHECK_STALE:'The inspected workspace or saved history changed. Inspect explicitly again.',RECHECK_PROTECTED_CHANGED:'A protected workspace file changed. Inspection cannot authorize a recheck.',RECHECK_GIT_CHANGED:'Private workspace Git controls or baseline changed. Inspect retained records.',RECHECK_INDEX_INVALID:'The private workspace index changed. Inspect retained records.',RECHECK_CHECKS_FAILED:'The snapshot check rerun failed. Inspect its retained output.',RECHECK_INTERRUPTED:'The recheck was interrupted. Its private records are retained.',RECHECK_EXECUTION_FAILED:'The recheck could not finish. Inspect retained records.',RECHECK_PREVIEW_REQUIRED:'Inspect the selected current workspace before running a recheck.',RECHECK_PREVIEW_EXPIRED:'The pinned inspection expired. Inspect explicitly again.',RECHECK_PREVIEW_CHANGED:'The pinned inspection changed. Inspect explicitly again.',RECHECK_FIELDS:'The recheck request did not contain the required exact pins.',RECHECK_PROJECT_CHANGED:'The saved project task or configuration changed. Inspect the private records.',RECHECK_ACTIVE_OR_UNRESOLVED:'A recheck is active, failed or unresolved. Inspect its retained records.',RECHECK_ID:'The selected recheck ID is unavailable.',NO_OWNED_ACTIVE_RECHECK:'This session does not own an active worker for that recheck.'};
function workspaceRecheckFailure(error){return diagnosticText(workspaceRecheckErrors,error&&error.message)||diagnosticText(bundleWorkspaceErrors,error&&error.message)||diagnosticText(errors,error&&error.message)||'The workspace recheck operation could not complete. Inspect retained private records.';}
function clearWorkspaceRecheckPoll(){if(workspaceRecheckPollTimer!==null)clearTimeout(workspaceRecheckPollTimer);workspaceRecheckPollTimer=null;}
function invalidateWorkspaceRecheckPreview(text){workspaceRecheckPreviewSequence++;workspaceRecheckPreview=null;workspaceRecheckPreviewBusy=false;if(workspaceRecheckExpiryTimer!==null)clearTimeout(workspaceRecheckExpiryTimer);workspaceRecheckExpiryTimer=null;$('workspace-recheck-preview').replaceChildren();$('workspace-recheck-preview').hidden=true;$('workspace-recheck-status').textContent=text||'Inspect the current selected workspace explicitly before deciding to recheck.';}
function closeWorkspaceRecheck(){workspaceRecheckContextSequence++;workspaceRecheckHistorySequence++;workspaceRecheckReceiptSequence++;clearWorkspaceRecheckPoll();invalidateWorkspaceRecheckPreview();workspaceRecheckWorkspaceId='';workspaceRecheckHistoryReady=false;workspaceRecheckHistoryBusy=false;workspaceRecheckHistorySha=null;workspaceRecheckReceipts=[];workspaceRecheckSelectedId='';workspaceRecheckReceipt=null;$('workspace-recheck-receipt').replaceChildren();$('workspace-recheck-receipt').hidden=true;$('workspace-recheck-history-select').replaceChildren();$('workspace-recheck-history-status').textContent='Recheck history is read only after an explicit inspection or refresh.';}
function syncWorkspaceRecheckWorkspace(receipt){const id=receipt&&receipt.status==='VERIFIED'?receipt.id:'';if(id===workspaceRecheckWorkspaceId)return;closeWorkspaceRecheck();workspaceRecheckWorkspaceId=id;$('workspace-recheck-status').textContent=id?'Creation verification remains historical. Inspect the current selected workspace explicitly.':'Select a workspace whose original creation status is Verified.';}
function workspaceRecheckUnresolved(){return workspaceRecheckUncertainStart||Array.from(workspaceRecheckKnown.values()).some(receipt=>receipt.status!=='VERIFIED');}
function setWorkspaceRecheckControls(){
  const enabled=bundleWorkspaceOpen&&bundleWorkspaceReady,eligible=Boolean(workspaceRecheckWorkspaceId&&bundleWorkspaceReceipt&&bundleWorkspaceReceipt.id===workspaceRecheckWorkspaceId&&bundleWorkspaceReceipt.status==='VERIFIED'),unresolved=workspaceRecheckUnresolved(),expired=workspaceRecheckPreview&&workspaceRecheckPreview.expires_at_ms<=Date.now();
  $('workspace-recheck-inspect').disabled=!enabled||!eligible||bundleWorkspaceActionBusy||workspaceRecheckPreviewBusy||workspaceRecheckHistoryBusy;
  $('workspace-recheck-history-refresh').disabled=!enabled||!eligible||bundleWorkspaceActionBusy||workspaceRecheckHistoryBusy||workspaceRecheckPreviewBusy;
  $('workspace-recheck-history-select').disabled=!enabled||!eligible||bundleWorkspaceActionBusy||workspaceRecheckHistoryBusy||!workspaceRecheckReceipts.length;
  $('workspace-recheck-start').disabled=!enabled||!eligible||bundleWorkspaceActionBusy||workspaceRecheckPreviewBusy||workspaceRecheckHistoryBusy||!workspaceRecheckPreview||expired||!workspaceRecheckHistoryReady||workspaceRecheckPreview.history_sha256!==workspaceRecheckHistorySha||!bundleWorkspaceAdmissionObserved()||Boolean(admissionReason)||!bundleWorkspaceHistoryReady||bundleWorkspaceUnresolved()||unresolved;
  $('workspace-recheck-stop').disabled=!enabled||bundleWorkspaceActionBusy||!workspaceRecheckReceipt||workspaceRecheckReceipt.workspace_id!==workspaceRecheckWorkspaceId||workspaceRecheckReceipt.status!=='PREPARING'||workspaceRecheckReceipt.owned_active!==true;
  $('workspace-recheck-admission').textContent=!eligible?'Only a selected bundle workspace with verified original creation is eligible.':!bundleWorkspaceAdmissionObserved()?'Global admission has not been observed. Execution remains unavailable.':admissionReason?'Last observed global admission: blocked. '+(diagnosticText(errors,admissionReason)||'Inspect the retained private records.'):(bundleWorkspaceUnresolved()||unresolved)?'An active, failed or unresolved creation or recheck blocks new execution. Read-only inspection remains available.':!workspaceRecheckPreview?'A current pinned inspection is required. Inspection remains available under a hold.':!workspaceRecheckHistoryReady?'Read recheck history explicitly before execution.':'Last observed global admission: no blocker recorded. This can become stale; the server rechecks admission, snapshot, metadata and history pins at Run recheck.';
}
function validWorkspaceRecheckReceipt(value,workspaceId){return Boolean(value&&value.version===1&&bundleWorkspaceId(value.id)&&bundleWorkspaceId(value.workspace_id)&&(!workspaceId||value.workspace_id===workspaceId)&&diagnosticText(workspaceRecheckStatuses,value.status)&&value.source_applied===false);}
function validWorkspaceRecheckPreview(value,workspaceId){
  const inspection=value&&value.inspection;
  return Boolean(value&&value.version===1&&value.workspace_id===workspaceId&&bundleWorkspaceId(value.preview_id)&&bundleHash(value.preview_sha256)&&bundleHash(value.history_sha256)&&Number.isSafeInteger(value.expires_at_ms)&&value.expires_at_ms>Date.now()&&inspection&&inspection.version===1&&inspection.workspace_id===workspaceId&&inspection.source_applied===false&&['creation_sha256','request_sha256','bundle_sha256','task_sha256','config_sha256','patch_sha256','snapshot_sha256'].every(key=>bundleHash(inspection[key]))&&typeof inspection.baseline_commit==='string'&&/^[0-9a-f]{40}$/.test(inspection.baseline_commit)&&typeof inspection.branch==='string'&&Number.isSafeInteger(inspection.changed_files)&&inspection.changed_files>=0&&Number.isSafeInteger(inspection.total_bytes)&&inspection.total_bytes>=0&&Number.isSafeInteger(inspection.max_turns)&&inspection.max_turns>0&&Number.isSafeInteger(inspection.request_seconds)&&inspection.request_seconds>0&&Array.isArray(inspection.files)&&inspection.files.length>0&&inspection.files.length<=32&&inspection.files.every(file=>file&&typeof file.path==='string'&&typeof file.editable==='boolean'&&bundleHash(file.created_sha256)&&bundleHash(file.current_sha256)&&Number.isSafeInteger(file.bytes)&&file.bytes>=0&&typeof file.changed==='boolean'&&file.changed===(file.created_sha256!==file.current_sha256)&&(file.editable||!file.changed))&&inspection.changed_files===inspection.files.filter(file=>file.changed).length&&Array.isArray(inspection.checks)&&inspection.checks.length>0&&inspection.checks.length<=4&&inspection.checks.every(check=>check&&typeof check.name==='string'&&Object.prototype.hasOwnProperty.call(check,'spec'))&&Array.isArray(inspection.guards)&&inspection.guards.length<=256&&inspection.guards.every(guard=>guard&&typeof guard.path==='string'&&bundleHash(guard.sha256)&&Number.isSafeInteger(guard.bytes)&&guard.bytes>=0));
}
function renderWorkspaceRecheckPreview(value){
  const inspection=value.inspection,summary=node('section',undefined,'workspace-recheck-preview-summary');
  summary.append(node('h4','Pinned current workspace inspection'),diagnosticList([['Workspace ID',value.workspace_id],['Expires (UTC)',diagnosticStarted(value.expires_at_ms)],['Editable files changed since creation',comparisonInteger(inspection.changed_files)],['Selected snapshot total',comparisonBytes(inspection.total_bytes)],['Original source changed by this action','No'],['Saved task turn budget',comparisonInteger(inspection.max_turns)],['Saved task request timeout',comparisonInteger(inspection.request_seconds)+' s']],'diagnostic-facts project-check-facts'),diagnosticList([['Preview SHA-256',value.preview_sha256],['Global recheck history SHA-256',value.history_sha256],['Current snapshot SHA-256',inspection.snapshot_sha256],['Original creation record SHA-256',inspection.creation_sha256],['Original request SHA-256',inspection.request_sha256],['Bundle SHA-256',inspection.bundle_sha256],['Task SHA-256',inspection.task_sha256],['Config SHA-256',inspection.config_sha256],['Patch SHA-256',inspection.patch_sha256],['Baseline commit',inspection.baseline_commit],['Private review branch',inspection.branch]],'context-file-facts bundle-workspace-hashes'));
  const files=node('ul',undefined,'bundle-file-list');for(const file of inspection.files){const item=node('li');item.append(node('h4',file.path),diagnosticList([['Permission',comparisonPermission(file.editable)],['Current bytes',comparisonBytes(file.bytes)],['Compared with creation',file.editable?(file.changed?'Editable file changed':'Editable file unchanged'):'Protected file unchanged'],['Created candidate SHA-256',file.created_sha256],['Current SHA-256',file.current_sha256]],'context-file-facts bundle-workspace-hashes'));files.append(item);}
  const checks=node('div',undefined,'workspace-recheck-specs');for(const check of inspection.checks){const card=node('section',undefined,'check-card');card.append(node('h4',check.name),node('pre',JSON.stringify(check.spec,null,2),'code-view'));checks.append(card);}
  const guards=node('ul',undefined,'bundle-file-list');for(const guard of inspection.guards){const item=node('li');item.append(node('h4',guard.path),diagnosticList([['Metadata bytes',comparisonBytes(guard.bytes)],['SHA-256',guard.sha256]],'context-file-facts bundle-workspace-hashes'));guards.append(item);}
  $('workspace-recheck-preview').replaceChildren(summary,readinessSection('Current selected-file snapshot',[files]),readinessSection('Fixed checks to rerun',[checks]),readinessSection('Pinned private job metadata',[guards]),node('p','This sequential inspection can become stale and does not lock files. It ran no Git command or check and wrote no persistent records. Run recheck executes these fixed checks against the pinned current snapshot in the private workspace. Creation verification remains historical; new results do not prove provider completion, source correctness or Git adoption.','muted'));$('workspace-recheck-preview').hidden=false;
}
function rememberWorkspaceRecheckReceipt(receipt){workspaceRecheckKnown.set(receipt.id,receipt);const index=workspaceRecheckReceipts.findIndex(row=>row.id===receipt.id);if(index<0)workspaceRecheckReceipts.unshift(receipt);else workspaceRecheckReceipts[index]={...workspaceRecheckReceipts[index],...receipt};renderWorkspaceRecheckOptions();}
function renderWorkspaceRecheckOptions(){const options=workspaceRecheckReceipts.map(receipt=>{const option=node('option',workspaceRecheckStatuses[receipt.status]+' · '+receipt.id.slice(0,8));option.value=receipt.id;return option;});if(!options.length){const option=node('option','No separate recheck attempts recorded');option.value='';options.push(option);}$('workspace-recheck-history-select').replaceChildren(...options);$('workspace-recheck-history-select').value=workspaceRecheckSelectedId;}
function renderWorkspaceRecheckReceipt(receipt){
  workspaceRecheckReceipt=receipt;rememberWorkspaceRecheckReceipt(receipt);const heading=node('div',undefined,'bundle-workspace-receipt-heading');heading.append(node('h4','Selected separate recheck attempt'),node('span',workspaceRecheckStatuses[receipt.status],'state-pill '+(receipt.status==='VERIFIED'?'good':receipt.status==='FAILED'||receipt.status==='INTERRUPTED'?'bad':'')));
  const children=[heading,diagnosticList([['Recheck ID',receipt.id],['Workspace ID',receipt.workspace_id],['Created (UTC)',Number.isSafeInteger(receipt.created)?diagnosticStarted(receipt.created*1000):'Not recorded'],['Finished (UTC)',Number.isSafeInteger(receipt.finished)?diagnosticStarted(receipt.finished*1000):'Not recorded'],['Owned active worker',comparisonBoolean(receipt.owned_active)],['Applied to original source',comparisonBoolean(receipt.source_applied)]],'diagnostic-facts project-check-facts'),node('p',receipt.status==='PREPARING'?(receipt.owned_active===true?'The owned recheck worker is rerunning the fixed checks on the pinned workspace snapshot.':'Preparing was saved, but this session does not own an active recheck worker. No polling or recovery will start.'):(receipt.status==='VERIFIED'?'This separate recheck passed when recorded. It does not update the original creation result. Later edits need another explicit inspection.':'The recheck failed or was interrupted. Its records and logs remain private and preserved; new execution remains blocked.'),'muted'),diagnosticList([['Preview SHA-256',comparisonValue(receipt.preview_sha256)],['Original creation SHA-256',comparisonValue(receipt.creation_sha256)],['Pinned history SHA-256',comparisonValue(receipt.history_sha256)],['Snapshot SHA-256',comparisonValue(receipt.snapshot_sha256)]],'context-file-facts bundle-workspace-hashes')];
  if(receipt.reason)children.push(node('p','Recorded reason: '+workspaceRecheckFailure({message:receipt.reason}),'muted'));
  const checks=receipt.checks&&typeof receipt.checks==='object'&&!Array.isArray(receipt.checks)?Object.entries(receipt.checks):[];if(checks.length){const results=node('div',undefined,'bundle-workspace-checks');for(const [name,raw] of checks){const check=raw&&typeof raw==='object'?raw:{};const card=node('section',undefined,'check-card');card.append(node('h4',name),diagnosticList([['Exit code',Number.isSafeInteger(check.exit_code)?String(check.exit_code):'Unknown'],['Tests reported',comparisonInteger(check.tests_ran)],['Timed out',comparisonBoolean(check.timed_out)],['Output limited',comparisonBoolean(check.output_limited)],['Infrastructure error',comparisonBoolean(check.infrastructure_error)]],'diagnostic-facts project-check-facts'),node('pre',typeof check.output==='string'?check.output:'No check output recorded.','code-view'));if(check.display_truncated===true)card.append(node('p','Receipt display truncated; full output kept privately.','muted'));results.append(card);}children.push(readinessSection('Observed recheck results',[results]));}else children.push(node('p','No results are recorded for this attempt yet.','muted'));
  $('workspace-recheck-receipt').replaceChildren(...children);$('workspace-recheck-receipt').hidden=false;setBundleWorkspaceControls();
}
function scheduleWorkspaceRecheckPoll(){clearWorkspaceRecheckPoll();const receipt=workspaceRecheckReceipt;if(bundleWorkspaceOpen&&bundleWorkspaceReady&&receipt&&receipt.workspace_id===workspaceRecheckWorkspaceId&&receipt.id===workspaceRecheckSelectedId&&receipt.status==='PREPARING'&&receipt.owned_active===true){const id=receipt.id,workspaceId=receipt.workspace_id;workspaceRecheckPollTimer=setTimeout(()=>{workspaceRecheckPollTimer=null;if(bundleWorkspaceOpen&&workspaceRecheckWorkspaceId===workspaceId&&workspaceRecheckSelectedId===id&&workspaceRecheckReceipt&&workspaceRecheckReceipt.status==='PREPARING'&&workspaceRecheckReceipt.owned_active===true)loadWorkspaceRecheckReceipt(id);},1500);}}
async function loadWorkspaceRecheckReceipt(id){clearWorkspaceRecheckPoll();const sequence=++workspaceRecheckReceiptSequence,workspaceId=workspaceRecheckWorkspaceId;try{const receipt=await api('/api/workspace-recheck/'+encodeURIComponent(id));if(!bundleWorkspaceOpen||sequence!==workspaceRecheckReceiptSequence||workspaceId!==workspaceRecheckWorkspaceId||id!==workspaceRecheckSelectedId)return;if(!validWorkspaceRecheckReceipt(receipt,workspaceId)||receipt.id!==id)throw new Error('RECHECK_RESPONSE');renderWorkspaceRecheckReceipt(receipt);$('workspace-recheck-history-status').textContent='Showing the selected separate recheck receipt.';scheduleWorkspaceRecheckPoll();}catch(error){if(bundleWorkspaceOpen&&sequence===workspaceRecheckReceiptSequence&&workspaceId===workspaceRecheckWorkspaceId){workspaceRecheckReceipt=null;workspaceRecheckHistoryReady=false;$('workspace-recheck-receipt').hidden=true;$('workspace-recheck-history-status').textContent=workspaceRecheckFailure(error)+' Status polling stopped.';setBundleWorkspaceControls();}}}
async function loadWorkspaceRecheckHistory(loadDetail=true){
  if(!bundleWorkspaceOpen||!workspaceRecheckWorkspaceId||workspaceRecheckHistoryBusy)return false;const sequence=++workspaceRecheckHistorySequence,workspaceId=workspaceRecheckWorkspaceId;workspaceRecheckHistoryBusy=true;clearWorkspaceRecheckPoll();$('workspace-recheck-history-status').textContent='Reading saved recheck history…';setBundleWorkspaceControls();
  try{const value=await api('/api/workspace-rechecks/'+encodeURIComponent(workspaceId));if(!bundleWorkspaceOpen||sequence!==workspaceRecheckHistorySequence||workspaceId!==workspaceRecheckWorkspaceId)return false;if(!value||value.version!==1||value.workspace_id!==workspaceId||!bundleHash(value.history_sha256)||!Array.isArray(value.rechecks)||value.rechecks.length>200||!value.rechecks.every(receipt=>validWorkspaceRecheckReceipt(receipt,workspaceId)))throw new Error('RECHECK_RESPONSE');if(workspaceRecheckPreview&&workspaceRecheckPreview.history_sha256!==value.history_sha256)invalidateWorkspaceRecheckPreview('Saved recheck history changed. Inspect the current workspace explicitly again.');workspaceRecheckHistorySha=value.history_sha256;workspaceRecheckReceipts=value.rechecks;for(const receipt of value.rechecks)workspaceRecheckKnown.set(receipt.id,receipt);workspaceRecheckHistoryReady=true;if(workspaceRecheckUncertainWorkspaceId===workspaceId){workspaceRecheckUncertainStart=false;workspaceRecheckUncertainWorkspaceId='';}if(!workspaceRecheckReceipts.some(receipt=>receipt.id===workspaceRecheckSelectedId)){workspaceRecheckSelectedId=(workspaceRecheckReceipts[0]&&workspaceRecheckReceipts[0].id)||'';workspaceRecheckReceipt=null;$('workspace-recheck-receipt').hidden=true;}renderWorkspaceRecheckOptions();$('workspace-recheck-history-status').textContent=value.rechecks.length+' separate recheck attempts. The original creation result is unchanged.';if(loadDetail&&workspaceRecheckSelectedId)await loadWorkspaceRecheckReceipt(workspaceRecheckSelectedId);return true;}
  catch(error){if(bundleWorkspaceOpen&&sequence===workspaceRecheckHistorySequence&&workspaceId===workspaceRecheckWorkspaceId){workspaceRecheckHistoryReady=false;invalidateWorkspaceRecheckPreview(workspaceRecheckFailure(error));$('workspace-recheck-history-status').textContent=workspaceRecheckFailure(error);}return false;}
  finally{if(sequence===workspaceRecheckHistorySequence){workspaceRecheckHistoryBusy=false;setBundleWorkspaceControls();}}
}
$('workspace-recheck-inspect').addEventListener('click',async()=>{
  if($('workspace-recheck-inspect').disabled)return;invalidateBundleWorkspacePreview('A workspace recheck inspection was requested. Preview creation separately before deciding to create.');invalidateWorkspaceRecheckPreview('Reading current recheck history and selected workspace snapshot…');const workspaceId=workspaceRecheckWorkspaceId,sequence=workspaceRecheckPreviewSequence;workspaceRecheckPreviewBusy=true;setBundleWorkspaceControls();
  try{if(!await loadWorkspaceRecheckHistory(false))return;if(!bundleWorkspaceOpen||workspaceId!==workspaceRecheckWorkspaceId||sequence!==workspaceRecheckPreviewSequence)return;const value=await api('/api/workspace-recheck-preview',{workspace_id:workspaceId});if(!bundleWorkspaceOpen||workspaceId!==workspaceRecheckWorkspaceId||sequence!==workspaceRecheckPreviewSequence)return;if(!validWorkspaceRecheckPreview(value,workspaceId)||value.history_sha256!==workspaceRecheckHistorySha)throw new Error('RECHECK_STALE');workspaceRecheckPreview=value;renderWorkspaceRecheckPreview(value);$('workspace-recheck-status').textContent='Current snapshot pinned. Review changed editable files, unchanged protected files and fixed checks before Run recheck.';workspaceRecheckExpiryTimer=setTimeout(()=>{if(workspaceRecheckPreview===value){invalidateWorkspaceRecheckPreview('The pinned inspection expired. Inspect explicitly again before Run recheck.');setBundleWorkspaceControls();}},Math.max(0,value.expires_at_ms-Date.now()));}
  catch(error){if(bundleWorkspaceOpen&&workspaceId===workspaceRecheckWorkspaceId&&sequence===workspaceRecheckPreviewSequence)invalidateWorkspaceRecheckPreview(workspaceRecheckFailure(error));}
  finally{if(sequence===workspaceRecheckPreviewSequence)workspaceRecheckPreviewBusy=false;setBundleWorkspaceControls();}
});
$('workspace-recheck-start').addEventListener('click',async()=>{
  const preview=workspaceRecheckPreview;if($('workspace-recheck-start').disabled||!preview||preview.expires_at_ms<=Date.now())return;const workspaceId=workspaceRecheckWorkspaceId,context=workspaceRecheckContextSequence;invalidateWorkspaceRecheckPreview('Starting one separate recheck from the consumed pinned inspection…');bundleWorkspaceActionBusy=true;setBundleWorkspaceControls();
  try{const receipt=await api('/api/workspace-recheck-start',{preview_id:preview.preview_id,preview_sha256:preview.preview_sha256});if(!validWorkspaceRecheckReceipt(receipt,workspaceId))throw new Error('RECHECK_RESPONSE');workspaceRecheckKnown.set(receipt.id,receipt);workspaceRecheckUncertainStart=false;workspaceRecheckUncertainWorkspaceId='';if(bundleWorkspaceOpen&&workspaceId===workspaceRecheckWorkspaceId&&context===workspaceRecheckContextSequence){workspaceRecheckReceiptSequence++;workspaceRecheckSelectedId=receipt.id;renderWorkspaceRecheckReceipt(receipt);$('workspace-recheck-status').textContent='Inspection consumed. The separate recheck attempt is recorded; original creation verification is unchanged.';scheduleWorkspaceRecheckPoll();}}
  catch(error){workspaceRecheckUncertainStart=true;workspaceRecheckUncertainWorkspaceId=workspaceId;if(bundleWorkspaceOpen&&workspaceId===workspaceRecheckWorkspaceId&&context===workspaceRecheckContextSequence)$('workspace-recheck-status').textContent=workspaceRecheckFailure(error)+' The cached preview was consumed. Refresh this workspace’s recheck history before another decision.';}
  finally{bundleWorkspaceActionBusy=false;setComparisonControls();}
});
$('workspace-recheck-history-refresh').addEventListener('click',()=>loadWorkspaceRecheckHistory());
$('workspace-recheck-history-select').addEventListener('change',()=>{clearWorkspaceRecheckPoll();workspaceRecheckReceiptSequence++;workspaceRecheckSelectedId=$('workspace-recheck-history-select').value;workspaceRecheckReceipt=null;$('workspace-recheck-receipt').hidden=true;invalidateWorkspaceRecheckPreview('Selected recheck attempt changed. Inspect the current workspace again before execution.');setBundleWorkspaceControls();if(workspaceRecheckSelectedId)loadWorkspaceRecheckReceipt(workspaceRecheckSelectedId);});
$('workspace-recheck-stop').addEventListener('click',async()=>{const receipt=workspaceRecheckReceipt;if($('workspace-recheck-stop').disabled||!receipt||receipt.status!=='PREPARING'||receipt.owned_active!==true)return;bundleWorkspaceActionBusy=true;clearWorkspaceRecheckPoll();invalidateWorkspaceRecheckPreview('An owned recheck stop was requested. Its records remain preserved.');setBundleWorkspaceControls();try{await api('/api/workspace-recheck-stop',{id:receipt.id});if(bundleWorkspaceOpen&&workspaceRecheckWorkspaceId===receipt.workspace_id&&workspaceRecheckSelectedId===receipt.id)await loadWorkspaceRecheckReceipt(receipt.id);}catch(error){if(bundleWorkspaceOpen&&workspaceRecheckWorkspaceId===receipt.workspace_id)$('workspace-recheck-history-status').textContent=workspaceRecheckFailure(error)+' Private records are retained.';}finally{bundleWorkspaceActionBusy=false;setComparisonControls();}});

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
