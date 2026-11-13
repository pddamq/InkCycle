<template>
  <div class="dashboard page">
    <div class="dash-head">
      <h2>一致性看板</h2>
      <div class="spacer"></div>
      <t-button size="small" variant="outline" :loading="loading" @click="load">
        <t-icon name="refresh" /> 刷新
      </t-button>
      <t-button size="small" variant="outline" :loading="indexing" @click="reindex">
        重建语义索引
      </t-button>
    </div>

    <t-loading :loading="loading">
      <div v-if="data.summary" class="stat-row">
        <t-card v-for="s in statCards" :key="s.key" class="stat-card">
          <div class="stat-num" :class="s.warn ? 'warn' : ''">{{ data.summary[s.key] ?? 0 }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </t-card>
      </div>

      <t-card title="未回收伏笔" class="sec">
        <div v-if="data.open_foreshadowing?.length" class="item-list">
          <div v-for="f in data.open_foreshadowing" :key="f.id" class="item-row">
            <span>{{ f.description }}</span>
            <t-button size="small" variant="text" @click="goForeshadow">查看</t-button>
          </div>
        </div>
        <t-empty v-else size="small" description="暂无待回收伏笔" />
      </t-card>

      <t-card title="低分章节（审校 &lt; 75）" class="sec">
        <div v-if="data.low_score_chapters?.length" class="item-list">
          <div v-for="c in data.low_score_chapters" :key="c.chapter_id" class="item-row">
            <t-tag size="small" theme="warning">{{ c.score }}分</t-tag>
            <span>{{ c.title }}</span>
            <t-button size="small" variant="text" @click="goChapter(c.chapter_id)">去改</t-button>
          </div>
        </div>
        <t-empty v-else size="small" description="暂无低分章节" />
      </t-card>

      <t-card title="文风漂移检测" class="sec">
        <p class="muted sec-tip">相对首章基线，对比句长、对话密度等信号。</p>
        <div v-if="data.style_drift?.chapters?.length" class="item-list">
          <div v-for="c in data.style_drift.chapters" :key="c.chapter_id" class="item-row">
            <t-tag size="small" :theme="driftTheme(c.drift)" variant="light">{{ c.drift }}</t-tag>
            <span>{{ c.title }}</span>
            <span class="muted">偏移 {{ c.score }}</span>
            <t-button size="small" variant="text" @click="goChapter(c.chapter_id)">查看</t-button>
          </div>
        </div>
        <t-empty v-else size="small" description="尚无足够正文做漂移分析" />
      </t-card>

      <t-card title="分支剧情" class="sec">
        <div class="branch-bar">
          <t-input v-model="branchName" placeholder="新分支名，如 BE线" style="max-width:200px" />
          <t-button size="small" theme="primary" :loading="branching" @click="createBranch">创建分支</t-button>
        </div>
        <div v-if="branches.branches?.length" class="item-list">
          <div v-for="b in branches.branches" :key="b.id" class="item-row">
            <span>{{ b.title }}</span>
            <t-tag size="small" variant="outline">{{ b.branch_name }}</t-tag>
            <t-button size="small" variant="text" @click="$router.push(`/project/${b.id}`)">打开</t-button>
          </div>
        </div>
        <t-empty v-else size="small" description="尚无分支" />
      </t-card>
    </t-loading>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

const route = useRoute()
const router = useRouter()
const pid = computed(() => route.params.pid)
const loading = ref(false)
const indexing = ref(false)
const branching = ref(false)
const data = ref({ summary: {}, open_foreshadowing: [], low_score_chapters: [], style_drift: { chapters: [] } })
const branches = ref({ branches: [] })
const branchName = ref('')

const statCards = [
  { key: 'open_foreshadowing', label: '待回收伏笔', warn: true },
  { key: 'low_score', label: '低分章节', warn: true },
  { key: 'incomplete', label: '未完成章节' },
  { key: 'style_drift_high', label: '文风高漂移', warn: true },
]

function driftTheme(d) {
  return d === 'high' ? 'danger' : d === 'medium' ? 'warning' : 'success'
}

async function load() {
  loading.value = true
  try {
    data.value = await api.get(`/api/projects/${pid.value}/dashboard`)
    branches.value = await api.get(`/api/projects/${pid.value}/branches`)
  } catch (e) {
    MessagePlugin.error(e.message)
  } finally {
    loading.value = false
  }
}

async function reindex() {
  indexing.value = true
  try {
    const r = await api.post(`/api/projects/${pid.value}/rag/index`, {})
    MessagePlugin.success(`已索引 ${r.chunks} 个文本块`)
  } catch (e) {
    MessagePlugin.error(e.message)
  } finally {
    indexing.value = false
  }
}

async function createBranch() {
  if (!branchName.value.trim()) { MessagePlugin.warning('请输入分支名'); return }
  branching.value = true
  try {
    const r = await api.post(`/api/projects/${pid.value}/branch`, { branch_name: branchName.value.trim() })
    MessagePlugin.success('分支已创建')
    router.push(`/project/${r.project_id}`)
  } catch (e) {
    MessagePlugin.error(e.message)
  } finally {
    branching.value = false
  }
}

function goChapter(chid) {
  router.push(`/project/${pid.value}/chapter/${chid}`)
}

function goForeshadow() {
  router.push(`/project/${pid.value}/foreshadow`)
}

onMounted(load)
</script>

<style scoped>
.dashboard { padding: 20px 24px; max-width: 960px; }
.dash-head { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.dash-head h2 { margin: 0; font-size: 20px; }
.spacer { flex: 1; }
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }
.stat-card { text-align: center; }
.stat-num { font-size: 28px; font-weight: 700; color: var(--td-brand-color); }
.stat-num.warn { color: var(--td-warning-color); }
.stat-label { font-size: 12px; color: var(--td-text-color-secondary); margin-top: 4px; }
.sec { margin-bottom: 16px; }
.sec-tip { font-size: 12px; margin-bottom: 12px; }
.item-list { display: flex; flex-direction: column; gap: 8px; }
.item-row { display: flex; align-items: center; gap: 10px; font-size: 14px; padding: 6px 0; border-bottom: 1px solid var(--td-component-stroke); }
.branch-bar { display: flex; gap: 10px; margin-bottom: 12px; align-items: center; }
</style>
