import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {readStudyRetry,saveStudyRetry,clearStudyRetry} from './studyRetryContext';
let data:Map<string,string>;
beforeEach(()=>{data=new Map();vi.stubGlobal('localStorage',{getItem:(k:string)=>data.get(k)??null,setItem:(k:string,v:string)=>data.set(k,v),removeItem:(k:string)=>data.delete(k)});});
afterEach(()=>vi.unstubAllGlobals());
it('restores only the same paper within a bounded lifetime',()=>{
 saveStudyRetry('retry','paper',1000);expect(readStudyRetry('paper',2000)).toBe('retry');
 expect(readStudyRetry('other-paper',2000)).toBeNull();expect(data.size).toBe(0);
});
it.each([0,5*60*60*1000])('rejects future or expired retry pointer at %s',now=>{
 saveStudyRetry('retry','paper',1000);expect(readStudyRetry('paper',now)).toBeNull();expect(data.size).toBe(0);
});
it('clears the pointer on explicit close without deleting any server receipt',()=>{
 saveStudyRetry('retry','paper',1000);clearStudyRetry();expect(readStudyRetry('paper',2000)).toBeNull();
});
