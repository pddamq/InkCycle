<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin:0">时间线</h1>
      <div class="spacer"></div>
      <t-button theme="primary" @click="openNew"><t-icon name="add" /> 添加事件</t-button>
    </div>
    <div class="muted" style="margin-bottom:16px">记录剧情时序，审校时用于核对时间一致性。</div>

    <t-loading :loading="loading" show-overlay>
      <t-timeline v-if="events.length">
        <t-timeline-item v-for="e in events" :key="e.id" :label="e.time_label || '—'">
          <div class="ev-card">
            <div class="ev-desc">{{ e.description }}</div>
            <div class="ev-foot muted">
              <span v-if="e.chapter_title">《{{ e.chapter_title }}》</span>
              <div class="spacer"></div>
              <t-button size="small" variant="text" @click="openEdit(e)"><t-icon name="edit" /></t-button>
              <t-popconfirm content="删除？" @confirm="remove(e.id)">
                <t-button size="small" variant="text" theme="danger"><t-icon name="delete" /></t-button>
              </t-popconfirm>
            </div>
          </div>
        </t-timeline-item>
      </t-timeline>
      <t-empty v-else-if="!loading" description="暂无时间线事件" />
    </t-loading>

    <t-dialog v-model:visible="dlg" :header="editing.id?'编辑事件':'添加事件'" :on-confirm="save">
      <t-form :data="editing" label-width="90px">
        <t-form-item label="时间标签"><t-input v-model="editing.time_label" placeholder="如：第1夜 / 三年前 / 案发当日" /></t-form-item>
        <t-form-item label="事件"><t-textarea v-model="editing.description" :autosize="{minRows:2}" /></t-form-item>
        <t-form-item label="关联章节">
          <t-select v-model="editing.chapter_id" clearable>
            <t-option v-for="c in chapters" :key="c.id" :value="c.id" :label="c.title" />
          </t-select>
        </t-form-item>
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
const events = ref([])
const chapters = ref([])
const loading = ref(false)
const dlg = ref(false)
const editing = ref({})

async function load() {
  loading.value = true
  try {
    events.value = await api.get(`/api/projects/${pid.value}/timeline`)
    const outline = await api.get(`/api/projects/${pid.value}/outline`)
    chapters.value = outline.flatMap(v => v.chapters)
  } catch (e) { MessagePlugin.error(e.message) }
  finally { loading.value = false }
}
function openNew() { editing.value = { time_label: '', description: '' }; dlg.value = true }
function openEdit(e) { editing.value = { ...e }; dlg.value = true }
async function save() {
  if (!editing.value.description?.trim()) return MessagePlugin.warning('请填写事件')
  try {
    if (editing.value.id) await api.put(`/api/projects/${pid.value}/timeline/${editing.value.id}`, editing.value)
    else await api.post(`/api/projects/${pid.value}/timeline`, editing.value)
    MessagePlugin.success('已保存'); dlg.value = false; load()
  } catch (e) { MessagePlugin.error(e.message) }
}
async function remove(id) {
  try { await api.del(`/api/projects/${pid.value}/timeline/${id}`); load() }
  catch (e) { MessagePlugin.error(e.message) }
}
onMounted(load)
</script>

<style scoped>
.ev-card { background: var(--td-bg-color-container); border: 1px solid var(--td-component-stroke); border-radius: var(--td-radius-medium); padding: 10px 14px; }
.ev-desc { font-size: 14px; }
.ev-foot { display: flex; align-items: center; gap: 8px; margin-top: 6px; font-size: 12px; }
</style>
