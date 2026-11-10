import {useEffect,useRef,useState} from 'react';
import type {Entry} from './subtitles';
import {ReadableTranslation,type TranslationView} from './readable-translation';

export function useReadableTranslation(entry:Entry|undefined,classId:string,epoch:number,live:boolean){
  const [view,setView]=useState<TranslationView>({});
  const presenter=useRef<ReadableTranslation|undefined>(undefined);
  useEffect(()=>{
    const current=new ReadableTranslation(setView);presenter.current=current;
    return()=>{current.dispose();presenter.current=undefined;};
  },[]);
  useEffect(()=>{
    const current=presenter.current;
    current?.setSession(classId,epoch);
    if(entry)current?.push(entry);
    if(!live)current?.flush();
  },[entry,classId,epoch,live]);
  return view;
}
