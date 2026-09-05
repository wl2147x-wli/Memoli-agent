import type { ModelEntry, ModelOption, ModelProvider, ModelsData } from '../../types'
import { localizedLabel } from '../../i18n'

// 将字符串|{value,hint}条目标准化为统一的选项形状。
export function normEntry(e: ModelEntry): ModelOption {
  return typeof e === 'string' ? { value: e } : e
}

export function normEntries(arr?: ModelEntry[]): ModelOption[] {
  return (arr || []).map(normEntry)
}

// 解析提供者 ID 的人工标签，回退到 ID 本身。
// 通过提供者概述处理扩展的自定义 ID（“自定义：<id>”）。
export function providerLabel(data: ModelsData | null, id: string): string {
  if (!id) return ''
  const p = data?.providers?.find((x) => x.id === id)
  if (p) return localizedLabel(p.label) || id
  return id
}

export function findProvider(data: ModelsData | null, id: string): ModelProvider | undefined {
  return data?.providers?.find((x) => x.id === id)
}

// 解析功能+提供者的模型列表，镜像 Web 控制台：
//   1. 能力范围的provider_models[id] (vision/image/asr/tts/embedding)
//   2.provider_models['custom'] 用于扩展自定义：<id> 提供商
//   3.回退到供应商的通用模型[]（聊天没有provider_models）
export function resolveModels(
  data: ModelsData | null,
  providerId: string,
  providerModels?: Record<string, ModelEntry[]>
): ModelOption[] {
  if (!providerId) return []
  if (providerModels?.[providerId]) return normEntries(providerModels[providerId])
  if (providerId.startsWith('custom:') && providerModels?.['custom']) {
    return normEntries(providerModels['custom'])
  }
  return normEntries(findProvider(data, providerId)?.models)
}

// tts 提供商的声音可能是一个平面列表，或者对于 linkai，则按模型键入。
export function resolveVoices(
  provider: string,
  model: string,
  voicesMap?: Record<string, ModelEntry[] | Record<string, ModelEntry[]>>
): ModelOption[] {
  const raw = voicesMap?.[provider]
  if (!raw) return []
  if (Array.isArray(raw)) return normEntries(raw)
  // 按模型键入（linkai）
  const byModel = raw as Record<string, ModelEntry[]>
  return normEntries(byModel[model] || [])
}

export const CUSTOM_OPTION = '__custom__'
