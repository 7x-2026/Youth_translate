import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Capture } from './capture';
import { SystemCapture } from './system-capture';
import { replaceCapture } from './switch-capture';
import { AudioProgress } from './audio-progress';
import { audioSources, resolveAudioSource, type AudioOutput } from './input';
import { displayLevel } from './audio';
import { RelayClient, type Status } from './connection';
import { initialSubtitles, transition, applySubtitle, markUnfinished, exportText, type SubtitleState } from './subtitles';
import './style.css';
type Health={credentialsConfigured:boolean;credentialSourceMismatch:boolean;subtitleSemanticsVerified:boolean;ready:boolean;cloudWarmupSupported?:boolean};
const labels:Record<string,string>={idle:'准备就绪',connecting:'正在连接',running:'正在翻译',muted:'云端等待语音',recovering:'正在恢复',finishing:'正在收尾',paused:'已暂停',stopped:'已结束',error:'需要处理'};
function assertReady(h:Health){
  if(!h.ready)throw Error(!h.credentialsConfigured?'请先在 .env 配置 VOLC_API_KEY，然后重启服务。':h.credentialSourceMismatch?'当前是火山方舟 ark- Key；请换为豆包语音新版控制台的 API Key。':'请先运行协议探测，确认音频封装及字幕语义，再设置 VOLC_SUBTITLE_RESPONSE_MODE。');
}
const DEFAULT_FONT_SIZE=48, DEFAULT_FONT_COLOR='#f2fbf7';
const MIN_FONT_SIZE=16, MAX_FONT_SIZE=64, FONT_STEP=2;
type DisplaySettings={fontSize:number|null;fontColor:string|null};
function readDisplaySettings():DisplaySettings{
  try{
    const size=localStorage.getItem('subtitleFontSize'),color=localStorage.getItem('subtitleFontColor');
    const number=size!==null&&/^\d+$/.test(size)?Number(size):NaN;
    return {
      fontSize:Number.isInteger(number)&&number>=MIN_FONT_SIZE&&number<=MAX_FONT_SIZE?number:null,
      fontColor:color!==null&&/^#[0-9a-f]{6}$/i.test(color)?color:null,
    };
  }catch{return {fontSize:null,fontColor:null};}
}
function App(){
  const [health,setHealth]=useState<Health>();
  const [devices,setDevices]=useState<MediaDeviceInfo[]>([]);
  const [outputs,setOutputs]=useState<AudioOutput[]>([]);
  const [input,setInput]=useState('auto');const [mode,setMode]=useState('auto');const [packetMs,setPacketMs]=useState(80);const [roomMode,setRoomMode]=useState(false);
  const systemAudio=input==='system'||input.startsWith('system:');
  const [display,setDisplay]=useState<DisplaySettings>(readDisplaySettings);
  const font=display.fontSize??DEFAULT_FONT_SIZE;
  const subtitleStyle={fontSize:display.fontSize??undefined,color:display.fontColor??undefined};
  const [source,setSource]=useState(true);
  const speechSupported=typeof window.speechSynthesis!=='undefined'&&typeof window.SpeechSynthesisUtterance!=='undefined';
  const [speaking,setSpeaking]=useState(false);const [speechHint,setSpeechHint]=useState('');
  const utterance=useRef<SpeechSynthesisUtterance|null>(null);
  function stopSpeech(){
    const current=utterance.current;utterance.current=null;
    if(current){current.onend=null;current.onerror=null;window.speechSynthesis.cancel();}
    setSpeaking(false);
  }
  useEffect(()=>{
    if(!speechSupported)return;
    // Some browsers populate the system voice list asynchronously after this call.
    try{window.speechSynthesis.getVoices();}catch{/* Report unavailable voices on click. */}
    const cancel=()=>{
      const current=utterance.current;utterance.current=null;
      if(current){current.onend=null;current.onerror=null;window.speechSynthesis.cancel();}
    };
    window.addEventListener('pagehide',cancel);
    return()=>{window.removeEventListener('pagehide',cancel);cancel();};
  },[speechSupported]);
  function speakTranslation(){
    if(utterance.current){stopSpeech();return;}
    const text=subtitles.current.translation?.text.trim();
    if(!text||!speechSupported)return;
    setSpeechHint('');
    try{
      const chinese=/\p{Script=Han}/u.test(text),lang=chinese?'zh-CN':'en-US';
      const voices=window.speechSynthesis.getVoices();
      const normalize=(value:string)=>value.toLowerCase().replaceAll('_','-');
      const matches=voices.filter(v=>chinese?/^zh-(hans|cn|sg)(-|$)/i.test(normalize(v.lang)):/^en(-|$)/i.test(normalize(v.lang)));
      const voice=matches.find(v=>v.localService&&normalize(v.lang)===normalize(lang))
        ??matches.find(v=>v.localService)
        ??matches.find(v=>normalize(v.lang)===normalize(lang))??matches[0];
      const current=new SpeechSynthesisUtterance(text);
      // An empty list can mean voices are still loading. Let the browser resolve
      // the default for lang instead of treating it as a missing language pack.
      current.lang=voice?.lang??lang;if(voice)current.voice=voice;
      current.rate=1;current.pitch=1;current.volume=1;
      current.onend=()=>{if(utterance.current===current){utterance.current=null;setSpeaking(false);}};
      current.onerror=event=>{
        if(utterance.current!==current)return;
        utterance.current=null;setSpeaking(false);
        const reason=event.error==='not-allowed'?'浏览器阻止了播报，请允许网站播放声音后重试。'
          :event.error==='network'?'语音服务网络连接失败，请检查网络后重试。'
          :['voice-unavailable','language-unavailable'].includes(event.error)?'浏览器没有可用的对应语言语音，请检查系统语音设置或更换浏览器。'
          :'请检查浏览器语音服务与声音输出后重试。';
        setSpeechHint(`译文播报未成功（${event.error}）：${reason}`);
      };
      utterance.current=current;setSpeaking(true);window.speechSynthesis.speak(current);
    }catch{stopSpeech();setSpeechHint('语音播报不可用，请检查浏览器和系统语音设置。');}
  }
  // Null preserves the existing, different source/translation defaults (including mobile).
  useEffect(()=>{
    for(const [key,value] of [['subtitleFontSize',display.fontSize],['subtitleFontColor',display.fontColor]] as const){
      try{if(value===null)localStorage.removeItem(key);else localStorage.setItem(key,String(value));}
      catch{/* Storage restrictions must never interrupt the live session. */}
    }
  },[display.fontSize,display.fontColor]);
  function adjustFont(delta:number){
    setDisplay(old=>({...old,fontSize:Math.max(MIN_FONT_SIZE,Math.min(MAX_FONT_SIZE,(old.fontSize??DEFAULT_FONT_SIZE)+delta))}));
  }
  const [status,setStatus]=useState<Status>({type:'status',state:'idle',detail:'选择音频输入后开始'});
  const [message,setMessage]=useState('');const [wakeStatus,setWakeStatus]=useState('未申请');
  const [activeInput,setActiveInput]=useState('');const [inputWarning,setInputWarning]=useState('');
  const [subtitles,setSubtitles]=useState<SubtitleState>(initialSubtitles);
  const [meter,setMeter]=useState(0);const [elapsed,setElapsed]=useState(0);const [busy,setBusy]=useState(false);
  const [switching,setSwitching]=useState(false);
  const [audioHint,setAudioHint]=useState('');const audioProgress=useRef(new AudioProgress());
  const [follow,setFollow]=useState(true);const [gaps,setGaps]=useState(0);
  const capture=useRef<Capture | SystemCapture | undefined>(undefined);const client=useRef<RelayClient | undefined>(undefined);const wake=useRef<WakeLockSentinel | undefined>(undefined);
  const wakePending=useRef(false);
  const captureRevision=useRef(0);const pendingCapture=useRef<Capture|SystemCapture|undefined>(undefined);
  const switchingAbort=useRef<AbortController|undefined>(undefined);
  const startupAbort=useRef<AbortController|undefined>(undefined);
  const history=useRef<HTMLDivElement>(null);const started=useRef(0);const active=useRef(false);const stateRef=useRef('idle');
  const refreshHealth=()=>fetch('/api/health').then(r=>{if(!r.ok)throw Error();return r.json();}).then(setHealth).catch(()=>{setHealth(undefined);setMessage('无法连接本机服务。请检查后台服务是否运行。');});
  const refreshDevices=()=>navigator.mediaDevices?.enumerateDevices().then(setDevices).catch(()=>setMessage('无法读取音频输入列表，请检查浏览器权限。'));
  const refreshOutputs=()=>fetch('/api/audio-outputs').then(async r=>{const data=await r.json();if(!r.ok)throw Error(data.message||'无法读取声音输出设备。');setOutputs(data.devices);}).catch(e=>setMessage(e instanceof Error?e.message:'无法读取声音输出设备。'));
  async function releaseWake(){const lock=wake.current;wake.current=undefined;try{await lock?.release();}catch{/* Wake Lock failure must never block translation. */}setWakeStatus('未常亮');}
  async function requestWake(){
    if(!active.current||!['running','muted'].includes(stateRef.current)||document.visibilityState!=='visible'||wake.current||wakePending.current)return;
    if(!navigator.wakeLock){setWakeStatus('浏览器不支持常亮');return;}
    wakePending.current=true;
    try{
      const lock=await navigator.wakeLock.request('screen');
      if(!active.current||!['running','muted'].includes(stateRef.current)){await lock.release();return;}
      wake.current=lock;setWakeStatus('常亮已开启');
      lock.addEventListener('release',()=>{if(wake.current===lock){wake.current=undefined;setWakeStatus('常亮已释放');}});
    }catch{setWakeStatus('常亮请求失败，请检查系统休眠设置');}finally{wakePending.current=false;}
  }
  function receiveStatus(s:Status){
    if(['running','muted'].includes(s.state)&&!['running','muted'].includes(stateRef.current)){
      audioProgress.current.reset();setAudioHint('');
    }
    stateRef.current=s.state;setStatus(s);
    if(s.classId&&s.sessionEpoch!==undefined)setSubtitles(old=>transition(old,s.classId!,s.sessionEpoch!));
    capture.current?.enable(['running','muted'].includes(s.state));
    if(s.gap)setGaps(n=>n+1);
    if(['paused','stopped','error'].includes(s.state)){
      const controller=switchingAbort.current;
      if(controller){
        switchingAbort.current=undefined;controller.abort();++captureRevision.current;
        setSwitching(false);setBusy(false);
      }
      void pendingCapture.current?.close();
      setSubtitles(markUnfinished);setMeter(0);active.current=false;if(s.state!=='paused')started.current=0;
      void capture.current?.close();void releaseWake();
    }
    if(['running','muted'].includes(s.state))void requestWake();
  }
  useEffect(()=>{
    client.current=new RelayClient(msg=>{
      if(msg.type==='subtitle'){
        if(msg.text&&msg.classId===client.current?.classId&&msg.sessionEpoch===client.current?.epoch){audioProgress.current.subtitle();setAudioHint('');}
        setSubtitles(old=>applySubtitle(old,msg));
      }
      if(msg.type==='error'){
        setMessage(msg.message);
        if(!msg.retryable)receiveStatus({type:'status',state:'error',detail:msg.message});
      }
    },receiveStatus);
    void refreshHealth();void refreshDevices();void refreshOutputs();
    const visibility=()=>{if(document.visibilityState==='visible'){void requestWake();void refreshHealth();void refreshOutputs();}};
    const deviceChange=()=>{void refreshDevices();void refreshOutputs();};
    const leave=(e:BeforeUnloadEvent)=>{if(active.current){e.preventDefault();}};
    const unload=()=>{startupAbort.current?.abort();switchingAbort.current?.abort();void pendingCapture.current?.close();client.current?.dispose();void capture.current?.close();};
    document.addEventListener('visibilitychange',visibility);navigator.mediaDevices?.addEventListener('devicechange',deviceChange);
    window.addEventListener('beforeunload',leave);window.addEventListener('pagehide',unload);
    const timer=setInterval(()=>{
      if(started.current)setElapsed(Math.floor((Date.now()-started.current)/1000));
      setAudioHint(active.current&&['running','muted'].includes(stateRef.current)?audioProgress.current.hint():'');
    },1000);
    return()=>{clearInterval(timer);unload();void releaseWake();document.removeEventListener('visibilitychange',visibility);navigator.mediaDevices?.removeEventListener('devicechange',deviceChange);window.removeEventListener('beforeunload',leave);window.removeEventListener('pagehide',unload);};
  },[]);
  useEffect(()=>{if(follow&&history.current)history.current.scrollTop=history.current.scrollHeight;},[subtitles.history,follow,source]);
  function createCapture(value:string,revision:number){
    const CaptureClass=resolveAudioSource(value).kind==='system'?SystemCapture:Capture;
    const current=()=>captureRevision.current===revision;
    const c=new CaptureClass(buffer=>{if(current())audioProgress.current.packet(buffer,client.current?.audio(buffer)===true);},level=>{if(current())setMeter(level);},detail=>{
      if(!current())return;
      setMessage(detail);void c.close();client.current?.end(true);receiveStatus({type:'status',state:'paused',detail});
    });
    if(c instanceof SystemCapture)c.onGap=detail=>{if(current()){setMessage(detail);setGaps(n=>n+1);}};
    return c;
  }
  async function changeInput(value:string){
    if(busy||value===input)return;
    setInput(value);setInputWarning('');
    if(!active.current){setActiveInput('');return;}
    setBusy(true);setSwitching(true);setMessage('');setMeter(0);
    audioProgress.current.reset();setAudioHint('');
    const controller=new AbortController();switchingAbort.current=controller;
    const previous=capture.current;capture.current=undefined;
    const revision=++captureRevision.current;
    const next=createCapture(value,revision);pendingCapture.current=next;
    try{
      await replaceCapture({previous,next,source:resolveAudioSource(value),packetMs,roomMode,signal:controller.signal,
        silence:packet=>{if(active.current&&['running','muted'].includes(stateRef.current))client.current?.audio(packet);},
        ready:actual=>{
          audioProgress.current.reset();setAudioHint('');
          capture.current=next;pendingCapture.current=undefined;
          next.enable(['running','muted'].includes(stateRef.current));
          setActiveInput(actual.label);setInputWarning(actual.warning);void refreshDevices();
        }});
    }catch(e){
      if(!controller.signal.aborted){
        const detail=e instanceof Error?e.message:'音频输入切换失败';
        setActiveInput('');setMessage(detail);client.current?.end(true);
        receiveStatus({type:'status',state:'paused',detail:'输入切换未成功，请选择可用设备后点击继续'});
      }
    }finally{
      if(pendingCapture.current===next)pendingCapture.current=undefined;
      if(switchingAbort.current===controller)switchingAbort.current=undefined;
      if(captureRevision.current===revision){setSwitching(false);setBusy(false);}
    }
  }
  async function begin(fresh:boolean){
    if(busy)return;setBusy(true);setMessage('');
    const controller=new AbortController();startupAbort.current=controller;
    receiveStatus({type:'status',state:'connecting',detail:'正在准备音频设备与翻译连接…'});
    try{
      // The page checks health on load and when returning to the foreground.
      // Reuse a ready result; the relay still validates configuration at start.
      let readyHealth=health;
      if(!readyHealth?.ready){
        const r=await fetch('/api/health',{signal:controller.signal});if(!r.ok)throw Error('本机服务不可用');
        const h:Health=await r.json();setHealth(h);assertReady(h);readyHealth=h;
      }
      controller.signal.throwIfAborted();
      client.current?.prepare(readyHealth.cloudWarmupSupported===true);
      await capture.current?.close();setActiveInput('');setInputWarning('');
      controller.signal.throwIfAborted();
      const c=createCapture(input,++captureRevision.current);pendingCapture.current=c;
      const actual=await c.open(resolveAudioSource(input),packetMs,roomMode);
      controller.signal.throwIfAborted();
      if(!c.isLive())throw Error('音频输入已中断，请重新选择并启动。');
      capture.current=c;pendingCapture.current=undefined;
      setActiveInput(actual.label);setInputWarning(actual.warning);active.current=true;
      if(fresh){setSubtitles(initialSubtitles);started.current=Date.now();setElapsed(0);setGaps(0);setFollow(true);}
      client.current?.start(mode,fresh);void refreshDevices();
    }catch(e){
      active.current=false;client.current?.cancelPrepare();await pendingCapture.current?.close();pendingCapture.current=undefined;await capture.current?.close();
      if(controller.signal.aborted)receiveStatus({type:'status',state:fresh?'idle':'paused',detail:'启动已取消'});
      else{setMessage(e instanceof Error?e.message:'音频输入启动失败');receiveStatus({type:'status',state:'error',detail:'启动未成功，请检查配置与音频输入权限'});}
    }finally{if(startupAbort.current===controller)startupAbort.current=undefined;setBusy(false);}
  }
  async function end(pause:boolean){
    if(busy&&!switchingAbort.current)return;setBusy(true);
    try{
      const controller=switchingAbort.current;switchingAbort.current=undefined;
      controller?.abort();if(controller)++captureRevision.current;
      setSwitching(false);await pendingCapture.current?.close();
      // Flush is delivered before stop, while upload is still accepted.
      await capture.current?.close(!pause);active.current=false;setMeter(0);await releaseWake();
      receiveStatus({type:'status',state:'finishing',detail:'正在接收最后字幕（最多 5 秒）…'});client.current?.end(pause);
    }finally{setBusy(false);}
  }
  function download(){const blob=new Blob([exportText(subtitles)],{type:'text/plain;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`课堂字幕-${new Date().toISOString().slice(0,10)}.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  const running=['connecting','running','muted','recovering'].includes(status.state);
  const locked=running||busy||status.state==='finishing';
  const time=`${String(Math.floor(elapsed/3600)).padStart(2,'0')}:${String(Math.floor(elapsed/60)%60).padStart(2,'0')}:${String(elapsed%60).padStart(2,'0')}`;
  const translations=subtitles.current.translation, original=subtitles.current.source;
  const inputs=audioSources(devices,outputs);
  const defaultOutput=outputs.find(d=>d.isDefault);
  const differentOutput=systemAudio&&defaultOutput&&input!==`system:${defaultOutput.id}`;
  return <main>
    <header><div><span className="eyebrow">CLASSROOM INTERPRETER</span><h1>课堂同传<span>中英实时字幕</span></h1></div><button className="quiet" onClick={()=>{if(document.fullscreenElement)void document.exitFullscreen();else void document.documentElement.requestFullscreen().catch(()=>setMessage('浏览器未能进入全屏。'));}}>⛶ 全屏</button></header>
    <section className="toolbar" aria-label="课程控制">
      <label>音频输入<select value={input} disabled={busy||status.state==='finishing'} onChange={e=>void changeInput(e.target.value)}><optgroup label="麦克风 / 输入设备">{inputs.filter(d=>d.group==='input').map(d=><option key={d.value} value={d.value}>{d.label}</option>)}</optgroup>{outputs.length>0&&<optgroup label="扬声器 / 耳机">{inputs.filter(d=>d.group==='output').map(d=><option key={d.value} value={d.value}>{d.label}</option>)}</optgroup>}</select></label>
      <label>翻译方向<select value={mode} disabled={locked} onChange={e=>setMode(e.target.value)}><option value="auto">自动中英反转</option><option value="zh-en">中文 → English</option><option value="en-zh">English → 中文</option></select></label>
      <div className="actions">{running?<button className="primary" disabled={busy&&!switching} onClick={()=>void end(true)}>{busy&&!switching?'正在启动…':'Ⅱ 暂停'}</button>:<button className="primary" disabled={busy||status.state==='finishing'} onClick={()=>void begin(status.state!=='paused')}>{busy?'正在启动…':status.state==='paused'?'▶ 继续':'▶ 开始课程'}</button>}<button disabled={(busy&&!switching)||!['paused','connecting','running','muted','recovering'].includes(status.state)} onClick={()=>void end(false)}>结束</button></div>
    </section>
    {differentOutput&&<aside className="capture-help">系统当前默认播放设备：{defaultOutput.label}。如果音频正在从它播放，请在“扬声器 / 耳机”组里选择这个设备。</aside>}
    {switching?<div className="input-source" role="status">正在切换音频输入…</div>:activeInput&&<div className="input-source">{running?'当前输入':'本次输入'}：{activeInput}{inputWarning&&<span> · {inputWarning}</span>}</div>}
    {(!health?.ready||message)&&<aside className="notice" role="alert">{message||(!health?'正在检查本机服务…':!health.credentialsConfigured?'尚未配置 API Key · 编辑本机 .env 后重启服务。':health.credentialSourceMismatch?'当前是火山方舟 Key · 请从豆包语音控制台获取 API Key 并更新 .env。':'协议语义尚未实测 · 请先运行探测脚本并确认配置。')}{health?.credentialSourceMismatch&&<a href="https://console.volcengine.com/speech/new/setting/apikeys?projectName=default" target="_blank" rel="noreferrer">获取豆包语音 Key ↗</a>}<button className="quiet" onClick={()=>void refreshHealth()}>重新检查</button></aside>}
    <div className="statusbar"><span className={`dot ${status.state}`}/><strong>{!switching&&['running','muted'].includes(status.state)&&audioHint?'等待字幕':labels[status.state]||status.state}</strong><span>{!switching&&['running','muted'].includes(status.state)&&audioHint?audioHint:status.detail}</span><span className="timer">{time}</span></div>
    <section className="stage" aria-label="当前字幕">
      <div className="stage-top"><span>当前译文</span><span>LIVE · {mode==='auto'?'中文 ⇄ English':mode==='zh-en'?'中文 → English':'English → 中文'}</span></div>
      <div className={`translation ${translations?.text?'':'placeholder'}`} style={{...subtitleStyle,fontSize:font}} aria-live="polite" aria-atomic="true">{translations?.text||'让语言跟上课堂。'}{translations?.text&&!translations.isFinal&&<span className="provisional">翻译中</span>}</div>
      {source&&<div className="original"><span>原文</span><p style={subtitleStyle}>{original?.text||'开始课程后，原文将在这里显示。'}</p></div>}
      <div className="stage-bottom"><div className="volume"><span>音频输入</span><meter min="0" max="1" value={displayLevel(meter)} title={meter>0?`${Math.round(20*Math.log10(meter))} dBFS`:'无输入'}/><span>{meter>0?`${Math.round(20*Math.log10(meter))} dBFS`:'无输入'}</span></div><div className="speech-actions"><span>{wakeStatus}</span><button type="button" className="quiet speech-button" disabled={!speechSupported||(!speaking&&!translations?.text.trim())} aria-label={speaking?'停止播报':'播报当前译文'} aria-pressed={speaking} title={speechSupported?'朗读当前译文；优先本地音色，其他音色可能需要联网；播报声音可能被当前输入再次采集':'当前浏览器不支持语音播报'} onClick={speakTranslation}>{speaking?'■ 停止播报':'🔊 播报译文'}</button></div></div>
      {(!speechSupported||speechHint)&&<div className="speech-hint" role="status">{speechSupported?speechHint:'当前浏览器不支持语音播报。'}</div>}
    </section>
    <section className="preferences" aria-label="字幕设置"><div className="display-settings" role="group" aria-label="显示设置"><span>显示设置</span><div className="font-size-control" role="group" aria-label="字号"><span>字号</span><button type="button" aria-label="减小字号" disabled={font<=MIN_FONT_SIZE} onClick={()=>adjustFont(-FONT_STEP)}>−</button><output aria-live="polite">{font}px</output><button type="button" aria-label="增大字号" disabled={font>=MAX_FONT_SIZE} onClick={()=>adjustFont(FONT_STEP)}>+</button></div><label>字体颜色<input type="color" value={display.fontColor??DEFAULT_FONT_COLOR} onChange={e=>setDisplay(old=>({...old,fontColor:e.target.value}))}/></label><button type="button" className="quiet" onClick={()=>setDisplay({fontSize:null,fontColor:null})}>恢复默认</button></div><label><input type="checkbox" checked={source} onChange={e=>setSource(e.target.checked)}/>显示原文</label>{!systemAudio&&<label>收音方式<select value={roomMode?'room':'standard'} disabled={locked} onChange={e=>setRoomMode(e.target.value==='room')}><option value="standard">标准 · 近讲</option><option value="room">教室 · 远距离</option></select></label>}<label>音频包<select value={packetMs} disabled={locked} onChange={e=>setPacketMs(Number(e.target.value))}><option value="80">80ms · 默认</option><option value="40">40ms · 实验</option></select></label></section>
    <section className="history-section"><div className="section-title"><h2>课堂记录 <span>{subtitles.history.length} 段</span></h2><div>{!follow&&<button onClick={()=>setFollow(true)}>↓ 回到最新</button>}<button className="quiet" disabled={!subtitles.history.length&&!translations?.text&&!original?.text} onClick={download}>导出 TXT</button></div></div>
      <div className="history" ref={history} onScroll={e=>{const el=e.currentTarget;setFollow(el.scrollHeight-el.clientHeight-el.scrollTop<36);}}>
        {!subtitles.history.length?<div className="empty">定稿后的字幕会按时间留在这里。<small>记录仅保存在当前页面，刷新前请主动导出。</small></div>:subtitles.history.filter(e=>source||e.channel==='translation').map(e=><article key={`${e.sessionEpoch}/${e.channel}/${e.segmentId}`}><time>{new Date(e.receivedAt).toLocaleTimeString()}</time><div><span className="channel">{e.channel==='translation'?'译文':'原文'}{e.unfinished?' · 未定稿':''}</span><p>{e.text||'（无文本）'}</p></div></article>)}
      </div>
    </section>
    <footer><span>所选音频经本机中继发送至火山引擎 · 依赖网络</span><span>{gaps?`已记录 ${gaps} 次缺口提示`:'当前页面内存保存 · 不保存音频'}</span></footer>
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
