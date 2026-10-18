<script setup lang="ts">
import { ElConfigProvider } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import WorkspaceLayout from '@/layouts/WorkspaceLayout.vue'
</script>
<template>
  <el-config-provider :locale="zhCn"><WorkspaceLayout /></el-config-provider>
</template>
