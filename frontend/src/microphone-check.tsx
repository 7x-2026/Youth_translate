import {useEffect,useRef,useState} from 'react';
import {Capture,microphoneError} from './capture';
import {displayLevel} from './audio';

export function MicrophoneCheck({deviceId,raw,onChecking,onDevices}:{deviceId:string;raw:boolean;onChecking:(value:boolean)=>void;onDevices:()=>void}){
  const [state,setState]=useState<'idle'|'opening'|'listening'>('idle');
  const [hint,setHint]=useState('先授权并试音，确认电平会随讲话变化，再开始课程。');
  const [level,setLevel]=useState(0);
  const capture=useRef<Capture|undefined>(undefined);const timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);
  const peak=useRef(0);const alive=useRef(true);
  const stop=async()=>{const c=capture.current;capture.current=undefined;clearTimeout(timer.current);await c?.close();if(alive.current){setState('idle');setLevel(0);onChecking(false);}};
  useEffect(()=>{alive.current=true;const leave=()=>{void stop();};window.addEventListener('pagehide',leave);return()=>{alive.current=false;window.removeEventListener('pagehide',leave);void stop();onChecking(false);};},[]);
  async function start(){
    peak.current=0;setState('opening');onChecking(true);setHint('请在浏览器的麦克风权限提示中选择“允许”；已授权时不会重复弹窗。');
    const c=new Capture(()=>{},value=>{if(capture.current===c){peak.current=Math.max(peak.current,value);setLevel(value);}},detail=>{if(capture.current===c){setHint(detail);void stop();}});
    capture.current=c;
    try{
      // Start capture directly from the click; no health check or cloud request comes first.
      const actual=await c.open({kind:'microphone',deviceId},80,raw);
      if(!alive.current||capture.current!==c){await c.close();return;}
      onDevices();c.enable(true);setState('listening');setHint(`已授权：${actual.label}。请讲话，正在进行 10 秒本地试音…`);
      timer.current=setTimeout(()=>{setHint(peak.current>=0.001?'已检测到输入电平，可以开始课程。':'已授权，但试音未检测到明显电平。请核对输入设备、静音与输入音量；也可开启“原声模式”再试。');void stop();},10000);
    }catch(error){if(alive.current&&capture.current===c){setHint(microphoneError(error).message);await stop();}}
  }
  return <section className="microphone-check" aria-label="麦克风授权与试音"><div><strong>麦克风准备</strong><span>本地试音 · 不上传、不保存</span></div><button type="button" onClick={()=>{if(state==='idle')void start();else{setHint('试音已停止，麦克风已释放。');void stop();}}}>{state==='idle'?'授权并试音':state==='opening'?'取消授权等待':'停止试音'}</button><meter min="0" max="1" value={displayLevel(level)} aria-label="麦克风试音电平"/><p role="status">{hint}</p></section>;
}
