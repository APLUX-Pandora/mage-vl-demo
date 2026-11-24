'use strict';
const $=id=>document.getElementById(id),video=$('video');
let config,job=null,stream=null,sequence=0,sending=false,terminal=false,resetting=false,lastTime=0;
let telemetry=[],lastEvent=0,clockTimer=null,ownsJob=false,autoStart=false,focusedSegment=0,lastWatching=-1;
let networkPaused=false,recovering=false,orphanedJob=false,pendingStart=null;
let customPrompt=null,defaultPrompt='',promptRevision=0;
const phases={1:'Ready',2:'Understanding',3:'Complete',4:'Cancelled'};
video.defaultMuted=false;video.muted=false;video.volume=1;
function status(text,state='ready'){$('status').textContent=text;$('status').dataset.state=state;}
function fail(message){$('error').textContent=message;$('error').hidden=false;}
function clearError(){$('error').hidden=true;}
async function api(path,options={}){
  const {timeout=10000,...request}=options;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
  try{
    const response=await fetch(path,{...request,signal:controller.signal,headers:{'Content-Type':'application/json',...request.headers}});
    const data=await response.json();if(!response.ok)throw Error(data.error||`Request failed (${response.status})`);return data;
  }catch(e){if(e.name==='AbortError')throw Error('Request timed out.');throw e;}
  finally{clearTimeout(timer);}
}
const post=(path,data={})=>api(path,{method:'POST',body:JSON.stringify(data)});
function stamp(s,precise=false){
  const ms=Math.round(s*1000),minutes=Math.floor(ms/60000),seconds=Math.floor(ms%60000/1000),fraction=ms%1000;
  const suffix=precise&&fraction?'.'+String(fraction).padStart(3,'0').replace(/0+$/,''):'';
  return `${String(minutes).padStart(2,'0')}:${String(seconds).padStart(2,'0')}${suffix}`;
}
function selected(){return config?.sources.find(s=>s.id===$('source').value);}
function segmentSeconds(){return Number(document.querySelector('input[name="summary-interval"]:checked').value);}
function selectCadence(seconds){
  document.querySelectorAll('input[name="summary-interval"]').forEach(input=>{input.checked=Number(input.value)===Number(seconds);});
}
// Match Python str.split() Unicode whitespace for the application word ceiling.
function promptWords(text){return (text.match(/[^\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/gu)||[]).length;}
function promptError(text){
  if(!promptWords(text)||text.includes('\0'))return 'Enter a non-empty prompt without NUL characters.';
  if(promptWords(text)>(config?.max_prompt_words||200))return 'Use at most 200 words (separated by whitespace).';
  if(new TextEncoder().encode(text).length>(config?.max_prompt_bytes||2048))return 'Use at most 2,048 UTF-8 bytes.';
  return '';
}
function promptLocked(){return Boolean(job);}
function effectivePrompt(){return job?.prompt??(customPrompt===null?defaultPrompt:customPrompt);}
function refreshPromptLabel(){
  const mode=job?.prompt_mode||(customPrompt===null?'default':'custom');

  $('prompt-text').readOnly=!config||promptLocked();$('prompt-default').disabled=!config||promptLocked();
  $('prompt-mode').textContent=promptLocked()?'Locked · Reset to edit':mode==='custom'?'Custom':'Default';
  const text=effectivePrompt(),bytes=new TextEncoder().encode(text).length,error=promptError(text);
  if($('prompt-text').value!==text)$('prompt-text').value=text;
  $('prompt-bytes').textContent=`${promptWords(text)} / ${config?.max_prompt_words||200} words · ${bytes} / ${config?.max_prompt_bytes||2048} UTF-8 bytes${error?' · '+error:''}`;
  $('prompt-bytes').dataset.invalid=String(Boolean(error));$('prompt-text').setCustomValidity(error);
}
async function refreshDefaultPrompt(){
  if(!config||promptLocked()||customPrompt!==null)return;
  const revision=++promptRevision;
  const response=await api(`/api/prompt?segment_seconds=${segmentSeconds()}&max_words=${encodeURIComponent($('words').value)}`);
  if(revision!==promptRevision||promptLocked()||customPrompt!==null)return;
  defaultPrompt=response.prompt;$('prompt-text').value=defaultPrompt;refreshPromptLabel();
}
$('prompt-text').oninput=()=>{if(!promptLocked()){customPrompt=$('prompt-text').value;promptRevision++;refreshPromptLabel();if(!promptError(customPrompt))clearError();}};
$('prompt-default').onclick=async()=>{if(promptLocked())return;customPrompt=null;clearError();try{await refreshDefaultPrompt();}catch(e){fail(e.message);}};
$('words').addEventListener('change',()=>refreshDefaultPrompt().catch(e=>fail(e.message)));
function windows(){return job?.windows?.length?job.windows:(selected()?.windows_by_interval?.[String(segmentSeconds())]||[]);}
function segmentCount(){return windows().length;}
function currentWindow(t){const list=windows();return Math.max(0,Math.min(list.length-1,list.findIndex(w=>t<w.end_s)===-1?list.length-1:list.findIndex(w=>t<w.end_s)));}
function drawCards(count){
  $('cards').classList.toggle('dense',count>6);
  $('cards').replaceChildren();telemetry=Array.from({length:count},(_,i)=>({segment_id:i,boundary_ms:null,first_ms:null,last_ms:null}));
  for(let i=0;i<count;i++){
    const w=windows()[i];
    const card=document.createElement('article');card.className='card';card.id=`segment-${i}`;card.dataset.phase='waiting';
    card.setAttribute('role','group');card.setAttribute('aria-label',`Segment ${i+1}, ${stamp(w.start_s,true)} to ${stamp(w.end_s,true)}`);
    card.onclick=()=>focusSegment(i);card.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();focusSegment(i);}};
    card.innerHTML=`<div class="card-top"><span class="number">${String(i+1).padStart(2,'0')}</span><span class="interval">${stamp(w.start_s,true)} – ${stamp(w.end_s,true)}</span><span class="phase">Waiting</span></div><p></p><div class="metrics"></div>`;
    const heading=card.querySelector('.card-top');heading.tabIndex=0;heading.setAttribute('role','button');heading.setAttribute('aria-label',`Show summary for segment ${i+1}`);
    $('cards').append(card);
  }$('completed').textContent=`0 / ${count} complete`;
  $('segment-ticks').replaceChildren(...windows().map(w=>{const tick=document.createElement('i');tick.style.flex=String(w.duration_s);return tick;}));
  focusedSegment=0;lastWatching=-1;focusSegment(0);refreshActivity();
}
function focusSegment(id){
  focusedSegment=id;
  document.querySelectorAll('.card').forEach((c,i)=>{c.classList.toggle('expanded',i===id);c.querySelector('.card-top').setAttribute('aria-expanded',String(i===id));});
}
function refreshActivity(){
  const count=telemetry.length,t=video.currentTime||0;
  const writing=[...document.querySelectorAll('.card')].findIndex(c=>['pending','writing'].includes(c.dataset.phase));
  let state='idle',title='Ready to understand',detail=`Start the video to follow each ${segmentSeconds()}-second segment.`,counter=`${segmentSeconds()}s`,progress=0;
  if(job&&!terminal&&job.state==='preparing'){title='Getting the video ready';detail='Playback and understanding will start automatically.';counter='…';}
  else if(writing>=0){state='writing';title=`Understanding segment ${writing+1} of ${count}`;detail=video.paused?'Video paused · Analysis in progress':'Preparing the summary · The next segment keeps playing';counter='…';progress=100;}
  else if(terminal){state=job?.state==='done'?'done':'idle';title=job?.state==='done'?'All segments understood':'Session stopped';detail='Select any segment below to read its summary.';counter=job?.state==='done'?`${count}/${count}`:'—';progress=job?.state==='done'?100:0;}
  else if(job&&ownsJob&&job.state!=='preparing'){
    const index=currentWindow(t),w=windows()[index],part=t-w.start_s;
    state=video.paused?'paused':'watching';title=`${video.paused?'Paused at':'Watching'} segment ${index+1} of ${count}`;
    detail=t>=selected().duration?'Video finished · Waiting for the final summary':`${stamp(w.start_s,true)}–${stamp(w.end_s,true)} · Summary after this segment`;
    counter=t>=selected().duration?'…':`${Math.max(0,Math.ceil(w.duration_s-part))}s`;progress=Math.min(100,part/w.duration_s*100);
  }else if(job&&!ownsJob){title='Observing an active session';detail='Playback is controlled by its original page.';counter='LIVE';}
  $('live-strip').dataset.state=state;$('live-title').textContent=title;$('live-detail').textContent=detail;$('live-count').textContent=counter;$('live-progress').style.width=progress+'%';
}
async function startPlayback(){
  autoStart=false;
  try{await video.play();job.state='running';status('Playing & understanding','running');controls();await sendClock();}
  catch(e){fail('Playback needs a click. Press Understand video to start playback.');controls();}
  refreshActivity();
}
function changeSource(){
  const source=selected();if(!source)return;
  video.src='/media/'+source.id;video.load();$('video-name').textContent=source.name;
  $('video-placeholder').hidden=true;lastTime=0;drawCards(segmentCount());updateTime();
  $('remove').hidden=source.id==='cafe';$('media-credit').hidden=source.id!=='cafe';refreshAudio();
}
function controls(){
  const active=job&&!terminal;
  refreshPromptLabel();
  ['codec-target','codec-group','codec-images'].forEach(id=>$(id).disabled=active);
  $('segment-seconds').disabled=active;$('source').disabled=active;$('file').disabled=active;$('words').disabled=active;$('tokens').disabled=active;$('remove').disabled=active;
  $('reload').disabled=!config||networkPaused||config.status==='loading'||Boolean(job&&!terminal);
  $('play').disabled=networkPaused||!config||config.status!=='ready'||resetting||job?.state==='preparing'||terminal||(job&&!ownsJob);
  $('stop').disabled=!active;$('reset').disabled=!job||resetting;
  $('play').textContent=!job?'Understand video':job.state==='preparing'?'Starting…':video.paused?'Understand video':'Pause';
  $('play').classList.toggle('starting',job?.state==='preparing');refreshActivity();
}
function updateTime(){
  const source=selected(),duration=source?.duration||0,t=video.currentTime||0;
  $('time').textContent=`${stamp(t,t>=duration)} / ${stamp(duration,true)}`;
  $('window').textContent=`Segment ${Math.min(segmentCount()||1,currentWindow(t)+1)} of ${segmentCount()||1}`;
  const percent=duration?t/duration*100:0;$('progress-fill').style.width=percent+'%';
  document.querySelector('.progress').setAttribute('aria-valuenow',percent.toFixed(1));
  const now=performance.now();
  telemetry.forEach((m,i)=>{if(m.boundary_ms===null&&t>=windows()[i].end_s)m.boundary_ms=now-(t-windows()[i].end_s)*1000;});
  if(job&&ownsJob&&!terminal&&job.state!=='preparing')telemetry.forEach((_,i)=>{
    const c=$(`segment-${i}`);if(c.dataset.phase==='collecting'&&t>=windows()[i].end_s){c.dataset.phase='pending';c.querySelector('.phase').textContent='Understanding';focusSegment(i);}
    if(c.dataset.phase==='waiting'&&t>=windows()[i].start_s&&t<windows()[i].end_s){c.dataset.phase='collecting';c.querySelector('.phase').textContent='Watching';if(lastWatching!==i){lastWatching=i;if(!document.querySelector('.card[data-phase=writing],.card[data-phase=pending]'))focusSegment(i);}}
  });
  refreshActivity();
}
function finishUI(state){terminal=true;job.state=state;stream?.close();video.pause();controls();status(state==='done'?'All summaries complete':state==='stopped'?'Stopped':'Session error',state);sendTelemetry();}
function sendTelemetry(){if(job&&ownsJob)post(`/api/jobs/${job.id}/telemetry`,{segments:telemetry,clock:'browser performance.now milliseconds',video_time_s:video.currentTime}).catch(()=>{});}
function connectEvents(id){
  stream?.close();stream=new EventSource(`/api/jobs/${id}/events?after=${lastEvent}`);
  stream.onmessage=event=>{
    const e=JSON.parse(event.data);if(Number.isInteger(e.event_id)){if(e.event_id<=lastEvent)return;lastEvent=e.event_id;}
    $('connection').textContent='Connected';
    if(e.kind==='ready'){job.windows=e.windows;job.duration_s=e.duration_s;drawCards(segmentCount());job.state='ready';status(ownsJob?'Ready':'A session is active. Stop or reset to restart.');controls();if(ownsJob&&autoStart)startPlayback();}
    if(e.kind==='text'){
      const c=$(`segment-${e.segment_id}`),m=telemetry[e.segment_id],now=performance.now();
      if(!c)return;if(c.dataset.phase!=='writing')focusSegment(e.segment_id);c.querySelector('p').textContent+=e.text;c.dataset.phase='writing';c.querySelector('.phase').textContent='Understanding';
      if(m.first_ms===null&&e.text.trim())m.first_ms=now;m.last_ms=now;
    }
    if(e.kind==='sdk_event'){
      const c=$(`segment-${e.segment_id}`);if(!c)return;
      c.querySelector('.phase').textContent=phases[e.type]||'Working';
      if(e.type===2){c.dataset.phase='writing';focusSegment(e.segment_id);}
      if(e.type===3){
        c.dataset.phase='done';const m=telemetry[e.segment_id];
        const first=m.boundary_ms!==null&&m.first_ms!==null?Math.max(0,(m.first_ms-m.boundary_ms)/1000).toFixed(2)+'s':'—';
        const write=m.first_ms!==null&&m.last_ms!==null?((m.last_ms-m.first_ms)/1000).toFixed(2)+'s':'—';
        c.querySelector('.metrics').textContent=ownsJob?`First text ${first} · Writing ${write} · ${e.emitted_words} words${e.stop_reason===2?' · Token ceiling':e.stop_reason===3?' · Word ceiling':''}`:`${e.emitted_words} words · Observing session`;
        const n=document.querySelectorAll('.card[data-phase=done]').length;$('completed').textContent=`${n} / ${telemetry.length} complete`;sendTelemetry();
      }else if(e.type===4){c.dataset.phase='cancelled';}
    }
    if(e.kind==='done')finishUI('done');
    if(e.kind==='state'&&e.state==='stopped')finishUI('stopped');
    if(e.kind==='error'){autoStart=false;fail(e.message);finishUI('error');}
    refreshActivity();
  };
  stream.onerror=()=>{
    if(!terminal)$('connection').textContent='Reconnecting…';
  };
}
async function sendClock(){
  if(networkPaused||!job||!ownsJob||terminal||['preparing','done','stopped','error'].includes(job.state)||sending||!job.id)return;
  sending=true;
  const duration=job.duration_s??job.windows?.at(-1)?.end_s??selected().duration;
  const time=video.ended?duration:Math.min(video.currentTime,duration);
  try{await post(`/api/jobs/${job.id}/clock`,{time,playing:!video.paused&&!video.ended,sequence:sequence++});}
  catch(e){
    if(!terminal){
      try{const current=await api(`/api/jobs/${job.id}`);if(['done','stopped','error'].includes(current.state)){job.state=current.state;return;}}catch(_){}
      networkPaused=true;$('connection').textContent='Disconnected';fail(e.message+' · Retry connection to continue.');video.pause();status('Connection interrupted','error');controls();
    }
  }
  finally{sending=false;}
}
$('play').onclick=async()=>{
  clearError();
  try{
    if(networkPaused)throw Error('Retry connection before continuing.');
    if(!job){
      const words=Number($('words').value),tokens=Number($('tokens').value);
      if(!Number.isInteger(words)||words<1||words>120||!Number.isInteger(tokens)||tokens<1||tokens>512)throw Error('Enter valid word and token ceilings.');
      if(customPrompt!==null&&promptError(customPrompt)){$('prompt-text').reportValidity();throw Error(promptError(customPrompt));}

      const codec={video_target_canvas:Number($('codec-target').value),video_group_size:Number($('codec-group').value),video_images_per_group:Number($('codec-images').value)};
      if(Object.values(codec).some(v=>!Number.isInteger(v)||v<1||v>0xffffffff)||codec.video_target_canvas%codec.video_images_per_group||codec.video_group_size%codec.video_images_per_group)throw Error('Use positive integer budgets; canvas and candidate counts must be divisible by canvases per group.');
      ownsJob=true;autoStart=true;$('advanced').open=false;job={state:'preparing'};controls();status('Starting video…');
      pendingStart=Array.from(crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16).padStart(2,'0')).join('');
      job=await post('/api/jobs',{request_id:pendingStart,source_id:selected().id,segment_seconds:segmentSeconds(),max_words:words,max_tokens:tokens,...codec,...(customPrompt===null?{}:{prompt:customPrompt})});
      pendingStart=null;orphanedJob=false;sequence=0;lastEvent=0;terminal=false;connectEvents(job.id);controls();
    }else if(video.paused){await startPlayback();}
    else{video.pause();job.state='paused';status('Playback paused','paused');controls();await sendClock();}
  }catch(e){autoStart=false;networkPaused=true;video.pause();fail(e.message+' · Retry connection to check whether the session started.');if(job&&!job.id)job=null;status('Connection interrupted','error');$('connection').textContent='Disconnected';controls();}
};
$('stop').onclick=async()=>{autoStart=false;video.pause();try{await post(`/api/jobs/${job.id}/stop`);if(!terminal)status('Stopping after the current step…');}catch(e){fail(e.message);}};
$('reset').onclick=async()=>{
  autoStart=false;resetting=true;video.pause();controls();
  try{
    if(!orphanedJob)await post('/api/reset',{job_id:job.id});
    const deadline=Date.now()+30000;
    for(;;){
      if(Date.now()>=deadline)throw Error('Reset is still pending. Retry connection after the current step.');
      const current=await api('/api/config',{timeout:Math.min(10000,deadline-Date.now())});
      config.status=current.status;config.error=current.error;
      if(current.status==='error')throw Error(current.error||'Reset failed. Reload the model.');
      if(!current.reset_pending&&(!current.current||['done','stopped','error'].includes(current.current.state)))break;
      await new Promise(r=>setTimeout(r,100));
    }
    stream?.close();job=null;orphanedJob=false;pendingStart=null;terminal=false;lastEvent=0;sequence=0;lastTime=0;refreshDefaultPrompt().catch(e=>fail(e.message));video.currentTime=0;drawCards(segmentCount());updateTime();clearError();status('Ready');
  }catch(e){fail(e.message);}finally{resetting=false;controls();}
};
$('mute').onclick=()=>{video.muted=!video.muted;};
function refreshAudio(){
  const silent=selected()?.has_audio===false;
  $('mute').disabled=silent;
  $('mute').textContent=silent?'No audio track':video.muted?'Sound off':'Sound on';
  $('mute').setAttribute('aria-pressed',String(!silent&&video.muted));
  $('mute').title=silent?'This video has no audio track':video.muted?'Click to unmute':'Click to mute';
  document.querySelector('.tag').textContent=silent?'Video · no audio track':`Video · sound ${video.muted?'off':'on'}`;
  document.querySelector('.explanation p').textContent=silent?'Visual analysis builds during playback. This video has no audio track.':'Visual analysis builds during playback. Audio plays for you; summaries describe what is visible.';
}
video.addEventListener('volumechange',refreshAudio);
$('source').onchange=changeSource;
function changeCadence(){
  const seconds=segmentSeconds(),profile=config.profiles.find(p=>p.segment_seconds===seconds);
  $('words').value=profile.max_words;$('tokens').value=profile.max_tokens;
  $('codec-target').value=job?.video_target_canvas??12;$('codec-group').value=job?.video_group_size??profile.sampled_frames_per_group;$('codec-images').value=job?.video_images_per_group??4;
  $('cadence-label').textContent=`A summary every ${seconds} seconds`;
  $('cadence-intro').textContent=`The video keeps playing. A new English summary arrives after each ${seconds}-second segment.`;
  $('word-help').textContent='Hard word limit. Applies to default and custom prompts.';
  drawCards(segmentCount());updateTime();
  if(config){const base=profile.prompt;defaultPrompt=base;refreshPromptLabel();refreshDefaultPrompt().catch(e=>fail(e.message));}
}
$('segment-seconds').onchange=changeCadence;
$('file').onchange=async()=>{
  const file=$('file').files[0];if(!file)return;clearError();$('file').disabled=true;status('Uploading video…');
  try{
    if(file.size>256*1024*1024)throw Error('The upload limit is 256 MiB.');
    const source=await api('/api/uploads',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name)},body:file,timeout:120000});
    config.sources.push(source);const option=new Option(source.name,source.id);$('source').add(option);$('source').value=source.id;changeSource();status('Ready');
  }catch(e){fail(e.message);status('Ready');}finally{$('file').value='';controls();}
};
$('remove').onclick=async()=>{try{const id=selected().id;await api('/api/uploads/'+id,{method:'DELETE'});config.sources=config.sources.filter(s=>s.id!==id);$('source').selectedOptions[0].remove();changeSource();}catch(e){fail(e.message);}};
video.addEventListener('timeupdate',()=>{lastTime=Math.max(lastTime,video.currentTime);updateTime();});
video.addEventListener('seeking',()=>{if(job&&!terminal&&!resetting&&Math.abs(video.currentTime-lastTime)>.5){video.currentTime=lastTime;fail('Seeking is unavailable during analysis. Reset to restart.');}});
video.addEventListener('ratechange',()=>{if(video.playbackRate!==1)video.playbackRate=1;});
video.addEventListener('ended',()=>{updateTime();sendClock();status('Finishing the last summary…','running');controls();});
video.addEventListener('waiting',()=>{if(job&&!terminal)status('Waiting for video…','paused');});
video.addEventListener('playing',()=>{if(job&&!terminal)status('Playing & understanding','running');});
video.addEventListener('error',()=>fail('This browser could not play the video. Use a browser with H.264 support.'));
window.addEventListener('beforeunload',()=>{if(job&&ownsJob&&!terminal)navigator.sendBeacon(`/api/jobs/${job.id}/stop`,new Blob(['{}'],{type:'application/json'}));});
async function init(){
  try{
    config=await api('/api/config');
    selectCadence(config.segment_seconds);
    $('source').replaceChildren(...config.sources.map(s=>new Option(s.name,s.id)));changeSource();changeCadence();
    $('connection').textContent='Connected';
    if(config.current&&!['done','stopped','error'].includes(config.current.state)){
      // Attach to an active session without changing its source clock.
      job=config.current;$('source').value=job.source_id;selectCadence(job.segment_seconds||config.segment_seconds);changeCadence();$('words').value=job.max_words;$('tokens').value=job.max_tokens;terminal=false;ownsJob=false;connectEvents(job.id);
      status('A session is active. Stop or reset to restart.');
    }else status(config.status==='ready'?'Ready':config.error||'Loading models…',config.status);
    controls();
    while(config.status==='loading'){await new Promise(r=>setTimeout(r,500));const next=await api('/api/config');config.status=next.status;config.error=next.error;status(next.status==='ready'?'Ready':next.error||'Loading models…',next.status);controls();}
    if(clockTimer)clearInterval(clockTimer);
    clockTimer=setInterval(()=>{updateTime();sendClock();},100);
  }catch(e){networkPaused=true;fail(e.message);$('connection').textContent='Disconnected';}
}
init();

async function recoverConnection(){
  if(recovering)return;recovering=true;$('retry').disabled=true;
  try{
    const next=await api('/api/config');
    if(!config){await init();if(!config)throw Error('Service configuration unavailable');}
    config.status=next.status;config.error=next.error;
    const priorSource=$('source').value;
    config.sources=next.sources;
    $('source').replaceChildren(...config.sources.map(s=>new Option(s.name,s.id)));
    $('source').value=config.sources.some(s=>s.id===priorSource)?priorSource:(next.current?.source_id||config.sources[0]?.id||'');
    if($('source').value!==priorSource)changeSource();
    // A start response may have been lost. Recover its identity before another start.
    if(next.current && (!job || job.id!==next.current.id)){
      job=next.current;ownsJob=Boolean(pendingStart&&job.request_id===pendingStart);orphanedJob=false;pendingStart=null;terminal=['done','stopped','error'].includes(job.state);
      $('source').value=job.source_id;selectCadence(job.segment_seconds);lastEvent=0;
      drawCards(segmentCount());connectEvents(job.id);
    }
    if(job && next.current?.id===job.id){
      job={...job,...next.current};sequence=Math.max(sequence,(next.current.sequence??-1)+1);
      if(!terminal && (!stream || stream.readyState===EventSource.CLOSED))connectEvents(job.id);
    }
    if(job&&!next.current){orphanedJob=true;terminal=true;ownsJob=false;stream?.close();}
    networkPaused=false;clearError();$('connection').textContent='Connected';
    status(next.status==='ready'?(orphanedJob?'Previous session ended · results retained; Reset to start again':(job&&terminal?(job.state==='done'?'All summaries complete':job.state==='error'?'Session failed · Reload model to retry':'Stopped · Reset to start again'):(job&&!ownsJob?'Observing another active session':'Connected · press Play to continue'))):next.error||'Loading models…',next.status);controls();
    if(!clockTimer)clockTimer=setInterval(()=>{updateTime();sendClock();},100);
  }catch(e){networkPaused=true;fail(e.message);$('connection').textContent='Disconnected';}
  finally{recovering=false;$('retry').disabled=false;}
}
$('retry').onclick=recoverConnection;
$('reload').onclick=async()=>{
  video.pause();autoStart=false;$('reload').disabled=true;
  try{
    await post('/api/reload');
    config.status='loading';controls();status('Reloading model…');
    const deadline=Date.now()+180000;
    while(Date.now()<deadline){
      const next=await api('/api/config');config.status=next.status;config.error=next.error;
      if(next.status==='error')throw Error(next.error||'Model loading failed. You can retry Reload model.');
      if(next.status==='ready'){networkPaused=false;clearError();status('Model ready · Reset to start a new session');controls();return;}
      await new Promise(r=>setTimeout(r,500));
    }
    throw Error('Model is still loading. Retry connection to check its status.');
  }catch(e){fail(e.message);status(config?.status==='error'?'Model load failed':'Reload status unavailable','error');}
  finally{$('reload').disabled=false;controls();}
};
