<template>
  <t-dialog
    v-model:visible="visible"
    header="关闭应用"
    :footer="false"
    :close-on-overlay-click="false"
    :close-btn="false"
    width="420px"
  >
    <p>点击关闭按钮时，你希望如何操作？</p>
    <p class="muted tip">最小化后窗口会缩到任务栏，整本创作等后台任务仍会继续运行。</p>
    <t-checkbox v-model="remember" style="margin-top:12px">不再提醒，下次直接执行所选操作</t-checkbox>
    <div class="actions">
      <t-button variant="outline" @click="choose('minimize')">
        <t-icon name="minus-rectangle" /> 最小化
      </t-button>
      <t-button theme="danger" @click="choose('exit')">
        <t-icon name="poweroff" /> 退出程序
      </t-button>
    </div>
  </t-dialog>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const visible = ref(false)
const remember = ref(false)

function hasDesktopApi() {
  return typeof window !== 'undefined' && window.pywebview?.api?.apply_close_choice
}

function show() {
  if (!hasDesktopApi()) return
  remember.value = false
  visible.value = true
}

async function choose(action) {
  visible.value = false
  if (!hasDesktopApi()) return
  try {
    await window.pywebview.api.apply_close_choice(action, remember.value)
  } catch (_) { /* 浏览器模式忽略 */ }
}

onMounted(() => {
  window.__showCloseDialog = show
})

onUnmounted(() => {
  if (window.__showCloseDialog === show) delete window.__showCloseDialog
})
</script>

<style scoped>
.tip { font-size: 13px; margin-top: 8px; line-height: 1.6; }
.actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 20px; }
</style>
