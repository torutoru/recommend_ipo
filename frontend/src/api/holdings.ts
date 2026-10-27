// v1.10 (#29) + v1.11 (#31): 「내 공모주」 저장소.
//
// v1.11: backend API 로 전환(계약 v1.7). GET /api/holdings · PUT /api/holdings/{corp_code} · DELETE /…
//   - `list()`/`get()`/`subscribe()` 는 **sync** — 모듈 로드 시 받은 캐시를 즉시 반환.
//   - `upsert()`/`remove()` 는 **async** — 서버 응답을 기다렸다가 캐시 갱신 → emit.
//   - 모듈 로드 직후: GET 으로 서버 목록 로드 + (있으면) 기존 localStorage 데이터를 PUT 으로 이전.
//   - 성공한 항목만 localStorage 에서 제거(실패는 유지 → 다음 로드 때 재시도).
//
// 서버 오류 처리:
//   - GET 404 은 "아직 backend 미지원"(backend #51 전) → 조용히 empty + loadError 유지 안 함.
//   - 그 외 GET 오류는 loadError 로 노출(UI 에서 재시도 안내).
//   - PUT/DELETE 는 호출부에 예외를 던져 폼이 오류를 표시한다(입력값 유지).
//
// localStorage 는 이후 '배너 닫기' 상태 용도로만 사용.

import { api } from './index'
import { HttpError } from '../utils/httpError'

export interface Holding {
  corp_code: string
  shares: number
  price: number
  memo: string
  created_at: string
  updated_at: string
  // v1.7 서버 조인 필드(응답 전용). mock·real 공통. UI 는 /api/ipos 조인을 그대로 사용 가능.
  corp_name?: string | null
  listing_date?: string | null
  amount_krw?: number
}

export interface HoldingDraft {
  corp_code: string
  shares: number
  price: number
  memo?: string
}

export interface HoldingsStatus {
  loading: boolean
  loadError: string | null
}

const LEGACY_KEY = 'recommend-ipo:holdings:v1'

interface State {
  cache: Record<string, Holding>
  loading: boolean
  loadError: string | null
}

const state: State = { cache: {}, loading: true, loadError: null }
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach(fn => { try { fn() } catch { /* ignore */ } })
}

export const holdings = {
  // 캐시 즉시 반환.
  list(): Holding[] {
    return Object.values(state.cache).sort((a, b) => a.corp_code.localeCompare(b.corp_code))
  },
  get(corp_code: string): Holding | null {
    return state.cache[corp_code] ?? null
  },

  // 서버에 PUT 후 캐시 갱신. 실패 시 호출부에 예외 전파.
  async upsert(d: HoldingDraft): Promise<Holding> {
    const body = {
      shares: d.shares,
      price: d.price,
      memo: (d.memo ?? '').slice(0, 60),
    }
    const saved = await api.putHolding(d.corp_code, body)
    state.cache[d.corp_code] = saved
    emit()
    return saved
  },

  async remove(corp_code: string): Promise<void> {
    await api.deleteHolding(corp_code)
    delete state.cache[corp_code]
    emit()
  },

  subscribe(fn: () => void): () => void {
    listeners.add(fn)
    return () => { listeners.delete(fn) }
  },

  getStatus(): HoldingsStatus {
    return { loading: state.loading, loadError: state.loadError }
  },

  async reload(): Promise<void> {
    state.loading = true
    state.loadError = null
    emit()
    try {
      const items = await api.getHoldings()
      state.cache = Object.fromEntries(items.map(h => [h.corp_code, h]))
      state.loadError = null
    } catch (e) {
      // backend #51 미지원 시 404 — 조용히 empty 로.
      if (e instanceof HttpError && e.status === 404) {
        state.cache = {}
        state.loadError = null
      } else {
        state.loadError = e instanceof Error ? e.message : String(e)
      }
    } finally {
      state.loading = false
      emit()
    }
  },
}

interface LegacyEntry { shares: number; price: number; memo?: string }

async function migrateLocal(): Promise<void> {
  let parsed: Record<string, LegacyEntry> | null = null
  try {
    const raw = localStorage.getItem(LEGACY_KEY)
    if (!raw) return
    const obj: unknown = JSON.parse(raw)
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
      parsed = obj as Record<string, LegacyEntry>
    }
  } catch {
    return
  }
  if (!parsed) return
  const entries = Object.entries(parsed)
  if (entries.length === 0) {
    try { localStorage.removeItem(LEGACY_KEY) } catch { /* ignore */ }
    return
  }

  const remaining: Record<string, LegacyEntry> = {}
  for (const [code, item] of entries) {
    try {
      const saved = await api.putHolding(code, {
        shares: Number(item.shares),
        price: Number(item.price),
        memo: String(item.memo ?? ''),
      })
      state.cache[code] = saved
    } catch {
      // 실패한 항목은 보존 — 다음 로드/수정 때 재시도될 수 있음.
      remaining[code] = item
    }
  }
  try {
    if (Object.keys(remaining).length === 0) {
      localStorage.removeItem(LEGACY_KEY)
    } else {
      localStorage.setItem(LEGACY_KEY, JSON.stringify(remaining))
    }
  } catch { /* ignore */ }
  emit()
}

// 모듈 로드 직후: 서버 로드 → legacy localStorage 이전 → 다시 emit.
void (async () => {
  await holdings.reload()
  await migrateLocal()
})()
