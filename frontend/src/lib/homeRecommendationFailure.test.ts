import {expect,it} from 'vitest';
import {ApiError} from '../api/client';
import {homeRecommendationFailure} from './homeRecommendationFailure';
it('classifies the captured identifier-free 404 without mislabelling it as a deleted topic',()=>{const message=homeRecommendationFailure(new ApiError('resource not found',404,'not_found'));expect(message).toContain('接口/版本不匹配');expect(message).toContain('404');expect(message).toContain('/api/plans/today/home-recommendation');expect(message).not.toContain('resource not found');});
it('separates denied authorization from missing route and never suggests bypass',()=>{expect(homeRecommendationFailure(new ApiError('forbidden',403,'forbidden'))).toContain('访问受限');expect(homeRecommendationFailure(new ApiError('unauthorized',401,'unauthorized'))).toContain('401');});
it('distinguishes network and server failures and retains diagnostic codes',()=>{expect(homeRecommendationFailure(new ApiError('offline',null,null))).toContain('连接失败');expect(homeRecommendationFailure(new ApiError('internal error',500,'internal_error'))).toContain('500 / internal_error');});
it('preserves unexpected failure detail without claiming successful fallback',()=>{expect(homeRecommendationFailure(new Error('解析失败'))).toContain('解析失败');expect(homeRecommendationFailure(new Error('解析失败'))).toContain('不会自动创建试卷');});
