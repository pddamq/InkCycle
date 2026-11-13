<template>
  <div class="page">
    <h1 class="page-title">导出</h1>
    <t-card style="max-width:640px">
      <t-form label-width="90px">
        <t-form-item label="格式">
          <t-radio-group v-model="format">
            <t-radio-button value="md">Markdown</t-radio-button>
            <t-radio-button value="txt">纯文本 TXT</t-radio-button>
          </t-radio-group>
        </t-form-item>
        <t-form-item label="范围">
          <t-radio-group v-model="scope">
            <t-radio value="book">整本</t-radio>
            <t-radio value="volume">单卷</t-radio>
            <t-radio value="chapter">单章</t-radio>
          </t-radio-group>
        </t-form-item>
        <t-form-item label="选择卷" v-if="scope==='volume'">
          <t-select v-model="scopeId">
            <t-option v-for="v in volumes" :key="v.id" :value="v.id" :label="v.title" />
          </t-select>
        </t-form-item>
        <t-form-item label="选择章" v-if="scope==='chapter'">
          <t-select v-model="scopeId" filterable>
            <t-option v-for="c in chapters" :key="c.id" :value="c.id" :label="c.title" />
          </t-select>
        </t-form-item>
        <t-form-item>
          <t-button theme="primary" @click="doExport"><t-icon name="download" /> 下载</t-button>
          <t-button variant="outline" style="margin-left:12px" @click="doPreview">预览</t-button>
        </t-form-item>
      </t-form>
      <div class="muted">仅导出已有正文的章节（按当前版本）。</div>
    </t-card>

    <t-dialog v-model:visible="previewOpen" header="导出预览" width="720px" :footer="false">
      <pre class="preview">{{ previewText }}</pre>
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
const format = ref('md')
const scope = ref('book')
const scopeId = ref(null)
const volumes = ref([])
const chapters = ref([])
const previewOpen = ref(false)
const previewText = ref('')

function url() {
  let u = `/api/projects/${pid.value}/export?format=${format.value}&scope=${scope.value}`
  if (scope.value !== 'book' && scopeId.value) u += `&scope_id=${scopeId.value}`
  return u
}

async function load() {
  const outline = await api.get(`/api/projects/${pid.value}/outline`)
  volumes.value = outline
  chapters.value = outline.flatMap(v => v.chapters.map(c => ({ ...c, title: `${v.title} · ${c.title}` })))
}

function doExport() {
  if (scope.value !== 'book' && !scopeId.value) return MessagePlugin.warning('请先选择卷/章')
  window.open(url(), '_blank')
}

async function doPreview() {
  if (scope.value !== 'book' && !scopeId.value) return MessagePlugin.warning('请先选择卷/章')
  try {
    const r = await fetch(url())
    previewText.value = await r.text()
    previewOpen.value = true
  } catch (e) { MessagePlugin.error(e.message) }
}

onMounted(load)
</script>

<style scoped>
.preview { white-space: pre-wrap; font-family: inherit; line-height: 1.8; max-height: 60vh; overflow-y: auto; }
</style>
