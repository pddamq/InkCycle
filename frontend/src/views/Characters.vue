<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin:0">角色</h1>
      <div class="spacer"></div>
      <t-button theme="primary" @click="$router.push(`/project/${pid}/characters/design`)">
        <t-icon name="chat-bubble" /> 对话式生成
      </t-button>
      <t-popconfirm v-if="!chars.length" content="跳过对话，直接根据蓝图一键生成角色？" @confirm="generate(false)">
        <t-button variant="outline" :disabled="gen.active"><t-icon name="magic" /> 快速生成</t-button>
      </t-popconfirm>
      <t-popconfirm v-else content="将删除现有角色并重新生成，确定？" @confirm="generate(true)">
        <t-button variant="outline" :disabled="gen.active"><t-icon name="magic" /> 快速重新生成</t-button>
      </t-popconfirm>
      <t-button theme="primary" variant="outline" @click="openNew"><t-icon name="add" /> 新增角色</t-button>
    </div>

    <GeneratePanel
      :active="gen.active"
      title="快速生成角色"
      :status="gen.status"
      :items="gen.items"
    />

    <t-loading :loading="loading && !gen.active" show-overlay>
      <div v-if="chars.length" class="card-list">
        <t-card v-for="c in chars" :key="c.id" hover-shadow>
          <template #title>
            <div class="ch-head">
              <t-avatar size="small">{{ (c.name||'?').slice(0,1) }}</t-avatar>
              <span class="ch-name">{{ c.name }}</span>
              <t-tag size="small" variant="light" theme="primary">{{ c.role || '角色' }}</t-tag>
            </div>
          </template>
          <template #actions>
            <t-button size="small" variant="text" @click="openEdit(c)"><t-icon name="edit" /></t-button>
            <t-popconfirm content="删除该角色？" @confirm="remove(c.id)">
              <t-button size="small" variant="text" theme="danger"><t-icon name="delete" /></t-button>
            </t-popconfirm>
          </template>
          <div class="ch-profile">
            <div v-for="(v,k) in c.profile" :key="k" class="pf-row" v-show="v">
              <span class="pf-key">{{ labelOf(k) }}</span>
              <span class="pf-val">{{ v }}</span>
            </div>
            <div v-if="!hasProfile(c)" class="muted">（暂无档案）</div>
          </div>
        </t-card>
      </div>
      <t-empty v-else-if="!loading && !gen.active" description="还没有角色">
        <template #action>
          <t-button theme="primary" @click="$router.push(`/project/${pid}/characters/design`)">
            <t-icon name="chat-bubble" /> 对话式生成
          </t-button>
          <t-button variant="outline" style="margin-left:8px" @click="generate(false)">快速生成</t-button>
          <t-button variant="outline" style="margin-left:8px" @click="openNew">手动新增</t-button>
        </template>
      </t-empty>
    </t-loading>

    <t-dialog v-model:visible="autoDlg" header="创建角色" :footer="false" width="440px">
      <p>本书还没有角色。推荐用<strong>对话式生成</strong>和 AI 聊清楚人物后再出卡；也可以快速一键生成。</p>
      <div class="toolbar" style="margin-top:20px">
        <t-checkbox v-model="autoDismiss">不再提示</t-checkbox>
        <div class="spacer"></div>
        <t-button variant="outline" @click="dismissAuto">稍后再说</t-button>
        <t-button theme="primary" @click="goDesign">开始对话</t-button>
      </div>
    </t-dialog>

    <t-dialog v-model:visible="dlg" :header="editing.id ? '编辑角色' : '新增角色'" width="640px" :on-confirm="save">
      <t-form :data="editing" label-width="80px">
        <t-form-item label="姓名"><t-input v-model="editing.name" /></t-form-item>
        <t-form-item label="定位">
          <t-select v-model="editing.role" filterable allow-input placeholder="主角/女主/对手/导师…">
            <t-option v-for="r in roles" :key="r" :value="r" :label="r" />
          </t-select>
        </t-form-item>
        <t-form-item v-for="f in profileFields" :key="f.key" :label="f.label">
          <t-textarea v-model="editing.profile[f.key]" :autosize="{minRows:1,maxRows:4}" :placeholder="f.ph" />
        </t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import GeneratePanel from '../components/GeneratePanel.vue'
import { useGenerateStream } from '../composables/useGenerateStream'
import { hydrateGenerationSnapshot } from '../composables/generationSession'

const route = useRoute()
const router = useRouter()
const pid = computed(() => route.params.pid)
const chars = ref([])
const loading = ref(false)
const gen = useGenerateStream(`chars-quick:${route.params.pid}`)
const autoDlg = ref(false)
const autoDismiss = ref(false)
const dlg = ref(false)
const roles = ['主角', '女主', '男主', '导师', '对手', '挚友', '反派', '配角']
const profileFields = [
  { key: 'appearance', label: '外貌', ph: '外形特征' },
  { key: 'personality', label: '性格', ph: '性格与行为习惯' },
  { key: 'goal', label: '目标', ph: '核心动机/追求' },
  { key: 'secret', label: '秘密', ph: '隐藏的秘密或软肋' },
  { key: 'relationships', label: '关系', ph: '与其他角色的关系' },
]
const labelMap = Object.fromEntries(profileFields.map(f => [f.key, f.label]))
const editing = ref({ id: null, name: '', role: '', profile: {} })

function dismissKey() { return `chars-auto-dismiss-${pid.value}` }
function labelOf(k) { return labelMap[k] || k }
function hasProfile(c) { return Object.values(c.profile || {}).some(Boolean) }

async function load() {
  loading.value = true
  try { chars.value = await api.get(`/api/projects/${pid.value}/characters`) }
  catch (e) { MessagePlugin.error(e.message) }
  finally { loading.value = false }
}

function maybePromptAuto() {
  if (chars.value.length || sessionStorage.getItem(dismissKey())) return
  autoDlg.value = true
}

function dismissAuto() {
  if (autoDismiss.value) sessionStorage.setItem(dismissKey(), '1')
  autoDlg.value = false
}

function goDesign() {
  if (autoDismiss.value) sessionStorage.setItem(dismissKey(), '1')
  autoDlg.value = false
  router.push(`/project/${pid.value}/characters/design`)
}

function generate(replace) {
  if (gen.active) return
  gen.start(
    `/api/projects/${pid.value}/characters/generate`,
    { replace },
    {
      onEvent(ev) {
        if (ev.type === 'done') {
          MessagePlugin.success(`已生成 ${ev.count || 0} 个角色`)
          gen.clearPersisted()
          load()
        } else if (ev.type === 'error') MessagePlugin.error(ev.message)
      },
      onError(e) { MessagePlugin.error(e.message) },
    },
  )
}

function openNew() { editing.value = { id: null, name: '', role: '', profile: {} }; dlg.value = true }
function openEdit(c) { editing.value = { id: c.id, name: c.name, role: c.role, profile: { ...c.profile } }; dlg.value = true }

async function save() {
  if (!editing.value.name.trim()) return MessagePlugin.warning('请填写姓名')
  try {
    if (editing.value.id) await api.put(`/api/projects/${pid.value}/characters/${editing.value.id}`, editing.value)
    else await api.post(`/api/projects/${pid.value}/characters`, editing.value)
    MessagePlugin.success('已保存'); dlg.value = false; load()
  } catch (e) { MessagePlugin.error(e.message) }
}

async function remove(id) {
  try { await api.del(`/api/projects/${pid.value}/characters/${id}`); MessagePlugin.success('已删除'); load() }
  catch (e) { MessagePlugin.error(e.message) }
}

onMounted(async () => {
  await load()
  const saved = await hydrateGenerationSnapshot(`chars-quick:${route.params.pid}`)
  if (saved?.interrupted) MessagePlugin.info('上次快速生成被中断，进度已恢复，可再次点击生成')
  maybePromptAuto()
})
</script>

<style scoped>
.ch-head { display: flex; align-items: center; gap: 8px; }
.ch-name { font-weight: 600; }
.ch-profile { font-size: 13px; line-height: 1.7; }
.pf-row { display: flex; gap: 8px; margin-bottom: 4px; }
.pf-key { color: var(--td-text-color-secondary); min-width: 42px; flex-shrink: 0; }
.pf-val { color: var(--td-text-color-primary); }
</style>
