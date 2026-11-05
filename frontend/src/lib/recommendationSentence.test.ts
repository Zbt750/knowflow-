import {expect,it} from 'vitest';
import {recommendationSentence} from './recommendationSentence';
it.each(['先阅读讲解','先阅读讲解。','先阅读讲解。。','先阅读讲解.'])('adds only one sentence ending for %s',value=>expect(recommendationSentence(value)).toBe('先阅读讲解。'));
it('keeps decimal values and questions intact',()=>{expect(recommendationSentence('预计0.5分钟')).toBe('预计0.5分钟。');expect(recommendationSentence('是否继续？')).toBe('是否继续？');expect(recommendationSentence('')).toBe('');});
