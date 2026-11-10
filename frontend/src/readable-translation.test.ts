import {afterEach,expect,it,vi} from 'vitest';
import {ReadableTranslation,type TranslationView} from './readable-translation';
import {applySubtitle,exportText,initialSubtitles,transition,type Entry} from './subtitles';

const presenters:ReadableTranslation[]=[];
afterEach(()=>{presenters.splice(0).forEach(p=>p.dispose());vi.useRealTimers();});
function entry(segmentId:string,revision=1,isFinal=true,text=segmentId):Entry{
  return {type:'subtitle',classId:'class',sessionEpoch:1,segmentId,revision,isFinal,text,channel:'translation',receivedAt:Date.now()};
}
function setup(){
  vi.useFakeTimers();vi.setSystemTime(0);
  let view:TranslationView={};const changed=vi.fn((next:TranslationView)=>{view=next;});
  const presenter=new ReadableTranslation(changed,()=>Date.now());presenters.push(presenter);
  presenter.setSession('class',1);
  return {presenter,changed,get view(){return view;}};
}
it('shows the first sentence and same-sentence revisions immediately',()=>{
  const s=setup();s.presenter.push(entry('a',1,false,'partial'));
  expect(s.view.current?.text).toBe('partial');
  s.presenter.push(entry('a',2,false,'more words'));expect(s.view.current?.text).toBe('more words');
  s.presenter.push(entry('a',3,true,'complete'));expect(s.view.current?.text).toBe('complete');
  s.presenter.push(entry('a',2,false,'stale'));expect(s.view.current?.text).toBe('complete');
});
it('holds a rapid next sentence but adds at most one second of waiting',()=>{
  const s=setup();s.presenter.push(entry('a'));vi.advanceTimersByTime(100);s.presenter.push(entry('b'));
  vi.advanceTimersByTime(999);expect(s.view.current?.segmentId).toBe('a');
  vi.advanceTimersByTime(1);expect(s.view.current?.segmentId).toBe('b');expect(s.view.previous?.segmentId).toBe('a');
});
it('does not delay a next sentence when the current one had enough reading time',()=>{
  const s=setup();s.presenter.push(entry('a'));vi.advanceTimersByTime(2000);s.presenter.push(entry('b'));
  expect(s.view.current?.segmentId).toBe('b');expect(vi.getTimerCount()).toBe(0);
});
it('pending partial/final updates do not keep pushing the deadline back',()=>{
  const s=setup();s.presenter.push(entry('a'));vi.advanceTimersByTime(100);s.presenter.push(entry('b',1,false));
  vi.advanceTimersByTime(700);s.presenter.push(entry('b',2,false,'more'));
  vi.advanceTimersByTime(150);s.presenter.push(entry('b',3,true,'complete'));
  vi.advanceTimersByTime(150);expect(s.view.current?.text).toBe('complete');expect(s.view.current?.isFinal).toBe(true);
});
it('gives a just-finalized visible sentence a short grace period',()=>{
  const s=setup();s.presenter.push(entry('a',1,false));vi.advanceTimersByTime(2000);
  s.presenter.push(entry('a',2,true));vi.advanceTimersByTime(10);s.presenter.push(entry('b'));
  vi.advanceTimersByTime(389);expect(s.view.current?.segmentId).toBe('a');
  vi.advanceTimersByTime(1);expect(s.view.current?.segmentId).toBe('b');
});
it('limits finalization grace by the original pending-sentence deadline',()=>{
  const s=setup();s.presenter.push(entry('a',1,false));vi.advanceTimersByTime(600);s.presenter.push(entry('b'));
  vi.advanceTimersByTime(500);s.presenter.push(entry('a',2,true));
  vi.advanceTimersByTime(399);expect(s.view.current?.segmentId).toBe('a');
  vi.advanceTimersByTime(1);expect(s.view.current?.segmentId).toBe('b');
});
it('coalesces a burst to the latest sentence rather than building a display backlog',()=>{
  const s=setup();s.presenter.push(entry('a'));
  for(let i=0;i<10;i++){vi.advanceTimersByTime(50);s.presenter.push(entry(`new-${i}`));}
  vi.advanceTimersByTime(550);expect(s.view.current?.segmentId).toBe('new-9');
  expect(s.view.previous?.segmentId).toBe('a');
  s.presenter.push(entry('new-0',2,true,'late old final'));
  expect(s.view.current?.segmentId).toBe('new-9');expect(vi.getTimerCount()).toBe(0);
});
it('pause/end flushes only the latest pending sentence and leaves no timer',()=>{
  const s=setup();s.presenter.push(entry('a'));vi.advanceTimersByTime(100);s.presenter.push(entry('b',1,false));
  s.presenter.flush();expect(s.view.current?.segmentId).toBe('b');expect(s.view.current?.unfinished).toBe(true);
  expect(vi.getTimerCount()).toBe(0);vi.advanceTimersByTime(3000);expect(s.view.current?.segmentId).toBe('b');
});
it('a new epoch cancels old pending subtitles and rejects late old-epoch events',()=>{
  const s=setup();s.presenter.push(entry('a'));s.presenter.push(entry('b'));
  s.presenter.setSession('class',2);s.presenter.push(entry('b',2));
  expect(s.view.current).toBeUndefined();
  s.presenter.push({...entry('fresh'),sessionEpoch:2});vi.advanceTimersByTime(3000);
  expect(s.view.current?.segmentId).toBe('fresh');expect(s.view.previous).toBeUndefined();expect(vi.getTimerCount()).toBe(0);
});
it('a late final can update the previous line without rolling back the current line',()=>{
  const s=setup();s.presenter.push(entry('a',1,false));s.presenter.push(entry('b'));s.presenter.flush();
  expect(s.view.previous?.unfinished).toBe(true);s.presenter.push(entry('a',2,true,'old complete'));
  expect(s.view.current?.segmentId).toBe('b');expect(s.view.previous?.text).toBe('old complete');
  expect(s.view.previous?.isFinal).toBe(true);expect(s.view.previous?.unfinished).toBe(false);
});
it('keeps raw history and exports immediate while presentation waits',()=>{
  const s=setup();let raw=transition(initialSubtitles,'class',1);
  raw=applySubtitle(raw,entry('a'));s.presenter.push(raw.current.translation!);
  vi.advanceTimersByTime(100);raw=applySubtitle(raw,entry('b'));s.presenter.push(raw.current.translation!);
  expect(s.view.current?.segmentId).toBe('a');expect(raw.current.translation?.segmentId).toBe('b');
  expect(raw.history).toHaveLength(2);expect(exportText(raw)).toContain('b');
});
it('dispose prevents pending updates after the page unmounts',()=>{
  const s=setup();s.presenter.push(entry('a'));s.presenter.push(entry('b'));s.presenter.dispose();
  const count=s.changed.mock.calls.length;vi.advanceTimersByTime(3000);
  expect(s.changed).toHaveBeenCalledTimes(count);expect(vi.getTimerCount()).toBe(0);
});
