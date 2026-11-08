<script setup>
import { onMounted, ref } from "vue";
import { getHealth, getInfra, postVerify } from "../api/neuroaxis";

const health = ref(null);
const infra = ref(null);
const verifyResult = ref(null);
const busy = ref(false);
const errorMsg = ref("");

async function refreshInfra() {
  errorMsg.value = "";
  try {
    infra.value = await getInfra();
  } catch (err) {
    errorMsg.value = err.detail || err.error || "加载失败";
  }
}

async function runVerify() {
  busy.value = true;
  errorMsg.value = "";
  try {
    verifyResult.value = await postVerify(50);
  } catch (err) {
    errorMsg.value = err.detail || err.error || "验证失败";
  } finally {
    busy.value = false;
  }
}

onMounted(async () => {
  try {
    health.value = await getHealth();
  } catch {
    health.value = { status: "unreachable", version: "-" };
  }
  await refreshInfra();
});
</script>

<template>
  <section class="card">
    <h2>服务状态</h2>
    <p v-if="health">后端 {{ health.status }} · v{{ health.version }}</p>
    <p v-else>加载中…</p>
    <p v-if="errorMsg" class="error">{{ errorMsg }}</p>
  </section>

  <section class="card" v-if="infra">
    <h2>基础设施</h2>
    <ul>
      <li v-for="(svc, name) in infra" :key="name">
        <span :class="svc.ok ? 'ok' : 'fail'">{{ svc.ok ? "PASS" : "FAIL" }}</span>
        {{ name }} — {{ svc.detail }}
      </li>
    </ul>
    <button @click="refreshInfra">刷新</button>
  </section>

  <section class="card">
    <h2>确定性验证</h2>
    <button :disabled="busy" @click="runVerify">
      {{ busy ? "运行中…" : "运行 50 次" }}
    </button>
    <p v-if="verifyResult">
      {{ verifyResult.ok ? "PASS" : "FAIL" }} · SHA256
      {{ verifyResult.digest.slice(0, 16) }}… · {{ verifyResult.runs }} 次
    </p>
  </section>
</template>

<style scoped>
.card { background: #fff; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.card h2 { margin: 0 0 12px; font-size: 16px; }
.ok { color: #188038; font-weight: 600; }
.fail { color: #c5221f; font-weight: 600; }
.error { color: #c5221f; }
button { padding: 6px 16px; border: none; border-radius: 6px; background: #1a2a44;
         color: #fff; cursor: pointer; }
button:disabled { opacity: 0.5; cursor: default; }
</style>
