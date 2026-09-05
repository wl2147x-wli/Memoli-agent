import React, { useMemo, useState, useRef } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Loader2 } from 'lucide-react'
import { t } from '../../i18n'
import type { CapabilityState, ModelsData } from '../../types'
import { Card, Field, Dropdown, TextInput, type DropdownOption } from './primitives'
import { resolveModels, providerLabel, CUSTOM_OPTION } from './modelsHelpers'

// 聊天/视觉/asr/嵌入/图像使用的通用提供商+模型能力卡。
// tts（语音）和搜索有定制卡。

export interface CapabilityCardProps {
  icon: LucideIcon
  title: string
  subtitle?: string
  capKey: string
  state: CapabilityState
  data: ModelsData | null
  // 是否允许选择“无提供商”（自动/禁用）
  allowAuto?: boolean
  autoLabel?: string
  // 是否允许自由格式的自定义模型条目
  allowCustomModel?: boolean
  busy?: boolean
  status?: string
  onSave: (providerId: string, model: string) => void
  children?: React.ReactNode
  // 卡标题上的可选尾随元素（例如聊天后备齿轮）。
  action?: React.ReactNode
}

const CapabilityCard: React.FC<CapabilityCardProps> = ({
  icon: Icon,
  title,
  subtitle,
  state,
  data,
  allowAuto,
  autoLabel,
  allowCustomModel,
  busy,
  status,
  onSave,
  children,
  action,
}) => {
  const [provider, setProvider] = useState(state.current_provider || '')
  const [model, setModel] = useState(state.current_model || '')
  // 自定义提供程序将模型呈现为自由格式输入；播种它与
  // 已保存模型，因此加载时它不是空白（仅占位符）。
  const [customModel, setCustomModel] = useState(
    (state.current_provider || '').startsWith('custom:') ? state.current_model || '' : ''
  )
  const [showCustom, setShowCustom] = useState(false)
  // 记住每个提供商输入的自定义模型，以便切换供应商和
  // 回来不会失去它。由提供商 ID 键入。
  const customModelByProvider = useRef<Record<string, string>>({})

  // 自定义提供程序不公开预设的模型目录，因此模型必须始终
  // 可以自由输入，而不是从（空）下拉列表中选择。
  const isCustomProvider = provider.startsWith('custom:')

  // 提供程序在具有凭据时进行配置（自定义提供程序计数
  // 仅当它实际携带名称/密钥时，而不是作为空占位符）。
  const isConfigured = (id: string): boolean => {
    const p = data?.providers?.find((x) => x.id === id)
    if (!p) return true
    return p.configured || (p.is_custom && !!p.custom_name)
  }

  // 仅实际配置的表面提供程序（内置或自定义）。
  // 未配置的供应商没有可用的凭据，因此将其列出 - 并且
  // 将其标记为“未配置”——只会增加噪音。当前选择的
  // 提供者始终被保留，因此保存的值永远不会悄无声息地消失。
  const providerOptions: DropdownOption[] = useMemo(() => {
    const opts = (state.providers || [])
      .filter((id) => isConfigured(id) || id === provider)
      .map((id) => ({ value: id, label: providerLabel(data, id) }))
    if (allowAuto) return [{ value: '', label: autoLabel || t('models_auto') }, ...opts]
    return opts
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.providers, data, allowAuto, autoLabel, provider])

  const currentUnconfigured = !!provider && !isConfigured(provider)

  const modelOptions: DropdownOption[] = useMemo(() => {
    const list = resolveModels(data, provider, state.provider_models).map((o) => ({
      value: o.value,
      label: o.value,
      hint: o.hint,
    }))
    // 即使当前保存的模型不在预设列表中，也请使其保持可选状态。
    if (model && !showCustom && !list.some((o) => o.value === model)) {
      list.unshift({ value: model, label: model, hint: undefined })
    }
    if (allowCustomModel) list.push({ value: CUSTOM_OPTION, label: t('config_custom_option'), hint: undefined })
    return list
  }, [data, state.provider_models, provider, allowCustomModel, model, showCustom])

  const handleProvider = (id: string) => {
    // 将输入的自定义模型存储在我们要离开的提供程序下。
    if (showCustom || isCustomProvider) {
      const typed = customModel.trim()
      if (typed) customModelByProvider.current[provider] = typed
    }
    setProvider(id)
    setShowCustom(false)
    const remembered = customModelByProvider.current[id]
    if (id.startsWith('custom:')) {
      // 预填充记住的值，否则保存的模型
      // 重新选择同一提供商。
      const saved = id === state.current_provider ? state.current_model || '' : ''
      setCustomModel(remembered || saved)
      setModel('')
      return
    }
    if (remembered) {
      // 预设提供程序的记住自定义模型：重新打开自定义输入。
      setShowCustom(true)
      setCustomModel(remembered)
      setModel('')
      return
    }
    setCustomModel('')
    const first = resolveModels(data, id, state.provider_models)[0]
    setModel(first?.value || '')
  }

  const handleModel = (val: string) => {
    if (val === CUSTOM_OPTION) {
      setShowCustom(true)
      setModel('')
      // 恢复之前为此提供程序键入的任何自定义模型。
      const remembered = customModelByProvider.current[provider]
      if (remembered) setCustomModel(remembered)
    } else {
      setShowCustom(false)
      setModel(val)
      setCustomModel('')
    }
  }

  // 当用户输入自定义模型时，保持每个提供者的内存同步。
  const handleCustomModelInput = (val: string) => {
    setCustomModel(val)
    const trimmed = val.trim()
    if (trimmed) customModelByProvider.current[provider] = trimmed
    else delete customModelByProvider.current[provider]
  }

  const finalModel = showCustom || isCustomProvider ? customModel.trim() : model
  const isAuto = allowAuto && !provider

  return (
    <Card icon={<Icon size={16} />} title={title} subtitle={subtitle} action={action}>
      <div className="space-y-4">
        <Field label={t('models_provider')}>
          <Dropdown
            value={provider}
            options={providerOptions}
            placeholder={t('models_select_provider')}
            onChange={handleProvider}
          />
          {/* 提供商的 API 密钥在上面的供应商卡中配置
              同样的选项卡，因此警告而不是链接到其他地方。 */}
          {currentUnconfigured && (
            <p className="text-xs text-danger mt-1.5">{t('config_provider_unconfigured_hint')}</p>
          )}
        </Field>
        {!isAuto && (
          <Field label={t('models_model')}>
            {isCustomProvider ? (
              // 自定义提供程序没有预设目录：直接键入模型。
              <TextInput
                className="font-mono"
                value={customModel}
                onChange={(e) => handleCustomModelInput(e.target.value)}
                placeholder={t('config_custom_model_hint')}
              />
            ) : (
              <>
                <Dropdown
                  value={showCustom ? CUSTOM_OPTION : model}
                  options={modelOptions}
                  placeholder={t('models_select_model')}
                  onChange={handleModel}
                />
                {showCustom && (
                  <TextInput
                    className="mt-2 font-mono"
                    value={customModel}
                    onChange={(e) => handleCustomModelInput(e.target.value)}
                    placeholder={t('config_custom_model_hint')}
                  />
                )}
              </>
            )}
          </Field>
        )}
        {children}
        <div className="flex items-center justify-end gap-3 pt-1">
          <span className={`text-xs text-accent transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>
            {status}
          </span>
          <button
            disabled={busy}
            onClick={() => onSave(provider, finalModel)}
            className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 inline-flex items-center gap-2"
          >
            {busy && <Loader2 size={14} className="animate-spin" />}
            {t('config_save')}
          </button>
        </div>
      </div>
    </Card>
  )
}

export default CapabilityCard
