import type {
  CollectStartResult,
  CollectStatus,
  Health,
  IpoDetail,
  IpoSummary,
  ListParams,
  ScoringConfig,
} from '../types'
import { HttpError } from '../utils/httpError'
import { trackRequest } from '../utils/wakeWatcher'

const BASE = '/api'

// Render 무료 플랜 콜드스타트(기동 30초+) 여유를 포함.
const PER_ATTEMPT_TIMEOUT_MS = 65_000

// Netlify 외부 프록시가 ~26초만 기다리고 502/503/504 를 돌려줄 수 있어
// GET 은 자동 재시도 (3초 간격, 총 90초 budget).
const GET_RETRY_BUDGET_MS = 90_000
const GET_RETRY_BACKOFF_MS = 3_000
const RETRYABLE_STATUSES = new Set([502, 503, 504])

const delay = (ms: number) => new Promise<void>(r => setTimeout(r, ms))

async function readDetail(res: Response): Promise<string | undefined> {
  try {
    const body = await res.json() as { detail?: string }
    return body?.detail
  } catch {
    return undefined
  }
}

async function doFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), PER_ATTEMPT_TIMEOUT_MS)
  const req = fetch(`${BASE}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...(init.headers ?? {}) },
    signal: controller.signal,
  })
  try {
    return await trackRequest(req)
  } finally {
    clearTimeout(timer)
  }
}

// GET 요청용 — 502/503/504 또는 네트워크 오류를 90초 budget 안에서 자동 재시도.
async function getJson<T>(path: string): Promise<T> {
  const start = Date.now()
  for (;;) {
    const remaining = GET_RETRY_BUDGET_MS - (Date.now() - start)
    try {
      const res = await doFetch(path)
      if (res.ok) return res.json() as Promise<T>
      if (RETRYABLE_STATUSES.has(res.status) && remaining > GET_RETRY_BACKOFF_MS) {
        await delay(GET_RETRY_BACKOFF_MS)
        continue
      }
      const detail = await readDetail(res)
      throw new HttpError(res.status, detail ?? `HTTP ${res.status} ${res.statusText}`)
    } catch (e) {
      if (e instanceof HttpError) throw e
      // 네트워크 오류 / AbortError — 재시도 budget 안이면 다시 시도.
      if (remaining > GET_RETRY_BACKOFF_MS) {
        await delay(GET_RETRY_BACKOFF_MS)
        continue
      }
      throw e
    }
  }
}

function qs(params: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

export async function listIpos(params: ListParams = {}): Promise<{ items: IpoSummary[] }> {
  return getJson(`/ipos${qs({ ...params })}`)
}

export async function getIpo(id: string, shares = 10): Promise<IpoDetail> {
  return getJson(`/ipos/${encodeURIComponent(id)}${qs({ shares })}`)
}

export async function getScoringConfig(): Promise<ScoringConfig> {
  return getJson(`/scoring-config`)
}

export async function getHealth(): Promise<Health> {
  return getJson(`/health`)
}

export async function getCollectStatus(): Promise<CollectStatus> {
  return getJson(`/collect/status`)
}

// POST 는 자동 재시도 금지(중복 실행 방지). 502/503/504 는 그대로 던지고
// 호출부(CollectBar)가 getCollectStatus 로 실제 시작 여부를 확인한다.
export async function postCollect(key: string | null): Promise<CollectStartResult> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (key) headers['X-Collect-Key'] = key
  const res = await doFetch(`/collect`, { method: 'POST', headers })
  if (res.status === 202) {
    return { kind: 'STARTED', data: (await res.json()) as CollectStatus }
  }
  if (res.status === 409) {
    const body = await res.json().catch(() => ({})) as Record<string, unknown>
    if (typeof body.detail === 'string' && !('status' in body)) {
      return { kind: 'BLOCKED', detail: body.detail }
    }
    return { kind: 'RUNNING', data: body as unknown as CollectStatus }
  }
  const detail = await readDetail(res)
  throw new HttpError(
    res.status,
    detail ?? (res.status === 401 ? '수집 키가 올바르지 않습니다.' : `HTTP ${res.status} ${res.statusText}`),
  )
}
