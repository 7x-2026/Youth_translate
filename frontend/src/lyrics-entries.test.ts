import {expect,it} from 'vitest';
import type {Entry} from './subtitles';
import {translationLyrics} from './lyrics-entries';
const entry=(segmentId:string,text=segmentId):Entry=>({type:'subtitle',classId:'class',sessionEpoch:1,
  segmentId,text,channel:'translation',revision:1,isFinal:true,receivedAt:0});
it('does not reveal pending future sentences before the readable current advances',()=>{
  const history=[entry('a'),entry('b'),entry('c')];
  expect(translationLyrics(history,history[0]).map(e=>e.segmentId)).toEqual(['a']);
  expect(translationLyrics(history,history[2]).map(e=>e.segmentId)).toEqual(['a','b','c']);
});
it('uses the presented partial snapshot instead of a newer raw final for the same sentence',()=>{
  const partial={...entry('b','partial'),isFinal:false};
  const rows=translationLyrics([entry('a'),{...entry('b','complete'),revision:2},entry('c')],partial);
  expect(rows.map(e=>e.text)).toEqual(['a','partial']);
});
it('includes prior history before an unarchived current sentence and filters other courses/epochs',()=>{
  const current={...entry('b'),isFinal:false};
  const history=[entry('a'),{...entry('wrong-course'),classId:'other'},{...entry('future'),sessionEpoch:2},
    {...entry('source'),channel:'source' as const}];
  expect(translationLyrics(history,current).map(e=>e.segmentId)).toEqual(['a','b']);
});
it('bounds lyric DOM history without changing the complete underlying record',()=>{
  const history=Array.from({length:100},(_,i)=>entry(String(i)));
  const rows=translationLyrics(history,history[99]);
  expect(rows).toHaveLength(30);expect(rows[0].segmentId).toBe('70');expect(rows[29].segmentId).toBe('99');
  expect(history).toHaveLength(100);expect(translationLyrics(history,history[99],1)).toEqual([history[99]]);
});
it('deduplicates unfinished history and keeps its newest revision',()=>{
  const history=[{...entry('a','old'),isFinal:false},{...entry('a','complete'),revision:2},entry('b')];
  expect(translationLyrics(history,entry('b')).map(e=>e.text)).toEqual(['complete','b']);
});
it('shows no old transcript when the current session has no displayed translation',()=>{
  expect(translationLyrics([entry('old')],undefined)).toEqual([]);
});
