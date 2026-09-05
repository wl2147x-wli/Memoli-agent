import React, { useState, useEffect, useRef } from 'react'
import { Cpu, Bot, ShieldCheck, Settings, Eye, EyeOff, ArrowRight, Loader2 } from 'lucide-react'
import { t, getLang, setLang, localizedLabel, type Lang } from '../../i18n'
import apiClient from '../../api/client'
import { product } from '@product'
import type { ConfigData, ProviderMeta } from '../../types'
import { useUIStore } from '../../store/uiStore'
import { useSessionStore } from '../../store/sessionStore'
import { useSessionSettingsStore } from '../../store/sessionSettingsStore'
import { Card, Field, Dropdown, Toggle, TextInput, SaveRow, MASK_RE } from './primitives'
import { PERMISSION_META, PERMISSION_MODE_ORDER, asPermissionMode } from '../../lib/permission'

const CustomModelPicker = product.models?.ModelPicker
const hideProviderSelect = product.models?.hideProviderSelect === true
const showManagedApiKey = product.models?.showManagedApiKey === true
const ModelFieldLink = product.models?.ModelFieldLink
const ApiKeyFieldLink = product.models?.ApiKeyFieldLink

interface BasicSettingsProps {
  baseUrl: string
  onLangChange?: () => void
  onOpenModels?: () => void
}

const BasicSettings: React.FC<BasicSettingsProps> = ({ baseUrl, onLangChange, onOpenModels }) => {
  const [config, setConfig] = useState<ConfigData | null>(null)
  const [loading, setLoading] = useState(true)

  // 通知卡（客户端首选项，立即应用）
  const taskNotify = useUIStore((s) => s.taskNotify)
  const taskNotifySound = useUIStore((s) => s.taskNotifySound)
  const setTaskNotify = useUIStore((s) => s.setTaskNotify)
  const setTaskNotifySound = useUIStore((s) => s.setTaskNotifySound)

  // 登录时启动（仅限 macOS + Windows）。状态存在于操作系统注册表中，因此
  // 从主进程中读取它，而不是我们自己保存它。
  const platform = window.electronAPI?.platform
  const supportsLaunchAtLogin =
    !!window.electronAPI?.setLoginItemEnabled && (platform === 'darwin' || platform === 'win32')
  const [launchAtLogin, setLaunchAtLogin] = useState(false)
  const [launchAtLoginError, setLaunchAtLoginError] = useState('')

  useEffect(() => {
    if (!supportsLaunchAtLogin) return
    window.electronAPI?.getLoginItemEnabled?.().then((v) => setLaunchAtLogin(!!v)).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supportsLaunchAtLogin])

  const toggleLaunchAtLogin = async (v: boolean) => {
    setLaunchAtLogin(v)
    setLaunchAtLoginError('')
    try {
      const res = await window.electronAPI?.setLoginItemEnabled?.(v)
      if (!res) return
      // 反映操作系统实际做了什么——永远不要默默地假装它有效。
      setLaunchAtLogin(res.enabled)
      if (!res.ok) {
        setLaunchAtLoginError(
          res.error
            ? `${t('config_launch_at_login_error')}: ${res.error}`
            : t('config_launch_at_login_refused')
        )
      }
    } catch (e) {
      // IPC 本身失败了：恢复并显示它而不是吞掉它。
      setLaunchAtLogin(!v)
      const msg = e instanceof Error ? e.message : String(e)
      setLaunchAtLoginError(`${t('config_launch_at_login_error')}: ${msg}`)
    }
  }

  // 模型卡 - 凭证（密钥/基础）现在位于“模型”选项卡中
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [modelStatus, setModelStatus] = useState('')
  // 记住每个提供商输入的自定义模型，以便切换供应商和
  // 回来不会失去它。由提供商 ID 键入。
  const customModelByProvider = useRef<Record<string, string>>({})

  // 托管 API 密钥（仅在隐藏独立模型选项卡时显示）
  const [apiKey, setApiKey] = useState('')
  const [apiKeyDirty, setApiKeyDirty] = useState(false)
  const [apiKeyVisible, setApiKeyVisible] = useState(false)

  // 代理卡
  const [maxTokens, setMaxTokens] = useState(100000)
  const [maxTurns, setMaxTurns] = useState(20)
  const [maxSteps, setMaxSteps] = useState(20)
  const [thinking, setThinking] = useState(false)
  const [reasoningEffort, setReasoningEffort] = useState('high')
  const [subagent, setSubagent] = useState(true)
  const [evolution, setEvolution] = useState(false)
  const [agentStatus, setAgentStatus] = useState('')

  // 安全卡
  const [password, setPassword] = useState('')
  const [pwDirty, setPwDirty] = useState(false)
  const [pwVisible, setPwVisible] = useState(false)
  const [pwStatus, setPwStatus] = useState('')
  const [permissionMode, setPermissionMode] = useState('full-access')
  const [permStatus, setPermStatus] = useState('')

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    loadConfig()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  const providerMeta = (id: string): ProviderMeta | undefined => config?.providers?.[id] as ProviderMeta | undefined

  // 自定义提供程序（自定义：<id> 或旧版“自定义”）没有预设模型
  // 目录，因此他们的模型总是被输入到自由格式的输入中。
  const isCustomProviderId = (id: string) => id.startsWith('custom:') || id === 'custom'

  // 与后端解析路径共享的规范每模型密钥：小写
  // 模型，因此无论用户如何输入模型名称，密钥都是稳定的。
  const currentModelKey = () => {
    const m = (
      CustomModelPicker
        ? model
        : isCustomProviderId(provider) || showCustom
          ? customModel.trim()
          : model
    )
      .trim()
      .toLowerCase()
    return m ? `${provider}:${m}` : ''
  }

  const currentSavedEffort = () => config?.reasoning_effort_by_model?.[currentModelKey()] ?? config?.reasoning_effort

  // 当活动提供者/模型发生变化时，显示该模型自己保存的
  // 努力，而不是让以前模型的价值可见。
  useEffect(() => {
    if (!config) return
    const saved = currentSavedEffort()
    setReasoningEffort(saved || 'high')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, model, showCustom, customModel, config])

  const loadConfig = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getConfig()
      setConfig(data)
      setModel(data.model || '')
      setMaxTokens(data.agent_max_context_tokens ?? 100000)
      setMaxTurns(data.agent_max_context_turns ?? 20)
      setMaxSteps(data.agent_max_steps ?? 20)
      setThinking(!!data.enable_thinking)
      setReasoningEffort(data.reasoning_effort || 'high')
      setSubagent(data.subagent_enabled !== false)
      setEvolution(!!data.self_evolution_enabled)
      setPermissionMode(asPermissionMode(data.agent_permission_mode))
      // 首选真实密码（仅限桌面），以便可以就地编辑；
      // 回退到浏览器访问的屏蔽值。
      setPassword(data.web_password ?? data.web_password_masked ?? '')
      setPwDirty(false)

      const ids = data.providers ? Object.keys(data.providers) : []
      const current = showManagedApiKey ? 'linkai' : data.use_linkai ? 'linkai' : data.bot_type || ids[0] || ''
      setProvider(current)
      const meta = data.providers?.[current] as ProviderMeta | undefined
      // 托管密钥：显示当前提供商密钥字段的屏蔽值。
      const keyField = meta?.api_key_field
      setApiKey((keyField && data.api_keys?.[keyField]) || '')
      setApiKeyDirty(false)
      const presets = meta?.models || []
      if (current.startsWith('custom:') || current === 'custom') {
        // 自定义提供程序始终使用自由格式模型输入；播种它
        // 保存的模型，因此加载时它不是空白的。
        setCustomModel(data.model || '')
      } else if (data.model && presets.length && !presets.includes(data.model)) {
        setShowCustom(true)
        setCustomModel(data.model)
      }
    } catch (err) {
      console.error('Failed to load config:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleProviderChange = (id: string) => {
    // 存储在我们要离开的提供程序下键入的自定义模型，以便
    // 稍后切换回它即可恢复该值。
    if (showCustom || isCustomProviderId(provider)) {
      const typed = customModel.trim()
      if (typed) customModelByProvider.current[provider] = typed
    }
    setProvider(id)
    setShowCustom(false)
    const remembered = customModelByProvider.current[id]
    if (id.startsWith('custom:') || id === 'custom') {
      // 预填充记住的值，否则提供者的默认模型（或
      // 重新选择活动提供商时保存的提供商）。
      const meta = config?.providers?.[id] as ProviderMeta | undefined
      const saved = id === config?.bot_type ? config?.model || '' : ''
      setCustomModel(remembered || saved || meta?.models?.[0] || '')
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
    if (config) {
      const meta = config.providers?.[id] as ProviderMeta | undefined
      const models = meta?.models || []
      setModel(models[0] || '')
    }
  }

  // 当用户输入自定义模型时，保持每个提供者的内存同步。
  const handleCustomModelInput = (val: string) => {
    setCustomModel(val)
    const trimmed = val.trim()
    if (trimmed) customModelByProvider.current[provider] = trimmed
    else delete customModelByProvider.current[provider]
  }

  const handleModelChange = (val: string) => {
    if (val === '__custom__') {
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

  const saveModelConfig = async () => {
    const finalModel = CustomModelPicker
      ? model
      : isCustomProviderId(provider) || showCustom
        ? customModel.trim()
        : model
    // 使用托管模型源，提供者选择器被隐藏；路线经过
    // 托管提供程序，以便凭据一致解析。
    const isLinkai = CustomModelPicker ? true : provider === 'linkai'
    try {
      await apiClient.updateConfig({
        model: finalModel,
        use_linkai: isLinkai,
        bot_type: isLinkai ? '' : provider,
      })
      setModelStatus(t('config_saved'))
      const fresh = await apiClient.getConfig()
      setConfig(fresh)
    } catch {
      setModelStatus(t('config_save_error'))
    }
    setTimeout(() => setModelStatus(''), 2000)
  }

  const currentKeyField =
    (config?.providers?.[provider] as ProviderMeta | undefined)?.api_key_field ||
    (showManagedApiKey ? 'linkai_api_key' : undefined)

  const saveApiKey = async () => {
    if (!apiKeyDirty || !currentKeyField) return
    // 切勿将屏蔽值保存回真实密钥。
    if (MASK_RE.test(apiKey)) return
    try {
      await apiClient.updateConfig({ [currentKeyField]: apiKey })
      setModelStatus(t('config_saved'))
      setApiKeyDirty(false)
      const fresh = await apiClient.getConfig()
      setConfig(fresh)
      const meta = fresh.providers?.[provider] as ProviderMeta | undefined
      const keyField = meta?.api_key_field
      setApiKey((keyField && fresh.api_keys?.[keyField]) || '')
    } catch {
      setModelStatus(t('config_save_error'))
    }
    setTimeout(() => setModelStatus(''), 2000)
  }

  const saveAgentConfig = async () => {
    const meta = config?.providers?.[provider] as ProviderMeta | undefined
    const selectedModel = CustomModelPicker
      ? model
      : isCustomProviderId(provider) || showCustom
        ? customModel.trim()
        : model
    const reasoning = meta?.reasoning_by_model?.[selectedModel] || meta?.reasoning
    const reasoningOptions = reasoning?.supported ? reasoning.options || [] : []
    const nextReasoningEffort = reasoningOptions.some((o) => o.value === reasoningEffort)
      ? reasoningEffort
      : reasoning?.default || reasoningOptions[0]?.value || reasoningEffort

    try {
      // 坚持每个模型的努力，这样更换供应商就不会重新解释一个模型
      // 值用户为不同的模型设置。与现有地图合并
      // 其他模型保存的工作不会被平面配置保存覆盖。
      const effortKey = currentModelKey()
      await apiClient.updateConfig({
        agent_max_context_tokens: maxTokens,
        agent_max_context_turns: maxTurns,
        agent_max_steps: maxSteps,
        enable_thinking: thinking,
        reasoning_effort_by_model: {
          ...(config?.reasoning_effort_by_model || {}),
          ...(effortKey ? { [effortKey]: nextReasoningEffort } : {}),
        },
        subagent_enabled: subagent,
        self_evolution_enabled: evolution,
      })
      // 刷新，以便内存中的配置携带刚刚保存的每个模型的值；
      // 否则切换模型并返回将显示/提交过时的值。
      const fresh = await apiClient.getConfig()
      setConfig(fresh)
      setAgentStatus(t('config_saved'))
    } catch {
      setAgentStatus(t('config_save_error'))
    }
    setTimeout(() => setAgentStatus(''), 2000)
  }

  // Desktop返回真实密码，因此该字段保存明文，可以
  // 直接保存（包括清除）。浏览器访问只有屏蔽的
  // 值，其中屏蔽字符串绝不能保存为真实密码。
  const hasRealPassword = config?.web_password !== undefined

  const savePassword = async () => {
    if (!pwDirty) return
    if (!hasRealPassword && MASK_RE.test(password)) return
    try {
      await apiClient.updateConfig({ web_password: password })
      setPwStatus(password ? t('config_password_saved') : t('config_password_cleared'))
      setPwDirty(false)
    } catch {
      setPwStatus(t('config_save_error'))
    }
    setTimeout(() => setPwStatus(''), 3000)
  }

  const savePermission = async (mode: string) => {
    setPermissionMode(mode)
    try {
      await apiClient.updateConfig({ agent_permission_mode: mode })
      setPermStatus(t('config_saved'))
      const sid = useSessionStore.getState().activeId
      if (sid) useSessionSettingsStore.getState().refresh(sid)
    } catch {
      setPermStatus(t('config_save_error'))
    }
    setTimeout(() => setPermStatus(''), 2000)
  }

  const changeLanguage = async (lang: Lang) => {
    setLang(lang)
    onLangChange?.()
    try {
      await apiClient.updateConfig({ cow_lang: lang })
    } catch {
      /* 非阻塞 */
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-content-tertiary">
        <Loader2 size={18} className="animate-spin mr-2" />
        {t('skills_loading')}
      </div>
    )
  }

  // 当提供者的关键字段包含值时，该提供者就被视为已配置。
  // 自定义提供程序（无关键字段）带有自己的凭据，因此请按照配置进行处理。
  const isConfigured = (id: string): boolean => {
    const meta = providerMeta(id)
    const f = meta?.api_key_field
    if (!f) return true
    return !!config?.api_keys?.[f]
  }

  // 仅列出已配置的提供程序（内置或自定义）。未配置的供应商
  // 没有可用的凭据，因此显示它们（标记为“未配置”）是
  // 只是噪音。保留当前选择，以便保存的值永远不会消失。
  const providerIds = config?.providers ? Object.keys(config.providers) : []
  const providerOptions = providerIds
    .filter((id) => isConfigured(id) || id === provider)
    .map((id) => ({
      value: id,
      label: localizedLabel(providerMeta(id)?.label) || id,
    }))
  const currentMeta = providerMeta(provider)
  const isCustomProvider = isCustomProviderId(provider)
  const selectedModel = CustomModelPicker
    ? model
    : isCustomProvider || showCustom
      ? customModel.trim()
      : model
  const reasoning = currentMeta?.reasoning_by_model?.[selectedModel] || currentMeta?.reasoning
  const reasoningOptions = reasoning?.supported ? reasoning.options || [] : []
  const reasoningValue = reasoningOptions.some((o) => o.value === reasoningEffort)
    ? reasoningEffort
    : reasoning?.default || reasoningOptions[0]?.value || ''
  // 努力只会塑造思维过程，因此领域会跟随切换。
  const showReasoningEffort = thinking && !!reasoning?.supported && reasoningOptions.length > 0
  const currentUnconfigured = !!provider && !isConfigured(provider)
  const modelOptions = [
    ...(currentMeta?.models || []).map((m) => ({ value: m, label: m })),
    { value: '__custom__', label: t('config_custom_option') },
  ]

  return (
    <div className="grid gap-5">
      {/* 型号 — 仅提供者/型号选择；凭证位于“模型”选项卡中 */}
      <Card icon={<Cpu size={16} />} title={t('config_model')}>
        <div className="space-y-4">
          {!hideProviderSelect && (
            <Field label={t('config_provider')}>
              <Dropdown value={provider} options={providerOptions} onChange={handleProviderChange} />
            </Field>
          )}
          <Field
            label={t('config_model_name')}
            labelAction={ModelFieldLink ? <ModelFieldLink /> : undefined}
          >
            {CustomModelPicker ? (
              <CustomModelPicker value={model} onChange={setModel} />
            ) : isCustomProvider ? (
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
                  value={showCustom ? '__custom__' : model}
                  options={modelOptions}
                  onChange={handleModelChange}
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

          {/* 托管 API 密钥：默认隐藏，单击眼睛即可显示
              部分屏蔽值（例如 sk-1****9aL7）。可就地编辑；如果
              保持不变（仍然包含掩码字符），它不会被覆盖。 */}
          {showManagedApiKey && currentKeyField && (
            <Field
              label={t('onboarding_apikey')}
              labelAction={ApiKeyFieldLink ? <ApiKeyFieldLink /> : undefined}
            >
              <div className="relative">
                <TextInput
                  type={apiKeyVisible ? 'text' : 'password'}
                  className="pr-10 font-mono"
                  value={apiKey}
                  placeholder="sk-..."
                  onChange={(e) => {
                    setApiKey(e.target.value.trim())
                    setApiKeyDirty(true)
                  }}
                />
                <button
                  type="button"
                  onClick={() => setApiKeyVisible((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary cursor-pointer p-1"
                >
                  {apiKeyVisible ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </Field>
          )}

          {/* 引导用户进入“模型”选项卡以获取 API 密钥/基本配置。
              当所选提供商没有凭据时，会显示警告。 */}
          {onOpenModels && (
            <button
              onClick={onOpenModels}
              className={`w-full flex items-center justify-between gap-2 rounded-btn border px-3 py-2.5 cursor-pointer transition-colors text-left ${
                currentUnconfigured
                  ? 'border-danger-border bg-danger-soft hover:border-danger'
                  : 'border-default bg-inset-2 hover:border-accent'
              }`}
            >
              <span className={`text-xs ${currentUnconfigured ? 'text-danger' : 'text-content-tertiary'}`}>
                {currentUnconfigured ? t('config_provider_unconfigured_hint') : t('config_credentials_link')}
              </span>
              <span
                className={`flex-shrink-0 inline-flex items-center gap-1 text-xs ${
                  currentUnconfigured ? 'text-danger font-medium' : 'text-accent'
                }`}
              >
                {t('config_goto_models')}
                <ArrowRight size={13} />
              </span>
            </button>
          )}

          <SaveRow
            status={modelStatus}
            onSave={async () => {
              await saveModelConfig()
              if (showManagedApiKey && apiKeyDirty) await saveApiKey()
            }}
          />
        </div>
      </Card>

      {/* 代理 */}
      <Card icon={<Bot size={16} />} title={t('config_agent')}>
        <div className="space-y-4">
          <Field label={t('config_max_tokens')} hint={t('config_max_tokens_hint')}>
            <TextInput
              type="number"
              className="font-mono"
              value={maxTokens}
              onChange={(e) => setMaxTokens(parseInt(e.target.value) || 0)}
            />
          </Field>
          <Field label={t('config_max_turns')} hint={t('config_max_turns_hint')}>
            <TextInput
              type="number"
              className="font-mono"
              value={maxTurns}
              onChange={(e) => setMaxTurns(parseInt(e.target.value) || 0)}
            />
          </Field>
          <Field label={t('config_max_steps')} hint={t('config_max_steps_hint')}>
            <TextInput
              type="number"
              className="font-mono"
              value={maxSteps}
              onChange={(e) => setMaxSteps(parseInt(e.target.value) || 0)}
            />
          </Field>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_thinking')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_thinking_hint')}</div>
            </div>
            <Toggle checked={thinking} onChange={setThinking} />
          </div>
          {showReasoningEffort && (
            <Field label={t('config_reasoning_effort')} hint={t('config_reasoning_effort_hint')}>
              <Dropdown
                value={reasoningValue}
                options={reasoningOptions}
                onChange={setReasoningEffort}
              />
            </Field>
          )}
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_subagent')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_subagent_hint')}</div>
            </div>
            <Toggle checked={subagent} onChange={setSubagent} />
          </div>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_evolution')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_evolution_hint')}</div>
            </div>
            <Toggle checked={evolution} onChange={setEvolution} />
          </div>
          <SaveRow status={agentStatus} onSave={saveAgentConfig} />
        </div>
      </Card>

      {/* 安全性 */}
      <Card icon={<ShieldCheck size={16} />} title={t('config_security')}>
        <div className="space-y-4">
          <Field label={t('config_permission')} hint={t('config_permission_desc')}>
            <Dropdown
              value={permissionMode}
              options={PERMISSION_MODE_ORDER.filter(
                (m) => !config?.permission_modes?.length || config.permission_modes.includes(m)
              ).map((m) => ({
                value: m,
                label: t(PERMISSION_META[m].key),
                hint: t(PERMISSION_META[m].descKey),
              }))}
              onChange={savePermission}
            />
            {permStatus && <p className="text-xs text-accent mt-1">{permStatus}</p>}
          </Field>
          <Field label={t('config_password')} hint={t('config_password_hint')}>
            <div className="relative">
              <TextInput
                type={pwVisible ? 'text' : 'password'}
                className="pr-10"
                value={password}
                placeholder={t('config_password_placeholder')}
                onFocus={() => {
                  // 浏览器访问显示掩码；清除焦点，以便用户
                  // 输入新密码。桌面保存着真实的密码
                  // 必须保持可编辑状态（光标位于末尾）。
                  if (!hasRealPassword && !pwDirty && MASK_RE.test(password)) setPassword('')
                }}
                onBlur={() => {
                  if (!hasRealPassword && !pwDirty) setPassword(config?.web_password_masked || '')
                }}
                onChange={(e) => {
                  setPassword(e.target.value)
                  setPwDirty(true)
                }}
              />
              <button
                type="button"
                onClick={() => setPwVisible((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary cursor-pointer p-1"
              >
                {pwVisible ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </Field>
          <SaveRow status={pwStatus} onSave={savePassword} />
        </div>
      </Card>

      {/* 系统——语言+通知首选项（客户端，无保存） */}
      <Card icon={<Settings size={16} />} title={t('config_system')}>
        <div className="space-y-4">
          <Field label={t('config_language')} hint={t('config_language_hint')}>
            <Dropdown
              value={getLang()}
              options={[
                { value: 'zh', label: '简体中文' },
                { value: 'en', label: 'English' },
              ]}
              onChange={(v) => changeLanguage(v as Lang)}
            />
          </Field>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_task_notify')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_task_notify_hint')}</div>
            </div>
            <Toggle checked={taskNotify} onChange={setTaskNotify} />
          </div>
          <div className="flex items-center justify-between py-1">
            <div>
              <div className="text-sm font-medium text-content">{t('config_task_notify_sound')}</div>
              <div className="text-xs text-content-tertiary mt-0.5">{t('config_task_notify_sound_hint')}</div>
            </div>
            <Toggle checked={taskNotifySound} onChange={setTaskNotifySound} />
          </div>
          {supportsLaunchAtLogin && (
            <div className="py-1">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-content">{t('config_launch_at_login')}</div>
                  <div className="text-xs text-content-tertiary mt-0.5">{t('config_launch_at_login_hint')}</div>
                </div>
                <Toggle checked={launchAtLogin} onChange={toggleLaunchAtLogin} />
              </div>
              {launchAtLoginError && (
                <div className="text-xs text-danger mt-1.5">{launchAtLoginError}</div>
              )}
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}

export default BasicSettings
