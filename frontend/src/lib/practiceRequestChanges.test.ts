import {expect,it} from 'vitest';
import {notifyPracticeRequestsChanged,onPracticeRequestsChanged} from './practiceRequestChanges';
it('invalidates every mounted owner and stops notifying unmounted owners',()=>{
 let a=0,b=0;const offA=onPracticeRequestsChanged(()=>a++),offB=onPracticeRequestsChanged(()=>b++);
 notifyPracticeRequestsChanged();expect([a,b]).toEqual([1,1]);
 offA();notifyPracticeRequestsChanged();expect([a,b]).toEqual([1,2]);offB();
});
