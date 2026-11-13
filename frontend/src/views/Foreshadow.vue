<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin:0">伏笔台账</h1>
      <div class="spacer"></div>
      <t-button theme="primary" @click="openNew"><t-icon name="add" /> 登记伏笔</t-button>
    </div>
    <div class="muted" style="margin-bottom:16px">伏笔会注入写作与审校上下文，帮助 Agent 记住"该埋的"和"该收的"。</div>

    <t-table row-key="id" :data="rows" :columns="columns" :loading="loading" bordered size="small">
      <template #status="{ row }">
        <t-tag size="small" :theme="row.status==='paid'?'success':'warning'" variant="light">
          {{ row.status==='paid' ? '已回收' : '待回收' }}
        </t-tag>
      </template>
      <template #planted="{ row }">{{ row.planted_title || '—' }}</template>
      <template #payoff="{ row }">{{ row.payoff_title || '—' }}</template>
      <template #op="{ row }">
        <t-button size="small" variant="text" @click="openEdit(row)"><t-icon name="edit" /></t-button>
        <t-popconfirm content="删除？" @confirm="remove(row.id)">
          <t-button size="small" variant="text" theme="danger"><t-icon name="delete" /></t-button>
        </t-popconfirm>
      </template>
    </t-table>

    <t-dialog v-model:visible="dlg" :header="editing.id?'编辑伏笔':'登记伏笔'" width="560px" :on-confirm="save">
      <t-form :data="editing" label-width="90px">
        <t-form-item label="描述"><t-textarea v-model="editing.description" :autosize="{minRows:2}" placeholder="这个伏笔是什么" /></t-form-item>
        <t-form-item label="埋设章节">
          <t-select v-model="editing.planted_chapter_id" clearable placeholder="（可选）">
            <t-option v-for="c in chapters" :key="c.id" :value="c.id" :label="c.title" />
          </t-select>
        </t-form-item>
        <t-form-item label="状态">
          <t-radio-group v-model="editing.status">
            <t-radio value="open">待回收</t-radio>
            <t-radio value="paid">已回收</t-radio>
          </t-radio-group>
        </t-form-item>
        <t-form-item label="回收章节" v-if="editing.status==='paid'">
          <t-select v-model="editing.payoff_chapter_id" clearable>
            <t-option v-for="c in chapters" :key="c.id" :value="c.id" :label="c.title" />
          </t-select>
        </t-form-item>
        <t-form-item label="备注"><t-input v-model="editing.note" /></t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

const route = useRoute()
const pid = computed(() => route.params.pid)
const rows = ref([])
const chapters = ref([])
const loading = ref(false)
const dlg = ref(false)
const editing = ref({})
const columns = [
  { colKey: 'description', title: '伏笔描述', ellipsis: true },
  { colKey: 'planted', title: '埋设于', width: 140 },
  { colKey: 'status', title: '状态', width: 90 },
  { colKey: 'payoff', title: '回收于', width: 140 },
  { colKey: 'note', title: '备注', width: 140, ellipsis: true },
  { colKey: 'op', title: '操作', width: 90 },
]

async function load() {
  loading.value = true
  try {
    rows.value = await api.get(`/api/projects/${pid.value}/foreshadow`)
    const outline = await api.get(`/api/projects/${pid.value}/outline`)
    chapters.value = outline.flatMap(v => v.chapters)
  } catch (e) { MessagePlugin.error(e.message) }
  finally { loading.value = false }
}
function openNew() { editing.value = { description: '', status: 'open', note: '' }; dlg.value = true }
function openEdit(r) { editing.value = { ...r }; dlg.value = true }
async function save() {
  if (!editing.value.description?.trim()) return MessagePlugin.warning('请填写描述')
  try {
    if (editing.value.id) await api.put(`/api/projects/${pid.value}/foreshadow/${editing.value.id}`, editing.value)
    else await api.post(`/api/projects/${pid.value}/foreshadow`, editing.value)
    MessagePlugin.success('已保存'); dlg.value = false; load()
  } catch (e) { MessagePlugin.error(e.message) }
}
async function remove(id) {
  try { await api.del(`/api/projects/${pid.value}/foreshadow/${id}`); load() }
  catch (e) { MessagePlugin.error(e.message) }
}
onMounted(load)
</script>
