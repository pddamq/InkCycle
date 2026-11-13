<template>
  <div class="page">
    <h1 class="page-title">概览</h1>
    <div class="stat-grid">
      <div class="stat-card"><div class="num">{{ s.words }}</div><div class="label">累计字数</div></div>
      <div class="stat-card"><div class="num">{{ s.chapters_done }}/{{ s.chapters }}</div><div class="label">章节进度</div></div>
      <div class="stat-card"><div class="num">{{ s.characters }}</div><div class="label">角色数</div></div>
      <div class="stat-card"><div class="num">{{ s.foreshadow_open }}</div><div class="label">待回收伏笔</div></div>
    </div>

    <t-card v-if="brief.logline || brief.theme" title="创作蓝图" style="margin-bottom:16px">
      <div class="brief-block">
        <div v-if="brief.logline" class="brief-line"><span class="bl-label">一句话</span>{{ brief.logline }}</div>
        <div v-if="brief.theme" class="brief-line"><span class="bl-label">主题</span>{{ brief.theme }}</div>
        <div class="brief-meta muted">
          <span v-if="brief.protagonist">主角：{{ brief.protagonist.slice(0, 60) }}{{ brief.protagonist.length > 60 ? '…' : '' }}</span>
          <span v-if="brief.core_conflict">冲突：{{ brief.core_conflict.slice(0, 60) }}{{ brief.core_conflict.length > 60 ? '…' : '' }}</span>
          <span v-if="brief.chapter_words">单章约 {{ brief.chapter_words }} 字</span>
        </div>
      </div>
    </t-card>

    <t-card title="作品信息" style="margin-bottom:16px">
      <template #actions>
        <t-button size="small" variant="outline" @click="editOpen = true">编辑</t-button>
      </template>
      <t-descriptions :column="2" bordered>
        <t-descriptions-item label="书名">{{ project.title }}</t-descriptions-item>
        <t-descriptions-item label="类型">{{ project.genre || '未分类' }}</t-descriptions-item>
        <t-descriptions-item label="风格">{{ project.style || '—' }}</t-descriptions-item>
        <t-descriptions-item label="目标字数">{{ (project.target_words/10000).toFixed(1) }} 万字</t-descriptions-item>
        <t-descriptions-item label="核心创意" :span="2">{{ project.premise || '—' }}</t-descriptions-item>
      </t-descriptions>
    </t-card>

    <t-card v-if="styleProfile.style_summary" title="文风档案" style="margin-bottom:16px">
      <div>{{ styleProfile.style_summary }}</div>
      <div class="brief-meta muted">
        <span v-if="styleProfile.pov">视角：{{ styleProfile.pov }}</span>
        <span v-if="styleProfile.pacing">节奏：{{ styleProfile.pacing }}</span>
        <span v-if="styleProfile.tone">基调：{{ styleProfile.tone }}</span>
        <span v-if="styleProfile.dialogue">对话：{{ String(styleProfile.dialogue).slice(0, 40) }}</span>
      </div>
    </t-card>

    <t-alert v-if="importStatus.needs_resume" theme="warning" style="margin-bottom:16px"
      :message="`导入分析未完成（关键章 ${importStatus.deep_done}/${importStatus.deep}），可继续生成流程图数据。`" />

    <t-card title="下一步">
      <div class="toolbar">
        <t-button v-if="importStatus.needs_resume" theme="primary" @click="goImportAnalyze">
          <t-icon name="play-circle" /> 继续导入分析
        </t-button>
        <t-button v-if="brief.source==='imported'" theme="primary" :variant="importStatus.needs_resume ? 'outline' : 'base'" @click="imitateOpen=true">
          <t-icon name="file-copy" /> 一键仿写
        </t-button>
        <t-button theme="primary" variant="outline" @click="$router.push(`/project/${pid}/outline`)">
          <t-icon name="edit" /> 去写作
        </t-button>
        <t-button variant="outline" @click="$router.push(`/project/${pid}/plot`)">剧情流程图</t-button>
        <t-button variant="outline" @click="$router.push(`/project/${pid}/world`)">完善世界观</t-button>
        <t-button variant="outline" @click="$router.push(`/project/${pid}/characters`)">管理角色</t-button>
      </div>
      <div class="muted" v-if="!s.chapters">大纲还没有章节，先去「大纲」页生成或添加章节。</div>
      <div class="muted" v-if="!s.characters" style="margin-top:8px">
        还没有角色，
        <t-link theme="primary" @click="$router.push(`/project/${pid}/characters/design`)">对话式生成角色</t-link>
      </div>
    </t-card>

    <t-dialog
      v-model:visible="imitateOpen"
      :header="imitateUi.running ? '仿写进行中' : '一键仿写'"
      width="640px"
      :confirm-btn="imitateUi.running ? null : { content: '开始仿写', loading: imitating }"
      :cancel-btn="imitateUi.running ? { content: '收起（后台继续）' } : true"
      :close-on-overlay-click="!imitateUi.running"
      @confirm="doImitate"
    >
      <ImitateSetupPanel
        v-if="imitateUi.running"
        :running="imitateUi.running"
        :pct="imitateUi.pct"
        :status="imitateUi.status"
        :phase="imitateUi.phase"
        :err="imitateUi.err"
        :items="imitateItems"
      />
      <template v-else>
        <t-form label-width="88px">
          <t-form-item label="新书名">
            <t-input v-model="imitateForm.title" :placeholder="(project.title || '') + '·仿写'" />
          </t-form-item>
          <t-form-item label="新故事创意" required>
            <t-textarea v-model="imitateForm.premise" placeholder="必填：原创故事核心。只仿文风，不抄原书人物与情节。"
              :autosize="{minRows:3}" />
          </t-form-item>
          <t-form-item label="写作速度">
            <t-radio-group v-model="imitateForm.mode">
              <t-radio value="draft_only">快速（仅初稿，推荐）</t-radio>
              <t-radio value="full">标准（含审校修订，较慢）</t-radio>
            </t-radio-group>
          </t-form-item>
        </t-form>
        <div class="muted">仅继承文风与章节数量，自动生成原创角色，不复制原书设定。</div>
      </template>
    </t-dialog>

    <t-dialog v-model:visible="editOpen" header="编辑作品信息" :on-confirm="saveEdit">
      <t-form :data="edit" label-width="80px">
        <t-form-item label="书名"><t-input v-model="edit.title" /></t-form-item>
        <t-form-item label="类型"><t-input v-model="edit.genre" /></t-form-item>
        <t-form-item label="风格"><t-input v-model="edit.style" /></t-form-item>
        <t-form-item label="核心创意"><t-textarea v-model="edit.premise" :autosize="{minRows:3}" /></t-form-item>
        <t-form-item label="目标字数"><t-input-number v-model="edit.target_words" :min="10000" :step="10000" theme="column" /></t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import ImitateSetupPanel from '../components/ImitateSetupPanel.vue'
import { useImitateStream } from '../composables/useImitateStream'

const props = defineProps({ project: Object })
const emit = defineEmits(['refresh'])
const route = useRoute()
const router = useRouter()
const pid = computed(() => route.params.pid)
const s = computed(() => props.project.stats || {})
const brief = computed(() => {
  const b = props.project?.brief
  return b && typeof b === 'object' ? b : {}
})
const styleProfile = computed(() => {
  const p = brief.value.style_profile
  return p && typeof p === 'object' ? p : {}
})
const editOpen = ref(false)
const edit = ref({})
const imitateOpen = ref(false)
const imitateForm = ref({ title: '', premise: '', mode: 'draft_only' })
const imitating = ref(false)
const { ui: imitateUi, items: imitateItems, start: startImitate } = useImitateStream()
const importStatus = ref({ needs_resume: false, deep: 0, deep_done: 0 })

async function loadImportStatus() {
  if (brief.value.source !== 'imported') {
    importStatus.value = { needs_resume: false, deep: 0, deep_done: 0 }
    return
  }
  try {
    importStatus.value = await api.get(`/api/projects/${pid.value}/import/status`)
  } catch {
    importStatus.value = { needs_resume: false, deep: 0, deep_done: 0 }
  }
}

function goImportAnalyze() {
  router.push(`/import?pid=${pid.value}`)
}

watch(() => props.project, (p) => {
  edit.value = { title: p.title, genre: p.genre, style: p.style, premise: p.premise, target_words: p.target_words }
}, { immediate: true, deep: true })

watch(() => [pid.value, brief.value.source], loadImportStatus, { immediate: true })

onMounted(loadImportStatus)

async function saveEdit() {
  try {
    await api.put(`/api/projects/${pid.value}`, edit.value)
    MessagePlugin.success('已保存')
    editOpen.value = false
    emit('refresh')
  } catch (e) { MessagePlugin.error(e.message) }
}

function doImitate() {
  if (imitating.value || imitateUi.running) return false
  if (!imitateForm.value.premise.trim()) {
    MessagePlugin.warning('请填写新故事创意')
    return false
  }
  imitating.value = true
  startImitate(
    pid.value,
    {
      title: imitateForm.value.title,
      premise: imitateForm.value.premise,
      mode: imitateForm.value.mode,
    },
    {
      onDone: (r) => {
        imitating.value = false
        imitateOpen.value = false
        if (r.book && !r.book.ok) {
          MessagePlugin.warning(r.book.error || '已建书，未能自动开写')
        } else {
          MessagePlugin.success('仿写项目已就绪，已开始整本创作')
        }
        router.push(`/project/${r.id}/book`)
      },
      onError: (e) => {
        imitating.value = false
        MessagePlugin.error(e.message)
      },
    },
  )
  return false
}
</script>

<style scoped>
.brief-block { display: flex; flex-direction: column; gap: 8px; }
.brief-line { font-size: 14px; line-height: 1.6; }
.bl-label { display: inline-block; min-width: 52px; margin-right: 8px; color: var(--td-text-color-secondary); font-size: 12px; }
.brief-meta { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; margin-top: 4px; }
</style>
