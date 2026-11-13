<template>
  <div class="plot-page">
    <!-- 工具栏 -->
    <div class="plot-toolbar">
      <h2 class="pt-title"><t-icon name="chart-bubble" /> 剧情流程图</h2>
      <t-select v-model="volFilter" size="small" style="width:150px" placeholder="全部卷">
        <t-option value="all" label="全部卷" />
        <t-option v-for="v in graph.volumes" :key="v.id" :value="String(v.id)" :label="v.title" />
      </t-select>
      <div class="spacer"></div>
      <t-checkbox v-model="layers.seq">顺序流</t-checkbox>
      <t-checkbox v-model="layers.fore">伏笔回收线</t-checkbox>
      <t-checkbox v-model="layers.pending">未回收伏笔</t-checkbox>
      <t-checkbox v-model="layers.chars">角色</t-checkbox>
      <t-button size="small" variant="outline" @click="fit"><t-icon name="fullscreen" /> 适应画布</t-button>
      <t-button size="small" variant="outline" :loading="loading" @click="load"><t-icon name="refresh" /></t-button>
    </div>

    <!-- 图例 -->
    <div class="plot-legend">
      <span class="lg"><i class="dot dot-todo"></i>待写</span>
      <span class="lg"><i class="dot dot-drafted"></i>初稿</span>
      <span class="lg"><i class="dot dot-reviewed"></i>已审</span>
      <span class="lg"><i class="dot dot-final"></i>定稿</span>
      <span class="lg"><i class="line line-seq"></i>顺序流</span>
      <span class="lg"><i class="line line-fore"></i>伏笔回收</span>
      <span class="lg"><i class="line line-pending"></i>待回收</span>
    </div>

    <!-- 画布 -->
    <div class="plot-canvas">
      <VueFlow
        v-if="flowNodes.length"
        :nodes="flowNodes"
        :edges="flowEdges"
        :default-viewport="{ zoom: 0.75 }"
        :min-zoom="0.2"
        :max-zoom="2"
        :fit-view-on-init="true"
        style="width:100%;height:100%"
        @node-click="onNodeClick"
      >
          <Background :gap="16" pattern-color="#dcdcdc" />
          <Controls />
          <MiniMap pannable zoomable />

          <!-- 卷标节点 -->
          <template #node-volume="{ data }">
            <div class="vol-node">{{ data.title }}</div>
          </template>

          <!-- 待回收汇聚节点 -->
          <template #node-pending="{ data }">
            <div class="pending-node">
              <Handle type="target" :position="Position.Left" id="l" />
              ⌛ 待回收 {{ data.count }}
            </div>
          </template>

          <!-- 章节卡片节点 -->
          <template #node-chapter="{ data }">
            <div class="ch-node" :class="'st-' + data.status" :style="{ width: NODE_W + 'px' }">
              <Handle type="target" :position="Position.Left" id="l" />
              <Handle type="source" :position="Position.Right" id="r" />
              <Handle type="source" :position="Position.Top" id="t" />
              <Handle type="target" :position="Position.Bottom" id="b" />
              <div class="ch-top">
                <span class="ch-no">第{{ data.idx + 1 }}章</span>
                <span class="ch-name" :title="data.title">{{ data.title }}</span>
              </div>
              <div class="ch-mid">
                <span class="ch-status">{{ statusText(data.status) }}</span>
                <span class="ch-wc">{{ data.word_count }}字</span>
              </div>
              <div class="ch-badges">
                <span v-if="data.fp" class="badge b-plant" :title="`埋设 ${data.fp} 条伏笔`">🚩{{ data.fp }}</span>
                <span v-if="data.fr" class="badge b-resolve" :title="`回收 ${data.fr} 条伏笔`">✓{{ data.fr }}</span>
                <span v-if="data.tl" class="badge b-tl" :title="`${data.tl} 个时间线事件`">🕐{{ data.tl }}</span>
              </div>
              <div v-if="layers.chars && data.characters.length" class="ch-chars">
                <span v-for="cn in data.characters.slice(0,4)" :key="cn" class="char-chip">{{ cn }}</span>
                <span v-if="data.characters.length>4" class="char-chip">+{{ data.characters.length-4 }}</span>
              </div>
            </div>
          </template>
        </VueFlow>
      <div v-else class="plot-placeholder">
        <t-loading v-if="loading" size="small" text="加载中…" />
        <t-empty v-else description="还没有章节，先去「大纲」生成或添加" />
      </div>
    </div>

    <!-- 章节详情抽屉 -->
    <t-drawer v-model:visible="detailOpen" :header="detail.title || '章节'" size="420px" :footer="false">
      <div v-if="detail.id" class="detail">
        <div class="d-row"><span class="d-k">状态</span><t-tag size="small" :theme="statusTheme(detail.status)">{{ statusText(detail.status) }}</t-tag></div>
        <div class="d-row"><span class="d-k">字数</span><span>{{ detail.word_count }}</span></div>
        <div class="d-row"><span class="d-k">所属卷</span><span>{{ detail.volumeTitle }}</span></div>
        <div class="d-sec">本章梗概<div class="d-text">{{ detail.brief || '—' }}</div></div>
        <div class="d-sec">内容摘要<div class="d-text">{{ detail.summary || '（暂无摘要）' }}</div></div>
        <div class="d-sec">出场角色
          <div class="d-chars">
            <t-tag v-for="cn in detail.characters" :key="cn" size="small" variant="light">{{ cn }}</t-tag>
            <span v-if="!detail.characters?.length" class="muted">—</span>
          </div>
        </div>
        <div class="d-sec">埋设伏笔
          <ul class="d-list"><li v-for="f in detail.plantedList" :key="f.id">{{ f.description }}</li></ul>
          <span v-if="!detail.plantedList?.length" class="muted">—</span>
        </div>
        <div class="d-sec">回收伏笔
          <ul class="d-list"><li v-for="f in detail.resolvedList" :key="f.id">{{ f.description }}</li></ul>
          <span v-if="!detail.resolvedList?.length" class="muted">—</span>
        </div>
        <t-button theme="primary" block style="margin-top:16px" @click="openEditor">
          <t-icon name="edit-1" /> 打开编辑器
        </t-button>
      </div>
    </t-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { VueFlow, Handle, Position, MarkerType, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
const pid = computed(() => route.params.pid)
const { fitView } = useVueFlow()

const NODE_W = 196
const NODE_H = 92
const GAP_X = 60
const LANE_H = 200
const LANE_TOP = 40
const VOL_W = 96

const graph = ref({ volumes: [], nodes: [], foreshadows: [], characters: [] })
const loading = ref(false)
const volFilter = ref('all')
const layers = reactive({ seq: true, fore: true, pending: true, chars: true })
const detailOpen = ref(false)
const detail = ref({})

const STATUS_TEXT = { todo: '待写', drafted: '初稿', reviewed: '已审', final: '定稿' }
const STATUS_THEME = { todo: 'default', drafted: 'warning', reviewed: 'primary', final: 'success' }
function statusText(s) { return STATUS_TEXT[s] || '待写' }
function statusTheme(s) { return STATUS_THEME[s] || 'default' }

async function load() {
  loading.value = true
  try {
    graph.value = await api.get(`/api/projects/${pid.value}/plot-graph`)
  } catch (e) {
    MessagePlugin.error('加载流程图失败：' + e.message)
  } finally {
    loading.value = false
  }
}

function fit() { nextTick(() => fitView({ padding: 0.15 })) }

// ---- 构建 vue-flow 节点与边 ----
const built = computed(() => {
  const g = graph.value
  const volumes = [...g.volumes].sort((a, b) => a.idx - b.idx)
  const nodesByVol = {}
  for (const n of g.nodes) (nodesByVol[n.volume_id] ||= []).push(n)
  Object.values(nodesByVol).forEach(arr => arr.sort((a, b) => a.idx - b.idx))

  const foByChapter = {}
  for (const f of g.foreshadows) {
    if (f.planted_chapter_id) (foByChapter[f.planted_chapter_id] ||= []).push(f)
  }

  const nodes = []
  const edges = []
  const chapterPos = {} // chid -> {x,y}
  const flatOrder = [] // 阅读顺序的章节 id

  volumes.forEach((v, vi) => {
    const chs = nodesByVol[v.id] || []
    if (volFilter.value !== 'all' && String(v.id) !== volFilter.value) return
    const laneY = LANE_TOP + vi * LANE_H

    // 卷标节点
    nodes.push({
      id: `vol-${v.id}`, type: 'volume',
      position: { x: 0, y: laneY + NODE_H / 2 - 16 },
      data: { title: v.title }, draggable: false, selectable: false,
    })

    chs.forEach((ch, cj) => {
      const x = VOL_W + GAP_X + cj * (NODE_W + GAP_X)
      const y = laneY
      chapterPos[ch.id] = { x, y }
      flatOrder.push(ch.id)
      nodes.push({
        id: `ch-${ch.id}`, type: 'chapter', position: { x, y },
        data: {
          id: ch.id, idx: ch.idx, title: ch.title, status: ch.status,
          word_count: ch.word_count, brief: ch.brief, summary: ch.summary,
          characters: ch.characters || [], fp: (ch.foreshadow_planted || []).length,
          fr: (ch.foreshadow_resolved || []).length, tl: ch.timeline_count || 0,
          volumeTitle: v.title,
          plantedList: (ch.foreshadow_planted || []).map(fid => g.foreshadows.find(f => f.id === fid)).filter(Boolean),
          resolvedList: (ch.foreshadow_resolved || []).map(fid => g.foreshadows.find(f => f.id === fid)).filter(Boolean),
        },
      })
    })

    // 该卷未回收伏笔汇聚节点
    if (layers.pending) {
      const openHere = g.foreshadows.filter(f => f.status === 'open'
        && chs.some(c => c.id === f.planted_chapter_id))
      if (openHere.length) {
        const px = VOL_W + GAP_X + Math.max(chs.length, 1) * (NODE_W + GAP_X)
        nodes.push({
          id: `pending-${v.id}`, type: 'pending',
          position: { x: px, y: laneY + NODE_H / 2 - 14 },
          data: { count: openHere.length }, draggable: false, selectable: false,
        })
        for (const f of openHere) {
          edges.push({
            id: `pf-${f.id}`, source: `ch-${f.planted_chapter_id}`, sourceHandle: 't',
            target: `pending-${v.id}`, targetHandle: 'l', type: 'default', animated: true,
            label: short(f.description), labelStyle: { fontSize: 10, fill: '#b26a00' },
            style: { stroke: '#e8a33d', strokeWidth: 1.6, strokeDasharray: '5 4' },
          })
        }
      }
    }
  })

  // 顺序流（按阅读顺序连接相邻章节，含跨卷）
  if (layers.seq) {
    for (let i = 0; i < flatOrder.length - 1; i++) {
      const a = flatOrder[i], b = flatOrder[i + 1]
      if (!chapterPos[a] || !chapterPos[b]) continue
      edges.push({
        id: `seq-${a}-${b}`, source: `ch-${a}`, sourceHandle: 'r',
        target: `ch-${b}`, targetHandle: 'l', type: 'smoothstep',
        style: { stroke: '#b8b8b8', strokeWidth: 1.6 },
        markerEnd: MarkerType.ArrowClosed,
      })
    }
  }

  // 伏笔回收线（埋设→回收）
  if (layers.fore) {
    for (const f of g.foreshadows) {
      if (f.status !== 'paid' || !f.planted_chapter_id || !f.payoff_chapter_id) continue
      if (!chapterPos[f.planted_chapter_id] || !chapterPos[f.payoff_chapter_id]) continue
      edges.push({
        id: `fore-${f.id}`, source: `ch-${f.planted_chapter_id}`, sourceHandle: 't',
        target: `ch-${f.payoff_chapter_id}`, targetHandle: 'b', type: 'default',
        label: short(f.description), labelStyle: { fontSize: 10, fill: '#1f8a4c' },
        style: { stroke: '#2ba471', strokeWidth: 2 },
        markerEnd: MarkerType.ArrowClosed,
      })
    }
  }

  return { nodes, edges }
})

const flowNodes = computed(() => built.value.nodes)
const flowEdges = computed(() => built.value.edges)

function short(s, n = 10) { return (s || '').length > n ? s.slice(0, n) + '…' : (s || '') }

function onNodeClick({ node }) {
  if (node.type !== 'chapter') return
  detail.value = node.data
  detailOpen.value = true
}

function openEditor() {
  detailOpen.value = false
  router.push(`/project/${pid.value}/chapter/${detail.value.id}`)
}

watch([volFilter, layers], () => nextTick(fit), { deep: true })
onMounted(async () => { await load(); fit() })
</script>

<style scoped>
.plot-page { display: flex; flex-direction: column; height: 100%; }
.plot-toolbar { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid var(--td-component-stroke); background: var(--td-bg-color-container); flex-wrap: wrap; }
.pt-title { font-size: 16px; font-weight: 600; margin: 0; display: flex; align-items: center; gap: 6px; }
.spacer { flex: 1; }
.plot-legend { display: flex; gap: 16px; padding: 6px 16px; font-size: 12px; color: var(--td-text-color-secondary); background: var(--td-bg-color-container); border-bottom: 1px solid var(--td-component-stroke); flex-wrap: wrap; }
.lg { display: flex; align-items: center; gap: 5px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.dot-todo { background: #bbb; } .dot-drafted { background: #e8a33d; } .dot-reviewed { background: #0052d9; } .dot-final { background: #2ba471; }
.line { width: 18px; height: 0; border-top: 2px solid; display: inline-block; }
.line-seq { border-color: #b8b8b8; } .line-fore { border-color: #2ba471; } .line-pending { border-color: #e8a33d; border-top-style: dashed; }
.plot-canvas { flex: 1; position: relative; min-height: 0; }
.plot-placeholder { height: 100%; display: flex; align-items: center; justify-content: center; }

/* 卷标 */
.vol-node { font-weight: 700; font-size: 14px; color: var(--td-brand-color); background: var(--td-brand-color-light, #ecf2fe); border: 1px solid var(--td-brand-color); border-radius: 8px; padding: 6px 12px; white-space: nowrap; }
/* 待回收汇聚 */
.pending-node { font-size: 12px; color: #b26a00; background: #fff7e8; border: 1px dashed #e8a33d; border-radius: 14px; padding: 5px 12px; white-space: nowrap; }

/* 章节卡片 */
.ch-node { box-sizing: border-box; height: 92px; background: var(--td-bg-color-container); border: 1px solid var(--td-component-border); border-left: 4px solid #bbb; border-radius: 8px; padding: 8px 10px; cursor: pointer; box-shadow: 0 1px 3px rgba(0,0,0,.08); transition: box-shadow .15s, transform .15s; overflow: hidden; }
.ch-node:hover { box-shadow: 0 4px 12px rgba(0,0,0,.16); transform: translateY(-1px); }
.ch-node.st-drafted { border-left-color: #e8a33d; }
.ch-node.st-reviewed { border-left-color: #0052d9; }
.ch-node.st-final { border-left-color: #2ba471; }
.ch-top { display: flex; align-items: baseline; gap: 6px; }
.ch-no { font-size: 11px; color: var(--td-text-color-placeholder); flex-shrink: 0; }
.ch-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ch-mid { display: flex; align-items: center; gap: 8px; margin-top: 3px; font-size: 11px; color: var(--td-text-color-secondary); }
.ch-status { }
.ch-badges { display: flex; gap: 6px; margin-top: 4px; }
.badge { font-size: 10px; padding: 1px 5px; border-radius: 8px; line-height: 1.5; }
.b-plant { background: #fff1e8; color: #d4492a; }
.b-resolve { background: #e8f7ef; color: #1f8a4c; }
.b-tl { background: #eef0f3; color: #555; }
.ch-chars { display: flex; gap: 3px; margin-top: 4px; flex-wrap: wrap; }
.char-chip { font-size: 10px; background: var(--td-bg-color-secondarycontainer, #f3f5f7); color: var(--td-text-color-secondary); border-radius: 6px; padding: 0 5px; line-height: 1.6; }

/* 详情抽屉 */
.detail { font-size: 13px; }
.d-row { display: flex; gap: 10px; margin-bottom: 8px; }
.d-k { color: var(--td-text-color-secondary); min-width: 56px; }
.d-sec { margin-top: 14px; font-weight: 600; }
.d-text { font-weight: 400; margin-top: 4px; line-height: 1.7; color: var(--td-text-color-primary); background: var(--td-bg-color-page); padding: 8px 10px; border-radius: 6px; }
.d-chars { margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap; }
.d-list { font-weight: 400; margin: 4px 0 0; padding-left: 18px; line-height: 1.7; }
</style>
