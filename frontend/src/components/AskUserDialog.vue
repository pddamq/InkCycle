<template>
  <t-dialog v-model:visible="open" header="Agent 需要你确认" :footer="false" width="480px" @close="$emit('cancel')">
    <p class="ask-q">{{ question?.question }}</p>
    <div v-if="question?.options?.length" class="ask-opts">
      <t-button v-for="(o,i) in question.options" :key="i" block variant="outline"
        class="opt-btn" @click="answer(o)">{{ o }}</t-button>
    </div>
    <t-textarea v-if="question?.allow_custom !== false" v-model="custom" placeholder="或输入自定义回答…"
      :autosize="{ minRows: 2, maxRows: 4 }" />
    <div class="ask-actions">
      <t-button variant="text" @click="$emit('cancel')">稍后</t-button>
      <t-button theme="primary" :disabled="!custom.trim() && !question?.options?.length" @click="answer(custom.trim())">
        提交
      </t-button>
    </div>
  </t-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  question: { type: Object, default: null },
})

const emit = defineEmits(['answer', 'cancel'])
const open = ref(false)
const custom = ref('')

watch(() => props.question, (q) => {
  open.value = !!q
  custom.value = ''
}, { immediate: true })

function answer(text) {
  if (!text) return
  emit('answer', text)
  open.value = false
}
</script>

<style scoped>
.ask-q { font-size: 15px; line-height: 1.6; margin-bottom: 16px; }
.ask-opts { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.opt-btn { justify-content: flex-start; text-align: left; }
.ask-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
</style>
