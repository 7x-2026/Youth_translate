import {it,expect} from 'vitest';
import {initialSubtitles,transition,applySubtitle,markUnfinished,exportText,previousTranslation,type SubtitleEvent} from './subtitles';
const event=(props:Partial<SubtitleEvent>={}):SubtitleEvent=>({type:'subtitle',classId:'class',sessionEpoch:1,segmentId:'translation-1',channel:'translation',revision:1,text:'Hello',isFinal:false,...props});
it('renders translation before any source, replacing snapshots',()=>{
  let s=transition(initialSubtitles,'class',1);s=applySubtitle(s,event());s=applySubtitle(s,event({text:'Hello class',revision:2}));
  expect(s.current.translation?.text).toBe('Hello class');expect(s.current.source).toBeUndefined();expect(s.history).toHaveLength(0);
});
it('ignores stale revisions and archives a final only once',()=>{
  let s=transition(initialSubtitles,'class',1);s=applySubtitle(s,event({revision:3,isFinal:true}));const final=s;
  s=applySubtitle(s,event({revision:2,text:'wrong'}));expect(s).toBe(final);
  s=applySubtitle(s,event({revision:4,isFinal:true}));expect(s.history).toHaveLength(1);
});
it('keeps independent unpaired channels and rejects old sessions',()=>{
  let s=transition(initialSubtitles,'class',1);s=applySubtitle(s,event());s=applySubtitle(s,event({channel:'source',segmentId:'source-1',text:'你好',isFinal:true}));
  expect(s.history).toHaveLength(1);s=transition(s,'class',2);
  expect(s.history).toHaveLength(2);expect(s.history[1].unfinished).toBe(true);const current=s;
  expect(applySubtitle(s,event({isFinal:true}))).toBe(current);
});
it('final replaces previously unfinished archive and never duplicates',()=>{
  let s=applySubtitle(transition(initialSubtitles,'class',1),event());s=markUnfinished(s);
  s=applySubtitle(s,event({isFinal:true,revision:2}));expect(s.history).toHaveLength(1);expect(s.history[0].unfinished).toBeUndefined();
});
it('marks replaced partial segments and exports provisional text honestly',()=>{
  let s=applySubtitle(transition(initialSubtitles,'class',1),event());s=applySubtitle(s,event({segmentId:'translation-2',text:'Second'}));
  expect(s.history[0].unfinished).toBe(true);expect(exportText(s)).toContain('未定稿');expect(exportText(s)).toContain('Second');
});
it('new class clears history',()=>{
  const s=applySubtitle(transition(initialSubtitles,'class',1),event({isFinal:true}));expect(transition(s,'new',0).history).toHaveLength(0);
});

it('does not show the current finalized translation twice',()=>{
  const s=applySubtitle(transition(initialSubtitles,'class',1),event({isFinal:true}));
  expect(previousTranslation(s)).toBeUndefined();
});
it('keeps the previous sentence through partial updates and finalization',()=>{
  let s=applySubtitle(transition(initialSubtitles,'class',1),event({isFinal:true,text:'First'}));
  s=applySubtitle(s,event({segmentId:'translation-2',text:'Second'}));
  expect(previousTranslation(s)?.text).toBe('First');
  s=applySubtitle(s,event({segmentId:'translation-2',text:'Second sentence',revision:2}));
  expect(previousTranslation(s)?.text).toBe('First');
  s=applySubtitle(s,event({segmentId:'translation-2',text:'Second sentence',revision:3,isFinal:true}));
  s=applySubtitle(s,event({channel:'source',segmentId:'source-2',text:'原文',isFinal:true}));
  expect(previousTranslation(s)?.text).toBe('First');
});
it('advances by segment even when two sentences have identical text',()=>{
  let s=applySubtitle(transition(initialSubtitles,'class',1),event({isFinal:true}));
  s=applySubtitle(s,event({segmentId:'translation-2',isFinal:true}));
  expect(previousTranslation(s)?.segmentId).toBe('translation-1');
  s=applySubtitle(s,event({segmentId:'translation-3',text:'Third'}));
  expect(previousTranslation(s)?.segmentId).toBe('translation-2');
});
it('retains interrupted text honestly and distinguishes matching IDs across epochs',()=>{
  let s=applySubtitle(transition(initialSubtitles,'class',1),event());
  s=applySubtitle(s,event({segmentId:'translation-2',text:'Second'}));
  expect(previousTranslation(s)?.unfinished).toBe(true);
  s=transition(s,'class',2);
  s=applySubtitle(s,event({sessionEpoch:2,segmentId:'translation-2',text:'New epoch'}));
  expect(previousTranslation(s)?.sessionEpoch).toBe(1);
  expect(previousTranslation(transition(s,'new-class',0))).toBeUndefined();
});
it('skips empty archived translations and ignores stale revisions',()=>{
  let s=applySubtitle(transition(initialSubtitles,'class',1),event({isFinal:true,text:'First'}));
  s=applySubtitle(s,event({segmentId:'translation-2',isFinal:true,text:'   '}));
  s=applySubtitle(s,event({segmentId:'translation-3',text:'Third',revision:3}));
  s=applySubtitle(s,event({segmentId:'translation-3',text:'stale',revision:2}));
  expect(previousTranslation(s)?.text).toBe('First');
  expect(s.current.translation?.text).toBe('Third');
});
