// v1.11 (#35): 「새 버전 안내」 토스트 로컬 미리보기용.
//
// 호출부는 반드시 `import.meta.env.DEV` 로 감싸서 호출. prod 번들에서는 데드 코드로 제거.

export function isUpdateDemoActive(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const u = new URL(window.location.href)
    return u.searchParams.get('demo') === 'update'
  } catch {
    return false
  }
}
