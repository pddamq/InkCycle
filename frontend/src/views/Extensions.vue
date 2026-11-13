<template>
  <div class="page">
    <div class="toolbar">
      <t-button variant="text" @click="$router.push('/')"><t-icon name="chevron-left" /> 返回书架</t-button>
      <h1 class="page-title" style="margin:0">扩展中心</h1>
    </div>

    <t-tabs v-model="tab">
      <!-- ===================== Skills ===================== -->
      <t-tab-panel value="skills" label="写作技巧 Skills">
        <div class="panel-pad">
          <div class="toolbar">
            <div class="muted">Skill 是一段可注入提示词的写作方法（SKILL.md）。按阶段（起草/审校/修订）生效。</div>
            <div class="spacer"></div>
            <t-button variant="outline" @click="rescan"><t-icon name="refresh" /> 重新扫描</t-button>
            <t-dropdown :options="installOpts" @click="onInstallMenu">
              <t-button theme="primary"><t-icon name="add" /> 安装 Skill <t-icon name="chevron-down" /></t-button>
            </t-dropdown>
          </div>

          <t-table row-key="id" :data="skills" :columns="skillCols" :loading="loadingSkills" bordered size="small">
            <template #stages="{ row }">
              <t-tag v-for="s in row.stages" :key="s" size="small" variant="light" style="margin-right:4px">{{ stageText(s) }}</t-tag>
            </template>
            <template #enabled="{ row }">
              <t-switch v-model="row.enabled" size="small" @change="(v)=>toggleSkill(row, v)" />
            </template>
            <template #source="{ row }">
              <t-tag size="small" variant="outline">{{ row.source }}</t-tag>
            </template>
            <template #op="{ row }">
              <t-button size="small" variant="text" @click="viewSkill(row)">查看</t-button>
              <t-popconfirm content="卸载该 Skill？" @confirm="uninstallSkill(row.id)">
                <t-button size="small" variant="text" theme="danger">卸载</t-button>
              </t-popconfirm>
            </template>
          </t-table>
        </div>
      </t-tab-panel>

      <!-- ===================== MCP ===================== -->
      <t-tab-panel value="mcp" label="MCP 工具服务器">
        <div class="panel-pad">
          <div class="toolbar">
            <div class="muted">连接 MCP 服务器后，其工具会暴露给写作 Agent 调用（如搜索资料、查设定）。</div>
            <div class="spacer"></div>
            <t-button theme="primary" @click="openServerDlg(null)"><t-icon name="add" /> 添加服务器</t-button>
          </div>

          <t-table row-key="id" :data="servers" :columns="serverCols" :loading="loadingServers" bordered size="small"
            :expanded-row="serverExpanded">
            <template #status="{ row }">
              <t-tag size="small" :theme="statusTheme(row.status)" variant="light">
                <t-icon :name="statusIcon(row.status)" /> {{ statusText(row.status) }}
              </t-tag>
            </template>
            <template #target="{ row }">
              <span class="mono">{{ row.transport === 'stdio' ? (row.command + ' ' + (row.args||[]).join(' ')) : row.url }}</span>
            </template>
            <template #tools="{ row }">
              <t-tag v-if="row.tools?.length" size="small" variant="light" theme="primary">{{ row.tools.length }} 个</t-tag>
              <span v-else class="muted">—</span>
            </template>
            <template #op="{ row }">
              <t-button v-if="row.status!=='connected'" size="small" variant="text" theme="primary" :loading="row._busy" @click="connect(row)">连接</t-button>
              <t-button v-else size="small" variant="text" @click="disconnect(row)">断开</t-button>
              <t-button size="small" variant="text" @click="openServerDlg(row)">编辑</t-button>
              <t-popconfirm content="删除该服务器？" @confirm="removeServer(row.id)">
                <t-button size="small" variant="text" theme="danger">删除</t-button>
              </t-popconfirm>
            </template>
          </t-table>
        </div>
      </t-tab-panel>
    </t-tabs>

    <!-- Skill 内容预览 -->
    <t-dialog v-model:visible="skillViewOpen" :header="`Skill · ${skillView.name||''}`" width="720px" :footer="false">
      <pre class="md-preview">{{ skillView.content }}</pre>
    </t-dialog>

    <!-- 安装 Skill：本地文件夹 -->
    <t-dialog v-model:visible="folderOpen" header="从本地文件夹安装" :on-confirm="installFolder">
      <t-form label-width="90px">
        <t-form-item label="文件夹路径">
          <t-input v-model="folderPath" placeholder="包含 SKILL.md 的文件夹绝对路径" />
        </t-form-item>
      </t-form>
    </t-dialog>

    <!-- 安装 Skill：GitHub -->
    <t-dialog v-model:visible="githubOpen" header="从 GitHub 安装" :on-confirm="installGithub" :confirm-btn="{loading:installing}">
      <t-form label-width="90px">
        <t-form-item label="仓库地址">
          <t-input v-model="githubUrl" placeholder="https://github.com/用户名/仓库名" />
        </t-form-item>
      </t-form>
      <div class="muted">仓库根目录或一级子目录需包含 SKILL.md。将尝试 main / master 分支。</div>
    </t-dialog>

    <!-- 安装 Skill：zip 上传 -->
    <t-dialog v-model:visible="zipOpen" header="上传 zip 安装" :on-confirm="installZip" :confirm-btn="{loading:installing}">
      <t-upload v-model="zipFile" :request-method="uploadMethod" theme="file" accept=".zip" :max="1"
        tips="选择包含 SKILL.md 的 .zip 包" />
    </t-dialog>

    <!-- 添加/编辑 MCP 服务器 -->
    <t-dialog v-model:visible="serverOpen" :header="serverForm.id?'编辑服务器':'添加服务器'" width="600px" :on-confirm="saveServer">
      <t-form :data="serverForm" label-width="90px">
        <t-form-item label="名称"><t-input v-model="serverForm.name" placeholder="如：web-search" /></t-form-item>
        <t-form-item label="传输方式">
          <t-radio-group v-model="serverForm.transport">
            <t-radio value="stdio">stdio（本地命令）</t-radio>
            <t-radio value="http">HTTP（远程 URL）</t-radio>
          </t-radio-group>
        </t-form-item>
        <template v-if="serverForm.transport==='stdio'">
          <t-form-item label="启动命令"><t-input v-model="serverForm.command" placeholder="如：python / npx / node" /></t-form-item>
          <t-form-item label="参数">
            <t-textarea v-model="serverForm.argsText" placeholder="每行一个参数，如：&#10;C:\path\to\server.py&#10;--port&#10;3000" :autosize="{minRows:3}" />
          </t-form-item>
        </template>
        <t-form-item v-else label="服务器 URL"><t-input v-model="serverForm.url" placeholder="https://example.com/mcp" /></t-form-item>
        <t-form-item label="启用"><t-switch v-model="serverForm.enabled" /></t-form-item>
        <t-form-item label="启动时自动连接"><t-switch v-model="serverForm.auto_connect" /></t-form-item>
      </t-form>
    </t-dialog>

    <!-- 测试调用 MCP 工具 -->
    <t-dialog v-model:visible="invokeOpen" :header="`测试工具 · ${invokeTool.name||''}`" width="640px" :on-confirm="doInvoke" :confirm-btn="{loading:invoking}">
      <div class="muted" style="margin-bottom:8px">{{ invokeTool.description }}</div>
      <t-form label-width="70px">
        <t-form-item label="参数 JSON">
          <t-textarea v-model="invokeArgs" :autosize="{minRows:4}" placeholder='{"keyword": "..."}' />
        </t-form-item>
      </t-form>
      <div v-if="invokeResult !== null" class="invoke-result">
        <div class="muted">结果：</div>
        <pre>{{ invokeResult }}</pre>
      </div>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, h, onMounted } from 'vue'
import { MessagePlugin, Button as TButton } from 'tdesign-vue-next'
import { api } from '../api'

const tab = ref('skills')

/* ---------------- Skills ---------------- */
const skills = ref([])
const loadingSkills = ref(false)
const skillCols = [
  { colKey: 'name', title: '名称', width: 160 },
  { colKey: 'description', title: '说明', ellipsis: true },
  { colKey: 'stages', title: '生效阶段', width: 180 },
  { colKey: 'source', title: '来源', width: 110 },
  { colKey: 'enabled', title: '启用', width: 70 },
  { colKey: 'op', title: '操作', width: 120 },
]
const installOpts = [
  { content: '从本地文件夹', value: 'folder' },
  { content: '上传 zip 包', value: 'zip' },
  { content: '从 GitHub 仓库', value: 'github' },
]
function stageText(s) { return { draft:'起草', review:'审校', revise:'修订', wizard:'向导' }[s] || s }

const skillViewOpen = ref(false)
const skillView = ref({})
const folderOpen = ref(false)
const folderPath = ref('')
const githubOpen = ref(false)
const githubUrl = ref('')
const zipOpen = ref(false)
const zipFile = ref([])
const installing = ref(false)

async function loadSkills() {
  loadingSkills.value = true
  try { skills.value = await api.get('/api/skills') }
  catch (e) { MessagePlugin.error(e.message) }
  finally { loadingSkills.value = false }
}
async function rescan() {
  try { await api.post('/api/skills/rescan'); MessagePlugin.success('已重新扫描'); loadSkills() }
  catch (e) { MessagePlugin.error(e.message) }
}
function onInstallMenu(item) {
  const v = item?.value ?? item
  if (v === 'folder') folderOpen.value = true
  else if (v === 'github') githubOpen.value = true
  else if (v === 'zip') { zipFile.value = []; zipOpen.value = true }
}
async function viewSkill(row) {
  try { skillView.value = await api.get(`/api/skills/${row.id}`); skillViewOpen.value = true }
  catch (e) { MessagePlugin.error(e.message) }
}
async function toggleSkill(row, v) {
  try { await api.post(`/api/skills/${row.id}/toggle`, { enabled: v }) }
  catch (e) { MessagePlugin.error(e.message); row.enabled = !v }
}
async function uninstallSkill(id) {
  try { await api.del(`/api/skills/${id}`); MessagePlugin.success('已卸载'); loadSkills() }
  catch (e) { MessagePlugin.error(e.message) }
}
async function installFolder() {
  if (!folderPath.value.trim()) return MessagePlugin.warning('请填写路径')
  try { await api.post('/api/skills/install', { source: 'folder', path: folderPath.value }); MessagePlugin.success('安装成功'); folderOpen.value = false; loadSkills() }
  catch (e) { MessagePlugin.error(e.message) }
}
async function installGithub() {
  if (!githubUrl.value.trim()) return MessagePlugin.warning('请填写仓库地址')
  installing.value = true
  try { await api.post('/api/skills/install', { source: 'github', url: githubUrl.value }); MessagePlugin.success('安装成功'); githubOpen.value = false; loadSkills() }
  catch (e) { MessagePlugin.error(e.message) }
  finally { installing.value = false }
}
// t-upload 自定义上传：拿到 File 后用 FormData 提交
function uploadMethod(file) {
  return new Promise((resolve) => {
    const fd = new FormData()
    fd.append('file', file.raw)
    fetch('/api/skills/install_zip', { method: 'POST', body: fd })
      .then(r => r.json().then(j => r.ok ? resolve({ status: 'success', response: j }) : resolve({ status: 'fail', error: j.detail })))
      .catch(e => resolve({ status: 'fail', error: e.message }))
  })
}
async function installZip() {
  const ok = zipFile.value.some(f => f.status === 'success')
  if (!ok) return MessagePlugin.warning('请先成功上传 zip')
  MessagePlugin.success('安装成功'); zipOpen.value = false; loadSkills()
}

/* ---------------- MCP ---------------- */
const servers = ref([])
const loadingServers = ref(false)
const serverCols = [
  { colKey: 'name', title: '名称', width: 140 },
  { colKey: 'status', title: '状态', width: 110 },
  { colKey: 'target', title: '命令 / URL', ellipsis: true },
  { colKey: 'tools', title: '工具', width: 80 },
  { colKey: 'op', title: '操作', width: 200 },
]
function statusTheme(s) { return s === 'connected' ? 'success' : s === 'error' ? 'danger' : s === 'connecting' ? 'warning' : 'default' }
function statusIcon(s) { return s === 'connected' ? 'check-circle' : s === 'error' ? 'close-circle' : s === 'connecting' ? 'loading' : 'minus-circle' }
function statusText(s) { return { connected:'已连接', error:'错误', connecting:'连接中', disconnected:'未连接' }[s] || s }

// 展开行：显示工具列表 + 测试调用
function serverExpanded(row) {
  if (!row.tools?.length) return h('div', { class: 'muted', style: 'padding:8px 16px' }, row.status === 'connected' ? '该服务器未提供工具' : '连接后显示工具列表')
  return h('div', { style: 'padding:8px 16px' },
    row.tools.map(t => h('div', { style: 'display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid var(--td-component-stroke)' }, [
      h('span', { style: 'font-weight:500;min-width:160px' }, t.name),
      h('span', { style: 'flex:1;color:var(--td-text-color-secondary);font-size:12px' }, t.description),
      h(TButton, { size: 'small', variant: 'text', theme: 'primary', onClick: () => openInvoke(row, t) }, () => '测试调用'),
    ]))
  )
}

const serverOpen = ref(false)
const serverForm = ref({})
const invokeOpen = ref(false)
const invokeTool = ref({})
const invokeServer = ref(null)
const invokeArgs = ref('{}')
const invokeResult = ref(null)
const invoking = ref(false)

async function loadServers() {
  loadingServers.value = true
  try { servers.value = await api.get('/api/mcp/servers') }
  catch (e) { MessagePlugin.error(e.message) }
  finally { loadingServers.value = false }
}
function openServerDlg(row) {
  serverForm.value = row
    ? { ...row, argsText: (row.args || []).join('\n') }
    : { transport: 'stdio', enabled: true, auto_connect: true, argsText: '' }
  serverOpen.value = true
}
async function saveServer() {
  const f = serverForm.value
  if (!f.name?.trim()) return MessagePlugin.warning('请填写名称')
  const body = {
    name: f.name, transport: f.transport, command: f.command || '', url: f.url || '',
    args: (f.argsText || '').split('\n').map(s => s.trim()).filter(Boolean),
    enabled: !!f.enabled, auto_connect: !!f.auto_connect,
  }
  try {
    if (f.id) await api.put(`/api/mcp/servers/${f.id}`, body)
    else await api.post('/api/mcp/servers', body)
    MessagePlugin.success('已保存'); serverOpen.value = false; loadServers()
  } catch (e) { MessagePlugin.error(e.message) }
}
async function connect(row) {
  row._busy = true
  try {
    const r = await api.post(`/api/mcp/servers/${row.id}/connect`)
    if (r.ok) MessagePlugin.success(`已连接，发现 ${r.tools.length} 个工具`)
    else MessagePlugin.error(r.error || '连接失败')
  } catch (e) { MessagePlugin.error(e.message) }
  finally { row._busy = false; loadServers() }
}
async function disconnect(row) {
  try { await api.post(`/api/mcp/servers/${row.id}/disconnect`); loadServers() }
  catch (e) { MessagePlugin.error(e.message) }
}
async function removeServer(id) {
  try { await api.del(`/api/mcp/servers/${id}`); MessagePlugin.success('已删除'); loadServers() }
  catch (e) { MessagePlugin.error(e.message) }
}
function openInvoke(row, tool) {
  invokeServer.value = row; invokeTool.value = tool
  const props = tool.inputSchema?.properties || {}
  const sample = Object.fromEntries(Object.entries(props).map(([k, v]) => [k, v.type === 'integer' || v.type === 'number' ? 0 : '']))
  invokeArgs.value = JSON.stringify(sample, null, 2)
  invokeResult.value = null; invokeOpen.value = true
}
async function doInvoke() {
  let args
  try { args = JSON.parse(invokeArgs.value || '{}') }
  catch { return MessagePlugin.error('参数不是合法 JSON') }
  invoking.value = true
  try {
    const r = await api.post(`/api/mcp/servers/${invokeServer.value.id}/tools/${invokeTool.value.name}/invoke`, { args })
    invokeResult.value = r.ok ? r.result : ('错误：' + r.error)
  } catch (e) { invokeResult.value = '错误：' + e.message }
  finally { invoking.value = false }
}

onMounted(() => { loadSkills(); loadServers() })
</script>

<style scoped>
.panel-pad { padding: 16px 0; }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
.md-preview { white-space: pre-wrap; font-family: inherit; line-height: 1.7; max-height: 60vh; overflow-y: auto; }
.invoke-result { margin-top: 12px; }
.invoke-result pre { white-space: pre-wrap; background: var(--td-bg-color-page); padding: 10px; border-radius: var(--td-radius-medium); max-height: 240px; overflow-y: auto; }
</style>
