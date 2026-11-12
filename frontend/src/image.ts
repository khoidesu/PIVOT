// Chuẩn bị ảnh trước khi gửi: thu nhỏ cạnh dài ≤ MAX_SIDE rồi mã hoá lại JPEG. Việc vẽ lại qua canvas cũng LOẠI BỎ EXIF
// (toạ độ GPS, kiểu máy) nên dữ liệu thừa không rời trình duyệt; máy chủ vẫn kiểm tra loại tệp + kích thước và gỡ metadata một lần nữa.
export const MAX_SIDE = 1600
export const ACCEPT = 'image/jpeg,image/png,image/webp'
export const PDF_MIME = 'application/pdf'
export const MAX_PDF_BYTES = 5_000_000 // khớp giới hạn máy chủ (intake_pdf_max_bytes)
export const MAX_INPUT_BYTES = 15_000_000 // ảnh gốc quá lớn thì không đọc (tránh treo trình duyệt)

/** Kích thước sau khi thu nhỏ, giữ tỉ lệ; ảnh nhỏ hơn giới hạn thì giữ nguyên. */
export function fitSize(w: number, h: number, max = MAX_SIDE): { w: number; h: number } {
  const k = Math.min(1, max / Math.max(w, h))
  return { w: Math.max(1, Math.round(w * k)), h: Math.max(1, Math.round(h * k)) }
}

export interface PreparedImage { base64: string; previewUrl: string; bytes: number }

export async function prepareImage(file: File): Promise<PreparedImage> {
  if (!ACCEPT.split(',').includes(file.type)) throw new Error('UNSUPPORTED')
  if (file.size > MAX_INPUT_BYTES) throw new Error('TOO_LARGE')
  const bmp = await createImageBitmap(file)
  const { w, h } = fitSize(bmp.width, bmp.height)
  const canvas = document.createElement('canvas')
  canvas.width = w; canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('CANVAS')
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, w, h) // nền trắng cho ảnh PNG trong suốt
  ctx.drawImage(bmp, 0, 0, w, h); bmp.close()
  const blob: Blob | null = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.85))
  if (!blob) throw new Error('CANVAS')
  const buf = new Uint8Array(await blob.arrayBuffer())
  let bin = ''
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000))
  return { base64: btoa(bin), previewUrl: URL.createObjectURL(blob), bytes: buf.length }
}

/** Loại tệp được chọn: PDF đọc nguyên tệp (máy chủ tự lấy chữ hoặc vẽ trang); ảnh được thu nhỏ trước. */
export const isPdf = (file: { type: string; name: string }) => file.type === PDF_MIME || /\.pdf$/i.test(file.name)

/** Thuộc tính accept của ô chọn tệp theo khả năng máy chủ: PDF luôn được (nếu bật), ảnh chỉ khi máy chủ có đọc ảnh. */
export function acceptFor(image: boolean, pdf: boolean): string {
  return [pdf ? `${PDF_MIME},.pdf` : '', image ? ACCEPT : ''].filter(Boolean).join(',')
}

export async function readPdf(file: File): Promise<{ base64: string; bytes: number }> {
  if (file.size > MAX_PDF_BYTES) throw new Error('PDF_TOO_LARGE')
  const buf = new Uint8Array(await file.arrayBuffer())
  let bin = ''
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000))
  return { base64: btoa(bin), bytes: buf.length }
}
