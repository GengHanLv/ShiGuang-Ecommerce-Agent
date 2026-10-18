<script setup lang="ts">
import { computed } from 'vue'
import {
  ChatLineRound,
  Collection,
  Setting,
  Plus,
  Top,
  Right,
  Search,
  Connection,
  Document,
  Refresh,
  Close,
  Check,
  CopyDocument,
  Delete,
  UploadFilled,
  ArrowLeft,
  MoreFilled,
  MagicStick,
  Box,
  Service,
  Clock,
  Switch,
  Warning,
  FolderOpened,
  Lightning,
  Menu,
  ArrowRight,
  Lock,
  CircleCheck,
  InfoFilled,
} from '@element-plus/icons-vue'
const icons = {
  ChatLineRound,
  Collection,
  Setting,
  Plus,
  Top,
  Right,
  Search,
  Connection,
  Document,
  Refresh,
  Close,
  Check,
  CopyDocument,
  Delete,
  UploadFilled,
  ArrowLeft,
  MoreFilled,
  MagicStick,
  Box,
  Service,
  Clock,
  Switch,
  Warning,
  FolderOpened,
  Lightning,
  Menu,
  ArrowRight,
  Lock,
  CircleCheck,
  InfoFilled,
}
const props = defineProps<{
  name: keyof typeof icons
  size?: number | string
}>()
const icon = computed(() => icons[props.name])
</script>
<template>
  <span
    class="app-icon"
    :style="{ width: (size || 20) + 'px', height: (size || 20) + 'px' }"
    aria-hidden="true"
    ><component :is="icon"
  /></span>
</template>
<style scoped>
.app-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  vertical-align: middle;
}
.app-icon svg {
  width: 100%;
  height: 100%;
}
</style>
