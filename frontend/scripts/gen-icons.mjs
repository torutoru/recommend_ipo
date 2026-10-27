// v1.11 (#32): PWA 아이콘 생성 — 상표·로고 없이 단순한 자체 아이콘.
//
// Node builtin(zlib) 만 사용해 솔리드 다크 배경 + 중앙 블록 패턴의 PNG 를 만든다.
// 192·512 + maskable-512 세 종류를 `public/icons/` 에 쓴다.

import { mkdirSync, writeFileSync } from 'node:fs'
import { deflateSync } from 'node:zlib'

const BG = [11, 18, 28]      // #0b121c — styles.css :root --bg
const FG = [90, 157, 253]    // #5a9dfd — styles.css --accent

const OUT_DIR = new URL('../public/icons/', import.meta.url)
mkdirSync(OUT_DIR, { recursive: true })

function crc32(buf) {
  let c = 0xffffffff
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i]
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1))
  }
  return (c ^ 0xffffffff) >>> 0
}

function chunk(type, data) {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length, 0)
  const typeBuf = Buffer.from(type, 'ascii')
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0)
  return Buffer.concat([len, typeBuf, data, crc])
}

function makePng(size, drawPixel) {
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8    // bit depth
  ihdr[9] = 2    // RGB
  ihdr[10] = 0   // compression (deflate)
  ihdr[11] = 0   // filter
  ihdr[12] = 0   // interlace

  // 각 행 앞에 filter type(0=None), RGB 3바이트씩.
  const rowBytes = 1 + size * 3
  const rows = Buffer.alloc(rowBytes * size)
  for (let y = 0; y < size; y++) {
    rows[y * rowBytes] = 0
    for (let x = 0; x < size; x++) {
      const [r, g, b] = drawPixel(x, y, size)
      const off = y * rowBytes + 1 + x * 3
      rows[off] = r; rows[off + 1] = g; rows[off + 2] = b
    }
  }
  const idatData = deflateSync(rows)

  return Buffer.concat([
    sig,
    chunk('IHDR', ihdr),
    chunk('IDAT', idatData),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

// 중앙 둥근사각형 + 4분할 블록(상승 바 느낌). 상표가 아닌 추상 심볼.
function draw(x, y, size) {
  const c = size / 2
  const r = size * 0.44             // 외곽 둥근사각형 반지름 느낌(실제론 원)
  const dx = x - c, dy = y - c
  const inside = Math.sqrt(dx * dx + dy * dy) <= r
  if (!inside) return BG

  // 중앙 정렬된 "증가하는 바" 패턴: 4개 세로 바가 왼쪽→오른쪽으로 높아짐.
  const barAreaW = size * 0.52
  const barAreaH = size * 0.42
  const barAreaX = c - barAreaW / 2
  const barAreaY = c - barAreaH / 2 + size * 0.04
  const gap = size * 0.03
  const bars = 4
  const barW = (barAreaW - gap * (bars - 1)) / bars

  if (x >= barAreaX && x <= barAreaX + barAreaW &&
      y >= barAreaY && y <= barAreaY + barAreaH) {
    const col = Math.floor((x - barAreaX) / (barW + gap))
    const colStart = barAreaX + col * (barW + gap)
    const colEnd = colStart + barW
    if (x >= colStart && x <= colEnd) {
      // 바 높이: col=0 → 25%, col=1 → 50%, col=2 → 75%, col=3 → 100%
      const h = barAreaH * (0.25 + col * 0.25)
      if (y >= barAreaY + barAreaH - h) {
        return FG
      }
    }
  }
  return BG
}

// maskable: safe-zone 중앙 80% 안에만 심볼이 있도록 더 작게 그린다.
function drawMaskable(x, y, size) {
  const c = size / 2
  const r = size * 0.5
  const dx = x - c, dy = y - c
  if (Math.sqrt(dx * dx + dy * dy) > r) return BG
  // 중앙 60% 안의 좌표만 심볼. 외곽 20% 는 안전 패딩.
  const inner = size * 0.6
  const innerX0 = c - inner / 2
  const innerY0 = c - inner / 2
  if (x < innerX0 || x > innerX0 + inner || y < innerY0 || y > innerY0 + inner) return BG
  const localX = ((x - innerX0) / inner) * size
  const localY = ((y - innerY0) / inner) * size
  const col = draw(localX, localY, size)
  return col === BG ? BG : col
}

function write(name, size, fn) {
  const buf = makePng(size, fn)
  writeFileSync(new URL(name, OUT_DIR), buf)
  console.log(`${name}  ${size}×${size}  ${buf.length} bytes`)
}

write('icon-192.png', 192, draw)
write('icon-512.png', 512, draw)
write('icon-maskable-512.png', 512, drawMaskable)
