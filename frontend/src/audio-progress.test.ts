import { expect, it } from 'vitest';
import { AudioProgress } from './audio-progress';
import { pcm16 } from './audio';

const sound=pcm16(Array(1280).fill(.1)),silence=new ArrayBuffer(2560);
it('does not treat ten minutes of valid silent uploads as a recognition failure',()=>{
  const progress=new AudioProgress();progress.reset(0);
  for(let t=80;t<=600000;t+=80)progress.packet(silence,true,t);
  expect(progress.hint(600000)).toBe('');
});
it('reports prolonged sound without subtitles without claiming sound is speech',()=>{
  const progress=new AudioProgress();progress.reset(0);
  for(let t=80;t<=29920;t+=80)progress.packet(sound,true,t);
  expect(progress.hint(29920)).toBe('');
  progress.packet(sound,true,30000);
  expect(progress.hint(30000)).toContain('云端暂未返回字幕');
  expect(progress.hint(30000)).toContain('尚不能确定');
});
it('clears the wait as soon as subtitle text arrives',()=>{
  const progress=new AudioProgress();progress.reset(0);
  for(let t=80;t<=120000;t+=80)progress.packet(sound,true,t);
  expect(progress.hint(120000)).toContain('云端暂未返回字幕');
  progress.subtitle(120000);expect(progress.hint(120000)).toBe('');
});
it('distinguishes stopped capture from a rejected upload',()=>{
  const progress=new AudioProgress();progress.reset(0);
  expect(progress.hint(6000)).toContain('暂未收到采集音频');
  progress.packet(sound,false,6000);
  expect(progress.hint(6000)).toContain('暂未能上传');
  progress.packet(sound,true,6080);expect(progress.hint(6080)).toBe('');
});
it('does not warn about speech recognition on sparse noise or after sound stops',()=>{
  const progress=new AudioProgress();progress.reset(0);progress.packet(sound,true,80);
  progress.packet(sound,true,30000);expect(progress.hint(30000)).toBe('');
  for(let t=30080;t<=40000;t+=80)progress.packet(sound,true,t);
  for(let t=40080;t<=50000;t+=80)progress.packet(silence,true,t);
  expect(progress.hint(50000)).toBe('');
});
it('starts a new observation window after a source change or reconnection',()=>{
  const progress=new AudioProgress();progress.reset(0);
  for(let t=80;t<=60000;t+=80)progress.packet(sound,true,t);
  expect(progress.hint(60000)).toContain('云端暂未返回字幕');
  progress.reset(60000);progress.packet(sound,true,60080);
  expect(progress.hint(60080)).toBe('');
});
