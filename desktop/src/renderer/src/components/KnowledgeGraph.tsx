import React, { useEffect, useMemo, useRef, useState } from 'react'
import type { KnowledgeGraph as KnowledgeGraphData } from '../types'

interface SimNode {
  id: string
  label: string
  category: string
  x: number
  y: number
  vx: number
  vy: number
  fx: number | null
  fy: number | null
  degree: number
}

interface KnowledgeGraphProps {
  data: KnowledgeGraphData
  onSelect: (id: string, label: string) => void
}

// d3.schemeTableau10 — 保留 Web 客户端的调色板以实现视觉奇偶校验。
const TABLEAU10 = [
  '#4e79a7',
  '#f28e2c',
  '#e15759',
  '#76b7b2',
  '#59a14f',
  '#edc949',
  '#af7aa1',
  '#ff9da7',
  '#9c755f',
  '#bab0ab',
]

const nodeRadius = (degree: number) => Math.max(4, Math.min(12, 4 + degree * 1.4))

// 具有滚轮缩放、画布平移和节点的无依赖性力导向图
// 拖。物理循环将位置直接写入 DOM（如 d3）
// 每帧调用 setState，因此 React 在该过程中不会重新渲染
// 模拟——这就是防止它闪烁的原因。
const KnowledgeGraph: React.FC<KnowledgeGraphProps> = ({ data, onSelect }) => {
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const sizeRef = useRef({ w: 800, h: 560 })
  const [hover, setHover] = useState<string | null>(null)
  // 碰撞此重新武装物理循环（在拖动时使用），而不需要
  // 重建模型，保留当前节点位置。
  const [warmTick, setWarmTick] = useState(0)

  // 视图变换（平移+缩放）。
  const viewRef = useRef({ k: 1, x: 0, y: 0 })

  // 每次数据更改时构建一次不可变模型。
  const model = useMemo(() => {
    const degree = new Map<string, number>()
    data.links.forEach((l) => {
      degree.set(l.source, (degree.get(l.source) || 0) + 1)
      degree.set(l.target, (degree.get(l.target) || 0) + 1)
    })
    // 按节点数对类别进行排序，以便主导集群获得最多
    // 显着的调色板条目而不是任何颜色插入顺序
    // 上。关系按名称断开，以在重新加载时保持映射稳定。
    const catCount = new Map<string, number>()
    data.nodes.forEach((n) => {
      const c = n.category || 'default'
      catCount.set(c, (catCount.get(c) || 0) + 1)
    })
    const categories = Array.from(catCount.keys()).sort(
      (a, b) => catCount.get(b)! - catCount.get(a)! || a.localeCompare(b)
    )
    const colorOf = (cat: string) => TABLEAU10[categories.indexOf(cat) % TABLEAU10.length]

    const n = data.nodes.length || 1
    const { w, h } = sizeRef.current
    const cx = w / 2
    const cy = h / 2
    const nodes: SimNode[] = data.nodes.map((nd, i) => {
      const angle = (i / n) * Math.PI * 2
      const radius = Math.min(w, h) * 0.32
      return {
        id: nd.id,
        label: nd.label,
        category: nd.category || 'default',
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        fx: null,
        fy: null,
        degree: degree.get(nd.id) || 0,
      }
    })
    const valid = new Set(nodes.map((x) => x.id))
    const byId = new Map(nodes.map((x) => [x.id, x]))
    const links = data.links
      .filter((l) => valid.has(l.source) && valid.has(l.target))
      .map((l, i) => ({ key: i, a: byId.get(l.source)!, b: byId.get(l.target)! }))
    const adjacency = new Map<string, Set<string>>()
    data.links.forEach((l) => {
      if (!valid.has(l.source) || !valid.has(l.target)) return
      if (!adjacency.has(l.source)) adjacency.set(l.source, new Set())
      if (!adjacency.has(l.target)) adjacency.set(l.target, new Set())
      adjacency.get(l.source)!.add(l.target)
      adjacency.get(l.target)!.add(l.source)
    })
    return { nodes, links, adjacency, categories, colorOf, byId }
  }, [data])

  // 用于命令式位置更新的 DOM 引用。
  const rootRef = useRef<SVGGElement>(null)
  const lineEls = useRef(new Map<number, SVGLineElement>())
  const groupEls = useRef(new Map<string, SVGGElement>())

  // 在 ref 中跟踪容器大小；永远不会自行触发重新渲染。
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const apply = () => {
      sizeRef.current = { w: el.clientWidth || 800, h: el.clientHeight || 560 }
    }
    apply()
    const ro = new ResizeObserver(apply)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // 物理循环。仅当模型（数据）更改时才重新启动。写入 DOM。
  // 使用 d3 式 alpha 冷却，因此它始终稳定并停止 rAF。
  useEffect(() => {
    const { nodes, links } = model
    if (nodes.length === 0) return
    let raf = 0
    let alive = true
    // 全局冷却系数；向 0 衰减并缩放节点移动的距离。
    let alpha = 1
    const alphaDecay = 0.018
    const alphaMin = 0.005

    const paint = () => {
      links.forEach(({ key, a, b }) => {
        const el = lineEls.current.get(key)
        if (!el) return
        el.setAttribute('x1', String(a.x))
        el.setAttribute('y1', String(a.y))
        el.setAttribute('x2', String(b.x))
        el.setAttribute('y2', String(b.y))
      })
      nodes.forEach((node) => {
        const el = groupEls.current.get(node.id)
        if (el) el.setAttribute('transform', `translate(${node.x},${node.y})`)
      })
    }

    const step = () => {
      if (!alive) return
      const { w, h } = sizeRef.current
      const cx = w / 2
      const cy = h / 2
      const repulsion = 9000
      const springLen = 80
      const spring = 0.04
      const centering = 0.012
      const dragging = nodes.some((node) => node.fx != null)

      // 每个刻度重置累积速度（alpha 缩放位移），以便
      // 系统不能积累能量和振荡。
      nodes.forEach((node) => {
        node.vx = 0
        node.vy = 0
      })

      // 排斥+碰撞：节点推开，但半径永远不会重叠。
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i]
        const ra = nodeRadius(a.degree)
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j]
          let dx = a.x - b.x
          let dy = a.y - b.y
          let d2 = dx * dx + dy * dy
          if (d2 < 0.01) {
            dx = Math.random() - 0.5
            dy = Math.random() - 0.5
            d2 = 0.01
          }
          let d = Math.sqrt(d2)
          let f = repulsion / d2
          // 硬碰撞：如果比组合半径更近，则强烈分离。
          const minDist = ra + nodeRadius(b.degree) + 14
          if (d < minDist) f += (minDist - d) * 0.6
          a.vx += (dx / d) * f
          a.vy += (dy / d) * f
          b.vx -= (dx / d) * f
          b.vy -= (dy / d) * f
        }
      }
      links.forEach(({ a, b }) => {
        const dx = b.x - a.x
        const dy = b.y - a.y
        const d = Math.sqrt(dx * dx + dy * dy) || 1
        const f = (d - springLen) * spring
        a.vx += (dx / d) * f
        a.vy += (dy / d) * f
        b.vx -= (dx / d) * f
        b.vy -= (dy / d) * f
      })
      // 弱居中，因此整个图表保持在视图中而不会折叠。
      nodes.forEach((node) => {
        node.vx += (cx - node.x) * centering
        node.vy += (cy - node.y) * centering
      })

      // 应用 alpha 缩放位移；固定节点保持原状。每个刻度上限
      // 如此强大的初始力不会将节点甩出屏幕。
      const maxStep = 30
      nodes.forEach((node) => {
        if (node.fx != null) {
          node.x = node.fx
          node.y = node.fy as number
          return
        }
        let dx = node.vx * alpha
        let dy = node.vy * alpha
        const m = Math.hypot(dx, dy)
        if (m > maxStep) {
          dx = (dx / m) * maxStep
          dy = (dy / m) * maxStep
        }
        node.x += dx
        node.y += dy
      })

      paint()
      alpha += (0 - alpha) * alphaDecay
      // 在冷却时或在拖动节点时保持运行。
      if (alpha > alphaMin || dragging) {
        raf = requestAnimationFrame(step)
      }
    }
    raf = requestAnimationFrame(step)
    return () => {
      alive = false
      cancelAnimationFrame(raf)
    }
    // WarmTick 按需重新设置循环（例如拖动时），无需
    // 重建模型，因此保留位置。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, warmTick])

  // 强制应用视图变换（无需重新渲染）。
  const applyView = () => {
    const v = viewRef.current
    if (rootRef.current) rootRef.current.setAttribute('transform', `translate(${v.x},${v.y}) scale(${v.k})`)
  }
  useEffect(applyView)

  // 将指针事件转换为图形（转换前）坐标。
  const toGraph = (clientX: number, clientY: number) => {
    const rect = svgRef.current!.getBoundingClientRect()
    const v = viewRef.current
    return { x: (clientX - rect.left - v.x) / v.k, y: (clientY - rect.top - v.y) / v.k }
  }

  // 以光标为中心的滚轮缩放（匹配 d3.zoom scaleExtent [0.2, 5]）。
  // React 在根被动附加 `wheel`，其中 PreventDefault 是
  // 仅记录警告的无操作 - 与 `passive: false` 本地绑定，因此
  // 缩放时页面不滚动。
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const v = viewRef.current
      const rect = svg.getBoundingClientRect()
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top
      const factor = Math.exp(-e.deltaY * 0.0015)
      const k = Math.min(5, Math.max(0.2, v.k * factor))
      viewRef.current = { k, x: px - ((px - v.x) / v.k) * k, y: py - ((py - v.y) / v.k) * k }
      applyView()
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [])

  // 拖动：在节点上移动节点，在背景上平移画布。
  const dragRef = useRef<
    | { mode: 'node'; node: SimNode; moved: boolean }
    | { mode: 'pan'; startX: number; startY: number; ox: number; oy: number }
    | null
  >(null)
  const kick = () => setWarmTick((v) => v + 1)

  const onPointerDownNode = (e: React.PointerEvent, node: SimNode) => {
    e.stopPropagation()
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    const p = toGraph(e.clientX, e.clientY)
    node.fx = p.x
    node.fy = p.y
    dragRef.current = { mode: 'node', node, moved: false }
    kick()
  }

  const onPointerDownBg = (e: React.PointerEvent) => {
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    const v = viewRef.current
    dragRef.current = { mode: 'pan', startX: e.clientX, startY: e.clientY, ox: v.x, oy: v.y }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current
    if (!drag) return
    if (drag.mode === 'node') {
      const p = toGraph(e.clientX, e.clientY)
      drag.node.fx = p.x
      drag.node.fy = p.y
      drag.moved = true
      // 保持循环温暖以进行实时拖动。
      const el = groupEls.current.get(drag.node.id)
      if (el) el.setAttribute('transform', `translate(${p.x},${p.y})`)
    } else {
      viewRef.current = { k: viewRef.current.k, x: drag.ox + (e.clientX - drag.startX), y: drag.oy + (e.clientY - drag.startY) }
      applyView()
    }
  }

  const onPointerUp = (e: React.PointerEvent, node?: SimNode) => {
    const drag = dragRef.current
    if (drag?.mode === 'node') {
      drag.node.fx = null
      drag.node.fy = null
      if (node && !drag.moved) onSelect(node.id, node.label)
      kick()
    }
    dragRef.current = null
    try {
      ;(e.target as Element).releasePointerCapture(e.pointerId)
    } catch {
      /* 努普 */
    }
  }

  const { nodes, links, adjacency, categories, colorOf } = model
  const { w, h } = sizeRef.current
  const isDimmed = (id: string) => hover != null && hover !== id && !adjacency.get(hover)?.has(id)
  const isLinkActive = (aId: string, bId: string) => hover === aId || hover === bId

  return (
    <div ref={wrapRef} className="w-full h-full relative overflow-hidden">
      <svg
        ref={svgRef}
        width={w}
        height={h}
        className="select-none block cursor-grab active:cursor-grabbing"
        onPointerDown={onPointerDownBg}
        onPointerMove={onPointerMove}
        onPointerUp={(e) => onPointerUp(e)}
      >
        <g ref={rootRef}>
          {links.map(({ key, a, b }) => {
            const active = isLinkActive(a.id, b.id)
            return (
              <line
                key={key}
                ref={(el) => {
                  if (el) lineEls.current.set(key, el)
                  else lineEls.current.delete(key)
                }}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="#94a3b8"
                strokeOpacity={hover ? (active ? 0.8 : 0.1) : 0.3}
                strokeWidth={1}
              />
            )
          })}
          {nodes.map((n) => {
            const r = nodeRadius(n.degree)
            const dim = isDimmed(n.id)
            return (
              <g
                key={n.id}
                ref={(el) => {
                  if (el) groupEls.current.set(n.id, el)
                  else groupEls.current.delete(n.id)
                }}
                transform={`translate(${n.x},${n.y})`}
                className="cursor-pointer"
                opacity={dim ? 0.2 : 1}
                onMouseEnter={() => setHover(n.id)}
                onMouseLeave={() => setHover(null)}
                onPointerDown={(e) => onPointerDownNode(e, n)}
                onPointerUp={(e) => onPointerUp(e, n)}
              >
                <circle r={r} fill={colorOf(n.category)} stroke="#fff" strokeWidth={1.5} />
                {(hover === n.id || n.degree >= 3) && (
                  <text x={r + 4} y={3} className="fill-content-secondary" fontSize={9} style={{ pointerEvents: 'none' }}>
                    {n.label.length > 15 ? n.label.slice(0, 14) + '…' : n.label}
                  </text>
                )}
              </g>
            )
          })}
        </g>
      </svg>

      {/* 类别图例，反映网络客户端。 */}
      {categories.length > 0 && (
        <div className="absolute bottom-3 left-3 flex flex-wrap gap-x-3 gap-y-1 max-w-[60%] rounded-lg bg-surface px-3 py-2 border border-subtle shadow-sm">
          {categories.map((cat) => (
            <span key={cat} className="inline-flex items-center gap-1.5 text-[11px] text-content-secondary">
              <span className="w-2.5 h-2.5 rounded-full" style={{ background: colorOf(cat) }} />
              {cat}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default KnowledgeGraph
