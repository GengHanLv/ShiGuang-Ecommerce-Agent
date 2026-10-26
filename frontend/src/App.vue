<script setup lang="ts">
import { ElConfigProvider } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import WorkspaceLayout from '@/layouts/WorkspaceLayout.vue'
import LoginView from '@/views/LoginView.vue'
import { useAuthStore } from '@/stores/auth'
import { onMounted } from 'vue'
const auth = useAuthStore()
onMounted(auth.refresh)
</script>
<template>
  <el-config-provider :locale="zhCn">
    <div v-if="!auth.ready" class="auth-loading">正在读取登录状态…</div>
    <LoginView v-else-if="!auth.user" />
    <WorkspaceLayout v-else :key="auth.user.id" />
  </el-config-provider>
</template>
