import React, { useEffect, useMemo, useState } from 'react'
import { Loader2, ShieldAlert } from 'lucide-react'
import { t } from '../../i18n'
import type { ChatFallbackCapabilityState, ModelsData } from '../../types'
import { Field, Dropdown, TextInput, Toggle, Modal, Btn, type DropdownOption } from './primitives'
import { resolveModels, providerLabel } from './modelsHelpers'

// 备份聊天模型。与其他功能不同，此功能是选择性加入的，并且
// 很少被触及，所以它没有自己的顶级卡：它生活在
// 主模型卡上的小按钮（请参阅 ChatFallbackButton）并进行编辑
// 在模态中。它会一直闲置，直到主模型永久无法转动为止，所以
// 整个表单被“启用”开关控制并验证提供者+
// 一起模型——不完整的条目决不允许劫持健康的条目
// 设置。

export interface ChatFallbackSavePayload {
  providerId: string
  model: string
  enabled: boolean
  maxSwitches: number
}

export interface ChatFallbackButtonProps {
  state: ChatFallbackCapabilityState | undefined
  data: ModelsData | null
  busy?: boolean
  status?: string
  onSave: (payload: ChatFallbackSavePayload) => void
}

// 主模型卡头上的小入口点：一个屏蔽按钮，
// 打开模式，并在启用回退时加上一个微妙的徽章，以便
// 主动回退一目了然。
export const ChatFallbackButton: React.FC<ChatFallbackButtonProps> = ({ state, data, busy, status, onSave }) => {
  const [open, setOpen] = useState(false)

  // 也反映状态的单个入口点：强调色+“on”标签
  // 启用回退时，静音 + 关闭时“配置”标签。
  const on = !!state?.enabled
  return (
    <>
      <button
        type="button"
        title={t('models_chat_fallback_button_tip')}
        onClick={() => setOpen(true)}
        className={
          'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-btn text-xs cursor-pointer transition-colors ' +
          (on
            ? 'text-accent bg-accent-soft hover:bg-accent-soft/70'
            : 'text-content-tertiary hover:text-accent hover:bg-accent-soft/60')
        }
      >
        <ShieldAlert size={12} />
        {on ? t('models_chat_fallback_badge_on') : t('models_chat_fallback_button')}
      </button>
      <ChatFallbackModal
        open={open}
        state={state}
        data={data}
        busy={busy}
        status={status}
        onClose={() => setOpen(false)}
        onSave={onSave}
      />
    </>
  )
}

interface ChatFallbackModalProps extends ChatFallbackButtonProps {
  open: boolean
  onClose: () => void
}

const ChatFallbackModal: React.FC<ChatFallbackModalProps> = ({
  open,
  state,
  data,
  busy,
  status,
  onClose,
  onSave,
}) => {
  const [enabled, setEnabled] = useState(!!state?.enabled)
  const [provider, setProvider] = useState(state?.current_provider || '')
  const [model, setModel] = useState(state?.current_model || '')
  const [customModel, setCustomModel] = useState(
    (state?.current_provider || '').startsWith('custom:') ? state?.current_model || '' : ''
  )
  const [showCustom, setShowCustom] = useState(false)

  // 每次（重新）打开模式时将表单重置为持久状态，以便
  // 取消的编辑永远不会泄漏到下一次打开中。
  useEffect(() => {
    if (!open) return
    setEnabled(!!state?.enabled)
    setProvider(state?.current_provider || '')
    setModel(state?.current_model || '')
    setCustomModel((state?.current_provider || '').startsWith('custom:') ? state?.current_model || '' : '')
    setShowCustom(false)
  }, [open, state])

  const isCustomProvider = provider.startsWith('custom:')

  const isConfigured = (id: string): boolean => {
    const p = data?.providers?.find((x) => x.id === id)
    if (!p) return true
    return p.configured || (p.is_custom && !!p.custom_name)
  }

  const providerOptions: DropdownOption[] = useMemo(() => {
    const opts = (state?.providers || [])
      .filter((id) => isConfigured(id) || id === provider)
      .map((id) => ({ value: id, label: providerLabel(data, id) }))
    return [{ value: '', label: t('models_select_provider') }, ...opts]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state?.providers, data, provider])

  const modelOptions: DropdownOption[] = useMemo(() => {
    const list = resolveModels(data, provider, state?.provider_models).map((o) => ({
      value: o.value,
      label: o.value,
      hint: o.hint,
    }))
    if (model && !showCustom && !list.some((o) => o.value === model)) {
      list.unshift({ value: model, label: model, hint: undefined })
    }
    return list
  }, [data, state?.provider_models, provider, model, showCustom])

  const handleProvider = (id: string) => {
    setProvider(id)
    setShowCustom(false)
    if (id.startsWith('custom:')) {
      setCustomModel(id === state?.current_provider ? state?.current_model || '' : '')
      setModel('')
      return
    }
    setCustomModel('')
    setModel(resolveModels(data, id, state?.provider_models)[0]?.value || '')
  }

  const finalModel = showCustom || isCustomProvider ? customModel.trim() : model
  // 启用是要么全有，要么全无；后端也拒绝半填的条目。
  const incomplete = enabled && (!provider || !finalModel)

  return (
    <Modal
      open={open}
      title={t('models_cap_chat_fallback')}
      onClose={onClose}
      footer={
        <>
          <span className={`text-xs text-accent mr-auto transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>
            {status}
          </span>
          <Btn variant="ghost" onClick={onClose}>
            {t('config_cancel')}
          </Btn>
          <Btn
            variant="primary"
            disabled={busy || incomplete}
            onClick={() =>
              onSave({
                providerId: provider,
                model: finalModel,
                enabled,
                // 回退在整个运行过程中都是粘性的，因此只需一次切换
                // 就足够了；无需面向用户的旋钮。
                maxSwitches: 1,
              })
            }
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : t('config_save')}
          </Btn>
        </>
      }
    >
      <p className="text-xs text-content-tertiary -mt-1">{t('models_cap_chat_fallback_sub')}</p>

      {/* 标签在左侧，开关与右侧齐平。 */}
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-content-secondary">{t('models_chat_fallback_enable')}</span>
        <Toggle checked={enabled} onChange={setEnabled} />
      </div>

      {enabled && (
        <>
          <Field label={t('models_provider')}>
            <Dropdown
              value={provider}
              options={providerOptions}
              placeholder={t('models_select_provider')}
              onChange={handleProvider}
            />
            {!!provider && !isConfigured(provider) && (
              <p className="text-xs text-danger mt-1.5">{t('config_provider_unconfigured_hint')}</p>
            )}
          </Field>

          <Field label={t('models_model')}>
            {isCustomProvider ? (
              <TextInput
                className="font-mono"
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                placeholder={t('config_custom_model_hint')}
              />
            ) : (
              <Dropdown
                value={model}
                options={modelOptions}
                placeholder={t('models_select_model')}
                onChange={setModel}
                disabled={!provider}
              />
            )}
          </Field>

          {incomplete && <p className="text-xs text-danger">{t('models_chat_fallback_incomplete')}</p>}
        </>
      )}
    </Modal>
  )
}

export default ChatFallbackButton
