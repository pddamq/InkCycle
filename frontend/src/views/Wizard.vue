<template>
  <div class="wizard page page-narrow">
    <PageTopbar :title="`生成《${project.title || '…'}》`" icon="magic" back-to="/" back-label="返回书架" />

    <t-card v-if="brief.logline || brief.theme" size="small" style="margin-bottom:16px">
      <div class="brief-sum">
        <t-tag size="small" variant="light" theme="primary">{{ project.genre || '未分类' }}</t-tag>
        <span class="bs-logline">{{ brief.logline }}</span>
      </div>
      <div class="bs-meta muted">
        <span v-if="brief.theme">主题：{{ brief.theme }}</span>
        <span v-if="brief.tone">基调：{{ brief.tone }}</span>
        <span>目标 {{ ((project.target_words||0)/10000).toFixed(1) }} 万字</span>
      </div>
    </t-card>

    <t-steps :current="step" style="margin-bottom:24px">
      <t-step-item title="生成设定·角色·大纲" />
      <t-step-item title="完成" />
    </t-steps>

    <t-card v-if="step === 0">
      <div v-for="s in stages" :key="s.key" class="stage-row">
        <t-icon v-if="s.state==='done'" name="check-circle-filled" class="ic ic-done" />
        <t-icon v-else-if="s.state==='run'" name="loading" class="ic ic-run" />
        <t-icon v-else-if="s.state==='error'" name="close-circle-filled" class="ic ic-err" />
        <t-icon v-else name="time" class="ic ic-wait" />
        <span class="stage-name">{{ s.name }}</span>
        <span class="muted stage-msg">{{ s.msg }}</span>
      </div>

      <GeneratePanel
        :active="gen.active"
        :title="currentStageTitle"
        :status="gen.status"
        :items="gen.items"
      />

      <div class="toolbar" style="margin-top:16px">
        <div class="spacer"></div>
        <t-button variant="outline" :disabled="running" @click="retryFailed" v-if="hasError">重试失败步骤</t-button>
        <t-button theme="primary" :disabled="running || !allDone" @click="finish">进入工作台</t-button>
      </div>
    </t-card>

    <t-result v-else theme="success" title="作品已就绪" :description="`《${project.title}》的世界观、角色与大纲已生成完毕。`">
      <template #extra>
        <t-button theme="primary" @click="$router.push(`/project/${pid}/overview`)">开始创作</t-button>
        <t-button variant="outline" style="margin-left:12px" @click="$router.push(`/project/${pid}/book`)">整本创作</t-button>
      </template>
    </t-result>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import GeneratePanel from '../components/GeneratePanel.vue'
import PageTopbar from '../components/PageTopbar.vue'
import { useGenerateStream } from '../composables/useGenerateStream'
import { hydrateGenerationSnapshot } from '../composables/generationSession'

const route = useRoute()
const pid = computed(() => route.params.pid)
const project = ref({})
const brief = ref({})
const step = ref(0)
const running = ref(false)
const gen = useGenerateStream(`wizard:${route.params.pid}`, {
  extraSnapshot: () => ({
    stages: stages.value.map((s) => ({ ...s })),
    currentKey: currentKey.value,
    running: running.value,
    step: step.value,
  }),
  restoreExtra: (ex) => {
    if (ex?.stages?.length) stages.value = ex.stages
    if (ex?.currentKey != null) currentKey.value = ex.currentKey
    if (ex?.running != null) running.value = ex.running
    if (ex?.step != null) step.value = ex.step
  },
})
const currentKey = ref('')

const stages = ref([
  { key: 'settings', name: '世界观设定', state: 'wait', msg: '' },
  { key: 'characters', name: '主要角色', state: 'wait', msg: '' },
  { key: 'outline', name: '全书大纲', state: 'wait', msg: '' },
])
const STAGE_TITLE = { settings: '架构世界观', characters: '设计主要角色', outline: '规划全书大纲' }
const allDone = computed(() => stages.value.every((s) => s.state === 'done'))
const hasError = computed(() => stages.value.some((s) => s.state === 'error'))
const currentStageTitle = computed(() => STAGE_TITLE[currentKey.value] || 'AI 生成中')

async function loadProject() {
  try {
    project.value = await api.get(`/api/projects/${pid.value}`)
    brief.value = project.value.brief || {}
  } catch (e) { MessagePlugin.error('加载项目失败：' + e.message) }
}

function setStage(key, state, msg) {
  const s = stages.value.find((x) => x.key === key)
  if (s) { s.state = state; s.msg = msg || '' }
}

async function runStage(key) {
  currentKey.value = key
  setStage(key, 'run', '')
  const ok = await gen.start(
    `/api/projects/${pid.value}/wizard/${key}`,
    {},
    {
      onEvent(ev) {
        if (ev.type === 'status') setStage(key, 'run', ev.message)
        else if (ev.type === 'done') {
          let m = '完成'
          if (key === 'settings') m = `完成（${ev.sections?.length || 0} 个小节）`
          if (key === 'characters') m = `完成（${ev.count || 0} 个角色）`
          if (key === 'outline') m = `完成（${ev.volumes} 卷 ${ev.chapters} 章）`
          setStage(key, 'done', m)
          gen.items.push({ type: 'phase', text: `✓ ${m}` })
        } else if (ev.type === 'error') {
          setStage(key, 'error', ev.message)
        }
      },
      onError(e) { setStage(key, 'error', e.message) },
    },
  )
  return ok
}

async function runStages(onlyFailed = false) {
  running.value = true
  if (!onlyFailed) gen.items = []
  for (const s of stages.value) {
    if (onlyFailed && s.state !== 'error') continue
    const ok = await runStage(s.key)
    if (!ok && s.state !== 'done' && !onlyFailed) break
  }
  running.value = false
  currentKey.value = ''
}

function retryFailed() { runStages(true) }
function finish() {
  step.value = 1
  gen.clearPersisted()
}

onMounted(async () => {
  await loadProject()
  const saved = await hydrateGenerationSnapshot(`wizard:${route.params.pid}`)
  const allDoneLocal = stages.value.every((s) => s.state === 'done')
  const hasProgress = stages.value.some((s) => s.state !== 'wait')
  const wasInterrupted = saved?.interrupted || stages.value.some((s) => s.state === 'run')

  if (wasInterrupted) {
    running.value = false
    stages.value.forEach((s) => {
      if (s.state === 'run') { s.state = 'error'; s.msg = '上次被中断，请重试' }
    })
    MessagePlugin.warning('上次生成未完成，可点击「重试失败步骤」继续')
    return
  }
  if (allDoneLocal) {
    step.value = 1
    return
  }
  if (hasProgress && stages.value.some((s) => s.state === 'error')) {
    MessagePlugin.info('有未完成的生成步骤，可点击「重试失败步骤」')
    return
  }
  if (!gen.active && !hasProgress) runStages()
})
</script>

<style scoped>
.brief-sum { display: flex; align-items: center; gap: 10px; }
.bs-logline { font-size: 14px; font-weight: 500; }
.bs-meta { display: flex; gap: 18px; margin-top: 6px; font-size: 12px; }
.stage-row { display: flex; align-items: center; gap: 10px; padding: 10px 4px; border-bottom: 1px dashed var(--td-component-stroke); }
.stage-name { font-weight: 500; min-width: 110px; }
.stage-msg { flex: 1; }
.ic { font-size: 18px; }
.ic-done { color: var(--td-success-color); }
.ic-run { color: var(--td-brand-color); animation: spin 1s linear infinite; }
.ic-err { color: var(--td-error-color); }
.ic-wait { color: var(--td-text-color-placeholder); }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
