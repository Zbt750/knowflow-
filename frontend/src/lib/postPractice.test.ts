import {expect,it} from 'vitest';
import {postPracticeSummary,type PostPractice} from './postPractice';
const base={applicable:true,status:'CONSOLIDATE',label:'建议巩固',reason:'两道不同题独立错误'} as PostPractice;
it('post practice risk never changes the foundation label',()=>{expect(postPracticeSummary(base)).toEqual({foundation:'基础毕业：已通过',label:'建议巩固',reason:'两道不同题独立错误',review:true});});
it('ungraduated or absent data never displays graduation',()=>{expect(postPracticeSummary({...base,applicable:false})).toBeNull();expect(postPracticeSummary(null)).toBeNull();});
