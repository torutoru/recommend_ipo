// v1.11 (#34): 빌드 메타 — vite.config.ts define 주입. 사용자가 반영 여부 직접 확인.
const COMMIT = typeof __BUILD_COMMIT__ === 'string' ? __BUILD_COMMIT__ : ''
const BUILD_TIME = typeof __BUILD_TIME__ === 'string' ? __BUILD_TIME__ : ''

function shortBuildLabel(): string {
  // 커밋 해시 우선. 로컬 빌드는 빈 문자열이므로 ISO 날짜/시각(UTC) 로 폴백.
  if (COMMIT) return COMMIT
  if (BUILD_TIME) {
    // "2026-10-27T02:10:00Z" → "2026-10-27 02:10 UTC"
    const d = new Date(BUILD_TIME)
    if (!Number.isNaN(d.getTime())) {
      const pad = (n: number) => String(n).padStart(2, '0')
      return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
    }
  }
  return ''
}

export function Disclaimer() {
  const label = shortBuildLabel()
  return (
    <p className="disclaimer" role="note">
      ※ 투자 권유가 아니며 참고용 정보입니다. 공시 데이터는 수집 시점에 따라 지연되거나
      누락될 수 있으며, 투자 결과에 대한 책임은 이용자에게 있습니다.
      {label && (
        <>
          {' '}<span className="build-tag" title={BUILD_TIME}>build {label}</span>
        </>
      )}
    </p>
  )
}
