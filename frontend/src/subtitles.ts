export type SubtitleEvent = {type:'subtitle';classId:string;sessionEpoch:number;segmentId:string;channel:'source'|'translation';revision:number;text:string;isFinal:boolean;startMs?:number;endMs?:number};
export type Entry = SubtitleEvent & {unfinished?:boolean;receivedAt:number};
export type SubtitleState = {classId:string;epoch:number;current:Partial<Record<'source'|'translation',Entry>>;history:Entry[]};
export const initialSubtitles:SubtitleState={classId:'',epoch:0,current:{},history:[]};
const key=(e:SubtitleEvent)=>`${e.sessionEpoch}/${e.channel}/${e.segmentId}`;
export function transition(state:SubtitleState,classId:string,epoch:number):SubtitleState {
  if(classId!==state.classId) return {classId,epoch,current:{},history:[]};
  if(epoch<=state.epoch) return state;
  return {...markUnfinished(state),epoch};
}
export function markUnfinished(state:SubtitleState):SubtitleState {
  const pending=Object.values(state.current).filter((e):e is Entry=>!!e && !e.isFinal && !!e.text);
  return {...state,current:{},history:[...state.history,...pending.map(e=>({...e,unfinished:true}))]};
}
export function applySubtitle(state:SubtitleState,event:SubtitleEvent,now=Date.now()):SubtitleState {
  if(event.classId!==state.classId || event.sessionEpoch!==state.epoch) return state;
  const id=key(event), old=state.current[event.channel];
  const archived=state.history.find(e=>key(e)===id);
  if(archived?.isFinal || (old && key(old)===id && event.revision<=old.revision)) return state;
  const entry={...event,receivedAt:now};
  let history=state.history;
  if(old && key(old)!==id && !old.isFinal && old.text) history=[...history,{...old,unfinished:true}];
  if(event.isFinal) {
    const index=history.findIndex(e=>key(e)===id);
    history=index<0?[...history,entry]:history.map((e,i)=>i===index?entry:e);
  }
  return {...state,current:{...state.current,[event.channel]:entry},history};
}
export function exportText(state:SubtitleState) {
  const entries=[...state.history,...Object.values(state.current).filter((e):e is Entry=>!!e&&!e.isFinal&&!!e.text).map(e=>({...e,unfinished:true}))];
  return entries.map(e=>`[${new Date(e.receivedAt).toLocaleTimeString()}] ${e.channel==='translation'?'译文':'原文'}${e.unfinished?'（未定稿）':''}\n${e.text}`).join('\n\n');
}
