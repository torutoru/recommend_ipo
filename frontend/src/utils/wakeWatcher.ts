// Render 무료 플랜이 15분 무요청 시 슬립 → 첫 요청이 30초+ 걸림.
// 활성 요청이 3초를 넘기면 "서버 깨우는 중" 배너를 띄우기 위한 전역 pub/sub.

type SlowListener = (slow: boolean) => void

let active = 0
let slowTimer: ReturnType<typeof setTimeout> | null = null
let isSlow = false
let listeners: SlowListener[] = []

const SLOW_AFTER_MS = 3000

export function subscribeSlow(cb: SlowListener): () => void {
  listeners.push(cb)
  cb(isSlow) // 현재 상태 즉시 반영
  return () => {
    listeners = listeners.filter(l => l !== cb)
  }
}

function emit(next: boolean): void {
  if (isSlow === next) return
  isSlow = next
  for (const l of listeners) l(next)
}

export async function trackRequest<T>(p: Promise<T>): Promise<T> {
  active++
  if (slowTimer === null) {
    slowTimer = setTimeout(() => emit(true), SLOW_AFTER_MS)
  }
  try {
    return await p
  } finally {
    active--
    if (active === 0) {
      if (slowTimer !== null) {
        clearTimeout(slowTimer)
        slowTimer = null
      }
      emit(false)
    }
  }
}
