"use strict";
const $ = id => document.getElementById(id);
const audio = $("audio"), canvas = $("kolam"), ctx = canvas.getContext("2d");
const state = {design:null, preview:null, session:null, busy:false, recomputing:false, resume:false, videoBusy:false, generation:0, request:0, raf:0};
const melaNames = ["Kanakangi","Ratnangi","Ganamurti","Vanaspati","Manavati","Tanarupi","Senavati","Hanumatodi","Dhenuka","Natakapriya","Kokilapriya","Rupavati","Gayakapriya","Vakulabharanam","Mayamalavagowla","Chakravakam","Suryakantam","Hatakambari","Jhankaradhwani","Natabhairavi","Keeravani","Kharaharapriya","Gourimanohari","Varunapriya","Mararanjani","Charukesi","Sarasangi","Harikambhoji","Dheerasankarabharanam","Naganandini","Yagapriya","Ragavardhini","Gangeyabhushani","Vagadheeswari","Shulini","Chalanata","Salagam","Jalarnavam","Jhalavarali","Navaneetam","Pavani","Raghupriya","Gavambodhi","Bhavapriya","Shubhapantuvarali","Shadvidhamargini","Suvarnangi","Divyamani","Dhavalambari","Namanarayani","Kamavardhini","Ramapriya","Gamanashrama","Vishwambhari","Shamalangi","Shanmukhapriya","Simhendramadhyamam","Hemavati","Dharmavati","Neetimati","Kantamani","Rishabhapriya","Latangi","Vachaspati","Mechakalyani","Chitrambari","Sucharitra","Jyotiswarupini","Dhatuvardhini","Nasikabhushani","Kosalam","Rasikapriya"];
melaNames.forEach((name,i)=>$("mela").add(new Option(`${i+1} · ${name}`, i+1)));
$("mela").value = "29";
function options() {
  const tonic = $("tonic").value === "" ? null : Number($("tonic").value);
  if (tonic !== null && (!Number.isFinite(tonic) || tonic < 55 || tonic > 1000)) throw Error("Set Sa between 55 and 1000 Hz, or leave it blank for automatic estimation.");
  return {grid:document.querySelector("input[name=grid]:checked").value,size:Number($("size").value),mela:Number($("mela").value),tonic,tala:Number($("tala").value)};
}
async function api(url, init={}) {
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail;
    try { const data = await response.json(); detail = typeof data.detail === "string" ? data.detail : "Some settings are invalid. Check the entered values."; } catch { detail = `Server error (${response.status}).`; }
    throw Error(detail);
  }
  return response.status === 204 ? null : response.json();
}
function status(message, progress=null, error=false) {
  $("statusText").textContent = message;
  $("status").classList.toggle("error",error);
  $("jobProgress").hidden = progress === null;
  if(progress !== null) $("jobProgress").value = progress;
}
function controls() {
  const ready = !!state.design && !state.busy && !state.recomputing;
  for(const id of ["play","restart","seek","svg"]) $(id).disabled = !ready;
  $("mp4").disabled = !ready || state.videoBusy;
  $("deleteAudio").disabled = !state.session || state.busy || state.videoBusy;
  $("file").disabled = state.busy || state.videoBusy;
  $("tracker").disabled = state.busy;
}
async function poll(job, generation, onProgress) {
  for (;;) {
    if(generation !== state.generation) return null;
    const result = await api(`/api/jobs/${job}`);
    if(generation !== state.generation) return null;
    onProgress(result);
    if(result.state === "failed") throw Error(result.message);
    if(result.state === "complete") return result;
    await new Promise(resolve=>setTimeout(resolve,900));
  }
}
async function upload(file) {
  if (!file || state.busy || state.videoBusy) return;
  if(!/\.(wav|mp3|flac|ogg)$/i.test(file.name)) return status("Choose a WAV, MP3, FLAC, or OGG recording.",null,true);
  if(file.size > 32*1024*1024) return status("The upload limit is 32 MB.",null,true);
  const generation = ++state.generation, oldSession = state.session;
  ++state.request;
  clearTimeout(recomputeTimer);
  audio.pause(); state.resume=false; state.recomputing=false; state.busy = true; controls();
  $("fileLabel").textContent = file.name;
  status("Uploading your recording…",0);
  let newSession = null;
  try {
    const form = new FormData(); form.append("file",file);form.append("tracker",$("tracker").value);
    const queued = await api("/api/analyze",{method:"POST",body:form});
    newSession = queued.session;
    const result = await poll(queued.job,generation,j=>status(j.message,j.progress));
    if(!result) return;
    state.session = queued.session;
    applyDesign(result.result,true);
    await recompute();
    if(oldSession && oldSession !== state.session) await api(`/api/sessions/${oldSession}`,{method:"DELETE"}).catch(()=>{});
  } catch(error) {
    status(error.message,null,true);
    if(newSession && newSession !== state.session) await api(`/api/sessions/${newSession}`,{method:"DELETE"}).catch(()=>{});
  } finally { state.busy=false; controls(); $("file").value=""; }
}
function applyDesign(design, newAudio=false) {
  state.design=design;
  if(newAudio) {audio.src=design.audio_url;audio.load();}
  const a=design.analysis,g=design.geometry;
  $("stageLabel").textContent="THE MELODY / IN MOTION";
  $("emptyHint").hidden=true;
  $("tonic").placeholder=`${a.estimated_tonic.toFixed(1)} · auto`;
  $("tonicNote").textContent=`Using Sa ${a.tonic.toFixed(1)} Hz · density confidence ${Math.round(a.tonic_confidence*100)}%. Adjust by ear.`;
  $("tempo").textContent=a.tempo > 0 ? `${a.tempo.toFixed(0)} BPM · estimated pulse` : "No stable beat pulse detected";
  $("analysisDetails").textContent=`${a.tracker} · ${a.duration.toFixed(2)} s · ${a.sample_rate} Hz mono · ${a.notes.filter(n=>n.voiced).length} voiced events · ${a.onsets.length} detected onsets. ${g.topology.dot_count} dot cycles, ${g.topology.splice_count} tree splices, ${g.topology.loop_count} closed loop, ${g.topology.crossing_count} paired crossings. Periodic C1 cubic geometry. Native librosa swaras use a 12-tone equal-tempered approximation in your selected Melakarta. Gamaka is within-event pitch spread; Sa is a density estimate. Tala is your chosen pulse grouping, not automatic tala recognition. ${a.warnings.join(" ")}`;
  refreshLabels();drawWave();render();controls();
  status(`Single-loop structure verified · ${g.topology.dot_count} pullis · ready to play.${a.warnings.length ? " pYIN CPU fallback active." : ""}`);
}
function refreshLabels() {
  const g=state.design?.geometry || state.preview;
  const o=state.design?.options;
  const grid=o?.grid || document.querySelector("input[name=grid]:checked").value;
  $("gridCaption").textContent=`${grid === "ner" ? "NER PULLI" : "IDUKKU PULLI"} / ${g?.topology.dot_count || 49} DOTS`;
  const size=Number($("size").value);
  $("sizeValue").textContent = document.querySelector("input[name=grid]:checked").value === "ner" ? `${size} × ${size}` : `${size} → 1`;
  const tala=state.design?.analysis.tala || Number($("tala").value);
  $("pulses").replaceChildren(...Array.from({length:tala},(_,i)=>{let el=document.createElement("span");el.className=i===0?"accent":"";return el;}));
}
async function recompute() {
  const request=++state.request;
  const generation=state.generation;
  const o=options();
  if(!state.session) {
    const geometry=await api("/api/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(o)});
    if(request !== state.request || generation !== state.generation) return;
    state.preview=geometry;refreshLabels();render();return;
  }
  state.resume=state.resume || !audio.paused;
  state.recomputing=true;controls();
  audio.pause();
  try {
    const design=await api(`/api/sessions/${state.session}/design`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(o)});
    if(request !== state.request || generation !== state.generation) return;
    applyDesign(design);
    if(state.resume) audio.play().catch(error=>status(error.message,null,true));
    state.resume=false;
  } finally {if(request === state.request && generation === state.generation){state.recomputing=false;controls();}}
}
let recomputeTimer;
function scheduleRecompute() {
  clearTimeout(recomputeTimer);
  $("sizeValue").textContent=document.querySelector("input[name=grid]:checked").value === "ner" ? `${$("size").value} × ${$("size").value}` : `${$("size").value} → 1`;
  if(state.busy) return;
  recomputeTimer=setTimeout(()=>recompute().catch(error=>status(error.message,null,true)),180);
}
for(const id of ["size","tonic","mela","tala"]) $(id).addEventListener("input",scheduleRecompute);
document.querySelectorAll("input[name=grid]").forEach(el=>el.addEventListener("change",scheduleRecompute));
$("autoTonic").addEventListener("click",()=>{$("tonic").value="";scheduleRecompute();});
$("file").addEventListener("change",()=>upload($("file").files[0]));
for(const name of ["dragenter","dragover"]) $("dropzone").addEventListener(name,e=>{e.preventDefault();$("dropzone").classList.add("dragover");});
for(const name of ["dragleave","drop"]) $("dropzone").addEventListener(name,e=>{e.preventDefault();$("dropzone").classList.remove("dragover");});
$("dropzone").addEventListener("drop",e=>upload(e.dataTransfer.files[0]));
function lowerBound(array,value,key=x=>x) {let lo=0,hi=array.length;while(lo<hi){const mid=(lo+hi)>>>1;if(key(array[mid])<=value)lo=mid+1;else hi=mid;}return lo;}
function interpolate(x,xs,ys) {
  let i=lowerBound(xs,x)-1;i=Math.max(0,Math.min(xs.length-2,i));
  const r=Math.max(0,Math.min(1,(x-xs[i])/(xs[i+1]-xs[i] || 1)));
  return ys[i]+(ys[i+1]-ys[i])*r;
}
function progressAt(g,t) {return interpolate(t,g.timeline.map(x=>x.time),g.timeline.map(x=>x.progress));}
const mix=(a,b,t)=>a.map((v,i)=>v+(b[i]-v)*t);
function prefix(p,t) {const a=mix(p[0],p[1],t),b=mix(p[1],p[2],t),c=mix(p[2],p[3],t),d=mix(a,b,t),e=mix(b,c,t);return[p[0],a,d,mix(d,e,t)];}
function addCurve(context,p,move=false) {if(move)context.moveTo(...p[0]);context.bezierCurveTo(...p[1],...p[2],...p[3]);}
function render() {
  const rect=canvas.getBoundingClientRect(),dpr=Math.min(window.devicePixelRatio||1,2);
  if(canvas.width!==Math.round(rect.width*dpr) || canvas.height!==Math.round(rect.height*dpr)) {canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);}
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,rect.width,rect.height);
  const g=state.design?.geometry || state.preview;
  if(!g) return;
  const q=state.design ? (audio.ended?1:progressAt(g,audio.currentTime)) : 1;
  const [x,y,w,h]=g.bounds,scale=Math.min((rect.width-62)/w,(rect.height-85)/h);
  ctx.translate((rect.width-w*scale)/2-x*scale,(rect.height-h*scale)/2-y*scale-8);
  ctx.scale(scale,scale);
  ctx.fillStyle="#d7a75b";
  for(const p of g.dots){ctx.beginPath();ctx.arc(...p,.047,0,Math.PI*2);ctx.fill();}
  ctx.strokeStyle="#f6ead1";ctx.lineWidth=.038;ctx.lineCap="round";ctx.lineJoin="round";
  ctx.globalAlpha=state.design?1:.55;
  const distance=q*g.length;
  ctx.beginPath();
  g.segments.some((s,i)=>{
    const available=distance-g.cumulative[i];
    if(available<=0)return true;
    const p=available>=s.length?s.points:prefix(s.points,interpolate(available,s.lut,s.lut.map((_,k)=>k/(s.lut.length-1))));
    addCurve(ctx,p,i===0);return available<s.length;
  });ctx.stroke();
  for(const c of g.crossings) {
    if(!c.over || distance<c.distance)continue;
    const other=g.crossings.find(v=>v.id===c.id && !v.over);
    if(distance<other.distance)continue;
    const incoming=g.segments[c.incoming].points;
    const tail=prefix([...incoming].reverse(),.22).reverse();
    const s=g.segments[c.outgoing],available=Math.max(0,Math.min(s.length,distance-c.distance));
    const u=Math.min(.22,interpolate(available,s.lut,s.lut.map((_,k)=>k/(s.lut.length-1))));
    const head=prefix(s.points,u);
    for(const [color,width] of [["#202c2b",.038*3.2],["#f6ead1",.038]]) {ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();addCurve(ctx,tail,true);addCurve(ctx,head);ctx.stroke();}
  }
  ctx.globalAlpha=1;
  $("drawPercent").textContent=state.design?`${Math.round(q*100)}% DRAWN`:"PREVIEW / NO AUDIO";
  if(state.design)updateHud();
}
function formatTime(value) {const n=Number.isFinite(value)?Math.floor(value):0;return `${Math.floor(n/60)}:${String(n%60).padStart(2,"0")}`;}
function updateHud() {
  const a=state.design.analysis,t=audio.currentTime;
  const n=a.notes[Math.max(0,lowerBound(a.notes,t,x=>x.start)-1)];
  $("swara").textContent=n?.swara || "—";
  const pitch=a.pitch[Math.max(0,lowerBound(a.pitch,t,x=>x.time)-1)];
  $("frequency").textContent=pitch?.hz ? `${pitch.hz.toFixed(1)} Hz` : "rest / unvoiced";
  const beat=lowerBound(a.beats,t)-1,index=beat<0?-1:beat%a.tala;
  $("beatText").textContent=`${index<0?"—":index+1} / ${a.tala}`;
  [...$("pulses").children].forEach((el,i)=>el.classList.toggle("active",i===index));
  $("gamakaBar").style.width=`${Math.min(100,(n?.gamaka||0)/1.5)}%`;
  $("gamakaText").textContent=`${(n?.gamaka||0).toFixed(0)} cents σ · pitch spread`;
  $("time").replaceChildren(document.createTextNode(`${formatTime(t)} `),Object.assign(document.createElement("i"),{textContent:`/ ${formatTime(a.duration)}`}));
  $("seek").value=String(1000*t/a.duration);
  $("playhead").style.left=`${Math.min(100,100*t/a.duration)}%`;
}
function animate(){render();if(!audio.paused)state.raf=requestAnimationFrame(animate);}
async function togglePlay(){if(!state.design || state.busy || state.recomputing)return;try{if(audio.paused)await audio.play();else audio.pause();}catch(error){status(error.message,null,true);}}
$("play").addEventListener("click",togglePlay);
$("restart").addEventListener("click",()=>{audio.currentTime=0;render();});
$("seek").addEventListener("input",()=>{if(state.design){audio.currentTime=Number($("seek").value)/1000*state.design.analysis.duration;render();}});
audio.addEventListener("play",()=>{$("play").textContent="Ⅱ";$("play").setAttribute("aria-label","Pause recording");cancelAnimationFrame(state.raf);animate();});
for(const event of ["pause","ended"])audio.addEventListener(event,()=>{$("play").textContent="▶";$("play").setAttribute("aria-label","Play recording");cancelAnimationFrame(state.raf);render();});
for(const event of ["loadedmetadata","seeked","timeupdate"])audio.addEventListener(event,()=>{if(audio.paused)render();});
audio.addEventListener("error",()=>status("The normalized recording could not be loaded. Upload the clip again.",null,true));
document.addEventListener("keydown",event=>{if(event.code==="Space" && !/INPUT|SELECT|TEXTAREA|BUTTON|SUMMARY/.test(document.activeElement.tagName)){event.preventDefault();togglePlay();}});
function drawWave() {
  const wave=$("waveform"),rect=wave.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,2),c=wave.getContext("2d");
  wave.width=Math.round(rect.width*ratio);wave.height=Math.round(rect.height*ratio);c.scale(ratio,ratio);
  const a=state.design?.analysis;
  c.strokeStyle="#bfc7aa";c.lineWidth=1;
  if(!a){c.beginPath();c.moveTo(0,rect.height/2);c.lineTo(rect.width,rect.height/2);c.stroke();return;}
  c.strokeStyle="#d8d6c5";
  a.beats.forEach(t=>{const x=t/a.duration*rect.width;c.beginPath();c.moveTo(x,rect.height-7);c.lineTo(x,rect.height);c.stroke();});
  c.strokeStyle="#c6a36c88";
  a.onsets.forEach(t=>{const x=t/a.duration*rect.width;c.beginPath();c.moveTo(x,0);c.lineTo(x,5);c.stroke();});
  c.strokeStyle="#929f78";c.lineWidth=Math.max(1,rect.width/a.waveform.length*.65);
  a.waveform.forEach((value,i)=>{const x=(i+.5)/a.waveform.length*rect.width,h=Math.max(1,value*(rect.height/2-6));c.beginPath();c.moveTo(x,rect.height/2-h);c.lineTo(x,rect.height/2+h);c.stroke();});
}
function download(url) {const link=document.createElement("a");link.href=url;link.download="";document.body.append(link);link.click();link.remove();}
$("svg").addEventListener("click",()=>{if(state.design)download(`/api/designs/${state.design.id}/svg`);});
$("mp4").addEventListener("click",async()=>{
  if(!state.design || state.videoBusy)return;
  state.videoBusy=true;controls();const generation=state.generation;
  try {const queued=await api(`/api/designs/${state.design.id}/mp4`,{method:"POST"});const result=await poll(queued.job,generation,j=>status(j.message,j.progress));if(result){download(result.url);status("Video + audio ready. Your download has started.");}}
  catch(error){status(error.message,null,true);}finally{state.videoBusy=false;controls();}
});
$("deleteAudio").addEventListener("click",async()=>{
  if(!state.session || state.busy || state.videoBusy)return;
  try {await api(`/api/sessions/${state.session}`,{method:"DELETE"});audio.pause();audio.removeAttribute("src");audio.load();++state.generation;state.session=null;state.design=null;$("emptyHint").hidden=false;$("stageLabel").textContent="STRUCTURAL PREVIEW";$("fileLabel").textContent="Bring a melody";$("swara").textContent="—";$("frequency").textContent="awaiting a melody";$("gamakaBar").style.width="0";$("gamakaText").textContent="Pitch movement · cents σ";$("beatText").textContent=`— / ${$("tala").value}`;$("time").innerHTML="0:00 <i>/ 0:00</i>";$("seek").value="0";$("playhead").style.left="0";$("tonicNote").textContent="Pitch-density estimate; adjust Sa by ear.";$("analysisDetails").textContent="Audio and derived files deleted. Upload a recording to begin again.";$("tempo").textContent="Pulse estimated from audio";await recompute();drawWave();controls();status("Audio and generated files deleted from this studio.");}
  catch(error){status(error.message,null,true);}
});
new ResizeObserver(()=>{render();drawWave();}).observe($("stage"));
refreshLabels();drawWave();recompute().catch(error=>status(error.message,null,true));
