<script setup lang="ts">
defineProps<{ small?: boolean }>()
</script>
<template>
  <span class="brand-mark" :class="{ small }" aria-hidden="true"
    ><svg viewBox="0 0 40 40" fill="none">
      <path
        d="M20 6c0 8-6 14-14 14 8 0 14 6 14 14 0-8 6-14 14-14-8 0-14-6-14-14Z"
        fill="currentColor"
      /></svg
  ></span>
</template>
