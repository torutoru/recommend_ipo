// v1.11 (#33): 모바일에서 입력칸이 가상 키보드에 가려지지 않게,
// 포커스 시 해당 요소를 화면 중앙으로 부드럽게 스크롤.

export function scrollIntoViewOnMobile<T extends HTMLElement>(e: React.FocusEvent<T>) {
  try {
    if (window.matchMedia('(max-width: 768px)').matches) {
      e.currentTarget.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  } catch { /* matchMedia 미지원 환경에서는 조용히 무시 */ }
}
