<template>
  <header class="page-topbar" :class="{ sticky }">
    <t-button v-if="backTo != null" variant="text" size="small" class="topbar-back" @click="goBack">
      <t-icon name="chevron-left" /> {{ backLabel }}
    </t-button>
    <h1 class="page-topbar-title">
      <t-icon v-if="icon" :name="icon" class="topbar-icon" />
      <slot name="title">{{ title }}</slot>
    </h1>
    <div class="spacer"></div>
    <div v-if="$slots.actions" class="topbar-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
import { useRouter } from 'vue-router'

const props = defineProps({
  title: { type: String, default: '' },
  icon: { type: String, default: '' },
  backTo: { type: [String, Object], default: null },
  backLabel: { type: String, default: '返回' },
  sticky: { type: Boolean, default: false },
})

const router = useRouter()

function goBack() {
  if (props.backTo === '/') router.push('/')
  else if (typeof props.backTo === 'string') router.push(props.backTo)
  else router.back()
}
</script>
