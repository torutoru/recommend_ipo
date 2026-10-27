// API 레이어 lazy 로더.
//
// `import * as mock` 식의 정적 import 는 운영 번들에도 목업 데이터·로직을 함께
// 넣어 버린다. 여기서는 USE_MOCK 분기를 동적 import 로 감싸 **운영 메인 번들에
// 목업이 포함되지 않도록** 한다 (Vite 가 ./mock, ./real 을 별도 chunk 로 분리).
//
// 호출부는 지금과 동일하게 `await api.listIpos(...)` 로 사용한다.

import { USE_MOCK } from '../config'
import type * as RealApi from './real'

type Api = typeof RealApi

let cached: Api | null = null
let loading: Promise<Api> | null = null

function load(): Promise<Api> {
  if (cached) return Promise.resolve(cached)
  if (loading) return loading
  const picked = USE_MOCK ? import('./mock') : import('./real')
  loading = picked.then(mod => {
    cached = mod as unknown as Api
    loading = null
    return cached
  })
  return loading
}

export const api = {
  async listIpos(params?: Parameters<Api['listIpos']>[0]) {
    return (await load()).listIpos(params)
  },
  async getIpo(id: string) {
    return (await load()).getIpo(id)
  },
  async getScoringConfig() {
    return (await load()).getScoringConfig()
  },
  async getHealth() {
    return (await load()).getHealth()
  },
  async getCollectStatus() {
    return (await load()).getCollectStatus()
  },
  async postCollect(key: string | null) {
    return (await load()).postCollect(key)
  },
  // v1.7 (#31): 「내 공모주」 — getHoldings/putHolding/deleteHolding.
  async getHoldings() {
    return (await load()).getHoldings()
  },
  async putHolding(corpCode: string, body: { shares: number; price: number; memo: string }) {
    return (await load()).putHolding(corpCode, body)
  },
  async deleteHolding(corpCode: string) {
    return (await load()).deleteHolding(corpCode)
  },
}
