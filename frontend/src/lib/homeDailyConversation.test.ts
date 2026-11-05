import {expect,it} from 'vitest';
import {homeStudyDay,homeDayKey,homeDayTitle} from './homeDailyConversation';
it('uses Shanghai midnight regardless of runtime timezone',()=>{expect(homeStudyDay(new Date('2026-10-27T15:59:59Z'))).toBe('2026-10-27');expect(homeStudyDay(new Date('2026-10-27T16:00:00Z'))).toBe('2026-10-28');});
it('new calendar day has an independent pointer and discoverable dated title',()=>{expect(homeDayKey('2026-10-27')).not.toBe(homeDayKey('2026-10-28'));expect(homeDayTitle('2026-10-28')).toBe('首页学习 2026-10-28');});
