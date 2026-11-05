// Mirror the upload limits for early feedback; the server remains authoritative.
export function photoFileError(file: { type: string; size: number }): string | null {
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    return '请选择JPEG、PNG或WebP图片。';
  }
  if (file.size <= 0 || file.size > 5 * 1024 * 1024) {
    return '图片不能为空或超过5MB，请另选图片。';
  }
  return null;
}

export function photoDimensionsError(width: number, height: number): string | null {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) {
    return '无法读取图片，请另选一张JPEG、PNG或WebP图片。';
  }
  if (Math.max(width, height) > 4096 || width * height > 12_000_000) {
    return '图片尺寸过大：边长需不超过4096像素，总像素不超过1200万。请降低拍照分辨率或另选图片。';
  }
  return null;
}
