// 수집 키 로컬 저장 — localStorage 접근 자체가 실패할 수 있어 모두 try/catch.

const STORAGE_KEY = 'recommendIpo:collectKey'

export function loadCollectKey(): string | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v && v.length > 0 ? v : null
  } catch {
    return null
  }
}

export function saveCollectKey(key: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, key)
  } catch {
    // noop — 저장 실패해도 세션 메모리로만 돌아가도록 호출부에서 처리.
  }
}

export function clearCollectKey(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // noop
  }
}
