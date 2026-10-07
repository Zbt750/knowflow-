import { describe, expect, it } from 'vitest';
import { photoFileError, photoDimensionsError } from './photoInput';

describe('photo input boundaries', () => {
  it('accepts the supported formats and exact byte limit', () => {
    for (const type of ['image/jpeg', 'image/png', 'image/webp']) {
      expect(photoFileError({type, size:5 * 1024 * 1024})).toBeNull();
    }
  });
  it('rejects unsupported formats, empty and over-limit files', () => {
    expect(photoFileError({type:'image/heic',size:100})).toContain('JPEG');
    for (const size of [0, -1, 5 * 1024 * 1024 + 1]) {
      expect(photoFileError({type:'image/png',size})).not.toBeNull();
    }
  });
  it('accepts the exact dimension and pixel boundaries', () => {
    expect(photoDimensionsError(4096,1)).toBeNull();
    expect(photoDimensionsError(4000,3000)).toBeNull();
  });
  it('rejects excess side length or pixel count in either orientation', () => {
    for (const [w,h] of [[4097,1],[1,4097],[4000,3001],[3001,4000]]) {
      expect(photoDimensionsError(w,h)).toContain('尺寸过大');
    }
  });
  it('rejects invalid dimensions', () => {
    for (const [w,h] of [[0,1],[-1,1],[1,NaN],[Infinity,1],[1.5,1]]) {
      expect(photoDimensionsError(w,h)).toContain('无法读取');
    }
  });
});
