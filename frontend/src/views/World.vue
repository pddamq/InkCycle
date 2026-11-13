<template>
  <div class="page">
    <div class="toolbar">
      <h1 class="page-title" style="margin:0">世界观设定</h1>
      <div class="spacer"></div>
      <t-button variant="outline" @click="addSection"><t-icon name="add" /> 添加小节</t-button>
      <t-button theme="primary" :loading="saving" @click="save"><t-icon name="save" /> 保存全部</t-button>
    </div>
    <div class="muted" style="margin-bottom:16px">设定会作为写作与审校的上下文。小节可自由增删，标题即维度名。</div>

    <t-loading :loading="loading" show-overlay>
      <div v-for="(sec, i) in sections" :key="i" class="sec-card">
        <div class="sec-head">
          <t-input v-model="sec.title" placeholder="小节标题，如：力量体系" class="sec-title" />
          <t-button variant="text" theme="danger" @click="sections.splice(i,1)">
            <t-icon name="delete" />
          </t-button>
        </div>
        <t-textarea v-model="sec.content" placeholder="小节内容…" :autosize="{ minRows: 3, maxRows: 10 }" />
      </div>
      <t-empty v-if="!sections.length && !loading" description="暂无设定，点「添加小节」或用向导生成" />
    </t-loading>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'

const route = useRoute()
const pid = computed(() => route.params.pid)
const sections = ref([])
const loading = ref(false)
const saving = ref(false)

function addSection() { sections.value.push({ title: '', content: '' }) }

async function load() {
  loading.value = true
  try { sections.value = await api.get(`/api/projects/${pid.value}/world`) }
  catch (e) { MessagePlugin.error(e.message) }
  finally { loading.value = false }
}

async function save() {
  saving.value = true
  try {
    await api.put(`/api/projects/${pid.value}/world`, { sections: sections.value.filter(s => s.title || s.content) })
    MessagePlugin.success('已保存')
  } catch (e) { MessagePlugin.error(e.message) }
  finally { saving.value = false }
}

onMounted(load)
</script>

<style scoped>
.sec-card { background: var(--td-bg-color-container); border: 1px solid var(--td-component-stroke); border-radius: var(--td-radius-medium); padding: 12px 16px; margin-bottom: 12px; }
.sec-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.sec-title { flex: 1; }
</style>
