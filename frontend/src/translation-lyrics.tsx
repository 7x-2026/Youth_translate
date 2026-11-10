import React,{memo,useCallback,useEffect,useLayoutEffect,useMemo,useRef} from 'react';
import type {Entry} from './subtitles';
import {translationKey,translationLyrics} from './lyrics-entries';

export const TranslationLyrics=memo(function TranslationLyrics({history,current,font,color}:{
  history:Entry[];current:Entry|undefined;font:number;color:string|undefined;
}){
  const rows=useMemo(()=>translationLyrics(history,current),[history,current]);
  const frame=useRef<HTMLDivElement>(null),active=useRef<HTMLParagraphElement>(null);
  const lastKey=useRef<string|undefined>(undefined),lastTarget=useRef<number|undefined>(undefined);
  const follow=useCallback((behavior:ScrollBehavior)=>{
    const box=frame.current,line=active.current;
    if(!box)return;
    if(!line){box.scrollTop=0;lastKey.current=undefined;lastTarget.current=undefined;return;}
    const height=box.clientHeight;
    const singleLine=parseFloat(getComputedStyle(line).lineHeight)||parseFloat(getComputedStyle(line).fontSize)*1.5;
    const bottomSpace=Math.min(singleLine*1.5,Math.max(0,height-singleLine));
    box.style.setProperty('--lyrics-bottom-space',`${bottomSpace}px`);
    // Fill the window from the top, then follow the newest text near the bottom.
    // Reserve 1.5 text lines instead of an artificial half-window of blank space.
    const target=Math.max(0,line.offsetTop+line.offsetHeight+bottomSpace-height);
    const key=line.dataset.entryKey;
    if(key===lastKey.current&&lastTarget.current!==undefined&&Math.abs(target-lastTarget.current)<1)return;
    const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    box.scrollTo({top:target,behavior:!lastKey.current||reduced?'auto':behavior});
    lastKey.current=key;lastTarget.current=target;
  },[]);
  useLayoutEffect(()=>{follow('smooth');},[rows,font,follow]);
  useEffect(()=>{
    const box=frame.current;if(!box||typeof ResizeObserver==='undefined')return;
    const observer=new ResizeObserver(()=>follow('auto'));observer.observe(box);
    return()=>observer.disconnect();
  },[follow]);
  return <div className="translation-lyrics" ref={frame} tabIndex={0} aria-label="译文滚动窗口" style={{fontSize:font,color}}>
    {current?<div className="lyrics-lines">{rows.map(entry=>{
      const isCurrent=translationKey(entry)===translationKey(current);
      return <p key={translationKey(entry)} data-entry-key={translationKey(entry)}
        className={`lyric-line${isCurrent?' current-translation':''}`} ref={isCurrent?active:undefined}
        aria-current={isCurrent?'true':undefined} aria-live={isCurrent?'polite':'off'} aria-atomic={true}>
        {entry.text}{isCurrent&&!entry.isFinal&&<span className="provisional">{entry.unfinished?'未定稿':'翻译中'}</span>}
      </p>;
    })}</div>:<p className="lyrics-empty">开始后，译文显示在这里。</p>}
  </div>;
});
