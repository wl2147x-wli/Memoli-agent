import React, { useEffect, useMemo, useState } from 'react'
import { Sparkles, KeyRound, Loader2, ArrowRight, ArrowLeft, ExternalLink } from 'lucide-react'
import { t, getLang, setLang, type Lang } from '../i18n'
import apiClient from '../api/client'
import type { ModelsData } from '../types'
import { Field, Dropdown, TextInput, type DropdownOption } from '../pages/settings/primitives'
import { resolveModels, providerLabel } from '../pages/settings/modelsHelpers'
import { useOnboardingStore } from '../store/onboardingStore'

interface OnboardingWizardProps {
  // 向导完成后调用，以便主持人可以刷新语言/状态。
  onDone: () => void
}

const TOTAL_STEPS = 2

// 每个提供商可选的“从哪里获取 API 密钥”控制台链接。
const PROVIDER_KEY_CONSOLE: Record<string, string> = {
  linkai: 'https://link-ai.tech/console/interface',
}

// 首次运行引导设置：语言 -> 聊天模型（提供商 + 密钥 + 模型）。
// 保存模型后，用户直接进入聊天（没有额外的
// 确认步骤）。渲染为主 UI 上方的全屏覆盖；
// 重用与设置页面相同的模型 API 和原语。
const OnboardingWizard: React.FC<OnboardingWizardProps> = ({ onDone }) => {
  const finish = useOnboardingStore((s) => s.finish)

  const [step, setStep] = useState(1)
  const [lang, setLangState] = useState<Lang>(getLang())
  const [models, setModels] = useState<ModelsData | null>(null)

  // 步骤2 形成状态。
  const [provider, setProvider] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [model, setModel] = useState('')

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // 为提供者/模型下拉列表加载模型控制台数据一次。
  useEffect(() => {
    apiClient
      .getModels()
      .then(setModels)
      .catch(() => setError(t('onboarding_save_failed')))
  }, [])

  // 在首次显示时保留自动检测到的默认语言，以便预先选择
  // 选项（由操作系统区域设置驱动）也会到达后端，即使用户
  // 不点击语言按钮。
  useEffect(() => {
    if (!localStorage.getItem('cow_lang')) switchLang(lang)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const providerOptions: DropdownOption[] = useMemo(() => {
    const chat = models?.capabilities?.chat
    const ids = chat?.providers || []
    return ids.map((id) => ({ value: id, label: providerLabel(models, id) }))
  }, [models])

  const modelOptions: DropdownOption[] = useMemo(() => {
    return resolveModels(models, provider, models?.capabilities?.chat?.provider_models).map((o) => ({
      value: o.value,
      label: o.value,
      hint: o.hint,
    }))
  }, [models, provider])

  // 当前所选提供商的 api_base 占位符/默认值（如果有）。
  const providerMeta = models?.providers?.find((p) => p.id === provider)
  const apiBasePlaceholder = providerMeta?.api_base_placeholder || providerMeta?.api_base_default

  const handleProvider = (id: string) => {
    setProvider(id)
    setApiBase('')
    const first = resolveModels(models, id, models?.capabilities?.chat?.provider_models)[0]
    setModel(first?.value || '')
  }

  const switchLang = (next: Lang) => {
    setLang(next)
    setLangState(next)
    // 将选择镜像到后端，以便代理/日志使用相同的语言
    // （匹配基本设置）。非阻塞：UI已经在本地切换。
    apiClient.updateConfig({ cow_lang: next }).catch(() => {})
  }

  // 第1步（语言）可以一直前进；第 2 步需要提供者、密钥、模型。
  const canNext = step === 1 || (!!provider && !!apiKey.trim() && !!model)

  const goNext = async () => {
    setError('')
    // 第 1 步（语言）仅前进到模型步骤。
    if (step === 1) {
      setStep(2)
      return
    }
    // 第 2 步是最后一步：保留提供者凭据，点聊天
    // 能力，然后直接进入聊天（无需额外步骤）。
    setSaving(true)
    try {
      await apiClient.modelsAction({
        action: 'set_provider',
        provider_id: provider,
        api_key: apiKey.trim(),
        ...(apiBase.trim() ? { api_base: apiBase.trim() } : {}),
      })
      await apiClient.modelsAction({
        action: 'set_capability',
        capability: 'chat',
        provider_id: provider,
        model,
      })
    } catch {
      setSaving(false)
      setError(t('onboarding_save_failed'))
      return
    }
    setSaving(false)
    complete()
  }

  const goBack = () => {
    setError('')
    setStep((s) => Math.max(1, s - 1))
  }

  const complete = () => {
    finish()
    onDone()
  }

  const stepLabel = t('onboarding_step').replace('{n}', String(step)).replace('{total}', String(TOTAL_STEPS))

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-base">
      <div className="w-full max-w-lg px-8">
        {/* 进度点 */}
        <div className="flex items-center justify-center gap-2 mb-8">
          {Array.from({ length: TOTAL_STEPS }).map((_, i) => (
            <span
              key={i}
              className={`h-1.5 rounded-full transition-all ${
                i + 1 === step ? 'w-8 bg-accent' : i + 1 < step ? 'w-4 bg-accent/50' : 'w-4 bg-surface-2'
              }`}
            />
          ))}
        </div>

        {step === 1 && (
          <div className="text-center space-y-6">
            <div className="w-16 h-16 rounded-2xl bg-accent-soft text-accent flex items-center justify-center mx-auto">
              <Sparkles size={30} />
            </div>
            <div className="space-y-2">
              <h1 className="text-2xl font-bold text-content">{t('onboarding_welcome_title')}</h1>
              <p className="text-sm text-content-secondary">{t('onboarding_welcome_desc')}</p>
            </div>
            <div className="max-w-xs mx-auto text-left">
              <Field label={t('onboarding_lang_label')}>
                <div className="grid grid-cols-2 gap-2">
                  {(['zh', 'en'] as Lang[]).map((l) => (
                    <button
                      key={l}
                      onClick={() => switchLang(l)}
                      className={`px-4 py-2.5 rounded-btn border text-sm font-medium cursor-pointer transition-colors ${
                        lang === l
                          ? 'border-accent bg-accent-soft text-accent'
                          : 'border-strong text-content-secondary hover:bg-surface-2'
                      }`}
                    >
                      {l === 'zh' ? '简体中文' : 'English'}
                    </button>
                  ))}
                </div>
              </Field>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-6">
            <div className="text-center space-y-2">
              <div className="w-16 h-16 rounded-2xl bg-accent-soft text-accent flex items-center justify-center mx-auto">
                <KeyRound size={28} />
              </div>
              <h1 className="text-2xl font-bold text-content">{t('onboarding_model_title')}</h1>
              <p className="text-sm text-content-secondary">{t('onboarding_model_desc')}</p>
            </div>
            <div className="space-y-4">
              <Field label={t('onboarding_provider')}>
                <Dropdown
                  value={provider}
                  options={providerOptions}
                  placeholder={t('onboarding_select_provider')}
                  onChange={handleProvider}
                />
              </Field>
              {provider && (
                <>
                  <Field label={t('onboarding_apikey')}>
                    <TextInput
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={t('onboarding_apikey_placeholder')}
                      className="font-mono"
                    />
                    {PROVIDER_KEY_CONSOLE[provider] && (
                      <a
                        href={PROVIDER_KEY_CONSOLE[provider]}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1.5 inline-flex items-center gap-1 text-xs text-accent hover:underline"
                      >
                        {t('onboarding_key_guide')}
                        <ExternalLink size={11} />
                      </a>
                    )}
                  </Field>
                  {providerMeta?.api_base_field && (
                    <Field label={t('onboarding_apibase')}>
                      <TextInput
                        value={apiBase}
                        onChange={(e) => setApiBase(e.target.value)}
                        placeholder={apiBasePlaceholder || ''}
                        className="font-mono"
                      />
                    </Field>
                  )}
                  <Field label={t('onboarding_model')}>
                    <Dropdown
                      value={model}
                      options={modelOptions}
                      placeholder={t('onboarding_select_model')}
                      onChange={setModel}
                    />
                  </Field>
                </>
              )}
              {error && <p className="text-sm text-danger">{error}</p>}
            </div>
          </div>
        )}

        {/* 页脚控件 */}
        <div className="mt-10 flex items-center justify-between">
          <div className="text-xs text-content-tertiary">{stepLabel}</div>
          <div className="flex items-center gap-2">
            {/* 第二步：回到语言。 */}
            {step === 2 && (
              <button
                onClick={goBack}
                disabled={saving}
                className="px-4 py-2 rounded-btn border border-strong text-content-secondary hover:bg-surface-2 text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                <ArrowLeft size={15} />
                {t('onboarding_back')}
              </button>
            )}
            {/* 每一步都可以跳过：忽略并直接进入聊天。 */}
            <button
              onClick={complete}
              disabled={saving}
              className="px-4 py-2 rounded-btn text-sm font-medium text-content-tertiary hover:text-content cursor-pointer transition-colors disabled:opacity-50"
            >
              {t('onboarding_skip')}
            </button>
            {/* 主要操作：前进第 1 步，保存 + 完成最后一步。 */}
            <button
              onClick={goNext}
              disabled={!canNext || saving}
              className="px-5 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
            >
              {saving && <Loader2 size={15} className="animate-spin" />}
              {saving
                ? t('onboarding_saving')
                : step === TOTAL_STEPS
                  ? t('onboarding_finish')
                  : t('onboarding_next')}
              {!saving && <ArrowRight size={15} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default OnboardingWizard
