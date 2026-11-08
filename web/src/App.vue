<script setup>
</script>

<template>
  <header class="app-header">
    <h1>灵枢 NeuroAxis</h1>
    <p class="subtitle">工艺描述到可运行 PLC 程序</p>
  </header>
  <main>
    <router-view />
  </main>
</template>

<style>
body { font-family: system-ui, sans-serif; margin: 0; background: #f5f6f8; }
.app-header { padding: 16px 24px; background: #1a2a44; color: #fff; }
.app-header h1 { margin: 0; font-size: 20px; }
.subtitle { margin: 4px 0 0; font-size: 13px; opacity: 0.8; }
main { max-width: 960px; margin: 24px auto; padding: 0 16px; }
</style>
