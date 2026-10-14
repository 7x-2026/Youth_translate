import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Capture } from './capture';
import { displayLevel } from './audio';
import { RelayClient, type Status } from './connection';
import { initialSubtitles, transition, applySubtitle, markUnfinished, exportText, type SubtitleState } from './subtitles';
import './style.css';
type Health={credentialsConfigured:boolean;credentialSourceMismatch:boolean;subtitleSemanticsVerified:boolean;ready:boolean};
const labels:Record<string,string>={idle:'准备就绪',connecting:'正在连接',running:'正在翻译',muted:'云端等待语音',recovering:'正在恢复',finishing:'正在收尾',paused:'已暂停',stopped:'已结束',error:'需要处理'};
function App(){
  const [health,setHealth]=useState<Health>();
  const [devices,setDevices]=useState<MediaDeviceInfo[]>([]);
  const [device,setDevice]=useState('');const [mode,setMode]=useState('auto');const [packetMs,setPacketMs]=useState(80);const [roomMode,setRoomMode]=useState(false);
  const [font,setFont]=useState(48);const [source,setSource]=useState(true);
  const [status,setStatus]=useState<Status>({type:'status',state:'idle',detail:'开始后申请麦克风权限'});
  const [message,setMessage]=useState('');const [wakeStatus,setWakeStatus]=useState('未申请');
  const [activeInput,setActiveInput]=useState('');const [inputWarning,setInputWarning]=useState('');
  const [subtitles,setSubtitles]=useState<SubtitleState>(initialSubtitles);
  const [meter,setMeter]=useState(0);const [elapsed,setElapsed]=useState(0);const [busy,setBusy]=useState(false);
  const [follow,setFollow]=useState(true);const [gaps,setGaps]=useState(0);
  const capture=useRef<Capture | undefined>(undefined);const client=useRef<RelayClient | undefined>(undefined);const wake=useRef<WakeLockSentinel | undefined>(undefined);
  const wakePending=useRef(false);
  const history=useRef<HTMLDivElement>(null);const started=useRef(0);const active=useRef(false);const stateRef=useRef('idle');
  const refreshHealth=()=>fetch('/api/health').then(r=>{if(!r.ok)throw Error();return r.json();}).then(setHealth).catch(()=>{setHealth(undefined);setMessage('无法连接本机服务。请检查后台服务是否运行。');});
  const refreshDevices=()=>navigator.mediaDevices?.enumerateDevices().then(list=>setDevices(list.filter(x=>x.kind==='audioinput'&&!['default','communications'].includes(x.deviceId)))).catch(()=>setMessage('无法读取麦克风列表，请检查浏览器权限。'));
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
    stateRef.current=s.state;setStatus(s);
    if(s.classId&&s.sessionEpoch!==undefined)setSubtitles(old=>transition(old,s.classId!,s.sessionEpoch!));
    capture.current?.enable(['running','muted'].includes(s.state));
    if(s.gap)setGaps(n=>n+1);
    if(['paused','stopped','error'].includes(s.state)){
      setSubtitles(markUnfinished);setMeter(0);active.current=false;if(s.state!=='paused')started.current=0;
      void capture.current?.close();void releaseWake();
    }
    if(['running','muted'].includes(s.state))void requestWake();
  }
  useEffect(()=>{
    client.current=new RelayClient(msg=>{
      if(msg.type==='subtitle')setSubtitles(old=>applySubtitle(old,msg));
      if(msg.type==='error'){
        setMessage(msg.message);
        if(!msg.retryable)receiveStatus({type:'status',state:'error',detail:msg.message});
      }
    },receiveStatus);
    void refreshHealth();void refreshDevices();
    const visibility=()=>{if(document.visibilityState==='visible'){void requestWake();void refreshHealth();}};
    const deviceChange=()=>{void refreshDevices();};
    const leave=(e:BeforeUnloadEvent)=>{if(active.current){e.preventDefault();}};
    const unload=()=>{client.current?.dispose();void capture.current?.close();};
    document.addEventListener('visibilitychange',visibility);navigator.mediaDevices?.addEventListener('devicechange',deviceChange);
    window.addEventListener('beforeunload',leave);window.addEventListener('pagehide',unload);
    const timer=setInterval(()=>{if(started.current)setElapsed(Math.floor((Date.now()-started.current)/1000));},1000);
    return()=>{clearInterval(timer);client.current?.dispose();void capture.current?.close();void releaseWake();document.removeEventListener('visibilitychange',visibility);navigator.mediaDevices?.removeEventListener('devicechange',deviceChange);window.removeEventListener('beforeunload',leave);window.removeEventListener('pagehide',unload);};
  },[]);
  useEffect(()=>{if(follow&&history.current)history.current.scrollTop=history.current.scrollHeight;},[subtitles.history,follow,source]);
  async function begin(fresh:boolean){
    if(busy)return;setBusy(true);setMessage('');
    try{
      const r=await fetch('/api/health');if(!r.ok)throw Error('本机服务不可用');
      const h:Health=await r.json();setHealth(h);
      if(!h.ready)throw Error(!h.credentialsConfigured?'请先在 .env 配置 VOLC_API_KEY，然后重启服务。':h.credentialSourceMismatch?'当前是火山方舟 ark- Key；请换为豆包语音新版控制台的 API Key。':'请先运行协议探测，确认音频封装及字幕语义，再设置 VOLC_SUBTITLE_RESPONSE_MODE。');
      await capture.current?.close();
      const c=new Capture(buffer=>client.current?.audio(buffer),setMeter,detail=>{
        setMessage(detail);void c.close();client.current?.end(true);receiveStatus({type:'status',state:'paused',detail});
      });capture.current=c;
      const input=await c.open(device,packetMs,roomMode);setActiveInput(input.label);setInputWarning(input.warning);active.current=true;
      if(fresh){setSubtitles(initialSubtitles);started.current=Date.now();setElapsed(0);setGaps(0);setFollow(true);}
      client.current?.start(mode,fresh);void refreshDevices();
    }catch(e){active.current=false;setMessage(e instanceof Error?e.message:'麦克风启动失败');await capture.current?.close();receiveStatus({type:'status',state:'error',detail:'启动未成功，请检查配置与麦克风权限'});}
    finally{setBusy(false);}
  }
  async function end(pause:boolean){
    if(busy)return;setBusy(true);
    try{
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
  return <main>
    <header><div><span className="eyebrow">CLASSROOM INTERPRETER</span><h1>课堂同传<span>中英实时字幕</span></h1></div><button className="quiet" onClick={()=>{if(document.fullscreenElement)void document.exitFullscreen();else void document.documentElement.requestFullscreen().catch(()=>setMessage('浏览器未能进入全屏。'));}}>⛶ 全屏</button></header>
    <section className="toolbar" aria-label="课程控制">
      <label>麦克风<select value={device} disabled={locked} onChange={e=>setDevice(e.target.value)}><option value="">电脑内置优先 · 自动</option>{devices.map((d,i)=><option key={d.deviceId||i} value={d.deviceId}>{d.label||`麦克风 ${i+1}`}</option>)}</select></label>
      <label>翻译方向<select value={mode} disabled={locked} onChange={e=>setMode(e.target.value)}><option value="auto">自动中英反转</option><option value="zh-en">中文 → English</option><option value="en-zh">English → 中文</option></select></label>
      <div className="actions">{running?<button className="primary" disabled={busy} onClick={()=>void end(true)}>Ⅱ 暂停</button>:<button className="primary" disabled={busy||status.state==='finishing'} onClick={()=>void begin(status.state!=='paused')}>{busy?'正在启动…':status.state==='paused'?'▶ 继续':'▶ 开始课程'}</button>}<button disabled={busy||!['paused','connecting','running','muted','recovering'].includes(status.state)} onClick={()=>void end(false)}>结束</button></div>
    </section>
    {activeInput&&<div className="input-source">{running?'当前输入':'本次输入'}：{activeInput}{inputWarning&&<span> · {inputWarning}</span>}</div>}
    {(!health?.ready||message)&&<aside className="notice" role="alert">{message||(!health?'正在检查本机服务…':!health.credentialsConfigured?'尚未配置 API Key · 编辑本机 .env 后重启服务。':health.credentialSourceMismatch?'当前是火山方舟 Key · 请从豆包语音控制台获取 API Key 并更新 .env。':'协议语义尚未实测 · 请先运行探测脚本并确认配置。')}{health?.credentialSourceMismatch&&<a href="https://console.volcengine.com/speech/new/setting/apikeys?projectName=default" target="_blank" rel="noreferrer">获取豆包语音 Key ↗</a>}<button className="quiet" onClick={()=>void refreshHealth()}>重新检查</button></aside>}
    <div className="statusbar"><span className={`dot ${status.state}`}/><strong>{labels[status.state]||status.state}</strong><span>{status.detail}</span><span className="timer">{time}</span></div>
    <section className="stage" aria-label="当前字幕">
      <div className="stage-top"><span>当前译文</span><span>LIVE · {mode==='auto'?'中文 ⇄ English':mode==='zh-en'?'中文 → English':'English → 中文'}</span></div>
      <div className={`translation ${translations?.text?'':'placeholder'}`} style={{fontSize:font}} aria-live="polite" aria-atomic="true">{translations?.text||'让语言跟上课堂。'}{translations?.text&&!translations.isFinal&&<span className="provisional">翻译中</span>}</div>
      {source&&<div className="original"><span>原文</span><p>{original?.text||'开始课程后，原文将在这里显示。'}</p></div>}
      <div className="stage-bottom"><div className="volume"><span>麦克风输入</span><meter min="0" max="1" value={displayLevel(meter)} title={meter>0?`${Math.round(20*Math.log10(meter))} dBFS`:'无输入'}/><span>{meter>0?`${Math.round(20*Math.log10(meter))} dBFS`:'无输入'}</span></div><span>{wakeStatus}</span></div>
    </section>
    <section className="preferences" aria-label="字幕设置"><label>字幕字号<input type="range" min="28" max="80" step="2" value={font} onChange={e=>setFont(Number(e.target.value))}/><span>{font}px</span></label><label><input type="checkbox" checked={source} onChange={e=>setSource(e.target.checked)}/>显示原文</label><label>收音方式<select value={roomMode?'room':'standard'} disabled={locked} onChange={e=>setRoomMode(e.target.value==='room')}><option value="standard">标准 · 近讲</option><option value="room">教室 · 远距离</option></select></label><label>音频包<select value={packetMs} disabled={locked} onChange={e=>setPacketMs(Number(e.target.value))}><option value="80">80ms · 默认</option><option value="40">40ms · 实验</option></select></label></section>
    <section className="history-section"><div className="section-title"><h2>课堂记录 <span>{subtitles.history.length} 段</span></h2><div>{!follow&&<button onClick={()=>setFollow(true)}>↓ 回到最新</button>}<button className="quiet" disabled={!subtitles.history.length&&!translations?.text&&!original?.text} onClick={download}>导出 TXT</button></div></div>
      <div className="history" ref={history} onScroll={e=>{const el=e.currentTarget;setFollow(el.scrollHeight-el.clientHeight-el.scrollTop<36);}}>
        {!subtitles.history.length?<div className="empty">定稿后的字幕会按时间留在这里。<small>记录仅保存在当前页面，刷新前请主动导出。</small></div>:subtitles.history.filter(e=>source||e.channel==='translation').map(e=><article key={`${e.sessionEpoch}/${e.channel}/${e.segmentId}`}><time>{new Date(e.receivedAt).toLocaleTimeString()}</time><div><span className="channel">{e.channel==='translation'?'译文':'原文'}{e.unfinished?' · 未定稿':''}</span><p>{e.text||'（无文本）'}</p></div></article>)}
      </div>
    </section>
    <footer><span>麦克风音频经本机中继发送至火山引擎 · 依赖网络</span><span>{gaps?`已记录 ${gaps} 次缺口提示`:'当前页面内存保存 · 不保存音频'}</span></footer>
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
