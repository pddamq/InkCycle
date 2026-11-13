<template>
  <div class="page page-narrow">
    <PageTopbar title="设置" icon="setting" back-to="/" back-label="返回书架" />

    <t-card title="模型接口（OpenAI 兼容）" style="margin-bottom:16px">
      <t-form :data="cfg" label-width="140px">
        <t-form-item label="API Base URL">
          <t-input v-model="cfg.base_url" placeholder="https://api.openai.com/v1" />
        </t-form-item>
        <t-form-item label="API Key">
          <t-input v-model="cfg.api_key" type="password" :placeholder="cfg.has_key ? ('已保存 ' + cfg.api_key_masked + '（留空则不修改）') : 'sk-...'" />
        </t-form-item>
        <t-form-item label="模型">
          <div class="model-row">
            <t-select
              v-model="cfg.model"
              filterable
              allow-input
              :loading="fetchingModels"
              :options="modelOptions"
              placeholder="gpt-4o-mini / deepseek-chat / glm-4-flash …"
              style="flex:1"
            />
            <t-button variant="outline" :loading="fetchingModels" @click="fetchModels">拉取模型</t-button>
          </div>
        </t-form-item>
        <t-form-item label="Temperature">
          <t-slider v-model="temperature" :min="0" :max="2" :step="0.1" style="width:280px" />
          <span class="muted" style="margin-left:12px">{{ temperature }}</span>
        </t-form-item>
        <t-form-item label="Max Tokens">
          <t-input-number v-model="maxTokens" :min="256" :max="32768" :step="256" theme="column" />
        </t-form-item>
        <t-form-item>
          <t-button theme="primary" :loading="saving" @click="save"><t-icon name="save" /> 保存</t-button>
          <t-button variant="outline" style="margin-left:12px" :loading="testing" @click="test">测试连接</t-button>
        </t-form-item>
      </t-form>
    </t-card>

    <t-card title="备份与恢复" style="margin-bottom:16px">
      <p class="muted" style="margin-bottom:12px">导出完整数据库备份，或上传 zip 恢复（全库或单项目）。</p>
      <t-button variant="outline" @click="exportBackup"><t-icon name="download" /> 导出全库备份</t-button>
      <input ref="fileInput" type="file" accept=".zip" hidden @change="importBackup" />
      <t-button variant="outline" style="margin-left:12px" @click="fileInput?.click()">
        <t-icon name="upload" /> 导入备份
      </t-button>
    </t-card>

    <t-card title="窗口行为" style="margin-bottom:16px">
      <t-form :data="cfg" label-width="140px">
        <t-form-item label="点击关闭时">
          <t-radio-group v-model="cfg.close_action">
            <t-radio value="ask">每次询问（最小化 / 退出）</t-radio>
            <t-radio value="minimize">直接最小化</t-radio>
            <t-radio value="exit">直接退出</t-radio>
          </t-radio-group>
        </t-form-item>
        <t-form-item>
          <span class="muted">最小化后整本创作等后台任务仍会继续；可在设置中改回「每次询问」。</span>
        </t-form-item>
        <t-form-item>
          <t-button theme="primary" :loading="saving" @click="save"><t-icon name="save" /> 保存</t-button>
        </t-form-item>
      </t-form>
    </t-card>

    <t-card title="Agent 参数">
      <t-form :data="cfg" label-width="140px">
        <t-form-item label="每章目标字数">
          <t-input-number v-model="chapterWords" :min="500" :max="20000" :step="100" theme="column" />
        </t-form-item>
        <t-form-item label="自动流程最大轮数">
          <t-input-number v-model="agentRounds" :min="1" :max="6" theme="column" />
          <span class="muted" style="margin-left:12px">初稿→审校→修订 的循环上限</span>
        </t-form-item>
        <t-form-item label="审校达标分数">
          <t-slider v-model="threshold" :min="50" :max="100" :step="1" style="width:280px" />
          <span class="muted" style="margin-left:12px">{{ threshold }} 分及以上即停止循环</span>
        </t-form-item>
        <t-form-item label="自动生成章节摘要">
          <t-switch v-model="autoSummary" />
          <span class="muted" style="margin-left:12px">摘要用于后续章节的"前文脉络"上下文</span>
        </t-form-item>
        <t-form-item>
          <t-button theme="primary" :loading="saving" @click="save"><t-icon name="save" /> 保存</t-button>
        </t-form-item>
      </t-form>
    </t-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { api } from '../api'
import PageTopbar from '../components/PageTopbar.vue'

const cfg = ref({})
const fileInput = ref(null)
const saving = ref(false)
const testing = ref(false)
const fetchingModels = ref(false)
const modelOptions = ref([])

const autoSummary = computed({ get: () => cfg.value.auto_summary === '1', set: v => cfg.value.auto_summary = v ? '1' : '0' })
const temperature = computed({ get: () => parseFloat(cfg.value.temperature || '0.8'), set: v => cfg.value.temperature = String(v) })
const maxTokens = computed({ get: () => parseInt(cfg.value.max_tokens || '4096'), set: v => cfg.value.max_tokens = String(v) })
const chapterWords = computed({ get: () => parseInt(cfg.value.chapter_words || '2500'), set: v => cfg.value.chapter_words = String(v) })
const agentRounds = computed({ get: () => parseInt(cfg.value.agent_rounds || '2'), set: v => cfg.value.agent_rounds = String(v) })
const threshold = computed({ get: () => parseInt(cfg.value.review_threshold || '85'), set: v => cfg.value.review_threshold = String(v) })

async function load() {
  try {
    cfg.value = await api.get('/api/config')
    if (!cfg.value.close_action) cfg.value.close_action = 'ask'
    if (cfg.value.model) {
      modelOptions.value = [{ label: cfg.value.model, value: cfg.value.model }]
    }
  }
  catch (e) { MessagePlugin.error(e.message) }
}

async function fetchModels() {
  fetchingModels.value = true
  try {
    const body = {}
    if (cfg.value.base_url) body.base_url = cfg.value.base_url
    if (cfg.value.api_key) body.api_key = cfg.value.api_key
    const r = await api.post('/api/config/models', body)
    if (!r.ok) {
      MessagePlugin.error(r.message || '拉取失败')
      return
    }
    modelOptions.value = (r.models || []).map(id => ({ label: id, value: id }))
    if (!modelOptions.value.length) MessagePlugin.warning('接口未返回模型列表')
    else MessagePlugin.success(`已拉取 ${modelOptions.value.length} 个模型`)
  } catch (e) { MessagePlugin.error(e.message) }
  finally { fetchingModels.value = false }
}

async function save() {
  saving.value = true
  try {
    const body = { ...cfg.value }
    delete body.api_key_masked; delete body.has_key
    if (!body.api_key) delete body.api_key  // 留空不覆盖
    await api.put('/api/config', body)
    MessagePlugin.success('已保存')
    load()
  } catch (e) { MessagePlugin.error(e.message) }
  finally { saving.value = false }
}

async function exportBackup() {
  try {
    const res = await fetch('/api/backup/export')
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'novel-agent-backup.zip'
    a.click()
    MessagePlugin.success('备份已开始下载')
  } catch (e) { MessagePlugin.error(e.message) }
}

async function importBackup(e) {
  const file = e.target.files?.[0]
  if (!file) return
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/api/backup/import', { method: 'POST', body: fd })
    const r = await res.json()
    if (r.ok) {
      MessagePlugin.success(r.type === 'project' ? `项目已恢复 #${r.project_id}` : '全库已恢复，请刷新')
      if (r.project_id) window.location.href = `/project/${r.project_id}`
      else window.location.href = '/'
    } else MessagePlugin.error(r.error || '恢复失败')
  } catch (err) { MessagePlugin.error(err.message) }
  e.target.value = ''
}

async function test() {
  testing.value = true
  try {
    const r = await api.post('/api/config/test', {})
    if (r.ok) MessagePlugin.success(r.message)
    else MessagePlugin.error(r.message)
  } catch (e) { MessagePlugin.error(e.message) }
  finally { testing.value = false }
}

onMounted(load)
</script>

<style scoped>
.model-row {
  display: flex;
  gap: 8px;
  width: 100%;
  max-width: 520px;
}
</style>
