import React, { useState } from 'react'
import apiClient from '../api/client'
import type { AgentProfile } from '../types'
import { useAgentStore, findAgent } from '../store/agentStore'

/**
 * An Agent's face: its uploaded image when it has one, else a tinted disc with
 * the first character of its name. Mirrors the web console's `agentAvatarHTML`,
 * down to the same tones, so the same Agent looks the same in both clients.
 *
 * A null agent means the id no longer resolves — a conversation pinned to a
 * since-deleted Agent. Fall back to the default Agent's face rather than an
 * empty disc, so the deleted Agent visibly degrades to the default one.
 */

// 每个代理 ID 都有一个稳定的音调，具有确定性，因此脸部可以保持其颜色
// 应用程序和跨重新启动。带有较暗文本的有色背景，而不是
// 饱和填充：十几个人的名册应该读作一个平静的名单。拼写出来
// 作为整个类字符串，因为 Tailwind 只发出它可以看到的类
// 从字面上看，在源代码中。色调 0 是中性色调，由没有任何颜色的特工佩戴
// id 还没有。这些与 Web 控制台的 .agent-avatar-tone-* 规则相匹配。
const PALETTE = [
  'bg-[#eef1f5] text-[#4b5563] dark:bg-[#2a2f36] dark:text-[#b6bec9]',
  'bg-[#eaf0f7] text-[#3f5f80] dark:bg-[#26313d] dark:text-[#a8c0d6]',
  'bg-[#ebf3ed] text-[#46694e] dark:bg-[#263329] dark:text-[#a9c7b0]',
  'bg-[#f4f1e9] text-[#6b5f45] dark:bg-[#33302a] dark:text-[#cdbe9f]',
  'bg-[#f5eeeb] text-[#7a564d] dark:bg-[#352c2a] dark:text-[#d0b0a7]',
  'bg-[#f0eef6] text-[#574f70] dark:bg-[#2e2b38] dark:text-[#b8b0d0]',
]

function toneFor(id: string): string {
  let hash = 0
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0
  return PALETTE[hash % PALETTE.length]
}

// Array.from 而不是 [0]，因此星体平面字符被视为完整的
// 而不是作为半代理对。
function initial(name: string): string {
  return (Array.from((name || '').trim())[0] || '').toUpperCase()
}

interface AgentAvatarProps {
  agent?: Pick<AgentProfile, 'id' | 'name' | 'avatar'> | null
  size?: number
  className?: string
  // 'circle'（默认）用于名册/作曲家面孔；聊天气泡的“方块”，
  // 与之前使用的辅助气泡的圆角方形标志相匹配。
  shape?: 'circle' | 'square'
}

const AgentAvatar: React.FC<AgentAvatarProps> = ({ agent, size = 32, className = '', shape = 'circle' }) => {
  const radius = shape === 'square' ? 'rounded-lg' : 'rounded-full'
  // 当名册修订版本更改时，破坏 <img> 缓存（头像已更改）
  // 更换）。在这里阅读它也会在上传后重新渲染面孔。
  const revision = useAgentStore((s) => s.revision)
  const defaultAgentId = useAgentStore((s) => s.defaultAgentId)
  const [failed, setFailed] = useState(false)

  // 固定到已删除的代理：降级为默认代理的面孔。
  if (!agent && defaultAgentId) {
    agent = findAgent(defaultAgentId) ?? null
  }

  const hasImage = !!agent && agent.avatar === 'image' && !failed
  const px = { width: size, height: size }
  const id = agent?.id || ''

  if (hasImage && agent) {
    return (
      <img
        src={apiClient.agentAvatarUrl(agent.id, revision || agent.id)}
        alt={agent.name || agent.id}
        draggable={false}
        onError={() => setFailed(true)}
        style={px}
        className={`${radius} object-cover flex-shrink-0 ${className}`}
      />
    )
  }

  return (
    <span
      style={{ ...px, fontSize: Math.round(size * 0.42) }}
      className={`${radius} ${toneFor(id)} flex items-center justify-center flex-shrink-0 font-semibold select-none ${className}`}
    >
      {initial(agent?.name || id)}
    </span>
  )
}

export default AgentAvatar
