<template>
  <div class="app-shell">
    <GenerationBanner />
    <router-view />
  </div>
  <CloseAppDialog />
</template>

<script setup>
import CloseAppDialog from './components/CloseAppDialog.vue'
import GenerationBanner from './components/GenerationBanner.vue'
</script>

<style>
.app-shell { display: flex; flex-direction: column; min-height: 100vh; }
.app-shell > :nth-child(2) { flex: 1; min-height: 0; }
</style>
