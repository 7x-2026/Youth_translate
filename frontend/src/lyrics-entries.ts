import type {Entry} from './subtitles';

export const translationKey=(entry:Entry)=>`${entry.classId}/${entry.sessionEpoch}/${entry.segmentId}`;

// Include received history only up to the sentence actually being presented.
// Pending raw results must not bypass the existing reading dwell.
export function translationLyrics(history:Entry[],current:Entry|undefined,limit=30):Entry[]{
  if(!current)return [];
  const entries:Entry[]=[],positions=new Map<string,number>();
  for(const entry of history){
    if(entry.channel!=='translation'||entry.classId!==current.classId
      ||entry.sessionEpoch>current.sessionEpoch||!entry.text.trim())continue;
    const key=translationKey(entry),position=positions.get(key);
    if(position===undefined){positions.set(key,entries.length);entries.push(entry);}
    else if(!entries[position].isFinal&&entry.revision>=entries[position].revision)entries[position]=entry;
  }
  const position=positions.get(translationKey(current));
  const older=position===undefined?entries:entries.slice(0,position);
  const olderCount=Math.max(0,limit-1);
  return [...(olderCount?older.slice(-olderCount):[]),current];
}
