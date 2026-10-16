import { USE_MOCK } from '../config'
import * as mock from './mock'
import * as real from './real'

export const api = USE_MOCK ? mock : real
export type Api = typeof real
